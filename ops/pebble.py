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

"""Client for the Pebble API (HTTP over Unix socket)."""

from typing import Any, Dict, List, Optional
import datetime
import enum
import http.client
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request


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


# Matches yyyy-mm-ddTHH:MM:SS.sss[-+]zz(:)zz
_TIMESTAMP_RE = re.compile(
    r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d+)([-+])(\d{2}):?(\d{2})')


def _parse_timestamp(s):
    """Parse timestamp from Go-encoded JSON (which uses 9 decimal places for seconds)."""
    match = _TIMESTAMP_RE.match(s)
    if not match:
        raise ValueError('invalid timestamp {!r}'.format(s))
    y, m, d, hh, mm, ss, sub, plus_minus, z1, z2 = match.groups()
    s = '{y}-{m}-{d}T{hh}:{mm}:{ss}.{sub}{plus_minus}{z1}{z2}'.format(
        y=y, m=m, d=d, hh=hh, mm=mm, ss=ss, sub=sub[:6],
        plus_minus=plus_minus, z1=z1, z2=z2,
    )
    return datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%f%z')


class ServiceError(Exception):
    """Raised by API.wait_change when a service change is ready but has an error."""

    def __init__(self, err, change):
        super().__init__(err)
        self.err = err
        self.change = change


class WarningState(enum.Enum):
    """Enum of states for API.get_warnings() select parameter."""

    ALL = 'all'
    PENDING = 'pending'


class ChangeState(enum.Enum):
    """Enum of states for API.get_changes() select parameter."""

    ALL = 'all'
    IN_PROGRESS = 'in-progress'
    READY = 'ready'


class SystemInfo:
    """System information object."""

    def __init__(self, version: str):
        self.version = version

    @classmethod
    def from_dict(cls, d: Dict) -> 'SystemInfo':
        """Create new object from dict parsed from JSON."""
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
    def from_dict(cls, d: Dict) -> 'Warning':
        """Create new object from dict parsed from JSON."""
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
    def from_dict(cls, d: Dict) -> 'TaskProgress':
        """Create new object from dict parsed from JSON."""
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
        log: List[str],
        progress: TaskProgress,
        spawn_time: datetime.datetime,
        ready_time: Optional[datetime.datetime],
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
    def from_dict(cls, d: Dict) -> 'Task':
        """Create new object from dict parsed from JSON."""
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
        tasks: List[Task],
        ready: bool,
        err: Optional[str],
        spawn_time: datetime.datetime,
        ready_time: Optional[datetime.datetime],
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
    def from_dict(cls, d: Dict) -> 'Change':
        """Create new object from dict parsed from JSON."""
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


