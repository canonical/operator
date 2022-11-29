import json
import os
import random
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scenario.runtime.memo import (
    DEFAULT_NAMESPACE,
    MEMO_DATABASE_NAME_KEY,
    MEMO_MODE_KEY,
    Context,
    Event,
    Memo,
    Scene,
    _reset_replay_cursors,
    event_db,
    memo,
)
from scenario.runtime.memo_tools import DecorateSpec, inject_memoizer, memo_import_block

# we always replay the last event in the default test env.
os.environ["MEMO_REPLAY_IDX"] = "-1"

mock_ops_source = """
import random

class _ModelBackend:
    def _private_method(self):
        pass
    def other_method(self):
        pass
    def action_set(self, *args, **kwargs):
        return str(random.random())
    def action_get(self, *args, **kwargs):
        return str(random.random())
        

class Foo:
    def bar(self, *args, **kwargs):
        return str(random.random())
    def baz(self, *args, **kwargs):
        return str(random.random())
"""

expected_decorated_source = f"""{memo_import_block}
import random

class _ModelBackend():

    def _private_method(self):
        pass

    def other_method(self):
        pass

    @memo(name=None, namespace='_ModelBackend', caching_policy='strict', serializer='json')
    def action_set(self, *args, **kwargs):
        return str(random.random())

    @memo(name=None, namespace='_ModelBackend', caching_policy='loose', serializer='pickle')
    def action_get(self, *args, **kwargs):
        return str(random.random())

class Foo():

    @memo(name=None, namespace='Bar', caching_policy='loose', serializer=('json', 'io'))
    def bar(self, *args, **kwargs):
        return str(random.random())

    def baz(self, *args, **kwargs):
        return str(random.random())
"""


def test_memoizer_injection():
    with tempfile.NamedTemporaryFile() as file:
        target_file = Path(file.name)
        target_file.write_text(mock_ops_source)

        inject_memoizer(
            target_file,
            decorate={
                "_ModelBackend": {
                    "action_set": DecorateSpec(),
                    "action_get": DecorateSpec(
                        caching_policy="loose", serializer="pickle"
                    ),
                },
                "Foo": {
                    "bar": DecorateSpec(
                        namespace="Bar",
                        caching_policy="loose",
                        serializer=("json", "io"),
                    )
                },
            },
        )

        assert target_file.read_text() == expected_decorated_source


def test_memoizer_recording():
    with tempfile.NamedTemporaryFile() as temp_db_file:
        Path(temp_db_file.name).write_text("{}")
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name

        @memo()
        def my_fn(*args, retval=None, **kwargs):
            return retval

        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        my_fn(10, retval=10, foo="bar")

        with event_db(temp_db_file.name) as data:
            ctx = data.scenes[0].context
            assert ctx.memos
            assert ctx.memos[f"{DEFAULT_NAMESPACE}.my_fn"].calls == [
                [json.dumps([[10], {"retval": 10, "foo": "bar"}]), "10"]
            ]


def test_memo_args():
    with tempfile.NamedTemporaryFile() as temp_db_file:
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name
        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        @memo(namespace="foo", name="bar", caching_policy="loose")
        def my_fn(*args, retval=None, **kwargs):
            return retval

        my_fn(10, retval=10, foo="bar")

        with event_db(temp_db_file.name) as data:
            assert data.scenes[0].context.memos["foo.bar"].caching_policy == "loose"


def test_memoizer_replay():
    os.environ[MEMO_MODE_KEY] = "replay"

    with tempfile.NamedTemporaryFile() as temp_db_file:
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name

        @memo(log_on_replay=True)
        def my_fn(*args, retval=None, **kwargs):
            return retval

        with event_db(temp_db_file.name) as data:
            data.scenes.append(
                Scene(
                    event=Event(env={}, timestamp="10:10"),
                    context=Context(
                        memos={
                            f"{DEFAULT_NAMESPACE}.my_fn": Memo(
                                calls=[
                                    [
                                        json.dumps(
                                            [[10], {"retval": 10, "foo": "bar"}]
                                        ),
                                        "20",
                                    ],
                                    [
                                        json.dumps(
                                            [[10], {"retval": 11, "foo": "baz"}]
                                        ),
                                        "21",
                                    ],
                                    [
                                        json.dumps(
                                            [
                                                [11],
                                                {"retval": 10, "foo": "baq", "a": "b"},
                                            ]
                                        ),
                                        "22",
                                    ],
                                ]
                            )
                        }
                    ),
                )
            )

        caught_calls = []

        def _catch_log_call(_, *args, **kwargs):
            caught_calls.append((args, kwargs))

        with patch(
            "jhack.utils.event_recorder.recorder._log_memo", new=_catch_log_call
        ):
            assert my_fn(10, retval=10, foo="bar") == 20
            assert my_fn(10, retval=11, foo="baz") == 21
            assert my_fn(11, retval=10, foo="baq", a="b") == 22
            # memos are all up! we run the actual function.
            assert my_fn(11, retval=10, foo="baq", a="b") == 10

        assert caught_calls == [
            (((10,), {"foo": "bar", "retval": 10}, "20"), {"cache_hit": True}),
            (((10,), {"foo": "baz", "retval": 11}, "21"), {"cache_hit": True}),
            (
                ((11,), {"a": "b", "foo": "baq", "retval": 10}, "22"),
                {"cache_hit": True},
            ),
            (
                ((11,), {"a": "b", "foo": "baq", "retval": 10}, "<propagated>"),
                {"cache_hit": False},
            ),
        ]

        with event_db(temp_db_file.name) as data:
            ctx = data.scenes[0].context
            assert ctx.memos[f"{DEFAULT_NAMESPACE}.my_fn"].cursor == 3


