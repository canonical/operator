# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Run a charm's events in a separate worker process.

The main test process never imports the charm: it reads the metadata from disk,
and events and ``State`` cross to the worker as JSON. Each application has its
own worker, which starts on the first event and is kept for later ones. A
worker that dies or times out raises :class:`IsolationError`, and isn't started
again.
"""

from __future__ import annotations

import collections
import contextlib
import os
import pathlib
import subprocess
import sys
import threading
from collections.abc import Sequence
from typing import IO, Any

from . import _state_json
from ._isolation_errors import IsolationError
from ._worker_protocol import read_message, write_message
from .context import _DEFAULT_JUJU_VERSION
from .state import State, _CharmSpec, _Event

# Seconds one event may run before the worker is killed.
# A guard against a hang, not a performance check: the first event also
# imports the charm, which can be slow for a large charm on a busy CI runner.
_DEFAULT_TIMEOUT = 60.0


# Python puts the current directory first on sys.path when running -c, and
# the worker inherits the test's, which would shadow the worker's own ops and
# scenario. PYTHONSAFEPATH and -P only exist from Python 3.11, and the worker's
# interpreter may be older, so the bootstrap removes the entry itself.
_WORKER_BOOTSTRAP = """\
import runpy, sys
if sys.path and sys.path[0] == '':
    del sys.path[0]
