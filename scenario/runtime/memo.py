#!/usr/bin/env python3

import base64
import dataclasses
import datetime as DT
import functools
import inspect
import io
import json
import os
import pickle
import typing
import warnings
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Literal, Tuple, Union, Sequence
from uuid import uuid4

from scenario.logger import logger as pkg_logger

logger = pkg_logger.getChild("recorder")

DEFAULT_DB_NAME = "event_db.json"
USE_STATE_KEY = "MEMO_REPLAY_IDX"
MEMO_REPLAY_INDEX_KEY = "MEMO_REPLAY_IDX"
MEMO_DATABASE_NAME_KEY = "MEMO_DATABASE_NAME"
MEMO_MODE_KEY = "MEMO_MODE"
DEFAULT_NAMESPACE = "<DEFAULT>"

# fixme: generalize the serializer by allowing to pass in a (pickled?) arbitrary callable.
#  right now we have this PebblePush nonsense because that's the only special case.

SUPPORTED_SERIALIZERS = Literal["pickle", "json", "io", "PebblePush"]
SUPPORTED_SERIALIZERS_LIST = ["pickle", "json", "io", "PebblePush"]


MemoModes = Literal["passthrough", "record", "replay", "isolated"]
_CachingPolicy = Literal["strict", "loose"]

# notify just once of what mode we're running in
_PRINTED_MODE = False

# flag to mark when a memo cache's return value is not found as opposed to being None
_NotFound = object()


class NotFoundError(RuntimeError):
    pass


def _check_caching_policy(policy: _CachingPolicy) -> _CachingPolicy:
    if policy in {"strict", "loose"}:
        return policy
    else:
        logger.warning(
            f"invalid caching policy: {policy!r}. " f"defaulting to `strict`"
        )
    return "strict"


def _load_memo_mode() -> MemoModes:
    global _PRINTED_MODE

    val = os.getenv(MEMO_MODE_KEY, "record")
    if val == "passthrough":
        # avoid doing anything at all with passthrough, to save time.
        pass
    if val == "record":
        # don't use logger, but print, to avoid recursion issues with juju-log.
        if not _PRINTED_MODE:
            print("MEMO: recording")
    elif val == "replay":
        if not _PRINTED_MODE:
            print("MEMO: replaying")
    elif val == "isolated":
        if not _PRINTED_MODE:
            print("MEMO: replaying (isolated mode)")
    else:
        warnings.warn(
            f"[ERROR]: MEMO: invalid value ({val!r}). Defaulting to `record`."
        )
        _PRINTED_MODE = True
        return "record"

    _PRINTED_MODE = True
    return typing.cast(MemoModes, val)


def _is_bound_method(fn: Any):
    try:
        return next(iter(inspect.signature(fn).parameters.items()))[0] == "self"
    except:
        return False


def _call_repr(
    fn: Callable,
    args,
    kwargs,
):
    """Str repr of memoized function call address."""
    fn_name = getattr(fn, "__name__", str(fn))
    if _self := getattr(fn, "__self__", None):
        # it's a method
        fn_repr = type(_self).__name__ + fn_name
    else:
        fn_repr = fn_name
    return f"{fn_repr}(*{args}, **{kwargs})"


def _log_memo(
    fn: Callable,
    args,
    kwargs,
    recorded_output: Any = None,
    cache_hit: bool = False,
    # use print, not logger calls, else the root logger will recurse if
    # juju-log calls are being @memo'd.
    log_fn: Callable[[str], None] = print,
):
    try:
        output_repr = repr(recorded_output)
    except:  # noqa catchall
        output_repr = "<repr failed: cannot repr(memoized output).>"

    trim = output_repr[:100]
    trimmed = "[...]" if len(output_repr) > 100 else ""
    hit = "hit" if cache_hit else "miss"

    return log_fn(
        f"@memo[{hit}]: replaying {_call_repr(fn, args, kwargs)}"
        f"\n\t --> {trim}{trimmed}"
    )


