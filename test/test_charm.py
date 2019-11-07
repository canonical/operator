#!/usr/bin/python3

import os
import unittest
import tempfile
import shutil

from pathlib import Path

from juju.charm import CharmBase, CharmMeta
from juju.charm import CharmEvents
from juju.framework import Framework, Event, EventBase
from juju.model import Model, ModelBackend


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
        model = Model('local/0', list(self.meta.endpoints), ModelBackend())
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
                for endpoints in self.endpoints.values():
                    # hook up relation events to generic handler
                    self.framework.observe(endpoints.on.joined, self.on_any)
                    self.framework.observe(endpoints.on.changed, self.on_any)
                    self.framework.observe(endpoints.on.departed, self.on_any)
                    self.framework.observe(endpoints.on.broken, self.on_any)

            def on_any(self, event):
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

        rel = charm.framework.model.get_relation('req1', 0)
        unit = charm.framework.model.get_unit('app/0')
        charm.endpoints['req1'].on.joined.emit(rel, unit)
        charm.endpoints['req1'].on.changed.emit(rel, unit)
        charm.endpoints['req-2'].on.changed.emit(rel, unit)
        charm.endpoints['pro1'].on.departed.emit(rel, unit)
        charm.endpoints['pro-2'].on.departed.emit(rel, unit)
        charm.endpoints['peer1'].on.broken.emit(rel)
        charm.endpoints['peer-2'].on.broken.emit(rel)

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
                self.framework.observe(self.storage['stor1'].on.attached, self.on_stor1_attached)
                self.framework.observe(self.storage['stor2'].on.detaching, self.on_stor2_detaching)
                self.framework.observe(self.storage['stor3'].on.attached, self.on_stor3_attached)
                self.framework.observe(self.storage['stor-4'].on.attached, self.on_stor_4_attached)

            def on_stor1_attached(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor2_detaching(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor3_attached(self, event):
                self.seen.append(f'{type(event).__name__}')

            def on_stor_4_attached(self, event):
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

        charm.storage['stor1'].on.attached.emit()
        charm.storage['stor2'].on.detaching.emit()
        charm.storage['stor3'].on.attached.emit()
        charm.storage['stor-4'].on.attached.emit()

        self.assertEqual(charm.seen, [
            'StorageAttachedEvent',
            'StorageDetachingEvent',
            'StorageAttachedEvent',
            'StorageAttachedEvent',
        ])


if __name__ == "__main__":
    unittest.main()
