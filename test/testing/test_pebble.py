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

import datetime
import io
import os
import pathlib
import platform
import shutil
import tempfile
import textwrap
import unittest
from io import BytesIO, StringIO

from ops import pebble
from ops.charm import CharmBase
from ops.testing import (
    Harness,
    NonAbsolutePathError,
    _Directory,
    _TestingFilesystem,
    _TestingStorageMount,
)

from .common import get_public_methods


class _TestingPebbleClientMixin:
    def get_testing_client(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            containers:
              mycontainer: {}
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend

        client = backend.get_pebble('/charm/containers/mycontainer/pebble.socket')
        harness.set_can_connect('mycontainer', True)
        return client


# For testing non file ops of the pebble testing client.
class TestTestingPebbleClient(unittest.TestCase, _TestingPebbleClientMixin):
    def test_methods_match_pebble_client(self):
        client = self.get_testing_client()
        self.assertIsNotNone(client)
        pebble_client_methods = get_public_methods(pebble.Client)
        testing_client_methods = get_public_methods(client)
        self.assertEqual(pebble_client_methods, testing_client_methods)

    def test_add_layer(self):
        client = self.get_testing_client()
        plan = client.get_plan()
        self.assertIsInstance(plan, pebble.Plan)
        self.assertEqual('{}\n', plan.to_yaml())
        client.add_layer('foo', pebble.Layer('''\
            summary: Foo
            description: |
              A longer description about Foo
            services:
              serv:
                summary: Serv
                description: |
                  A description about Serv the amazing service.
                startup: enabled
                override: replace
                command: '/bin/echo hello'
                environment:
                  KEY: VALUE
            '''))
        plan = client.get_plan()
        # The YAML should be normalized
        self.assertEqual(textwrap.dedent('''\
            services:
              serv:
                command: /bin/echo hello
                description: 'A description about Serv the amazing service.

                  '
                environment:
                  KEY: VALUE
                override: replace
                startup: enabled
                summary: Serv
            '''), plan.to_yaml())

    def test_add_layer_merge(self):
        client = self.get_testing_client()
        plan = client.get_plan()
        self.assertIsInstance(plan, pebble.Plan)
        self.assertEqual('{}\n', plan.to_yaml())
        client.add_layer('foo', pebble.Layer('''\
            summary: Foo
            description: |
              A longer description about Foo
            services:
              serv:
                summary: Serv
                description: |
                  A description about Serv the amazing service.
                startup: enabled
                override: replace
                command: '/bin/echo hello'
                environment:
                  KEY1: VALUE1
                after:
                - thing1
                before:
                - thing1
                requires:
                - thing1
                user: user1
                user-id: userID1
                group: group1
                group-id: groupID1
                on-failure: thing1
                on-success: thing1
                on-check-failure:
                  KEY1: VALUE1
                backoff-delay: 1
                backoff-factor: 2
                backoff-limit: 1
            '''))
        plan = client.get_plan()
        # The YAML should be normalized
        self.maxDiff = None
        self.assertEqual(textwrap.dedent('''\
            services:
              serv:
                after:
                - thing1
                backoff-delay: 1
                backoff-factor: 2
                backoff-limit: 1
                before:
                - thing1
                command: /bin/echo hello
                description: 'A description about Serv the amazing service.

                  '
                environment:
                  KEY1: VALUE1
                group: group1
                group-id: groupID1
                on-check-failure:
                  KEY1: VALUE1
                on-failure: thing1
                on-success: thing1
                override: replace
                requires:
                - thing1
                startup: enabled
                summary: Serv
                user: user1
                user-id: userID1
            '''), plan.to_yaml())

        client.add_layer('foo', pebble.Layer('''\
            summary: Foo
            description: |
              A longer description about Foo
            services:
              serv:
                summary: Serv
                description: |
                  A new description of the the amazing Serv service.
                startup: enabled
                override: merge
                command: '/bin/echo hello'
                environment:
                  KEY1: VALUE4
                  KEY2: VALUE2
                  KEY3: VALUE3
                after:
                - thing2
                before:
                - thing2
                requires:
                - thing2
                user: user2
                user-id: userID2
                group: group2
                group-id: groupID2
                on-success: thing2
                on-failure: thing2
                on-check-failure:
                  KEY1: VALUE4
                  KEY2: VALUE2
                  KEY3: VALUE3
                backoff-delay: 2
                backoff-factor: 3
                backoff-limit: 2
            '''), combine=True)
        plan = client.get_plan()
        # The YAML should be normalized
        self.assertEqual(textwrap.dedent('''\
            services:
              serv:
                after:
                - thing1
                - thing2
                backoff-delay: 2
                backoff-factor: 3
                backoff-limit: 2
                before:
                - thing1
                - thing2
                command: /bin/echo hello
                description: 'A new description of the the amazing Serv service.

                  '
                environment:
                  KEY1: VALUE4
                  KEY2: VALUE2
                  KEY3: VALUE3
                group: group2
                group-id: groupID2
                on-check-failure:
                  KEY1: VALUE4
                  KEY2: VALUE2
                  KEY3: VALUE3
                on-failure: thing2
                on-success: thing2
                override: merge
                requires:
                - thing1
                - thing2
                startup: enabled
                summary: Serv
                user: user2
                user-id: userID2
            '''), plan.to_yaml())

    def test_add_layer_not_combined(self):
        client = self.get_testing_client()
        plan = client.get_plan()
        self.assertIsInstance(plan, pebble.Plan)
        self.assertEqual('{}\n', plan.to_yaml())
        service = textwrap.dedent('''\
            summary: Foo
            description: |
              A longer description about Foo
            services:
              serv:
                summary: Serv
                description: |
                  A description about Serv the amazing service.
                startup: enabled
                override: replace
                command: '/bin/echo hello'
                environment:
                  KEY: VALUE
            ''')
        client.add_layer('foo', pebble.Layer(service))
        # TODO: jam 2021-04-19 We should have a clearer error type for this case. The actual
        #  pebble raises an HTTP exception. See https://github.com/canonical/operator/issues/514
        #  that this should be cleaned up into a clearer error type, however, they should get an
        #  error
        with self.assertRaises(RuntimeError):
            client.add_layer('foo', pebble.Layer(service))

    def test_add_layer_three_services(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                override: replace
                command: '/bin/echo foo'
            ''')
        client.add_layer('bar', '''\
            summary: bar
            services:
              bar:
                summary: The Great Bar
                startup: enabled
                override: replace
                command: '/bin/echo bar'
            ''')
        client.add_layer('baz', '''\
            summary: baz
            services:
              baz:
                summary: Not Bar, but Baz
                startup: enabled
                override: replace
                command: '/bin/echo baz'
            ''')
        plan = client.get_plan()
        self.maxDiff = 1000
        # Alphabetical services, and the YAML should be normalized
        self.assertEqual(textwrap.dedent('''\
            services:
              bar:
                command: /bin/echo bar
                override: replace
                startup: enabled
                summary: The Great Bar
              baz:
                command: /bin/echo baz
                override: replace
                startup: enabled
                summary: Not Bar, but Baz
              foo:
                command: /bin/echo foo
                override: replace
                startup: enabled
                summary: Foo
            '''), plan.to_yaml())

    def test_add_layer_combine_no_override(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
            command: '/bin/echo foo'
            ''')
        # TODO: jam 2021-04-19 Pebble currently raises a HTTP Error 500 Internal Service Error
        #  if you don't supply an override directive. That needs to be fixed and this test
        #  should be updated. https://github.com/canonical/operator/issues/514
        with self.assertRaises(RuntimeError):
            client.add_layer('foo', '''\
                summary: foo
                services:
                  foo:
                    summary: Foo
                    command: '/bin/echo foo'
                ''', combine=True)

    def test_add_layer_combine_override_replace(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              bar:
                summary: Bar
                command: '/bin/echo bar'
              foo:
                summary: Foo
                command: '/bin/echo foo'
            ''')
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                command: '/bin/echo foo new'
                override: replace
            ''', combine=True)
        self.assertEqual(textwrap.dedent('''\
            services:
              bar:
                command: /bin/echo bar
                summary: Bar
              foo:
                command: /bin/echo foo new
                override: replace
            '''), client.get_plan().to_yaml())

    def test_add_layer_combine_override_merge(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              bar:
                summary: Bar
                command: '/bin/echo bar'
              foo:
                summary: Foo
                command: '/bin/echo foo'
            ''')
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                command: '/bin/echo foob'
                override: merge
            ''', combine=True)
        self.assertEqual(textwrap.dedent('''\
            services:
              bar:
                command: /bin/echo bar
                summary: Bar
              foo:
                command: /bin/echo foob
                override: merge
                summary: Foo
            '''), client.get_plan().to_yaml())

    def test_add_layer_combine_override_unknown(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              bar:
                summary: Bar
                command: '/bin/echo bar'
              foo:
                summary: Foo
                command: '/bin/echo foo'
            ''')
        with self.assertRaises(RuntimeError):
            client.add_layer('foo', '''\
                summary: foo
                services:
                  foo:
                    summary: Foo
                    command: '/bin/echo foob'
                    override: blah
                ''', combine=True)

    def test_get_services_none(self):
        client = self.get_testing_client()
        service_info = client.get_services()
        self.assertEqual([], service_info)

    def test_get_services_not_started(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Default when not specified is DISABLED
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)
        self.assertFalse(bar_info.is_running())
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)
        self.assertFalse(foo_info.is_running())

    def test_get_services_autostart(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        client.autostart_services()
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Default when not specified is DISABLED
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)
        self.assertFalse(bar_info.is_running())
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, foo_info.current)
        self.assertTrue(foo_info.is_running())

    def test_get_services_start_stop(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        client.start_services(['bar'])
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Even though bar defaults to DISABLED, we explicitly started it
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, bar_info.current)
        # foo would be started by autostart, but we only called start_services
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)
        client.stop_services(['bar'])
        infos = client.get_services()
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)

    def test_get_services_bad_request(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        # It is a common mistake to pass just a name vs a list of names, so catch it with a
        # TypeError
        with self.assertRaises(TypeError):
            client.get_services('foo')

    def test_get_services_subset(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        infos = client.get_services(['foo'])
        self.assertEqual(len(infos), 1)
        foo_info = infos[0]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)

    def test_get_services_unknown(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        # This doesn't seem to be an error at the moment.
        # pebble_cli.py service just returns an empty list
        # pebble service unknown says "No matching services" (but exits 0)
        infos = client.get_services(['unknown'])
        self.assertEqual(infos, [])

    def test_invalid_start_service(self):
        client = self.get_testing_client()
        # TODO: jam 2021-04-20 This should become a better error
        with self.assertRaises(RuntimeError):
            client.start_services(['unknown'])

    def test_start_service_str(self):
        # Start service takes a list of names, but it is really easy to accidentally pass just a
        # name
        client = self.get_testing_client()
        with self.assertRaises(TypeError):
            client.start_services('unknown')

    def test_stop_service_str(self):
        # Start service takes a list of names, but it is really easy to accidentally pass just a
        # name
        client = self.get_testing_client()
        with self.assertRaises(TypeError):
            client.stop_services('unknown')

    def test_mixed_start_service(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
            ''')
        # TODO: jam 2021-04-20 better error type
        with self.assertRaises(RuntimeError):
            client.start_services(['foo', 'unknown'])
        # foo should not be started
        infos = client.get_services()
        self.assertEqual(len(infos), 1)
        foo_info = infos[0]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)

    def test_stop_services_unknown(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
            ''')
        client.autostart_services()
        # TODO: jam 2021-04-20 better error type
        with self.assertRaises(RuntimeError):
            client.stop_services(['foo', 'unknown'])
        # foo should still be running
        infos = client.get_services()
        self.assertEqual(len(infos), 1)
        foo_info = infos[0]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, foo_info.current)

    def test_start_started_service(self):
        # Pebble maintains idempotency even if you start a service
        # which is already started.
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        client.autostart_services()
        # Foo is now started, but Bar is not
        client.start_services(['bar', 'foo'])
        # foo and bar are both started
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Default when not specified is DISABLED
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, bar_info.current)
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, foo_info.current)

    def test_stop_stopped_service(self):
        # Pebble maintains idempotency even if you stop a service
        # which is already stopped.
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        client.autostart_services()
        # Foo is now started, but Bar is not
        client.stop_services(['foo', 'bar'])
        # foo and bar are both stopped
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Default when not specified is DISABLED
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)

    @ unittest.skipUnless(platform.system() == 'Linux', 'Pebble runs on Linux')
    def test_send_signal(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            ''')
        client.autostart_services()
        # Foo is now started, but Bar is not

        # Send a valid signal to a running service
        client.send_signal("SIGINT", "foo")

        # Send a valid signal but omit service name
        with self.assertRaises(TypeError):
            client.send_signal("SIGINT")

        # Send an invalid signal to a running service
        with self.assertRaises(pebble.APIError):
            client.send_signal("sigint", "foo")

        # Send a valid signal to a stopped service
        with self.assertRaises(pebble.APIError):
            client.send_signal("SIGINT", "bar")

        # Send a valid signal to a non-existing service
        with self.assertRaises(pebble.APIError):
            client.send_signal("SIGINT", "baz")

        # Send a valid signal to a multiple services, one of which is not running
        with self.assertRaises(pebble.APIError):
            client.send_signal("SIGINT", "foo", "bar")


