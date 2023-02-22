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
import uuid

from ops.charm import CharmBase
from ops.model import ModelError, RelationNotFoundError, _ModelBackend
from ops.testing import Harness, _TestingPebbleClient

from .common import get_public_methods


class TestTestingModelBackend(unittest.TestCase):
    def test_conforms_to_model_backend(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        mb_methods = get_public_methods(_ModelBackend)
        backend_methods = get_public_methods(backend)
        self.assertEqual(mb_methods, backend_methods)

    def test_model_uuid_is_uuid_v4(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
        ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        self.assertEqual(uuid.UUID(backend.model_uuid).version, 4)

    def test_status_set_get_unit(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        backend.status_set('blocked', 'message', is_app=False)
        self.assertEqual(
            backend.status_get(is_app=False),
            {'status': 'blocked', 'message': 'message'})
        self.assertEqual(
            backend.status_get(is_app=True),
            {'status': 'unknown', 'message': ''})

    def test_status_set_get_app(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        backend.status_set('blocked', 'message', is_app=True)
        self.assertEqual(
            backend.status_get(is_app=True),
            {'status': 'blocked', 'message': 'message'})
        self.assertEqual(
            backend.status_get(is_app=False),
            {'status': 'maintenance', 'message': ''})

    def test_relation_ids_unknown_relation(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            provides:
              db:
                interface: mydb
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        # With no relations added, we just get an empty list for the interface
        self.assertEqual(backend.relation_ids('db'), [])
        # But an unknown interface raises a ModelError
        with self.assertRaises(ModelError):
            backend.relation_ids('unknown')

    def test_relation_get_unknown_relation_id(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        with self.assertRaises(RelationNotFoundError):
            backend.relation_get(1234, 'unit/0', False)

    def test_relation_list_unknown_relation_id(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        with self.assertRaises(RelationNotFoundError):
            backend.relation_list(1234)

    def test_lazy_resource_directory(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        harness.populate_oci_resources()
        backend = harness._backend
        self.assertIsNone(backend._resource_dir)
        path = backend.resource_get('image')
        self.assertIsNotNone(backend._resource_dir)
        self.assertTrue(
            str(path).startswith(str(backend._resource_dir.name)),
            msg=f'expected {path} to be a subdirectory of {backend._resource_dir.name}')

    def test_resource_get_no_resource(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        with self.assertRaises(ModelError) as cm:
            backend.resource_get('foo')
        self.assertIn(
            "units/unit-test-app-0/resources/foo: resource#test-app/foo not found",
            str(cm.exception))

    def test_relation_remote_app_name(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            requires:
               db:
                 interface: foo
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend

        self.assertIs(backend.relation_remote_app_name(1), None)

        rel_id = harness.add_relation('db', 'postgresql')
        self.assertEqual(backend.relation_remote_app_name(rel_id), 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.add_relation_unit(rel_id, 'postgresql/1')
        self.assertEqual(backend.relation_remote_app_name(rel_id), 'postgresql')

        self.assertIs(backend.relation_remote_app_name(7), None)

    def test_get_pebble_methods(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend

        client = backend.get_pebble('/custom/socket/path')
        self.assertIsInstance(client, _TestingPebbleClient)