def _check_serializer(
    serializer: Union[
        SUPPORTED_SERIALIZERS, Tuple[SUPPORTED_SERIALIZERS, SUPPORTED_SERIALIZERS]
    ]
) -> Tuple[SUPPORTED_SERIALIZERS, SUPPORTED_SERIALIZERS]:
    if isinstance(serializer, str):
        input_serializer = output_serializer = serializer
    else:
        input_serializer, output_serializer = serializer

    if input_serializer not in SUPPORTED_SERIALIZERS_LIST:
        warnings.warn(
            f"invalid input serializer name: {input_serializer}; "
            f"falling back to `json`."
        )
        input_serializer = "json"
    if output_serializer not in SUPPORTED_SERIALIZERS_LIST:
        warnings.warn(
            f"invalid output serializer name: {input_serializer}; "
            f"falling back to `json`."
        )
        output_serializer = "json"

    return input_serializer, output_serializer


def memo(
    namespace: str = DEFAULT_NAMESPACE,
    name: str = None,
    caching_policy: _CachingPolicy = "strict",
    log_on_replay: bool = True,
    serializer: Union[
        SUPPORTED_SERIALIZERS, Tuple[SUPPORTED_SERIALIZERS, SUPPORTED_SERIALIZERS]
    ] = "json",
):
    f"""This decorator wraps a callable and memoizes its calls.

    Based on the value of the {MEMO_MODE_KEY!r} environment variable, it can work in multiple ways:

    - "passthrough": does nothing. As if the decorator wasn't there. Useful as production default,
        to minimize the runtime impact of memo.
    - "record": each function call gets intercepted, and the [arguments -> return value] mapping is
        stored in a database, using `namespace`.`name` as key. The `serializers` arg tells how the args/kwargs and
        return value should be serialized, respectively.
        Useful for populating a database for replaying/testing purposes.
    - "isolated": each function call gets intercepted, and instead of propagating the call to the wrapped function,
        the database is searched for a matching argument set. If one is found, the stored return value is
        deserialized and returned. If none is found, a RuntimeError is raised.
        Useful for replaying in local environments, where propagating the call would result in errors further down.
    - "replay": like "isolated", but in case of a cache miss, the call is propagated to the wrapped function
        (the database is NOT implicitly updated).
        Useful for replaying in 'live' environments where propagating the call would get you the right result.

    `caching_policy` can be either:
    - "strict": each function call is stored individually and in an ordered sequence. Useful for when a
        function can return different values when called on distinct occasions.
    - "loose": the arguments -> return value mapping is stored as a mapping. Assumes that same
        arguments == same return value.
    """

    def decorator(fn):
        if not inspect.isfunction(fn):
            raise RuntimeError(f"Cannot memoize non-function obj {fn!r}.")

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):

            _MEMO_MODE: MemoModes = _load_memo_mode()

            def propagate():
                """Make the real wrapped call."""
                if _MEMO_MODE == "isolated":
                    raise RuntimeError(
                        f"Attempted propagation in isolated mode: "
                        f"{_call_repr(fn, args, kwargs)}"
                    )

                if _MEMO_MODE == "replay" and log_on_replay:
                    _log_memo(fn, args, kwargs, "<propagated>", cache_hit=False)

                # todo: if we are replaying, should we be caching this result?
                return fn(*args, **kwargs)

            if _MEMO_MODE == "passthrough":
                return propagate()

            input_serializer, output_serializer = _check_serializer(serializer)

            def _load(obj: str, method: SUPPORTED_SERIALIZERS):
                if log_on_replay and _MEMO_MODE in ["replay", "isolated"]:
                    _log_memo(fn, args, kwargs, recorded_output, cache_hit=True)
                if method == "pickle":
                    byt = base64.b64decode(obj)
                    return pickle.loads(byt)
                elif method == "json":
                    return json.loads(obj)
                elif method == "io":
                    byt = base64.b64decode(obj)
                    raw = pickle.loads(byt)
                    byio = io.StringIO(raw)
                    return byio
                raise ValueError(f"Invalid method: {method!r}")

            def _dump(obj: Any, method: SUPPORTED_SERIALIZERS, output_=None):
                if method == "pickle":
                    if isinstance(obj, io.TextIOWrapper):
                        pass
                    byt = pickle.dumps(obj)
                    return base64.b64encode(byt).decode("utf-8")
                elif method == "json":
                    return json.dumps(obj)
                elif method == "PebblePush":
                    _args, _kwargs = obj
                    assert len(_args) == 2
                    path, source = _args
                    # pebble._Client.push's second argument:
                    #  source: Union[bytes, str, BinaryIO, TextIO]

                    if isinstance(source, (bytes, str)):
                        source_ = pickle.dumps(source)
                        return _dump(((path, source_), _kwargs), "pickle")
                    else:  # AnyIO:
                        if not output_:
                            if _MEMO_MODE == "record":
                                raise ValueError(
                                    "we serialize AnyIO by just caching the contents. "
                                    "Output required."
                                )
                            # attempt to obtain it by reading the obj
                            try:
                                output_ = source.read()
                            except Exception as e:
                                raise RuntimeError(
                                    f"Cannot read source: {source}; unable to compare to cache"
                                ) from e
                        return _dump(((path, output_), _kwargs), "pickle")

                elif method == "io":
                    if not hasattr(obj, "read"):
                        raise TypeError(
                            "you can only serialize with `io` "
                            "stuff that has a .read method."
                        )
                    byt = pickle.dumps(obj.read())
                    return base64.b64encode(byt).decode("utf-8")
                raise ValueError(f"Invalid method: {method!r}")

            def load_from_state(
                scene: Scene, question: Tuple[str, Tuple[Any], Dict[str, Any]]
            ):
                if not os.getenv(USE_STATE_KEY):
                    return propagate()

                logger.debug("Attempting to load from state.")
                if not hasattr(scene.context, "state"):
                    logger.warning(
                        "Context has no state; probably there is a version mismatch."
                    )
                    return propagate()

                if not scene.context.state:
                    logger.debug("No state found for this call.")
                    return propagate()

                try:
                    return get_from_state(scene, question)
                except StateError as e:
                    logger.error(f"Error trying to get_from_state {memo_name}: {e}")
                    return propagate()

            memoizable_args = args
            if args:
                if _is_bound_method(fn):
                    # which means args[0] is `self`
                    memoizable_args = args[1:]
                else:
                    memoizable_args = args

            # convert args to list for comparison purposes because memos are
            # loaded from json, where tuples become lists.
            memo_args = list(memoizable_args)

            database = os.environ.get(MEMO_DATABASE_NAME_KEY, DEFAULT_DB_NAME)
            if not Path(database).exists():
                raise RuntimeError(
                    f"Database not found at {database}. "
                    f"@memo requires a scene to be set."
                )

            with event_db(database) as data:
                idx = os.environ.get(MEMO_REPLAY_INDEX_KEY, None)

                strict_caching = _check_caching_policy(caching_policy) == "strict"

                memo_name = f"{namespace}.{name or fn.__name__}"

                if _MEMO_MODE == "record":
                    memo = data.scenes[-1].context.memos.get(memo_name)
                    if memo is None:
                        cpolicy_name = typing.cast(
                            _CachingPolicy, "strict" if strict_caching else "loose"
                        )
                        memo = Memo(
                            caching_policy=cpolicy_name,
                            serializer=(input_serializer, output_serializer),
                        )

                    output = propagate()

                    # we can't hash dicts, so we dump args and kwargs
                    # regardless of what they are
                    serialized_args_kwargs = _dump(
                        (memo_args, kwargs), input_serializer, output_=output
                    )
                    serialized_output = _dump(output, output_serializer)

                    memo.cache_call(serialized_args_kwargs, serialized_output)
                    data.scenes[-1].context.memos[memo_name] = memo

                    # if we're in IO mode, output might be a file handle and
                    # serialized_output might be the b64encoded, pickle repr of its contents.
                    # We need to mock a file-like stream to return.
                    if output_serializer == "io":
                        return _load(serialized_output, "io")
                    return output

                elif _MEMO_MODE in ["replay", "isolated"]:
                    if idx is None:
                        raise RuntimeError(
                            f"provide a {MEMO_REPLAY_INDEX_KEY} envvar"
                            "to tell the replay environ which scene to look at"
                        )
                    try:
                        idx = int(idx)
                    except TypeError:
                        raise RuntimeError(
                            f"invalid idx: ({idx}); expecting an integer."
                        )

                    try:
                        memo = data.scenes[idx].context.memos[memo_name]

                    except KeyError:
                        # if no memo is present for this function, that might mean that
                        # in the recorded session it was not called (this path is new!)
                        warnings.warn(
                            f"No memo found for {memo_name}: " f"this path must be new."
                        )
                        return load_from_state(
                            data.scenes[idx],
                            (memo_name, memoizable_args, kwargs),
                        )

                    if not all(
                        (
                            memo.caching_policy == caching_policy,
                            # loading from yaml makes it a list
                            (
                                (
                                    memo.serializer
                                    == [input_serializer, output_serializer]
                                )
                                or (
                                    memo.serializer
                                    == (input_serializer, output_serializer)
                                )
                            ),
                        )
                    ):
                        warnings.warn(
                            f"Stored memo params differ from those passed to @memo at runtime. "
                            f"The database must have been generated by an outdated version of "
                            f"memo-tools. Falling back to stored memo: \n "
                            f"\tpolicy: {memo.caching_policy} (vs {caching_policy!r}), \n"
                            f"\tserializer: {memo.serializer} "
                            f"(vs {(input_serializer, output_serializer)!r})..."
                        )
                        strict_caching = (
                            _check_caching_policy(memo.caching_policy) == "strict"
                        )
                        input_serializer, output_serializer = _check_serializer(
                            memo.serializer
                        )

                    # we serialize args and kwargs to compare them with the memo'd ones
                    fn_args_kwargs = _dump((memo_args, kwargs), input_serializer)

                    if strict_caching:
                        # in strict mode, fn might return different results every time it is called --
                        # regardless of the arguments it is called with. So each memo contains a sequence of values,
                        # and a cursor to keep track of which one is next in the replay routine.
                        try:
                            current_cursor = memo.cursor
                            recording = memo.calls[current_cursor]
                            memo.cursor += 1
                        except IndexError:
                            # There is a memo, but its cursor is out of bounds.
                            # this means the current path is calling the wrapped function
                            # more times than the recorded path did.
                            # if this happens while replaying locally, of course, game over.
                            warnings.warn(
                                f"Memo cursor {current_cursor} out of bounds for {memo_name}: "
                                f"this path must have diverged. Propagating call..."
                            )
                            return load_from_state(
                                data.scenes[idx],
                                (memo_name, memoizable_args, kwargs),
                            )

                        recorded_args_kwargs, recorded_output = recording

                        if recorded_args_kwargs != fn_args_kwargs:
                            # if this happens while replaying locally, of course, game over.
                            warnings.warn(
                                f"memoized {memo_name} arguments ({recorded_args_kwargs}) "
                                f"don't match the ones received at runtime ({fn_args_kwargs}). "
                                f"This path has diverged. Propagating call..."
                            )
                            return load_from_state(
                                data.scenes[idx],
                                (memo_name, memoizable_args, kwargs),
                            )

                        return _load(
                            recorded_output, output_serializer
                        )  # happy path! good for you, path.

                    else:
                        # in non-strict mode, we don't care about the order in which fn is called:
                        #  it will return values in function of the arguments it is called with,
                        #  regardless of when it is called.
                        # so all we have to check is whether the arguments are known.
                        #  in non-strict mode, memo.calls is an inputs/output dict.
                        recorded_output = memo.calls.get(fn_args_kwargs, _NotFound)
                        if recorded_output is not _NotFound:
                            return _load(
                                recorded_output, output_serializer
                            )  # happy path! good for you, path.

                        warnings.warn(
                            f"No memo for {memo_name} matches the arguments received at runtime. "
                            f"This path has diverged."
                        )
                        return load_from_state(
                            data.scenes[idx],
                            (memo_name, memoizable_args, kwargs),
                        )

                else:
                    msg = f"invalid memo mode: {_MEMO_MODE}"
                    warnings.warn(msg)
                    raise ValueError(msg)

            raise RuntimeError("Unhandled memo path.")

        return wrapper

    return decorator


