# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import importlib
import os
import pathlib
import signal
import sys
from collections.abc import Iterator

import pytest
from scenario import ActiveStatus, State
from scenario._isolation import Worker
from scenario._isolation_errors import IsolationError
from scenario.context import CharmEvents
from scenario.errors import MetadataNotFoundError
from scenario.state import _CharmSpec

HERE = pathlib.Path(__file__).parent
CHARMS = HERE / 'charms'
V1 = str(HERE / 'deps' / 'confdep_v1')
V2 = str(HERE / 'deps' / 'confdep_v2')

on = CharmEvents()


@pytest.fixture
def workers() -> Iterator[list[Worker]]:
    """Workers appended to this list are closed at the end of the test."""
    started: list[Worker] = []
    yield started
    for worker in started:
        worker.close()


@pytest.fixture(scope='module')
def report() -> Iterator[Worker]:
    worker = Worker(CHARMS / 'report')
    yield worker
    worker.close()


def _pid(state: State) -> int:
    return int(state.unit_status.message.rsplit('pid=', 1)[1])


def test_two_versions_of_a_dependency_cant_share_a_process():
    sys.path.insert(0, V1)
    try:
        v1 = importlib.import_module('confdep')
    finally:
        sys.path.remove(V1)
    sys.path.insert(0, V2)
    try:
        assert importlib.import_module('confdep') is v1
    finally:
        sys.path.remove(V2)
        sys.modules.pop('confdep')


def test_each_worker_has_its_own_dependencies(workers: list[Worker]):
    alpha = Worker(CHARMS / 'alpha', extra_sys_path=[V1])
    beta = Worker(CHARMS / 'beta', extra_sys_path=[V2])
    workers += [alpha, beta]
    assert alpha.run(on.install(), State()).unit_status == ActiveStatus('confdep=1.0 legacy')
    assert beta.run(on.install(), State()).unit_status == ActiveStatus('confdep=2.0 new')
    assert 'confdep' not in sys.modules


def test_the_current_directory_doesnt_shadow_the_workers_packages(
    workers: list[Worker], tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    shadow = tmp_path / 'ops'
    shadow.mkdir()
    (shadow / '__init__.py').write_text("raise ImportError('imported ops from the cwd')\n")
    monkeypatch.chdir(tmp_path)
    worker = Worker(CHARMS / 'report')
    workers.append(worker)
    assert worker.run(on.install(), State()).unit_status.message.startswith('report/0 ')


def test_the_worker_is_kept_between_events(report: Worker):
    first = report.run(on.install(), State())
    second = report.run(on.config_changed(), first)
    assert _pid(first) == _pid(second) != os.getpid()


def test_the_state_reaches_the_charm_and_comes_back(report: Worker):
    state_in = State(leader=True, config={'name': 'given'}, unit_status=ActiveStatus('old'))
    state_out = report.run(on.config_changed(), state_in)
    assert state_out.unit_status.message.startswith(
        'report/0 leader=True trusted=False juju=3.6.14 name=given '
    )
    assert state_out.leader
    assert state_out.config == {'name': 'given'}


def test_one_worker_runs_any_unit(report: Worker):
    zero = report.run(on.install(), State())
    three = report.run(on.install(), State(), unit_id=3)
    assert zero.unit_status.message.startswith('report/0 ')
    assert three.unit_status.message.startswith('report/3 ')
    assert _pid(zero) == _pid(three)


def test_the_worker_gets_the_application_settings(workers: list[Worker]):
    worker = Worker(CHARMS / 'report', app_name='other', juju_version='3.4.2', app_trusted=True)
    workers.append(worker)
    state_out = worker.run(on.install(), State())
    assert state_out.unit_status.message.startswith(
        'other/0 leader=False trusted=True juju=3.4.2 name=default '
    )


def test_a_charm_that_raises_leaves_the_worker_running(workers: list[Worker]):
    worker = Worker(CHARMS / 'alpha')  # Without confdep.
    workers.append(worker)
    for _ in range(2):
        with pytest.raises(IsolationError, match="No module named 'confdep'") as caught:
            worker.run(on.install(), State())
        assert 'crashed' not in str(caught.value)


def test_a_charm_that_calls_sys_exit_leaves_the_worker_running(workers: list[Worker]):
    worker = Worker(CHARMS / 'hardexit')
    workers.append(worker)
    with pytest.raises(IsolationError, match='SystemExit: 3') as caught:
        worker.run(on.stop(), State())
    assert 'crashed' not in str(caught.value)
    assert worker.run(on.install(), State()).unit_status == ActiveStatus('installed')


def test_a_crash_is_reported_and_the_worker_not_restarted(workers: list[Worker]):
    worker = Worker(CHARMS / 'hardexit')
    workers.append(worker)
    with pytest.raises(IsolationError, match='crashed without responding') as caught:
        worker.run(on.start(), State())
    assert 'Return code: 70' in str(caught.value)
    # install works in a fresh worker, so this fails only because it isn't restarted.
    with pytest.raises(IsolationError, match="isn't restarted after it crashes"):
        worker.run(on.install(), State())
    fresh = Worker(CHARMS / 'hardexit')
    workers.append(fresh)
    assert fresh.run(on.install(), State()).unit_status == ActiveStatus('installed')


def test_a_worker_that_died_between_events_is_reported(workers: list[Worker]):
    worker = Worker(CHARMS / 'report')
    workers.append(worker)
    pid = _pid(worker.run(on.install(), State()))
    os.kill(pid, signal.SIGKILL)
    with pytest.raises(IsolationError, match='crashed without responding') as caught:
        worker.run(on.install(), State())
    assert 'Return code: -9' in str(caught.value)
    with pytest.raises(IsolationError, match="isn't restarted after it crashes"):
        worker.run(on.install(), State())


def test_a_worker_that_exits_before_its_setup_is_reported(workers: list[Worker]):
    # `true` exits without reading its input, and a setup message larger than
    # the pipe buffer makes sure the write fails rather than racing the exit.
    worker = Worker(CHARMS / 'report', python='true', extra_sys_path=['x' * 100_000])
    workers.append(worker)
    with pytest.raises(IsolationError, match='crashed without responding'):
        worker.run(on.install(), State())
    with pytest.raises(IsolationError, match="isn't restarted after it crashes"):
        worker.run(on.install(), State())


@pytest.mark.parametrize('timeout', [None, 60])
def test_a_malformed_response_is_reported(
    tmp_path: pathlib.Path, workers: list[Worker], timeout: float | None
):
    # Stands in for the Python interpreter: it ignores its arguments, sends a
    # frame that isn't JSON, and keeps reading so that writes to it succeed.
    fake_python = tmp_path / 'python'
    fake_python.write_text("#!/bin/sh\nprintf '\\000\\000\\000\\002{x'\ncat >/dev/null\n")
    fake_python.chmod(0o755)
    worker = Worker(CHARMS / 'report', python=str(fake_python), timeout=timeout)
    workers.append(worker)
    with pytest.raises(IsolationError, match='crashed without responding'):
        worker.run(on.install(), State())


@pytest.mark.parametrize(
    ('source', 'found'),
    [
        ('import ops\n', r'found \[\]'),
        (
            'import ops\nclass One(ops.CharmBase): pass\nclass Two(ops.CharmBase): pass\n',
            r"found \['One', 'Two'\]",
        ),
    ],
)
def test_a_charm_module_needs_exactly_one_charm_class(
    tmp_path: pathlib.Path, workers: list[Worker], source: str, found: str
):
    (tmp_path / 'metadata.yaml').write_text('name: classes\n')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'charm.py').write_text(source)
    worker = Worker(tmp_path)
    workers.append(worker)
    with pytest.raises(IsolationError, match=f'Expected one CharmBase subclass .*{found}'):
        worker.run(on.install(), State())


