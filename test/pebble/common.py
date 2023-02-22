# Copyright 2023 Canonical Ltd.
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

import datetime
import io

from ops import pebble


def datetime_utc(y, m, d, hour, min, sec, micro=0):
    tz = datetime.timezone.utc
    return datetime.datetime(y, m, d, hour, min, sec, micro, tzinfo=tz)


def datetime_nzdt(y, m, d, hour, min, sec, micro=0):
    tz = datetime.timezone(datetime.timedelta(hours=13))
    return datetime.datetime(y, m, d, hour, min, sec, micro, tzinfo=tz)


class MockClient(pebble.Client):
    """Mock Pebble client that simply records requests and returns stored responses."""

    def __init__(self):
        self.requests = []
        self.responses = []
        self.timeout = 5
        self.websockets = {}

    def _request(self, method, path, query=None, body=None):
        self.requests.append((method, path, query, body))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        if callable(resp):
            resp = resp()
        return resp

    def _request_raw(self, method, path, query=None, headers=None, data=None):
        self.requests.append((method, path, query, headers, data))
        headers, body = self.responses.pop(0)
        return MockHTTPResponse(headers, body)

    def _connect_websocket(self, task_id, websocket_id):
        return self.websockets[task_id, websocket_id]


class MockHTTPResponse:
    def __init__(self, headers, body):
        self.headers = headers
        reader = io.BytesIO(body)
        self.read = reader.read


class MockTime:
    """Mocked versions of time.time() and time.sleep().

    MockTime.sleep() advances the clock and MockTime.time() returns the current time.
    """

    def __init__(self):
        self._time = 0

    def time(self):
        return self._time

    def sleep(self, delay):
        self._time += delay


def build_mock_change_dict(change_id='70'):
    return {
        "id": change_id,
        "kind": "autostart",
        "ready": True,
        "ready-time": "2021-01-28T14:37:04.291517768+13:00",
        "spawn-time": "2021-01-28T14:37:02.247202105+13:00",
        "status": "Done",
        "summary": 'Autostart service "svc"',
        "tasks": [
            {
                "id": "78",
                "kind": "start",
                "progress": {
                    "done": 1,
                    "label": "",
                    "total": 1,
                    "extra-field": "foo",
                },
                "ready-time": "2021-01-28T14:37:03.270218778+13:00",
                "spawn-time": "2021-01-28T14:37:02.247158162+13:00",
                "status": "Done",
                "summary": 'Start service "svc"',
                "extra-field": "foo",
            },
        ],
        "extra-field": "foo",
    }
