
from typing import Dict, List, Optional
import datetime
import enum
import http.client
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request


class UnixSocketConnection(http.client.HTTPConnection):
    def __init__(self, host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, socket_path=None):
        super(UnixSocketConnection, self).__init__(host, timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.socket_path)
        if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
            self.sock.settimeout(self.timeout)


class UnixSocketHandler(urllib.request.AbstractHTTPHandler):
    def __init__(self, socket_path):
        super(UnixSocketHandler, self).__init__()
        self.socket_path = socket_path

    def http_open(self, req):
        return self.do_open(UnixSocketConnection, req, socket_path=self.socket_path)

    http_request = urllib.request.AbstractHTTPHandler.do_request_


TIMESTAMP_RE = re.compile(r'(.*)\.(\d+)(.*)')

def parse_timestamp(s):
    match = TIMESTAMP_RE.match(s)
    if not match:
        return datetime.datetime.fromisoformat(s)
    head, subsecond, rest = match.groups()
    subsecond = subsecond[:6]  # fromisoformat supports at most 6 decimal places
    return datetime.datetime.fromisoformat(head + '.' + subsecond + rest)


def indent(s, indent='    '):
    return '\n'.join(indent+l for l in s.splitlines())


class ServiceError(Exception):
    def __init__(self, err, change):
        self.err = err
        self.change = change

    def __str__(self):
        return self.err


class WarningState(enum.Enum):
    ALL = 'all'
    PENDING = 'pending'


class ChangeState(enum.Enum):
    ALL = 'all'
    IN_PROGRESS = 'in-progress'
    READY = 'ready'


class SystemInfo:
    version: str

    @classmethod
    def from_dict(cls, d):
        s = cls()
        s.version = d['version']
        return s

    def __repr__(self):
        return 'SystemInfo(version={!r})'.format(self.version)

    __str__ = __repr__


class Warning:
    message: str
    first_added: datetime.datetime
    last_added: datetime.datetime
    last_shown: Optional[datetime.datetime]
    expire_after: str
    repeat_after: str

    @classmethod
    def from_dict(cls, d):
        w = cls()
        w.message = d['message']
        w.first_added = parse_timestamp(d['first-added'])
        w.last_added = parse_timestamp(d['last-added'])
        w.last_shown = parse_timestamp(d['last-shown']) if d.get('last-shown') else None
        w.expire_after = d['expire-after']
        w.repeat_after = d['repeat-after']
        return w

    def __repr__(self):
        return """Warning(
    message={!r},
    first_added={!r},
    last_added={!r},
    last_shown={!r},
    expire_after={!r},
    repeat_after={!r},
)""".format(
            self.message,
            self.first_added,
            self.last_added,
            self.last_shown,
            self.expire_after,
            self.repeat_after,
        )

    __str__ = __repr__


class TaskProgress:
    label: str
    done: int
    total: int

    @classmethod
    def from_dict(cls, d):
        t = cls()
        t.label = d['label']
        t.done = d['done']
        t.total = d['total']
        return t

    def __repr__(self):
        return 'TaskProgress(label={!r}, done={!r}, total={!r})'.format(
            self.label,
            self.done,
            self.total,
        )

    __str__ = __repr__


class Task:
    id: str
    kind: str
    summary: str
    status: str
    log: List[str]
    progress: TaskProgress
    spawn_time: datetime.datetime
    ready_time: Optional[datetime.datetime]

    @classmethod
    def from_dict(cls, d):
        t = cls()
        t.id = d['id']
        t.kind = d['kind']
        t.summary = d['summary']
        t.status = d['status']
        t.log = d.get('log') or []
        t.progress = TaskProgress.from_dict(d['progress'])
        t.spawn_time = parse_timestamp(d['spawn-time'])
        t.ready_time = parse_timestamp(d['ready-time']) if d.get('ready-time') else None
        return t

    def __repr__(self):
        return """Task(
    id={!r},
    kind={!r},
    summary={!r},
    status={!r},
    log={!r},
    progress={!r},
    spawn_time={!r},
    ready_time={!r},
)""".format(
            self.id,
            self.kind,
            self.summary,
            self.status,
            self.log,
            self.progress,
            self.spawn_time,
            self.ready_time,
        )

    __str__ = __repr__


