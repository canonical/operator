# Copyright 2023 Canonical Ltd.
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

import unittest

from ops import model
from ops.charm import (
    CharmBase,
    SecretChangedEvent,
    SecretRemoveEvent,
    SecretRotateEvent,
)
from ops.testing import Harness


class TestSecrets(unittest.TestCase):
    def test_add_model_secret_by_app_name_str(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        self.assertEqual(secret.id, secret_id)
        self.assertEqual(secret.get_content(), {'password': 'hunter2'})

    def test_add_model_secret_by_app_instance(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        app = harness.model.get_app('database')
        secret_id = harness.add_model_secret(app, {'password': 'hunter3'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        self.assertEqual(secret.id, secret_id)
        self.assertEqual(secret.get_content(), {'password': 'hunter3'})

    def test_add_model_secret_by_unit_instance(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        unit = harness.model.get_unit('database/0')
        secret_id = harness.add_model_secret(unit, {'password': 'hunter4'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        self.assertEqual(secret.id, secret_id)
        self.assertEqual(secret.get_content(), {'password': 'hunter4'})

    def test_add_model_secret_invalid_content(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)

        with self.assertRaises(ValueError):
            harness.add_model_secret('database', {'x': 'y'})  # key too short

    def test_set_secret_content(self):
        harness = Harness(EventRecorder, meta='name: webapp')
        self.addCleanup(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'foo': '1'})
        harness.grant_secret(secret_id, 'webapp')
        harness.begin()
        harness.framework.observe(harness.charm.on.secret_changed, harness.charm.record_event)
        harness.set_secret_content(secret_id, {'foo': '2'})

        self.assertEqual(len(harness.charm.events), 1)
        event = harness.charm.events[0]
        self.assertIsInstance(event, SecretChangedEvent)
        self.assertEqual(event.secret.get_content(), {'foo': '1'})
        self.assertEqual(event.secret.get_content(refresh=True), {'foo': '2'})
        self.assertEqual(event.secret.get_content(), {'foo': '2'})

        self.assertEqual(harness.get_secret_revisions(secret_id), [1, 2])

    def test_set_secret_content_wrong_owner(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)

        secret = harness.model.app.add_secret({'foo': 'bar'})
        with self.assertRaises(RuntimeError):
            harness.set_secret_content(secret.id, {'bar': 'foo'})

    def test_set_secret_content_invalid_secret_id(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)

        with self.assertRaises(RuntimeError):
            harness.set_secret_content('asdf', {'foo': 'bar'})

    def test_set_secret_content_invalid_content(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)

        secret_id = harness.add_model_secret('database', {'foo': 'bar'})
        with self.assertRaises(ValueError):
            harness.set_secret_content(secret_id, {'x': 'y'})

    def test_grant_secret_and_revoke_secret(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        self.assertEqual(secret.id, secret_id)
        self.assertEqual(secret.get_content(), {'password': 'hunter2'})

        harness.revoke_secret(secret_id, 'webapp')
        with self.assertRaises(model.SecretNotFoundError):
            harness.model.get_secret(id=secret_id)

    def test_grant_secret_wrong_app(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        harness.grant_secret(secret_id, 'otherapp')
        with self.assertRaises(model.SecretNotFoundError):
            harness.model.get_secret(id=secret_id)

    def test_grant_secret_wrong_unit(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        harness.grant_secret(secret_id, 'webapp/1')  # should be webapp/0
        with self.assertRaises(model.SecretNotFoundError):
            harness.model.get_secret(id=secret_id)

    def test_grant_secret_no_relation(self):
        harness = Harness(CharmBase, meta='name: webapp')
        self.addCleanup(harness.cleanup)

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        with self.assertRaises(RuntimeError):
            harness.grant_secret(secret_id, 'webapp')

    def test_get_secret_grants(self):
        harness = Harness(CharmBase, meta='name: database')
        self.addCleanup(harness.cleanup)

        relation_id = harness.add_relation('db', 'webapp')
        harness.add_relation_unit(relation_id, 'webapp/0')

        secret = harness.model.app.add_secret({'foo': 'x'})
        self.assertEqual(harness.get_secret_grants(secret.id, relation_id), set())
        secret.grant(harness.model.get_relation('db'))
        self.assertEqual(harness.get_secret_grants(secret.id, relation_id), {'webapp'})

        secret.revoke(harness.model.get_relation('db'))
        self.assertEqual(harness.get_secret_grants(secret.id, relation_id), set())
        secret.grant(harness.model.get_relation('db'), unit=harness.model.get_unit('webapp/0'))
        self.assertEqual(harness.get_secret_grants(secret.id, relation_id), {'webapp/0'})

    def test_trigger_secret_rotation(self):
        harness = Harness(EventRecorder, meta='name: database')
        self.addCleanup(harness.cleanup)

        secret = harness.model.app.add_secret({'foo': 'x'}, label='lbl')
        harness.begin()
        harness.framework.observe(harness.charm.on.secret_rotate, harness.charm.record_event)
        harness.trigger_secret_rotation(secret.id)
        harness.trigger_secret_rotation(secret.id, label='override')

        self.assertEqual(len(harness.charm.events), 2)
        event = harness.charm.events[0]
        self.assertIsInstance(event, SecretRotateEvent)
        self.assertEqual(event.secret.label, 'lbl')
        self.assertEqual(event.secret.get_content(), {'foo': 'x'})
        event = harness.charm.events[1]
        self.assertIsInstance(event, SecretRotateEvent)
        self.assertEqual(event.secret.label, 'override')
        self.assertEqual(event.secret.get_content(), {'foo': 'x'})

        with self.assertRaises(RuntimeError):
            harness.trigger_secret_rotation('nosecret')

    def test_trigger_secret_removal(self):
        harness = Harness(EventRecorder, meta='name: database')
        self.addCleanup(harness.cleanup)

        secret = harness.model.app.add_secret({'foo': 'x'}, label='lbl')
        harness.begin()
        harness.framework.observe(harness.charm.on.secret_remove, harness.charm.record_event)
        harness.trigger_secret_removal(secret.id, 1)
        harness.trigger_secret_removal(secret.id, 42, label='override')

        self.assertEqual(len(harness.charm.events), 2)
        event = harness.charm.events[0]
        self.assertIsInstance(event, SecretRemoveEvent)
        self.assertEqual(event.secret.label, 'lbl')
        self.assertEqual(event.revision, 1)
        self.assertEqual(event.secret.get_content(), {'foo': 'x'})
        event = harness.charm.events[1]
        self.assertIsInstance(event, SecretRemoveEvent)
        self.assertEqual(event.secret.label, 'override')
        self.assertEqual(event.revision, 42)
        self.assertEqual(event.secret.get_content(), {'foo': 'x'})

        with self.assertRaises(RuntimeError):
            harness.trigger_secret_removal('nosecret', 1)

    def test_trigger_secret_expiration(self):
        harness = Harness(EventRecorder, meta='name: database')
        self.addCleanup(harness.cleanup)

        secret = harness.model.app.add_secret({'foo': 'x'}, label='lbl')
        harness.begin()
        harness.framework.observe(harness.charm.on.secret_remove, harness.charm.record_event)
        harness.trigger_secret_removal(secret.id, 1)
        harness.trigger_secret_removal(secret.id, 42, label='override')

        self.assertEqual(len(harness.charm.events), 2)
        event = harness.charm.events[0]
        self.assertIsInstance(event, SecretRemoveEvent)
        self.assertEqual(event.secret.label, 'lbl')
        self.assertEqual(event.revision, 1)
        self.assertEqual(event.secret.get_content(), {'foo': 'x'})
        event = harness.charm.events[1]
        self.assertIsInstance(event, SecretRemoveEvent)
        self.assertEqual(event.secret.label, 'override')
        self.assertEqual(event.revision, 42)
        self.assertEqual(event.secret.get_content(), {'foo': 'x'})

        with self.assertRaises(RuntimeError):
            harness.trigger_secret_removal('nosecret', 1)


class EventRecorder(CharmBase):
    def __init__(self, framework):
        super().__init__(framework)
        self.events = []

    def record_event(self, event):
        self.events.append(event)