# For testing file-ops of the pebble client.  This is refactored into a
# separate mixin so we can run these tests against both the mock client as
# well as a real pebble server instance.
class _PebbleStorageAPIsTestMixin:
    # Override this in classes using this mixin.
    # This should be set to any non-empty path, but without a trailing /.
    prefix = None

    def test_push_and_pull_bytes(self):
        self._test_push_and_pull_data(
            original_data=b"\x00\x01\x02\x03\x04",
            encoding=None,
            stream_class=io.BytesIO)

    def test_push_and_pull_non_utf8_data(self):
        self._test_push_and_pull_data(
            original_data='日本語',  # "Japanese" in Japanese
            encoding='sjis',
            stream_class=io.StringIO)

    def _test_push_and_pull_data(self, original_data, encoding, stream_class):
        client = self.client
        client.push(f"{self.prefix}/test", original_data, encoding=encoding)
        with client.pull(f"{self.prefix}/test", encoding=encoding) as infile:
            received_data = infile.read()
        self.assertEqual(original_data, received_data)

        # We also support file-like objects as input, so let's test that case as well.
        small_file = stream_class(original_data)
        client.push(f"{self.prefix}/test", small_file, encoding=encoding)
        with client.pull(f"{self.prefix}/test", encoding=encoding) as infile:
            received_data = infile.read()
        self.assertEqual(original_data, received_data)

    def test_push_and_pull_larger_file(self):
        # Intent: to ensure things work appropriately with larger files.
        # Larger files may be sent/received in multiple chunks; this should help for
        # checking that such logic is correct.
        data_size = 1024 * 1024
        original_data = os.urandom(data_size)

        client = self.client
        client.push(f"{self.prefix}/test", original_data, encoding=None)
        with client.pull(f"{self.prefix}/test", encoding=None) as infile:
            received_data = infile.read()
        self.assertEqual(original_data, received_data)

    def test_push_to_non_existent_subdir(self):
        data = 'data'
        client = self.client

        with self.assertRaises(pebble.PathError) as cm:
            client.push(f"{self.prefix}/nonexistent_dir/test", data, make_dirs=False)
        self.assertEqual(cm.exception.kind, 'not-found')

        client.push(f"{self.prefix}/nonexistent_dir/test", data, make_dirs=True)

    def test_push_as_child_of_file_raises_error(self):
        data = 'data'
        client = self.client
        client.push(f"{self.prefix}/file", data)
        with self.assertRaises(pebble.PathError) as cm:
            client.push(f"{self.prefix}/file/file", data)
        self.assertEqual(cm.exception.kind, 'generic-file-error')

    def test_push_with_permission_mask(self):
        data = 'data'
        client = self.client
        client.push(f"{self.prefix}/file", data, permissions=0o600)
        client.push(f"{self.prefix}/file", data, permissions=0o777)
        # If permissions are outside of the range 0o000 through 0o777, an exception should be
        # raised.
        for bad_permission in (
                0o1000,  # Exceeds 0o777
                -1,      # Less than 0o000
        ):
            with self.assertRaises(pebble.PathError) as cm:
                client.push(f"{self.prefix}/file", data, permissions=bad_permission)
        self.assertEqual(cm.exception.kind, 'generic-file-error')

    def test_push_files_and_list(self):
        data = 'data'
        client = self.client

        # Let's push the first file with a bunch of details.  We'll check on this later.
        client.push(
            f"{self.prefix}/file1", data,
            permissions=0o620)

        # Do a quick push with defaults for the other files.
        client.push(f"{self.prefix}/file2", data)
        client.push(f"{self.prefix}/file3", data)

        files = client.list_files(f"{self.prefix}/")
        self.assertEqual({file.path for file in files},
                         {self.prefix + file for file in ('/file1', '/file2', '/file3')})

        # Let's pull the first file again and check its details
        file = [f for f in files if f.path == f"{self.prefix}/file1"][0]
        self.assertEqual(file.name, 'file1')
        self.assertEqual(file.type, pebble.FileType.FILE)
        self.assertEqual(file.size, 4)
        self.assertIsInstance(file.last_modified, datetime.datetime)
        self.assertEqual(file.permissions, 0o620)
        # Skipping ownership checks here; ownership will be checked in purely-mocked tests

    def test_push_and_list_file(self):
        data = 'data'
        client = self.client
        client.push(f"{self.prefix}/file", data)
        files = client.list_files(f"{self.prefix}/")
        self.assertEqual({file.path for file in files}, {f"{self.prefix}/file"})

    def test_push_file_with_relative_path_fails(self):
        client = self.client
        with self.assertRaises(pebble.PathError) as cm:
            client.push('file', '')
        self.assertEqual(cm.exception.kind, 'generic-file-error')

    def test_pull_not_found(self):
        with self.assertRaises(pebble.PathError) as cm:
            self.client.pull("/not/found")
        self.assertEqual(cm.exception.kind, "not-found")
        self.assertIn("/not/found", cm.exception.message)

    def test_pull_directory(self):
        self.client.make_dir(f"{self.prefix}/subdir")
        with self.assertRaises(pebble.PathError) as cm:
            self.client.pull(f"{self.prefix}/subdir")
        self.assertEqual(cm.exception.kind, "generic-file-error")
        self.assertIn(f"{self.prefix}/subdir", cm.exception.message)

    def test_list_files_not_found_raises(self):
        client = self.client
        with self.assertRaises(pebble.APIError) as cm:
            client.list_files("/not/existing/file/")
        self.assertEqual(cm.exception.code, 404)
        self.assertEqual(cm.exception.status, 'Not Found')
        self.assertEqual(cm.exception.message, 'stat /not/existing/file/: no '
                                               'such file or directory')

    def test_list_directory_object_itself(self):
        client = self.client

        # Test with root dir
        # (Special case; we won't prefix this, even when using the real Pebble server.)
        files = client.list_files('/', itself=True)
        self.assertEqual(len(files), 1)
        dir_ = files[0]
        self.assertEqual(dir_.path, '/')
        self.assertEqual(dir_.name, '/')
        self.assertEqual(dir_.type, pebble.FileType.DIRECTORY)

        # Test with subdirs
        client.make_dir(f"{self.prefix}/subdir")
        files = client.list_files(f"{self.prefix}/subdir", itself=True)
        self.assertEqual(len(files), 1)
        dir_ = files[0]
        self.assertEqual(dir_.name, 'subdir')
        self.assertEqual(dir_.type, pebble.FileType.DIRECTORY)

    def test_push_files_and_list_by_pattern(self):
        # Note: glob pattern deltas do exist between golang and Python, but here,
        # we'll just use a simple * pattern.
        data = 'data'
        client = self.client
        for filename in (
                '/file1.gz',
                '/file2.tar.gz',
                '/file3.tar.bz2',
                '/backup_file.gz',
        ):
            client.push(self.prefix + filename, data)
        files = client.list_files(f"{self.prefix}/", pattern='file*.gz')
        self.assertEqual({file.path for file in files},
                         {self.prefix + file for file in ('/file1.gz', '/file2.tar.gz')})

    def test_make_directory(self):
        client = self.client
        client.make_dir(f"{self.prefix}/subdir")
        self.assertEqual(
            client.list_files(f"{self.prefix}/", pattern='subdir')[0].path,
            f"{self.prefix}/subdir")
        client.make_dir(f"{self.prefix}/subdir/subdir")
        self.assertEqual(
            client.list_files(f"{self.prefix}/subdir", pattern='subdir')[0].path,
            f"{self.prefix}/subdir/subdir")

    def test_make_directory_recursively(self):
        client = self.client

        with self.assertRaises(pebble.PathError) as cm:
            client.make_dir(f"{self.prefix}/subdir/subdir", make_parents=False)
        self.assertEqual(cm.exception.kind, 'not-found')

        client.make_dir(f"{self.prefix}/subdir/subdir", make_parents=True)
        self.assertEqual(
            client.list_files(f"{self.prefix}/subdir", pattern='subdir')[0].path,
            f"{self.prefix}/subdir/subdir")

    def test_make_directory_with_relative_path_fails(self):
        client = self.client
        with self.assertRaises(pebble.PathError) as cm:
            client.make_dir('dir')
        self.assertEqual(cm.exception.kind, 'generic-file-error')

    def test_make_subdir_of_file_fails(self):
        client = self.client
        client.push(f"{self.prefix}/file", 'data')

        # Direct child case
        with self.assertRaises(pebble.PathError) as cm:
            client.make_dir(f"{self.prefix}/file/subdir")
        self.assertEqual(cm.exception.kind, 'generic-file-error')

        # Recursive creation case, in case its flow is different
        with self.assertRaises(pebble.PathError) as cm:
            client.make_dir(f"{self.prefix}/file/subdir/subdir", make_parents=True)
        self.assertEqual(cm.exception.kind, 'generic-file-error')

    def test_make_dir_with_permission_mask(self):
        client = self.client
        client.make_dir(f"{self.prefix}/dir1", permissions=0o700)
        client.make_dir(f"{self.prefix}/dir2", permissions=0o777)

        files = client.list_files(f"{self.prefix}/", pattern='dir*')
        self.assertEqual([f for f in files if f.path == f"{self.prefix}/dir1"]
                         [0].permissions, 0o700)
        self.assertEqual([f for f in files if f.path == f"{self.prefix}/dir2"]
                         [0].permissions, 0o777)

        # If permissions are outside of the range 0o000 through 0o777, an exception should be
        # raised.
        for i, bad_permission in enumerate((
                0o1000,  # Exceeds 0o777
                -1,      # Less than 0o000
        )):
            with self.assertRaises(pebble.PathError) as cm:
                client.make_dir(f"{self.prefix}/dir3_{i}", permissions=bad_permission)
            self.assertEqual(cm.exception.kind, 'generic-file-error')

    def test_remove_path(self):
        client = self.client
        client.push(f"{self.prefix}/file", '')
        client.make_dir(f"{self.prefix}/dir/subdir", make_parents=True)
        client.push(f"{self.prefix}/dir/subdir/file1", '')
        client.push(f"{self.prefix}/dir/subdir/file2", '')
        client.push(f"{self.prefix}/dir/subdir/file3", '')
        client.make_dir(f"{self.prefix}/empty_dir")

        client.remove_path(f"{self.prefix}/file")

        client.remove_path(f"{self.prefix}/empty_dir")

        # Remove non-empty directory, recursive=False: error
        with self.assertRaises(pebble.PathError) as cm:
            client.remove_path(f"{self.prefix}/dir", recursive=False)
        self.assertEqual(cm.exception.kind, 'generic-file-error')

        # Remove non-empty directory, recursive=True: succeeds (and removes child objects)
        client.remove_path(f"{self.prefix}/dir", recursive=True)

        # Remove non-existent path, recursive=False: error
        with self.assertRaises(pebble.PathError) as cm:
            client.remove_path(f"{self.prefix}/dir/does/not/exist/asdf", recursive=False)
        self.assertEqual(cm.exception.kind, 'not-found')

        # Remove non-existent path, recursive=True: succeeds
        client.remove_path(f"{self.prefix}/dir/does/not/exist/asdf", recursive=True)

    # Other notes:
    # * Parent directories created via push(make_dirs=True) default to root:root ownership
    #   and whatever permissions are specified via the permissions argument; as we default to None
    #   for ownership/permissions, we do ignore this nuance.
    # * Parent directories created via make_dir(make_parents=True) default to root:root ownership
    #   and 0o755 permissions; as we default to None for ownership/permissions, we do ignore this
    #   nuance.