def test_an_imported_charm_class_isnt_counted(tmp_path: pathlib.Path, workers: list[Worker]):
    (tmp_path / 'metadata.yaml').write_text('name: subclass\n')
    (tmp_path / 'lib').mkdir()
    (tmp_path / 'lib' / 'shared_base.py').write_text(
        'import ops\nclass SharedBase(ops.CharmBase): pass\n'
    )
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'charm.py').write_text(
        'import ops\n'
        'from shared_base import SharedBase\n'
        'class Subclass(SharedBase):\n'
        '    def __init__(self, framework):\n'
        '        super().__init__(framework)\n'
        '        framework.observe(self.on.install, self._on_install)\n'
        '    def _on_install(self, event):\n'
        '        self.unit.status = ops.ActiveStatus(type(self).__name__)\n'
    )
    worker = Worker(tmp_path)
    workers.append(worker)
    assert worker.run(on.install(), State()).unit_status == ActiveStatus('Subclass')


def test_an_event_that_runs_too_long_kills_the_worker(
    workers: list[Worker], monkeypatch: pytest.MonkeyPatch
):
    # Without this, sys.stdout in the worker is block-buffered.
    monkeypatch.delenv('PYTHONUNBUFFERED', raising=False)
    worker = Worker(CHARMS / 'slow', timeout=0.5)
    workers.append(worker)
    with pytest.raises(IsolationError, match=r'more than 0\.5 seconds') as caught:
        worker.run(on.install(), State())
    assert 'about to hang' in str(caught.value)
    with pytest.raises(IsolationError, match="isn't restarted after it crashes"):
        worker.run(on.install(), State())


def test_charm_output_doesnt_reach_the_protocol(workers: list[Worker]):
    worker = Worker(CHARMS / 'noisy')
    workers.append(worker)
    for _ in range(2):
        assert worker.run(on.install(), State()).unit_status == ActiveStatus('survived')


def test_output_without_newlines_is_kept_within_a_limit(workers: list[Worker]):
    worker = Worker(CHARMS / 'noisy')
    workers.append(worker)
    with pytest.raises(IsolationError, match='crashed without responding') as caught:
        worker.run(on.start(), State())
    message = str(caught.value)
    assert message.endswith('end of output')
    assert len(message) < 1024 * 1024


def test_close_stops_the_worker_and_a_later_event_starts_another():
    worker = Worker(CHARMS / 'report')
    try:
        pid = _pid(worker.run(on.install(), State()))
        worker.close()
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        worker.close()
        assert _pid(worker.run(on.install(), State())) != pid
    finally:
        worker.close()


def test_metadata_is_read_from_a_unified_charmcraft_yaml():
    meta, config, actions = _CharmSpec._load_metadata_or_legacy(CHARMS / 'report')
    assert meta['name'] == 'report'
    assert 'config' not in meta
    assert config == {'options': {'name': {'type': 'string', 'default': 'default'}}}
    assert actions is None


def test_metadata_is_read_from_metadata_yaml():
    meta, config, actions = _CharmSpec._load_metadata_or_legacy(CHARMS / 'alpha')
    assert meta['name'] == 'alpha'
    assert config is None
    assert actions is None


def test_a_charm_without_metadata_is_rejected(tmp_path: pathlib.Path):
    with pytest.raises(MetadataNotFoundError, match='invalid charm root'):
        Worker(tmp_path)
