#!/usr/bin/env python3
#
# Copyright 2022 Canonical Ltd.
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

"""Charm the service.

Refer to the following post for a quick-start guide that will help you
develop a new k8s charm using the ops library:

    https://discourse.charmhub.io/t/4208
"""

import logging

import ops

logger = logging.getLogger(__name__)


class SmokeCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)

    def _on_install(self, event: ops.EventBase):
        self.unit.status = ops.ActiveStatus()


if __name__ == '__main__':
    ops.main(SmokeCharm)