class Change:
    id: str
    kind: str
    summary: str
    status: str
    tasks: List[Task]
    ready: bool
    err: str
    spawn_time: datetime.datetime
    ready_time: Optional[datetime.datetime]

    @classmethod
    def from_dict(cls, d):
        c = cls()
        c.id = d['id']
        c.kind = d['kind']
        c.summary = d['summary']
        c.status = d['status']
        c.tasks = [Task.from_dict(t) for t in d.get('tasks') or []]
        c.ready = d['ready']
        c.err = d.get('err')
        c.spawn_time = parse_timestamp(d['spawn-time'])
        c.ready_time = parse_timestamp(d['ready-time']) if d.get('ready-time') else None
        return c

    def __repr__(self):
        return """Change(
    id={!r},
    kind={!r},
    summary={!r},
    status={!r},
    tasks={},
    ready={!r},
    err={!r},
    spawn_time={!r},
    ready_time={!r},
)""".format(
            self.id,
            self.kind,
            self.summary,
            self.status,
            '[\n' + indent(',\n'.join(indent(repr(t)) for t in self.tasks)) + ',\n    ]' if self.tasks else '[]',
            self.ready,
            self.err,
            self.spawn_time,
            self.ready_time,
        )

    __str__ = __repr__


class API:
    def __init__(self, socket_path=None, opener=None, base_url='http://localhost', timeout=5.0):
        if opener is None:
            opener = self._get_default_opener(socket_path)
        self.opener = opener
        self.base_url = base_url
        self.timeout = timeout

    @classmethod
    def _get_default_opener(cls, socket_path):
        if socket_path is None:
            PEBBLE = os.getenv('PEBBLE')
            if not PEBBLE:
                raise Exception('You must specify socket_path or set $PEBBLE')
            socket_path = os.path.join(PEBBLE, '.pebble.socket')

        opener = urllib.request.OpenerDirector()
        opener.add_handler(UnixSocketHandler(socket_path))
        opener.add_handler(urllib.request.HTTPDefaultErrorHandler())
        opener.add_handler(urllib.request.HTTPRedirectHandler())
        opener.add_handler(urllib.request.HTTPErrorProcessor())
        return opener

    def _request(self, method: str, path: str, query: Dict = None, body: Dict = None) -> Dict:
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

    def get_warnings(self, select=WarningState.PENDING) -> List[Warning]:
        """Get list of warnings in given state (pending or all)."""
        query = {'select': select.value}
        result = self._request('GET', '/v1/warnings', query)
        return [Warning.from_dict(w) for w in result['result']]

    def ack_warnings(self, timestamp: datetime.datetime) -> int:
        """Acknowledge warnings up to given timestamp."""
        body = {'action': 'okay', 'timestamp': timestamp.isoformat()}
        result = self._request('POST', '/v1/warnings', body=body)
        return result['result']

    def get_changes(self, select=ChangeState.IN_PROGRESS, service=None) -> List[Change]:
        """Get list of changes in given state, filter by service name if given."""
        query = {'select': select.value}
        if service is not None:
            query['for'] = service
        result = self._request('GET', '/v1/changes', query)
        return [Change.from_dict(c) for c in result['result']]

    def get_change(self, change_id: str) -> Change:
        """Get single change by ID."""
        result = self._request('GET', '/v1/changes/{}'.format(change_id))
        return Change.from_dict(result['result'])

    def abort_change(self, change_id: str) -> Change:
        """Abort change with given ID."""
        body = {'action': 'abort'}
        result = self._request('POST', '/v1/changes/{}'.format(change_id), body=body)
        return Change.from_dict(result['result'])

    def autostart_services(self, timeout: float = 30.0, delay: float = 0.1) -> str:
        """Start the autostart services and wait (poll) for them to be started.
        If timeout is 0, submit the action but don't wait.
        """
        return self._services_action('autostart', [], timeout, delay)

    def start_services(self, services: List[str], timeout: float = 30.0, delay: float = 0.1) -> str:
        """Start services by name and wait (poll) for them to be started.
        If timeout is 0 or None, submit the action but don't wait.
        """
        return self._services_action('start', services, timeout, delay)

    def stop_services(self, services: List[str], timeout: float = 30.0, delay: float = 0.1) -> str:
        """Stop services by name and wait (poll) for them to be started.
        If timeout is 0 or None, submit the action but don't wait.
        """
        return self._services_action('stop', services, timeout, delay)

    def _services_action(self, action: str, services: List[str], timeout: float, delay: float) -> str:
        body = {'action': action, 'services': services}
        result = self._request('POST', '/v1/services', body=body)
        change_id = result['change']
        if timeout:
            self.wait_change(change_id, timeout=timeout, delay=delay)
        return change_id

    def wait_change(self, change_id: str, timeout: float = 30.0, delay: float = 0.1) -> Change:
        """Poll change every delay seconds (up to timeout) for it to be ready."""
        deadline = time.time() + timeout

        while time.time() < deadline:
            change = self.get_change(change_id)
            if change.ready:
                if change.err:
                    raise ServiceError(change.err, change)
                return change

            time.sleep(delay)

        raise TimeoutError('timed out waiting for change {} ({} seconds)'.format(change_id, timeout))


api = API()
try:
    for c in api.get_changes(select=ChangeState.ALL):
        print(c)
except urllib.error.HTTPError as e:
    print(e)
    print(e.read().decode('utf-8'))
