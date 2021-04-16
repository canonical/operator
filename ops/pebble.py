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

from email.mime.multipart import MIMEBase, MIMEMultipart
import cgi
import datetime
import email.parser
import enum
import http.client
import json
import re
import socket
import sys
import time
import typing
import urllib.error
import urllib.parse
import urllib.request

from ops._private import yaml


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


def _json_loads(s: typing.Union[str, bytes]) -> typing.Dict:
    """Like json.loads(), but handle str or bytes.

    This is needed because an HTTP response's read() method returns bytes on
    Python 3.5, and json.load doesn't handle bytes.
    """
    if isinstance(s, bytes):
        s = s.decode('utf-8')
    return json.loads(s)


class Error(Exception):
    """Base class of most errors raised by the Pebble client."""


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
        super().__init__(err)  # Makes str(e) return err
        self.err = err
        self.change = change

    def __repr__(self):
        return 'ChangeError({!r}, {!r})'.format(self.err, self.change)


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
    ):
        self.id = id
        self.kind = kind
        self.summary = summary
        self.status = status
        self.log = log
        self.progress = progress
        self.spawn_time = spawn_time
        self.ready_time = ready_time

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
                'ready_time={self.ready_time!r})'
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
                'ready_time={self.ready_time!r})'
                ).format(self=self)


class Plan:
    """Represents the effective Pebble configuration."""

    def __init__(self, raw: str):
        d = yaml.safe_load(raw) or {}
        self._raw = raw
        self._services = {name: Service(name, service)
                          for name, service in d.get('services', {}).items()}

    @property
    def services(self):
        """This plan's services mapping (maps service name to Service).

        This property is currently read-only.
        """
        return self._services

    def to_yaml(self) -> str:
        """Return this plan's YAML representation."""
        return self._raw

    __str__ = to_yaml


class Layer:
    """Represents a Pebble configuration layer.

    The format of this is not documented, but is captured in code here:
    https://github.com/canonical/pebble/blob/master/internal/plan/plan.go
    """

    def __init__(self, raw: typing.Union[str, typing.Dict] = None):
        if isinstance(raw, str):
            d = yaml.safe_load(raw) or {}
        else:
            d = raw or {}
        self.summary = d.get('summary', '')
        self.description = d.get('description', '')
        self.services = {name: Service(name, service)
                         for name, service in d.get('services', {}).items()}

    def to_yaml(self) -> str:
        """Convert this layer to its YAML representation."""
        return yaml.safe_dump(self.to_dict())

    def to_dict(self) -> typing.Dict:
        """Convert this layer to its dict representation."""
        fields = [
            ('summary', self.summary),
            ('description', self.description),
            ('services', {name: service.to_dict() for name, service in self.services.items()})
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

    def to_dict(self) -> typing.Dict:
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
        ]
        return {name: value for name, value in fields if value}

    def __repr__(self) -> str:
        return 'Service({!r})'.format(self.to_dict())


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
    """Stat-like information about a single file."""

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


