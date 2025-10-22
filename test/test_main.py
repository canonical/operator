# Copyright 2019 Canonical Ltd.
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

import abc
import dataclasses
import datetime
import importlib.util
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import typing
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import ops
from ops._main import _should_use_controller_storage
from ops.jujucontext import JujuContext
from ops.storage import SQLiteStorage

from .charms.test_main.src.charm import MyCharmEvents
from .test_helpers import FakeScript

# This relies on the expected repository structure to find a path to
# source of the charm under test.
TEST_CHARM_DIR = Path(f'{__file__}/../charms/test_main').resolve()

VERSION_LOGLINE = [
    'juju-log',
    '--log-level',
    'DEBUG',
    '--',
    f'ops {ops.__version__} up and running.',
]

logger = logging.getLogger(__name__)


class SymlinkTargetError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class EventSpec:
    event_type: type[ops.EventBase]
    event_name: str
    env_var: str | None = None
    relation_id: int | None = None
    remote_app: str | None = None
    remote_unit: str | None = None
    model_name: str | None = None
    model_uuid: str | None = None
    set_in_env: dict[str, str] | None = None
    workload_name: str | None = None
    notice_id: str | None = None
    notice_type: str | None = None
    notice_key: str | None = None
    departing_unit_name: str | None = None
    secret_id: str | None = None
    secret_label: str | None = None
    secret_revision: str | None = None
    check_name: str | None = None


@patch('ops._main.setup_root_logging', new=lambda *a, **kw: None)  # type: ignore
@patch('ops._main._Manager._emit_charm_event', new=lambda *a, **kw: None)  # type: ignore
@patch('ops.charm._evaluate_status', new=lambda *a, **kw: None)  # type: ignore
class TestCharmInit:
    @patch('sys.stderr', new_callable=io.StringIO)
    def test_breakpoint(self, fake_stderr: io.StringIO):
        class MyCharm(ops.CharmBase):
            pass

        self._check(MyCharm, extra_environ={'JUJU_DEBUG_AT': 'all'})

        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()

        assert mock.call_count == 1
        assert 'Starting pdb to debug charm operator' in fake_stderr.getvalue()

    def test_no_debug_breakpoint(self):
        class MyCharm(ops.CharmBase):
            pass

        self._check(MyCharm, extra_environ={'JUJU_DEBUG_AT': ''})

        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()

        assert mock.call_count == 0

    def _check(
        self,
        charm_class: type[ops.CharmBase],
        *,
        extra_environ: dict[str, str] | None = None,
        **kwargs: typing.Any,
    ):
        """Helper for below tests."""
        fake_environ = {
            'JUJU_UNIT_NAME': 'test_main/0',
            'JUJU_MODEL_NAME': 'mymodel',
            'JUJU_VERSION': '2.8.0',
        }
        if extra_environ is not None:
            fake_environ.update(extra_environ)

        with tempfile.TemporaryDirectory() as tmpdirname:
            fake_environ.update({'JUJU_CHARM_DIR': tmpdirname})
            with patch.dict(os.environ, fake_environ):
                tmpdirname = Path(tmpdirname)
                fake_metadata = tmpdirname / 'metadata.yaml'
                with fake_metadata.open('wb') as fh:
                    fh.write(b'name: test')

                ops.main(charm_class, **kwargs)

    def test_init_signature_passthrough(self):
        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)

        with warnings.catch_warnings(record=True) as warn_cm:
            self._check(MyCharm)
        assert warn_cm == []

    def test_init_signature_old_key_argument(self):
        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework, somekey: typing.Any):
                super().__init__(framework, somekey)  # type: ignore

        # Support for "key" has been deprecated since ops 0.7 and was removed in 2.0
        with pytest.raises(TypeError):
            self._check(MyCharm)

    def test_init_signature_only_framework(self):
        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)

        with warnings.catch_warnings(record=True) as warn_cm:
            self._check(MyCharm)
        assert warn_cm == []

    def test_storage_no_storage(self):
        # here we patch juju_backend_available so it refuses to set it up
        with patch('ops.storage.juju_backend_available') as juju_backend_available:
            juju_backend_available.return_value = False
            with pytest.raises(
                RuntimeError,
                match=r'charm set use_juju_for_storage=True, but Juju .* does not support it',
            ):
                self._check(ops.CharmBase, use_juju_for_storage=True)

    def test_storage_with_storage(self):
        # here we patch juju_backend_available, so it gets set up and falls over when used
        with patch('ops.storage.juju_backend_available') as juju_backend_available:
            juju_backend_available.return_value = True
            with pytest.warns(DeprecationWarning, match='Controller storage'):
                with pytest.raises(FileNotFoundError, match='state-get'):
                    self._check(ops.CharmBase, use_juju_for_storage=True)


