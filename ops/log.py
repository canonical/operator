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

"""Interface to emit messages to the Juju logging system."""

import logging
import sys
import types
import typing

from ops.model import _ModelBackend


class JujuLogHandler(logging.Handler):
    """A handler for sending logs to Juju via juju-log."""

    def __init__(self, model_backend: _ModelBackend, level: int = logging.DEBUG):
        super().__init__(level)
        self.model_backend = model_backend

    def emit(self, record: logging.LogRecord):
        """Send the specified logging record to the Juju backend.

        This method is not used directly by the ops library, but by
        :class:`logging.Handler` itself as part of the logging machinery.
        """
        self.model_backend.juju_log(record.levelname, self.format(record))


def setup_root_logging(
    model_backend: _ModelBackend, debug: bool = False, exc_stderr: bool = False
):
    """Setup python logging to forward messages to juju-log.

    By default, logging is set to DEBUG level, and messages will be filtered by Juju.
    Charmers can also set their own default log level with::

      logging.getLogger().setLevel(logging.INFO)

    Args:
        model_backend: a ModelBackend to use for juju-log
        debug: if True, write logs to stderr as well as to juju-log.
        exc_stderr: if True, write uncaught exceptions to stderr as well as to juju-log.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(JujuLogHandler(model_backend))
    if debug:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    def except_hook(
        etype: typing.Type[BaseException], value: BaseException, tb: types.TracebackType
    ):
        logger.error('Uncaught exception while in charm code:', exc_info=(etype, value, tb))
        if exc_stderr:
            print(f'Uncaught {etype.__name__} in charm code: {value}', file=sys.stderr)
            print('Use `juju debug-log` to see the full traceback.', file=sys.stderr)

    sys.excepthook = except_hook
