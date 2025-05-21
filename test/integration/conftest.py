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
#
# Learn more about testing at
# https://ops.readthedocs.io/en/latest/explanation/testing.html

from __future__ import annotations

import logging
import pathlib
import subprocess
from typing import Callable, Generator

import jubilant
import minio
import pytest


@pytest.fixture
def juju() -> Generator[jubilant.Juju]:
    """Make a Juju model with the tracing part of COS ready."""
    with jubilant.temp_model() as juju:
        juju.wait_timeout = 360
        deploy_tempo(juju)
        deploy_tempo_worker(juju)
        juju.deploy('minio', config={'access-key': 'accesskey', 'secret-key': 'mysoverysecretkey'})
        juju.deploy('s3-integrator')

        juju.integrate('tempo:s3', 's3-integrator')
        juju.integrate('tempo:tempo-cluster', 'tempo-worker')

        juju.wait(
            lambda status: jubilant.all_active(status, 'minio')
            and jubilant.all_blocked(status, 's3-integrator')
        )

        address = juju.status().apps['minio'].address
        mc_client = minio.Minio(
            f'{address}:9000',
            access_key='accesskey',
            secret_key='mysoverysecretkey',
            secure=False,
        )

        found = mc_client.bucket_exists('tempo')
        if not found:
            mc_client.make_bucket('tempo')

        juju.config('s3-integrator', dict(endpoint=f'http://{address}:9000', bucket='tempo'))
        juju.run(
            's3-integrator/0',
            'sync-s3-credentials',
            {'access-key': 'accesskey', 'secret-key': 'mysoverysecretkey'},
        )

        # Tempo goes through a cycle of:
        # - update own stateful set
        # - kill own pod
        # - new pod is scheduled by k8s
        # - check own stateful set
        #
        # This process may take a while.

        juju.wait(jubilant.all_active)

        yield juju

        print(juju.debug_log())


@pytest.fixture(scope='session')
def charm_dir(pytestconfig: pytest.Config) -> Generator[pathlib.Path]:
    """Prepare and return the test charm directory.

    Builds and injects `ops` and `ops-tracing` from the local checkout in to the
    charm's dependencies. Cleans up afterwards.
    """
    charm_dir = pytestconfig.rootpath / 'test/charms/test_tracing'
    requirements_file = charm_dir / 'requirements.txt'

    def cleanup():
        """Ensure pristine test charm directory."""
        for path in charm_dir.glob('ops*.tar.gz'):
            path.unlink()
        for path in charm_dir.glob('*.charm'):
            path.unlink()
        if requirements_file.exists():
            requirements_file.unlink()

    cleanup()

    try:
        subprocess.run(
            [  # noqa: S607
                'uv',
                'build',
                '--sdist',
                '--directory',
                pytestconfig.rootpath,
                '--out-dir',
                charm_dir,
            ],
            text=True,
            check=True,
            capture_output=True,
        )

        subprocess.run(
            [  # noqa: S607
                'uv',
                'build',
                '--sdist',
                '--directory',
                pytestconfig.rootpath / 'tracing',
                '--out-dir',
                charm_dir,
            ],
            text=True,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logging.error('%s stderr:\n%s', e.cmd, e.stderr)
        raise

    requirements_file.write_text(
        ''.join(f'./{path.name}\n' for path in charm_dir.glob('ops*.tar.gz'))
    )

    yield charm_dir

    cleanup()


@pytest.fixture(scope='session')
def build_charm(charm_dir: pathlib.Path) -> Generator[Callable[[], str]]:
    """Build the test charm and provide the artefact path.

    Starts building the test-tracing charm early.
    Call the fixture value to get the built charm file path.
    """
    proc = subprocess.Popen(
        ['charmcraft', 'pack', '--verbose'],  # noqa: S607
        cwd=str(charm_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def wait_for_build_to_complete():
        proc.communicate()
        assert proc.returncode == 0
        charm = charm_dir / 'test-tracing_amd64.charm'
        assert charm.exists()
        return str(charm)

    yield wait_for_build_to_complete

    if proc.returncode is None:
        proc.kill()

    stdout, stderr = proc.communicate()
    logging.info('`charmcraft pack` stdout follows:\n%s', stdout)
    logging.info('`charmcraft pack` stderr follows:\n%s', stderr)


def deploy_tempo(juju: jubilant.Juju):
    juju.deploy(
        'tempo-coordinator-k8s',
        app='tempo',
        channel='edge',
        trust=True,
        resources={
            'nginx-image': 'ubuntu/nginx:1.24-24.04_beta',
            'nginx-prometheus-exporter-image': 'nginx/nginx-prometheus-exporter:1.1.0',
        },
    )


def deploy_tempo_worker(juju: jubilant.Juju):
    juju.deploy(
        'tempo-worker-k8s',
        app='tempo-worker',
        channel='edge',
        config={'role-all': True},
        trust=True,
        resources={'tempo-image': 'docker.io/ubuntu/tempo:2-22.04'},
    )


@pytest.fixture
def setup_tracing():
    """Stub out the top-level fixture."""
    pass
