# Copyright 2025 Canonical Ltd.
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

"""Canaries for upstream regressions that block tracing integration tests."""

from __future__ import annotations

import shutil
import subprocess

import pytest

# This is the tag pinned in conftest.py via the ``nginx-image`` resource for
# tempo-coordinator-k8s; it is also the charm's own ``upstream-source``.
TEMPO_NGINX_IMAGE = 'ubuntu/nginx:1.24-24.04_beta'


@pytest.mark.xfail(
    strict=True,
    reason=(
        'tempo-coordinator-k8s rev 143 crashes in upgrade-charm because '
        'coordinated_workers/nginx.py:_delete_certificates calls '
        '`update-ca-certificates --fresh` in the nginx workload container, '
        'and the pinned ubuntu/nginx image does not ship that binary. '
        'When this xfail unexpectedly passes, the upstream image has been '
        'fixed and the gated integration tests in test_tracing.py can be '
        're-enabled.'
    ),
)
def test_tempo_nginx_image_ships_update_ca_certificates():
    """When this xpasses, the integration tests in test_tracing.py can run again."""
    docker = shutil.which('docker') or shutil.which('podman')
    if docker is None:
        pytest.skip('needs docker or podman to pull and inspect the upstream image')

    result = subprocess.run(
        [
            docker,
            'run',
            '--rm',
            '--entrypoint',
            '/bin/sh',
            TEMPO_NGINX_IMAGE,
            '-c',
            'command -v update-ca-certificates',
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, (
        f'{TEMPO_NGINX_IMAGE} still lacks update-ca-certificates '
        f'(stdout={result.stdout!r}, stderr={result.stderr!r})'
    )
