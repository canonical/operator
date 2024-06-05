"""
cl -> ser

GET /v1/tasks/12/websocket/34 HTTP/1.1\r\nUpgrade: websocket\r\nHost: localhost\r\nOrigin: http://localhost\r\nSec-WebSocket-Key: CSYKHZJp5/Fo3MsfzegtwQ==\r\nSec-WebSocket-Version: 13\r\nConnection: Upgrade\r\n\r\n

sr -> cl

HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: gREbd4xj8MeWZlUX989GaiiDMLM=\r\nDate: Wed, 05 Jun 2024 07:54:11 GMT\r\nServer: Python/3.12 websockets/12.0\r\n\r\n

# Data sequence

cl -> sr

"\201\203\362\341\221\275\263\240\320" (got 'AAA')

sr -> cl

"\201\tEcho: AAA" ('Echo: AAA')
 ^^^^- frame
     ^^- len 9
       ^^^^^^^^^- data (len 9)

"\211\4\262H\313'" (ping)


# Close sequence

cl -> sr

"\210\202\36\271\235\336\35Q"

sr -> cl

"\210\2\3\350"

cl -> sr

"" EOF


"""
import contextlib
import enum
import socket
import time
import threading

from websocket import WebSocketTimeoutException
import pytest

class Stage(enum.Enum):
    LISTEN = 1
    ACCEPT = 2
    RECEIVE_UPGRADE = 3
    PARTIAL_RESPONSE = 4


class Worker(threading.Thread):
    done = False

    def __init__(self, sock: socket.socket, stage: Stage):
        super().__init__()
        self.sock = sock
        self.stage = stage

    def run(self):
        """
        This is a little ugly, but we want to be able to clean up if the
        code under test behaves badly, forcing the fixture to return early.
        Thus, we don't want to use the blocking mode on listener or data sockets.
        """
        while self.stage >= Stage.ACCEPT.value and not self.done:
            try:
                s = self.sock.accept()
                break
            except socket.Timeout:
                continue

        while self.stage >= Stage.RECEIVE_UPGRADE.value and not self.done:
            try:
                data = s.recv(1024)
                logging.info("Expecting HTTP request with WebSocket upgrade: %r", data)
                break
            except socket.Timeout:
                continue

        if self.stage >= Stage.PARTIAL_RESPONSE.value and not self.done:
            s.send("HTTP/1.1 101 Switching Protocols\r\n")

        # Stage.COMPLETE_RESPONSE
        # requires computing Sec-WebSocket-Accept: ...
        # base64(sha1(Sec-WebSocket-Key . magic-uuid))

        while not self.done:
            time.sleep(1)

        s.close()


@pytest.fixture
def raw_domain_websocket_factory(tmp_path):
    @contextlib.contextmanager
    def websocket_factory(stage: Stage):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            path = str(tmp_path / str(stage))
            sock.bind(path)
            sock.listen(99)
            sock.settimeout(1)
            (w := Worker(sock, stage)).start()
            try:
                yield path
            finally:
                w.done = True
                w.join()
                sock.close()

    return websocket_factory

@pytest.mark.parametrize("stage", list(Stage))
def test_pebble_connection_timeout(raw_domain_websocket_factory, stage: Stage):
    with raw_domain_websocket_factory(stage) as path:
        from ops import pebble
        c = pebble.Client(path)
        started = time.time()

        # This part I don't like, because the code without the fix should get stuck forever
        # So, we'd need to isolate it into a subprocess maybe?
        with pytest.raises(WebSocketTimeoutException):
            c._connect_websocket("foo", "bar")

        spent = time.time() - started
        assert spent < 5.9