class DB:
    def __init__(self, file: Path) -> None:
        self._file = file
        self.data = None

    def load(self):
        text = self._file.read_text()
        if not text:
            logger.debug("database empty; initializing with data=[]")
            self.data = Data([])
            return

        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            raise ValueError(f"database invalid: could not json-decode {self._file}")

        try:
            scenes = [Scene.from_dict(obj) for obj in raw.get("scenes", ())]
        except Exception as e:
            raise RuntimeError(
                f"database invalid: could not parse Scenes from {raw['scenes']!r}..."
            ) from e

        self.data = Data(scenes)

    def commit(self):
        self._file.write_text(json.dumps(asdict(self.data), indent=2))


@dataclass
class Event:
    env: Dict[str, str]
    timestamp: str = dataclasses.field(
        default_factory=lambda: DT.datetime.now().isoformat()
    )

    @property
    def name(self):
        return self.env["JUJU_DISPATCH_PATH"].split("/")[1]

    @property
    def unit_name(self):
        return self.env.get("JUJU_UNIT_NAME", "")

    @property
    def app_name(self):
        unit_name = self.unit_name
        return unit_name.split("/")[0] if unit_name else ""

    @property
    def datetime(self):
        return DT.datetime.fromisoformat(self.timestamp)


@dataclass
class Memo:
    # todo clean this up by subclassing out to two separate StrictMemo and LooseMemo objects.
    # list of (args, kwargs), return-value pairs for this memo
    # warning: in reality it's all lists, no tuples.
    calls: Union[
        List[Tuple[str, Any]],  # if caching_policy == 'strict'
        Dict[str, Any],  # if caching_policy == 'loose'
    ] = field(default_factory=list)
    # indicates the position of the replay cursor if we're replaying the memo
    cursor: Union[
        int,  # if caching_policy == 'strict'
        Literal["n/a"],  # if caching_policy == 'loose'
    ] = 0
    caching_policy: _CachingPolicy = "strict"
    serializer: Union[
        SUPPORTED_SERIALIZERS, Tuple[SUPPORTED_SERIALIZERS, SUPPORTED_SERIALIZERS]
    ] = "json"

    def __post_init__(self):
        if self.caching_policy == "loose" and not self.calls:  # first time only!
            self.calls = {}
            self.cursor = "n/a"

    def cache_call(self, input: str, output: str):
        assert isinstance(input, str), input
        assert isinstance(output, str), output

        if self.caching_policy == "loose":
            self.calls[input] = output
        else:
            self.calls.append((input, output))


