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

    def test_parse_duration(self):
        # Test cases taken from Go's time.ParseDuration tests
        cases = [
            # simple
            ('0', datetime.timedelta(seconds=0)),
            ('5s', datetime.timedelta(seconds=5)),
            ('30s', datetime.timedelta(seconds=30)),
            ('1478s', datetime.timedelta(seconds=1478)),
            # sign
            ('-5s', datetime.timedelta(seconds=-5)),
            ('+5s', datetime.timedelta(seconds=5)),
            ('-0', datetime.timedelta(seconds=0)),
            ('+0', datetime.timedelta(seconds=0)),
            # decimal
            ('5.0s', datetime.timedelta(seconds=5)),
            ('5.6s', datetime.timedelta(seconds=5.6)),
            ('5.s', datetime.timedelta(seconds=5)),
            ('.5s', datetime.timedelta(seconds=0.5)),
            ('1.0s', datetime.timedelta(seconds=1)),
            ('1.00s', datetime.timedelta(seconds=1)),
            ('1.004s', datetime.timedelta(seconds=1.004)),
            ('1.0040s', datetime.timedelta(seconds=1.004)),
            ('100.00100s', datetime.timedelta(seconds=100.001)),
            # different units
            ('10ns', datetime.timedelta(seconds=0.000_000_010)),
            ('11us', datetime.timedelta(seconds=0.000_011)),
            ('12µs', datetime.timedelta(seconds=0.000_012)),  # U+00B5
            ('12μs', datetime.timedelta(seconds=0.000_012)),  # U+03BC
            ('13ms', datetime.timedelta(seconds=0.013)),
            ('14s', datetime.timedelta(seconds=14)),
            ('15m', datetime.timedelta(seconds=15 * 60)),
            ('16h', datetime.timedelta(seconds=16 * 60 * 60)),
            # composite durations
            ('3h30m', datetime.timedelta(seconds=3 * 60 * 60 + 30 * 60)),
            ('10.5s4m', datetime.timedelta(seconds=4 * 60 + 10.5)),
            ('-2m3.4s', datetime.timedelta(seconds=-(2 * 60 + 3.4))),
            ('1h2m3s4ms5us6ns', datetime.timedelta(seconds=1 * 60 * 60 + 2 * 60 + 3.004_005_006)),
            ('39h9m14.425s', datetime.timedelta(seconds=39 * 60 * 60 + 9 * 60 + 14.425)),
            # large value
            ('52763797000ns', datetime.timedelta(seconds=52.763_797_000)),
            # more than 9 digits after decimal point, see https://golang.org/issue/6617
            ('0.3333333333333333333h', datetime.timedelta(seconds=20 * 60)),
            # huge string; issue 15011.
            ('0.100000000000000000000h', datetime.timedelta(seconds=6 * 60)),
            # This value tests the first overflow check in leadingFraction.
            ('0.830103483285477580700h', datetime.timedelta(seconds=49 * 60 + 48.372_539_827)),

            # Test precision handling
            ('7200000h1us', datetime.timedelta(hours=7_200_000, microseconds=1))
        ]

        for input, expected in cases:
            output = timeconv.parse_duration(input)
            self.assertEqual(output, expected,
                             f'parse_duration({input!r}): expected {expected!r}, got {output!r}')

    def test_parse_duration_errors(self):
        cases = [
            # Test cases taken from Go's time.ParseDuration tests
            '',
            '3',
            '-',
            's',
            '.',
            '-.',
            '.s',
            '+.s',
            '1d',
            '\x85\x85',
            '\xffff',
            'hello \xffff world',

            # Additional cases
            'X3h',
            '3hY',
            'X3hY',
            '3.4.5s',
        ]
        for input in cases:
            with self.assertRaises(ValueError):
                timeconv.parse_duration(input)
