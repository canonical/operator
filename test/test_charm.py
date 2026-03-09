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

import dataclasses
import enum
import functools
import pathlib
import tempfile
import typing
from pathlib import Path

import pytest
import yaml

try:
    import pydantic
    import pydantic.dataclasses
except ImportError:
    pydantic = None

import ops
import ops.charm
from ops import testing
from ops._main import _Abort
from ops.hookcmds import StatusName
from ops.model import ModelError

from .test_helpers import FakeScript, create_framework


@pytest.fixture
def fake_script(request: pytest.FixtureRequest) -> FakeScript:
    return FakeScript(request)


def test_basic(request: pytest.FixtureRequest):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)

            self.started = False
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, event: ops.EventBase):
            self.started = True

    framework = create_framework(request)

    events: list[str] = list(MyCharm.on.events())  # type: ignore
    assert 'install' in events
    assert 'custom' in events

    charm = MyCharm(framework)
    charm.on.start.emit()

    assert charm.started

    with pytest.raises(TypeError):
        framework.observe(charm.on.start, charm)  # type: ignore


def test_observe_decorated_method(request: pytest.FixtureRequest):
    # We test that charm methods decorated with @functools.wraps(wrapper)
    # can be observed by Framework. Simpler decorators won't work because
    # Framework searches for __self__ and other method things; functools.wraps
    # is more careful and it still works, this test is here to ensure that
    # it keeps working in future releases, as this is presently the only
    # way we know of to cleanly decorate charm event observers.
    events: list[ops.EventBase] = []

    def dec(fn: typing.Any) -> typing.Callable[..., None]:
        # simple decorator that appends to the nonlocal
        # `events` list all events it receives
        @functools.wraps(fn)
        def wrapper(charm: MyCharm, evt: ops.EventBase):
            events.append(evt)
            fn(charm, evt)

        return wrapper

    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.start, self._on_start)
            self.seen = None

        @dec
        def _on_start(self, event: ops.EventBase):
            self.seen = event

    framework = create_framework(request)
    charm = MyCharm(framework)
    charm.on.start.emit()
    # check that the event has been seen by the decorator
    assert len(events) == 1
    # check that the event has been seen by the observer
    assert isinstance(charm.seen, ops.StartEvent)


def test_observer_not_referenced_warning(
    request: pytest.FixtureRequest, caplog: pytest.LogCaptureFixture
):
    class MyObj(ops.Object):
        def __init__(self, charm: ops.CharmBase):
            super().__init__(charm, 'obj')
            framework.observe(charm.on.start, self._on_start)

        def _on_start(self, _: ops.StartEvent):
            raise RuntimeError()  # never reached!

    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            MyObj(self)  # not assigned!
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, _: ops.StartEvent):
            pass  # is reached

    framework = create_framework(request)
    c = MyCharm(framework)
    c.on.start.emit()
    assert 'Reference to ops.Object' in caplog.text


@pytest.mark.parametrize('empty_yaml', ['', '{}', None])
def test_empty_action_and_config_from_yaml(empty_yaml: str | None):
    meta = ops.CharmMeta.from_yaml('name: my-charm', empty_yaml, empty_yaml)
    assert meta.actions == {}
    assert meta.config == {}
    if empty_yaml is not None:
        meta = ops.CharmMeta.from_yaml('name: my-charm', config=f'options: {empty_yaml}')
        assert meta.actions == {}
        assert meta.config == {}


@pytest.mark.parametrize('empty_yaml', ['', '{}', None])
def test_empty_action_and_config_from_charm_root(empty_yaml: str | None):
    with tempfile.TemporaryDirectory() as d:
        td = pathlib.Path(d)
        (td / 'metadata.yaml').write_text('name: my-charm')
        if empty_yaml is not None:
            (td / 'actions.yaml').write_text(empty_yaml)
            (td / 'config.yaml').write_text(empty_yaml)
        meta = ops.CharmMeta.from_charm_root(td)
    assert meta.actions == {}
    assert meta.config == {}
    with tempfile.TemporaryDirectory() as d:
        td = pathlib.Path(d)
        (td / 'metadata.yaml').write_text('name: my-charm')
        if empty_yaml is not None:
            (td / 'config.yaml').write_text(f'options:\n  {empty_yaml}')
        meta = ops.CharmMeta.from_charm_root(td)
    assert meta.actions == {}
    assert meta.config == {}


@pytest.mark.parametrize('empty_yaml', [{}, None])
def test_empty_action_and_config(empty_yaml: dict[str, typing.Any] | None):
    meta = ops.CharmMeta({'name': 'my-charm'}, empty_yaml, empty_yaml)
    assert meta.actions == {}
    assert meta.config == {}
    meta = ops.CharmMeta({'name': 'my-charm'}, config_raw={'options': empty_yaml})
    assert meta.actions == {}
    assert meta.config == {}


def test_helper_properties(request: pytest.FixtureRequest):
    class MyCharm(ops.CharmBase):
        pass

    framework = create_framework(request)
    charm = MyCharm(framework)
    assert charm.app == framework.model.app
    assert charm.unit == framework.model.unit
    assert charm.meta == framework.meta
    assert charm.charm_dir == framework.charm_dir
    assert charm.config is framework.model.config


def test_relation_events(request: pytest.FixtureRequest):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.seen: list[str] = []
            for rel in ('req1', 'req-2', 'pro1', 'pro-2', 'peer1', 'peer-2'):
                # Hook up relation events to generic handler.
                self.framework.observe(self.on[rel].relation_joined, self.on_any_relation)
                self.framework.observe(self.on[rel].relation_changed, self.on_any_relation)
                self.framework.observe(self.on[rel].relation_departed, self.on_any_relation)
                self.framework.observe(self.on[rel].relation_broken, self.on_any_relation)

        def on_any_relation(self, event: ops.RelationEvent):
            assert event.relation.name == 'req1'
            assert event.relation.app is not None
            assert event.relation.app.name == 'remote'
            self.seen.append(type(event).__name__)

    # language=YAML
    meta = ops.CharmMeta.from_yaml(
        metadata="""
name: my-charm
requires:
 req1:
   interface: req1
 req-2:
   interface: req2
provides:
 pro1:
   interface: pro1
 pro-2:
   interface: pro2
peers:
 peer1:
   interface: peer1
 peer-2:
   interface: peer2
"""
    )
    framework = create_framework(request, meta=meta)
    charm = MyCharm(framework)

    assert 'pro_2_relation_broken' in repr(charm.on)

    rel = charm.framework.model.get_relation('req1', 1)
    app = charm.framework.model.get_app('remote')
    unit = charm.framework.model.get_unit('remote/0')
    charm.on['req1'].relation_joined.emit(rel, app, unit)
    charm.on['req1'].relation_changed.emit(rel, app, unit)
    charm.on['req1'].relation_changed.emit(rel, app)
    charm.on['req-2'].relation_changed.emit(rel, app, unit)
    charm.on['pro1'].relation_departed.emit(rel, app, unit)
    charm.on['pro-2'].relation_departed.emit(rel, app, unit)
    charm.on['peer1'].relation_broken.emit(rel, app)
    charm.on['peer-2'].relation_broken.emit(rel, app)

    assert charm.seen == [
        'RelationJoinedEvent',
        'RelationChangedEvent',
        'RelationChangedEvent',
        'RelationChangedEvent',
        'RelationDepartedEvent',
        'RelationDepartedEvent',
        'RelationBrokenEvent',
        'RelationBrokenEvent',
    ]


