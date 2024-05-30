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

"""Fake (partial) Pebble server to allow testing the HTTP-over-Unix-socket protocol."""

import http.server
import json
import os
import re
import socket
import socketserver
import tempfile
import threading
import typing
import urllib.parse

from typing_extensions import NotRequired

_Response = typing.TypedDict(
    '_Response',
    {
        'result': typing.Optional[typing.Dict[str, str]],
        'status': str,
        'status-code': int,
        'type': str,
        'change': NotRequired[str],
    },
)


class Handler(http.server.BaseHTTPRequestHandler):
    _route = typing.List[
        typing.Tuple[typing.Literal['GET', 'POST'], typing.Any, typing.Callable[..., None]]
    ]

    def __init__(
        self,
        request: socket.socket,
        client_address: typing.Tuple[str, int],
        server: socketserver.BaseServer,
    ):
        self.routes: Handler._route = [
            ('GET', re.compile(r'^/system-info$'), self.get_system_info),
            ('POST', re.compile(r'^/services$'), self.services_action),
        ]
        self._services = ['foo']
        super().__init__(request, ('unix-socket', 80), server)

    def log_message(self, format: str, *args: typing.Any):
        # Disable logging for tests
        pass

    def respond(self, d: _Response, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        d_json = json.dumps(d, indent=4, sort_keys=True)
        self.wfile.write(d_json.encode('utf-8'))

    def bad_request(self, message: str):
        d: _Response = {
            'result': {
                'message': message,
            },
            'status': 'Bad Request',
            'status-code': 400,
            'type': 'error',
        }
        self.respond(d, 400)

    def not_found(self):
        d: _Response = {
            'result': {'message': 'invalid API endpoint requested'},
            'status': 'Not Found',
            'status-code': 404,
            'type': 'error',
        }
        self.respond(d, 404)

    def method_not_allowed(self):
        d: _Response = {
            'result': {'message': 'method "PUT" not allowed'},
            'status': 'Method Not Allowed',
            'status-code': 405,
            'type': 'error',
        }
        self.respond(d, 405)

    def internal_server_error(self, msg: Exception):
        d: _Response = {
            'result': {
                'message': f'internal server error: {msg}',
            },
            'status': 'Internal Server Error',
            'status-code': 500,
            'type': 'error',
        }
        self.respond(d, 500)

    def do_GET(self):  # noqa: N802 ("should be lowercase")
        self.do_request('GET')

    def do_POST(self):  # noqa: N802 ("should be lowercase")
        self.do_request('POST')

    def do_request(self, request_method: typing.Literal['GET', 'POST']):
        path, _, query = self.path.partition('?')
        path = urllib.parse.unquote(path)
        query = dict(urllib.parse.parse_qsl(query))

        if not path.startswith('/v1/'):
            self.not_found()
            return
        path = path[3:]

        allowed: typing.List[str] = []
        for method, regex, func in self.routes:
            match = regex.match(path)
            if match:
                if request_method == method:
                    data = self.read_body_json()
                    try:
                        func(match, query, data)
                    except Exception as e:
                        self.internal_server_error(e)
                        raise
                    return
                allowed.append(method)

        if allowed:
            self.method_not_allowed()
            return

        self.not_found()

    def read_body_json(self) -> typing.Dict[str, str]:
        try:
            content_len = int(self.headers.get('Content-Length', ''))
        except ValueError:
            content_len = 0
        if not content_len:
            return {}
        body = self.rfile.read(content_len)
        if isinstance(body, bytes):
            body = body.decode('utf-8')
        return json.loads(body)

    def get_system_info(
        self, match: typing.Any, query: typing.Dict[str, str], data: typing.Dict[str, str]
    ):
        self.respond({
            'result': {'version': '3.14.159'},
            'status': 'OK',
            'status-code': 200,
            'type': 'sync',
        })

    def services_action(
        self, match: typing.Any, query: typing.Dict[str, str], data: typing.Dict[str, str]
    ):
        action = data['action']
        services = data['services']
        if action == 'start':
            for service in services:
                if service not in self._services:
                    self.bad_request(f'service "{service}" does not exist')
                    return
            self.respond({
                'change': '1234',
                'result': None,
                'status': 'Accepted',
                'status-code': 202,
                'type': 'async',
            })
        else:
            self.bad_request(f'action "{action}" not implemented')


def start_server() -> typing.Tuple[typing.Callable[[], None], str]:
    socket_dir = tempfile.mkdtemp(prefix='test-ops.pebble')
    socket_path = os.path.join(socket_dir, 'test.socket')

    server = socketserver.UnixStreamServer(socket_path, Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

    def shutdown():
        server.shutdown()
        server.server_close()
        thread.join()
        os.remove(socket_path)
        os.rmdir(socket_dir)

    return (shutdown, socket_path)


if __name__ == '__main__':
    import time

    shutdown, socket_path = start_server()
    print('Serving HTTP over socket', socket_path)

    # Wait forever (or till Ctrl-C pressed)
    try:
        while True:
            time.sleep(1)
    finally:
        shutdown()
