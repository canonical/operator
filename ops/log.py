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

import logging


class JujuLogHandler(logging.Handler):
    """A handler for sending logs to Juju via juju-log."""

    def __init__(self, model_backend, level=logging.INFO):
        super().__init__(level)
        self.model_backend = model_backend

    def emit(self, record):
        self.model_backend.juju_log(record.levelname, self.format(record))


def setup_root_logging(model_backend, *, debug=False, debug_stream=None):
    """Setup python logging to forward messages to juju-log.

    :param model_backend: a ModelBackend to use for juju_log.
    :param debug: (optional) If set to True, this will log messages at DEBUG level to
        debug_stream as well as INFO to juju_log.
    :type debug: bool
    :param debug_stream: (optional) when debug is True, message will also be sent to this
        stream. If not supplied, uses the default logging.StreamHandler (stderr)
    """
    if debug:
        logLevel = logging.DEBUG
    else:
        logLevel = logging.INFO
    logger = logging.getLogger()
    logger.setLevel(logLevel)
    logger.addHandler(JujuLogHandler(model_backend))
    if debug:
        streamHandler = logging.StreamHandler(debug_stream)
        formatter = logging.Formatter('%(levelname)8s %(message)s')
        streamHandler.setFormatter(formatter)
        logger.addHandler(streamHandler)