def _random_model_name():
    import random
    import string

    space = string.ascii_letters + string.digits
    return "".join(random.choice(space) for _ in range(20))


@dataclass
class Model:
    name: str = _random_model_name()
    uuid: str = str(uuid4())


@dataclass
class ContainerSpec:
    name: str
    can_connect: bool = False
    # todo mock filesystem and pebble proc?

    @classmethod
    def from_dict(cls, obj):
        return cls(**obj)


@dataclass
class Address:
    hostname: str
    value: str
    cidr: str


@dataclass
class BindAddress:
    mac_address: str
    interface_name: str
    interfacename: str  # legacy
    addresses: List[Address]


@dataclass
class Network:
    bind_addresses: List[BindAddress]
    bind_address: str
    egress_subnets: List[str]
    ingress_addresses: List[str]


@dataclass
class NetworkSpec:
    name: str
    bind_id: int
    network: Network
    is_default: bool = False

    @classmethod
    def from_dict(cls, obj):
        return cls(**obj)


@dataclass
class RelationMeta:
    endpoint: str
    interface: str
    relation_id: int
    remote_app_name: str
    remote_unit_ids: List[int] = field(default_factory=lambda: list((0,)))

    # local limit
    limit: int = 1

    # scale of the remote application; number of units, leader ID?
    # TODO figure out if this is relevant
    scale: int = 1
    leader_id: int = 0

    @classmethod
    def from_dict(cls, obj):
        return cls(**obj)


