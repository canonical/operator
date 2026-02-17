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
import enum
import functools
import json
import logging
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
        debug: if true, write logs to stderr as well as to juju-log.
        exc_stderr: if true, write uncaught exceptions to stderr as well as to juju-log.
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

    def except_hook(
        etype: type[BaseException], value: BaseException, tb: types.TracebackType | None
    ):
        logger.error('Uncaught exception while in charm code:', exc_info=(etype, value, tb))
        if exc_stderr:
            print(f'Uncaught {etype.__name__} in charm code: {value}', file=sys.stderr)
            print('Use `juju debug-log` to see the full traceback.', file=sys.stderr)
        _log_security_event(
            _SecurityEventLevel.WARN,
            _SecurityEvent.SYS_CRASH,
            etype.__name__,
            description=f'Uncaught exception in charm code: {value!r}.',
        )

    sys.excepthook = except_hook


class _SecurityEvent(enum.Enum):
    """Security event names.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    AUTHZ_FAIL = 'authz_fail'
    SYS_RESTART = 'sys_restart'
    SYS_CRASH = 'sys_crash'
    SYS_MONITOR_DISABLED = 'sys_monitor_disabled'


class _SecurityEventLevel(enum.Enum):
    """Security event levels.

    These are the OWASP log levels, which are not the same as the Juju or Python log levels.
    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    INFO = 'INFO'
    WARN = 'WARN'
    CRITICAL = 'CRITICAL'


@functools.cache
def _get_juju_log_and_app_id():
    logger = logging.getLogger()
    for juju_handler in logger.handlers:
        if isinstance(juju_handler, JujuLogHandler):
            model_backend = juju_handler.model_backend
            juju_context = model_backend._juju_context
            app_id = f'{juju_context.model_uuid}-{juju_context.unit_name}'
            juju_log = model_backend.juju_log
            return juju_log, app_id

    warnings.warn(
        'JujuLogHandler is not set up for the logger. '
        'Call setup_root_logging() before logging security events.',
        RuntimeWarning,
    )

    def juju_log(level: str, message: str):
        logger.debug(message)

    return juju_log, 'charm'


def _log_security_event(
    level: _SecurityEventLevel | str,
    event_type: _SecurityEvent | str,
    event_data: str,
    *,
    description: str,
):
    """Send a structured security event log to Juju, as defined by SEC0045.

    Args:
        level: log level of the security event (this is not the same as the Juju log level)
        event_type: the event type, in the format described by OWASP
          https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary
        event_data: the name of the event, in the format described by OWASP
        description: a free-form description of the event, meant for human
          consumption. Includes additional details of the event that do not
          fit in the event name.
    """
    juju_log, app_id = _get_juju_log_and_app_id()
    type = event_type if isinstance(event_type, str) else event_type.value
    data: dict[str, typing.Any] = {
        # This duplicates the timestamp that will be in the Juju log, but is
        # included so that applications that are pulling out only the structured
        # data can still see the time of the event.
        'datetime': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        # Note that the Juju log level is not the same as the event level.
        'level': level if isinstance(level, str) else level.value,
        'type': 'security',
        'appid': app_id,
        'event': f'{type}:{event_data}',
        'description': description,
    }
    juju_log('TRACE', json.dumps(data))
