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

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import types
import typing
import warnings

if typing.TYPE_CHECKING:
    from .model import _ModelBackend


class JujuLogHandler(logging.Handler):
    """A handler for sending logs and warnings to Juju via juju-log."""

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
    """Setup Python logging to forward messages to juju-log.

    By default, logging is set to DEBUG level, and messages will be filtered by Juju.
    Charmers can also set their own default log level with::

      logging.getLogger().setLevel(logging.INFO)

    Warnings issued by the warnings module are redirected to the logging system
    and forwarded to juju-log, too.

    Args:
        model_backend: a ModelBackend to use for juju-log
        debug: if True, write logs to stderr as well as to juju-log.
        exc_stderr: if True, write uncaught exceptions to stderr as well as to juju-log.
    """
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger.addHandler(JujuLogHandler(model_backend))

    def custom_showwarning(
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: typing.TextIO | None = None,
        line: str | None = None,
    ):
        """Direct the warning to Juju's debug-log, and don't include the code."""
        logger.warning('%s:%s: %s: %s', filename, lineno, category.__name__, message)

    warnings.showwarning = custom_showwarning

    if debug:
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    def except_hook(etype: type[BaseException], value: BaseException, tb: types.TracebackType):
        logger.error('Uncaught exception while in charm code:', exc_info=(etype, value, tb))
        if exc_stderr:
            print(f'Uncaught {etype.__name__} in charm code: {value}', file=sys.stderr)
            print('Use `juju debug-log` to see the full traceback.', file=sys.stderr)
        _security_event(
            f'sys_crash:{etype.__name__}',
            level='ERROR',
            description=f'Uncaught exception in charm code: {value!r}.',
        )

    sys.excepthook = except_hook


def _security_event(event: str, *, level: str, description: str):
    """Send a structured security event log to Juju, as defined by SEC0045.

    Args:
        event: the name of the event, in the format described by OWASP
          https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
        level: log level, such as 'DEBUG', 'INFO', or 'ERROR'
        description: a free-form description of the event, meant for human
          consumption. Includes additional details of the event that do not
          fit in the event name.
    """
    logger = logging.getLogger(__name__)
    data: dict[str, typing.Any] = {
        # This duplicates the timestamp that will be in the Juju log, but is
        # included so that applications that are pulling out only the structured
        # data can still see the time of the event.
        'datetime': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        # Similarly, this duplicates the level at which this is logged to Juju.
        'level': level,
        'type': 'security',
        'appid': os.environ.get('JUJU_MODEL_UUID', 'unknown'),
        'event': event,
        'description': description,
    }
    logger.log(getattr(logging, level.upper()), json.dumps(data))