@dataclass
class RelationSpec:
    meta: RelationMeta
    local_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    remote_app_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    local_unit_data: Dict[str, str] = dataclasses.field(default_factory=dict)
    remote_units_data: Dict[int, Dict[str, str]] = dataclasses.field(default_factory=dict)

    @classmethod
    def from_dict(cls, obj):
        meta = RelationMeta.from_dict(obj.pop("meta"))
        return cls(meta=meta, **obj)

    @property
    def changed(self):
        """Sugar to generate a <this relation>-changed event."""
        from scenario import structs
        return structs.Event(self.meta.endpoint + '-changed',
                             meta=structs.EventMeta(relation=self.meta))

    @property
    def joined(self):
        """Sugar to generate a <this relation>-joined event."""
        from scenario import structs
        return structs.Event(self.meta.endpoint + '-joined',
                             meta=structs.EventMeta(relation=self.meta))

    @property
    def created(self):
        """Sugar to generate a <this relation>-created event."""
        from scenario import structs
        return structs.Event(self.meta.endpoint + '-created',
                             meta=structs.EventMeta(relation=self.meta))

    @property
    def departed(self):
        """Sugar to generate a <this relation>-departed event."""
        from scenario import structs
        return structs.Event(self.meta.endpoint + '-departed',
                             meta=structs.EventMeta(relation=self.meta))

    @property
    def removed(self):
        """Sugar to generate a <this relation>-removed event."""
        from scenario import structs
        return structs.Event(self.meta.endpoint + '-removed',
                             meta=structs.EventMeta(relation=self.meta))


