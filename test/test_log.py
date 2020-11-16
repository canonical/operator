#!/usr/bin/python3

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
import unittest
from unittest.mock import patch

import logging
import ops.log


class FakeModelBackend:

    def __init__(self):
        self._calls = []

    def calls(self, clear=False):
        calls = self._calls
        if clear:
            self._calls = []
        return calls

    def juju_log(self, message, level):
        self._calls.append((message, level))


class TestLogging(unittest.TestCase):

    def setUp(self):
        self.backend = FakeModelBackend()

    def tearDown(self):
        logging.getLogger().handlers.clear()

    def test_default_logging(self):
        ops.log.setup_root_logging(self.backend)

        logger = logging.getLogger()
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertIsInstance(logger.handlers[-1], ops.log.JujuLogHandler)

        test_cases = [
            (logger.critical, 'critical', ('CRITICAL', 'critical')),
            (logger.error, 'error', ('ERROR', 'error')),
            (logger.warning, 'warning', ('WARNING', 'warning')),
            (logger.info, 'info', ('INFO', 'info')),
            (logger.debug, 'debug', ('DEBUG', 'debug')),
        ]

        for method, message, result in test_cases:
            with self.subTest(message):
                method(message)
                calls = self.backend.calls(clear=True)
                self.assertEqual(calls, [result])

    def test_handler_filtering(self):
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(ops.log.JujuLogHandler(self.backend, logging.WARNING))
        logger.info('foo')
        self.assertEqual(self.backend.calls(), [])
        logger.warning('bar')
        self.assertEqual(self.backend.calls(), [('WARNING', 'bar')])

    def test_no_stderr_without_debug(self):
        buffer = io.StringIO()
        with patch('sys.stderr', buffer):
            ops.log.setup_root_logging(self.backend, debug=False)
            logger = logging.getLogger()
            logger.debug('debug message')
            logger.info('info message')
            logger.warning('warning message')
            logger.critical('critical message')
        self.assertEqual(
            self.backend.calls(),
            [('DEBUG', 'debug message'),
             ('INFO', 'info message'),
                ('WARNING', 'warning message'),
                ('CRITICAL', 'critical message'),
             ])
        self.assertEqual(buffer.getvalue(), "")

    def test_debug_logging(self):
        buffer = io.StringIO()
        with patch('sys.stderr', buffer):
            ops.log.setup_root_logging(self.backend, debug=True)
            logger = logging.getLogger()
            logger.debug('debug message')
            logger.info('info message')
            logger.warning('warning message')
            logger.critical('critical message')
        self.assertEqual(
            self.backend.calls(),
            [('DEBUG', 'debug message'),
             ('INFO', 'info message'),
             ('WARNING', 'warning message'),
             ('CRITICAL', 'critical message'),
             ])
        self.assertRegex(
            buffer.getvalue(),
            r"\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d DEBUG    debug message\n"
            r"\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d INFO     info message\n"
            r"\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d WARNING  warning message\n"
            r"\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d,\d\d\d CRITICAL critical message\n"
        )

    def test_reduced_logging(self):
        ops.log.setup_root_logging(self.backend)
        logger = logging.getLogger()
        logger.setLevel(logging.WARNING)
        logger.debug('debug')
        logger.info('info')
        logger.warning('warning')
        self.assertEqual(self.backend.calls(), [('WARNING', 'warning')])


if __name__ == '__main__':
    unittest.main()
