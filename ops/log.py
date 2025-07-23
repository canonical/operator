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
import json
import logging
import os
import sys
import types
import typing
import warnings

if typing.TYPE_CHECKING:
    from .model import _ModelBackend


TRACE: typing.Final[int] = 5
"""The TRACE log level, which is lower than DEBUG."""


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

    # Juju supports logging at TRACE level.
    logging.addLevelName(TRACE, 'TRACE')

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
        _log_security_event(
            'WARN',
            _SecurityEventSystem.SYS_CRASH,
            etype.__name__,
            description=f'Uncaught exception in charm code: {value!r}.',
        )

    sys.excepthook = except_hook


class _SecurityEventAuthN(enum.Enum):
    """Security event names for authentication events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    AUTHN_LOGIN_SUCCESS = 'authn_login_success'
    AUTHN_LOGIN_SUCCESSAFTERFAIL = 'authn_login_successafterfail'
    AUTHN_LOGIN_FAIL = 'authn_login_fail'
    AUTHN_LOGIN_FAIL_MAX = 'authn_login_fail_max'
    AUTHN_LOGIN_LOCK = 'authn_login_lock'
    AUTHN_PASSWORD_CHANGE = 'authn_password_change'  # noqa: S105
    AUTHN_PASSWORD_CHANGE_FAIL = 'authn_password_change_fail'  # noqa: S105
    AUTHN_IMPOSSIBLE_TRAVEL = 'authn_impossible_travel'
    AUTHN_TOKEN_CREATED = 'authn_token_created'  # noqa: S105
    AUTHN_TOKEN_REVOKED = 'authn_token_revoked'  # noqa: S105
    AUTHN_TOKEN_REUSE = 'authn_token_reuse'  # noqa: S105
    AUTHN_TOKEN_DELETE = 'authn_token_delete'  # noqa: S105


class _SecurityEventAuthZ(enum.Enum):
    """Security event names for system events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    AUTHZ_FAIL = 'authz_fail'
    AUTHZ_CHANGE = 'authz_change'
    AUTHZ_ADMIN = 'authz_admin'


class _SecurityEventCrypt(enum.Enum):
    """Security event names for cryptographic events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    CRYPT_DECRYPT_FAIL = 'crypt_decrypt_fail'
    CRYPT_ENCRYPT_FAIL = 'crypt_encrypt_fail'


class _SecurityEventExcess(enum.Enum):
    """Security event names for excess events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    EXCESS_RATE_LIMIT_EXCEEDED = 'excess_rate_limit_exceeded'


class _SecurityEventUpload(enum.Enum):
    """Security event names for upload events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    UPLOAD_COMPLETE = 'upload_complete'
    UPLOAD_STORED = 'upload_stored'
    UPLOAD_VALIDATION = 'upload_validation'
    UPLOAD_DELETE = 'upload_delete'


class _SecurityEventInput(enum.Enum):
    """Security event names for input events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    INPUT_VALIDATION_FAIL = 'input_validation_fail'


class _SecurityEventMalicious(enum.Enum):
    """Security event names for malicious events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    MALICIOUS_EXCESS_404 = 'malicious_excess_404'
    MALICIOUS_EXTRANEOUS = 'malicious_extraneous'
    MALICIOUS_ATTACK_TOOL = 'malicious_attack_tool'
    MALICIOUS_CORS = 'malicious_cors'
    MALICIOUS_DIRECT_REFERENCE = 'malicious_direct_reference'


class _SecurityEventPrivilege(enum.Enum):
    """Security event names for privilege and permissions events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    PRIVILEGE_PERMISSIONS_CHANGED = 'privilege_permissions_changed'


class _SecurityEventSensitive(enum.Enum):
    """Security event names for sensitive data events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    SENSITIVE_CREATE = 'sensitive_create'
    SENSITIVE_READ = 'sensitive_read'
    SENSITIVE_UPDATE = 'sensitive_update'
    SENSITIVE_DELETE = 'sensitive_delete'


class _SecurityEventSequence(enum.Enum):
    """Security event names for sequence events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    SEQUENCE_FAIL = 'sequence_fail'


class _SecurityEventSession(enum.Enum):
    """Security event names for session events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    SESSION_CREATED = 'session_created'
    SESSION_RENEWED = 'session_renewed'
    SESSION_EXPIRED = 'session_expired'
    SESSION_USE_AFTER_EXPIRE = 'session_use_after_expire'


class _SecurityEventSystem(enum.Enum):
    """Security event names for system events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    SYS_STARTUP = 'sys_startup'
    SYS_SHUTDOWN = 'sys_shutdown'
    SYS_RESTART = 'sys_restart'
    SYS_CRASH = 'sys_crash'
    SYS_MONITOR_DISABLED = 'sys_monitor_disabled'
    SYS_MONITOR_ENABLED = 'sys_monitor_enabled'


class _SecurityEventUser(enum.Enum):
    """Security event names for user events.

    See https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary_Cheat_Sheet.html
    """

    USER_CREATED = 'user_created'
    USER_UPDATED = 'user_updated'
    USER_ARCHIVED = 'user_archived'
    USER_DELETED = 'user_deleted'


_SecurityEvent = typing.Union[
    _SecurityEventAuthN,
    _SecurityEventAuthZ,
    _SecurityEventCrypt,
    _SecurityEventExcess,
    _SecurityEventUpload,
    _SecurityEventInput,
    _SecurityEventMalicious,
    _SecurityEventPrivilege,
    _SecurityEventSensitive,
    _SecurityEventSequence,
    _SecurityEventSession,
    _SecurityEventSystem,
    _SecurityEventUser,
]


def _log_security_event(
    # These are the OWASP log levels, which are not the same as the Juju or Python log levels.
    level: typing.Literal['INFO', 'WARN', 'CRITICAL'],
    event_type: _SecurityEvent | str,
    event: str,
    *,
    description: str,
):
    """Send a structured security event log to Juju, as defined by SEC0045.

    Args:
        level: log level of the security event (this is not the same as the Juju log level)
        event_type: the event type, in the format described by OWASP
          https://cheatsheetseries.owasp.org/cheatsheets/Logging_Vocabulary
        event: the name of the event, in the format described by OWASP
        description: a free-form description of the event, meant for human
          consumption. Includes additional details of the event that do not
          fit in the event name.
    """
    logger = logging.getLogger(__name__)
    app_id = (
        f'{os.environ.get("JUJU_MODEL_UUID", "unknown")}'
        f'-{os.environ.get("JUJU_UNIT_NAME", "unknown")}'
    )
    type = event_type if isinstance(event_type, str) else event_type.value
    data: dict[str, typing.Any] = {
        # This duplicates the timestamp that will be in the Juju log, but is
        # included so that applications that are pulling out only the structured
        # data can still see the time of the event.
        'datetime': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        # Note that the Juju log level is not the same as the event level.
        'level': level,
        'type': 'security',
        'appid': app_id,
        'event': f'{type}:{event}',
        'description': description,
    }
    logger.log(TRACE, '%s', json.dumps(data))