class API:
    """Pebble API client."""

    def __init__(self, socket_path=None, opener=None, base_url='http://localhost', timeout=5.0):
        """Initialize an instance. Defaults to Unix socket "$PEBBLE/.pebble.socket"."""
        if opener is None:
            opener = self._get_default_opener(socket_path)
        self.opener = opener
        self.base_url = base_url
        self.timeout = timeout

    @classmethod
    def _get_default_opener(cls, socket_path):
        """Build the default urllib opener to use for requests.

        If socket_path is None, use "$PEBBLE/.pebble.socket".
        """
        if socket_path is None:
            PEBBLE = os.getenv('PEBBLE')
            if not PEBBLE:
                raise ValueError('You must specify socket_path or set $PEBBLE')
            socket_path = os.path.join(PEBBLE, '.pebble.socket')

        opener = urllib.request.OpenerDirector()
        opener.add_handler(_UnixSocketHandler(socket_path))
        opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
        opener.add_handler(urllib.request.HTTPRedirectHandler())
        opener.add_handler(urllib.request.HTTPErrorProcessor())
        return opener

    def _request(self, method: str, path: str, query: Dict = None, body: Dict = None) -> Dict:
        """Make a request with the given HTTP method and path to the Pebble API.

        If query dict is provided, it is encoded and appended as a query string
        to the URL. If body dict is provided, it is serialied as JSON and used
        as the HTTP body (with Content-Type "application/json").
        """
        url = self.base_url + path
        if query:
            url = url + '?' + urllib.parse.urlencode(query)

        headers = {'Accept': 'application/json'}
        data = None
        if body is not None:
            data = json.dumps(body).encode('utf-8')
            headers['Content-Type'] = 'application/json'

        request = urllib.request.Request(url, method=method, data=data, headers=headers)
        response = self.opener.open(request, timeout=self.timeout)
        result = json.load(response)
        return result

    def get_system_info(self) -> SystemInfo:
        """Get system info."""
        result = self._request('GET', '/v1/system-info')
        return SystemInfo.from_dict(result['result'])

    def get_warnings(self, select: WarningState = WarningState.PENDING) -> List[Warning]:
        """Get list of warnings in given state (pending or all)."""
        query = {'select': select.value}
        result = self._request('GET', '/v1/warnings', query)
        return [Warning.from_dict(w) for w in result['result']]

    def ack_warnings(self, timestamp: datetime.datetime) -> int:
        """Acknowledge warnings up to given timestamp, return number acknowledged."""
        body = {'action': 'okay', 'timestamp': timestamp.isoformat()}
        result = self._request('POST', '/v1/warnings', body=body)
        return result['result']

    def get_changes(
        self, select: ChangeState = ChangeState.IN_PROGRESS, service: str = None,
    ) -> List[Change]:
        """Get list of changes in given state, filter by service name if given."""
        query = {'select': select.value}
        if service is not None:
            query['for'] = service
        result = self._request('GET', '/v1/changes', query)
        return [Change.from_dict(c) for c in result['result']]

    def get_change(self, change_id: ChangeID) -> Change:
        """Get single change by ID."""
        result = self._request('GET', '/v1/changes/{}'.format(change_id))
        return Change.from_dict(result['result'])

    def abort_change(self, change_id: ChangeID) -> Change:
        """Abort change with given ID."""
        body = {'action': 'abort'}
        result = self._request('POST', '/v1/changes/{}'.format(change_id), body=body)
        return Change.from_dict(result['result'])

    def autostart_services(self, timeout: float = 30.0, delay: float = 0.1) -> ChangeID:
        """Start the autostart services and wait (poll) for them to be started.

        If timeout is 0, submit the action but don't wait.
        """
        return self._services_action('autostart', [], timeout, delay)

    def start_services(
        self, services: List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Start services by name and wait (poll) for them to be started.

        If timeout is 0, submit the action but don't wait.
        """
        return self._services_action('start', services, timeout, delay)

    def stop_services(
        self, services: List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> ChangeID:
        """Stop services by name and wait (poll) for them to be started.

        If timeout is 0, submit the action but don't wait.
        """
        return self._services_action('stop', services, timeout, delay)

    def _services_action(
        self, action: str, services: List[str], timeout: float, delay: float,
    ) -> ChangeID:
        body = {'action': action, 'services': services}
        result = self._request('POST', '/v1/services', body=body)
        change_id = ChangeID(result['change'])
        if timeout:
            self.wait_change(change_id, timeout=timeout, delay=delay)
        return change_id

    def wait_change(
        self, change_id: ChangeID, timeout: float = 30.0, delay: float = 0.1,
    ) -> Change:
        """Poll change every delay seconds (up to timeout) for it to be ready."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            change = self.get_change(change_id)
            if change.ready:
                if change.err:
                    raise ServiceError(change.err, change)
                return change

            time.sleep(delay)

        raise TimeoutError(
            'timed out waiting for change {} ({} seconds)'.format(change_id, timeout))


# Make useable as a command line client for local testing
if __name__ == '__main__':
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument('--socket', help='pebble socket path, default $PEBBLE/.pebble.socket')
    subparsers = parser.add_subparsers(dest='command', metavar='command')

    p = subparsers.add_parser('abort', help='abort a change by ID')
    p.add_argument('change_id', help='ID of change to abort')

    p = subparsers.add_parser('ack', help='acknowledge warnings up to given time')
    p.add_argument('--timestamp', help='time to acknowledge up to (YYYY-mm-ddTHH:MM:SS.f+ZZ:zz'
                                       'format), default current time',
                   type=_parse_timestamp)

    p = subparsers.add_parser('autostart', help='autostart default service(s)')

    p = subparsers.add_parser('change', help='show a single change by ID')
    p.add_argument('change_id', help='ID of change to fetch')

    p = subparsers.add_parser('changes', help='show (filtered) changes')
    p.add_argument('--select', help='change state to filter on, default %(default)s',
                   choices=[s.value for s in ChangeState], default='all')
    p.add_argument('--service', help='optional service name to filter on')

    p = subparsers.add_parser('start', help='start service(s)')
    p.add_argument('service', help='name of service to start (can specify multiple)', nargs='+')

    p = subparsers.add_parser('stop', help='stop service(s)')
    p.add_argument('service', help='name of service to stop (can specify multiple)', nargs='+')

    p = subparsers.add_parser('system-info', help='show Pebble system information')

    p = subparsers.add_parser('warnings', help='show (filtered) warnings')
    p.add_argument('--select', help='warning state to filter on, default %(default)s',
                   choices=[s.value for s in WarningState], default='all')

    args = parser.parse_args()

    try:
        api = API(socket_path=args.socket)
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    try:
        result = None  # type: Any
        if args.command == 'abort':
            result = api.abort_change(ChangeID(args.change_id))
        elif args.command == 'ack':
            timestamp = args.timestamp or datetime.datetime.now(tz=datetime.timezone.utc)
            result = api.ack_warnings(timestamp)
        elif args.command == 'autostart':
            result = api.autostart_services()
        elif args.command == 'change':
            result = api.get_change(ChangeID(args.change_id))
        elif args.command == 'changes':
            result = api.get_changes(select=ChangeState(args.select), service=args.service)
        elif args.command == 'start':
            result = api.start_services(args.service)
        elif args.command == 'stop':
            result = api.stop_services(args.service)
        elif args.command == 'system-info':
            result = api.get_system_info()
        elif args.command == 'warnings':
            result = api.get_warnings(select=WarningState(args.select))
        else:
            parser.error('command required')
    except urllib.error.HTTPError as e:
        print(e, file=sys.stderr)
        obj = json.load(e)
        print(json.dumps(obj, sort_keys=True, indent=4), file=sys.stderr)
        sys.exit(1)
    except ServiceError as e:
        print('ServiceError:', e.err, file=sys.stderr)
        sys.exit(1)

    if isinstance(result, list):
        for x in result:
            print(x)
    else:
        print(result)
