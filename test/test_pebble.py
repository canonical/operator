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

import datetime
import unittest
import unittest.util

import ops.pebble as pebble


# Ensure unittest diffs don't get truncated like "[17 chars]"
unittest.util._MAX_LENGTH = 1000

NZDT_STR = 'tzinfo=datetime.timezone(datetime.timedelta(seconds=46800))'


def datetime_utc(y, m, d, hour, min, sec, micro=0):
    tz = datetime.timezone.utc
    return datetime.datetime(y, m, d, hour, min, sec, micro, tzinfo=tz)


def datetime_nzdt(y, m, d, hour, min, sec, micro=0):
    tz = datetime.timezone(datetime.timedelta(hours=13))
    return datetime.datetime(y, m, d, hour, min, sec, micro, tzinfo=tz)


class TestMisc(unittest.TestCase):
    def test_fromisoformat(self):
        self.assertEqual(pebble._fromisoformat('2020-12-25T13:45:50.123456+13:00'),
                         datetime_nzdt(2020, 12, 25, 13, 45, 50, 123456))
        with self.assertRaises(ValueError):
            pebble._fromisoformat('xyz')

    def test_parse_timestamp(self):
        self.assertEqual(pebble._fromisoformat('2020-12-25T13:45:50.123456+13:00'),
                         datetime_nzdt(2020, 12, 25, 13, 45, 50, 123456))
        self.assertEqual(pebble._parse_timestamp('2020-12-25T13:45:50.123456789+13:00'),
                         datetime_nzdt(2020, 12, 25, 13, 45, 50, 123456))
        self.assertEqual(pebble._fromisoformat('2020-12-25T13:45:50.123456+00:00'),
                         datetime_utc(2020, 12, 25, 13, 45, 50, 123456))
        self.assertEqual(pebble._parse_timestamp('2020-12-25T13:45:50.123456789+00:00'),
                         datetime_utc(2020, 12, 25, 13, 45, 50, 123456))


class TestTypes(unittest.TestCase):
    maxDiff = None

    def test_service_error(self):
        change = pebble.Change(
            id=pebble.ChangeID('1234'),
            kind='start',
            summary='Start service "foo"',
            status='Done',
            tasks=[],
            ready=True,
            err=None,
            spawn_time=datetime.datetime.now(),
            ready_time=datetime.datetime.now(),
        )
        error = pebble.ServiceError('Some error', change)
        self.assertEqual(error.err, 'Some error')
        self.assertEqual(error.change, change)
        self.assertEqual(error.args, ('Some error', change))
        self.assertEqual(str(error), 'Some error')

    def test_warning_state(self):
        self.assertEqual(list(pebble.WarningState), [
            pebble.WarningState.ALL,
            pebble.WarningState.PENDING,
        ])
        self.assertEqual(pebble.WarningState.ALL.value, 'all')
        self.assertEqual(pebble.WarningState.PENDING.value, 'pending')

    def test_change_state(self):
        self.assertEqual(list(pebble.ChangeState), [
            pebble.ChangeState.ALL,
            pebble.ChangeState.IN_PROGRESS,
            pebble.ChangeState.READY,
        ])
        self.assertEqual(pebble.ChangeState.ALL.value, 'all')
        self.assertEqual(pebble.ChangeState.IN_PROGRESS.value, 'in-progress')
        self.assertEqual(pebble.ChangeState.READY.value, 'ready')

    def test_system_info_init(self):
        info = pebble.SystemInfo(version='1.2.3')
        self.assertEqual(info.version, '1.2.3')
        self.assertEqual(repr(info), "SystemInfo(version='1.2.3')")

    def test_system_info_from_dict(self):
        info = pebble.SystemInfo.from_dict({'version': '3.2.1'})
        self.assertEqual(info.version, '3.2.1')
        self.assertEqual(repr(info), "SystemInfo(version='3.2.1')")

    def test_warning_init(self):
        warning = pebble.Warning(
            message='Beware!',
            first_added=datetime_utc(2021, 1, 1, 1, 1, 1),
            last_added=datetime_utc(2021, 1, 26, 2, 3, 4),
            last_shown=None,
            expire_after='1s',
            repeat_after='2s',
        )
        self.assertEqual(warning.message, 'Beware!')
        self.assertEqual(warning.first_added, datetime_utc(2021, 1, 1, 1, 1, 1))
        self.assertEqual(warning.last_added, datetime_utc(2021, 1, 26, 2, 3, 4))
        self.assertEqual(warning.last_shown, None)
        self.assertEqual(warning.expire_after, '1s')
        self.assertEqual(warning.repeat_after, '2s')
        self.assertEqual(repr(warning), (
            "Warning("
            "message='Beware!', "
            "first_added=datetime.datetime(2021, 1, 1, 1, 1, 1, tzinfo=datetime.timezone.utc), "
            "last_added=datetime.datetime(2021, 1, 26, 2, 3, 4, tzinfo=datetime.timezone.utc), "
            "last_shown=None, "
            "expire_after='1s', "
            "repeat_after='2s')"))

    def test_warning_from_dict(self):
        d = {
            'message': 'Look out...',
            'first-added': '2020-12-25T17:18:54.016273778+13:00',
            'last-added': '2021-01-26T17:01:02.12345+13:00',
            'expire-after': '1s',
            'repeat-after': '2s',
        }
        warning = pebble.Warning.from_dict(d)
        self.assertEqual(warning.message, 'Look out...')
        self.assertEqual(warning.first_added, datetime_nzdt(2020, 12, 25, 17, 18, 54, 16273))
        self.assertEqual(warning.last_added, datetime_nzdt(2021, 1, 26, 17, 1, 2, 123450))
        self.assertEqual(warning.last_shown, None)
        self.assertEqual(warning.expire_after, '1s')
        self.assertEqual(warning.repeat_after, '2s')
        self.assertEqual(repr(warning), (
            "Warning("
            "message='Look out...', "
            "first_added=datetime.datetime(2020, 12, 25, 17, 18, 54, 16273, "+NZDT_STR+"), "
            "last_added=datetime.datetime(2021, 1, 26, 17, 1, 2, 123450, "+NZDT_STR+"), "
            "last_shown=None, "
            "expire_after='1s', "
            "repeat_after='2s')"))

        d['last-shown'] = None
        warning = pebble.Warning.from_dict(d)
        self.assertEqual(warning.last_shown, None)

        d['last-shown'] = '2021-08-04T03:02:01.000000000+13:00'
        warning = pebble.Warning.from_dict(d)
        self.assertEqual(warning.last_shown, datetime_nzdt(2021, 8, 4, 3, 2, 1))
