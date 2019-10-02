#!/usr/bin/python3

import unittest
import tempfile
import shutil

from pathlib import Path

from juju.charm import CharmBase
from juju.framework import Framework


class TestCharm(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def create_framework(self):
        return Framework(self.tmpdir / "framework.data")

    def test_basic(self):

        class MyCharm(CharmBase):

            def __init__(self, metadata, framework, key):
                super().__init__(metadata, framework, key)

                self.started = False
                framework.observe(self.on.start, self)

            def on_start(self, event):
                self.started = True

        framework = self.create_framework()
        charm = MyCharm({}, framework, None)
        charm.on.start.emit()

        self.assertEqual(charm.started, True)

    def test_dynamic(self):

        class MyCharm(CharmBase):
            def __init__(self, metadata, framework, key):
                super().__init__(metadata, framework, key)
                self.seen = []
                for event_kind, bound_event in self.on.events():
                    framework.observe(bound_event, self.on_any)

            def on_any(self, event):
                self.seen.append(f'{type(event).__name__} on {event.name}')

        metadata = {
            'name': 'my-charm',
            'requires': {
                'req1': {'interface': 'req1'},
                'req2': {'interface': 'req2'},
            },
            'provides': {
                'pro1': {'interface': 'pro1'},
                'pro2': {'interface': 'pro2'},
            },
            'peers': {
                'peer1': {'interface': 'peer1'},
            },
            'storage': {
                'stor1': {'type': 'filesystem'},
                'stor2': {'type': 'filesystem'},
            },
        }

        charm = MyCharm(metadata, self.create_framework(), None)

        charm.on.req1_relation_joined.emit('req1')
        charm.on.req1_relation_changed.emit('req1')
        charm.on.req2_relation_changed.emit('req2')
        charm.on.pro1_relation_departed.emit('pro1')
        charm.on.peer1_relation_broken.emit('peer1')
        charm.on.stor1_storage_attached.emit('stor1')
        charm.on.stor2_storage_detaching.emit('stor2')

        self.assertEqual(charm.seen, [
            'RelationJoinedEvent on req1',
            'RelationChangedEvent on req1',
            'RelationChangedEvent on req2',
            'RelationDepartedEvent on pro1',
            'RelationBrokenEvent on peer1',
            'StorageAttachedEvent on stor1',
            'StorageDetachingEvent on stor2',
        ])


if __name__ == "__main__":
    unittest.main()
