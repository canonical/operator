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

import datetime
import io
import unittest

import yaml as base_yaml

from ops._private import timeconv, yaml


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
        yaml.safe_dump({'foo': 'bar', 'baz': 123}, stream=f)
        self.assertEqual(f.getvalue(), 'baz: 123\nfoo: bar\n')

        # Should error -- it's not safe to dump an instance of a user-defined class
        with self.assertRaises(base_yaml.YAMLError):
            yaml.safe_dump(YAMLTest())


class TestStrconv(unittest.TestCase):
    def test_parse_rfc3339(self):
        nzdt = datetime.timezone(datetime.timedelta(hours=13))
        utc = datetime.timezone.utc

        self.assertEqual(timeconv.parse_rfc3339('2020-12-25T13:45:50+13:00'),
                         datetime.datetime(2020, 12, 25, 13, 45, 50, 0, tzinfo=nzdt))

        self.assertEqual(timeconv.parse_rfc3339('2020-12-25T13:45:50.123456789+13:00'),
                         datetime.datetime(2020, 12, 25, 13, 45, 50, 123457, tzinfo=nzdt))

        self.assertEqual(timeconv.parse_rfc3339('2021-02-10T04:36:22Z'),
                         datetime.datetime(2021, 2, 10, 4, 36, 22, 0, tzinfo=utc))

        self.assertEqual(timeconv.parse_rfc3339('2021-02-10t04:36:22z'),
                         datetime.datetime(2021, 2, 10, 4, 36, 22, 0, tzinfo=utc))

        self.assertEqual(timeconv.parse_rfc3339('2021-02-10T04:36:22.118970777Z'),
                         datetime.datetime(2021, 2, 10, 4, 36, 22, 118971, tzinfo=utc))

        self.assertEqual(timeconv.parse_rfc3339('2020-12-25T13:45:50.123456789+00:00'),
                         datetime.datetime(2020, 12, 25, 13, 45, 50, 123457, tzinfo=utc))

        self.assertEqual(timeconv.parse_rfc3339('2006-08-28T13:20:00.9999999Z'),
                         datetime.datetime(2006, 8, 28, 13, 20, 0, 999999, tzinfo=utc))

        self.assertEqual(timeconv.parse_rfc3339('2006-12-31T23:59:59.9999999Z'),
                         datetime.datetime(2006, 12, 31, 23, 59, 59, 999999, tzinfo=utc))

        tzinfo = datetime.timezone(datetime.timedelta(hours=-11, minutes=-30))
        self.assertEqual(timeconv.parse_rfc3339('2020-12-25T13:45:50.123456789-11:30'),
                         datetime.datetime(2020, 12, 25, 13, 45, 50, 123457, tzinfo=tzinfo))

        tzinfo = datetime.timezone(datetime.timedelta(hours=4))
        self.assertEqual(timeconv.parse_rfc3339('2000-01-02T03:04:05.006000+04:00'),
                         datetime.datetime(2000, 1, 2, 3, 4, 5, 6000, tzinfo=tzinfo))

        with self.assertRaises(ValueError):
            timeconv.parse_rfc3339('')

        with self.assertRaises(ValueError):
            timeconv.parse_rfc3339('foobar')

        with self.assertRaises(ValueError):
            timeconv.parse_rfc3339('2021-99-99T04:36:22Z')

        with self.assertRaises(ValueError):
            timeconv.parse_rfc3339('2021-02-10T04:36:22.118970777x')

        with self.assertRaises(ValueError):
            timeconv.parse_rfc3339('2021-02-10T04:36:22.118970777-99:99')
