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

import contextlib
import logging
import pathlib
import socket
import subprocess
import time
from collections.abc import Callable, Generator, Iterator

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


def _kubectl_cluster_ip(namespace: str, service: str) -> str:
    """Return the ClusterIP of `service` in `namespace` via kubectl.

    Juju 4 no longer exposes the Service ClusterIP on apps[X].address for caas
    models; only units have an address, and that's the Pod IP. We still need
    the ClusterIP to configure in-cluster consumers (such as the
    s3-integrator endpoint that Tempo pods resolve from inside the cluster).
    """
    out = subprocess.check_output(
        [  # noqa: S607
            'kubectl',
            '--namespace',
            namespace,
            'get',
            'svc',
            service,
            '-o',
            'jsonpath={.spec.clusterIP}',
        ],
        text=True,
    )
    return out.strip()


@contextlib.contextmanager
def kubectl_port_forward(namespace: str, target: str, port: int) -> Iterator[tuple[str, int]]:
    """Forward `target:port` to a free local port via kubectl port-forward.

    Yields (host, port) pointing at 127.0.0.1:<local>. Used by host-side test
    code to reach in-cluster services without depending on the runner being
    able to route to the ClusterIP or pod CIDR. On GitHub Actions, direct
    connections to ClusterIPs return EPERM ("Operation not permitted"), and
    Juju 4 stopped exposing the ClusterIP on app status, so port-forward is
    the portable way for the host to reach a Service.

    `target` is the kubectl resource (such as 'svc/minio' or 'pod/tempo-0').
    """
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        local_port = sock.getsockname()[1]
    proc = subprocess.Popen(
        [  # noqa: S607
            'kubectl',
            '--namespace',
            namespace,
            'port-forward',
            target,
            f'{local_port}:{port}',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with socket.create_connection(('127.0.0.1', local_port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError(f'port-forward to {target}:{port} did not become reachable')
        yield '127.0.0.1', local_port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _xfail_on_caas_juju4(juju: jubilant.Juju, reason: str = '') -> None:
    """xfail the current test on Kubernetes substrates with Juju 4.x.

    Juju 4 on k8s ships a broken `juju-secret-consumer-<id>` Role: it grants
    `get,list` on `namespaces` but nothing on `secrets`. Any charm that
    patches a secret it owns (such as self-signed-certificates, tempo-coordinator
    with TLS, or the test-secrets charm under test) hits a 403 on the second
    secret-set and goes into hook-error. Tests that exercise that path can't
    run until the upstream fix lands.
    """
    status = juju.status()
    if status.model.type == 'caas' and status.model.version.startswith('4.'):
        pytest.xfail(reason or 'Juju 4 k8s juju-secret-consumer Role lacks secrets rules')


@pytest.fixture
def tracing_juju(juju: jubilant.Juju) -> Generator[jubilant.Juju]:
    """Make a Juju model with the tracing part of COS ready."""
    deploy_tempo(juju)
    deploy_tempo_worker(juju)
    # On Juju 4, the default minio channel resolves to a podspec charm that
    # crashes on install (pod-spec-set was removed in Juju 4); latest/edge is
    # the only sidecar variant. On Juju 3 the latest/edge charm doesn't reach
    # active either, but the unpinned default does.
    minio_deploy: dict[str, object] = {
        'config': {'access-key': 'accesskey', 'secret-key': 'mysoverysecretkey'},
    }
    if juju.status().model.version.startswith('4.'):
        minio_deploy['channel'] = 'latest/edge'
        minio_deploy['trust'] = True
    juju.deploy('minio', **minio_deploy)  # type: ignore[arg-type]
    juju.deploy('s3-integrator')

    juju.integrate('tempo:s3', 's3-integrator')
    juju.integrate('tempo:tempo-cluster', 'tempo-worker')

    juju.wait(
        lambda status: (
            jubilant.all_active(status, 'minio') and jubilant.all_blocked(status, 's3-integrator')
        )
    )

    # Juju 4 stopped exposing the Service ClusterIP on apps[X].address for
    # caas; resolve it from k8s directly. The ClusterIP is what in-cluster
    # consumers (the Tempo pods, via s3-integrator) need.
    cluster_ip = _kubectl_cluster_ip(juju.model, 'minio')

    # The host can't necessarily reach the ClusterIP (on GitHub Actions a
    # direct connect returns EPERM), so create the bucket via a port-forward.
    with kubectl_port_forward(juju.model, 'svc/minio', 9000) as (host, port):
        mc_client = minio.Minio(
            f'{host}:{port}',
            access_key='accesskey',
            secret_key='mysoverysecretkey',
            secure=False,
        )
        if not mc_client.bucket_exists('tempo'):
            mc_client.make_bucket('tempo')

    juju.config('s3-integrator', dict(endpoint=f'http://{cluster_ip}:9000', bucket='tempo'))
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


@pytest.fixture(scope='session')
def hookcmds_charm_dir(pytestconfig: pytest.Config) -> Generator[pathlib.Path]:
    """Prepare and return the test_hookcmds charm directory.

    Builds and injects `ops` from the local checkout into the charm's
    dependencies. Cleans up afterwards.
    """
    charm_dir = pytestconfig.rootpath / 'test/charms/test_hookcmds'
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

        # uv lock does not refresh the recorded hash for `path = ` sources
        # when the package version is unchanged, so the committed uv.lock
        # keeps its stale hash and charmcraft pack later fails with a hash
        # mismatch inside the build container. --refresh-package forces a
        # recompute.
        refresh_packages = ['--refresh-package', 'ops']
        if build_tracing:
            refresh_packages += ['--refresh-package', 'ops-tracing']
        subprocess.run(
            ['uv', 'lock', *refresh_packages],  # noqa: S607
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


@pytest.fixture(scope='session')
def build_hookcmds_charm(hookcmds_charm_dir: pathlib.Path) -> Generator[Callable[[], str]]:
    """Build the test_hookcmds charm and provide the artefact path.

    Starts building the test-hookcmds charm early.
    Call the fixture value to get the built charm file path.
    """
    yield from _build_charm(hookcmds_charm_dir, 'test-hookcmds_amd64.charm')


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
        channel='2/stable',
        trust=True,
    )


def deploy_tempo_worker(tracing_juju: jubilant.Juju):
    tracing_juju.deploy(
        'tempo-worker-k8s',
        app='tempo-worker',
        channel='2/stable',
        config={'role-all': True},
        trust=True,
    )


@pytest.fixture
def setup_tracing():
    """Stub out the top-level fixture."""
    pass