@dataclass
class Status:
    app: Tuple[str, str] = ("unknown", "")
    unit: Tuple[str, str] = ("unknown", "")
    app_version: str = ""

    @classmethod
    def from_dict(cls, obj: dict):
        if obj is None:
            return cls()

        return cls(
            app=tuple(obj.get("app", ("unknown", ""))),
            unit=tuple(obj.get("unit", ("unknown", ""))),
            app_version=obj.get("app_version", ""),
        )


@dataclass
class State:
    config: Dict[str, Union[str, int, float, bool]] = None
    relations: Sequence[RelationSpec] = field(default_factory=list)
    networks: Sequence[NetworkSpec] = field(default_factory=list)
    containers: Sequence[ContainerSpec] = field(default_factory=list)
    status: Status = field(default_factory=Status)
    leader: bool = False
    model: Model = Model()
    juju_log: Sequence[Tuple[str, str]] = field(default_factory=list)

    # todo: add pebble stuff, unit/app status, etc...
    #  actions?
    #  juju topology

    @classmethod
    def from_dict(cls, obj):
        if obj is None:
            return cls()

        return cls(
            config=obj["config"],
            relations=list(
                RelationSpec.from_dict(raw_ard) for raw_ard in obj["relations"]
            ),
            networks=list(NetworkSpec.from_dict(raw_ns) for raw_ns in obj["networks"]),
            containers=list(
                ContainerSpec.from_dict(raw_cs) for raw_cs in obj["containers"]
            ),
            leader=obj.get("leader", False),
            status=Status.from_dict(obj.get("status")),
            model=Model(**obj.get("model", {})),
        )

    def get_container(self, name) -> ContainerSpec:
        try:
            return next(filter(lambda c: c.name == name, self.containers))
        except StopIteration as e:
            raise NotFoundError(f"container: {name}") from e


@dataclass
class Context:
    memos: Dict[str, Memo] = field(default_factory=dict)
    state: State = None

    @staticmethod
    def from_dict(obj: dict):
        return Context(
            memos={name: Memo(**content) for name, content in obj["memos"].items()},
            state=State.from_dict(obj.get("state")),
        )


@dataclass
class Scene:
    event: Event
    context: Context = Context()

    @staticmethod
    def from_dict(obj):
        return Scene(
            event=Event(**obj["event"]),
            context=Context.from_dict(obj.get("context", {})),
        )


@dataclass
class Data:
    scenes: List[Scene]


@contextmanager
def event_db(file=DEFAULT_DB_NAME) -> Generator[Data, None, None]:
    path = Path(file)
    if not path.exists():
        print(f"Initializing DB file at {path}...")
        path.touch(mode=0o666)
        path.write_text("{}")  # empty json obj

    db = DB(file=path)
    db.load()
    yield db.data
    db.commit()


def _capture() -> Event:
    return Event(env=dict(os.environ), timestamp=DT.datetime.now().isoformat())


def _reset_replay_cursors(file=DEFAULT_DB_NAME, *scene_idx: int):
    """Reset the replay cursor for all scenes, or the specified ones."""
    with event_db(file) as data:
        to_reset = (data.scenes[idx] for idx in scene_idx) if scene_idx else data.scenes
        for scene in to_reset:
            for memo in scene.context.memos.values():
                memo.cursor = 0


def _record_current_event(file) -> Event:
    with event_db(file) as data:
        scenes = data.scenes
        event = _capture()
        scenes.append(Scene(event=event))
    return event


