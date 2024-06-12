# Copyright 2020 Canonical Ltd.
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

import io
import logging
import re
import sys
import typing
import unittest
from unittest.mock import patch

import pytest

import ops.log
from ops.model import MAX_LOG_LINE_LEN, _ModelBackend


class FakeModelBackend(_ModelBackend):
    def __init__(self):
        self._calls: typing.List[typing.Tuple[str, str]] = []

    def calls(self, clear: bool = False):
        calls = self._calls
        if clear:
            self._calls = []
        return calls

    def juju_log(self, level: str, message: str):
        for line in _ModelBackend.log_split(message):
            self._calls.append((level, line))


@pytest.fixture()
def backend():
    return FakeModelBackend()


@pytest.fixture()
def logger():
    logger = logging.getLogger()
    yield logger
    logging.getLogger().handlers.clear()
    sys.excepthook = sys.__excepthook__


class TestLogging:
    @pytest.mark.parametrize(
        'message,result',
        [
            ('critical', ('CRITICAL', 'critical')),
            ('error', ('ERROR', 'error')),
            ('warning', ('WARNING', 'warning')),
            ('info', ('INFO', 'info')),
            ('debug', ('DEBUG', 'debug')),
        ],
    )
    def test_default_logging(
        self,
        backend: FakeModelBackend,
        logger: logging.Logger,
        message: str,
        result: typing.Tuple[str, str],
    ):
        ops.log.setup_root_logging(backend)
        assert logger.level == logging.DEBUG
        assert isinstance(logger.handlers[-1], ops.log.JujuLogHandler)

        method = getattr(logger, message)
        method(message)
        calls = backend.calls(clear=True)
        assert calls == [result]

    def test_handler_filtering(self, backend: FakeModelBackend, logger: logging.Logger):
        logger.setLevel(logging.INFO)
        logger.addHandler(ops.log.JujuLogHandler(backend, logging.WARNING))
        logger.info('foo')
        assert backend.calls() == []
        logger.warning('bar')
        assert backend.calls() == [('WARNING', 'bar')]

    def test_no_stderr_without_debug(self, backend: FakeModelBackend, logger: logging.Logger):
        buffer = io.StringIO()
        with patch('sys.stderr', buffer):
            ops.log.setup_root_logging(backend, debug=False)
            logger.debug('debug message')
            logger.info('info message')
            logger.warning('warning message')
            logger.critical('critical message')
        assert backend.calls() == [
            ('DEBUG', 'debug message'),
            ('INFO', 'info message'),
            ('WARNING', 'warning message'),
            ('CRITICAL', 'critical message'),
        ]
        assert buffer.getvalue() == ''

    def test_debug_logging(self, backend: FakeModelBackend, logger: logging.Logger):
        buffer = io.StringIO()
        with patch('sys.stderr', buffer):
            ops.log.setup_root_logging(backend, debug=True)
            logger.debug('debug message')
            logger.info('info message')
            logger.warning('warning message')
            logger.critical('critical message')
        assert backend.calls() == [
            ('DEBUG', 'debug message'),
            ('INFO', 'info message'),
            ('WARNING', 'warning message'),
            ('CRITICAL', 'critical message'),
        ]
        assert re.search(
            r'\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d DEBUG    debug message\n'
            r'\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d INFO     info message\n'
            r'\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d WARNING  warning message\n'
            r'\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d CRITICAL critical message\n',
            buffer.getvalue(),
        )

    def test_reduced_logging(self, backend: FakeModelBackend, logger: logging.Logger):
        ops.log.setup_root_logging(backend)
        logger.setLevel(logging.WARNING)
        logger.debug('debug')
        logger.info('info')
        logger.warning('warning')
        assert backend.calls() == [('WARNING', 'warning')]

    def test_long_string_logging(self, backend: FakeModelBackend, logger: logging.Logger):
        buffer = io.StringIO()

        with patch('sys.stderr', buffer):
            ops.log.setup_root_logging(backend, debug=True)
            logger.debug('l' * MAX_LOG_LINE_LEN)

        assert len(backend.calls()) == 1

        backend.calls(clear=True)

        with patch('sys.stderr', buffer):
            logger.debug('l' * (MAX_LOG_LINE_LEN + 9))

        calls = backend.calls()
        assert len(calls) == 3
        # Verify that we note that we are splitting the log message.
        assert 'Splitting into multiple chunks' in calls[0][1]

        # Verify that it got split into the expected chunks.
        assert len(calls[1][1]) == MAX_LOG_LINE_LEN
        assert len(calls[2][1]) == 9


if __name__ == '__main__':
    unittest.main()
