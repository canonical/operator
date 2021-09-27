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

import io
import unittest

import yaml as base_yaml

from ops._private import yaml


class YAMLTest:
    pass


class TestYAML(unittest.TestCase):
    def test_safe_load(self):
        d = yaml.safe_load('foo: bar\nbaz: 123\n')
        self.assertEqual(len(d), 2)
        self.assertEqual(d['foo'], 'bar')
        self.assertEqual(d['baz'], 123)

        # Should error -- it's not safe to load an instance of a user-defined class
        with self.assertRaises(base_yaml.YAMLError):
            yaml.safe_load('!!python/object:test.test_helpers.YAMLTest {}')

    def test_safe_dump(self):
        s = yaml.safe_dump({'foo': 'bar', 'baz': 123})
        self.assertEqual(s, 'baz: 123\nfoo: bar\n')

        f = io.StringIO()
        s = yaml.safe_dump({'foo': 'bar', 'baz': 123}, stream=f)
        self.assertEqual(f.getvalue(), 'baz: 123\nfoo: bar\n')

        # Should error -- it's not safe to dump an instance of a user-defined class
        with self.assertRaises(base_yaml.YAMLError):
            yaml.safe_dump(YAMLTest())
