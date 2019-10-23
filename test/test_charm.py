#!/usr/bin/python3

import os
import unittest
import tempfile
import shutil

from pathlib import Path

from juju.charm import CharmBase, CharmMeta
from juju.charm import CharmEvents
from juju.framework import Framework, Event, EventBase
from juju.model import DeadRelation, Model, ModelBackend


class TestCharm(unittest.TestCase):

    def setUp(self):
        self._path = os.environ['PATH']
        os.environ['PATH'] = str(Path(__file__).parent / 'bin')
        self.tmpdir = Path(tempfile.mkdtemp())
        self.meta = CharmMeta()

        class CustomEvent(EventBase):
            pass

        class TestCharmEvents(CharmEvents):
            custom = Event(CustomEvent)

        # Relations events are defined dynamically and modify the class attributes.
        # We use a subclass temporarily to prevent these side effects from leaking.
        CharmBase.on = TestCharmEvents()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        os.environ['PATH'] = self._path

        CharmBase.on = CharmEvents()

    def create_framework(self):
        model = Model('local/0', list(self.meta.relations), ModelBackend())
        framework = Framework(self.tmpdir / "framework.data", self.tmpdir, self.meta, model)
        self.addCleanup(framework.close)
        return framework

    def test_basic(self):

        class MyCharm(CharmBase):

            def __init__(self, *args):
                super().__init__(*args)

                self.started = False
                framework.observe(self.on.start, self)

            def on_start(self, event):
                self.started = True

        events = list(MyCharm.on.events())
        self.assertIn('install', events)
        self.assertIn('custom', events)

        framework = self.create_framework()
        charm = MyCharm(framework, None)
        charm.on.start.emit()

        self.assertEqual(charm.started, True)

    def test_relation_events(self):

        class MyCharm(CharmBase):
            def __init__(self, *args):
                super().__init__(*args)
                self.seen = []
                for event_kind, bound_event in self.on.events().items():
                    # hook up relation events to generic handler
                    if 'relation' in event_kind:
                        self.framework.observe(bound_event, self.on_any_relation)

            def on_any_relation(self, event):
                assert event.relation.name == 'req1'
                self.seen.append(f'{type(event).__name__}')

        self.meta = CharmMeta({
            'name': 'my-charm',
            'requires': {
                'req1': {'interface': 'req1'},
                'req-2': {'interface': 'req2'},
            },
            'provides': {
                'pro1': {'interface': 'pro1'},
                'pro-2': {'interface': 'pro2'},
            },
            'peers': {
                'peer1': {'interface': 'peer1'},
                'peer-2': {'interface': 'peer2'},
            },
        })

        charm = MyCharm(self.create_framework(), None)

        rel = DeadRelation('req1', '0')
        unit = charm.framework.model.get_unit('app/0')
        charm.on.req1_relation_joined.emit(rel, unit)
        charm.on.req1_relation_changed.emit(rel, unit)
        charm.on.req_2_relation_changed.emit(rel, unit)
        charm.on.pro1_relation_departed.emit(rel, unit)
        charm.on.pro_2_relation_departed.emit(rel, unit)
        charm.on.peer1_relation_broken.emit(rel)
        charm.on.peer_2_relation_broken.emit(rel)

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
                self.framework.observe(self.on.stor1_storage_attached, self)
                self.framework.observe(self.on.stor2_storage_detaching, self)
                self.framework.observe(self.on.stor3_storage_attached, self)
                self.framework.observe(self.on.stor_4_storage_attached, self)

            def on_stor1_storage_attached(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor2_storage_detaching(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor3_storage_attached(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor_4_storage_attached(self, event):
                self.seen.append(f'{type(event).__name__}')

        self.meta = CharmMeta({
            'name': 'my-charm',
            'storage': {
                'stor1': {'type': 'filesystem'},
                'stor2': {
                    'type': 'filesystem',
                    'multiple': {
                        'range': '2',
                    },
                },
                'stor3': {
                    'type': 'filesystem',
                    'multiple': {
                        'range': '2-',
                    },
                },
                'stor-4': {
                    'type': 'filesystem',
                    'multiple': {
                        'range': '2-4',
                    },
                },
            },
        })

        self.assertIsNone(self.meta.storage['stor1'].multiple_range)
        self.assertEqual(self.meta.storage['stor2'].multiple_range, (2, 2))
        self.assertEqual(self.meta.storage['stor3'].multiple_range, (2, None))
        self.assertEqual(self.meta.storage['stor-4'].multiple_range, (2, 4))

        charm = MyCharm(self.create_framework(), None)

        charm.on.stor1_storage_attached.emit()
        charm.on.stor2_storage_detaching.emit()
        charm.on.stor3_storage_attached.emit()
        charm.on.stor_4_storage_attached.emit()

        self.assertEqual(charm.seen, [
            'StorageAttachedEvent',
            'StorageDetachingEvent',
            'StorageAttachedEvent',
            'StorageAttachedEvent',
        ])


if __name__ == "__main__":
    unittest.main()