@patch('sys.argv', new=('hooks/config-changed',))
@patch('ops._main._Manager._setup_root_logging', new=lambda *a, **kw: None)  # type: ignore
@patch('ops.charm._evaluate_status', new=lambda *a, **kw: None)  # type: ignore
class TestDispatch:
    def _check(self, *, dispatch_path: str = ''):
        """Helper for below tests."""

        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)

        fake_environ = {
            'JUJU_UNIT_NAME': 'test_main/0',
            'JUJU_MODEL_NAME': 'mymodel',
            'JUJU_DISPATCH_PATH': dispatch_path,
            'JUJU_VERSION': '2.8.0',
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_environ.update({'JUJU_CHARM_DIR': tmpdir})
            tmpdir = Path(tmpdir)
            fake_metadata = tmpdir / 'metadata.yaml'
            with fake_metadata.open('wb') as fh:
                fh.write(b'name: test')
            dispatch = tmpdir / 'dispatch'
            dispatch.write_text('', encoding='utf8')
            dispatch.chmod(0o755)

            with patch.dict(os.environ, fake_environ):
                with patch('ops._main._Manager._emit_charm_event') as mock_charm_event:
                    ops.main(MyCharm)

        assert mock_charm_event.call_count == 1
        return mock_charm_event.call_args[0][0]

    def test_with_dispatch(self):
        """With dispatch, dispatch is used."""
        event = self._check(dispatch_path='hooks/potatos')
        assert event == 'potatos'


_event_test = list[tuple[EventSpec, dict[str, str | int | None]]]


@pytest.fixture
def fake_script(request: pytest.FixtureRequest):
    return FakeScript(request)


class _TestMain(abc.ABC):
    @abc.abstractmethod
    def _setup_entry_point(self):
        """Set up the given entry point in the given directory.

        With dispatch, that would be a symlink pointing at src/charm.py
        or a script that executes src/charm.py.
        """
        return NotImplemented

    @abc.abstractmethod
    def _call_event(
        self,
        fake_script: FakeScript,
        rel_path: Path,
        env: dict[str, str],
    ):
        """Set up the environment and call (i.e. run) the given event."""
        return NotImplemented

    @pytest.fixture
    def setup_charm(self, request: pytest.FixtureRequest, fake_script: FakeScript):
        self._setup_charm_dir(request)

        # Relations events are defined dynamically and modify the class attributes.
        # We use a subclass temporarily to prevent these side effects from leaking.
        class TestCharmEvents(ops.CharmEvents):
            pass

        ops.CharmBase.on = TestCharmEvents()  # type: ignore

        def cleanup():
            ops.CharmBase.on = ops.CharmEvents()  # type: ignore

        request.addfinalizer(cleanup)

        fake_script.write('is-leader', 'echo true')
        fake_script.write('juju-log', 'exit 0')

        # set to something other than None for tests that care
        self.stdout = None
        self.stderr = None

    def _setup_charm_dir(self, request: pytest.FixtureRequest):
        self._tmpdir = Path(tempfile.mkdtemp(prefix='tmp-ops-test-')).resolve()

        def cleanup():
            shutil.rmtree(self._tmpdir, ignore_errors=True)

        request.addfinalizer(cleanup)

        self.JUJU_CHARM_DIR = self._tmpdir / 'test_main'
        self._charm_state_file = self.JUJU_CHARM_DIR / '.unit-state.db'
        self.hooks_dir = self.JUJU_CHARM_DIR / 'hooks'
        charm_path = str(self.JUJU_CHARM_DIR / 'src/charm.py')
        self.charm_exec_path = os.path.relpath(charm_path, str(self.hooks_dir))
        shutil.copytree(str(TEST_CHARM_DIR), str(self.JUJU_CHARM_DIR))

        charm_spec = importlib.util.spec_from_file_location('charm', charm_path)
        assert charm_spec is not None
        self.charm_module = importlib.util.module_from_spec(charm_spec)
        assert charm_spec.loader is not None
        charm_spec.loader.exec_module(self.charm_module)

        self.hooks_dir.mkdir()  # For testing cases when a charm has a legacy hook.
        self._setup_entry_point()

    def _read_and_clear_state(
        self, event_name: str, env: dict[str, str]
    ) -> ops.BoundStoredState | ops.StoredStateData:
        if self._charm_state_file.stat().st_size:
            storage = SQLiteStorage(self._charm_state_file)
            with (self.JUJU_CHARM_DIR / 'metadata.yaml').open() as m:
                af = self.JUJU_CHARM_DIR / 'actions.yaml'
                if af.exists():
                    with af.open() as a:
                        meta = ops.CharmMeta.from_yaml(m, a)
                else:
                    meta = ops.CharmMeta.from_yaml(m)
            framework = ops.Framework(
                storage,
                self.JUJU_CHARM_DIR,
                meta,
                None,  # type: ignore
                event_name,
                juju_debug_at=JujuContext._from_dict(env).debug_at,
            )

            class ThisCharmEvents(MyCharmEvents):
                pass

            class Charm(self.charm_module.Charm):
                on = ThisCharmEvents()

            mycharm = Charm(framework)
            stored = mycharm._stored
            # Override the saved data with a cleared state
            storage.save_snapshot(stored._data.handle.path, {})
            storage.commit()
            framework.close()
        else:
            stored = ops.StoredStateData(None, None)  # type: ignore
        return stored

    def _simulate_event(self, fake_script: FakeScript, event_spec: EventSpec):
        ppath = Path(__file__).parent
        pypath = str(ppath.parent)
        if 'PYTHONPATH' in os.environ:
            pypath += os.pathsep + os.environ['PYTHONPATH']
        env = os.environ.copy()
        env.update({
            'PATH': os.pathsep.join([str(ppath / 'bin'), env['PATH']]),
            'PYTHONPATH': pypath,
            'JUJU_CHARM_DIR': str(self.JUJU_CHARM_DIR),
            'JUJU_UNIT_NAME': 'test_main/0',
        })
        if event_spec.set_in_env is not None:
            env.update(event_spec.set_in_env)
        if issubclass(event_spec.event_type, ops.SecretEvent):
            assert event_spec.secret_id is not None
            env.update({
                'JUJU_SECRET_ID': event_spec.secret_id,
                'JUJU_SECRET_LABEL': event_spec.secret_label or '',
            })
        if issubclass(event_spec.event_type, (ops.SecretRemoveEvent, ops.SecretExpiredEvent)):
            env.update({
                'JUJU_SECRET_REVISION': str(event_spec.secret_revision or ''),
            })
        if issubclass(event_spec.event_type, ops.RelationEvent):
            rel_name = event_spec.event_name.split('_')[0]
            env.update({
                'JUJU_RELATION': rel_name,
                'JUJU_RELATION_ID': str(event_spec.relation_id),
            })
            remote_app = event_spec.remote_app
            # For juju < 2.7 app name is extracted from JUJU_REMOTE_UNIT.
            if remote_app is not None:
                env['JUJU_REMOTE_APP'] = remote_app

            remote_unit = event_spec.remote_unit
            if remote_unit is None:
                remote_unit = ''
            env['JUJU_REMOTE_UNIT'] = remote_unit

            departing_unit_name = event_spec.departing_unit_name
            if departing_unit_name is None:
                departing_unit_name = ''
            env['JUJU_DEPARTING_UNIT'] = departing_unit_name
        else:
            env.update({
                'JUJU_REMOTE_UNIT': '',
                'JUJU_REMOTE_APP': '',
            })
        if issubclass(event_spec.event_type, ops.WorkloadEvent):
            assert event_spec.workload_name is not None
            env.update({
                'JUJU_WORKLOAD_NAME': event_spec.workload_name,
            })
        if issubclass(event_spec.event_type, ops.PebbleNoticeEvent):
            assert event_spec.notice_id is not None
            assert event_spec.notice_type is not None
            assert event_spec.notice_key is not None
            env.update({
                'JUJU_NOTICE_ID': event_spec.notice_id,
                'JUJU_NOTICE_TYPE': event_spec.notice_type,
                'JUJU_NOTICE_KEY': event_spec.notice_key,
            })
        if issubclass(event_spec.event_type, ops.charm.PebbleCheckEvent):
            assert event_spec.check_name is not None
            env['JUJU_PEBBLE_CHECK_NAME'] = event_spec.check_name
        if issubclass(event_spec.event_type, ops.ActionEvent):
            event_filename = event_spec.event_name[: -len('_action')].replace('_', '-')
            assert event_spec.env_var is not None
            env.update({
                event_spec.env_var: event_filename,
            })
            if event_spec.env_var == 'JUJU_ACTION_NAME':
                event_dir = 'actions'
            else:
                raise RuntimeError('invalid envar name specified for an action event')
        else:
            event_filename = event_spec.event_name.replace('_', '-')
            event_dir = 'hooks'
        if event_spec.model_name is not None:
            env['JUJU_MODEL_NAME'] = event_spec.model_name
        if event_spec.model_uuid is not None:
            env['JUJU_MODEL_UUID'] = event_spec.model_uuid

        self._call_event(fake_script, Path(event_dir, event_filename), env)
        return self._read_and_clear_state(event_spec.event_name, env)

    @pytest.mark.usefixtures('setup_charm')
    def test_event_reemitted(self, fake_script: FakeScript):
        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)
        assert list(state.observed_event_types) == ['InstallEvent']

        state = self._simulate_event(
            fake_script, EventSpec(ops.ConfigChangedEvent, 'config-changed')
        )
        assert isinstance(state, ops.BoundStoredState)
        assert list(state.observed_event_types) == ['ConfigChangedEvent']

        # Re-emit should pick the deferred config-changed.
        state = self._simulate_event(
            fake_script, EventSpec(ops.UpdateStatusEvent, 'update-status')
        )
        assert isinstance(state, ops.BoundStoredState)
        assert list(state.observed_event_types) == ['ConfigChangedEvent', 'UpdateStatusEvent']

    @pytest.mark.parametrize(
        'event_class,event_name',
        [
            (ops.CollectMetricsEvent, 'collect-metrics'),
            (ops.HookEvent, 'meter-status-changed'),  # Ops doesn't have an event object for this.
        ],
    )
    @pytest.mark.usefixtures('setup_charm')
    def test_no_reemission_on_restricted_event(
        self, event_class: type[ops.EventBase], event_name: str, fake_script: FakeScript
    ):
        fake_script.write('add-metric', 'exit 0')

        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)
        assert list(state.observed_event_types) == ['InstallEvent']

        state = self._simulate_event(
            fake_script, EventSpec(ops.ConfigChangedEvent, 'config-changed')
        )
        assert isinstance(state, ops.BoundStoredState)
        assert list(state.observed_event_types) == ['ConfigChangedEvent']

        # Re-emit should not pick the deferred config-changed because
        # the event runs in a restricted context.
        state = self._simulate_event(fake_script, EventSpec(event_class, event_name))
        assert isinstance(state, ops.BoundStoredState)
        # Ops doesn't support observing meter-status-changed, so there are no
        # observed event types in that case.
        if event_name == 'meter-status-changed':
            assert not state.observed_event_types
        else:
            assert list(state.observed_event_types) == [event_class.__name__]

    @pytest.mark.parametrize('is_leader', [True, False], ids=['leader', 'not_leader'])
    @pytest.mark.parametrize(
        'event_class,event_name,restricted',
        [
            pytest.param(ops.CollectMetricsEvent, 'collect-metrics', True, id='collect_metrics'),
            pytest.param(ops.HookEvent, 'meter-status-changed', True, id='meter_status_changed'),
            pytest.param(ops.StartEvent, 'start', False, id='start'),
        ],
    )
    @pytest.mark.usefixtures('setup_charm')
    def test_no_collect_status_on_restricted_event(
        self,
        is_leader: bool,
        event_class: type[ops.EventBase],
        event_name: str,
        restricted: bool,
        fake_script: FakeScript,
    ):
        fake_script.write('is-leader', f'echo {str(is_leader).lower()}')
        fake_script.write('add-metric', 'exit 0')

        # First run "install" to make sure all hooks are set up.
        state = self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)
        assert list(state.observed_event_types) == ['InstallEvent']

        state = self._simulate_event(fake_script, EventSpec(event_class, event_name))
        assert isinstance(state, ops.BoundStoredState)
        expected: list[str] = []
        if not restricted:
            if is_leader:
                expected.append('collect_app_status')
            expected.append('collect_unit_status')
        assert list(state.on_collect_status) == expected

    @pytest.mark.usefixtures('setup_charm')
    def test_multiple_events_handled(self, fake_script: FakeScript):
        fake_script.write('action-get', "echo '{}'")

        # Sample events with a different amount of dashes used
        # and with endpoints from different sections of metadata.yaml
        events_under_test: _event_test = [
            (
                EventSpec(ops.InstallEvent, 'install'),
                {},
            ),
            (
                EventSpec(ops.StartEvent, 'start'),
                {},
            ),
            (
                EventSpec(ops.UpdateStatusEvent, 'update_status'),
                {},
            ),
            (
                EventSpec(ops.LeaderSettingsChangedEvent, 'leader_settings_changed'),
                {},
            ),
            (
                EventSpec(
                    ops.RelationJoinedEvent,
                    'db_relation_joined',
                    relation_id=1,
                    remote_app='remote',
                    remote_unit='remote/0',
                ),
                {
                    'relation_name': 'db',
                    'relation_id': 1,
                    'app_name': 'remote',
                    'unit_name': 'remote/0',
                },
            ),
            (
                EventSpec(
                    ops.RelationChangedEvent,
                    'mon_relation_changed',
                    relation_id=2,
                    remote_app='remote',
                    remote_unit='remote/0',
                ),
                {
                    'relation_name': 'mon',
                    'relation_id': 2,
                    'app_name': 'remote',
                    'unit_name': 'remote/0',
                },
            ),
            (
                EventSpec(
                    ops.RelationChangedEvent,
                    'mon_relation_changed',
                    relation_id=2,
                    remote_app='remote',
                    remote_unit=None,
                ),
                {'relation_name': 'mon', 'relation_id': 2, 'app_name': 'remote'},
            ),
            (
                EventSpec(
                    ops.RelationDepartedEvent,
                    'mon_relation_departed',
                    relation_id=2,
                    remote_app='remote',
                    remote_unit='remote/0',
                    departing_unit_name='remote/42',
                ),
                {
                    'relation_name': 'mon',
                    'relation_id': 2,
                    'app_name': 'remote',
                    'unit_name': 'remote/0',
                    'departing_unit': 'remote/42',
                },
            ),
            (
                EventSpec(ops.RelationBrokenEvent, 'ha_relation_broken', relation_id=3),
                {'relation_name': 'ha', 'relation_id': 3},
            ),
            (
                # Events without a remote app specified (for Juju < 2.7).
                EventSpec(
                    ops.RelationJoinedEvent,
                    'db_relation_joined',
                    relation_id=1,
                    remote_unit='remote/0',
                ),
                {
                    'relation_name': 'db',
                    'relation_id': 1,
                    'app_name': 'remote',
                    'unit_name': 'remote/0',
                },
            ),
            (
                EventSpec(
                    ops.RelationChangedEvent,
                    'mon_relation_changed',
                    relation_id=2,
                    remote_unit='remote/0',
                ),
                {
                    'relation_name': 'mon',
                    'relation_id': 2,
                    'app_name': 'remote',
                    'unit_name': 'remote/0',
                },
            ),
            (
                EventSpec(
                    ops.RelationDepartedEvent,
                    'mon_relation_departed',
                    relation_id=2,
                    remote_unit='remote/0',
                    departing_unit_name='remote/42',
                ),
                {
                    'relation_name': 'mon',
                    'relation_id': 2,
                    'app_name': 'remote',
                    'unit_name': 'remote/0',
                    'departing_unit': 'remote/42',
                },
            ),
            (
                EventSpec(
                    ops.ActionEvent,
                    'start_action',
                    env_var='JUJU_ACTION_NAME',
                    set_in_env={'JUJU_ACTION_UUID': '1'},
                ),
                {},
            ),
            (
                EventSpec(
                    ops.ActionEvent,
                    'foo_bar_action',
                    env_var='JUJU_ACTION_NAME',
                    set_in_env={'JUJU_ACTION_UUID': '2'},
                ),
                {},
            ),
            (
                EventSpec(ops.PebbleReadyEvent, 'test_pebble_ready', workload_name='test'),
                {'container_name': 'test'},
            ),
            (
                EventSpec(
                    ops.PebbleCustomNoticeEvent,
                    'test_pebble_custom_notice',
                    workload_name='test',
                    notice_id='123',
                    notice_type='custom',
                    notice_key='example.com/a',
                ),
                {
                    'container_name': 'test',
                    'notice_id': '123',
                    'notice_type': 'custom',
                    'notice_key': 'example.com/a',
                },
            ),
            (
                EventSpec(
                    ops.PebbleCheckFailedEvent,
                    'test_pebble_check_failed',
                    workload_name='test',
                    check_name='http-check',
                ),
                {
                    'container_name': 'test',
                    'check_name': 'http-check',
                },
            ),
            (
                EventSpec(
                    ops.PebbleCheckRecoveredEvent,
                    'test_pebble_check_recovered',
                    workload_name='test',
                    check_name='http-check',
                ),
                {
                    'container_name': 'test',
                    'check_name': 'http-check',
                },
            ),
            (
                EventSpec(
                    ops.SecretChangedEvent,
                    'secret_changed',
                    secret_id='secret:12345',
                    secret_label='foo',
                ),
                {'id': 'secret:12345', 'label': 'foo'},
            ),
            (
                EventSpec(
                    ops.SecretRotateEvent,
                    'secret_rotate',
                    secret_id='secret:12345',
                    secret_label='foo',
                    secret_revision='42',
                ),
                {'id': 'secret:12345', 'label': 'foo'},
            ),
            (
                EventSpec(
                    ops.SecretRemoveEvent,
                    'secret_remove',
                    secret_id='secret:12345',
                    secret_label='foo',
                    secret_revision='42',
                ),
                {'id': 'secret:12345', 'label': 'foo', 'revision': 42},
            ),
            (
                EventSpec(
                    ops.SecretExpiredEvent,
                    'secret_expired',
                    secret_id='secret:12345',
                    secret_label='foo',
                    secret_revision='42',
                ),
                {'id': 'secret:12345', 'label': 'foo', 'revision': 42},
            ),
        ]

        logger.debug('Expected events %s', events_under_test)

        # First run "install" to make sure all hooks are set up.
        self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))

        # Simulate hook executions for every event.
        for event_spec, expected_event_data in events_under_test:
            state = self._simulate_event(fake_script, event_spec)
            assert isinstance(state, ops.BoundStoredState)

            state_key = f'on_{event_spec.event_name}'
            handled_events = getattr(state, state_key, [])

            # Make sure that a handler for that event was called once.
            assert len(handled_events) == 1
            # Make sure the event handled by the Charm has the right type.
            handled_event_type = handled_events[0]
            assert handled_event_type == event_spec.event_type.__name__

            assert list(state.observed_event_types) == [event_spec.event_type.__name__]

            if expected_event_data:
                assert getattr(state, f'{event_spec.event_name}_data') == expected_event_data

    @pytest.mark.usefixtures('setup_charm')
    def test_event_not_implemented(self, fake_script: FakeScript):
        """Make sure events without implementation do not cause non-zero exit."""
        # Simulate a scenario where there is a symlink for an event that
        # a charm does not know how to handle.
        hook_path = self.JUJU_CHARM_DIR / 'hooks/not-implemented-event'
        # This will be cleared up in tearDown.
        hook_path.symlink_to('install')

        try:
            self._simulate_event(fake_script, EventSpec(ops.HookEvent, 'not-implemented-event'))
        except subprocess.CalledProcessError:
            pytest.fail(
                'Event simulation for an unsupported event'
                ' results in a non-zero exit code returned'
            )

    @pytest.mark.usefixtures('setup_charm')
    def test_no_actions(self, fake_script: FakeScript):
        (self.JUJU_CHARM_DIR / 'actions.yaml').unlink()
        self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))

    @pytest.mark.usefixtures('setup_charm')
    def test_empty_actions(self, fake_script: FakeScript):
        (self.JUJU_CHARM_DIR / 'actions.yaml').write_text('')
        self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))

    @pytest.mark.usefixtures('setup_charm')
    def test_collect_metrics(self, fake_script: FakeScript):
        fake_script.write('add-metric', 'exit 0')
        self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))
        # Clear the calls during 'install'
        fake_script.calls(clear=True)
        self._simulate_event(fake_script, EventSpec(ops.CollectMetricsEvent, 'collect_metrics'))

        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'DEBUG', '--', 'Emitting Juju event collect_metrics.'],
            ['add-metric', '--labels', 'bar=4.2', 'foo=42'],
        ]
        calls = fake_script.calls()

        assert calls == expected

    @pytest.mark.usefixtures('setup_charm')
    def test_custom_event(self, fake_script: FakeScript):
        self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))
        # Clear the calls during 'install'
        fake_script.calls(clear=True)
        self._simulate_event(
            fake_script,
            EventSpec(
                ops.UpdateStatusEvent, 'update-status', set_in_env={'EMIT_CUSTOM_EVENT': '1'}
            ),
        )

        calls = fake_script.calls()

        custom_event_prefix = 'Emitting custom event <CustomEvent via Charm/on/custom'
        expected = [
            VERSION_LOGLINE,
            ['juju-log', '--log-level', 'DEBUG', '--', 'Emitting Juju event update_status.'],
            ['juju-log', '--log-level', 'DEBUG', '--', custom_event_prefix],
            ['is-leader', '--format=json'],
        ]
        # Remove the "[key]>" suffix from the end of the event string
        assert re.match(re.escape(custom_event_prefix) + '.*', calls[2][-1])
        calls[2][-1] = custom_event_prefix
        assert calls == expected

    @pytest.mark.usefixtures('setup_charm')
    def test_logger(self, fake_script: FakeScript):
        fake_script.write('action-get', "echo '{}'")

        test_cases = [
            (
                EventSpec(
                    ops.ActionEvent,
                    'log_critical_action',
                    env_var='JUJU_ACTION_NAME',
                    set_in_env={'JUJU_ACTION_UUID': '1'},
                ),
                ['juju-log', '--log-level', 'CRITICAL', '--', 'super critical'],
            ),
            (
                EventSpec(
                    ops.ActionEvent,
                    'log_error_action',
                    env_var='JUJU_ACTION_NAME',
                    set_in_env={'JUJU_ACTION_UUID': '2'},
                ),
                ['juju-log', '--log-level', 'ERROR', '--', 'grave error'],
            ),
            (
                EventSpec(
                    ops.ActionEvent,
                    'log_warning_action',
                    env_var='JUJU_ACTION_NAME',
                    set_in_env={'JUJU_ACTION_UUID': '3'},
                ),
                ['juju-log', '--log-level', 'WARNING', '--', 'wise warning'],
            ),
            (
                EventSpec(
                    ops.ActionEvent,
                    'log_info_action',
                    env_var='JUJU_ACTION_NAME',
                    set_in_env={'JUJU_ACTION_UUID': '4'},
                ),
                ['juju-log', '--log-level', 'INFO', '--', 'useful info'],
            ),
        ]

        # Set up action symlinks.
        self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))

        for event_spec, calls in test_cases:
            self._simulate_event(fake_script, event_spec)
            assert calls in fake_script.calls(clear=True)

        # Test warnings are captured and sent to the Juju debug-log,
        event_spec = EventSpec(
            ops.ActionEvent,
            'warn_action',
            env_var='JUJU_ACTION_NAME',
            set_in_env={'JUJU_ACTION_UUID': '5'},
        )
        self._simulate_event(fake_script, event_spec)
        calls = fake_script.calls(clear=True)

        calls_without_message = [call[:-1] for call in calls]
        expected_without_message = ['juju-log', '--log-level', 'WARNING', '--']
        assert expected_without_message in calls_without_message

        idx = calls_without_message.index(expected_without_message)
        warning_message = calls[idx][-1]
        pattern = (
            r'^.*:(\d+):\s+DeprecationWarning:\s+'
            + re.escape('feature x is deprecated, use feature y instead')
            + '$'
        )
        if not re.match(pattern, warning_message):
            pytest.fail(f'Warning was not sent to debug-log: {calls!r}')

    @patch('os.getuid', return_value=1000)
    @pytest.mark.usefixtures('setup_charm')
    def test_excepthook(self, _: MagicMock, fake_script: FakeScript):
        with pytest.raises(subprocess.CalledProcessError):
            self._simulate_event(
                fake_script,
                EventSpec(
                    ops.InstallEvent,
                    'install',
                    set_in_env={'TRY_EXCEPTHOOK': '1'},
                    model_uuid='1234',
                ),
            )

        calls = [' '.join(i) for i in fake_script.calls()]

        assert calls.pop(0) == ' '.join(VERSION_LOGLINE)
        assert 'Using local storage: not a Kubernetes podspec charm' in calls.pop(0)
        assert 'Initializing SQLite local storage: ' in calls.pop(0)
        assert re.search(
            r'(?ms)juju-log --log-level ERROR -- Uncaught exception while in charm code:\n'
            r'Traceback .most recent call last.:\n'
            r'  .*'
            r"    raise RuntimeError.'failing as requested'.\n"
            r'RuntimeError: failing as requested',
            calls[0],
        )
        sec_crash = calls.pop(1)
        assert len(calls) == 1, f'expected 1 call, but got extra: {calls[1:]}'

        assert sec_crash.startswith('juju-log --log-level TRACE --')
        data_crash = json.loads(sec_crash.rsplit('--', 1)[-1])
        assert data_crash['type'] == 'security'
        assert data_crash['appid'] == '1234-test_main/0'
        crash_timestamp = datetime.datetime.fromisoformat(data_crash['datetime'])
        assert (
            datetime.datetime.now(datetime.timezone.utc) - crash_timestamp
        ).total_seconds() < 60
        assert (
            data_crash['description']
            == "Uncaught exception in charm code: RuntimeError('failing as requested')."
        )
        assert data_crash['event'] == 'sys_crash:RuntimeError'

    @pytest.mark.usefixtures('setup_charm')
    def test_sets_model_name(self, fake_script: FakeScript):
        fake_script.write('action-get', "echo '{}'")
        state = self._simulate_event(
            fake_script,
            EventSpec(
                ops.ActionEvent,
                'get_model_name_action',
                env_var='JUJU_ACTION_NAME',
                model_name='test-model-name',
                set_in_env={'JUJU_ACTION_UUID': '1'},
            ),
        )
        assert isinstance(state, ops.BoundStoredState)
        assert state._on_get_model_name_action == ['test-model-name']

    @pytest.mark.usefixtures('setup_charm')
    def test_has_valid_status(self, fake_script: FakeScript):
        fake_script.write('action-get', "echo '{}'")
        fake_script.write(
            'status-get', """echo '{"status": "unknown", "message": "", "status-data": {}}'"""
        )
        state = self._simulate_event(
            fake_script,
            EventSpec(
                ops.ActionEvent,
                'get_status_action',
                env_var='JUJU_ACTION_NAME',
                set_in_env={'JUJU_ACTION_UUID': '1'},
            ),
        )
        assert isinstance(state, ops.BoundStoredState)
        assert state.status_name == 'unknown'
        assert state.status_message == ''
        fake_script.write(
            'status-get',
            """echo '{"status": "blocked", "message": "help meeee", "status-data": {}}'""",
        )
        state = self._simulate_event(
            fake_script,
            EventSpec(
                ops.ActionEvent,
                'get_status_action',
                env_var='JUJU_ACTION_NAME',
                set_in_env={'JUJU_ACTION_UUID': '1'},
            ),
        )
        assert isinstance(state, ops.BoundStoredState)
        assert state.status_name == 'blocked'
        assert state.status_message == 'help meeee'

    @pytest.mark.usefixtures('setup_charm')
    def test_hook_and_dispatch(
        self,
        request: pytest.FixtureRequest,
        fake_script: FakeScript,
    ):
        fake_script_hooks = FakeScript(request, self.hooks_dir)
        fake_script_hooks.write('install', 'exit 0')
        state = self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)

        # the script was called, *and*, the .on. was called
        assert fake_script_hooks.calls() == [['install', '']]
        assert list(state.observed_event_types) == ['InstallEvent']

        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            [
                'juju-log',
                '--log-level',
                'INFO',
                '--',
                f'Running legacy {hook}.',
            ],
            ['juju-log', '--log-level', 'DEBUG', '--', f'Legacy {hook} exited with status 0.'],
            [
                'juju-log',
                '--log-level',
                'DEBUG',
                '--',
                'Using local storage: not a Kubernetes podspec charm',
            ],
            ['juju-log', '--log-level', 'DEBUG', '--', 'Emitting Juju event install.'],
            ['is-leader', '--format=json'],
        ]
        calls = fake_script.calls()
        assert 'Initializing SQLite local storage: ' in ' '.join(calls.pop(-3))
        assert calls == expected

    @pytest.mark.usefixtures('setup_charm')
    def test_non_executable_hook_and_dispatch(self, fake_script: FakeScript):
        (self.hooks_dir / 'install').write_text('')
        state = self._simulate_event(fake_script, EventSpec(ops.InstallEvent, 'install'))
        assert isinstance(state, ops.BoundStoredState)

        assert list(state.observed_event_types) == ['InstallEvent']

        expected = [
            VERSION_LOGLINE,
            [
                'juju-log',
                '--log-level',
                'WARNING',
                '--',
                'Legacy hooks/install exists but is not executable.',
            ],
            [
                'juju-log',
                '--log-level',
                'DEBUG',
                '--',
                'Using local storage: not a Kubernetes podspec charm',
            ],
            ['juju-log', '--log-level', 'DEBUG', '--', 'Emitting Juju event install.'],
            ['is-leader', '--format=json'],
        ]
        calls = fake_script.calls()
        assert 'Initializing SQLite local storage: ' in ' '.join(calls.pop(-3))
        assert calls == expected

    @pytest.mark.usefixtures('setup_charm')
    def test_hook_and_dispatch_with_failing_hook(
        self,
        request: pytest.FixtureRequest,
        fake_script: FakeScript,
    ):
        self.stdout = self.stderr = tempfile.TemporaryFile()  # noqa: SIM115
        request.addfinalizer(self.stdout.close)

        fake_script_hooks = FakeScript(request, self.hooks_dir)
        fake_script_hooks.write('install', 'exit 42')
        event = EventSpec(ops.InstallEvent, 'install')
        with pytest.raises(subprocess.CalledProcessError):
            self._simulate_event(fake_script, event)

        self.stdout.seek(0)
        assert self.stdout.read() == b''
        self.stderr.seek(0)
        assert self.stderr.read() == b''
        calls = fake_script.calls()
        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            [
                'juju-log',
                '--log-level',
                'INFO',
                '--',
                f'Running legacy {hook}.',
            ],
            ['juju-log', '--log-level', 'WARNING', '--', f'Legacy {hook} exited with status 42.'],
        ]
        assert calls == expected

    @pytest.mark.usefixtures('setup_charm')
    def test_hook_and_dispatch_but_hook_is_dispatch(self, fake_script: FakeScript):
        event = EventSpec(ops.InstallEvent, 'install')
        hook_path = self.hooks_dir / 'install'
        for (rel, ind), path in {
            # relative and indirect
            (True, True): Path('../dispatch'),
            # relative and direct
            (True, False): Path(self.charm_exec_path),
            # absolute and direct
            (False, False): (self.hooks_dir / self.charm_exec_path).resolve(),
            # absolute and indirect
            (False, True): self.JUJU_CHARM_DIR / 'dispatch',
        }.items():
            # Sanity check
            assert path.is_absolute() == (not rel)
            assert (path.with_suffix('').name == 'dispatch') == ind
            try:
                hook_path.symlink_to(path)

                state = self._simulate_event(fake_script, event)
                assert isinstance(state, ops.BoundStoredState)

                # The `.on.` method was only called once
                assert list(state.observed_event_types) == ['InstallEvent']
                assert list(state.on_install) == ['InstallEvent']
            finally:
                hook_path.unlink()

    @pytest.mark.usefixtures('setup_charm')
    def test_hook_and_dispatch_but_hook_is_dispatch_copy(self, fake_script: FakeScript):
        hook_path = self.hooks_dir / 'install'
        path = (self.hooks_dir / self.charm_exec_path).resolve()
        shutil.copy(str(path), str(hook_path))

        event = EventSpec(ops.InstallEvent, 'install')
        state = self._simulate_event(fake_script, event)
        assert isinstance(state, ops.BoundStoredState)

        # the .on. was only called once
        assert list(state.observed_event_types) == ['InstallEvent']
        assert list(state.on_install) == ['InstallEvent']
        hook = Path('hooks/install')
        expected = [
            VERSION_LOGLINE,
            [
                'juju-log',
                '--log-level',
                'INFO',
                '--',
                f'Running legacy {hook}.',
            ],
            VERSION_LOGLINE,  # because it called itself
            ['juju-log', '--log-level', 'DEBUG', '--', f'Charm called itself via {hook}.'],
            ['juju-log', '--log-level', 'DEBUG', '--', f'Legacy {hook} exited with status 0.'],
            [
                'juju-log',
                '--log-level',
                'DEBUG',
                '--',
                'Using local storage: not a Kubernetes podspec charm',
            ],
            ['juju-log', '--log-level', 'DEBUG', '--', 'Emitting Juju event install.'],
            ['is-leader', '--format=json'],
        ]
        calls = fake_script.calls()
        assert 'Initializing SQLite local storage: ' in ' '.join(calls.pop(-3))

        assert calls == expected