runpy.run_module('scenario._isolated_worker', run_name='__main__', alter_sys=True)
"""


def _worker_environ() -> dict[str, str]:
    environ = dict(os.environ)
    # Run unbuffered so that a charm's output is written before the worker is killed.
    environ['PYTHONUNBUFFERED'] = '1'
    # The worker is a new process, so it can import this scenario only if the
    # directory that holds the package is on its sys.path.
    scenario_parent = pathlib.Path(__file__).resolve().parent.parent
    if scenario_parent.name in {'site-packages', 'dist-packages'}:
        # Installed. The test's own interpreter already has this directory on
        # its path. Another interpreter needs its own ops-scenario, because
        # adding this directory would bring in the test environment's other
        # packages too, which would undo the isolation.
        return environ
    # A source checkout or an editable install. This directory holds only
    # scenario, so adding it gives any interpreter this scenario and nothing else.
    existing = environ.get('PYTHONPATH')
    parts = [str(scenario_parent), *([existing] if existing else [])]
    environ['PYTHONPATH'] = os.pathsep.join(parts)
    return environ


class Worker:
    """A worker process that runs events for one application's units.

    The application's name and trust are fixed when the worker is created, and
    each event names the unit it runs as, so one worker serves every unit. Two
    applications of the same charm need a worker each.

    Args:
        charm_source: The charm's directory, with ``src/charm.py``.
        python: The interpreter to run the worker with. The default is the
            test's own, so the worker gets a fresh ``sys.modules`` but the same
            installed packages. Give another environment's interpreter to
            isolate those too.
        extra_sys_path: Directories put at the front of the worker's
            ``sys.path`` before the charm is imported.
        app_name: The application name; the charm's name if not given.
        juju_version: The Juju version the charm sees.
        app_trusted: Whether the application is trusted.
        timeout: Seconds one event may run before the worker is killed.
            ``None`` waits for as long as it takes.
    """

    def __init__(
        self,
        charm_source: pathlib.Path,
        *,
        python: str = sys.executable,
        extra_sys_path: Sequence[str] = (),
        app_name: str | None = None,
        juju_version: str = _DEFAULT_JUJU_VERSION,
        app_trusted: bool = False,
        timeout: float | None = _DEFAULT_TIMEOUT,
    ):
        meta, config, actions = _CharmSpec._load_metadata_or_legacy(charm_source)
        self.app_name: str = app_name or meta['name']
        self._setup = {
            'charm_source': str(charm_source),
            'extra_sys_path': list(extra_sys_path),
            'meta': meta,
            'config': config,
            'actions': actions,
            'app_name': self.app_name,
            'juju_version': juju_version,
            'app_trusted': app_trusted,
        }
        self._command = [python, '-c', _WORKER_BOOTSTRAP]
        self._environ = _worker_environ()
        self._timeout = timeout
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr: collections.deque[str] = collections.deque(maxlen=200)
        self._stderr_reader: threading.Thread | None = None
        self._reader: threading.Thread | None = None
        self._crashed = False

    def run(self, event: _Event, state: State, *, unit_id: int = 0) -> State:
        """Run ``event`` on ``state`` as unit ``unit_id``, and return the output ``State``.

        Raises:
            IsolationError: if the charm raised, or the worker crashed or
                timed out, now or earlier.
        """
        if self._crashed:
            raise IsolationError(
                f'The worker for {self.app_name!r} crashed earlier, and is not restarted.'
            )
        request = {
            'unit_id': unit_id,
            'event': _state_json.encode_event(event),
            'state': _state_json.encode_state(state),
        }
        starting = self._proc is None
        if starting:
            self._start()
        proc = self._proc
        assert proc is not None and proc.stdin is not None and proc.stdout is not None
        try:
            if starting:
                write_message(proc.stdin, self._setup)
            write_message(proc.stdin, request)
            response = self._read_response(proc.stdout)
        except TimeoutError:
            raise self._fail(
                f'An event took more than {self._timeout} seconds, and the worker was killed.'
            ) from None
        except (OSError, ValueError):
            response = None
        if response is None:
            raise self._fail('The worker crashed without responding.')
        if 'error' in response:
            raise IsolationError(f'The charm failed in its worker:\n{response["error"]}')
        return _state_json.decode_state(response['state'])

    def close(self) -> None:
        """Stop the worker, if it's running.

        A later event starts a new worker, unless this one crashed.
        """
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        assert proc.stdin is not None
        try:
            proc.stdin.close()  # The worker exits when its input closes.
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait()
        self._finish(proc)

    def _start(self) -> None:
        self._proc = proc = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._environ,
        )
        self._stderr.clear()
        # Read stderr as it comes, so a full pipe can't block the worker, and
        # so there's something to report if it crashes.
        self._stderr_reader = threading.Thread(
            target=self._read_stderr, args=(proc.stderr,), daemon=True
        )
        self._stderr_reader.start()

    def _read_stderr(self, stream: IO[bytes]) -> None:
        try:
            # A size limit splits a long line, so the deque bounds memory too.
            for chunk in iter(lambda: stream.readline(4096), b''):
                self._stderr.append(chunk.decode(errors='replace'))
        except (OSError, ValueError):
            pass  # Closed by _finish.

    @staticmethod
    def _read_message_into(stream: IO[bytes], result: list[dict[str, Any] | None]) -> None:
        try:
            result.append(read_message(stream))
        except (OSError, ValueError):
            pass  # Closed by _finish.

    def _read_response(self, stream: IO[bytes]) -> dict[str, Any] | None:
        if self._timeout is None:
            return read_message(stream)
        # Reads from a pipe block, so the read runs on a thread. On a timeout,
        # killing the worker closes the other end of the pipe, which ends it.
        result: list[dict[str, Any] | None] = []
        self._reader = threading.Thread(
            target=self._read_message_into, args=(stream, result), daemon=True
        )
        self._reader.start()
        self._reader.join(self._timeout)
        if self._reader.is_alive():
            raise TimeoutError
        return result[0] if result else None

    def _fail(self, message: str) -> IsolationError:
        self._crashed = True
        proc = self._proc
        assert proc is not None
        self._proc = None
        proc.kill()
        proc.wait()
        self._finish(proc)
        stderr = ''.join(self._stderr).strip()
        return IsolationError(
            f'{message}\nReturn code: {proc.returncode}\n'
            f'Worker stderr (most recent output):\n{stderr}'
        )

    def _finish(self, proc: subprocess.Popen[bytes]) -> None:
        for thread in (self._reader, self._stderr_reader):
            if thread is not None:
                thread.join(timeout=1)
        self._reader = self._stderr_reader = None
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                # Closing stdin flushes it, which fails if the worker is gone.
                with contextlib.suppress(OSError):
                    stream.close()
