# Copyright 2019-2020 Canonical Ltd.
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

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from ops.charm import (
    CharmBase,
    CharmEvents,
    CharmMeta,
    CloudEventReceivedEvent,
    ContainerMeta,
)
from ops.framework import EventBase, EventSource, Framework
from ops.model import Model, ModelError, _ModelBackend
from ops.storage import SQLiteStorage

from .test_helpers import fake_script, fake_script_calls


class TestCharm(unittest.TestCase):

    def setUp(self):
        def restore_env(env):
            os.environ.clear()
            os.environ.update(env)
        self.addCleanup(restore_env, os.environ.copy())

        os.environ['PATH'] = os.pathsep.join([
            str(Path(__file__).parent / 'bin'),
            os.environ['PATH']])
        os.environ['JUJU_UNIT_NAME'] = 'local/0'

        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmpdir))
        self.meta = CharmMeta()

        class CustomEvent(EventBase):
            pass

        class TestCharmEvents(CharmEvents):
            custom = EventSource(CustomEvent)

        # Relations events are defined dynamically and modify the class attributes.
        # We use a subclass temporarily to prevent these side effects from leaking.
        CharmBase.on = TestCharmEvents()

        def cleanup():
            CharmBase.on = CharmEvents()
        self.addCleanup(cleanup)

    def create_framework(self):
        model = Model(self.meta, _ModelBackend('local/0'))
        framework = Framework(SQLiteStorage(':memory:'), self.tmpdir, self.meta, model)
        self.addCleanup(framework.close)
        return framework

    def test_basic(self):

        class MyCharm(CharmBase):

            def __init__(self, *args):
                super().__init__(*args)

                self.started = False
                framework.observe(self.on.start, self._on_start)

            def _on_start(self, event):
                self.started = True

        events = list(MyCharm.on.events())
        self.assertIn('install', events)
        self.assertIn('custom', events)

        framework = self.create_framework()
        charm = MyCharm(framework)
        charm.on.start.emit()

        self.assertEqual(charm.started, True)

        with self.assertRaisesRegex(TypeError, "observer methods must now be explicitly provided"):
            framework.observe(charm.on.start, charm)

    def test_empty_action(self):
        meta = CharmMeta.from_yaml('name: my-charm', '')
        self.assertEqual(meta.actions, {})

    def test_helper_properties(self):
        framework = self.create_framework()

        class MyCharm(CharmBase):
            pass

        charm = MyCharm(framework)
        self.assertEqual(charm.app, framework.model.app)
        self.assertEqual(charm.unit, framework.model.unit)
        self.assertEqual(charm.meta, framework.meta)
        self.assertEqual(charm.charm_dir, framework.charm_dir)
        self.assertIs(charm.config, framework.model.config)

    def test_relation_events(self):

        class MyCharm(CharmBase):
            def __init__(self, *args):
                super().__init__(*args)
                self.seen = []
                for rel in ('req1', 'req-2', 'pro1', 'pro-2', 'peer1', 'peer-2'):
                    # Hook up relation events to generic handler.
                    self.framework.observe(self.on[rel].relation_joined, self.on_any_relation)
                    self.framework.observe(self.on[rel].relation_changed, self.on_any_relation)
                    self.framework.observe(self.on[rel].relation_departed, self.on_any_relation)
                    self.framework.observe(self.on[rel].relation_broken, self.on_any_relation)

            def on_any_relation(self, event):
                assert event.relation.name == 'req1'
                assert event.relation.app.name == 'remote'
                self.seen.append(type(event).__name__)

        # language=YAML
        self.meta = CharmMeta.from_yaml(metadata='''
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
''')

        charm = MyCharm(self.create_framework())

        self.assertIn('pro_2_relation_broken', repr(charm.on))

        rel = charm.framework.model.get_relation('req1', 1)
        unit = charm.framework.model.get_unit('remote/0')
        charm.on['req1'].relation_joined.emit(rel, unit)
        charm.on['req1'].relation_changed.emit(rel, unit)
        charm.on['req-2'].relation_changed.emit(rel, unit)
        charm.on['pro1'].relation_departed.emit(rel, unit)
        charm.on['pro-2'].relation_departed.emit(rel, unit)
        charm.on['peer1'].relation_broken.emit(rel)
        charm.on['peer-2'].relation_broken.emit(rel)

        self.assertEqual(charm.seen, [
            'RelationJoinedEvent',
            'RelationChangedEvent',
            'RelationChangedEvent',
            'RelationDepartedEvent',
            'RelationDepartedEvent',
            'RelationBrokenEvent',
            'RelationBrokenEvent',
        ])

    def test_storage_events(self):

        class MyCharm(CharmBase):
            def __init__(self, *args):
                super().__init__(*args)
                self.seen = []
                self.framework.observe(self.on['stor1'].storage_attached, self._on_stor1_attach)
                self.framework.observe(self.on['stor2'].storage_detaching, self._on_stor2_detach)
                self.framework.observe(self.on['stor3'].storage_attached, self._on_stor3_attach)
                self.framework.observe(self.on['stor-4'].storage_attached, self._on_stor4_attach)

            def _on_stor1_attach(self, event):
                self.seen.append(type(event).__name__)

            def _on_stor2_detach(self, event):
                self.seen.append(type(event).__name__)

            def _on_stor3_attach(self, event):
                self.seen.append(type(event).__name__)

            def _on_stor4_attach(self, event):
                self.seen.append(type(event).__name__)

        # language=YAML
        self.meta = CharmMeta.from_yaml('''
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
''')

        self.assertIsNone(self.meta.storages['stor1'].multiple_range)
        self.assertEqual(self.meta.storages['stor2'].multiple_range, (2, 2))
        self.assertEqual(self.meta.storages['stor3'].multiple_range, (2, None))
        self.assertEqual(self.meta.storages['stor-4'].multiple_range, (2, 4))

        charm = MyCharm(self.create_framework())

        charm.on['stor1'].storage_attached.emit()
        charm.on['stor2'].storage_detaching.emit()
        charm.on['stor3'].storage_attached.emit()
        charm.on['stor-4'].storage_attached.emit()

        self.assertEqual(charm.seen, [
            'StorageAttachedEvent',
            'StorageDetachingEvent',
            'StorageAttachedEvent',
            'StorageAttachedEvent',
        ])

    def test_workload_events(self):

        class MyCharm(CharmBase):
            def __init__(self, *args):
                super().__init__(*args)
                self.seen = []
                self.count = 0
                for workload in ('container-a', 'containerb'):
                    # Hook up relation events to generic handler.
                    self.framework.observe(
                        self.on[workload].pebble_ready,
                        self.on_any_pebble_ready)

            def on_any_pebble_ready(self, event):
                self.seen.append(type(event).__name__)
                self.count += 1

        # language=YAML
        self.meta = CharmMeta.from_yaml(metadata='''
name: my-charm
containers:
  container-a:
  containerb:
''')

        charm = MyCharm(self.create_framework())

        self.assertIn('container_a_pebble_ready', repr(charm.on))
        self.assertIn('containerb_pebble_ready', repr(charm.on))

        charm.on['container-a'].pebble_ready.emit(
            charm.framework.model.unit.get_container('container-a'))
        charm.on['containerb'].pebble_ready.emit(
            charm.framework.model.unit.get_container('containerb'))

        self.assertEqual(charm.seen, [
            'PebbleReadyEvent',
            'PebbleReadyEvent'
        ])
        self.assertEqual(charm.count, 2)

    @classmethod
    def _get_action_test_meta(cls):
        # language=YAML
        return CharmMeta.from_yaml(metadata='''
name: my-charm
''', actions='''
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
''')

    def test_cloud_event_events(self):
        class MyCharm(CharmBase):
            def __init__(self, *args):
                super().__init__(*args)
                self.event_types = []
                self.count = 0

                self.framework.observe(
                    self.on.cloud_event_received(
                        'foo', resource_type='configmap', resource_name='cm-foo',
                    ),
                    self._on_foo_cloud_event_received,
                )
                self.framework.observe(
                    self.on.cloud_event_received(
                        'bar', resource_type='configmap', resource_name='cm-bar',
                    ),
                    self._on_bar_cloud_event_received,
                )

            def _on_foo_cloud_event_received(self, event):
                assert isinstance(event, CloudEventReceivedEvent)
                assert event.cloud_event_id == 'foo'
                self.event_types.append(type(event).__name__)
                self.count += 1
                assert event.events == expected_events
                event.stop_watch()

            def _on_bar_cloud_event_received(self, event):
                assert isinstance(event, CloudEventReceivedEvent)
                assert event.cloud_event_id == 'bar'
                self.event_types.append(type(event).__name__)
                self.count += 1
                assert event.events == expected_events
                event.stop_watch()

        fake_script(self, 'register-cloud-event', 'exit 0')
        fake_script(self, 'unregister-cloud-event', 'exit 0')
        fake_script(self, 'is-leader', 'echo true')
        expected_events = [
            dict(
                type='CREATED',
                message='The resource has been created successfully.',
                event_time=datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            ),
        ]
        fake_script(self, 'cloud-event-get', "echo '{}'".format(json.dumps(expected_events)))

        charm = MyCharm(self.create_framework())
        self.assertEqual(charm.count, 0)

        self.assertIn('foo_cloud_event_received', repr(charm.on))
        self.assertIn('bar_cloud_event_received', repr(charm.on))

        charm.on.foo_cloud_event_received.emit('foo')
        self.assertEqual(charm.count, 1)
        charm.on.bar_cloud_event_received.emit('bar')
        self.assertEqual(charm.count, 2)

        self.assertEqual(charm.event_types, [
            'CloudEventReceivedEvent',
            'CloudEventReceivedEvent'
        ])

        # all good for leader.
        charm.start_watch_cloud_event('foo', 'configmap', 'cm-foo')
        charm.stop_watch_cloud_event('foo')

        fake_script(self, 'is-leader', 'echo false')
        charm.framework.model._backend._is_leader = None
        charm.start_watch_cloud_event('foo', 'configmap', 'cm-foo')  # no ops for non leader.
        with self.assertRaisesRegex(
            ModelError, 'cannot unregister watched cloud event as this unit is not a leader',
        ):
            charm.stop_watch_cloud_event('foo')
        self.assertEqual(
            fake_script_calls(self, clear=True),
            [
                ['is-leader', '--format=json'],
                ['register-cloud-event', 'foo', '--resource_type',
                    'configmap', '--resource_name', 'cm-foo'],
                ['register-cloud-event', 'bar', '--resource_type',
                    'configmap', '--resource_name', 'cm-bar'],
                ['cloud-event-get', 'foo', '--format=json'],
                ['unregister-cloud-event', 'foo'],  # event.stop_watch()
                ['cloud-event-get', 'bar', '--format=json'],
                ['unregister-cloud-event', 'bar'],  # event.stop_watch()
                ['register-cloud-event', 'foo', '--resource_type',
                    'configmap', '--resource_name', 'cm-foo'],  # charm.start_watch_cloud_event
                ['unregister-cloud-event', 'foo'],  # charm.stop_watch_cloud_event
                ['is-leader', '--format=json'],
            ],
        )

    def _test_action_events(self, cmd_type):

        class MyCharm(CharmBase):

            def __init__(self, *args):
                super().__init__(*args)
                framework.observe(self.on.foo_bar_action, self._on_foo_bar_action)
                framework.observe(self.on.start_action, self._on_start_action)

            def _on_foo_bar_action(self, event):
                self.seen_action_params = event.params
                event.log('test-log')
                event.set_results({'res': 'val with spaces'})
                event.fail('test-fail')

            def _on_start_action(self, event):
                pass

        fake_script(self, cmd_type + '-get', """echo '{"foo-name": "name", "silent": true}'""")
        fake_script(self, cmd_type + '-set', "")
        fake_script(self, cmd_type + '-log', "")
        fake_script(self, cmd_type + '-fail', "")
        self.meta = self._get_action_test_meta()

        os.environ['JUJU_{}_NAME'.format(cmd_type.upper())] = 'foo-bar'
        framework = self.create_framework()
        charm = MyCharm(framework)

        events = list(MyCharm.on.events())
        self.assertIn('foo_bar_action', events)
        self.assertIn('start_action', events)

        charm.on.foo_bar_action.emit()
        self.assertEqual(charm.seen_action_params, {"foo-name": "name", "silent": True})
        self.assertEqual(fake_script_calls(self), [
            [cmd_type + '-get', '--format=json'],
            [cmd_type + '-log', "test-log"],
            [cmd_type + '-set', "res=val with spaces"],
            [cmd_type + '-fail', "test-fail"],
        ])

        # Make sure that action events that do not match the current context are
        # not possible to emit by hand.
        with self.assertRaises(RuntimeError):
            charm.on.start_action.emit()

    def test_action_events(self):
        self._test_action_events('action')

    def _test_action_event_defer_fails(self, cmd_type):

        class MyCharm(CharmBase):

            def __init__(self, *args):
                super().__init__(*args)
                framework.observe(self.on.start_action, self._on_start_action)

            def _on_start_action(self, event):
                event.defer()

        fake_script(self, cmd_type + '-get', """echo '{"foo-name": "name", "silent": true}'""")
        self.meta = self._get_action_test_meta()

        os.environ['JUJU_{}_NAME'.format(cmd_type.upper())] = 'start'
        framework = self.create_framework()
        charm = MyCharm(framework)

        with self.assertRaises(RuntimeError):
            charm.on.start_action.emit()

    def test_action_event_defer_fails(self):
        self._test_action_event_defer_fails('action')

    def test_containers(self):
        meta = CharmMeta.from_yaml("""
name: k8s-charm
containers:
  test1:
    k: v
  test2:
    k: v
""")
        self.assertIsInstance(meta.containers['test1'], ContainerMeta)
        self.assertIsInstance(meta.containers['test2'], ContainerMeta)
        self.assertEqual(meta.containers['test1'].name, 'test1')
        self.assertEqual(meta.containers['test2'].name, 'test2')