class TestMainWithDispatchAsSymlink(_TestMain):
    def _setup_entry_point(self):
        path = self.JUJU_CHARM_DIR / 'dispatch'
        if not path.exists():
            path.symlink_to(os.path.join('src', 'charm.py'))

    def _call_event(
        self,
        fake_script: FakeScript,
        rel_path: Path,
        env: dict[str, str],
    ):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        env['JUJU_VERSION'] = '2.8.0'
        dispatch = self.JUJU_CHARM_DIR / 'dispatch'
        fake_script.write(
            'storage-get',
            """
            if [ "$1" = "-s" ]; then
                id=${2#*/}
                key=${2%/*}
                echo "\\"/var/srv/${key}/${id}\\"" # NOQA: test_quote_backslashes
            elif [ "$1" = '--help' ]; then
                printf '%s\\n' \\
                'Usage: storage-get [options] [<key>]' \\
                '   ' \\
                'Summary:' \\
                'print information for storage instance with specified id' \\
                '   ' \\
                'Options:' \\
                '--format  (= smart)' \\
                '    Specify output format (json|smart|yaml)' \\
                '-o, --output (= "")' \\
                '    Specify an output file' \\
                '-s  (= test-stor/0)' \\
                '    specify a storage instance by id' \\
                '   ' \\
                'Details:' \\
                'When no <key> is supplied, all keys values are printed.'
            else
                # Return the same path for all disks since `storage-get`
                # on attach and detach takes no parameters and is not
                # deterministically faked with fake_script
                exit 1
            fi
            """,
        )
        fake_script.write(
            'storage-list',
            """
            echo '["disks/0"]'
            """,
        )
        subprocess.run(
            [sys.executable, str(dispatch)],
            stdout=self.stdout,
            stderr=self.stderr,
            check=True,
            env=env,
            cwd=str(self.JUJU_CHARM_DIR),
        )

    @pytest.mark.usefixtures('setup_charm')
    def test_crash_action(self, request: pytest.FixtureRequest, fake_script: FakeScript):
        self.stderr = tempfile.TemporaryFile('w+t')  # noqa: SIM115
        request.addfinalizer(self.stderr.close)
        fake_script.write('action-get', "echo '{}'")
        with pytest.raises(subprocess.CalledProcessError):
            self._simulate_event(
                fake_script,
                EventSpec(
                    ops.ActionEvent,
                    'keyerror_action',
                    env_var='JUJU_ACTION_NAME',
                    set_in_env={'JUJU_ACTION_UUID': '1'},
                ),
            )
        self.stderr.seek(0)
        stderr = self.stderr.read()
        assert 'KeyError' in stderr
        assert "'foo' not found in 'bar'" in stderr


