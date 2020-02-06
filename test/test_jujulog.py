#!/usr/bin/python3

import unittest
import importlib

import logging
import ops.jujulog


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


class TestJujuLog(unittest.TestCase):

    def setUp(self):
        self.backend = FakeModelBackend()

        logging.shutdown()
        importlib.reload(logging)

    def test_default_logging(self):
        ops.jujulog.setup_default_logging(self.backend)

        logger = logging.getLogger()
        self.assertEqual(logger.level, logging.DEBUG)
        self.assertIsInstance(logger.handlers[0], ops.jujulog.JujuLogHandler)

        test_cases = [(
            lambda: logger.critical('critical'), ('CRITICAL', 'critical')
        ), (
            lambda: logger.error('error'), ('ERROR', 'error')
        ), (
            lambda: logger.warning('warning'), ('WARNING', 'warning'),
        ), (
            lambda: logger.info('info'), ('INFO', 'info'),
        ), (
            lambda: logger.debug('debug'), ('DEBUG', 'debug')
        )]

        for do, res in test_cases:
            do()
            calls = self.backend.calls(clear=True)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0], res)

    def test_handler_filtering(self):
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        logger.addHandler(ops.jujulog.JujuLogHandler(self.backend, logging.WARNING))
        logger.info('debug')
        self.assertEqual(self.backend.calls(), [])


if __name__ == '__main__':
    unittest.main()
