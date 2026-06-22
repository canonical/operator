#!/usr/bin/env python3

# Copyright 2026 Canonical Ltd.
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

"""Functions for interacting with the workload.

The intention is that this module could be used outside the context of a charm.
"""

import json
import logging
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def get_version(port: int) -> str:
    """Get the version of fastapi_demo that is running.

    Args:
        port: The port where fastapi_demo web server is listening.

    Raises:
        RuntimeError: If the server can't be reached, for example because of an invalid port.
    """
    try:
        response = urllib.request.urlopen(f"http://0.0.0.0:{port}/version")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Could not connect to the workload server on port {port}") from e
    data = json.loads(response.read())
    return data["version"]