def setup(file=DEFAULT_DB_NAME):
    _MEMO_MODE: MemoModes = _load_memo_mode()

    if _MEMO_MODE == "record":
        event = _record_current_event(file)
        print(f"Captured event: {event.name}.")

    if _MEMO_MODE in ["replay", "isolated"]:
        _reset_replay_cursors()
        print(f"Replaying: reset replay cursors.")


class StateError(RuntimeError):
    pass


class QuestionNotImplementedError(StateError):
    pass


def get_from_state(scene: Scene, question: Tuple[str, Tuple[Any], Dict[str, Any]]):
    state = scene.context.state
    this_unit_name = scene.event.unit_name
    memo_name, call_args, call_kwargs = question
    ns, _, meth = memo_name.rpartition(".")
    setter = False

    try:
        # MODEL BACKEND CALLS
        if ns == "_ModelBackend":
            if meth == "relation_get":
                rel_id, obj_name, app = call_args
                relation = next(
                    filter(lambda r: r.meta.relation_id == rel_id, state.relations)
                )
                if app and obj_name == scene.event.app_name:
                    return relation.local_app_data
                elif app:
                    return relation.remote_app_data
                elif obj_name == this_unit_name:
                    return relation.local_unit_data.get(this_unit_name, {})
                else:
                    unit_id = obj_name.split("/")[-1]
                    return relation.local_unit_data[unit_id]

            elif meth == "is_leader":
                return state.leader

            elif meth == "status_get":
                status, message = (
                    state.status.app if call_kwargs.get("app") else state.status.unit
                )
                return {"status": status, "message": message}

            elif meth == "relation_ids":
                return [rel.meta.relation_id for rel in state.relations]

            elif meth == "relation_list":
                rel_id = call_args[0]
                relation = next(
                    filter(lambda r: r.meta.relation_id == rel_id, state.relations)
                )
                return tuple(
                    f"{relation.meta.remote_app_name}/{unit_id}"
                    for unit_id in relation.meta.remote_unit_ids
                )

            elif meth == "config_get":
                return state.config[call_args[0]]

            elif meth == "action_get":
                pass

            elif meth == "relation_remote_app_name":
                pass

            elif meth == "resource_get":
                pass
            elif meth == "storage_list":
                pass
            elif meth == "storage_get":
                pass
            elif meth == "network_get":
                pass
            elif meth == "planned_units":
                pass
            else:
                setter = True

            # # setter methods

            if meth == "application_version_set":
                state.status.app_version = call_args[0]
                return None

            elif meth == "status_set":
                status = call_args
                if call_kwargs.get("is_app"):
                    state.status.app = status
                else:
                    state.status.unit = status
                return None

            elif meth == "juju_log":
                state.juju_log.append(call_args)
                return None

            elif meth == "relation_set":
                rel_id, key, value, app = call_args
                relation = next(
                    filter(lambda r: r.meta.relation_id == rel_id, state.relations)
                )
                if app:
                    if not state.leader:
                        raise RuntimeError("needs leadership to set app data")
                    tgt = relation.local_app_data
                else:
                    tgt = relation.local_unit_data
                tgt[key] = value
                return None

            elif meth == "action_set":
                pass
            elif meth == "action_fail":
                pass
            elif meth == "action_log":
                pass
            elif meth == "storage_add":
                pass

            # todo add
            #  'secret_get'
            #  'secret_set'
            #  'secret_grant'
            #  'secret_remove'

        # PEBBLE CALLS
        elif ns == "Client":
            if meth == "_request":
                if call_args == ("GET", "/v1/system-info"):
                    # fixme: can't differentiate between containers ATM, because Client._request
                    #  does not pass around the container name as argument
                    if state.containers[0].can_connect:
                        return {"result": {"version": "unknown"}}
                    else:
                        raise FileNotFoundError("")
            elif meth == "pull":
                pass
            elif meth == "push":
                setter = True
                pass

        else:
            raise QuestionNotImplementedError(ns)
    except Exception as e:
        action = "setting" if setter else "getting"
        msg = f"Error {action} state for {ns}.{meth} given ({call_args}, {call_kwargs})"
        logger.error(msg)
        raise StateError(msg) from e

    raise QuestionNotImplementedError((ns, meth))
