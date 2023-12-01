# Copyright 2021 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Client for the Pebble API (HTTP over Unix socket).

For a command-line interface for local testing, see test/pebble_cli.py.
"""

import binascii
import copy
import datetime
import email.message
import email.parser
import enum
import http.client
import io
import json
import logging
import os
import select
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import typing
import urllib.error
import urllib.parse
import urllib.request
import warnings
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    AnyStr,
    BinaryIO,
    Callable,
    Dict,
    Generator,
    Generic,
    Iterable,
    List,
    Literal,
    Optional,
    Protocol,
    Sequence,
    TextIO,
    Tuple,
    TypedDict,
    Union,
)

import websocket  # type: ignore

from ops._private import timeconv, yaml

# Public as these are used in the Container.add_layer signature
ServiceDict = typing.TypedDict('ServiceDict',
                               {'summary': str,
                                'description': str,
                                'startup': str,
                                'override': str,
                                'command': str,
                                'after': Sequence[str],
                                'before': Sequence[str],
                                'requires': Sequence[str],
                                'environment': Dict[str, str],
                                'user': str,
                                'user-id': Optional[int],
                                'group': str,
                                'group-id': Optional[int],
                                'working-dir': str,
                                'on-success': str,
                                'on-failure': str,
                                'on-check-failure': Dict[str, Any],
                                'backoff-delay': str,
                                'backoff-factor': Optional[int],
                                'backoff-limit': str,
                                'kill-delay': Optional[str],
                                },
                               total=False)

HttpDict = typing.TypedDict('HttpDict',
                            {'url': str,
                             'headers': Dict[str, str]},
                            total=False)
TcpDict = typing.TypedDict('TcpDict',
                           {'port': int,
                            'host': str},
                           total=False)
ExecDict = typing.TypedDict('ExecDict',
                            {'command': str,
                             # see JujuVersion.supports_exec_service_context
                             'service-context': str,
                             'environment': Dict[str, str],
                             'user-id': Optional[int],
                             'user': str,
                             'group-id': Optional[int],
                             'group': str,
                             'working-dir': str},
                            total=False)

CheckDict = typing.TypedDict('CheckDict',
                             {'override': str,
                              'level': Union['CheckLevel', str],
                              'period': Optional[str],
                              'timeout': Optional[str],
                              'http': Optional[HttpDict],
                              'tcp': Optional[TcpDict],
                              'exec': Optional[ExecDict],
                              'threshold': Optional[int]},
                             total=False)

# In Python 3.11+ 'services' and 'labels' should be NotRequired, and total=True.
LogTargetDict = typing.TypedDict('LogTargetDict',
                                 {'override': Union[Literal['merge'], Literal['replace']],
                                  'type': Literal['loki'],
                                  'location': str,
                                  'services': List[str],
                                  'labels': Dict[str, str]},
                                 total=False)

LayerDict = typing.TypedDict('LayerDict',
                             {'summary': str,
                              'description': str,
                              'services': Dict[str, ServiceDict],
                              'checks': Dict[str, CheckDict],
                              'log-targets': Dict[str, LogTargetDict]},
                             total=False)

PlanDict = typing.TypedDict('PlanDict',
                            {'services': Dict[str, ServiceDict],
                             'checks': Dict[str, CheckDict],
                             'log-targets': Dict[str, LogTargetDict]},
                            total=False)

_AuthDict = TypedDict('_AuthDict',
                      {'permissions': Optional[str],
                       'user-id': Optional[int],
                       'user': Optional[str],
                       'group-id': Optional[int],
                       'group': Optional[str],
                       'path': Optional[str],
                       'make-dirs': Optional[bool],
                       'make-parents': Optional[bool],
                       }, total=False)

_ServiceInfoDict = TypedDict('_ServiceInfoDict',
                             {'startup': Union['ServiceStartup', str],
                                 'current': Union['ServiceStatus', str],
                                 'name': str})

# Callback types for _MultiParser header and body handlers


class _BodyHandler(Protocol):
    def __call__(self, data: bytes, done: bool = False) -> None: ...  # noqa


_HeaderHandler = Callable[[bytes], None]

# tempfile.NamedTemporaryFile has an odd interface because of that
# 'name' attribute, so we need to make a Protocol for it.


class _Tempfile(Protocol):
    name = ''
    def write(self, data: bytes): ...  # noqa
    def close(self): ...  # noqa


class _FileLikeIO(Protocol[typing.AnyStr]):  # That also covers TextIO and BytesIO
    def read(self, __n: int = ...) -> typing.AnyStr: ...  # for BinaryIO  # noqa
    def write(self, __s: typing.AnyStr) -> int: ...  # noqa
    def __enter__(self) -> typing.IO[typing.AnyStr]: ...  # noqa


_AnyStrFileLikeIO = Union[_FileLikeIO[bytes], _FileLikeIO[str]]
_TextOrBinaryIO = Union[TextIO, BinaryIO]
_IOSource = Union[str, bytes, _AnyStrFileLikeIO]

_SystemInfoDict = TypedDict('_SystemInfoDict', {'version': str})

if TYPE_CHECKING:
    from typing_extensions import NotRequired

    _CheckInfoDict = TypedDict('_CheckInfoDict',
                               {"name": str,
                                "level": NotRequired[Optional[Union['CheckLevel', str]]],
                                "status": Union['CheckStatus', str],
                                "failures": NotRequired[int],
                                "threshold": int})
    _FileInfoDict = TypedDict('_FileInfoDict',
                              {"path": str,
                               "name": str,
                               "size": NotRequired[Optional[int]],
                               "permissions": str,
                               "last-modified": str,
                               "user-id": NotRequired[Optional[int]],
                               "user": NotRequired[Optional[str]],
                               "group-id": NotRequired[Optional[int]],
                               "group": NotRequired[Optional[str]],
                               "type": Union['FileType', str]})

    _ProgressDict = TypedDict('_ProgressDict',
                              {'label': str,
                               'done': int,
                               'total': int})
    _TaskDict = TypedDict('_TaskDict',
                          {'id': str,
                           'kind': str,
                           'summary': str,
                           'status': str,
                           'log': NotRequired[Optional[List[str]]],
                           'progress': _ProgressDict,
                           'spawn-time': str,
                           'ready-time': NotRequired[Optional[str]],
                           'data': NotRequired[Optional[Dict[str, Any]]]})
    _ChangeDict = TypedDict('_ChangeDict',
                            {'id': str,
                             'kind': str,
                             'summary': str,
                             'status': str,
                             'ready': bool,
                             'spawn-time': str,
                             'tasks': NotRequired[Optional[List[_TaskDict]]],
                             'err': NotRequired[Optional[str]],
                             'ready-time': NotRequired[Optional[str]],
                             'data': NotRequired[Optional[Dict[str, Any]]]})

    _Error = TypedDict('_Error',
                       {'kind': str,
                        'message': str})
    _Item = TypedDict('_Item',
                      {'path': str,
                       'error': NotRequired[_Error]})
    _FilesResponse = TypedDict('_FilesResponse',
                               {'result': List[_Item]})

    _WarningDict = TypedDict('_WarningDict',
                             {'message': str,
                              'first-added': str,
                              'last-added': str,
                              'last-shown': NotRequired[Optional[str]],
                              'expire-after': str,
                              'repeat-after': str})


class _WebSocket(Protocol):
    def connect(self, url: str, socket: socket.socket): ...  # noqa
    def shutdown(self): ...                                  # noqa
    def send(self, payload: str): ...                        # noqa
    def send_binary(self, payload: bytes): ...               # noqa
    def recv(self) -> Union[str, bytes]: ...                 # noqa


logger = logging.getLogger(__name__)


class _NotProvidedFlag:
    pass


_not_provided = _NotProvidedFlag()


class _UnixSocketConnection(http.client.HTTPConnection):
    """Implementation of HTTPConnection that connects to a named Unix socket."""

    def __init__(self, host: str, socket_path: str,
                 timeout: Union[_NotProvidedFlag, float] = _not_provided):
        if timeout is _not_provided:
            super().__init__(host)
        else:
            assert isinstance(timeout, (int, float)), timeout  # type guard for pyright
            super().__init__(host, timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        """Override connect to use Unix socket (instead of TCP socket)."""
        if not hasattr(socket, 'AF_UNIX'):
            raise NotImplementedError(f'Unix sockets not supported on {sys.platform}')
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        if self.timeout is not _not_provided:
            self.sock.settimeout(self.timeout)


class _UnixSocketHandler(urllib.request.AbstractHTTPHandler):
    """Implementation of HTTPHandler that uses a named Unix socket."""

    def __init__(self, socket_path: str):
        super().__init__()
        self.socket_path = socket_path

    def http_open(self, req: urllib.request.Request):
        """Override http_open to use a Unix socket connection (instead of TCP)."""
        return self.do_open(_UnixSocketConnection, req,  # type:ignore
                            socket_path=self.socket_path)


def _format_timeout(timeout: float) -> str:
    """Format timeout for use in the Pebble API.

    The format is in seconds with a millisecond resolution and an 's' suffix,
    as accepted by the Pebble API (which uses Go's time.ParseDuration).
    """
    return f'{timeout:.3f}s'


def _start_thread(target: Callable[..., Any], *args: Any, **kwargs: Any) -> threading.Thread:
    """Helper to simplify starting a thread."""
    thread = threading.Thread(target=target, args=args, kwargs=kwargs)
    thread.start()
    return thread


class Error(Exception):
    """Base class of most errors raised by the Pebble client."""

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.args}>'


class TimeoutError(TimeoutError, Error):
    """Raised when a polling timeout occurs."""


class ConnectionError(Error):
    """Raised when the Pebble client can't connect to the socket."""


class ProtocolError(Error):
    """Raised when there's a higher-level protocol error talking to Pebble."""


class PathError(Error):
    """Raised when there's an error with a specific path."""

    kind: typing.Literal["not-found", "permission-denied", "generic-file-error"]
    """Short string representing the kind of error."""

    message: str
    """Human-readable error message from the API."""

    def __init__(self, kind: str, message: str):
        """This shouldn't be instantiated directly."""
        self.kind = kind  # type: ignore
        self.message = message

    def __str__(self):
        return f'{self.kind} - {self.message}'

    def __repr__(self):
        return f'PathError({self.kind!r}, {self.message!r})'


class APIError(Error):
    """Raised when an HTTP API error occurs talking to the Pebble server."""

    body: Dict[str, Any]
    """Body of the HTTP response, parsed as JSON."""

    code: int
    """HTTP status code."""

    status: str
    """HTTP status string (reason)."""

    message: str
    """Human-readable error message from the API."""

    def __init__(self, body: Dict[str, Any], code: int, status: str, message: str):
        """This shouldn't be instantiated directly."""
        super().__init__(message)  # Makes str(e) return message
        self.body = body
        self.code = code
        self.status = status
        self.message = message

    def __repr__(self):
        return f'APIError({self.body!r}, {self.code!r}, {self.status!r}, {self.message!r})'


class ChangeError(Error):
    """Raised by actions when a change is ready but has an error."""

    err: str
    """Human-readable error message."""

    change: 'Change'
    """Change object associated with this error."""

    def __init__(self, err: str, change: 'Change'):
        """This shouldn't be instantiated directly."""
        self.err = err
        self.change = change

    def __str__(self):
        parts = [self.err]

        # Append any task logs to the error message
        for i, task in enumerate(self.change.tasks):
            if not task.log:
                continue
            parts.append(f'\n----- Logs from task {i} -----\n')
            parts.append('\n'.join(task.log))

        if len(parts) > 1:
            parts.append('\n-----')

        return ''.join(parts)

    def __repr__(self):
        return f'ChangeError({self.err!r}, {self.change!r})'


class ExecError(Error, Generic[AnyStr]):
    """Raised when a :meth:`Client.exec` command returns a non-zero exit code."""

    STR_MAX_OUTPUT = 1024
    """Maximum number of characters that stdout/stderr are truncated to in ``__str__``."""

    command: List[str]
    """Command line of command being executed."""

    exit_code: int
    """The process's exit code. Because this is an error, this will always be non-zero."""

    stdout: Optional[AnyStr]
    """Standard output from the process.

    If :meth:`ExecProcess.wait_output` was being called, this is the captured
    stdout as a str (or bytes if encoding was None). If :meth:`ExecProcess.wait`
    was being called, this is None.
    """

    stderr: Optional[AnyStr]
    """Standard error from the process.

    If :meth:`ExecProcess.wait_output` was being called and ``combine_stderr``
    was False, this is the captured stderr as a str (or bytes if encoding was
    None). If :meth:`ExecProcess.wait` was being called or ``combine_stderr``
    was True, this is None.
    """

    def __init__(
        self,
        command: List[str],
        exit_code: int,
        stdout: Optional[AnyStr],
        stderr: Optional[AnyStr],
    ):
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def __str__(self):
        message = f'non-zero exit code {self.exit_code} executing {self.command!r}'

        for name, out in [('stdout', self.stdout), ('stderr', self.stderr)]:
            if out is None:
                continue
            truncated = ' [truncated]' if len(out) > self.STR_MAX_OUTPUT else ''
            out = out[:self.STR_MAX_OUTPUT]
            message = f'{message}, {name}={out!r}{truncated}'

        return message


class WarningState(enum.Enum):
    """Enum of states for get_warnings() select parameter."""

    ALL = 'all'
    PENDING = 'pending'


class ChangeState(enum.Enum):
    """Enum of states for get_changes() select parameter."""

    ALL = 'all'
    IN_PROGRESS = 'in-progress'
    READY = 'ready'


class SystemInfo:
    """System information object."""

    def __init__(self, version: str):
        self.version = version

    @classmethod
    def from_dict(cls, d: '_SystemInfoDict') -> 'SystemInfo':
        """Create new SystemInfo object from dict parsed from JSON."""
        return cls(version=d['version'])

    def __repr__(self):
        return f'SystemInfo(version={self.version!r})'


class Warning:
    """Warning object."""

    def __init__(
        self,
        message: str,
        first_added: datetime.datetime,
        last_added: datetime.datetime,
        last_shown: Optional[datetime.datetime],
        expire_after: str,
        repeat_after: str,
    ):
        self.message = message
        self.first_added = first_added
        self.last_added = last_added
        self.last_shown = last_shown
        self.expire_after = expire_after
        self.repeat_after = repeat_after

    @classmethod
    def from_dict(cls, d: '_WarningDict') -> 'Warning':
        """Create new Warning object from dict parsed from JSON."""
        return cls(
            message=d['message'],
            first_added=timeconv.parse_rfc3339(d['first-added']),
            last_added=timeconv.parse_rfc3339(d['last-added']),
            last_shown=(timeconv.parse_rfc3339(d['last-shown'])  # type: ignore
                        if d.get('last-shown') else None),
            expire_after=d['expire-after'],
            repeat_after=d['repeat-after'],
        )

    def __repr__(self):
        return ('Warning('
                'message={self.message!r}, '
                'first_added={self.first_added!r}, '
                'last_added={self.last_added!r}, '
                'last_shown={self.last_shown!r}, '
                'expire_after={self.expire_after!r}, '
                'repeat_after={self.repeat_after!r})'
                ).format(self=self)


class TaskProgress:
    """Task progress object."""

    def __init__(
        self,
        label: str,
        done: int,
        total: int,
    ):
        self.label = label
        self.done = done
        self.total = total

    @classmethod
    def from_dict(cls, d: '_ProgressDict') -> 'TaskProgress':
        """Create new TaskProgress object from dict parsed from JSON."""
        return cls(
            label=d['label'],
            done=d['done'],
            total=d['total'],
        )

    def __repr__(self):
        return ('TaskProgress('
                'label={self.label!r}, '
                'done={self.done!r}, '
                'total={self.total!r})'
                ).format(self=self)


class TaskID(str):
    """Task ID (a more strongly-typed string)."""

    def __repr__(self):
        return f'TaskID({str(self)!r})'


class Task:
    """Task object."""

    def __init__(
        self,
        id: TaskID,
        kind: str,
        summary: str,
        status: str,
        log: List[str],
        progress: TaskProgress,
        spawn_time: datetime.datetime,
        ready_time: Optional[datetime.datetime],
        data: Optional[Dict[str, Any]] = None,
    ):
        self.id = id
        self.kind = kind
        self.summary = summary
        self.status = status
        self.log = log
        self.progress = progress
        self.spawn_time = spawn_time
        self.ready_time = ready_time
        self.data = data or {}

    @classmethod
    def from_dict(cls, d: '_TaskDict') -> 'Task':
        """Create new Task object from dict parsed from JSON."""
        return cls(
            id=TaskID(d['id']),
            kind=d['kind'],
            summary=d['summary'],
            status=d['status'],
            log=d.get('log') or [],
            progress=TaskProgress.from_dict(d['progress']),
            spawn_time=timeconv.parse_rfc3339(d['spawn-time']),
            ready_time=(timeconv.parse_rfc3339(d['ready-time'])  # type: ignore
                        if d.get('ready-time') else None),
            data=d.get('data') or {},
        )

    def __repr__(self):
        return ('Task('
                'id={self.id!r}, '
                'kind={self.kind!r}, '
                'summary={self.summary!r}, '
                'status={self.status!r}, '
                'log={self.log!r}, '
                'progress={self.progress!r}, '
                'spawn_time={self.spawn_time!r}, '
                'ready_time={self.ready_time!r}, '
                'data={self.data!r})'
                ).format(self=self)


class ChangeID(str):
    """Change ID (a more strongly-typed string)."""

    def __repr__(self):
        return f'ChangeID({str(self)!r})'


class Change:
    """Change object."""

    def __init__(
        self,
        id: ChangeID,
        kind: str,
        summary: str,
        status: str,
        tasks: List[Task],
        ready: bool,
        err: Optional[str],
        spawn_time: datetime.datetime,
        ready_time: Optional[datetime.datetime],
        data: Optional[Dict[str, Any]] = None,
    ):
        self.id = id
        self.kind = kind
        self.summary = summary
        self.status = status
        self.tasks = tasks
        self.ready = ready
        self.err = err
        self.spawn_time = spawn_time
        self.ready_time = ready_time
        self.data = data or {}

    @classmethod
    def from_dict(cls, d: '_ChangeDict') -> 'Change':
        """Create new Change object from dict parsed from JSON."""
        return cls(
            id=ChangeID(d['id']),
            kind=d['kind'],
            summary=d['summary'],
            status=d['status'],
            tasks=[Task.from_dict(t) for t in d.get('tasks') or []],
            ready=d['ready'],
            err=d.get('err'),
            spawn_time=timeconv.parse_rfc3339(d['spawn-time']),
            ready_time=(timeconv.parse_rfc3339(d['ready-time'])  # type: ignore
                        if d.get('ready-time') else None),
            data=d.get('data') or {},
        )

    def __repr__(self):
        return ('Change('
                'id={self.id!r}, '
                'kind={self.kind!r}, '
                'summary={self.summary!r}, '
                'status={self.status!r}, '
                'tasks={self.tasks!r}, '
                'ready={self.ready!r}, '
                'err={self.err!r}, '
                'spawn_time={self.spawn_time!r}, '
                'ready_time={self.ready_time!r}, '
                'data={self.data!r})'
                ).format(self=self)


class Plan:
    """Represents the effective Pebble configuration.

    A plan is the combined layer configuration. The layer configuration is
    documented at https://github.com/canonical/pebble/#layer-specification.
    """

    def __init__(self, raw: str):
        d = yaml.safe_load(raw) or {}  # type: ignore
        d = typing.cast('PlanDict', d)

        self._raw = raw
        self._services: Dict[str, Service] = {name: Service(name, service)
                                              for name, service in d.get('services', {}).items()}
        self._checks: Dict[str, Check] = {name: Check(name, check)
                                          for name, check in d.get('checks', {}).items()}
        self._log_targets: Dict[str, LogTarget] = {
            name: LogTarget(name, target)
            for name, target in d.get('log-targets', {}).items()}

    @property
    def services(self) -> Dict[str, 'Service']:
        """This plan's services mapping (maps service name to Service).

        This property is currently read-only.
        """
        return self._services

    @property
    def checks(self) -> Dict[str, 'Check']:
        """This plan's checks mapping (maps check name to :class:`Check`).

        This property is currently read-only.
        """
        return self._checks

    @property
    def log_targets(self) -> Dict[str, 'LogTarget']:
        """This plan's log targets mapping (maps log target name to :class:`LogTarget`).

        This property is currently read-only.
        """
        return self._log_targets

    def to_dict(self) -> 'PlanDict':
        """Convert this plan to its dict representation."""
        fields = [
            ('services', {name: service.to_dict() for name, service in self._services.items()}),
            ('checks', {name: check.to_dict() for name, check in self._checks.items()}),
            ('log-targets', {name: target.to_dict() for name, target in self._log_targets.items()})
        ]
        dct = {name: value for name, value in fields if value}
        return typing.cast('PlanDict', dct)

    def to_yaml(self) -> str:
        """Return this plan's YAML representation."""
        return yaml.safe_dump(self.to_dict())

    __str__ = to_yaml


class Layer:
    """Represents a Pebble configuration layer.

    The format of this is documented at
    https://github.com/canonical/pebble/#layer-specification.
    """

    #: Summary of the purpose of this layer.
    summary: str
    #: Long-form description of this layer.
    description: str
    #: Mapping of name to :class:`Service` defined by this layer.
    services: Dict[str, 'Service']
    #: Mapping of check to :class:`Check` defined by this layer.
    checks: Dict[str, 'Check']
    #: Mapping of target to :class:`LogTarget` defined by this layer.
    log_targets: Dict[str, 'LogTarget']

    def __init__(self, raw: Optional[Union[str, 'LayerDict']] = None):
        if isinstance(raw, str):
            d = yaml.safe_load(raw) or {}  # type: ignore # (Any 'raw' type)
        else:
            d = raw or {}
        d = typing.cast('LayerDict', d)

        self.summary = d.get('summary', '')
        self.description = d.get('description', '')
        self.services = {name: Service(name, service)
                         for name, service in d.get('services', {}).items()}
        self.checks = {name: Check(name, check)
                       for name, check in d.get('checks', {}).items()}
        self.log_targets = {name: LogTarget(name, target)
                            for name, target in d.get('log-targets', {}).items()}

    def to_yaml(self) -> str:
        """Convert this layer to its YAML representation."""
        return yaml.safe_dump(self.to_dict())

    def to_dict(self) -> 'LayerDict':
        """Convert this layer to its dict representation."""
        fields = [
            ('summary', self.summary),
            ('description', self.description),
            ('services', {name: service.to_dict() for name, service in self.services.items()}),
            ('checks', {name: check.to_dict() for name, check in self.checks.items()}),
            ('log-targets', {name: target.to_dict() for name, target in self.log_targets.items()})
        ]
        dct = {name: value for name, value in fields if value}
        return typing.cast('LayerDict', dct)

    def __repr__(self) -> str:
        return f'Layer({self.to_dict()!r})'

    def __eq__(self, other: Union['LayerDict', 'Layer']) -> bool:
        """Reports whether this layer configuration is equal to another."""
        if isinstance(other, dict):
            return self.to_dict() == other
        elif isinstance(other, Layer):
            return self.to_dict() == other.to_dict()
        else:
            return NotImplemented

    __str__ = to_yaml


class Service:
    """Represents a service description in a Pebble configuration layer."""

    def __init__(self, name: str, raw: Optional['ServiceDict'] = None):
        self.name = name
        dct: ServiceDict = raw or {}
        self.summary = dct.get('summary', '')
        self.description = dct.get('description', '')
        self.startup = dct.get('startup', '')
        self.override = dct.get('override', '')
        self.command = dct.get('command', '')
        self.after = list(dct.get('after', []))
        self.before = list(dct.get('before', []))
        self.requires = list(dct.get('requires', []))
        self.environment = dict(dct.get('environment', {}))
        self.user = dct.get('user', '')
        self.user_id = dct.get('user-id')
        self.group = dct.get('group', '')
        self.group_id = dct.get('group-id')
        self.working_dir = dct.get('working-dir', '')
        self.on_success = dct.get('on-success', '')
        self.on_failure = dct.get('on-failure', '')
        self.on_check_failure = dict(dct.get('on-check-failure', {}))
        self.backoff_delay = dct.get('backoff-delay', '')
        self.backoff_factor = dct.get('backoff-factor')
        self.backoff_limit = dct.get('backoff-limit', '')
        self.kill_delay = dct.get('kill-delay', '')

    def to_dict(self) -> 'ServiceDict':
        """Convert this service object to its dict representation."""
        fields = [
            ('summary', self.summary),
            ('description', self.description),
            ('startup', self.startup),
            ('override', self.override),
            ('command', self.command),
            ('after', self.after),
            ('before', self.before),
            ('requires', self.requires),
            ('environment', self.environment),
            ('user', self.user),
            ('user-id', self.user_id),
            ('group', self.group),
            ('group-id', self.group_id),
            ('working-dir', self.working_dir),
            ('on-success', self.on_success),
            ('on-failure', self.on_failure),
            ('on-check-failure', self.on_check_failure),
            ('backoff-delay', self.backoff_delay),
            ('backoff-factor', self.backoff_factor),
            ('backoff-limit', self.backoff_limit),
            ('kill-delay', self.kill_delay),
        ]
        dct = {name: value for name, value in fields if value}
        return typing.cast('ServiceDict', dct)

    def _merge(self, other: 'Service'):
        """Merges this service object with another service definition.

        For attributes present in both objects, the passed in service
        attributes take precedence.
        """
        for name, value in other.__dict__.items():
            if not value or name == 'name':
                continue
            if name in ['after', 'before', 'requires']:
                getattr(self, name).extend(value)
            elif name in ['environment', 'on_check_failure']:
                getattr(self, name).update(value)
            else:
                setattr(self, name, value)

    def __repr__(self) -> str:
        return f'Service({self.to_dict()!r})'

    def __eq__(self, other: Union['ServiceDict', 'Service']) -> bool:
        """Reports whether this service configuration is equal to another."""
        if isinstance(other, dict):
            return self.to_dict() == other
        elif isinstance(other, Service):
            return self.to_dict() == other.to_dict()
        else:
            return NotImplemented


class ServiceStartup(enum.Enum):
    """Enum of service startup options."""

    ENABLED = 'enabled'
    DISABLED = 'disabled'


class ServiceStatus(enum.Enum):
    """Enum of service statuses."""

    ACTIVE = 'active'
    INACTIVE = 'inactive'
    ERROR = 'error'


class ServiceInfo:
    """Service status information."""

    def __init__(
        self,
        name: str,
        startup: Union[ServiceStartup, str],
        current: Union[ServiceStatus, str],
    ):
        self.name = name
        self.startup = startup
        self.current = current

    def is_running(self) -> bool:
        """Return True if this service is running (in the active state)."""
        return self.current == ServiceStatus.ACTIVE

    @classmethod
    def from_dict(cls, d: '_ServiceInfoDict') -> 'ServiceInfo':
        """Create new ServiceInfo object from dict parsed from JSON."""
        try:
            startup = ServiceStartup(d['startup'])
        except ValueError:
            startup = d['startup']
        try:
            current = ServiceStatus(d['current'])
        except ValueError:
            current = d['current']
        return cls(
            name=d['name'],
            startup=startup,
            current=current,
        )

    def __repr__(self):
        return ('ServiceInfo('
                'name={self.name!r}, '
                'startup={self.startup}, '
                'current={self.current})'
                ).format(self=self)


class Check:
    """Represents a check in a Pebble configuration layer."""

    def __init__(self, name: str, raw: Optional['CheckDict'] = None):
        self.name = name
        dct: CheckDict = raw or {}
        self.override: str = dct.get('override', '')
        try:
            level: Union[CheckLevel, str] = CheckLevel(dct.get('level', ''))
        except ValueError:
            level = dct.get('level', '')
        self.level = level
        self.period: Optional[str] = dct.get('period', '')
        self.timeout: Optional[str] = dct.get('timeout', '')
        self.threshold: Optional[int] = dct.get('threshold')

        http = dct.get('http')
        if http is not None:
            http = copy.deepcopy(http)
        self.http: Optional[HttpDict] = http

        tcp = dct.get('tcp')
        if tcp is not None:
            tcp = copy.deepcopy(tcp)
        self.tcp: Optional[TcpDict] = tcp

        exec_ = dct.get('exec')
        if exec_ is not None:
            exec_ = copy.deepcopy(exec_)
        self.exec: Optional[ExecDict] = exec_

    def to_dict(self) -> 'CheckDict':
        """Convert this check object to its dict representation."""
        level: str = self.level.value if isinstance(self.level, CheckLevel) else self.level
        fields = [
            ('override', self.override),
            ('level', level),
            ('period', self.period),
            ('timeout', self.timeout),
            ('threshold', self.threshold),
            ('http', self.http),
            ('tcp', self.tcp),
            ('exec', self.exec),
        ]
        dct = {name: value for name, value in fields if value}
        return typing.cast('CheckDict', dct)

    def __repr__(self) -> str:
        return f'Check({self.to_dict()!r})'

    def __eq__(self, other: Union['CheckDict', 'Check']) -> bool:
        """Reports whether this check configuration is equal to another."""
        if isinstance(other, dict):
            return self.to_dict() == other
        elif isinstance(other, Check):
            return self.to_dict() == other.to_dict()
        else:
            return NotImplemented


class CheckLevel(enum.Enum):
    """Enum of check levels."""

    UNSET = ''
    ALIVE = 'alive'
    READY = 'ready'


class CheckStatus(enum.Enum):
    """Enum of check statuses."""

    UP = 'up'
    DOWN = 'down'


class LogTarget:
    """Represents a log target in a Pebble configuration layer."""

    def __init__(self, name: str, raw: Optional['LogTargetDict'] = None):
        self.name = name
        dct: LogTargetDict = raw or {}
        self.override: str = dct.get('override', '')
        self.type = dct.get('type', '')
        self.location = dct.get('location', '')
        self.services: List[str] = list(dct.get('services', []))
        labels = dct.get('labels')
        if labels is not None:
            labels = copy.deepcopy(labels)
        self.labels: Optional[Dict[str, str]] = labels

    def to_dict(self) -> 'LogTargetDict':
        """Convert this log target object to its dict representation."""
        fields = [
            ('override', self.override),
            ('type', self.type),
            ('location', self.location),
            ('services', self.services),
            ('labels', self.labels),
        ]
        dct = {name: value for name, value in fields if value}
        return typing.cast('LogTargetDict', dct)

    def __repr__(self):
        return f'LogTarget({self.to_dict()!r})'

    def __eq__(self, other: Union['LogTargetDict', 'LogTarget']):
        if isinstance(other, dict):
            return self.to_dict() == other
        elif isinstance(other, LogTarget):
            return self.to_dict() == other.to_dict()
        else:
            return NotImplemented


class FileType(enum.Enum):
    """Enum of file types."""

    FILE = 'file'
    DIRECTORY = 'directory'
    SYMLINK = 'symlink'
    SOCKET = 'socket'
    NAMED_PIPE = 'named-pipe'
    DEVICE = 'device'
    UNKNOWN = 'unknown'


class FileInfo:
    """Stat-like information about a single file or directory."""

    path: str
    """Full path of the file."""

    name: str
    """Base name of the file."""

    type: Union['FileType', str]
    """Type of the file ("file", "directory", "symlink", etc)."""

    size: Optional[int]
    """Size of the file (will be 0 if ``type`` is not "file")."""

    permissions: int
    """Unix permissions of the file."""

    last_modified: datetime.datetime
    """Time file was last modified."""

    user_id: Optional[int]
    """User ID of the file."""

    user: Optional[str]
    """Username of the file."""

    group_id: Optional[int]
    """Group ID of the file."""

    group: Optional[str]
    """Group name of the file."""

    def __init__(
        self,
        path: str,
        name: str,
        type: Union['FileType', str],
        size: Optional[int],
        permissions: int,
        last_modified: datetime.datetime,
        user_id: Optional[int],
        user: Optional[str],
        group_id: Optional[int],
        group: Optional[str],
    ):
        self.path = path
        self.name = name
        self.type = type
        self.size = size
        self.permissions = permissions
        self.last_modified = last_modified
        self.user_id = user_id
        self.user = user
        self.group_id = group_id
        self.group = group

    @classmethod
    def from_dict(cls, d: '_FileInfoDict') -> 'FileInfo':
        """Create new FileInfo object from dict parsed from JSON."""
        try:
            file_type = FileType(d['type'])
        except ValueError:
            file_type = d['type']
        return cls(
            path=d['path'],
            name=d['name'],
            type=file_type,
            size=d.get('size'),
            permissions=int(d['permissions'], 8),
            last_modified=timeconv.parse_rfc3339(d['last-modified']),
            user_id=d.get('user-id'),
            user=d.get('user'),
            group_id=d.get('group-id'),
            group=d.get('group'),
        )

    def __repr__(self):
        return ('FileInfo('
                'path={self.path!r}, '
                'name={self.name!r}, '
                'type={self.type}, '
                'size={self.size}, '
                'permissions=0o{self.permissions:o}, '
                'last_modified={self.last_modified!r}, '
                'user_id={self.user_id}, '
                'user={self.user!r}, '
                'group_id={self.group_id}, '
                'group={self.group!r})'
                ).format(self=self)


class CheckInfo:
    """Check status information.

    A list of these objects is returned from :meth:`Client.get_checks`.
    """

    name: str
    """Name of the check."""

    level: Optional[Union[CheckLevel, str]]
    """Check level.

    This can be :attr:`CheckLevel.ALIVE`, :attr:`CheckLevel.READY`, or None (level not set).
    """

    status: Union[CheckStatus, str]
    """Status of the check.

    :attr:`CheckStatus.UP` means the check is healthy (the number of failures
    is less than the threshold), :attr:`CheckStatus.DOWN` means the check is
    unhealthy (the number of failures has reached the threshold).
    """

    failures: int
    """Number of failures since the check last succeeded.

    This is reset to zero if the check succeeds.
    """

    threshold: int
    """Failure threshold.

    This is how many consecutive failures for the check to be considered "down".
    """

    def __init__(
        self,
        name: str,
        level: Optional[Union[CheckLevel, str]],
        status: Union[CheckStatus, str],
        failures: int = 0,
        threshold: int = 0,
    ):
        self.name = name
        self.level = level
        self.status = status
        self.failures = failures
        self.threshold = threshold

    @classmethod
    def from_dict(cls, d: '_CheckInfoDict') -> 'CheckInfo':
        """Create new :class:`CheckInfo` object from dict parsed from JSON."""
        try:
            level = CheckLevel(d.get('level', ''))
        except ValueError:
            level = d.get('level')
        try:
            status = CheckStatus(d['status'])
        except ValueError:
            status = d['status']
        return cls(
            name=d['name'],
            level=level,
            status=status,
            failures=d.get('failures', 0),
            threshold=d['threshold'],
        )

    def __repr__(self):
        return ('CheckInfo('
                'name={self.name!r}, '
                'level={self.level!r}, '
                'status={self.status}, '
                'failures={self.failures}, '
                'threshold={self.threshold!r})'
                ).format(self=self)


class ExecProcess(Generic[AnyStr]):
    """Represents a process started by :meth:`Client.exec`.

    To avoid deadlocks, most users should use :meth:`wait_output` instead of
    reading and writing the :attr:`stdin`, :attr:`stdout`, and :attr:`stderr`
    attributes directly. Alternatively, users can pass stdin/stdout/stderr to
    :meth:`Client.exec`.

    This class should not be instantiated directly, only via
    :meth:`Client.exec`.
    """

    stdin: Optional[IO[AnyStr]]
    """Standard input for the process.

    If the stdin argument was not passed to :meth:`Client.exec`, this is a
    writable file-like object the caller can use to stream input to the
    process. It is None if stdin was passed to :meth:`Client.exec`.
    """

    stdout: Optional[IO[AnyStr]]
    """Standard output from the process.

    If the stdout argument was not passed to :meth:`Client.exec`, this is a
    readable file-like object the caller can use to stream output from the
    process. It is None if stdout was passed to :meth:`Client.exec`.
    """

    stderr: Optional[IO[AnyStr]]
    """Standard error from the process.

    If the stderr argument was not passed to :meth:`Client.exec` and
    ``combine_stderr`` was False, this is a readable file-like object the
    caller can use to stream error output from the process. It is None if
    stderr was passed to :meth:`Client.exec` or ``combine_stderr`` was True.
    """

    def __init__(
        self,
        stdin: Optional[IO[AnyStr]],
        stdout: Optional[IO[AnyStr]],
        stderr: Optional[IO[AnyStr]],
        client: 'Client',
        timeout: Optional[float],
        control_ws: '_WebSocket',
        stdio_ws: '_WebSocket',
        stderr_ws: Optional['_WebSocket'],
        command: List[str],
        encoding: Optional[str],
        change_id: ChangeID,
        cancel_stdin: Optional[Callable[[], None]],
        cancel_reader: Optional[int],
        threads: List[threading.Thread],
    ):
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self._client = client
        self._timeout = timeout
        self._control_ws = control_ws
        self._stdio_ws = stdio_ws
        self._stderr_ws = stderr_ws
        self._command = command
        self._encoding = encoding
        self._change_id = change_id
        self._cancel_stdin = cancel_stdin
        self._cancel_reader = cancel_reader
        self._threads = threads
        self._waited = False

    def __del__(self):
        if not self._waited:
            msg = 'ExecProcess instance garbage collected without call to wait() or wait_output()'
            warnings.warn(msg, ResourceWarning)

    def wait(self):
        """Wait for the process to finish.

        If a timeout was specified to the :meth:`Client.exec` call, this waits
        at most that duration.

        Raises:
            ChangeError: if there was an error starting or running the process.
            ExecError: if the process exits with a non-zero exit code.
        """
        exit_code = self._wait()
        if exit_code != 0:
            raise ExecError(self._command, exit_code, None, None)

    def _wait(self) -> int:
        self._waited = True
        timeout = self._timeout
        if timeout is not None:
            # A bit more than the command timeout to ensure that happens first
            timeout += 1
        change = self._client.wait_change(self._change_id, timeout=timeout)

        # If stdin reader thread is running, stop it
        if self._cancel_stdin is not None:
            self._cancel_stdin()

        # Wait for all threads to finish (e.g., message barrier sent)
        for thread in self._threads:
            thread.join()

        # If we opened a cancel_reader pipe, close the read side now (write
        # side was already closed by _cancel_stdin().
        if self._cancel_reader is not None:
            os.close(self._cancel_reader)

        # Close websockets (shutdown doesn't send CLOSE message or wait for response).
        self._control_ws.shutdown()
        self._stdio_ws.shutdown()
        if self._stderr_ws is not None:
            self._stderr_ws.shutdown()

        if change.err:
            raise ChangeError(change.err, change)

        exit_code = -1
        if change.tasks:
            exit_code = change.tasks[0].data.get('exit-code', -1)
        return exit_code

    def wait_output(self) -> Tuple[AnyStr, Optional[AnyStr]]:
        """Wait for the process to finish and return tuple of (stdout, stderr).

        If a timeout was specified to the :meth:`Client.exec` call, this waits
        at most that duration. If combine_stderr was True, stdout will include
        the process's standard error, and stderr will be None.

        Raises:
            ChangeError: if there was an error starting or running the process.
            ExecError: if the process exits with a non-zero exit code.
            TypeError: if :meth:`Client.exec` was called with the ``stdout`` argument.
        """
        if self.stdout is None:
            raise TypeError(
                "can't use wait_output() when exec was called with the stdout argument; "
                "use wait() instead"
            )

        if self._encoding is not None:
            out = io.StringIO()
            err = io.StringIO() if self.stderr is not None else None
        else:
            out = io.BytesIO()
            err = io.BytesIO() if self.stderr is not None else None

        t = _start_thread(shutil.copyfileobj, self.stdout, out)
        self._threads.append(t)

        if self.stderr is not None:
            t = _start_thread(shutil.copyfileobj, self.stderr, err)
            self._threads.append(t)

        exit_code: int = self._wait()

        out_value = typing.cast(AnyStr, out.getvalue())
        err_value = typing.cast(AnyStr, err.getvalue()) if err is not None else None
        if exit_code != 0:
            raise ExecError[AnyStr](self._command, exit_code, out_value, err_value)

        return (out_value, err_value)

    def send_signal(self, sig: Union[int, str]):
        """Send the given signal to the running process.

        Args:
            sig: Name or number of signal to send, e.g., "SIGHUP", 1, or
                signal.SIGHUP.
        """
        if isinstance(sig, int):
            sig = signal.Signals(sig).name
        payload = {
            'command': 'signal',
            'signal': {'name': sig},
        }
        msg = json.dumps(payload, sort_keys=True)
        self._control_ws.send(msg)


def _has_fileno(f: Any) -> bool:
    """Return True if the file-like object has a valid fileno() method."""
    try:
        f.fileno()
        return True
    except Exception:
        # Some types define a fileno method that raises io.UnsupportedOperation,
        # but just catching all exceptions here won't hurt.
        return False


def _reader_to_websocket(reader: '_WebsocketReader',
                         ws: '_WebSocket',
                         encoding: str,
                         cancel_reader: Optional[int] = None,
                         bufsize: int = 16 * 1024):
    """Read reader through to EOF and send each chunk read to the websocket."""
    while True:
        if cancel_reader is not None:
            # Wait for either a read to be ready or the caller to cancel stdin
            result = select.select([cancel_reader, reader], [], [])
            if cancel_reader in result[0]:
                break

        chunk = reader.read(bufsize)
        if not chunk:
            break
        if isinstance(chunk, str):
            chunk = chunk.encode(encoding)
        ws.send_binary(chunk)

    ws.send('{"command":"end"}')  # type: ignore # Send "end" command as TEXT frame to signal EOF


def _websocket_to_writer(ws: '_WebSocket', writer: '_WebsocketWriter',
                         encoding: Optional[str]):
    """Receive messages from websocket (until end signal) and write to writer."""
    while True:
        chunk = ws.recv()

        if isinstance(chunk, str):
            try:
                payload = json.loads(chunk)
            except ValueError:
                # Garbage sent, try to keep going
                logger.warning('Cannot decode I/O command (invalid JSON)')
                continue
            command = payload.get('command')
            if command != 'end':
                # A command we don't recognize, keep going
                logger.warning(f'Invalid I/O command {command!r}')
                continue
            # Received "end" command (EOF signal), stop thread
            break

        if encoding is not None:
            chunk = chunk.decode(encoding)
        writer.write(chunk)


class _WebsocketWriter(io.BufferedIOBase):
    """A writable file-like object that sends what's written to it to a websocket."""

    def __init__(self, ws: '_WebSocket'):
        self.ws = ws

    def writable(self):
        """Denote this file-like object as writable."""
        return True

    def write(self, chunk: Union[str, bytes]) -> int:
        """Write chunk to the websocket."""
        if not isinstance(chunk, bytes):
            raise TypeError(f'value to write must be bytes, not {type(chunk).__name__}')
        self.ws.send_binary(chunk)
        return len(chunk)

    def close(self):
        """Send end-of-file message to websocket."""
        self.ws.send('{"command":"end"}')


class _WebsocketReader(io.BufferedIOBase):
    """A readable file-like object whose reads come from a websocket."""

    def __init__(self, ws: '_WebSocket'):
        self.ws = ws
        self.remaining = b''
        self.eof = False

    def readable(self) -> bool:
        """Denote this file-like object as readable."""
        return True

    def read(self, n: int = -1) -> Union[str, bytes]:
        """Read up to n bytes from the websocket (or one message if n<0)."""
        if self.eof:
            # Calling read() multiple times after EOF should still return EOF
            return b''

        while not self.remaining:
            chunk = self.ws.recv()

            if isinstance(chunk, str):
                try:
                    payload = json.loads(chunk)
                except ValueError:
                    # Garbage sent, try to keep going
                    logger.warning('Cannot decode I/O command (invalid JSON)')
                    continue
                command = payload.get('command')
                if command != 'end':
                    # A command we don't recognize, keep going
                    logger.warning(f'Invalid I/O command {command!r}')
                    continue
                # Received "end" command, return EOF designator
                self.eof = True
                return b''

            self.remaining = chunk

        if n < 0:
            n = len(self.remaining)
        result: Union[str, bytes] = self.remaining[:n]
        self.remaining = self.remaining[n:]
        return result

    def read1(self, n: int = -1) -> Union[str, bytes]:
        """An alias for read."""
        return self.read(n)


class Client:
    """Pebble API client.

    Defaults to using a Unix socket at socket_path (which must be specified
    unless a custom opener is provided).

    For methods that wait for changes, such as :meth:`start_services` and :meth:`replan_services`,
    if the change fails or times out, then a :class:`ChangeError` or :class:`TimeoutError` will be
    raised.

    All methods may raise exceptions when there are problems communicating with Pebble. Problems
    connecting to or transferring data with Pebble will raise a :class:`ConnectionError`. When an
    error occurs executing the request, such as trying to add an invalid layer or execute a command
    that does not exist, an :class:`APIError` is raised.
    """

    _chunk_size = 8192

    def __init__(self, socket_path: str,
                 opener: Optional[urllib.request.OpenerDirector] = None,
                 base_url: str = 'http://localhost',
                 timeout: float = 5.0):
        if not isinstance(socket_path, str):
            raise TypeError(f'`socket_path` should be a string, not: {type(socket_path)}')
        if opener is None:
            opener = self._get_default_opener(socket_path)
        self.socket_path = socket_path
        self.opener = opener
        self.base_url = base_url
        self.timeout = timeout

    @classmethod
    def _get_default_opener(cls, socket_path: str) -> urllib.request.OpenerDirector:
        """Build the default opener to use for requests (HTTP over Unix socket)."""
        opener = urllib.request.OpenerDirector()
        opener.add_handler(_UnixSocketHandler(socket_path))
        opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
        opener.add_handler(urllib.request.HTTPRedirectHandler())
        opener.add_handler(urllib.request.HTTPErrorProcessor())
        return opener

    # we need to cast the return type depending on the request params
    def _request(self,
                 method: str,
                 path: str,
                 query: Optional[Dict[str, Any]] = None,
                 body: Optional[Dict[str, Any]] = None
                 ) -> Dict[str, Any]:
        """Make a JSON request to the Pebble server with the given HTTP method and path.

        If query dict is provided, it is encoded and appended as a query string
        to the URL. If body dict is provided, it is serialied as JSON and used
        as the HTTP body (with Content-Type: "application/json"). The resulting
        body is decoded from JSON.
        """
        headers = {'Accept': 'application/json'}
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        response = self._request_raw(method, path, query, headers, data)
        self._ensure_content_type(response.headers, 'application/json')
        raw_resp: Dict[str, Any] = json.loads(response.read())
        return raw_resp

    @staticmethod
    def _ensure_content_type(headers: email.message.Message,
                             expected: 'Literal["multipart/form-data", "application/json"]'):
        """Parse Content-Type header from headers and ensure it's equal to expected.

        Return a dict of any options in the header, e.g., {'boundary': ...}.
        """
        ctype = headers.get_content_type()
        params = headers.get_params() or {}
        options = {key: value for key, value in params if value}
        if ctype != expected:
            raise ProtocolError(f'expected Content-Type {expected!r}, got {ctype!r}')
        return options

    def _request_raw(
        self, method: str, path: str,
        query: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, Any]] = None,
        data: Optional[Union[bytes, Generator[bytes, Any, Any]]] = None,
    ) -> http.client.HTTPResponse:
        """Make a request to the Pebble server; return the raw HTTPResponse object."""
        url = self.base_url + path
        if query:
            url = f"{url}?{urllib.parse.urlencode(query, doseq=True)}"

        if headers is None:
            headers = {}
        request = urllib.request.Request(url, method=method, data=data, headers=headers)

        try:
            response = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            code = e.code
            status = e.reason
            try:
                body: Dict[str, Any] = json.loads(e.read())
                message: str = body['result']['message']
            except (OSError, ValueError, KeyError) as e2:
                # Will only happen on read error or if Pebble sends invalid JSON.
                body: Dict[str, Any] = {}
                message = f'{type(e2).__name__} - {e2}'
            raise APIError(body, code, status, message) from None
        except urllib.error.URLError as e:
            if e.args and isinstance(e.args[0], FileNotFoundError):
                raise ConnectionError(
                    f"Could not connect to Pebble: socket not found at {self.socket_path!r} "
                    "(container restarted?)") from None
            raise ConnectionError(e.reason) from e

        return response

    def get_system_info(self) -> SystemInfo:
        """Get system info."""
        resp = self._request('GET', '/v1/system-info')
        return SystemInfo.from_dict(resp['result'])

    def get_warnings(self, select: WarningState = WarningState.PENDING) -> List[Warning]:
        """Get list of warnings in given state (pending or all)."""
        query = {'select': select.value}
        resp = self._request('GET', '/v1/warnings', query)
        return [Warning.from_dict(w) for w in resp['result']]

    def ack_warnings(self, timestamp: datetime.datetime) -> int:
        """Acknowledge warnings up to given timestamp, return number acknowledged."""
        body = {'action': 'okay', 'timestamp': timestamp.isoformat()}
        resp = self._request('POST', '/v1/warnings', body=body)
        return resp['result']

    def get_changes(
        self, select: ChangeState = ChangeState.IN_PROGRESS, service: Optional[str] = None,
    ) -> List[Change]:
        """Get list of changes in given state, filter by service name if given."""
        query: Dict[str, Union[str, int]] = {'select': select.value}
        if service is not None:
            query['for'] = service
        resp = self._request('GET', '/v1/changes', query)
        return [Change.from_dict(c) for c in resp['result']]

    def get_change(self, change_id: ChangeID) -> Change:
        """Get single change by ID."""
        resp = self._request('GET', f'/v1/changes/{change_id}')
        return Change.from_dict(resp['result'])

    def abort_change(self, change_id: ChangeID) -> Change:
        """Abort change with given ID."""
        body = {'action': 'abort'}
        resp = self._request('POST', f'/v1/changes/{change_id}', body=body)
        return Change.from_dict(resp['result'])

    def autostart_services(self, timeout: float = 30.0, delay: float = 0.1) -> ChangeID:
        """Start the startup-enabled services and wait (poll) for them to be started.

        Args:
            timeout: Seconds before autostart change is considered timed out (float). If
                timeout is 0, submit the action but don't wait; just return the change ID
                immediately.
            delay: Seconds before executing the autostart change (float).

        Returns:
            ChangeID of the autostart change.

        Raises:
            ChangeError: if one or more of the services didn't start, and ``timeout`` is non-zero.
        """
        return self._services_action('autostart', [], timeout, delay)

    def replan_services(self, timeout: float = 30.0, delay: float = 0.1) -> ChangeID:
        """Replan by (re)starting changed and startup-enabled services and wait for them to start.

        Args:
            timeout: Seconds before replan change is considered timed out (float). If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
            delay: Seconds before executing the replan change (float).

        Returns:
            ChangeID of the replan change.

        Raises:
            ChangeError: if one or more of the services didn't stop/start, and ``timeout`` is
                non-zero.
        """
        return self._services_action('replan', [], timeout, delay)

    def start_services(
        self, services: Iterable[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Start services by name and wait (poll) for them to be started.

        Args:
            services: Non-empty list of services to start.
            timeout: Seconds before start change is considered timed out (float). If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
            delay: Seconds before executing the start change (float).

        Returns:
            ChangeID of the start change.

        Raises:
            ChangeError: if one or more of the services didn't stop/start, and ``timeout`` is
                non-zero.
        """
        return self._services_action('start', services, timeout, delay)

    def stop_services(
        self, services: Iterable[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Stop services by name and wait (poll) for them to be started.

        Args:
            services: Non-empty list of services to stop.
            timeout: Seconds before stop change is considered timed out (float). If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
            delay: Seconds before executing the stop change (float).

        Returns:
            ChangeID of the stop change.

        Raises:
            ChangeError: if one or more of the services didn't stop/start and ``timeout`` is
                non-zero.
        """
        return self._services_action('stop', services, timeout, delay)

    def restart_services(
        self, services: Iterable[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Restart services by name and wait (poll) for them to be started.

        Args:
            services: Non-empty list of services to restart.
            timeout: Seconds before restart change is considered timed out (float). If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
            delay: Seconds before executing the restart change (float).

        Returns:
            ChangeID of the restart change.

        Raises:
            ChangeError: if one or more of the services didn't stop/start and ``timeout`` is
                non-zero.
        """
        return self._services_action('restart', services, timeout, delay)

    def _services_action(
        self, action: str, services: Iterable[str], timeout: Optional[float],
            delay: float,
    ) -> ChangeID:
        if isinstance(services, (str, bytes)) or not hasattr(services, '__iter__'):
            raise TypeError(
                f'services must be of type Iterable[str], not {type(services).__name__}')

        services = list(services)
        for s in services:
            if not isinstance(s, str):
                raise TypeError(f'service names must be str, not {type(s).__name__}')

        body = {'action': action, 'services': services}
        resp = self._request('POST', '/v1/services', body=body)
        change_id = ChangeID(resp['change'])
        if timeout:
            change = self.wait_change(change_id, timeout=timeout, delay=delay)
            if change.err:
                raise ChangeError(change.err, change)
        return change_id

    def wait_change(
        self, change_id: ChangeID,
        timeout: Optional[float] = 30.0,
        delay: float = 0.1,
    ) -> Change:
        """Wait for the given change to be ready.

        If the Pebble server supports the /v1/changes/{id}/wait API endpoint,
        use that to avoid polling, otherwise poll /v1/changes/{id} every delay
        seconds.

        Args:
            change_id: Change ID of change to wait for.
            timeout: Maximum time in seconds to wait for the change to be
                ready. It may be None, in which case wait_change never times out.
            delay: If polling, this is the delay in seconds between attempts.

        Returns:
            The Change object being waited on.

        Raises:
            TimeoutError: If the maximum timeout is reached.
        """
        try:
            return self._wait_change_using_wait(change_id, timeout)
        except NotImplementedError:
            # Pebble server doesn't support wait endpoint, fall back to polling
            return self._wait_change_using_polling(change_id, timeout, delay)

    def _wait_change_using_wait(self, change_id: ChangeID, timeout: Optional[float]):
        """Wait for a change to be ready using the wait-change API."""
        deadline = time.time() + timeout if timeout is not None else 0

        # Hit the wait endpoint every Client.timeout-1 seconds to avoid long
        # requests (the -1 is to ensure it wakes up before the socket timeout)
        while True:
            this_timeout = max(self.timeout - 1, 1)  # minimum of 1 second
            if timeout is not None:
                time_remaining = deadline - time.time()
                if time_remaining <= 0:
                    break
                # Wait the lesser of the time remaining and Client.timeout-1
                this_timeout = min(time_remaining, this_timeout)

            try:
                return self._wait_change(change_id, this_timeout)
            except TimeoutError:
                # Catch timeout from wait endpoint and loop to check deadline
                pass

        raise TimeoutError(f'timed out waiting for change {change_id} ({timeout} seconds)')

    def _wait_change(self, change_id: ChangeID, timeout: Optional[float] = None) -> Change:
        """Call the wait-change API endpoint directly."""
        query = {}
        if timeout is not None:
            query['timeout'] = _format_timeout(timeout)

        try:
            resp = self._request('GET', f'/v1/changes/{change_id}/wait', query)
        except APIError as e:
            if e.code == 404:
                raise NotImplementedError('server does not implement wait-change endpoint')
            if e.code == 504:
                raise TimeoutError(f'timed out waiting for change {change_id} ({timeout} seconds)')
            raise

        return Change.from_dict(resp['result'])

    def _wait_change_using_polling(self, change_id: ChangeID, timeout: Optional[float],
                                   delay: float):
        """Wait for a change to be ready by polling the get-change API."""
        deadline = time.time() + timeout if timeout is not None else 0

        while timeout is None or time.time() < deadline:
            change = self.get_change(change_id)
            if change.ready:
                return change

            time.sleep(delay)

        raise TimeoutError(f'timed out waiting for change {change_id} ({timeout} seconds)')

    def add_layer(
            self, label: str, layer: Union[str, 'LayerDict', Layer], *,
            combine: bool = False):
        """Dynamically add a new layer onto the Pebble configuration layers.

        If combine is False (the default), append the new layer as the top
        layer with the given label. If combine is True and the label already
        exists, the two layers are combined into a single one considering the
        layer override rules; if the layer doesn't exist, it is added as usual.
        """
        if not isinstance(label, str):
            raise TypeError(f'label must be a str, not {type(label).__name__}')

        if isinstance(layer, str):
            layer_yaml = layer
        elif isinstance(layer, dict):
            layer_yaml = Layer(layer).to_yaml()
        elif isinstance(layer, Layer):
            layer_yaml = layer.to_yaml()
        else:
            raise TypeError(
                f'layer must be str, dict, or pebble.Layer, not {type(layer).__name__}')

        body = {
            'action': 'add',
            'combine': combine,
            'label': label,
            'format': 'yaml',
            'layer': layer_yaml,
        }
        self._request('POST', '/v1/layers', body=body)

    def get_plan(self) -> Plan:
        """Get the Pebble plan (contains combined layer configuration)."""
        resp = self._request('GET', '/v1/plan', {'format': 'yaml'})
        return Plan(resp['result'])

    def get_services(self, names: Optional[Iterable[str]] = None) -> List[ServiceInfo]:
        """Get the service status for the configured services.

        If names is specified, only fetch the service status for the services
        named.
        """
        query = None
        if names is not None:
            query = {'names': ','.join(names)}
        resp = self._request('GET', '/v1/services', query)
        return [ServiceInfo.from_dict(info) for info in resp['result']]

    @typing.overload
    def pull(self, path: str, *, encoding: None) -> BinaryIO:  # noqa
        ...

    @typing.overload
    def pull(self, path: str, *, encoding: str = 'utf-8') -> TextIO:  # noqa
        ...

    def pull(self,
             path: str,
             *,
             encoding: Optional[str] = 'utf-8') -> Union[BinaryIO, TextIO]:
        """Read a file's content from the remote system.

        Args:
            path: Path of the file to read from the remote system.
            encoding: Encoding to use for decoding the file's bytes to str,
                or None to specify no decoding.

        Returns:
            A readable file-like object, whose read() method will return str
            objects decoded according to the specified encoding, or bytes if
            encoding is None.

        Raises:
            PathError: If there was an error reading the file at path, for
                example, if the file doesn't exist or is a directory.
        """
        query = {
            'action': 'read',
            'path': path,
        }
        headers = {'Accept': 'multipart/form-data'}
        response = self._request_raw('GET', '/v1/files', query, headers)

        options = self._ensure_content_type(response.headers, 'multipart/form-data')
        boundary = options.get('boundary', '')
        if not boundary:
            raise ProtocolError(f'invalid boundary {boundary!r}')

        parser = _FilesParser(boundary)

        while True:
            chunk = response.read(self._chunk_size)
            if not chunk:
                break
            parser.feed(chunk)

        resp = parser.get_response()
        if resp is None:
            raise ProtocolError('no "response" field in multipart body')
        self._raise_on_path_error(resp, path)

        filenames = parser.filenames()
        if not filenames:
            raise ProtocolError('no file content in multipart response')
        elif len(filenames) > 1:
            raise ProtocolError('single file request resulted in a multi-file response')

        filename = filenames[0]
        if filename != path:
            raise ProtocolError(f'path not expected: {filename!r}')

        f = parser.get_file(path, encoding)

        parser.remove_files()
        return f

    @staticmethod
    def _raise_on_path_error(resp: '_FilesResponse', path: str):
        result = resp['result'] or []  # in case it's null instead of []
        paths = {item['path']: item for item in result}
        if path not in paths:
            raise ProtocolError(f'path not found in response metadata: {resp}')
        error = paths[path].get('error')
        if error:
            raise PathError(error['kind'], error['message'])

    def push(
            self, path: str, source: '_IOSource', *,
            encoding: str = 'utf-8', make_dirs: bool = False,
            permissions: Optional[int] = None,
            user_id: Optional[int] = None,
            user: Optional[str] = None,
            group_id: Optional[int] = None,
            group: Optional[str] = None):
        """Write content to a given file path on the remote system.

        Args:
            path: Path of the file to write to on the remote system.
            source: Source of data to write. This is either a concrete str or
                bytes instance, or a readable file-like object.
            encoding: Encoding to use for encoding source str to bytes, or
                strings read from source if it is a TextIO type. Ignored if
                source is bytes or BinaryIO.
            make_dirs: If True, create parent directories if they don't exist.
            permissions: Permissions (mode) to create file with (Pebble default
                is 0o644).
            user_id: User ID (UID) for file.
            user: Username for file. User's UID must match user_id if both are
                specified.
            group_id: Group ID (GID) for file.
            group: Group name for file. Group's GID must match group_id if
                both are specified.

        Raises:
            PathError: If there was an error writing the file to the path; for example, if the
                destination path doesn't exist and ``make_dirs`` is not used.
        """
        info = self._make_auth_dict(permissions, user_id, user, group_id, group)
        info['path'] = path
        if make_dirs:
            info['make-dirs'] = True
        metadata = {
            'action': 'write',
            'files': [info],
        }

        data, content_type = self._encode_multipart(metadata, path, source, encoding)

        headers = {
            'Accept': 'application/json',
            'Content-Type': content_type,
        }
        response = self._request_raw('POST', '/v1/files', None, headers, data)
        self._ensure_content_type(response.headers, 'application/json')
        resp = json.loads(response.read())
        # we need to cast the Dict[Any, Any] to _FilesResponse
        self._raise_on_path_error(typing.cast('_FilesResponse', resp), path)

    @staticmethod
    def _make_auth_dict(permissions: Optional[int],
                        user_id: Optional[int],
                        user: Optional[str],
                        group_id: Optional[int],
                        group: Optional[str]) -> '_AuthDict':
        d: _AuthDict = {}
        if permissions is not None:
            d['permissions'] = format(permissions, '03o')
        if user_id is not None:
            d['user-id'] = user_id
        if user is not None:
            d['user'] = user
        if group_id is not None:
            d['group-id'] = group_id
        if group is not None:
            d['group'] = group
        return d

    def _encode_multipart(self, metadata: Dict[str, Any], path: str,
                          source: '_IOSource', encoding: str):
        # Python's stdlib mime/multipart handling is screwy and doesn't handle
        # binary properly, so roll our own.
        if isinstance(source, str):
            source_io: _AnyStrFileLikeIO = io.StringIO(source)
        elif isinstance(source, bytes):
            source_io: _AnyStrFileLikeIO = io.BytesIO(source)
        else:
            source_io: _AnyStrFileLikeIO = source
        boundary = binascii.hexlify(os.urandom(16))
        path_escaped = path.replace('"', '\\"').encode('utf-8')  # NOQA: test_quote_backslashes
        content_type = f"multipart/form-data; boundary=\"{boundary.decode('utf-8')}\""  # NOQA: test_quote_backslashes

        def generator() -> Generator[bytes, None, None]:
            yield b''.join([
                b'--', boundary, b'\r\n',
                b'Content-Type: application/json\r\n',
                b'Content-Disposition: form-data; name="request"\r\n',
                b'\r\n',
                json.dumps(metadata).encode('utf-8'), b'\r\n',
                b'--', boundary, b'\r\n',
                b'Content-Type: application/octet-stream\r\n',
                b'Content-Disposition: form-data; name="files"; filename="',
                path_escaped, b'"\r\n',
                b'\r\n',
            ])

            content: Union[str, bytes] = source_io.read(self._chunk_size)
            while content:
                if isinstance(content, str):
                    content = content.encode(encoding)
                yield content
                content = source_io.read(self._chunk_size)

            yield b''.join([
                b'\r\n',
                b'--', boundary, b'--\r\n',
            ])

        return generator(), content_type

    def list_files(self, path: str, *, pattern: Optional[str] = None,
                   itself: bool = False) -> List[FileInfo]:
        """Return list of directory entries from given path on remote system.

        Despite the name, this method returns a list of files *and*
        directories, similar to :func:`os.listdir` or :func:`os.scandir`.

        Args:
            path: Path of the directory to list, or path of the file to return
                information about.
            pattern: If specified, filter the list to just the files that match,
                for example ``*.txt``.
            itself: If path refers to a directory, return information about the
                directory itself, rather than its contents.

        Raises:
            PathError: if there was an error listing the directory; for example, if the directory
                does not exist.
        """
        query = {
            'action': 'list',
            'path': path,
        }
        if pattern:
            query['pattern'] = pattern
        if itself:
            query['itself'] = 'true'
        resp = self._request('GET', '/v1/files', query)
        result = resp['result'] or []  # in case it's null instead of []
        return [FileInfo.from_dict(d) for d in result]

    def make_dir(
            self, path: str, *, make_parents: bool = False,
            permissions: Optional[int] = None,
            user_id: Optional[int] = None,
            user: Optional[str] = None,
            group_id: Optional[int] = None,
            group: Optional[str] = None):
        """Create a directory on the remote system with the given attributes.

        Args:
            path: Path of the directory to create on the remote system.
            make_parents: If True, create parent directories if they don't exist.
            permissions: Permissions (mode) to create directory with (Pebble
                default is 0o755).
            user_id: User ID (UID) for directory.
            user: Username for directory. User's UID must match user_id if
                both are specified.
            group_id: Group ID (GID) for directory.
            group: Group name for directory. Group's GID must match group_id
                if both are specified.

        Raises:
            PathError: if there was an error making the directory; for example, if the parent path
                does not exist, and ``make_parents`` is not used.
        """
        info = self._make_auth_dict(permissions, user_id, user, group_id, group)
        info['path'] = path
        if make_parents:
            info['make-parents'] = True
        body = {
            'action': 'make-dirs',
            'dirs': [info],
        }
        resp = self._request('POST', '/v1/files', None, body)
        self._raise_on_path_error(typing.cast('_FilesResponse', resp), path)

    def remove_path(self, path: str, *, recursive: bool = False):
        """Remove a file or directory on the remote system.

        Args:
            path: Path of the file or directory to delete from the remote system.
            recursive: If True, and path is a directory, recursively delete it and
                       everything under it. If path is a file, delete the file. In
                       either case, do nothing if the file or directory does not
                       exist. Behaviourally similar to ``rm -rf <file|dir>``.

        Raises:
            pebble.PathError: If a relative path is provided, or if `recursive` is False
                and the file or directory cannot be removed (it does not exist or is not empty).
        """
        info: Dict[str, Any] = {'path': path}
        if recursive:
            info['recursive'] = True
        body = {
            'action': 'remove',
            'paths': [info],
        }
        resp = self._request('POST', '/v1/files', None, body)
        self._raise_on_path_error(typing.cast('_FilesResponse', resp), path)

    # Exec I/O is str if encoding is provided (the default)
    @typing.overload
    def exec(  # noqa
        self,
        command: List[str],
        *,
        service_context: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        working_dir: Optional[str] = None,
        timeout: Optional[float] = None,
        user_id: Optional[int] = None,
        user: Optional[str] = None,
        group_id: Optional[int] = None,
        group: Optional[str] = None,
        stdin: Optional[Union[str, TextIO]] = None,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
        encoding: str = 'utf-8',
        combine_stderr: bool = False
    ) -> ExecProcess[str]:
        ...

    # Exec I/O is bytes if encoding is explicitly set to None
    @typing.overload
    def exec(  # noqa
        self,
        command: List[str],
        *,
        service_context: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        working_dir: Optional[str] = None,
        timeout: Optional[float] = None,
        user_id: Optional[int] = None,
        user: Optional[str] = None,
        group_id: Optional[int] = None,
        group: Optional[str] = None,
        stdin: Optional[Union[bytes, BinaryIO]] = None,
        stdout: Optional[BinaryIO] = None,
        stderr: Optional[BinaryIO] = None,
        encoding: None = None,
        combine_stderr: bool = False
    ) -> ExecProcess[bytes]:
        ...

    def exec(
        self,
        command: List[str],
        *,
        service_context: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        working_dir: Optional[str] = None,
        timeout: Optional[float] = None,
        user_id: Optional[int] = None,
        user: Optional[str] = None,
        group_id: Optional[int] = None,
        group: Optional[str] = None,
        stdin: Optional[Union[str, bytes, TextIO, BinaryIO]] = None,
        stdout: Optional[Union[TextIO, BinaryIO]] = None,
        stderr: Optional[Union[TextIO, BinaryIO]] = None,
        encoding: Optional[str] = 'utf-8',
        combine_stderr: bool = False
    ) -> ExecProcess[Any]:
        r"""Execute the given command on the remote system.

        Two method signatures are shown because this method returns an
        :class:`ExecProcess` that deals with strings if ``encoding`` is
        specified (the default ), or one that deals with bytes if ``encoding``
        is set to ``None``.

        Most of the parameters are explained in the "Parameters" section
        below, however, input/output handling is a bit more complex. Some
        examples are shown below::

            # Simple command with no output; just check exit code
            >>> process = client.exec(['send-emails'])
            >>> process.wait()

            # Fetch output as string
            >>> process = client.exec(['python3', '--version'])
            >>> version, _ = process.wait_output()
            >>> print(version)
            Python 3.8.10

            # Fetch both stdout and stderr as strings
            >>> process = client.exec(['pg_dump', '-s', ...])
            >>> schema, logs = process.wait_output()

            # Stream input from a string and write output to files
            >>> stdin = 'foo\nbar\n'
            >>> with open('out.txt', 'w') as out, open('err.txt', 'w') as err:
            ...     process = client.exec(['awk', '{ print toupper($0) }'],
            ...                           stdin=stdin, stdout=out, stderr=err)
            ...     process.wait()
            >>> open('out.txt').read()
            'FOO\nBAR\n'
            >>> open('err.txt').read()
            ''

            # Real-time streaming using ExecProcess.stdin and ExecProcess.stdout
            >>> process = client.exec(['cat'])
            >>> def stdin_thread():
            ...     for line in ['one\n', '2\n', 'THREE\n']:
            ...         process.stdin.write(line)
            ...         process.stdin.flush()
            ...         time.sleep(1)
            ...     process.stdin.close()
            ...
            >>> threading.Thread(target=stdin_thread).start()
            >>> for line in process.stdout:
            ...     print(datetime.datetime.now().strftime('%H:%M:%S'), repr(line))
            ...
            16:20:26 'one\n'
            16:20:27 '2\n'
            16:20:28 'THREE\n'
            >>> process.wait()  # will return immediately as stdin was closed

            # Show exception raised for non-zero return code
            >>> process = client.exec(['ls', 'notexist'])
            >>> out, err = process.wait_output()
            Traceback (most recent call last):
              ...
            ExecError: "ls" returned exit code 2
            >>> exc = sys.last_value
            >>> exc.exit_code
            2
            >>> exc.stdout
            ''
            >>> exc.stderr
            "ls: cannot access 'notfound': No such file or directory\n"

        Args:
            command: Command to execute: the first item is the name (or path)
                of the executable, the rest of the items are the arguments.
            service_context: If specified, run the command in the context of
                this service. Specifically, inherit its environment variables,
                user/group settings, and working directory. The other exec
                options will override the service context; ``environment``
                will be merged on top of the service's.
            environment: Environment variables to pass to the process.
            working_dir: Working directory to run the command in. If not set,
                Pebble uses the target user's $HOME directory (and if the user
                argument is not set, $HOME of the user Pebble is running as).
            timeout: Timeout in seconds for the command execution, after which
                the process will be terminated. If not specified, the
                execution never times out.
            user_id: User ID (UID) to run the process as.
            user: Username to run the process as. User's UID must match
                user_id if both are specified.
            group_id: Group ID (GID) to run the process as.
            group: Group name to run the process as. Group's GID must match
                group_id if both are specified.
            stdin: A string or readable file-like object that is sent to the
                process's standard input. If not set, the caller can write
                input to :attr:`ExecProcess.stdin` to stream input to the
                process.
            stdout: A writable file-like object that the process's standard
                output is written to. If not set, the caller can use
                :meth:`ExecProcess.wait_output` to capture output as a string,
                or read from :meth:`ExecProcess.stdout` to stream output from
                the process.
            stderr: A writable file-like object that the process's standard
                error is written to. If not set, the caller can use
                :meth:`ExecProcess.wait_output` to capture error output as a
                string, or read from :meth:`ExecProcess.stderr` to stream
                error output from the process. Must be None if combine_stderr
                is True.
            encoding: If encoding is set (the default is UTF-8), the types
                read or written to stdin/stdout/stderr are str, and encoding
                is used to encode them to bytes. If encoding is None, the
                types read or written are raw bytes.
            combine_stderr: If True, process's stderr output is combined into
                its stdout (the stderr argument must be None). If False,
                separate streams are used for stdout and stderr.

        Returns:
            A Process object representing the state of the running process.
            To wait for the command to finish, the caller will typically call
            :meth:`ExecProcess.wait` if stdout/stderr were provided as
            arguments to :meth:`exec`, or :meth:`ExecProcess.wait_output` if
            not.

        Raises:
            APIError: if an error occurred communicating with pebble, or if the command is not
                found.
            ExecError: if the command exits with a non-zero exit code.
        """
        if not isinstance(command, list) or not all(isinstance(s, str) for s in command):
            raise TypeError(f'command must be a list of str, not {type(command).__name__}')
        if len(command) < 1:
            raise ValueError('command must contain at least one item')

        if stdin is not None:
            if isinstance(stdin, str):
                if encoding is None:
                    raise ValueError('encoding must be set if stdin is str')
                stdin = io.BytesIO(stdin.encode(encoding))
            elif isinstance(stdin, bytes):
                if encoding is not None:
                    raise ValueError('encoding must be None if stdin is bytes')
                stdin = io.BytesIO(stdin)
            elif not hasattr(stdin, 'read'):
                raise TypeError('stdin must be str, bytes, or a readable file-like object')

        if combine_stderr and stderr is not None:
            raise ValueError('stderr must be None if combine_stderr is True')

        body = {
            'command': command,
            'service-context': service_context,
            'environment': environment or {},
            'working-dir': working_dir,
            'timeout': _format_timeout(timeout) if timeout is not None else None,
            'user-id': user_id,
            'user': user,
            'group-id': group_id,
            'group': group,
            'split-stderr': not combine_stderr,
        }
        resp = self._request('POST', '/v1/exec', body=body)
        change_id = resp['change']
        task_id = resp['result']['task-id']

        stderr_ws: Optional['_WebSocket'] = None
        try:
            control_ws = self._connect_websocket(task_id, 'control')
            stdio_ws = self._connect_websocket(task_id, 'stdio')
            if not combine_stderr:
                stderr_ws = self._connect_websocket(task_id, 'stderr')
        except websocket.WebSocketException as e:  # type: ignore
            # Error connecting to websockets, probably due to the exec/change
            # finishing early with an error. Call wait_change to pick that up.
            change = self.wait_change(ChangeID(change_id))
            if change.err:
                raise ChangeError(change.err, change)
            raise ConnectionError(f'unexpected error connecting to websockets: {e}')

        cancel_stdin: Optional[Callable[[], None]] = None
        cancel_reader: Optional[int] = None
        threads: List[threading.Thread] = []

        if stdin is not None:
            if _has_fileno(stdin):
                # Create a pipe so _reader_to_websocket can select() on the
                # reader as well as this cancel_reader; when we write anything
                # to cancel_writer it'll trigger the select and end the thread.
                cancel_reader, cancel_writer = os.pipe()

                def _cancel_stdin():
                    os.write(cancel_writer, b'x')  # doesn't matter what we write
                    os.close(cancel_writer)
                cancel_stdin = _cancel_stdin

            t = _start_thread(_reader_to_websocket, stdin, stdio_ws, encoding, cancel_reader)
            threads.append(t)
            process_stdin = None
        else:
            process_stdin = _WebsocketWriter(stdio_ws)
            if encoding is not None:
                process_stdin = io.TextIOWrapper(
                    process_stdin, encoding=encoding, newline='')  # type: ignore

        if stdout is not None:
            t = _start_thread(_websocket_to_writer, stdio_ws, stdout, encoding)
            threads.append(t)
            process_stdout = None
        else:
            process_stdout = _WebsocketReader(stdio_ws)
            if encoding is not None:
                process_stdout = io.TextIOWrapper(
                    process_stdout, encoding=encoding, newline='')  # type: ignore

        process_stderr = None
        if not combine_stderr:
            if stderr is not None:
                t = _start_thread(_websocket_to_writer, stderr_ws, stderr, encoding)
                threads.append(t)
            else:
                ws = typing.cast('_WebSocket', stderr_ws)
                process_stderr = _WebsocketReader(ws)
                if encoding is not None:
                    process_stderr = io.TextIOWrapper(
                        process_stderr, encoding=encoding, newline='')  # type: ignore

        process: ExecProcess[Any] = ExecProcess(
            stdin=process_stdin,  # type: ignore
            stdout=process_stdout,  # type: ignore
            stderr=process_stderr,  # type: ignore
            client=self,
            timeout=timeout,
            stdio_ws=stdio_ws,
            stderr_ws=stderr_ws,
            control_ws=control_ws,
            command=command,
            encoding=encoding,
            change_id=ChangeID(change_id),
            cancel_stdin=cancel_stdin,
            cancel_reader=cancel_reader,
            threads=threads,
        )
        return process

    def _connect_websocket(self, task_id: str, websocket_id: str) -> '_WebSocket':
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.socket_path)
        url = self._websocket_url(task_id, websocket_id)
        ws: '_WebSocket' = websocket.WebSocket(skip_utf8_validation=True)  # type: ignore
        ws.connect(url, socket=sock)
        return ws

    def _websocket_url(self, task_id: str, websocket_id: str) -> str:
        base_url = self.base_url.replace('http://', 'ws://')
        url = f'{base_url}/v1/tasks/{task_id}/websocket/{websocket_id}'
        return url

    def send_signal(self, sig: Union[int, str], services: Iterable[str]):
        """Send the given signal to the list of services named.

        Args:
            sig: Name or number of signal to send, for example ``"SIGHUP"``, ``1``, or
                ``signal.SIGHUP``.
            services: Non-empty list of service names to send the signal to.

        Raises:
            APIError: If any of the services are not in the plan or are not
                currently running.
        """
        if isinstance(services, (str, bytes)) or not hasattr(services, '__iter__'):
            raise TypeError('services must be of type Iterable[str], '
                            'not {}'.format(type(services).__name__))
        for s in services:
            if not isinstance(s, str):
                raise TypeError(f'service names must be str, not {type(s).__name__}')

        if isinstance(sig, int):
            sig = signal.Signals(sig).name
        body = {
            'signal': sig,
            'services': services,
        }
        self._request('POST', '/v1/signals', body=body)

    def get_checks(
        self,
        level: Optional[CheckLevel] = None,
        names: Optional[Iterable[str]] = None
    ) -> List[CheckInfo]:
        """Get the check status for the configured checks.

        Args:
            level: Optional check level to query for (default is to fetch
                checks with any level).
            names: Optional list of check names to query for (default is to
                fetch all checks).

        Returns:
            List of :class:`CheckInfo` objects.
        """
        query = {}
        if level is not None:
            query['level'] = level.value
        if names:
            query['names'] = list(names)
        resp = self._request('GET', '/v1/checks', query)
        return [CheckInfo.from_dict(info) for info in resp['result']]


class _FilesParser:
    """A limited purpose multi-part parser backed by files for memory efficiency."""

    def __init__(self, boundary: Union[bytes, str]):
        self._response: Optional[_FilesResponse] = None  # externally managed
        self._part_type: Optional[Literal["response", "files"]] = None  # externally managed
        self._headers: Optional[email.message.Message] = None  # externally managed
        self._files: Dict[str, _Tempfile] = {}

        # Prepare the MIME multipart boundary line patterns.
        if isinstance(boundary, str):
            boundary = boundary.encode()

        # State vars, as we may enter the feed() function multiple times.
        self._response_data = bytearray()

        self._max_lookahead = 8 * 1024 * 1024

        self._parser = _MultipartParser(
            boundary,
            self._process_header,
            self._process_body,
            max_lookahead=self._max_lookahead)

        # RFC 2046 says that the boundary string needs to be preceded by a CRLF.
        # Unfortunately, the request library's header parsing logic strips off one of
        # these, so we'll prime the parser buffer with that missing sequence.
        self._parser.feed(b'\r\n')

    def _process_header(self, data: bytes):
        parser = email.parser.BytesFeedParser()
        parser.feed(data)
        self._headers = parser.close()

        content_disposition = self._headers.get_content_disposition()
        if content_disposition != 'form-data':
            raise ProtocolError(
                f'unexpected content disposition: {content_disposition!r}')

        name = self._headers.get_param('name', header='content-disposition')
        if name == 'files':
            filename = self._headers.get_filename()
            if filename is None:
                raise ProtocolError('multipart "files" part missing filename')
            self._prepare_tempfile(filename)
        elif name != 'response':
            raise ProtocolError(
                f'unexpected name in content-disposition header: {name!r}')

        self._part_type = typing.cast('Literal["response", "files"]', name)

    def _process_body(self, data: bytes, done: bool = False):
        if self._part_type == 'response':
            self._response_data.extend(data)
            if done:
                if len(self._response_data) > self._max_lookahead:
                    raise ProtocolError('response end marker not found')
                resp = json.loads(self._response_data.decode())
                self._response = typing.cast('_FilesResponse', resp)
                self._response_data = bytearray()
        elif self._part_type == 'files':
            if done:
                # This is the final write.
                outfile = self._get_open_tempfile()
                outfile.write(data)
                outfile.close()
                self._headers = None
            else:
                # Not the end of file data yet. Don't open/close file for intermediate writes
                outfile = self._get_open_tempfile()
                outfile.write(data)

    def remove_files(self):
        """Remove all temporary files on disk."""
        for file in self._files.values():
            os.unlink(file.name)
        self._files.clear()

    def feed(self, data: bytes):
        """Provide more data to the running parser."""
        self._parser.feed(data)

    def _prepare_tempfile(self, filename: str):
        tf = tempfile.NamedTemporaryFile(delete=False)
        self._files[filename] = tf  # type: ignore # we have a custom protocol for it
        self.current_filename = filename

    def _get_open_tempfile(self):
        return self._files[self.current_filename]

    def get_response(self) -> Optional['_FilesResponse']:
        """Return the deserialized JSON object from the multipart "response" field."""
        return self._response

    def filenames(self):
        """Return a list of filenames from the "files" parts of the response."""
        return list(self._files.keys())

    def get_file(self, path: str, encoding: Optional[str]) -> '_TextOrBinaryIO':
        """Return an open file object containing the data."""
        mode = 'r' if encoding else 'rb'
        # We're using text-based file I/O purely for file encoding purposes, not for
        # newline normalization.  newline='' serves the line endings as-is.
        newline = '' if encoding else None
        file_io = open(self._files[path].name, mode,
                       encoding=encoding, newline=newline)
        # open() returns IO[Any]
        return typing.cast('_TextOrBinaryIO', file_io)


class _MultipartParser:
    def __init__(
            self,
            marker: bytes,
            handle_header: '_HeaderHandler',
            handle_body: '_BodyHandler',
            max_lookahead: int = 0,
            max_boundary_length: int = 0):
        r"""Configures a parser for mime multipart messages.

        Args:
            marker: the multipart boundary marker (i.e. in "\r\n--<marker>--\r\n")

            handle_header(data): called once with the entire contents of a part
            header as encountered in data fed to the parser

            handle_body(data, done=False): called incrementally as part body
            data is fed into the parser - its "done" parameter is set to true when
            the body is complete.

            max_lookahead: maximum amount of bytes to buffer when searching for a complete header.

            max_boundary_length: maximum number of bytes that can make up a part
            boundary (e.g. \r\n--<marker>--\r\n")
        """
        self._marker = marker
        self._handle_header = handle_header
        self._handle_body = handle_body
        self._max_lookahead = max_lookahead
        self._max_boundary_length = max_boundary_length

        self._buf = bytearray()
        self._pos = 0  # current position in buf
        self._done = False  # whether we have found the terminal boundary and are done parsing
        self._header_terminator = b'\r\n\r\n'

        # RFC 2046 notes optional "linear whitespace" (e.g. [ \t]+) after the boundary pattern
        # and the optional "--" suffix.  The boundaries strings can be constructed as follows:
        #
        #     boundary = \r\n--<marker>[ \t]+\r\n
        #     terminal_boundary = \r\n--<marker>--[ \t]+\r\n
        #
        # 99 is arbitrarily chosen to represent a max number of linear
        # whitespace characters to help avoid wrongly writing boundary
        # characters into a (temporary) file.
        if not max_boundary_length:
            self._max_boundary_length = len(b'\r\n--' + marker + b'--\r\n') + 99

    def feed(self, data: bytes):
        """Feeds data incrementally into the parser."""
        if self._done:
            return
        self._buf.extend(data)

        while True:
            # seek to a boundary if we aren't already on one
            i, n, self._done = _next_part_boundary(self._buf, self._marker)
            if i == -1 or self._done:
                return  # waiting for more data or terminal boundary reached

            if self._pos == 0:
                # parse the part header
                if self._max_lookahead and len(self._buf) - self._pos > self._max_lookahead:
                    raise ProtocolError('header terminator not found')
                term_index = self._buf.find(self._header_terminator)
                if term_index == -1:
                    return  # waiting for more data

                start = i + n
                # data includes the double CRLF at the end of the header.
                end = term_index + len(self._header_terminator)

                self._handle_header(self._buf[start:end])
                self._pos = end
            else:
                # parse the part body
                ii, _, self._done = _next_part_boundary(self._buf, self._marker, start=self._pos)
                safe_bound = max(0, len(self._buf) - self._max_boundary_length)
                if ii != -1:
                    # part body is finished
                    self._handle_body(self._buf[self._pos:ii], done=True)
                    self._buf = self._buf[ii:]
                    self._pos = 0
                    if self._done:
                        return  # terminal boundary reached
                elif safe_bound > self._pos:
                    # write partial body data
                    data = self._buf[self._pos:safe_bound]
                    self._pos = safe_bound
                    self._handle_body(data)
                    return  # waiting for more data
                else:
                    return  # waiting for more data


def _next_part_boundary(buf: bytes, marker: bytes, start: int = 0
                        ) -> Tuple[int, int, bool]:
    """Returns the index of the next boundary marker in buf beginning at start.

    Returns:
        (index, length, is_terminal) or (-1, -1, False) if no boundary is found.
    """
    prefix = b'\r\n--' + marker
    suffix = b'\r\n'
    terminal_midfix = b'--'

    i = buf.find(prefix, start)
    if i == -1:
        return -1, -1, False

    pos = i + len(prefix)
    is_terminal = False
    if buf[pos:].startswith(terminal_midfix):
        is_terminal = True
        pos += len(terminal_midfix)

    # Note: RFC 2046 notes optional "linear whitespace" (e.g. [ \t]) after the boundary pattern
    # and the optional "--" suffix.
    tail = buf[pos:]
    for c in tail:
        if c not in b' \t':
            break
        pos += 1

    if buf[pos:].startswith(suffix):
        pos += len(suffix)
        return i, pos - i, is_terminal
    return -1, -1, False
