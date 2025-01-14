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

import contextvars
import logging
import sys
import types
import typing
import warnings

from ops.model import _ModelBackend


class JujuLogHandler(logging.Handler):
    """A handler for sending logs and warnings to Juju via juju-log."""

    drop: contextvars.ContextVar[bool]
    """When set to True, drop any record we're asked to emit, because:
    - either we're already logging here and the record is recursive,
    - or we're exporting tracing data and the record stems from that.

    # FIXME suggest a better name for this attribute
    #
    # Typical code path:
    # logging -> this logger -> juju-log hook tool -> error ->
    # logging [recursion]
    #
    # or
    #
    # helper thread -> export -> real export -> requests -> urllib3 -> log.debug(...)
    #
    # and additionally
    # shutdown_tracing -> ... -> start_as_new_span -> if shutdown: logger.warning(...)
    #
    # FIXME: decision to be made if we want to capture export errors
    """

    def __init__(self, model_backend: _ModelBackend, level: int = logging.DEBUG):
        super().__init__(level)
        self.model_backend = model_backend
        self.drop = contextvars.ContextVar('drop', default=False)

    def emit(self, record: logging.LogRecord):
        """Send the specified logging record to the Juju backend.

        This method is not used directly by the ops library, but by
        :class:`logging.Handler` itself as part of the logging machinery.
        """
        if self.drop.get():
            return

        token = self.drop.set(True)
        try:
            self.model_backend.juju_log(record.levelname, self.format(record))
        finally:
            self.drop.reset(token)


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
    # FIXME temporary for debug, don't merge
    # NOTE: figure out why I sometimes need this and other times I don't
    # logger.addHandler(logging.StreamHandler(stream=sys.stderr))
    # logger.handlers[-1].setLevel(logging.NOTSET)

    def custom_showwarning(
        message: typing.Union[Warning, str],
        category: typing.Type[Warning],
        filename: str,
        lineno: int,
        file: typing.Optional[typing.TextIO] = None,
        line: typing.Optional[str] = None,
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
        etype: typing.Type[BaseException], value: BaseException, tb: types.TracebackType
    ):
        logger.error('Uncaught exception while in charm code:', exc_info=(etype, value, tb))
        if exc_stderr:
            print(f'Uncaught {etype.__name__} in charm code: {value}', file=sys.stderr)
            print('Use `juju debug-log` to see the full traceback.', file=sys.stderr)

    sys.excepthook = except_hook