class TestMainWithDispatchAsScript(_TestMain):
    """Here dispatch is a script that execs the charm.py instead of a symlink."""

    def _setup_entry_point(self):
        path = self.JUJU_CHARM_DIR / 'dispatch'
        if not path.exists():
            path.write_text(
                '#!/bin/sh\nexec "{}" "{}"\n'.format(
                    sys.executable, self.JUJU_CHARM_DIR / 'src/charm.py'
                )
            )
            path.chmod(0o755)

    def _call_event(
        self,
        fake_script: FakeScript,
        rel_path: Path,
        env: dict[str, str],
    ):
        env['JUJU_DISPATCH_PATH'] = str(rel_path)
        env['JUJU_VERSION'] = '2.8.0'
        fake_script.write(
            'storage-get',
            """
            if [ "$1" = "-s" ]; then
                id=${2#*/}
                key=${2%/*}
                echo "\\"/var/srv/${key}/${id}\\"" # NOQA: test_quote_backslashes
            elif [ "$1" = '--help' ]; then
                printf '%s\\n' \\
                'Usage: storage-get [options] [<key>]' \\
                '   ' \\
                'Summary:' \\
                'print information for storage instance with specified id' \\
                '   ' \\
                'Options:' \\
                '--format  (= smart)' \\
                '    Specify output format (json|smart|yaml)' \\
                '-o, --output (= "")' \\
                '    Specify an output file' \\
                '-s  (= test-stor/0)' \\
                '    specify a storage instance by id' \\
                '   ' \\
                'Details:' \\
                'When no <key> is supplied, all keys values are printed.'
            else
                # Return the same path for all disks since `storage-get`
                # on attach and detach takes no parameters and is not
                # deterministically faked with fake_script
                exit 1
            fi
            """,
        )
        fake_script.write(
            'storage-list',
            """
            echo '["disks/0"]'
            """,
        )
        dispatch = self.JUJU_CHARM_DIR / 'dispatch'
        subprocess.check_call([str(dispatch)], env=env, cwd=str(self.JUJU_CHARM_DIR))


