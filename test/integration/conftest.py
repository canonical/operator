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


from __future__ import annotations

import logging
import pathlib
import subprocess
from collections.abc import Callable, Generator

import jubilant
import minio
import pytest


@pytest.fixture(scope='module')
def juju() -> Generator[jubilant.Juju]:
    """Make a Juju model for testing."""
    with jubilant.temp_model() as juju:
        juju.wait_timeout = 900
        yield juju
        print(juju.debug_log())


@pytest.fixture
def tracing_juju(juju: jubilant.Juju) -> Generator[jubilant.Juju]:
    """Make a Juju model with the tracing part of COS ready."""
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


@pytest.fixture(scope='session')
def tracing_charm_dir(pytestconfig: pytest.Config) -> Generator[pathlib.Path]:
    """Prepare and return the test_tracing charm directory.

    Builds and injects `ops` and `ops-tracing` from the local checkout into the
    charm's dependencies. Cleans up afterwards.
    """
    charm_dir = pytestconfig.rootpath / 'test/charms/test_tracing'
    yield from _prepare_generic_charm_dir(root_path=pytestconfig.rootpath, charm_dir=charm_dir)


@pytest.fixture(scope='session')
def relation_charm_dir(pytestconfig: pytest.Config) -> Generator[pathlib.Path]:
    """Prepare and return the test_relation charm directory.

    Builds and injects `ops` from the local checkout into the charm's
    dependencies. Cleans up afterwards.
    """
    charm_dir = pytestconfig.rootpath / 'test/charms/test_relation'
    yield from _prepare_generic_charm_dir(
        root_path=pytestconfig.rootpath, charm_dir=charm_dir, build_tracing=False
    )


@pytest.fixture(scope='session')
def secrets_charm_dir(pytestconfig: pytest.Config) -> Generator[pathlib.Path]:
    """Prepare and return the test_secrets charm directory.

    Builds and injects `ops` from the local checkout into the charm's
    dependencies. Cleans up afterwards.
    """
    charm_dir = pytestconfig.rootpath / 'test/charms/test_secrets'
    yield from _prepare_generic_charm_dir(
        root_path=pytestconfig.rootpath, charm_dir=charm_dir, build_tracing=False
    )


def _prepare_generic_charm_dir(
    root_path: pathlib.Path, *, charm_dir: pathlib.Path, build_tracing: bool = True
):
    def cleanup():
        """Ensure pristine test charm directory."""
        for path in charm_dir.glob('ops*.tar.gz'):
            path.unlink()
        for path in charm_dir.glob('*.charm'):
            path.unlink()

    cleanup()

    try:
        subprocess.run(
            [  # noqa: S607
                'uv',
                'build',
                '--sdist',
                '--directory',
                root_path,
                '--out-dir',
                charm_dir,
            ],
            text=True,
            check=True,
            capture_output=True,
        )
        (sdist,) = charm_dir.glob('ops*.tar.gz')
        sdist.rename(charm_dir / 'ops.tar.gz')

        if build_tracing:
            subprocess.run(
                [  # noqa: S607
                    'uv',
                    'build',
                    '--sdist',
                    '--directory',
                    root_path / 'tracing',
                    '--out-dir',
                    charm_dir,
                ],
                text=True,
                check=True,
                capture_output=True,
            )
            (sdist,) = charm_dir.glob('ops_tracing*.tar.gz')
            sdist.rename(charm_dir / 'ops_tracing.tar.gz')

        subprocess.run(
            ['uv', 'lock'],  # noqa: S607
            cwd=charm_dir,
            text=True,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        logging.error('%s stderr:\n%s', e.cmd, e.stderr)
        raise

    yield charm_dir

    cleanup()


@pytest.fixture(scope='session')
def build_tracing_charm(tracing_charm_dir: pathlib.Path) -> Generator[Callable[[], str]]:
    """Build the test_tracing charm and provide the artefact path.

    Starts building the test-tracing charm early.
    Call the fixture value to get the built charm file path.
    """
    yield from _build_charm(tracing_charm_dir, 'test-tracing_amd64.charm')


@pytest.fixture(scope='session')
def build_relation_charm(relation_charm_dir: pathlib.Path) -> Generator[Callable[[], str]]:
    """Build the test_relation charm and provide the artefact path.

    Starts building the test-relation charm early.
    Call the fixture value to get the built charm file path.
    """
    yield from _build_charm(relation_charm_dir, 'test-relation_amd64.charm')


@pytest.fixture(scope='session')
def build_secrets_charm(secrets_charm_dir: pathlib.Path) -> Generator[Callable[[], str]]:
    """Build the test_secrets charm and provide the artefact path.

    Starts building the test-relation charm early.
    Call the fixture value to get the built charm file path.
    """
    yield from _build_charm(secrets_charm_dir, 'test-secrets_amd64.charm')


def _build_charm(charm_dir: pathlib.Path, expected_artifact: str) -> Generator[Callable[[], str]]:
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
        charm = charm_dir / expected_artifact
        assert charm.exists()
        return str(charm)

    yield wait_for_build_to_complete

    if proc.returncode is None:
        proc.kill()

    stdout, stderr = proc.communicate()
    logging.info('`charmcraft pack` stdout follows:\n%s', stdout)
    logging.info('`charmcraft pack` stderr follows:\n%s', stderr)


def deploy_tempo(tracing_juju: jubilant.Juju):
    tracing_juju.deploy(
        'tempo-coordinator-k8s',
        app='tempo',
        channel='edge',
        trust=True,
        resources={
            'nginx-image': 'ubuntu/nginx:1.24-24.04_beta',
            'nginx-prometheus-exporter-image': 'nginx/nginx-prometheus-exporter:1.1.0',
        },
    )


def deploy_tempo_worker(tracing_juju: jubilant.Juju):
    tracing_juju.deploy(
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
