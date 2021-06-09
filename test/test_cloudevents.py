#!/usr/bin/python3

# Copyright 2021 Canonical Ltd.
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

import os
import unittest
from unittest.mock import Mock, patch

from ops.charm import CharmMeta
from ops.cloudevents import (
    _set_registered,
    _set_unregistered,
    register_cloud_event,
    unregister_cloud_event,
)
from ops.framework import Framework, StoredStateData
from ops.model import Model, _ModelBackend
from ops.storage import SQLiteStorage


class TestCloudEvents(unittest.TestCase):

    def setUp(self):
        os.environ['JUJU_UNIT_NAME'] = 'mysql/0'

        self.emitter = Mock()
        model_backend = _ModelBackend()
        model = Model(CharmMeta.from_yaml('name: my-charm', ''), model_backend)
        self.emitter.framework = Framework(SQLiteStorage(':memory:'), None, None, model)
        self.emitter.framework._stored = StoredStateData(self.emitter, '_stored')

    def test_set_registered(self):
        self.assertEqual(self.emitter.framework._stored['registered_cloud_events'], None)
        _set_registered(self.emitter, 'foo')
        self.assertTrue(self.emitter.framework._stored['registered_cloud_events']['foo'])

    def test_set_unregistered(self):
        self.assertEqual(self.emitter.framework._stored['registered_cloud_events'], None)
        _set_unregistered(self.emitter, 'foo')
        self.assertFalse(self.emitter.framework._stored['registered_cloud_events']['foo'])

        # unregister foo, will removes foo from registered.
        self.emitter.framework._stored['registered_cloud_events'] = {'foo': True}
        self.assertTrue(self.emitter.framework._stored['registered_cloud_events']['foo'])
        _set_unregistered(self.emitter, 'foo')
        self.assertFalse(self.emitter.framework._stored['registered_cloud_events']['foo'])

    def test_register_cloud_event_no_ops_if_already_in_registered(self):
        with patch('ops.model._ModelBackend.register_cloud_event') as mock_register_cloud_event:
            self.emitter.framework._stored['registered_cloud_events'] = {'foo': True}
            self.assertTrue(self.emitter.framework._stored['registered_cloud_events']['foo'])
            register_cloud_event(self.emitter, 'foo', 'configmap', 'configmap1', False)
            self.assertTrue(self.emitter.framework._stored['registered_cloud_events']['foo'])
            self.assertFalse(mock_register_cloud_event.called)

    def test_register_cloud_event_no_ops_if_already_in_unregistered_without_force(self):
        with patch('ops.model._ModelBackend.register_cloud_event') as mock_register_cloud_event:
            self.emitter.framework._stored['registered_cloud_events'] = {'foo': False}
            self.assertFalse(self.emitter.framework._stored['registered_cloud_events']['foo'])
            register_cloud_event(self.emitter, 'foo', 'configmap', 'configmap1', False)
            self.assertFalse(self.emitter.framework._stored['registered_cloud_events']['foo'])
            self.assertFalse(mock_register_cloud_event.called)

    def test_register_cloud_event_already_in_unregistered_with_force(self):
        with patch('ops.model._ModelBackend.register_cloud_event') as mock_register_cloud_event:
            self.emitter.framework._stored['registered_cloud_events'] = {'foo': False}
            self.assertFalse(self.emitter.framework._stored['registered_cloud_events']['foo'])
            register_cloud_event(self.emitter, 'foo', 'configmap', 'configmap1', True)
            self.assertTrue(self.emitter.framework._stored['registered_cloud_events']['foo'])
            mock_register_cloud_event.assert_called_once_with('foo', 'configmap', 'configmap1')

    def test_register_cloud_event_first_time(self):
        with patch('ops.model._ModelBackend.register_cloud_event') as mock_register_cloud_event:
            self.assertEqual(self.emitter.framework._stored['registered_cloud_events'], None)
            register_cloud_event(self.emitter, 'foo', 'configmap', 'configmap1', False)
            self.assertTrue(self.emitter.framework._stored['registered_cloud_events']['foo'])
            mock_register_cloud_event.assert_called_once_with('foo', 'configmap', 'configmap1')

    def test_unregister_cloud_event_first_time_foo_in_registered(self):
        with patch(
            'ops.model._ModelBackend.unregister_cloud_event',
        ) as mock_unregister_cloud_event:
            self.emitter.framework._stored['registered_cloud_events'] = {'foo': True}
            self.assertTrue(self.emitter.framework._stored['registered_cloud_events']['foo'])
            unregister_cloud_event(self.emitter, 'foo')
            self.assertFalse(self.emitter.framework._stored['registered_cloud_events']['foo'])
            mock_unregister_cloud_event.assert_called_once_with('foo')

    def test_unregister_cloud_event_first_time_foo_not_in_registered(self):
        with patch(
            'ops.model._ModelBackend.unregister_cloud_event',
        ) as mock_unregister_cloud_event:
            self.assertEqual(self.emitter.framework._stored['registered_cloud_events'], None)
            unregister_cloud_event(self.emitter, 'foo')
            self.assertEqual(self.emitter.framework._stored['registered_cloud_events'], {})
            self.assertFalse(mock_unregister_cloud_event.called)

    def test_unregister_cloud_event_no_ops_if_already_in_unregistered(self):
        with patch(
            'ops.model._ModelBackend.unregister_cloud_event',
        ) as mock_unregister_cloud_event:
            self.emitter.framework._stored['registered_cloud_events'] = {'foo': False}
            self.assertFalse(self.emitter.framework._stored['registered_cloud_events']['foo'])
            unregister_cloud_event(self.emitter, 'foo')
            self.assertFalse(self.emitter.framework._stored['registered_cloud_events']['foo'])
            self.assertFalse(mock_unregister_cloud_event.called)