def test_storage_events(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.seen: list[str] = []
            self.framework.observe(self.on['stor1'].storage_attached, self._on_stor1_attach)
            self.framework.observe(self.on['stor2'].storage_detaching, self._on_stor2_detach)
            self.framework.observe(self.on['stor3'].storage_attached, self._on_stor3_attach)
            self.framework.observe(self.on['stor-4'].storage_attached, self._on_stor4_attach)

        def _on_stor1_attach(self, event: ops.StorageAttachedEvent):
            self.seen.append(type(event).__name__)
            assert event.storage.location == Path('/var/srv/stor1/0')

        def _on_stor2_detach(self, event: ops.StorageDetachingEvent):
            self.seen.append(type(event).__name__)

        def _on_stor3_attach(self, event: ops.StorageAttachedEvent):
            self.seen.append(type(event).__name__)

        def _on_stor4_attach(self, event: ops.StorageAttachedEvent):
            self.seen.append(type(event).__name__)

    # language=YAML
    meta = ops.CharmMeta.from_yaml("""
name: my-charm
storage:
  stor-4:
    multiple:
      range: 2-4
    type: filesystem
  stor1:
    type: filesystem
  stor2:
    multiple:
      range: "2"
    type: filesystem
  stor3:
    multiple:
      range: 2-
    type: filesystem
  stor-multiple-dashes:
    multiple:
      range: 2-
    type: filesystem
  stor-plus:
    multiple:
      range: 10+
    type: filesystem
""")

    fake_script.write(
        'storage-get',
        """
        if [ "$2" = "-s" ]; then
            id=${3#*/}
            key=${3%/*}
            echo "{\\"kind\\": \\"filesystem\\", \\"location\\": \\"/var/srv/${key}/${id}\\"}"
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

    assert meta.storages['stor1'].multiple_range is None
    assert meta.storages['stor2'].multiple_range == (2, 2)
    assert meta.storages['stor3'].multiple_range == (2, None)
    assert meta.storages['stor-4'].multiple_range == (2, 4)
    assert meta.storages['stor-plus'].multiple_range == (10, None)

    framework = create_framework(request, meta=meta)
    charm = MyCharm(framework)

    charm.on['stor1'].storage_attached.emit(ops.Storage('stor1', 0, charm.model._backend))
    charm.on['stor2'].storage_detaching.emit(ops.Storage('stor2', 0, charm.model._backend))
    charm.on['stor3'].storage_attached.emit(ops.Storage('stor3', 0, charm.model._backend))
    charm.on['stor-4'].storage_attached.emit(ops.Storage('stor-4', 0, charm.model._backend))
    charm.on['stor-multiple-dashes'].storage_attached.emit(
        ops.Storage('stor-multiple-dashes', 0, charm.model._backend)
    )

    assert charm.seen == [
        'StorageAttachedEvent',
        'StorageDetachingEvent',
        'StorageAttachedEvent',
        'StorageAttachedEvent',
    ]


def test_workload_events(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    def mock_change(self: ops.pebble.Client, change_id: str):
        return ops.pebble.Change.from_dict({
            'id': ops.pebble.ChangeID(change_id),
            'kind': 'recover-check',
            'ready': False,
            'spawn-time': '2021-01-28T14:37:02.247202105+13:00',
            'status': 'Error',
            'summary': 'Recovering check "test"',
        })

    monkeypatch.setattr(ops.pebble.Client, 'get_change', mock_change)

    def mock_check_info(
        self: ops.pebble.Client,
        level: ops.pebble.CheckLevel | None = None,
        names: typing.Iterable[str] | None = None,
    ):
        assert names is not None
        names = list(names)
        return [
            ops.pebble.CheckInfo.from_dict({
                'name': names[0],
                'status': 'down',
                'failures': 3,
                'threshold': 3,
                'change-id': '1',
            })
        ]

    monkeypatch.setattr(ops.pebble.Client, 'get_checks', mock_check_info)

    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.seen: list[str] = []
            for workload in ('container-a', 'containerb'):
                # Hook up relation events to generic handler.
                self.framework.observe(self.on[workload].pebble_ready, self.on_any_pebble_ready)
                self.framework.observe(
                    self.on[workload].pebble_custom_notice,
                    self.on_any_pebble_custom_notice,
                )
                self.framework.observe(
                    self.on[workload].pebble_check_failed, self.on_any_pebble_check_event
                )
                self.framework.observe(
                    self.on[workload].pebble_check_recovered, self.on_any_pebble_check_event
                )

        def on_any_pebble_ready(self, event: ops.PebbleReadyEvent):
            self.seen.append(type(event).__name__)

        def on_any_pebble_custom_notice(self, event: ops.PebbleCustomNoticeEvent):
            self.seen.append(type(event).__name__)

        def on_any_pebble_check_event(
            self, event: ops.PebbleCheckFailedEvent | ops.PebbleCheckRecoveredEvent
        ):
            self.seen.append(type(event).__name__)
            info = event.info
            assert info.name == 'test'
            assert info.status == ops.pebble.CheckStatus.DOWN

    # language=YAML
    meta = ops.CharmMeta.from_yaml(
        metadata="""
name: my-charm
containers:
  container-a:
  containerb:
"""
    )
    framework = create_framework(request, meta=meta)
    charm = MyCharm(framework)

    assert 'container_a_pebble_ready' in repr(charm.on)
    assert 'containerb_pebble_ready' in repr(charm.on)

    charm.on['container-a'].pebble_ready.emit(
        charm.framework.model.unit.get_container('container-a')
    )
    charm.on['containerb'].pebble_ready.emit(
        charm.framework.model.unit.get_container('containerb')
    )

    charm.on['container-a'].pebble_custom_notice.emit(
        charm.framework.model.unit.get_container('container-a'), '1', 'custom', 'x'
    )
    charm.on['containerb'].pebble_custom_notice.emit(
        charm.framework.model.unit.get_container('containerb'), '2', 'custom', 'y'
    )

    charm.on['container-a'].pebble_check_failed.emit(
        charm.framework.model.unit.get_container('container-a'), 'test'
    )
    charm.on['containerb'].pebble_check_recovered.emit(
        charm.framework.model.unit.get_container('containerb'), 'test'
    )

    assert charm.seen == [
        'PebbleReadyEvent',
        'PebbleReadyEvent',
        'PebbleCustomNoticeEvent',
        'PebbleCustomNoticeEvent',
        'PebbleCheckFailedEvent',
        'PebbleCheckRecoveredEvent',
    ]


def test_relations_meta():
    # language=YAML
    meta = ops.CharmMeta.from_yaml(
        metadata="""
name: my-charm
requires:
  database:
    interface: mongodb
    limit: 1
    scope: container
  metrics:
    interface: prometheus-scraping
    optional: true
"""
    )

    assert meta.requires['database'].interface_name == 'mongodb'
    assert meta.requires['database'].limit == 1
    assert meta.requires['database'].scope == 'container'
    assert not meta.requires['database'].optional

    assert meta.requires['metrics'].interface_name == 'prometheus-scraping'
    assert meta.requires['metrics'].limit is None
    assert meta.requires['metrics'].scope == 'global'  # Default value
    assert meta.requires['metrics'].optional


def test_relations_meta_limit_type_validation():
    with pytest.raises(TypeError, match=r"limit should be an int, not <class 'str'>"):
        # language=YAML
        ops.CharmMeta.from_yaml("""
name: my-charm
requires:
  database:
    interface: mongodb
    limit: foobar
""")


def test_relations_meta_scope_type_validation():
    with pytest.raises(
        TypeError, match="scope should be one of 'global', 'container'; not 'foobar'"
    ):
        # language=YAML
        ops.CharmMeta.from_yaml("""
name: my-charm
requires:
  database:
    interface: mongodb
    scope: foobar
""")


def test_meta_from_charm_root():
    with tempfile.TemporaryDirectory() as d:
        td = pathlib.Path(d)
        (td / 'metadata.yaml').write_text(
            yaml.safe_dump({'name': 'bob', 'requires': {'foo': {'interface': 'bar'}}})
        )
        meta = ops.CharmMeta.from_charm_root(td)
        assert meta.name == 'bob'
        assert meta.requires['foo'].interface_name == 'bar'


def test_config_from_charm_root():
    with tempfile.TemporaryDirectory() as d:
        td = pathlib.Path(d)
        (td / 'config.yaml').write_text(
            yaml.safe_dump({
                'options': {
                    'foo': {'type': 'string', 'default': 'bar'},
                    'baz': {'type': 'int', 'default': 42},
                    'qux': {'type': 'bool', 'default': True},
                    'quux': {'type': 'float', 'default': 3.14},
                    'sssh': {'type': 'secret', 'description': 'a user secret'},
                }
            })
        )
        (td / 'metadata.yaml').write_text(yaml.safe_dump({'name': 'bob'}))
        meta = ops.CharmMeta.from_charm_root(td)
        assert meta.name == 'bob'
        assert meta.config['foo'].type == 'string'
        assert meta.config['foo'].default == 'bar'
        assert meta.config['baz'].type == 'int'
        assert meta.config['baz'].default == 42
        assert meta.config['qux'].type == 'bool'
        assert meta.config['qux'].default  # == True
        assert meta.config['quux'].type == 'float'
        assert meta.config['quux'].default == 3.14
        assert meta.config['sssh'].type == 'secret'
        assert meta.config['sssh'].description == 'a user secret'


def test_config_from_yaml():
    options = yaml.safe_dump({
        'options': {
            'foo': {'type': 'string', 'default': 'bar'},
            'baz': {'type': 'int', 'default': 42},
            'qux': {'type': 'bool', 'default': True},
            'quux': {'type': 'float', 'default': 3.14},
            'sssh': {'type': 'secret', 'description': 'a user secret'},
        }
    })
    metadata = yaml.safe_dump({'name': 'bob'})
    meta = ops.CharmMeta.from_yaml(metadata, config=options)
    assert meta.name == 'bob'
    assert meta.config['foo'].type == 'string'
    assert meta.config['foo'].default == 'bar'
    assert meta.config['baz'].type == 'int'
    assert meta.config['baz'].default == 42
    assert meta.config['qux'].type == 'bool'
    assert meta.config['qux'].default  # == True
    assert meta.config['quux'].type == 'float'
    assert meta.config['quux'].default == 3.14
    assert meta.config['sssh'].type == 'secret'
    assert meta.config['sssh'].description == 'a user secret'


def test_config_from_raw():
    options = {
        'options': {
            'foo': {'type': 'string', 'default': 'bar'},
            'baz': {'type': 'int', 'default': 42},
            'qux': {'type': 'bool', 'default': True},
            'quux': {'type': 'float', 'default': 3.14},
            'sssh': {'type': 'secret', 'description': 'a user secret'},
        },
    }
    metadata = {'name': 'bob'}
    meta = ops.CharmMeta(raw=metadata, config_raw=options)
    assert meta.name == 'bob'
    assert meta.config['foo'].type == 'string'
    assert meta.config['foo'].default == 'bar'
    assert meta.config['baz'].type == 'int'
    assert meta.config['baz'].default == 42
    assert meta.config['qux'].type == 'bool'
    assert meta.config['qux'].default  # == True
    assert meta.config['quux'].type == 'float'
    assert meta.config['quux'].default == 3.14
    assert meta.config['sssh'].type == 'secret'
    assert meta.config['sssh'].description == 'a user secret'


@pytest.mark.parametrize('additional_properties', [False, True])
def test_actions_from_charm_root(additional_properties: bool):
    with tempfile.TemporaryDirectory() as d:
        td = pathlib.Path(d)
        (td / 'actions.yaml').write_text(
            yaml.safe_dump({
                'foo': {
                    'description': 'foos the bar',
                    'additionalProperties': additional_properties,
                }
            })
        )
        (td / 'metadata.yaml').write_text(
            yaml.safe_dump({'name': 'bob', 'requires': {'foo': {'interface': 'bar'}}})
        )

        meta = ops.CharmMeta.from_charm_root(td)
        assert meta.name == 'bob'
        assert meta.requires['foo'].interface_name == 'bar'
        assert meta.actions['foo'].additional_properties == additional_properties
        assert meta.actions['foo'].description == 'foos the bar'


@pytest.mark.parametrize(
    'juju_version,additional_properties',
    [('2.9', True), ('3.6.12', True), ('4.0.0', False), ('4.1', False), (None, True)],
)
def test_actions_additional_properties(
    monkeypatch: pytest.MonkeyPatch, juju_version: str | None, additional_properties: bool
):
    if juju_version is None:
        monkeypatch.delenv('JUJU_VERSION', raising=False)
    else:
        monkeypatch.setenv('JUJU_VERSION', juju_version)
    action = ops.ActionMeta('foo', {})
    assert action.additional_properties == additional_properties


def _setup_test_action(fake_script: FakeScript):
    fake_script.write('action-get', """echo '{"foo-name": "name", "silent": true}'""")
    fake_script.write('action-set', '')
    fake_script.write('action-log', '')
    fake_script.write('action-fail', '')


def _get_action_test_meta():
    return ops.CharmMeta.from_yaml(
        metadata="""
name: my-charm
""",
        actions="""
foo-bar:
  description: "Foos the bar."
  params:
    foo-name:
      description: "A foo name to bar"
      type: string
    silent:
      default: false
      description: ""
      type: boolean
  required: foo-bar
  title: foo-bar
start:
  description: "Start the unit."
  additionalProperties: false
""",
    )


def test_action_events(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.foo_bar_action, self._on_foo_bar_action)
            framework.observe(self.on.start_action, self._on_start_action)

        def _on_foo_bar_action(self, event: ops.ActionEvent):
            self.seen_action_params = event.params
            event.log('test-log')
            event.set_results({'res': 'val with spaces', 'id': event.id})
            event.fail('test-fail')

        def _on_start_action(self, event: ops.ActionEvent):
            pass

    _setup_test_action(fake_script)
    meta = _get_action_test_meta()
    framework = create_framework(request, meta=meta)
    charm = MyCharm(framework)

    events: list[str] = list(MyCharm.on.events())  # type: ignore
    assert 'foo_bar_action' in events
    assert 'start_action' in events

    action_id = '1234'
    charm.on.foo_bar_action.emit(id=action_id)
    assert charm.seen_action_params == {'foo-name': 'name', 'silent': True}
    assert fake_script.calls() == [
        ['action-get', '--format=json'],
        ['action-log', '--', 'test-log'],
        ['action-set', 'res=val with spaces', f'id={action_id}'],
        ['action-fail', '--', 'test-fail'],
    ]


@pytest.mark.parametrize(
    'bad_res',
    [
        {'a': {'b': 'c'}, 'a.b': 'c'},
        {'a': {'B': 'c'}},
        {'a': {(1, 2): 'c'}},
        {'a': {None: 'c'}},
        {'aBc': 'd'},
    ],
)
def test_invalid_action_results(
    request: pytest.FixtureRequest, fake_script: FakeScript, bad_res: dict[str, typing.Any]
):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.res: dict[str, typing.Any] = {}
            framework.observe(self.on.foo_bar_action, self._on_foo_bar_action)

        def _on_foo_bar_action(self, event: ops.ActionEvent):
            event.set_results(self.res)

    _setup_test_action(fake_script)
    meta = _get_action_test_meta()
    framework = create_framework(request, meta=meta)
    charm = MyCharm(framework)

    charm.res = bad_res
    with pytest.raises(ValueError):
        charm.on.foo_bar_action.emit(id='1')


@pytest.mark.parametrize(
    'event,kwargs',
    [
        ('start_action', {'id': 2}),
        ('stop', {}),
        ('remove', {}),
        ('secret_expired', {'id': 'secret:123', 'label': None, 'revision': 0}),
        ('secret_rotate', {'id': 'secret:234', 'label': 'my-secret'}),
    ],
)
def test_inappropriate_event_defer_fails(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    fake_script: FakeScript,
    event: str,
    kwargs: dict[str, typing.Any],
):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(getattr(self.on, event), self._call_defer)

        def _call_defer(self, event: ops.EventBase):
            event.defer()

    # This is only necessary for the action event, but is ignored by the others.
    cmd_type = 'action'
    fake_script.write(f'{cmd_type}-get', """echo '{"foo-name": "name", "silent": true}'""")
    monkeypatch.setenv(f'JUJU_{cmd_type.upper()}_NAME', 'start')
    meta = _get_action_test_meta()

    framework = create_framework(request, meta=meta)
    charm = MyCharm(framework)

    with pytest.raises(RuntimeError):
        getattr(charm.on, event).emit(**kwargs)


def test_containers():
    meta = ops.CharmMeta.from_yaml("""
name: k8s-charm
containers:
  test1:
    k: v
  test2:
    k: v
""")
    assert isinstance(meta.containers['test1'], ops.ContainerMeta)
    assert isinstance(meta.containers['test2'], ops.ContainerMeta)
    assert meta.containers['test1'].name == 'test1'
    assert meta.containers['test2'].name == 'test2'


def test_containers_storage():
    meta = ops.CharmMeta.from_yaml("""
name: k8s-charm
storage:
  data:
    type: filesystem
    location: /test/storage
  other:
    type: filesystem
    location: /test/other
    properties:
      - transient
containers:
  test1:
    mounts:
      - storage: data
        location: /test/storagemount
      - storage: other
        location: /test/otherdata
    resource: ubuntu-22.10
  test2:
    bases:
      - name: ubuntu
        channel: '23.10'
        architectures:
         - amd64
      - name: ubuntu
        channel: 23.04/stable/fips
        architectures:
         - arm
""")
    assert isinstance(meta.containers['test1'], ops.ContainerMeta)
    assert isinstance(meta.containers['test1'].mounts['data'], ops.ContainerStorageMeta)
    assert meta.containers['test1'].mounts['data'].location == '/test/storagemount'
    assert meta.containers['test1'].mounts['other'].location == '/test/otherdata'
    assert meta.storages['other'].properties == ['transient']
    assert meta.containers['test1'].resource == 'ubuntu-22.10'
    assert meta.containers['test2'].bases is not None
    assert len(meta.containers['test2'].bases) == 2
    assert meta.containers['test2'].bases[0].os_name == 'ubuntu'
    assert meta.containers['test2'].bases[0].channel == '23.10'
    assert meta.containers['test2'].bases[0].architectures == ['amd64']
    assert meta.containers['test2'].bases[1].os_name == 'ubuntu'
    assert meta.containers['test2'].bases[1].channel == '23.04/stable/fips'
    assert meta.containers['test2'].bases[1].architectures == ['arm']
    # It's an error to specify both the 'resource' and the 'bases' fields.
    with pytest.raises(ModelError):
        ops.CharmMeta.from_yaml("""
name: invalid-charm
containers:
  test1:
    bases:
      - name: ubuntu
        channel: '23.10'
        architectures: [amd64]
    resource: ubuntu-23.10
""")


def test_containers_storage_multiple_mounts():
    meta = ops.CharmMeta.from_yaml("""
name: k8s-charm
storage:
  data:
    type: filesystem
    location: /test/storage
containers:
  test1:
    mounts:
      - storage: data
        location: /test/storagemount
      - storage: data
        location: /test/otherdata
""")
    assert isinstance(meta.containers['test1'], ops.ContainerMeta)
    assert isinstance(meta.containers['test1'].mounts['data'], ops.ContainerStorageMeta)
    assert meta.containers['test1'].mounts['data'].locations[0] == '/test/storagemount'
    assert meta.containers['test1'].mounts['data'].locations[1] == '/test/otherdata'

    with pytest.raises(RuntimeError):
        meta.containers['test1'].mounts['data'].location


def test_secret_events(request: pytest.FixtureRequest):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.seen: list[str] = []
            self.framework.observe(self.on.secret_changed, self.on_secret_changed)
            self.framework.observe(self.on.secret_rotate, self.on_secret_rotate)
            self.framework.observe(self.on.secret_remove, self.on_secret_remove)
            self.framework.observe(self.on.secret_expired, self.on_secret_expired)

        def on_secret_changed(self, event: ops.SecretChangedEvent):
            assert event.secret.id == 'secret:changed'
            assert event.secret.label is None
            self.seen.append(type(event).__name__)

        def on_secret_rotate(self, event: ops.SecretRotateEvent):
            assert event.secret.id == 'secret:rotate'
            assert event.secret.label == 'rot'
            self.seen.append(type(event).__name__)

        def on_secret_remove(self, event: ops.SecretRemoveEvent):
            assert event.secret.id == 'secret:remove'
            assert event.secret.label == 'rem'
            assert event.revision == 7
            self.seen.append(type(event).__name__)

        def on_secret_expired(self, event: ops.SecretExpiredEvent):
            assert event.secret.id == 'secret:expired'
            assert event.secret.label == 'exp'
            assert event.revision == 42
            self.seen.append(type(event).__name__)

    framework = create_framework(request)
    charm = MyCharm(framework)

    charm.on.secret_changed.emit('secret:changed', None)
    charm.on.secret_rotate.emit('secret:rotate', 'rot')
    charm.on.secret_remove.emit('secret:remove', 'rem', 7)
    charm.on.secret_expired.emit('secret:expired', 'exp', 42)

    assert charm.seen == [
        'SecretChangedEvent',
        'SecretRotateEvent',
        'SecretRemoveEvent',
        'SecretExpiredEvent',
    ]


@pytest.mark.parametrize('event', ['secret_remove', 'secret_expired'])
def test_secret_event_remove_revision(
    request: pytest.FixtureRequest, fake_script: FakeScript, event: str
):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(getattr(self.on, event), self.on_secret_event)

        def on_secret_event(self, event: ops.SecretRemoveEvent | ops.SecretExpiredEvent):
            event.remove_revision()

    framework = create_framework(request)
    charm = MyCharm(framework)
    fake_script.write('secret-remove', 'exit 0')
    secret_id = 'secret:remove'
    revision = 28

    getattr(charm.on, event).emit(secret_id, 'secret-label', revision)

    assert fake_script.calls(True) == [
        ['secret-remove', secret_id, '--revision', str(revision)],
    ]


def test_collect_app_status_leader(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        def _on_collect_status(self, event: ops.CollectStatusEvent):
            event.add_status(ops.ActiveStatus())
            event.add_status(ops.BlockedStatus('first'))
            event.add_status(ops.WaitingStatus('waiting'))
            event.add_status(ops.BlockedStatus('second'))

    fake_script.write('is-leader', 'echo true')
    fake_script.write('status-set', 'exit 0')

    framework = create_framework(request)
    charm = MyCharm(framework)
    ops.charm._evaluate_status(charm)

    assert fake_script.calls(True) == [
        ['is-leader', '--format=json'],
        ['status-set', '--application=True', 'blocked', '--', 'first'],
    ]


def test_collect_app_status_no_statuses(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        def _on_collect_status(self, event: ops.CollectStatusEvent):
            pass

    fake_script.write('is-leader', 'echo true')

    framework = create_framework(request)
    charm = MyCharm(framework)
    ops.charm._evaluate_status(charm)

    assert fake_script.calls(True) == [
        ['is-leader', '--format=json'],
    ]


def test_collect_app_status_non_leader(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        def _on_collect_status(self, event: ops.CollectStatusEvent):
            raise Exception  # shouldn't be called

    fake_script.write('is-leader', 'echo false')

    framework = create_framework(request)
    charm = MyCharm(framework)
    ops.charm._evaluate_status(charm)

    assert fake_script.calls(True) == [
        ['is-leader', '--format=json'],
    ]


def test_collect_unit_status(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.collect_unit_status, self._on_collect_status)

        def _on_collect_status(self, event: ops.CollectStatusEvent):
            event.add_status(ops.ActiveStatus())
            event.add_status(ops.BlockedStatus('first'))
            event.add_status(ops.WaitingStatus('waiting'))
            event.add_status(ops.BlockedStatus('second'))

    # called only for collecting app statuses
    fake_script.write('is-leader', 'echo false')
    fake_script.write('status-set', 'exit 0')

    framework = create_framework(request)
    charm = MyCharm(framework)
    ops.charm._evaluate_status(charm)

    assert fake_script.calls(True) == [
        ['is-leader', '--format=json'],
        ['status-set', '--application=False', 'blocked', '--', 'first'],
    ]


def test_collect_unit_status_no_statuses(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.collect_unit_status, self._on_collect_status)

        def _on_collect_status(self, event: ops.CollectStatusEvent):
            pass

    # called only for collecting app statuses
    fake_script.write('is-leader', 'echo false')

    framework = create_framework(request)
    charm = MyCharm(framework)
    ops.charm._evaluate_status(charm)

    assert fake_script.calls(True) == [
        ['is-leader', '--format=json'],
    ]


def test_collect_app_and_unit_status(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.collect_app_status, self._on_collect_app_status)
            self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

        def _on_collect_app_status(self, event: ops.CollectStatusEvent):
            event.add_status(ops.ActiveStatus())

        def _on_collect_unit_status(self, event: ops.CollectStatusEvent):
            event.add_status(ops.WaitingStatus('blah'))

    fake_script.write('is-leader', 'echo true')
    fake_script.write('status-set', 'exit 0')

    framework = create_framework(request)
    charm = MyCharm(framework)
    ops.charm._evaluate_status(charm)

    assert fake_script.calls(True) == [
        ['is-leader', '--format=json'],
        ['status-set', '--application=True', 'active', '--', ''],
        ['status-set', '--application=False', 'waiting', '--', 'blah'],
    ]


def test_add_status_type_error(request: pytest.FixtureRequest, fake_script: FakeScript):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.collect_app_status, self._on_collect_status)

        def _on_collect_status(self, event: ops.CollectStatusEvent):
            event.add_status('active')  # type: ignore

    fake_script.write('is-leader', 'echo true')

    framework = create_framework(request)
    charm = MyCharm(framework)
    with pytest.raises(TypeError):
        ops.charm._evaluate_status(charm)


@pytest.mark.parametrize(
    'statuses,expected',
    [
        (['waiting', 'blocked'], 'blocked'),
        (['waiting', 'maintenance'], 'maintenance'),
        (['active', 'waiting'], 'waiting'),
    ],
)
def test_collect_status_priority_valid(
    request: pytest.FixtureRequest,
    fake_script: FakeScript,
    statuses: list[StatusName],
    expected: str,
):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework, statuses: list[StatusName]):
            super().__init__(framework)
            self.framework.observe(self.on.collect_app_status, self._on_collect_status)
            self.statuses = statuses

        def _on_collect_status(self, event: ops.CollectStatusEvent):
            for status in self.statuses:
                event.add_status(ops.StatusBase.from_name(status, ''))

    fake_script.write('is-leader', 'echo true')
    fake_script.write('status-set', 'exit 0')

    framework = create_framework(request)
    charm = MyCharm(framework, statuses=statuses)
    ops.charm._evaluate_status(charm)

    status_set_calls = [call for call in fake_script.calls(True) if call[0] == 'status-set']
    assert status_set_calls == [['status-set', '--application=True', expected, '--', '']]


@pytest.mark.parametrize(
    'statuses',
    [
        ['blocked', 'error'],
        ['unknown'],
        ['active', 'unknown'],
    ],
)
def test_collect_status_priority_invalid(
    request: pytest.FixtureRequest,
    fake_script: FakeScript,
    statuses: list[StatusName],
):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework, statuses: list[StatusName]):
            super().__init__(framework)
            self.framework.observe(self.on.collect_app_status, self._on_collect_status)
            self.statuses = statuses

        def _on_collect_status(self, event: ops.CollectStatusEvent):
            for status in self.statuses:
                event.add_status(ops.StatusBase.from_name(status, ''))

    fake_script.write('is-leader', 'echo true')

    framework = create_framework(request)
    charm = MyCharm(framework, statuses=statuses)
    with pytest.raises(ops.InvalidStatusError):
        ops.charm._evaluate_status(charm)


def test_meta_links():
    # Each type of link can be a single item.
    meta = ops.CharmMeta.from_yaml("""
name: my-charm
website: https://example.com
source: https://git.example.com
issues: https://bugs.example.com
docs: https://docs.example.com
""")
    assert meta.links.websites == ['https://example.com']
    assert meta.links.sources == ['https://git.example.com']
    assert meta.links.issues == ['https://bugs.example.com']
    assert meta.links.documentation == 'https://docs.example.com'
    # Other than documentation, they can also all be lists of items.
    meta = ops.CharmMeta.from_yaml("""
name: my-charm
website:
 - https://example.com
 - https://example.org
source:
 - https://git.example.com
 - https://bzr.example.com
issues:
 - https://bugs.example.com
 - https://features.example.com
""")
    assert meta.links.websites == ['https://example.com', 'https://example.org']
    assert meta.links.sources == ['https://git.example.com', 'https://bzr.example.com']
    assert meta.links.issues == ['https://bugs.example.com', 'https://features.example.com']


def test_meta_links_charmcraft_yaml():
    meta = ops.CharmMeta.from_yaml("""
links:
  documentation: https://discourse.example.com/
  issues:
  - https://git.example.com/
  source:
  - https://git.example.com/issues/
  website:
  - https://example.com/
  contact: Support Team <help@example.com>
""")
    assert meta.links.websites == ['https://example.com/']
    assert meta.links.sources == ['https://git.example.com/issues/']
    assert meta.links.issues == ['https://git.example.com/']
    assert meta.links.documentation == 'https://discourse.example.com/'
    assert meta.maintainers == ['Support Team <help@example.com>']


def test_meta_assumes():
    meta = ops.CharmMeta.from_yaml("""
assumes:
  - juju
""")
    assert meta.assumes.features == ['juju']
    meta = ops.CharmMeta.from_yaml("""
assumes:
  - juju > 3
  - k8s-api
""")
    assert meta.assumes.features == ['juju > 3', 'k8s-api']
    meta = ops.CharmMeta.from_yaml("""
assumes:
  - k8s-api
  - any-of:
      - all-of:
          - juju >= 2.9.44
          - juju < 3
      - all-of:
          - juju >= 3.1.5
          - juju < 4
""")
    assert meta.assumes.features == [
        'k8s-api',
        ops.JujuAssumes(
            [
                ops.JujuAssumes(['juju >= 2.9.44', 'juju < 3']),
                ops.JujuAssumes(['juju >= 3.1.5', 'juju < 4']),
            ],
            ops.JujuAssumesCondition.ANY,
        ),
    ]


@pytest.mark.parametrize('user', ['root', 'sudoer', 'non-root'])
def test_meta_charm_user(user: str):
    meta = ops.CharmMeta.from_yaml(f"""
name: my-charm
charm-user: {user}
""")
    assert meta.charm_user == user


def test_meta_charm_user_default():
    meta = ops.CharmMeta.from_yaml("""
name: my-charm
""")
    assert meta.charm_user == 'root'


class _ConfigProtocol(typing.Protocol):
    @property
    def my_bool(self) -> bool | None: ...
    @property
    def my_int(self) -> int: ...
    @property
    def my_float(self) -> float: ...
    @property
    def my_str(self) -> str: ...
    @property
    def my_secret(self) -> ops.Secret | None: ...


class MyConfig:
    my_bool: bool | None = None
    my_int: int = 42
    my_float: float = 3.14
    my_str: str = 'foo'
    my_secret: ops.Secret | None = None

    def __init__(
        self,
        *,
        my_bool: bool | int | float | str | None = None,
        my_int: bool | int | float | str = 42,
        my_float: bool | int | float | str = 3.14,
        my_str: bool | int | float | str = 'foo',
        my_secret: ops.Secret | None = None,
    ):
        super().__init__()
        # Juju takes care of making sure the types are correct, so this
        # is only to help the Python type checking understand that.
        if my_bool is not None:
            assert isinstance(my_bool, bool)
        self.my_bool = my_bool
        assert isinstance(my_float, float)
        self.my_float = my_float
        assert isinstance(my_int, int)
        if my_int < 0:
            raise ValueError('my_int must be zero or positive')
        self.my_int = my_int
        assert isinstance(my_str, str)
        self.my_str = my_str
        if my_secret is not None:
            assert isinstance(my_secret, ops.Secret)
            self.my_secret = my_secret


class BaseTestConfigCharm(ops.CharmBase):
    _config_errors: typing.Literal['blocked', 'raise'] | None = None

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        if self._config_errors:
            self.typed_config = self.load_config(self.config_class, errors=self._config_errors)
        else:
            self.typed_config = self.load_config(self.config_class)
        # These should not have any type errors.
        new_float = self.typed_config.my_float + 2006.8
        new_int = self.typed_config.my_int + 1979
        new_str = self.typed_config.my_str + 'bar'
        if self.typed_config.my_secret is not None:
            label = self.typed_config.my_secret.label
        else:
            label = 'no secret'
        # 'Use' the values to avoid unused variable errors.
        self.data = f'{new_float=}, {new_int=}, {new_str=}, {label=}'

    @property
    def config_class(self) -> type[_ConfigProtocol]:
        raise NotImplementedError


class _MyConfigCharm(BaseTestConfigCharm):
    @property
    def config_class(self) -> type[_ConfigProtocol]:
        return MyConfig


@dataclasses.dataclass(frozen=True, kw_only=True)
class MyDataclassConfig:
    my_bool: bool | None = None
    my_int: int = 42
    my_float: float = 3.14
    my_str: str = 'foo'
    my_secret: ops.Secret | None = None

    def __post_init__(self):
        if self.my_int < 0:
            raise ValueError('my_int must be zero or positive')


class _MyDataclassConfigCharm(BaseTestConfigCharm):
    @property
    def config_class(self) -> type[_ConfigProtocol]:
        return MyDataclassConfig


_test_config_classes: list[type[BaseTestConfigCharm]] = [_MyConfigCharm, _MyDataclassConfigCharm]

if pydantic:

    @pydantic.dataclasses.dataclass(frozen=True, config={'arbitrary_types_allowed': True})
    class MyPydanticDataclassConfig:
        my_bool: bool | None = pydantic.Field(None)
        my_int: int = pydantic.Field(42)
        my_float: float = pydantic.Field(3.14)
        my_str: str = pydantic.Field('foo')
        my_secret: ops.Secret | None = pydantic.Field(None)

        @pydantic.field_validator('my_int')
        @classmethod
        def validate_my_int(cls, my_int: int) -> int:
            if my_int < 0:
                raise ValueError('my_int must be zero or positive')
            return my_int

    class _MyPydanticDataclassConfigCharm(BaseTestConfigCharm):
        @property
        def config_class(self) -> type[_ConfigProtocol]:
            return MyPydanticDataclassConfig

    class MyPydanticBaseModelConfig(pydantic.BaseModel):
        my_bool: bool | None = pydantic.Field(None)
        my_int: int = pydantic.Field(42)
        my_float: float = pydantic.Field(3.14)
        my_str: str = pydantic.Field('foo')
        my_secret: ops.Secret | None = pydantic.Field(None)

        @pydantic.field_validator('my_int')
        @classmethod
        def validate_my_int(cls, my_int: int) -> int:
            if my_int < 0:
                raise ValueError('my_int must be zero or positive')
            return my_int

        model_config = pydantic.ConfigDict(frozen=True, arbitrary_types_allowed=True)

    class _MyPydanticBaseModelConfigCharm(BaseTestConfigCharm):
        @property
        def config_class(self) -> type[_ConfigProtocol]:
            return MyPydanticBaseModelConfig

    _test_config_classes.extend((_MyPydanticDataclassConfigCharm, _MyPydanticBaseModelConfigCharm))


_config = """
options:
    my-bool:
        type: boolean
    my-int:
        type: int
        default: 42
    my-float:
        type: float
        default: 3.14
    my-str:
        type: string
        default: foo
    my-secret:
        type: secret
"""


@pytest.mark.parametrize('charm_class', _test_config_classes)
def test_config_init(charm_class: type[BaseTestConfigCharm], request: pytest.FixtureRequest):
    harness = testing.Harness(charm_class, config=_config)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    typed_config = harness.charm.typed_config
    assert typed_config.my_bool is None
    assert typed_config.my_float == 3.14
    assert isinstance(typed_config.my_float, float)
    assert typed_config.my_int == 42
    assert isinstance(typed_config.my_int, int)
    assert typed_config.my_str == 'foo'
    assert isinstance(typed_config.my_str, str)
    assert typed_config.my_secret is None


@pytest.mark.parametrize('charm_class', _test_config_classes)
def test_config_init_non_default(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    harness = testing.Harness(charm_class, config=_config)
    request.addfinalizer(harness.cleanup)
    harness.update_config({
        'my-bool': True,
        'my-float': 2.71,
        'my-int': 24,
        'my-str': 'bar',
    })
    harness.begin()
    typed_config = harness.charm.typed_config  # type: ignore
    typed_config = typing.cast('_ConfigProtocol', typed_config)
    assert typed_config.my_bool is True
    assert typed_config.my_float == 2.71
    assert typed_config.my_int == 24
    assert typed_config.my_str == 'bar'
    assert typed_config.my_secret is None


@pytest.mark.parametrize(
    'errors,exc',
    (('raise', ValueError), ('blocked', ops._main._Abort), (None, ValueError)),
)
@pytest.mark.parametrize('charm_class', _test_config_classes)
def test_config_with_error_blocked(
    charm_class: type[ops.CharmBase],
    errors: typing.Literal['blocked', 'raise'] | None,
    exc: type[Exception],
    request: pytest.FixtureRequest,
):
    harness = testing.Harness(charm_class, config=_config)
    request.addfinalizer(harness.cleanup)
    charm_class._config_errors = errors  # type: ignore
    request.addfinalizer(lambda: setattr(charm_class, '_config_errors', None))
    harness.update_config({
        'my-int': -1,
    })
    with pytest.raises(exc):
        harness.begin()
    if errors == 'blocked':
        status_dict = harness._backend.status_get()
        assert status_dict['status'] == 'blocked'
        assert 'my_int must be zero or positive' in status_dict['message']


@pytest.mark.parametrize('charm_class', _test_config_classes)
def test_config_with_secret(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    harness = testing.Harness(charm_class, config=_config)
    request.addfinalizer(harness.cleanup)
    content = {'password': 'admin'}
    secret_id = harness.add_user_secret(content)
    harness.grant_secret(secret_id, harness.model.app.name)
    harness.update_config({
        'my-secret': secret_id,
    })
    harness.begin()
    typed_config = harness.charm.typed_config  # type: ignore
    typed_config = typing.cast('_ConfigProtocol', typed_config)
    secret = typed_config.my_secret
    assert secret is not None
    assert secret.id == secret_id
    assert secret.get_content() == content


def test_config_extra_args(request: pytest.FixtureRequest):
    @dataclasses.dataclass
    class Config:
        a: int
        b: float
        c: str

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(Config, 10, c='foo')

    schema = """
options:
    b:
        type: float
"""
    harness = testing.Harness(Charm, config=schema)
    request.addfinalizer(harness.cleanup)
    harness.update_config({'b': 3.14})
    harness.begin()
    typed_config = harness.charm.typed_config
    assert isinstance(typed_config, Config)
    assert typed_config.a == 10
    assert typed_config.b == 3.14
    assert typed_config.c == 'foo'


class SmallConfig:
    x: int

    # Note that for plain classes we do not try to determine the fields
    # and instead get all arguments.
    def __init__(self, x: int, **_):
        self.x = x


@dataclasses.dataclass(frozen=True)
class SmallDataclassConfig:
    x: int


_small_configs: list[type[object]] = [SmallConfig, SmallDataclassConfig]

if pydantic:

    @pydantic.dataclasses.dataclass(frozen=True)
    class SmallPydanticDataclassConfig:
        x: int

    class SmallPydanticBaseModelConfig(pydantic.BaseModel):
        x: int = pydantic.Field()

    _small_configs.extend((SmallPydanticDataclassConfig, SmallPydanticBaseModelConfig))


@pytest.mark.parametrize('config_class', _small_configs)
def test_config_partial_init(config_class: type[object], request: pytest.FixtureRequest):
    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(config_class)

    # Harness needs to know about *all* the options, even though the charm does not.
    schema = """
options:
    x:
        type: int
    y:
        type: string
        description: An int not used in the class
"""
    harness = testing.Harness(Charm, config=schema)
    request.addfinalizer(harness.cleanup)
    # The raw config contains more fields than the class requires.
    harness.update_config({'x': 42, 'y': 'foo'})
    harness.begin()
    typed_config = harness.charm.typed_config
    assert isinstance(typed_config, config_class)
    assert typed_config.x == 42  # type: ignore
    assert not hasattr(typed_config, 'y')


class MyAction:
    my_str: str
    my_bool: bool = False
    my_int: int = 42
    my_float: float = 3.14
    my_list: list[str] = []  # noqa: RUF012

    def __init__(
        self,
        *,
        my_str: typing.Any,
        my_bool: typing.Any = False,
        my_int: typing.Any = 42,
        my_float: typing.Any = 3.14,
        my_list: typing.Any = None,
    ):
        super().__init__()
        assert isinstance(my_bool, bool)
        self.my_bool = my_bool
        assert isinstance(my_float, float)
        self.my_float = my_float
        assert isinstance(my_float, float)
        assert isinstance(my_int, int)
        if my_int < 0:
            raise ValueError('my_int must be zero or positive')
        self.my_int = my_int
        assert isinstance(my_str, str)
        self.my_str = my_str
        if my_list is None:
            self.my_list = []
        else:
            assert isinstance(my_list, list)
            self.my_list = my_list


class BaseTestActionCharm(ops.CharmBase):
    errors: typing.Literal['fail', 'raise'] = 'fail'

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['my-action'].action, self._on_action)

    @property
    def action_class(self) -> type[MyAction]:
        raise NotImplementedError

    def _on_action(self, event: ops.ActionEvent):
        params = event.load_params(self.action_class, errors=self.errors)
        # These should not have any type errors.
        new_float = params.my_float + 2006.8
        new_int = params.my_int + 1979
        new_str = params.my_str + 'bar'
        new_list = params.my_list[:]
        event.log(f'{new_float=}, {new_int=}, {new_str=}, {new_list=}')
        event.set_results({'params': params})


class _MyActionCharm(BaseTestActionCharm):
    @property
    def action_class(self) -> type[MyAction]:
        return MyAction


@dataclasses.dataclass(frozen=True, kw_only=True)
class MyDataclassAction:
    my_str: str
    my_bool: bool = False
    my_int: int = 42
    my_float: float = 3.14
    my_list: list[str] = dataclasses.field(default_factory=list[str])

    def __post_init__(self):
        if self.my_int < 0:
            raise ValueError('my_int must be zero or positive')


class _MyDataclassActionCharm(BaseTestActionCharm):
    @property
    def action_class(self) -> type[MyDataclassAction]:
        return MyDataclassAction


_test_action_classes: list[type[ops.CharmBase]] = [_MyActionCharm, _MyDataclassActionCharm]

if pydantic:

    @pydantic.dataclasses.dataclass(frozen=True)
    class MyPydanticDataclassAction:
        my_str: str = pydantic.Field()
        my_bool: bool = pydantic.Field(False)
        my_int: int = pydantic.Field(42)
        my_float: float = pydantic.Field(3.14)
        my_list: list[str] = pydantic.Field(default_factory=list)

        @pydantic.field_validator('my_int')
        @classmethod
        def validate_my_int(cls, my_int: int) -> int:
            if my_int < 0:
                raise ValueError('my_int must be zero or positive')
            return my_int

    class _MyPydanticDataclassActionCharm(BaseTestActionCharm):
        @property
        def action_class(self) -> type[MyPydanticDataclassAction]:
            return MyPydanticDataclassAction

    class MyPydanticBaseModelAction(pydantic.BaseModel):
        my_str: str = pydantic.Field()
        my_bool: bool = pydantic.Field(False)
        my_int: int = pydantic.Field(42, ge=0)
        my_float: float = pydantic.Field(3.14)
        my_list: list[str] = pydantic.Field(default_factory=list)

        model_config = pydantic.ConfigDict(frozen=True)

    class _MyPydanticBaseModelActionCharm(BaseTestActionCharm):
        @property
        def action_class(self) -> type[MyPydanticBaseModelAction]:
            return MyPydanticBaseModelAction

    _test_action_classes.extend((_MyPydanticDataclassActionCharm, _MyPydanticBaseModelActionCharm))


@pytest.mark.parametrize('charm_class', _test_action_classes)
def test_action_init(
    charm_class: type[BaseTestActionCharm],
    request: pytest.FixtureRequest,
):
    action_yaml = """
my-action:
    params:
        my-str:
            type: string
        my-bool:
            type: boolean
            default: false
        my-int:
            type: integer
            default: 42
        my-float:
            type: float
            default: 3.14
        my-list:
            type: list
"""
    harness = testing.Harness(charm_class, actions=action_yaml)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params_out = harness.run_action('my-action', {'my-str': 'foo'}).results['params']
    assert params_out.my_bool is False
    assert params_out.my_float == 3.14
    assert isinstance(params_out.my_float, float)
    assert params_out.my_int == 42
    assert isinstance(params_out.my_int, int)
    assert params_out.my_str == 'foo'
    assert isinstance(params_out.my_str, str)
    assert params_out.my_list == []
    assert isinstance(params_out.my_list, list)


@pytest.mark.parametrize('charm_class', _test_action_classes)
def test_action_init_non_default(
    charm_class: type[BaseTestActionCharm],
    request: pytest.FixtureRequest,
):
    action_yaml = """
my-action:
    params:
        my-str:
            type: string
        my-bool:
            type: boolean
            default: false
        my-int:
            type: integer
            default: 42
        my-float:
            type: float
            default: 3.14
        my-list:
            type: list
"""
    harness = testing.Harness(charm_class, actions=action_yaml)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params_in = {
        'my-bool': True,
        'my-float': 2.71,
        'my-int': 24,
        'my-str': 'bar',
        'my-list': ['a', 'b', 'c'],
    }
    params_out = harness.run_action('my-action', params_in).results['params']
    assert params_out.my_bool is True
    assert params_out.my_float == 2.71
    assert params_out.my_int == 24
    assert params_out.my_str == 'bar'
    assert params_out.my_list == ['a', 'b', 'c']


@pytest.mark.parametrize('charm_class', _test_action_classes)
def test_action_with_error_fail(
    charm_class: type[BaseTestActionCharm],
    request: pytest.FixtureRequest,
):
    action_yaml = """
my-action:
    params:
        my-str:
            type: string
            default: foo
        my-int:
            type: integer
            default: 42
"""
    harness = testing.Harness(charm_class, actions=action_yaml)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    with pytest.raises(_Abort):
        harness.run_action('my-action', params={'my-str': 'foo', 'my-int': -1})
    # There should be a failure message, but we're not concerned with the exact
    # wording, which will differ between action classes.
    assert harness._backend._running_action.failure_message


@pytest.mark.parametrize('charm_class', _test_action_classes)
def test_action_with_error_raise(
    charm_class: type[BaseTestActionCharm],
    request: pytest.FixtureRequest,
):
    class RaiseCharm(charm_class):
        errors = 'raise'

    action_yaml = """
my-action:
    params:
        my-str:
            type: string
            default: foo
        my-int:
            type: integer
            default: 42
"""

    harness = testing.Harness(RaiseCharm, actions=action_yaml)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    with pytest.raises(ValueError):
        harness.run_action('my-action', params={'my-str': 'foo', 'my-int': -1})


class _Alias:  # noqa: B903
    def __init__(self, fooBar: int, other: str):  # noqa: N803
        self.foo_bar = fooBar
        self.other = other


@dataclasses.dataclass(frozen=True)
class _DataclassesAlias:
    foo_bar: int = dataclasses.field(default=42, metadata={'alias': 'fooBar'})
    other: str = 'baz'


_alias_action_classes: list[type[object]] = [_Alias, _DataclassesAlias]

if pydantic is not None:

    @pydantic.dataclasses.dataclass(frozen=True, init=False)
    class _PydanticDataclassesAlias:
        foo_bar: int = dataclasses.field(default=42, metadata={'alias': 'fooBar'})
        other: str = pydantic.Field(default='baz')

    class _PydanticBaseModelAlias(pydantic.BaseModel):
        foo_bar: int = pydantic.Field(42, alias='fooBar')
        other: str = pydantic.Field('baz')

    _alias_action_classes.extend([_PydanticDataclassesAlias, _PydanticBaseModelAlias])


@pytest.mark.parametrize('action_params', [{}, {'fooBar': 24}])
@pytest.mark.parametrize('action_class', _alias_action_classes)
def test_action_custom_naming_pattern(
    action_params: dict[str, int], action_class: type[object], request: pytest.FixtureRequest
):
    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['act'].action, self._on_action)

        def _on_action(self, event: ops.ActionEvent):
            params = event.load_params(action_class)
            event.set_results({'params': params})

    action_yaml = """
act:
    params:
        fooBar:
            type: int
            default: 42
        other:
            type: string
            default: baz
"""
    harness = testing.Harness(Charm, actions=action_yaml)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params_out = harness.run_action('act', action_params).results['params']
    assert params_out.foo_bar == action_params.get('fooBar', 42)
    assert params_out.other == 'baz'


def test_action_extra_args(request: pytest.FixtureRequest):
    @dataclasses.dataclass
    class Action:
        a: int
        b: float
        c: str

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['action'].action, self._on_action)

        def _on_action(self, event: ops.ActionEvent):
            params = event.load_params(Action, 10, c='foo')
            event.set_results({'params': params})

    action_yaml = """
action:
    params:
        b:
            type: float
"""
    harness = testing.Harness(Charm, actions=action_yaml)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params = harness.run_action('action', {'b': 3.14}).results['params']
    assert params.a == 10
    assert params.b == 3.14
    assert params.c == 'foo'


# Note that this test is based on the example in the actions how-to doc.
# Ideally, the configuration and charm classes are kept the same as in that
# doc, so that we are confident that the code we're recommending charmers
# write will actually work. This means that the test is a bit more verbose
# than otherwise, but not excessively so.
@pytest.mark.skipif(
    pydantic is None,
    reason='pydantic is not available, so we cannot test pydantic-based classes.',
)
def test_action_nested_with_enum(request: pytest.FixtureRequest):
    assert pydantic is not None

    class CompressionKind(enum.Enum):
        GZIP = 'gzip'
        BZIP = 'bzip2'
        XZ = 'xz'

    class Compression(pydantic.BaseModel):
        kind: CompressionKind = pydantic.Field(CompressionKind.BZIP)
        quality: int = pydantic.Field(5, description='Compression quality.', ge=0, le=9)

    class SnapshotAction(pydantic.BaseModel):
        """Take a snapshot of the database."""

        filename: str = pydantic.Field(description='The name of the snapshot file.')
        compression: Compression = pydantic.Field(  # type: ignore
            default_factory=Compression,  # type: ignore
            description='The type of compression to use.',
        )

    class DBCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['snapshot'].action, self._on_snapshot_action)

        def _on_snapshot_action(self, event: ops.ActionEvent):
            params = event.load_params(SnapshotAction, errors='raise')
            event.log(f'Generating snapshot into {params.filename}')
            success = self.do_snapshot(
                filename=params.filename,
                kind=params.compression.kind,
                quality=params.compression.quality,
            )
            if not success:
                event.fail('Failed to generate snapshot.')
                return
            msg = f'Stored snapshot in {params.filename}.'
            event.set_results({'result': msg})

        def do_snapshot(self, filename: str, kind: CompressionKind, quality: int) -> bool:
            self.snapped = [filename, kind, quality]
            return True

    action_yaml = """
snapshot:
    description: Take a snapshot of the database.
    params:
        filename:
            type: string
            description: The name of the snapshot file.
        compression:
            type: object
            description: The type of compression to use.
            properties:
                kind:
                    type: string
                    enum:
                    - gzip
                    - bzip2
                    - xz
                    default: gzip
                quality:
                    description: Compression quality
                    type: integer
                    default: 5
                    minimum: 0
                    maximum: 9
    required:
    - filename
    additionalProperties: false
"""

    harness = testing.Harness(DBCharm, actions=action_yaml)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    # Snapshot with the defaults.
    out = harness.run_action('snapshot', {'filename': 'snap.bz2'})
    assert out.results['result'] == 'Stored snapshot in snap.bz2.'
    assert harness.charm.snapped == ['snap.bz2', CompressionKind.BZIP, 5]
    # Snapshot with custom values.
    out = harness.run_action(
        'snapshot',
        {
            'filename': 'snap.gz',
            'compression': {'kind': 'gzip', 'quality': 7},
        },
    )
    assert out.results['result'] == 'Stored snapshot in snap.gz.'
    assert harness.charm.snapped == ['snap.gz', CompressionKind.GZIP, 7]
    # Snapshot with an invalid compression kind.
    with pytest.raises(ValueError):
        harness.run_action(
            'snapshot',
            {
                'filename': 'snap.zip',
                'compression': {'kind': 'zip'},
            },
        )
    # Snapshot with an invalid compression quality.
    with pytest.raises(ValueError):
        harness.run_action(
            'snapshot',
            {
                'filename': 'snap.xz',
                'compression': {'kind': 'xz', 'quality': 10},
            },
        )