class GenericTestingFilesystemTests:
    def test_listdir_root_on_empty_os(self):
        self.assertEqual(self.fs.list_dir('/'), [])

    def test_listdir_on_nonexistent_dir(self):
        with self.assertRaises(FileNotFoundError) as cm:
            self.fs.list_dir('/etc')
        self.assertTrue('/etc' in cm.exception.args[0])

    def test_listdir(self):
        self.fs.create_dir('/opt')
        self.fs.create_file('/opt/file1', 'data')
        self.fs.create_file('/opt/file2', 'data')
        expected_results = {
            pathlib.PurePosixPath('/opt/file1'),
            pathlib.PurePosixPath('/opt/file2')}
        self.assertEqual(expected_results, {f.path for f in self.fs.list_dir('/opt')})
        # Ensure that Paths also work for listdir
        self.assertEqual(
            expected_results, {f.path for f in self.fs.list_dir(pathlib.PurePosixPath('/opt'))})

    def test_listdir_on_file(self):
        self.fs.create_file('/file', 'data')
        with self.assertRaises(NotADirectoryError) as cm:
            self.fs.list_dir('/file')
        self.assertTrue('/file' in cm.exception.args[0])

    def test_makedir(self):
        d = self.fs.create_dir('/etc')
        self.assertEqual(d.name, 'etc')
        self.assertEqual(d.path, pathlib.PurePosixPath('/etc'))
        d2 = self.fs.create_dir('/etc/init.d')
        self.assertEqual(d2.name, 'init.d')
        self.assertEqual(d2.path, pathlib.PurePosixPath('/etc/init.d'))

    def test_makedir_fails_if_already_exists(self):
        self.fs.create_dir('/etc')
        with self.assertRaises(FileExistsError) as cm:
            self.fs.create_dir('/etc')
        self.assertTrue('/etc' in cm.exception.args[0])

    def test_makedir_succeeds_if_already_exists_when_make_parents_true(self):
        d1 = self.fs.create_dir('/etc')
        d2 = self.fs.create_dir('/etc', make_parents=True)
        self.assertEqual(d1.path, d2.path)
        self.assertEqual(d1.name, d2.name)

    def test_makedir_fails_if_parent_dir_doesnt_exist(self):
        with self.assertRaises(FileNotFoundError) as cm:
            self.fs.create_dir('/etc/init.d')
        self.assertTrue('/etc' in cm.exception.args[0])

    def test_make_and_list_directory(self):
        self.fs.create_dir('/etc')
        self.fs.create_dir('/var')
        self.assertEqual(
            {f.path for f in self.fs.list_dir('/')},
            {pathlib.PurePosixPath('/etc'), pathlib.PurePosixPath('/var')})

    def test_make_directory_recursively(self):
        self.fs.create_dir('/etc/init.d', make_parents=True)
        self.assertEqual([str(o.path) for o in self.fs.list_dir('/')], ['/etc'])
        self.assertEqual([str(o.path) for o in self.fs.list_dir('/etc')], ['/etc/init.d'])

    def test_makedir_path_must_start_with_slash(self):
        with self.assertRaises(NonAbsolutePathError):
            self.fs.create_dir("noslash")

    def test_create_file_fails_if_parent_dir_doesnt_exist(self):
        with self.assertRaises(FileNotFoundError) as cm:
            self.fs.create_file('/etc/passwd', "foo")
        self.assertTrue('/etc' in cm.exception.args[0])

    def test_create_file_succeeds_if_parent_dir_doesnt_exist_when_make_dirs_true(self):
        self.fs.create_file('/test/subdir/testfile', "foo", make_dirs=True)
        with self.fs.open('/test/subdir/testfile') as infile:
            self.assertEqual(infile.read(), 'foo')

    def test_create_file_from_str(self):
        self.fs.create_file('/test', "foo")
        with self.fs.open('/test') as infile:
            self.assertEqual(infile.read(), 'foo')

    def test_create_file_from_bytes(self):
        self.fs.create_file('/test', b"foo")
        with self.fs.open('/test', encoding=None) as infile:
            self.assertEqual(infile.read(), b'foo')

    def test_create_file_from_files(self):
        data = "foo"

        sio = StringIO(data)
        self.fs.create_file('/test', sio)
        with self.fs.open('/test') as infile:
            self.assertEqual(infile.read(), 'foo')

        bio = BytesIO(data.encode())
        self.fs.create_file('/test2', bio)
        with self.fs.open('/test2') as infile:
            self.assertEqual(infile.read(), 'foo')

    def test_create_and_read_with_different_encodings(self):
        # write str, read as utf-8 bytes
        self.fs.create_file('/test', "foo")
        with self.fs.open('/test', encoding=None) as infile:
            self.assertEqual(infile.read(), b'foo')

        # write bytes, read as utf-8-decoded str
        data = "日本語"  # Japanese for "Japanese"
        self.fs.create_file('/test2', data.encode('utf-8'))
        with self.fs.open('/test2') as infile:                    # Implicit utf-8 read
            self.assertEqual(infile.read(), data)
        with self.fs.open('/test2', encoding='utf-8') as infile:  # Explicit utf-8 read
            self.assertEqual(infile.read(), data)

    def test_open_directory_fails(self):
        self.fs.create_dir('/dir1')
        with self.assertRaises(IsADirectoryError) as cm:
            self.fs.open('/dir1')
        self.assertEqual(cm.exception.args[0], '/dir1')

    def test_delete_file(self):
        self.fs.create_file('/test', "foo")
        self.fs.delete_path('/test')
        with self.assertRaises(FileNotFoundError) as cm:
            self.fs.get_path('/test')

        # Deleting deleted files should fail as well
        with self.assertRaises(FileNotFoundError) as cm:
            self.fs.delete_path('/test')
        self.assertTrue('/test' in cm.exception.args[0])

    def test_create_dir_with_extra_args(self):
        d = self.fs.create_dir('/dir1')
        self.assertEqual(d.kwargs, {})

        d = self.fs.create_dir(
            '/dir2', permissions=0o700, user='ubuntu', user_id=1000, group='www-data', group_id=33)
        self.assertEqual(d.kwargs, {
            'permissions': 0o700,
            'user': 'ubuntu',
            'user_id': 1000,
            'group': 'www-data',
            'group_id': 33,
        })

    def test_create_file_with_extra_args(self):
        f = self.fs.create_file('/file1', 'data')
        self.assertEqual(f.kwargs, {})

        f = self.fs.create_file(
            '/file2', 'data',
            permissions=0o754, user='ubuntu', user_id=1000, group='www-data', group_id=33)
        self.assertEqual(f.kwargs, {
            'permissions': 0o754,
            'user': 'ubuntu',
            'user_id': 1000,
            'group': 'www-data',
            'group_id': 33,
        })

    def test_getattr(self):
        self.fs.create_dir('/etc/init.d', make_parents=True)

        # By path
        o = self.fs.get_path(pathlib.PurePosixPath('/etc/init.d'))
        self.assertIsInstance(o, _Directory)
        self.assertEqual(o.path, pathlib.PurePosixPath('/etc/init.d'))

        # By str
        o = self.fs.get_path('/etc/init.d')
        self.assertIsInstance(o, _Directory)
        self.assertEqual(o.path, pathlib.PurePosixPath('/etc/init.d'))

    def test_getattr_file_not_found(self):
        # Arguably this could be a KeyError given the dictionary-style access.
        # However, FileNotFoundError seems more appropriate for a filesystem, and it
        # gives a closer semantic feeling, in my opinion.
        with self.assertRaises(FileNotFoundError) as cm:
            self.fs.get_path('/nonexistent_file')
        self.assertTrue('/nonexistent_file' in cm.exception.args[0])