def test_memoizer_loose_caching():
    with tempfile.NamedTemporaryFile() as temp_db_file:
        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name

        _backing = {x: x + 1 for x in range(50)}

        @memo(caching_policy="loose", log_on_replay=True)
        def my_fn(m):
            return _backing[m]

        os.environ[MEMO_MODE_KEY] = "record"
        for i in range(50):
            assert my_fn(i) == i + 1

        # clear the backing storage, so that a cache miss would raise a
        # KeyError. my_fn is, as of now, totally useless
        _backing.clear()

        os.environ[MEMO_MODE_KEY] = "replay"

        # check that the function still works, with unordered arguments and repeated ones.
        values = list(range(50)) * 2
        random.shuffle(values)
        for i in values:
            assert my_fn(i) == i + 1


def test_memoizer_classmethod_recording():
    os.environ[MEMO_MODE_KEY] = "record"

    with tempfile.NamedTemporaryFile() as temp_db_file:
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name

        class Foo:
            @memo("foo")
            def my_fn(self, *args, retval=None, **kwargs):
                return retval

        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        f = Foo()
        f.my_fn(10, retval=10, foo="bar")

        with event_db(temp_db_file.name) as data:
            memos = data.scenes[0].context.memos
            assert memos["foo.my_fn"].calls == [
                [json.dumps([[10], {"retval": 10, "foo": "bar"}]), "10"]
            ]

            # replace return_value for replay test
            memos["foo.my_fn"].calls = [
                [json.dumps([[10], {"retval": 10, "foo": "bar"}]), "20"]
            ]

        os.environ[MEMO_MODE_KEY] = "replay"
        assert f.my_fn(10, retval=10, foo="bar") == 20

        # memos are up
        assert f.my_fn(10, retval=10, foo="bar") == 10
        assert f.my_fn(10, retval=10, foo="bar") == 10


def test_reset_replay_cursor():
    os.environ[MEMO_MODE_KEY] = "replay"

    with tempfile.NamedTemporaryFile() as temp_db_file:
        Path(temp_db_file.name).write_text("{}")
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name

        @memo()
        def my_fn(*args, retval=None, **kwargs):
            return retval

        with event_db(temp_db_file.name) as data:
            calls = [
                [[[10], {"retval": 10, "foo": "bar"}], 20],
                [[[10], {"retval": 11, "foo": "baz"}], 21],
                [[[11], {"retval": 10, "foo": "baq", "a": "b"}], 22],
            ]

            data.scenes.append(
                Scene(
                    event=Event(env={}, timestamp="10:10"),
                    context=Context(memos={"my_fn": Memo(calls=calls, cursor=2)}),
                )
            )

        with event_db(temp_db_file.name) as data:
            _memo = data.scenes[0].context.memos["my_fn"]
            assert _memo.cursor == 2
            assert _memo.calls == calls

        _reset_replay_cursors(temp_db_file.name)

        with event_db(temp_db_file.name) as data:
            _memo = data.scenes[0].context.memos["my_fn"]
            assert _memo.cursor == 0
            assert _memo.calls == calls


class Foo:
    pass


@pytest.mark.parametrize(
    "obj, serializer",
    (
        (b"1234", "pickle"),
        (object(), "pickle"),
        (Foo(), "pickle"),
    ),
)
def test_memo_exotic_types(obj, serializer):
    with tempfile.NamedTemporaryFile() as temp_db_file:
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name
        os.environ[MEMO_MODE_KEY] = "record"

        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        @memo(serializer=serializer)
        def my_fn(_obj):
            return _obj

        assert obj is my_fn(obj)

        os.environ[MEMO_MODE_KEY] = "replay"

        replay_output = my_fn(obj)
        assert obj is not replay_output

        assert type(obj) is type(replay_output)


def test_memo_pebble_push():
    with tempfile.NamedTemporaryFile() as temp_db_file:
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name
        os.environ[MEMO_MODE_KEY] = "record"

        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        stored = None

        class Foo:
            @memo(serializer=("PebblePush", "json"))
            def push(
                self,
                path,
                source,
                *,
                encoding: str = "utf-8",
                make_dirs: bool = False,
                permissions=42,
                user_id=42,
                user=42,
                group_id=42,
                group=42,
            ):

                nonlocal stored
                stored = source.read()
                return stored

        tf = tempfile.NamedTemporaryFile(delete=False)
        Path(tf.name).write_text("helloworld")

        obj = open(tf.name)
        assert Foo().push(42, obj, user="lolz") == stored == "helloworld"
        obj.close()
        stored = None

        os.environ[MEMO_MODE_KEY] = "replay"

        obj = open(tf.name)
        assert Foo().push(42, obj, user="lolz") == "helloworld"
        assert stored == None
        obj.close()

        tf.close()
        del tf


def test_memo_pebble_pull():
    with tempfile.NamedTemporaryFile() as temp_db_file:
        os.environ[MEMO_DATABASE_NAME_KEY] = temp_db_file.name
        os.environ[MEMO_MODE_KEY] = "record"

        with event_db(temp_db_file.name) as data:
            data.scenes.append(Scene(event=Event(env={}, timestamp="10:10")))

        class Foo:
            @memo(serializer=("json", "io"))
            def pull(self, foo: str):
                tf = tempfile.NamedTemporaryFile()
                Path(tf.name).write_text("helloworld")
                return open(tf.name)

            def getfile(self, foo: str):
                return self.pull(foo).read()

        assert Foo().getfile(foo="helloworld") == "helloworld"

        os.environ[MEMO_MODE_KEY] = "replay"

        assert Foo().getfile(foo="helloworld") == "helloworld"
