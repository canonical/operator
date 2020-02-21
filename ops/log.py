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


def setup_root_logging(model_backend):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(JujuLogHandler(model_backend))
