#!/usr/bin/python3
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

import os
import unittest
import tempfile
import shutil

from ops.charm import (
    CharmBase,
    CharmMeta,
    CharmEvents,
)
from ops.framework import Framework, EventSource, EventBase
from ops.model import Model, ModelBackend
from ops.testing import TestingModelBuilder


class TestModelBuilder(unittest.TestCase):

    def test_add_relation(self):
        builder = TestingModelBuilder('test-unit/0')
        rel_id = builder.add_relation('db', 'postgresql')
        backend = builder.get_backend()
        self.assertEqual([rel_id], backend.relation_ids('db'))
        self.assertEqual([], backend.relation_list(rel_id))

    def test_add_relation_and_unit(self):
        builder = TestingModelBuilder('test-unit/0')
        remote_unit = 'postgresql/0'
        rel_id = builder.add_relation_and_unit('db', remote_unit, remote_unit_data={'foo': 'bar'}, remote_app_data={'app': 'data'})
        backend = builder.get_backend()
        self.assertEqual([rel_id], backend.relation_ids('db'))
        self.assertEqual([remote_unit], backend.relation_list(rel_id))
        self.assertEqual({'foo': 'bar'}, backend.relation_get(rel_id, remote_unit, is_app=False))
        self.assertEqual({'app': 'data'}, backend.relation_get(rel_id, remote_unit, is_app=True))


if __name__ == "__main__":
    unittest.main()