class TestTestingFilesystem(GenericTestingFilesystemTests, unittest.TestCase):
    def setUp(self):
        self.fs = _TestingFilesystem()

    def test_storage_mount(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.fs.add_mount('foo', '/foo', tmpdir.name)
        self.fs.create_file('/foo/bar/baz.txt', 'quux', make_dirs=True)

        tmppath = os.path.join(tmpdir.name, 'bar/baz.txt')
        self.assertTrue(os.path.exists(tmppath))
        with open(tmppath) as f:
            self.assertEqual(f.read(), 'quux')


class TestTestingStorageMount(GenericTestingFilesystemTests, unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fs = _TestingStorageMount('/', pathlib.Path(self.tmp.name))


class TestPebbleStorageAPIsUsingMocks(
        unittest.TestCase,
        _TestingPebbleClientMixin,
        _PebbleStorageAPIsTestMixin):
    def setUp(self):
        self.prefix = '/prefix'
        self.client = self.get_testing_client()
        if self.prefix:
            self.client.make_dir(self.prefix, make_parents=True)

    @unittest.skipUnless(platform.system() == 'Linux', 'Pebble runs on Linux')
    def test_container_storage_mounts(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            containers:
                c1:
                    mounts:
                        - storage: store1
                          location: /mounts/foo
                c2:
                    mounts:
                        - storage: store2
                          location: /mounts/foo
                c3:
                    mounts:
                        - storage: store1
                          location: /mounts/bar
            storage:
                store1:
                    type: filesystem
                store2:
                    type: filesystem
            ''')
        self.addCleanup(harness.cleanup)

        store_id = harness.add_storage('store1')[0]
        harness.attach_storage(store_id)

        harness.begin()
        harness.set_can_connect('c1', True)
        harness.set_can_connect('c2', True)
        harness.set_can_connect('c3', True)

        # push file to c1 storage mount, check that we can see it in charm container storage path.
        c1 = harness.model.unit.get_container('c1')
        c1_fname = 'foo.txt'
        c1_fpath = os.path.join('/mounts/foo', c1_fname)
        c1.push(c1_fpath, '42')
        self.assertTrue(c1.exists(c1_fpath))
        fpath = os.path.join(str(harness.model.storages['store1'][0].location), 'foo.txt')
        with open(fpath) as f:
            self.assertEqual('42', f.read())

        # check that the file is not visible in c2 which has a different storage mount
        c2 = harness.model.unit.get_container('c2')
        c2_fpath = os.path.join('/mounts/foo', c1_fname)
        self.assertFalse(c2.exists(c2_fpath))

        # check that the file is visible in c3 which has the same storage mount
        c3 = harness.model.unit.get_container('c3')
        c3_fpath = os.path.join('/mounts/bar', c1_fname)
        self.assertTrue(c3.exists(c3_fpath))
        with c3.pull(c3_fpath) as f:
            self.assertEqual('42', f.read())

        # test all other container file ops
        with c1.pull(c1_fpath) as f:
            self.assertEqual('42', f.read())
        files = c1.list_files(c1_fpath)
        self.assertEqual([c1_fpath], [fi.path for fi in files])
        c1.remove_path(c1_fpath)
        self.assertFalse(c1.exists(c1_fpath))

        # test detaching storage
        c1.push(c1_fpath, '42')
        self.assertTrue(c1.exists(c1_fpath))
        store1_id = harness.model.storages['store1'][0].full_id
        harness.remove_storage(store1_id)
        self.assertFalse(c1.exists(c1_fpath))

    def test_push_with_ownership(self):
        # Note: To simplify implementation, ownership is simply stored as-is with no verification.
        data = 'data'
        client = self.client
        client.push(f"{self.prefix}/file", data, user_id=1, user='foo', group_id=3, group='bar')
        file_ = client.list_files(f"{self.prefix}/file")[0]
        self.assertEqual(file_.user_id, 1)
        self.assertEqual(file_.user, 'foo')
        self.assertEqual(file_.group_id, 3)
        self.assertEqual(file_.group, 'bar')

    def test_make_dir_with_ownership(self):
        client = self.client
        client.make_dir(f"{self.prefix}/dir1", user_id=1, user="foo", group_id=3, group="bar")
        dir_ = client.list_files(f"{self.prefix}/dir1", itself=True)[0]
        self.assertEqual(dir_.user_id, 1)
        self.assertEqual(dir_.user, "foo")
        self.assertEqual(dir_.group_id, 3)
        self.assertEqual(dir_.group, "bar")


@unittest.skipUnless(os.getenv('RUN_REAL_PEBBLE_TESTS'), 'RUN_REAL_PEBBLE_TESTS not set')
class TestPebbleStorageAPIsUsingRealPebble(unittest.TestCase, _PebbleStorageAPIsTestMixin):
    def setUp(self):
        socket_path = os.getenv('PEBBLE_SOCKET')
        pebble_dir = os.getenv('PEBBLE')
        if not socket_path and pebble_dir:
            socket_path = os.path.join(pebble_dir, '.pebble.socket')
        assert socket_path and pebble_dir, 'PEBBLE must be set if RUN_REAL_PEBBLE_TESTS set'

        self.prefix = tempfile.mkdtemp(dir=pebble_dir)
        self.client = pebble.Client(socket_path=socket_path)

    def tearDown(self):
        shutil.rmtree(self.prefix)

    # Remove this entirely once the associated bug is fixed; it overrides the original test in the
    # test mixin class.
    @unittest.skip('pending resolution of https://github.com/canonical/pebble/issues/80')
    def test_make_dir_with_permission_mask(self):
        pass