class TestStorageHeuristics:
    def test_fallback_to_current_juju_version__too_old(self):
        meta = ops.CharmMeta.from_yaml('series: [kubernetes]')
        with patch.dict(os.environ, {'JUJU_VERSION': '1.0'}):
            juju_context = JujuContext._from_dict(os.environ)
            assert not _should_use_controller_storage(Path('/xyzzy'), meta, juju_context)

    def test_fallback_to_current_juju_version__new_enough(self):
        meta = ops.CharmMeta.from_yaml('series: [kubernetes]')
        with patch.dict(os.environ, {'JUJU_VERSION': '2.8'}):
            juju_context = JujuContext._from_dict(os.environ)
            assert _should_use_controller_storage(Path('/xyzzy'), meta, juju_context)

    def test_not_if_not_in_k8s(self):
        meta = ops.CharmMeta.from_yaml('series: [ecs]')
        with patch.dict(os.environ, {'JUJU_VERSION': '2.8'}):
            juju_context = JujuContext._from_dict(os.environ)
            assert not _should_use_controller_storage(Path('/xyzzy'), meta, juju_context)

    def test_not_if_already_local(self):
        meta = ops.CharmMeta.from_yaml('series: [kubernetes]')
        with patch.dict(os.environ, {'JUJU_VERSION': '2.8'}), tempfile.NamedTemporaryFile() as fd:
            juju_context = JujuContext._from_dict(os.environ)
            assert not _should_use_controller_storage(Path(fd.name), meta, juju_context)
