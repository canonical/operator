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
import cgi
import copy
import datetime
import email.parser
import enum
import http.client
import io
import json
import logging
import os
import re
import select
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import types
import typing
import urllib.error
import urllib.parse
import urllib.request
import warnings

from ops._private import yaml
from ops._vendor import websocket

logger = logging.getLogger(__name__)

_not_provided = object()


class _UnixSocketConnection(http.client.HTTPConnection):
    """Implementation of HTTPConnection that connects to a named Unix socket."""

    def __init__(self, host, timeout=_not_provided, socket_path=None):
        if timeout is _not_provided:
            super().__init__(host)
        else:
            super().__init__(host, timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        """Override connect to use Unix socket (instead of TCP socket)."""
        if not hasattr(socket, 'AF_UNIX'):
            raise NotImplementedError('Unix sockets not supported on {}'.format(sys.platform))
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        if self.timeout is not _not_provided:
            self.sock.settimeout(self.timeout)


class _UnixSocketHandler(urllib.request.AbstractHTTPHandler):
    """Implementation of HTTPHandler that uses a named Unix socket."""

    def __init__(self, socket_path):
        super().__init__()
        self.socket_path = socket_path

    def http_open(self, req):
        """Override http_open to use a Unix socket connection (instead of TCP)."""
        return self.do_open(_UnixSocketConnection, req, socket_path=self.socket_path)


# Matches yyyy-mm-ddTHH:MM:SS(.sss)ZZZ
_TIMESTAMP_RE = re.compile(
    r'(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?(.*)')

# Matches [-+]HH:MM
_TIMEOFFSET_RE = re.compile(r'([-+])(\d{2}):(\d{2})')


def _parse_timestamp(s):
    """Parse timestamp from Go-encoded JSON.

    This parses RFC3339 timestamps (which are a subset of ISO8601 timestamps)
    that Go's encoding/json package produces for time.Time values.

    Unfortunately we can't use datetime.fromisoformat(), as that does not
    support more than 6 digits for the fractional second, nor the 'Z' for UTC.
    Also, it was only introduced in Python 3.7.
    """
    match = _TIMESTAMP_RE.match(s)
    if not match:
        raise ValueError('invalid timestamp {!r}'.format(s))
    y, m, d, hh, mm, ss, sfrac, zone = match.groups()

    if zone in ('Z', 'z'):
        tz = datetime.timezone.utc
    else:
        match = _TIMEOFFSET_RE.match(zone)
        if not match:
            raise ValueError('invalid timestamp {!r}'.format(s))
        sign, zh, zm = match.groups()
        tz_delta = datetime.timedelta(hours=int(zh), minutes=int(zm))
        tz = datetime.timezone(tz_delta if sign == '+' else -tz_delta)

    microsecond = round(float(sfrac or '0') * 1000000)

    return datetime.datetime(int(y), int(m), int(d), int(hh), int(mm), int(ss),
                             microsecond=microsecond, tzinfo=tz)


def _format_timeout(timeout: float):
    """Format timeout for use in the Pebble API.

    The format is in seconds with a millisecond resolution and an 's' suffix,
    as accepted by the Pebble API (which uses Go's time.ParseDuration).
    """
    return '{:.3f}s'.format(timeout)


def _json_loads(s: typing.Union[str, bytes]) -> typing.Dict:
    """Like json.loads(), but handle str or bytes.

    This is needed because an HTTP response's read() method returns bytes on
    Python 3.5, and json.load doesn't handle bytes.
    """
    if isinstance(s, bytes):
        s = s.decode('utf-8')
    return json.loads(s)


def _start_thread(target, *args, **kwargs) -> threading.Thread:
    """Helper to simplify starting a thread."""
    thread = threading.Thread(target=target, args=args, kwargs=kwargs)
    thread.start()
    return thread


class Error(Exception):
    """Base class of most errors raised by the Pebble client."""

    def __repr__(self):
        return '<{}.{} {}>'.format(type(self).__module__, type(self).__name__, self.args)

    def name(self):
        """Return a string representation of the model plus class."""
        return '<{}.{}>'.format(type(self).__module__, type(self).__name__)

    def message(self):
        """Return the message passed as an argument."""
        return self.args[0]


class TimeoutError(TimeoutError, Error):
    """Raised when a polling timeout occurs."""


class ConnectionError(Error):
    """Raised when the Pebble client can't connect to the socket."""


class ProtocolError(Error):
    """Raised when there's a higher-level protocol error talking to Pebble."""


class PathError(Error):
    """Raised when there's an error with a specific path."""

    def __init__(self, kind: str, message: str):
        """This shouldn't be instantiated directly."""
        self.kind = kind
        self.message = message

    def __str__(self):
        return '{} - {}'.format(self.kind, self.message)

    def __repr__(self):
        return 'PathError({!r}, {!r})'.format(self.kind, self.message)


class APIError(Error):
    """Raised when an HTTP API error occurs talking to the Pebble server."""

    def __init__(self, body: typing.Dict, code: int, status: str, message: str):
        """This shouldn't be instantiated directly."""
        super().__init__(message)  # Makes str(e) return message
        self.body = body
        self.code = code
        self.status = status
        self.message = message

    def __repr__(self):
        return 'APIError({!r}, {!r}, {!r}, {!r})'.format(
            self.body, self.code, self.status, self.message)


class ChangeError(Error):
    """Raised by actions when a change is ready but has an error.

    For example, this happens when you attempt to start an already-started
    service:

    cannot perform the following tasks:
    - Start service "test" (service "test" was previously started)
    """

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
            parts.append('\n----- Logs from task {} -----\n'.format(i))
            parts.append('\n'.join(task.log))

        if len(parts) > 1:
            parts.append('\n-----')

        return ''.join(parts)

    def __repr__(self):
        return 'ChangeError({!r}, {!r})'.format(self.err, self.change)


class ExecError(Error):
    """Raised when a :meth:`Client.exec` command returns a non-zero exit code.

    Attributes:
        command: Command line of command being executed.
        exit_code: The process's exit code. This will always be non-zero.
        stdout: If :meth:`ExecProcess.wait_output` was being called, this is
            the captured stdout as a str (or bytes if encoding was None). If
            :meth:`ExecProcess.wait` was being called, this is None.
        stderr: If :meth:`ExecProcess.wait_output` was being called and
            combine_stderr was False, this is the captured stderr as a str (or
            bytes if encoding was None). If :meth:`ExecProcess.wait` was being
            called or combine_stderr was True, this is None.
    """

    STR_MAX_OUTPUT = 1024

    def __init__(
        self,
        command: typing.List[str],
        exit_code: int,
        stdout: typing.Optional[typing.AnyStr],
        stderr: typing.Optional[typing.AnyStr],
    ):
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr

    def __str__(self):
        message = 'non-zero exit code {} executing {!r}'.format(
            self.exit_code, self.command)

        for name, out in [('stdout', self.stdout), ('stderr', self.stderr)]:
            if out is None:
                continue
            truncated = ' [truncated]' if len(out) > self.STR_MAX_OUTPUT else ''
            out = out[:self.STR_MAX_OUTPUT]
            message = '{}, {}={!r}{}'.format(message, name, out, truncated)

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
    def from_dict(cls, d: typing.Dict) -> 'SystemInfo':
        """Create new SystemInfo object from dict parsed from JSON."""
        return cls(version=d['version'])

    def __repr__(self):
        return 'SystemInfo(version={self.version!r})'.format(self=self)


class Warning:
    """Warning object."""

    def __init__(
        self,
        message: str,
        first_added: datetime.datetime,
        last_added: datetime.datetime,
        last_shown: typing.Optional[datetime.datetime],
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
    def from_dict(cls, d: typing.Dict) -> 'Warning':
        """Create new Warning object from dict parsed from JSON."""
        return cls(
            message=d['message'],
            first_added=_parse_timestamp(d['first-added']),
            last_added=_parse_timestamp(d['last-added']),
            last_shown=_parse_timestamp(d['last-shown']) if d.get('last-shown') else None,
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
    def from_dict(cls, d: typing.Dict) -> 'TaskProgress':
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
        return 'TaskID({!r})'.format(str(self))


class Task:
    """Task object."""

    def __init__(
        self,
        id: TaskID,
        kind: str,
        summary: str,
        status: str,
        log: typing.List[str],
        progress: TaskProgress,
        spawn_time: datetime.datetime,
        ready_time: typing.Optional[datetime.datetime],
        data: typing.Dict[str, typing.Any] = None,
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
    def from_dict(cls, d: typing.Dict) -> 'Task':
        """Create new Task object from dict parsed from JSON."""
        return cls(
            id=TaskID(d['id']),
            kind=d['kind'],
            summary=d['summary'],
            status=d['status'],
            log=d.get('log') or [],
            progress=TaskProgress.from_dict(d['progress']),
            spawn_time=_parse_timestamp(d['spawn-time']),
            ready_time=_parse_timestamp(d['ready-time']) if d.get('ready-time') else None,
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
        return 'ChangeID({!r})'.format(str(self))


class Change:
    """Change object."""

    def __init__(
        self,
        id: ChangeID,
        kind: str,
        summary: str,
        status: str,
        tasks: typing.List[Task],
        ready: bool,
        err: typing.Optional[str],
        spawn_time: datetime.datetime,
        ready_time: typing.Optional[datetime.datetime],
        data: typing.Dict[str, typing.Any] = None,
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
    def from_dict(cls, d: typing.Dict) -> 'Change':
        """Create new Change object from dict parsed from JSON."""
        return cls(
            id=ChangeID(d['id']),
            kind=d['kind'],
            summary=d['summary'],
            status=d['status'],
            tasks=[Task.from_dict(t) for t in d.get('tasks') or []],
            ready=d['ready'],
            err=d.get('err'),
            spawn_time=_parse_timestamp(d['spawn-time']),
            ready_time=_parse_timestamp(d['ready-time']) if d.get('ready-time') else None,
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
        d = yaml.safe_load(raw) or {}
        self._raw = raw
        self._services = {name: Service(name, service)
                          for name, service in d.get('services', {}).items()}
        self._checks = {name: Check(name, check)
                        for name, check in d.get('checks', {}).items()}

    @property
    def services(self):
        """This plan's services mapping (maps service name to Service).

        This property is currently read-only.
        """
        return self._services

    @property
    def checks(self):
        """This plan's checks mapping (maps check name to :class:`Check`).

        This property is currently read-only.
        """
        return self._checks

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """Convert this plan to its dict representation."""
        fields = [
            ('services', {name: service.to_dict() for name, service in self._services.items()}),
            ('checks', {name: check.to_dict() for name, check in self._checks.items()}),
        ]
        return {name: value for name, value in fields if value}

    def to_yaml(self) -> str:
        """Return this plan's YAML representation."""
        return yaml.safe_dump(self.to_dict())

    __str__ = to_yaml


class Layer:
    """Represents a Pebble configuration layer.

    The format of this is documented at
    https://github.com/canonical/pebble/#layer-specification.

    Attributes:
        summary: A summary of the purpose of this layer
        description: A long form description of this layer
        services: A mapping of name to :class:`Service` defined by this layer
        checks: A mapping of check to :class:`Check` defined by this layer
    """

    # This is how you do type annotations, but it is not supported by Python 3.5
    # summary: str
    # description: str
    # services: typing.Mapping[str, 'Service']

    def __init__(self, raw: typing.Union[str, typing.Dict] = None):
        if isinstance(raw, str):
            d = yaml.safe_load(raw) or {}
        else:
            d = raw or {}
        self.summary = d.get('summary', '')
        self.description = d.get('description', '')
        self.services = {name: Service(name, service)
                         for name, service in d.get('services', {}).items()}
        self.checks = {name: Check(name, check)
                       for name, check in d.get('checks', {}).items()}

    def to_yaml(self) -> str:
        """Convert this layer to its YAML representation."""
        return yaml.safe_dump(self.to_dict())

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """Convert this layer to its dict representation."""
        fields = [
            ('summary', self.summary),
            ('description', self.description),
            ('services', {name: service.to_dict() for name, service in self.services.items()}),
            ('checks', {name: check.to_dict() for name, check in self.checks.items()}),
        ]
        return {name: value for name, value in fields if value}

    def __repr__(self) -> str:
        return 'Layer({!r})'.format(self.to_dict())

    __str__ = to_yaml


class Service:
    """Represents a service description in a Pebble configuration layer."""

    def __init__(self, name: str, raw: typing.Dict = None):
        self.name = name
        raw = raw or {}
        self.summary = raw.get('summary', '')
        self.description = raw.get('description', '')
        self.startup = raw.get('startup', '')
        self.override = raw.get('override', '')
        self.command = raw.get('command', '')
        self.after = list(raw.get('after', []))
        self.before = list(raw.get('before', []))
        self.requires = list(raw.get('requires', []))
        self.environment = dict(raw.get('environment', {}))
        self.user = raw.get('user', '')
        self.user_id = raw.get('user-id')
        self.group = raw.get('group', '')
        self.group_id = raw.get('group-id')
        self.on_success = raw.get('on-success', '')
        self.on_failure = raw.get('on-failure', '')
        self.on_check_failure = dict(raw.get('on-check-failure', {}))
        self.backoff_delay = raw.get('backoff-delay', '')
        self.backoff_factor = raw.get('backoff-factor')
        self.backoff_limit = raw.get('backoff-limit', '')

    def to_dict(self) -> typing.Dict[str, typing.Any]:
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
            ('on-success', self.on_success),
            ('on-failure', self.on_failure),
            ('on-check-failure', self.on_check_failure),
            ('backoff-delay', self.backoff_delay),
            ('backoff-factor', self.backoff_factor),
            ('backoff-limit', self.backoff_limit),
        ]
        return {name: value for name, value in fields if value}

    def __repr__(self) -> str:
        return 'Service({!r})'.format(self.to_dict())

    def __eq__(self, other: typing.Union[typing.Dict, 'Service']) -> bool:
        """Compare this service description to another."""
        if isinstance(other, dict):
            return self.to_dict() == other
        elif isinstance(other, Service):
            return self.to_dict() == other.to_dict()
        else:
            raise ValueError(
                "Cannot compare pebble.Service to {}".format(type(other))
            )


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
        startup: typing.Union[ServiceStartup, str],
        current: typing.Union[ServiceStatus, str],
    ):
        self.name = name
        self.startup = startup
        self.current = current

    def is_running(self) -> bool:
        """Return True if this service is running (in the active state)."""
        return self.current == ServiceStatus.ACTIVE

    @classmethod
    def from_dict(cls, d: typing.Dict) -> 'ServiceInfo':
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

    def __init__(self, name: str, raw: typing.Dict = None):
        self.name = name
        raw = raw or {}
        self.override = raw.get('override', '')
        try:
            self.level = CheckLevel(raw.get('level', ''))
        except ValueError:
            self.level = raw.get('level')
        self.period = raw.get('period', '')
        self.timeout = raw.get('timeout', '')
        self.threshold = raw.get('threshold')

        http = raw.get('http')
        if http is not None:
            http = copy.deepcopy(http)
        self.http = http

        tcp = raw.get('tcp')
        if tcp is not None:
            tcp = copy.deepcopy(tcp)
        self.tcp = tcp

        exec_ = raw.get('exec')
        if exec_ is not None:
            exec_ = copy.deepcopy(exec_)
        self.exec = exec_

    def to_dict(self) -> typing.Dict[str, typing.Any]:
        """Convert this check object to its dict representation."""
        fields = [
            ('override', self.override),
            ('level', self.level.value),
            ('period', self.period),
            ('timeout', self.timeout),
            ('threshold', self.threshold),
            ('http', self.http),
            ('tcp', self.tcp),
            ('exec', self.exec),
        ]
        return {name: value for name, value in fields if value}

    def __repr__(self) -> str:
        return 'Check({!r})'.format(self.to_dict())

    def __eq__(self, other: typing.Union[typing.Dict, 'Check']) -> bool:
        """Compare this check configuration to another."""
        if isinstance(other, dict):
            return self.to_dict() == other
        elif isinstance(other, Check):
            return self.to_dict() == other.to_dict()
        else:
            raise ValueError("Cannot compare pebble.Check to {}".format(type(other)))


class CheckLevel(enum.Enum):
    """Enum of check levels."""

    UNSET = ''
    ALIVE = 'alive'
    READY = 'ready'


class CheckStatus(enum.Enum):
    """Enum of check statuses."""

    UP = 'up'
    DOWN = 'down'


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

    def __init__(
        self,
        path: str,
        name: str,
        type: typing.Union['FileType', str],
        size: typing.Optional[int],
        permissions: int,
        last_modified: datetime.datetime,
        user_id: typing.Optional[int],
        user: typing.Optional[str],
        group_id: typing.Optional[int],
        group: typing.Optional[str],
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
    def from_dict(cls, d: typing.Dict) -> 'FileInfo':
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
            last_modified=_parse_timestamp(d['last-modified']),
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

    Attributes:
        name: The name of the check.
        level: The check level: :attr:`CheckLevel.ALIVE`,
            :attr:`CheckLevel.READY`, or None (level not set).
        status: The status of the check: :attr:`CheckStatus.UP` means the
            check is healthy (the number of failures is less than the
            threshold), :attr:`CheckStatus.DOWN` means the check is unhealthy
            (the number of failures has reached the threshold).
        failures: The number of failures since the check last succeeded (reset
            to zero if the check succeeds).
        threshold: The failure threshold, that is, how many consecutive
            failures for the check to be considered "down".
    """

    def __init__(
        self,
        name: str,
        level: typing.Optional[typing.Union[CheckLevel, str]],
        status: typing.Union[CheckStatus, str],
        failures: int = 0,
        threshold: int = 0,
    ):
        self.name = name
        self.level = level
        self.status = status
        self.failures = failures
        self.threshold = threshold

    @classmethod
    def from_dict(cls, d: typing.Dict) -> 'CheckInfo':
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


class ExecProcess:
    """Represents a process started by :meth:`Client.exec`.

    To avoid deadlocks, most users should use :meth:`wait_output` instead of
    reading and writing the :attr:`stdin`, :attr:`stdout`, and :attr:`stderr`
    attributes directly. Alternatively, users can pass stdin/stdout/stderr to
    :meth:`Client.exec`.

    This class should not be instantiated directly, only via
    :meth:`Client.exec`.

    Attributes:
        stdin: If the stdin argument was not passed to :meth:`Client.exec`,
            this is a writable file-like object the caller can use to stream
            input to the process. It is None if stdin was passed to
            :meth:`Client.exec`.
        stdout: If the stdout argument was not passed to :meth:`Client.exec`,
            this is a readable file-like object the caller can use to stream
            output from the process. It is None if stdout was passed to
            :meth:`Client.exec`.
        stderr: If the stderr argument was not passed to :meth:`Client.exec`
            and combine_stderr was False, this is a readable file-like object
            the caller can use to stream error output from the process. It is
            None if stderr was passed to :meth:`Client.exec` or combine_stderr
            was True.
    """

    def __init__(
        self,
        stdin: typing.Optional[typing.Union[typing.TextIO, typing.BinaryIO]],
        stdout: typing.Optional[typing.Union[typing.TextIO, typing.BinaryIO]],
        stderr: typing.Optional[typing.Union[typing.TextIO, typing.BinaryIO]],
        client: 'Client',
        timeout: typing.Optional[float],
        control_ws: websocket.WebSocket,
        stdio_ws: websocket.WebSocket,
        stderr_ws: websocket.WebSocket,
        command: typing.List[str],
        encoding: typing.Optional[str],
        change_id: ChangeID,
        cancel_stdin: typing.Callable[[], None],
        cancel_reader: typing.Optional[int],
        threads: typing.List[threading.Thread],
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

    def _wait(self):
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

    def wait_output(self) -> typing.Tuple[typing.AnyStr, typing.AnyStr]:
        """Wait for the process to finish and return tuple of (stdout, stderr).

        If a timeout was specified to the :meth:`Client.exec` call, this waits
        at most that duration. If combine_stderr was True, stdout will include
        the process's standard error, and stderr will be None.

        Raises:
            ChangeError: if there was an error starting or running the process.
            ExecError: if the process exits with a non-zero exit code.
        """
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

        exit_code = self._wait()

        out_value = out.getvalue()
        err_value = err.getvalue() if err is not None else None
        if exit_code != 0:
            raise ExecError(self._command, exit_code, out_value, err_value)

        return (out_value, err_value)

    def send_signal(self, sig: typing.Union[int, str]):
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


def _has_fileno(f):
    """Return True if the file-like object has a valid fileno() method."""
    try:
        f.fileno()
        return True
    except Exception:
        # Some types define a fileno method that raises io.UnsupportedOperation,
        # but just catching all exceptions here won't hurt.
        return False


def _reader_to_websocket(reader, ws, encoding, cancel_reader=None, bufsize=16 * 1024):
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

    ws.send('{"command":"end"}')  # Send "end" command as TEXT frame to signal EOF


def _websocket_to_writer(ws, writer, encoding):
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
                logger.warning('Invalid I/O command {!r}'.format(command))
                continue
            # Received "end" command (EOF signal), stop thread
            break

        if encoding is not None:
            chunk = chunk.decode(encoding)
        writer.write(chunk)


class _WebsocketWriter(io.BufferedIOBase):
    """A writable file-like object that sends what's written to it to a websocket."""

    def __init__(self, ws):
        self.ws = ws

    def writable(self):
        """Denote this file-like object as writable."""
        return True

    def write(self, chunk):
        """Write chunk to the websocket."""
        if not isinstance(chunk, bytes):
            raise TypeError('value to write must be bytes, not {}'.format(type(chunk).__name__))
        self.ws.send_binary(chunk)
        return len(chunk)

    def close(self):
        """Send end-of-file message to websocket."""
        self.ws.send('{"command":"end"}')


class _WebsocketReader(io.BufferedIOBase):
    """A readable file-like object whose reads come from a websocket."""

    def __init__(self, ws):
        self.ws = ws
        self.remaining = b''
        self.eof = False

    def readable(self):
        """Denote this file-like object as readable."""
        return True

    def read(self, n=-1):
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
                    logger.warning('Invalid I/O command {!r}'.format(command))
                    continue
                # Received "end" command, return EOF designator
                self.eof = True
                return b''

            self.remaining = chunk

        if n < 0:
            n = len(self.remaining)
        result = self.remaining[:n]
        self.remaining = self.remaining[n:]
        return result

    def read1(self, n=-1):
        """An alias for read."""
        return self.read(n)


class Client:
    """Pebble API client."""

    _chunk_size = 8192

    def __init__(self, socket_path=None, opener=None, base_url='http://localhost', timeout=5.0):
        """Initialize a client instance.

        Defaults to using a Unix socket at socket_path (which must be specified
        unless a custom opener is provided).
        """
        if opener is None:
            if socket_path is None:
                raise ValueError('no socket path provided')
            opener = self._get_default_opener(socket_path)
        self.socket_path = socket_path
        self.opener = opener
        self.base_url = base_url
        self.timeout = timeout

    @classmethod
    def _get_default_opener(cls, socket_path):
        """Build the default opener to use for requests (HTTP over Unix socket)."""
        opener = urllib.request.OpenerDirector()
        opener.add_handler(_UnixSocketHandler(socket_path))
        opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
        opener.add_handler(urllib.request.HTTPRedirectHandler())
        opener.add_handler(urllib.request.HTTPErrorProcessor())
        return opener

    def _request(
        self, method: str, path: str, query: typing.Dict = None, body: typing.Dict = None,
    ) -> typing.Dict:
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
        return _json_loads(response.read())

    @staticmethod
    def _ensure_content_type(headers, expected):
        """Parse Content-Type header from headers and ensure it's equal to expected.

        Return a dict of any options in the header, e.g., {'boundary': ...}.
        """
        ctype, options = cgi.parse_header(headers.get('Content-Type', ''))
        if ctype != expected:
            raise ProtocolError('expected Content-Type {!r}, got {!r}'.format(expected, ctype))
        return options

    def _request_raw(
        self, method: str, path: str, query: typing.Dict = None, headers: typing.Dict = None,
        data: bytes = None,
    ) -> http.client.HTTPResponse:
        """Make a request to the Pebble server; return the raw HTTPResponse object."""
        url = self.base_url + path
        if query:
            url = url + '?' + urllib.parse.urlencode(query, doseq=True)

        # python 3.5 urllib requests require their data to be a bytes object -
        # generators won't work.
        if sys.version_info[:2] < (3, 6) and isinstance(data, types.GeneratorType):
            data = b''.join(data)

        if headers is None:
            headers = {}
        request = urllib.request.Request(url, method=method, data=data, headers=headers)

        try:
            response = self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            code = e.code
            status = e.reason
            try:
                body = _json_loads(e.read())
                message = body['result']['message']
            except (IOError, ValueError, KeyError) as e2:
                # Will only happen on read error or if Pebble sends invalid JSON.
                body = {}
                message = '{} - {}'.format(type(e2).__name__, e2)
            raise APIError(body, code, status, message)
        except urllib.error.URLError as e:
            raise ConnectionError(e.reason)

        return response

    def get_system_info(self) -> SystemInfo:
        """Get system info."""
        resp = self._request('GET', '/v1/system-info')
        return SystemInfo.from_dict(resp['result'])

    def get_warnings(self, select: WarningState = WarningState.PENDING) -> typing.List[Warning]:
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
        self, select: ChangeState = ChangeState.IN_PROGRESS, service: str = None,
    ) -> typing.List[Change]:
        """Get list of changes in given state, filter by service name if given."""
        query = {'select': select.value}
        if service is not None:
            query['for'] = service
        resp = self._request('GET', '/v1/changes', query)
        return [Change.from_dict(c) for c in resp['result']]

    def get_change(self, change_id: ChangeID) -> Change:
        """Get single change by ID."""
        resp = self._request('GET', '/v1/changes/{}'.format(change_id))
        return Change.from_dict(resp['result'])

    def abort_change(self, change_id: ChangeID) -> Change:
        """Abort change with given ID."""
        body = {'action': 'abort'}
        resp = self._request('POST', '/v1/changes/{}'.format(change_id), body=body)
        return Change.from_dict(resp['result'])

    def autostart_services(self, timeout: float = 30.0, delay: float = 0.1) -> ChangeID:
        """Start the startup-enabled services and wait (poll) for them to be started.

        Args:
            timeout: Seconds before autostart change is considered timed out (float).
            delay: Seconds before executing the autostart change (float).

        Returns:
            ChangeID of the autostart change.

        Raises:
            ChangeError: if one or more of the services didn't start. If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
        """
        return self._services_action('autostart', [], timeout, delay)

    def replan_services(self, timeout: float = 30.0, delay: float = 0.1) -> ChangeID:
        """Replan by (re)starting changed and startup-enabled services and wait for them to start.

        Args:
            timeout: Seconds before replan change is considered timed out (float).
            delay: Seconds before executing the replan change (float).

        Returns:
            ChangeID of the replan change.

        Raises:
            ChangeError: if one or more of the services didn't stop/start. If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
        """
        return self._services_action('replan', [], timeout, delay)

    def start_services(
        self, services: typing.List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Start services by name and wait (poll) for them to be started.

        Args:
            services: Non-empty list of services to start.
            timeout: Seconds before start change is considered timed out (float).
            delay: Seconds before executing the start change (float).

        Returns:
            ChangeID of the start change.

        Raises:
            ChangeError: if one or more of the services didn't stop/start. If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
        """
        return self._services_action('start', services, timeout, delay)

    def stop_services(
        self, services: typing.List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Stop services by name and wait (poll) for them to be started.

        Args:
            services: Non-empty list of services to stop.
            timeout: Seconds before stop change is considered timed out (float).
            delay: Seconds before executing the stop change (float).

        Returns:
            ChangeID of the stop change.

        Raises:
            ChangeError: if one or more of the services didn't stop/start. If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
        """
        return self._services_action('stop', services, timeout, delay)

    def restart_services(
        self, services: typing.List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Restart services by name and wait (poll) for them to be started.

        Args:
            services: Non-empty list of services to restart.
            timeout: Seconds before restart change is considered timed out (float).
            delay: Seconds before executing the restart change (float).

        Returns:
            ChangeID of the restart change.

        Raises:
            ChangeError: if one or more of the services didn't stop/start. If
                timeout is 0, submit the action but don't wait; just return the change
                ID immediately.
        """
        return self._services_action('restart', services, timeout, delay)

    def _services_action(
        self, action: str, services: typing.Iterable[str], timeout: float, delay: float,
    ) -> ChangeID:
        if not isinstance(services, (list, tuple)):
            raise TypeError('services must be a list of str, not {}'.format(
                type(services).__name__))
        for s in services:
            if not isinstance(s, str):
                raise TypeError('service names must be str, not {}'.format(type(s).__name__))

        body = {'action': action, 'services': services}
        resp = self._request('POST', '/v1/services', body=body)
        change_id = ChangeID(resp['change'])
        if timeout:
            change = self.wait_change(change_id, timeout=timeout, delay=delay)
            if change.err:
                raise ChangeError(change.err, change)
        return change_id

    def wait_change(
        self, change_id: ChangeID, timeout: float = 30.0, delay: float = 0.1,
    ) -> Change:
        """Wait for the given change to be ready.

        If the Pebble server supports the /v1/changes/{id}/wait API endpoint,
        use that to avoid polling, otherwise poll /v1/changes/{id} every delay
        seconds.

        Args:
            change_id: Change ID of change to wait for.
            timeout: Maximum time in seconds to wait for the change to be
                ready. May be None, in which case wait_change never times out.
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

    def _wait_change_using_wait(self, change_id, timeout):
        """Wait for a change to be ready using the wait-change API."""
        deadline = time.time() + timeout if timeout is not None else None

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

        raise TimeoutError('timed out waiting for change {} ({} seconds)'.format(
            change_id, timeout))

    def _wait_change(self, change_id: ChangeID, timeout: float = None) -> Change:
        """Call the wait-change API endpoint directly."""
        query = {}
        if timeout is not None:
            query['timeout'] = _format_timeout(timeout)

        try:
            resp = self._request('GET', '/v1/changes/{}/wait'.format(change_id), query)
        except APIError as e:
            if e.code == 404:
                raise NotImplementedError('server does not implement wait-change endpoint')
            if e.code == 504:
                raise TimeoutError('timed out waiting for change {} ({} seconds)'.format(
                    change_id, timeout))
            raise

        return Change.from_dict(resp['result'])

    def _wait_change_using_polling(self, change_id, timeout, delay):
        """Wait for a change to be ready by polling the get-change API."""
        deadline = time.time() + timeout if timeout is not None else None

        while timeout is None or time.time() < deadline:
            change = self.get_change(change_id)
            if change.ready:
                return change

            time.sleep(delay)

        raise TimeoutError('timed out waiting for change {} ({} seconds)'.format(
            change_id, timeout))

    def add_layer(
            self, label: str, layer: typing.Union[str, dict, Layer], *, combine: bool = False):
        """Dynamically add a new layer onto the Pebble configuration layers.

        If combine is False (the default), append the new layer as the top
        layer with the given label. If combine is True and the label already
        exists, the two layers are combined into a single one considering the
        layer override rules; if the layer doesn't exist, it is added as usual.
        """
        if not isinstance(label, str):
            raise TypeError('label must be a str, not {}'.format(type(label).__name__))

        if isinstance(layer, str):
            layer_yaml = layer
        elif isinstance(layer, dict):
            layer_yaml = Layer(layer).to_yaml()
        elif isinstance(layer, Layer):
            layer_yaml = layer.to_yaml()
        else:
            raise TypeError('layer must be str, dict, or pebble.Layer, not {}'.format(
                type(layer).__name__))

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

    def get_services(self, names: typing.List[str] = None) -> typing.List[ServiceInfo]:
        """Get the service status for the configured services.

        If names is specified, only fetch the service status for the services
        named.
        """
        query = None
        if names is not None:
            query = {'names': ','.join(names)}
        resp = self._request('GET', '/v1/services', query)
        return [ServiceInfo.from_dict(info) for info in resp['result']]

    def pull(self, path: str, *, encoding: str = 'utf-8') -> typing.Union[typing.BinaryIO,
                                                                          typing.TextIO]:
        """Read a file's content from the remote system.

        Args:
            path: Path of the file to read from the remote system.
            encoding: Encoding to use for decoding the file's bytes to str,
                or None to specify no decoding.

        Returns:
            A readable file-like object, whose read() method will return str
            objects decoded according to the specified encoding, or bytes if
            encoding is None.
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
            raise ProtocolError('invalid boundary {!r}'.format(boundary))

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
            raise ProtocolError('path not expected: {!r}'.format(filename))

        f = parser.get_file(path, encoding)

        # The opened file remains usable after removing/unlinking on posix
        # platforms until it is closed.  This prevents callers from
        # interacting with it on disk.  But e.g. Windows doesn't allow
        # removing opened files, and so we use the tempfile lib's
        # helper class to auto-delete on close/gc for us.
        if os.name != 'posix' or sys.platform == 'cygwin':
            return tempfile._TemporaryFileWrapper(f, f.name, delete=True)
        parser.remove_files()
        return f

    @staticmethod
    def _raise_on_path_error(resp, path):
        result = resp['result'] or []  # in case it's null instead of []
        paths = {item['path']: item for item in result}
        if path not in paths:
            raise ProtocolError('path not found in response metadata: {}'.format(resp))
        error = paths[path].get('error')
        if error:
            raise PathError(error['kind'], error['message'])

    def push(
            self, path: str, source: typing.Union[bytes, str, typing.BinaryIO, typing.TextIO], *,
            encoding: str = 'utf-8', make_dirs: bool = False, permissions: int = None,
            user_id: int = None, user: str = None, group_id: int = None, group: str = None):
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
        resp = _json_loads(response.read())
        self._raise_on_path_error(resp, path)

    @staticmethod
    def _make_auth_dict(permissions, user_id, user, group_id, group) -> typing.Dict:
        d = {}
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

    def _encode_multipart(self, metadata, path, source, encoding):
        # Python's stdlib mime/multipart handling is screwy and doesn't handle
        # binary properly, so roll our own.

        if isinstance(source, str):
            source = io.StringIO(source)
        elif isinstance(source, bytes):
            source = io.BytesIO(source)

        boundary = binascii.hexlify(os.urandom(16))
        path_escaped = path.replace('"', '\\"').encode('utf-8')  # NOQA: test_quote_backslashes
        content_type = 'multipart/form-data; boundary="' + boundary.decode('utf-8') + '"'

        def generator():
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

            content = source.read(self._chunk_size)
            while content:
                if isinstance(content, str):
                    content = content.encode(encoding)
                yield content
                content = source.read(self._chunk_size)

            yield b''.join([
                b'\r\n',
                b'--', boundary, b'--\r\n',
            ])

        return generator(), content_type

    def list_files(self, path: str, *, pattern: str = None,
                   itself: bool = False) -> typing.List[FileInfo]:
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
            self, path: str, *, make_parents: bool = False, permissions: int = None,
            user_id: int = None, user: str = None, group_id: int = None, group: str = None):
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
        self._raise_on_path_error(resp, path)

    def remove_path(self, path: str, *, recursive: bool = False):
        """Remove a file or directory on the remote system.

        Args:
            path: Path of the file or directory to delete from the remote system.
            recursive: If True, and path is a directory recursively deletes it and
                       everything under it. If the path is a file, delete the file and
                       do nothing if the file is non-existent. Behaviourally similar
                       to `rm -rf <file|dir>`

        """
        info = {'path': path}
        if recursive:
            info['recursive'] = True
        body = {
            'action': 'remove',
            'paths': [info],
        }
        resp = self._request('POST', '/v1/files', None, body)
        self._raise_on_path_error(resp, path)

    def exec(
        self,
        command: typing.List[str],
        *,
        environment: typing.Dict[str, str] = None,
        working_dir: str = None,
        timeout: float = None,
        user_id: int = None,
        user: str = None,
        group_id: int = None,
        group: str = None,
        stdin: typing.Union[str, bytes, typing.TextIO, typing.BinaryIO] = None,
        stdout: typing.Union[typing.TextIO, typing.BinaryIO] = None,
        stderr: typing.Union[typing.TextIO, typing.BinaryIO] = None,
        encoding: str = 'utf-8',
        combine_stderr: bool = False
    ) -> ExecProcess:
        r"""Execute the given command on the remote system.

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
        """
        if not isinstance(command, list) or not all(isinstance(s, str) for s in command):
            raise TypeError('command must be a list of str, not {}'.format(
                type(command).__name__))
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

        stderr_ws = None
        try:
            control_ws = self._connect_websocket(task_id, 'control')
            stdio_ws = self._connect_websocket(task_id, 'stdio')
            if not combine_stderr:
                stderr_ws = self._connect_websocket(task_id, 'stderr')
        except websocket.WebSocketException as e:
            # Error connecting to websockets, probably due to the exec/change
            # finishing early with an error. Call wait_change to pick that up.
            change = self.wait_change(ChangeID(change_id))
            if change.err:
                raise ChangeError(change.err, change)
            raise ConnectionError('unexpected error connecting to websockets: {}'.format(e))

        cancel_stdin = None
        cancel_reader = None
        threads = []

        if stdin is not None:
            if _has_fileno(stdin):
                if sys.platform == 'win32':
                    raise NotImplementedError('file-based stdin not supported on Windows')

                # Create a pipe so _reader_to_websocket can select() on the
                # reader as well as this cancel_reader; when we write anything
                # to cancel_writer it'll trigger the select and end the thread.
                cancel_reader, cancel_writer = os.pipe()

                def cancel_stdin():
                    os.write(cancel_writer, b'x')  # doesn't matter what we write
                    os.close(cancel_writer)

            t = _start_thread(_reader_to_websocket, stdin, stdio_ws, encoding, cancel_reader)
            threads.append(t)
            process_stdin = None
        else:
            process_stdin = _WebsocketWriter(stdio_ws)
            if encoding is not None:
                process_stdin = io.TextIOWrapper(process_stdin, encoding=encoding, newline='')

        if stdout is not None:
            t = _start_thread(_websocket_to_writer, stdio_ws, stdout, encoding)
            threads.append(t)
            process_stdout = None
        else:
            process_stdout = _WebsocketReader(stdio_ws)
            if encoding is not None:
                process_stdout = io.TextIOWrapper(process_stdout, encoding=encoding, newline='')

        process_stderr = None
        if not combine_stderr:
            if stderr is not None:
                t = _start_thread(_websocket_to_writer, stderr_ws, stderr, encoding)
                threads.append(t)
            else:
                process_stderr = _WebsocketReader(stderr_ws)
                if encoding is not None:
                    process_stderr = io.TextIOWrapper(
                        process_stderr, encoding=encoding, newline='')

        process = ExecProcess(
            stdin=process_stdin,
            stdout=process_stdout,
            stderr=process_stderr,
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

    def _connect_websocket(self, task_id: str, websocket_id: str) -> websocket.WebSocket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.socket_path)
        url = self._websocket_url(task_id, websocket_id)
        ws = websocket.WebSocket(skip_utf8_validation=True)
        ws.connect(url, socket=sock)
        return ws

    def _websocket_url(self, task_id: str, websocket_id: str) -> str:
        base_url = self.base_url.replace('http://', 'ws://')
        url = '{}/v1/tasks/{}/websocket/{}'.format(base_url, task_id, websocket_id)
        return url

    def send_signal(self, sig: typing.Union[int, str], services: typing.List[str]):
        """Send the given signal to the list of services named.

        Args:
            sig: Name or number of signal to send, e.g., "SIGHUP", 1, or
                signal.SIGHUP.
            services: Non-empty list of service names to send the signal to.

        Raises:
            APIError: If any of the services are not in the plan or are not
                currently running.
        """
        if not isinstance(services, (list, tuple)):
            raise TypeError('services must be a list of str, not {}'.format(
                type(services).__name__))
        for s in services:
            if not isinstance(s, str):
                raise TypeError('service names must be str, not {}'.format(type(s).__name__))

        if isinstance(sig, int):
            sig = signal.Signals(sig).name
        body = {
            'signal': sig,
            'services': services,
        }
        self._request('POST', '/v1/signals', body=body)

    def get_checks(
        self,
        level: CheckLevel = None,
        names: typing.List[str] = None
    ) -> typing.List[CheckInfo]:
        """Get the check status for the configured checks.

        Args:
            level: Optional check level to query for (default is to fetch
                checks with any level).
            names: Optional list of check names to query for (default is to
                fetch checks with any name).

        Returns:
            List of :class:`CheckInfo` objects.
        """
        query = {}
        if level is not None:
            query['level'] = level.value
        if names:
            query['names'] = names
        resp = self._request('GET', '/v1/checks', query)
        return [CheckInfo.from_dict(info) for info in resp['result']]


class _FilesParser:
    """A limited purpose multi-part parser backed by files for memory efficiency."""

    def __init__(self, boundary: typing.Union[bytes, str]):
        self._response = None
        self._files = {}

        # Prepare the MIME multipart boundary line patterns.
        if isinstance(boundary, str):
            boundary = boundary.encode()

        # State vars, as we may enter the feed() function multiple times.
        self._headers = None
        self._part_type = None
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
                'unexpected content disposition: {!r}'.format(content_disposition))

        name = self._headers.get_param('name', header='content-disposition')
        if name == 'files':
            filename = self._headers.get_filename()
            if filename is None:
                raise ProtocolError('multipart "files" part missing filename')
            self._prepare_tempfile(filename)
        elif name != 'response':
            raise ProtocolError(
                'unexpected name in content-disposition header: {!r}'.format(name))

        self._part_type = name

    def _process_body(self, data: bytes, done=False):
        if self._part_type == 'response':
            self._response_data.extend(data)
            if done:
                if len(self._response_data) > self._max_lookahead:
                    raise ProtocolError('response end marker not found')
                self._response = json.loads(self._response_data.decode())
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

    def _prepare_tempfile(self, filename):
        tf = tempfile.NamedTemporaryFile(delete=False)
        self._files[filename] = tf
        self.current_filename = filename

    def _get_open_tempfile(self):
        return self._files[self.current_filename]

    def get_response(self):
        """Return the deserialized JSON object from the multipart "response" field."""
        return self._response

    def filenames(self):
        """Return a list of filenames from the "files" parts of the response."""
        return list(self._files.keys())

    def get_file(self, path, encoding):
        """Return an open file object containing the data."""
        mode = 'r' if encoding else 'rb'
        # We're using text-based file I/O purely for file encoding purposes, not for
        # newline normalization.  newline='' serves the line endings as-is.
        newline = '' if encoding else None
        return open(self._files[path].name, mode, encoding=encoding, newline=newline)


class _MultipartParser:
    def __init__(
            self,
            marker: bytes,
            handle_header,
            handle_body,
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
                ii, nn, self._done = _next_part_boundary(self._buf, self._marker, start=self._pos)
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


def _next_part_boundary(buf, marker, start=0):
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