class Client:
    """Pebble API client."""

    def __init__(self, socket_path=None, opener=None, base_url='http://localhost', timeout=5.0):
        """Initialize a client instance.

        Defaults to using a Unix socket at socket_path (which must be specified
        unless a custom opener is provided).
        """
        if opener is None:
            if socket_path is None:
                raise ValueError('no socket path provided')
            opener = self._get_default_opener(socket_path)
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
            url = url + '?' + urllib.parse.urlencode(query)

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

        Raises ChangeError if one or more of the services didn't start. If
        timeout is 0, submit the action but don't wait; just return the change
        ID immediately.
        """
        return self._services_action('autostart', [], timeout, delay)

    def start_services(
        self, services: typing.List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Start services by name and wait (poll) for them to be started.

        Raises ChangeError if one or more of the services didn't start. If
        timeout is 0, submit the action but don't wait; just return the change
        ID immediately.
        """
        return self._services_action('start', services, timeout, delay)

    def stop_services(
        self, services: typing.List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Stop services by name and wait (poll) for them to be started.

        Raises ChangeError if one or more of the services didn't stop. If
        timeout is 0, submit the action but don't wait; just return the change
        ID immediately.
        """
        return self._services_action('stop', services, timeout, delay)

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
        """Poll change every delay seconds (up to timeout) for it to be ready."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            change = self.get_change(change_id)
            if change.ready:
                return change

            time.sleep(delay)

        raise TimeoutError(
            'timed out waiting for change {} ({} seconds)'.format(change_id, timeout))

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
        """Get the Pebble plan (currently contains only combined services)."""
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

    def read_file(self, path: str, destination: typing.BinaryIO):
        """Read a file from the remote system and write content to destination."""
        query = {
            'action': 'read',
            'path': path,
        }
        headers = {'Accept': 'multipart/form-data'}
        response = self._request_raw('GET', '/v1/files', query, headers)
        resp = self._parse_read_multipart(response, {path: destination})
        self._raise_on_path_error(resp, path)

    @staticmethod
    def _raise_on_path_error(resp, path):
        result = resp['result'] or []  # in case it's null instead of []
        paths = {item['path']: item for item in result}
        if path not in paths:
            raise ProtocolError('path not found in response metadata: {}'.format(resp))
        error = paths[path].get('error')
        if error:
            raise PathError(error['kind'], error['message'])

    @classmethod
    def _parse_read_multipart(cls, response: http.client.HTTPResponse,
                              destinations: typing.Dict[str, typing.BinaryIO]) -> typing.Dict:
        """Parse a multipart HTTP response from the read-files API.

        Return "response" metadata field decoded from JSON, and write content
        to file-like object in destinations dictionary (keyed by path).
        Currently the content is entirely loaded into memory, but the goal is
        to stream that in future (the signature of read_file won't change).
        """
        options = cls._ensure_content_type(response.headers, 'multipart/form-data')
        boundary = options.get('boundary', '')
        if not boundary:
            raise ProtocolError('invalid boundary {!r}'.format(boundary))

        # We have to manually write the Content-Type with boundary, because
        # email.parser expects the entire multipart message with headers.
        parser = email.parser.BytesFeedParser()
        parser.feed(b'Content-Type: multipart/form-data; boundary=' +
                    boundary.encode('utf-8') + b'\r\n\r\n')

        # Then read the rest of the response and feed it to the parser.
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            parser.feed(chunk)
        message = parser.close()

        resp = None
        for part in message.walk():
            name = part.get_param('name', header='Content-Disposition')
            if name == 'response':
                resp = _json_loads(part.get_payload())
            elif name == 'files':
                # decode=True, ironically, avoids decoding bytes to str
                content = part.get_payload(decode=True)
                filename = part.get_filename()
                if filename not in destinations:
                    raise ProtocolError('path not expected: {}'.format(filename))
                destinations[filename].write(content)

        if resp is None:
            raise ProtocolError('no "response" field in multipart body')

        return resp

    def write_file(
            self, path: str, source: typing.BinaryIO, make_dirs: bool = False,
            permissions: int = None, user: typing.Union[str, int] = None,
            group: typing.Union[str, int] = None):
        """Write data from source to given file path on remote system.

        If make_dirs is True, create parent directories if they don't exist.
        Set file's mode, user, and group to those provided. User and group may
        be either name strings or UID/GID integers.
        """
        info = self._make_auth_dict(permissions, user, group)
        info['path'] = path
        if make_dirs:
            info['make-dirs'] = True

        metadata = {
            'action': 'write',
            'files': [info],
        }
        body, content_type = self._encode_multipart(metadata, {path: source})

        headers = {
            'Accept': 'application/json',
            'Content-Type': content_type,
        }
        response = self._request_raw('POST', '/v1/files', None, headers, body)
        self._ensure_content_type(response.headers, 'application/json')
        resp = _json_loads(response.read())
        self._raise_on_path_error(resp, path)

    @staticmethod
    def _make_auth_dict(permissions, user, group) -> typing.Dict:
        d = {}
        if permissions is not None:
            d['permissions'] = format(permissions, '03o')
        if user is not None:
            if isinstance(user, int):
                d['user-id'] = user
            elif isinstance(user, str):
                d['user'] = user
            else:
                raise TypeError('user must be int UID or string username')
        if group is not None:
            if isinstance(group, int):
                d['group-id'] = group
            elif isinstance(group, str):
                d['group'] = group
            else:
                raise TypeError('group must be int GID or string group name')
        return d

    @staticmethod
    def _encode_multipart(
        metadata: typing.Dict, sources: typing.Dict[str, typing.BinaryIO],
    ) -> typing.Tuple[bytes, str]:
        multipart = MIMEMultipart('form-data')

        part = MIMEBase('application', 'json')
        part.add_header('Content-Disposition', 'form-data', name='request')
        part.set_payload(json.dumps(metadata))
        multipart.attach(part)

        for path, source in sources.items():
            part = MIMEBase('application', 'octet-stream')
            part.add_header('Content-Disposition', 'form-data', name='files', filename=path)
            part.set_payload(source.read())
            multipart.attach(part)

        return (multipart.as_bytes(), multipart['Content-Type'])

    def list_files(
        self, path: str, pattern: str = None, itself: bool = False,
    ) -> typing.List[FileInfo]:
        """Return list of file information from given path on remote system.

        If path is a directory (and "itself" is False), return a list of all
        entries in that directory. If path is a file (or if "itself" is True),
        return a one-element list with information about just that file. If
        pattern is specified, filter the list to just the files that match,
        for example "*.txt".
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
            self, path: str, make_parents: bool = False, permissions: int = None,
            user: typing.Union[str, int] = None, group: typing.Union[str, int] = None):
        """Create a directory on the remote system with the given attributes.

        If make_parents is True, create parent directories if they don't exist.
        Set directory's mode, user, and group to those provided. User and group
        may be either name strings or UID/GID integers.
        """
        info = self._make_auth_dict(permissions, user, group)
        info['path'] = path
        if make_parents:
            info['make-parents'] = True
        body = {
            'action': 'make-dirs',
            'dirs': [info],
        }
        resp = self._request('POST', '/v1/files', None, body)
        self._raise_on_path_error(resp, path)

    def remove_path(self, path: str, recursive: bool = False):
        """Remove a file or directory on the remote system.

        If "recursive" is True, recursively delete path and everything under it.
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
