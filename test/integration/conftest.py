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
# Learn more about testing at: https://juju.is/docs/sdk/testing
from __future__ import annotations

import functools
import logging
import subprocess
from typing import Callable, Generator

import jubilant
import minio
import pytest


@pytest.fixture
def juju() -> Generator[jubilant.Juju, None, None]:
    with jubilant.temp_model() as j:
        deploy_tempo(j)
        deploy_tempo_worker(j)
        j.deploy('minio', config={'access-key': 'accesskey', 'secret-key': 'mysoverysecretkey'})
        j.deploy('s3-integrator')

        j.integrate('tempo:s3', 's3-integrator')
        j.integrate('tempo:tempo-cluster', 'tempo-worker')

        j.wait(lambda s: minio_active(s) and s3_integrator_blocked(s))

        address = j.status().apps['minio'].address
        mc_client = minio.Minio(
            f'{address}:9000',
            access_key='accesskey',
            secret_key='mysoverysecretkey',
            secure=False,
        )

        found = mc_client.bucket_exists('tempo')
        if not found:
            mc_client.make_bucket('tempo')

        j.config('s3-integrator', dict(endpoint=f'http://{address}:9000', bucket='tempo'))
        j.run(
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
        # This process may take a while. I'm unsure about the default timeout.

        j.wait(jubilant.all_active)

        yield j

        print(j.debug_log())


@pytest.fixture(scope='session')
def build_tracing_test_charm(
    pytestconfig: pytest.Config,
) -> Generator[Callable[[], str], None, None]:
    charm_dir = pytestconfig.rootpath / 'test/charms/test_integration'
    proc = subprocess.Popen(
        ['charmcraft', 'pack'],  # noqa: S607
        cwd=str(charm_dir),
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    def tracing_test_charm():
        proc.communicate()
        assert proc.returncode == 0
        charm = charm_dir / 'tracing-tester_amd64.charm'
        assert charm.exists()
        return str(charm)

    yield tracing_test_charm
    if proc.returncode is None:
        proc.kill()
    out, err = proc.communicate()
    logging.info('charmcraft pack stdout:\n%s', out)
    logging.error('charmcraft pack stderr:\n%s', err)


def app_is(s: jubilant.Status, app: str, status: str):
    return next(iter(s.apps[app].units.values())).workload_status.current == status


minio_active = functools.partial(app_is, app='minio', status='active')
s3_integrator_blocked = functools.partial(app_is, app='s3-integrator', status='blocked')


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
