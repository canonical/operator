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

import json
import os
import pathlib
import tempfile
import textwrap
import unittest
from collections import OrderedDict
from test.test_helpers import fake_script, fake_script_calls

import ops


class TestModelBackend(unittest.TestCase):
    def setUp(self):
        self._backend = None

    @property
    def backend(self):
        if self._backend is None:
            self._backend = ops.model._ModelBackend('myapp/0')
        return self._backend

    def test_relation_get_set_is_app_arg(self):
        # No is_app provided.
        with self.assertRaises(TypeError):
            self.backend.relation_set(1, 'fookey', 'barval')

        with self.assertRaises(TypeError):
            self.backend.relation_get(1, 'fooentity')

        # Invalid types for is_app.
        for is_app_v in [None, 1, 2.0, 'a', b'beef']:
            with self.assertRaises(TypeError):
                self.backend.relation_set(1, 'fookey', 'barval', is_app=is_app_v)

            with self.assertRaises(TypeError):
                self.backend.relation_get(1, 'fooentity', is_app=is_app_v)

    def test_is_leader_refresh(self):
        meta = ops.charm.CharmMeta.from_yaml('''
            name: myapp
        ''')
        model = ops.model.Model(meta, self.backend)
        fake_script(self, 'is-leader', 'echo false')
        self.assertFalse(model.unit.is_leader())

        # Change the leadership status
        fake_script(self, 'is-leader', 'echo true')
        # If you don't force it, we don't check, so we won't see the change
        self.assertFalse(model.unit.is_leader())
        # If we force a recheck, then we notice
        self.backend._leader_check_time = None
        self.assertTrue(model.unit.is_leader())

        # Force a recheck without changing the leadership status.
        fake_script(self, 'is-leader', 'echo true')
        self.backend._leader_check_time = None
        self.assertTrue(model.unit.is_leader())

    def test_relation_tool_errors(self):
        self.addCleanup(os.environ.pop, 'JUJU_VERSION', None)
        os.environ['JUJU_VERSION'] = '2.8.0'
        err_msg = 'ERROR invalid value "$2" for option -r: relation not found'

        test_cases = [(
            lambda: fake_script(self, 'relation-list', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.relation_list(3),
            ops.model.ModelError,
            [['relation-list', '-r', '3', '--format=json']],
        ), (
            lambda: fake_script(self, 'relation-list', f'echo {err_msg} >&2 ; exit 2'),
            lambda: self.backend.relation_list(3),
            ops.model.RelationNotFoundError,
            [['relation-list', '-r', '3', '--format=json']],
        ), (
            lambda: fake_script(self, 'relation-set', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=False),
            ops.model.ModelError,
            [['relation-set', '-r', '3', '--file', '-']],
        ), (
            lambda: fake_script(self, 'relation-set', f'echo {err_msg} >&2 ; exit 2'),
            lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=False),
            ops.model.RelationNotFoundError,
            [['relation-set', '-r', '3', '--file', '-']],
        ), (
            lambda: None,
            lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=True),
            ops.model.RelationNotFoundError,
            [['relation-set', '-r', '3', '--app', '--file', '-']],
        ), (
            lambda: fake_script(self, 'relation-get', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.relation_get(3, 'remote/0', is_app=False),
            ops.model.ModelError,
            [['relation-get', '-r', '3', '-', 'remote/0', '--format=json']],
        ), (
            lambda: fake_script(self, 'relation-get', f'echo {err_msg} >&2 ; exit 2'),
            lambda: self.backend.relation_get(3, 'remote/0', is_app=False),
            ops.model.RelationNotFoundError,
            [['relation-get', '-r', '3', '-', 'remote/0', '--format=json']],
        ), (
            lambda: None,
            lambda: self.backend.relation_get(3, 'remote/0', is_app=True),
            ops.model.RelationNotFoundError,
            [['relation-get', '-r', '3', '-', 'remote/0', '--app', '--format=json']],
        )]

        for i, (do_fake, run, exception, calls) in enumerate(test_cases):
            with self.subTest(i):
                do_fake()
                with self.assertRaises(exception):
                    run()
                self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_relation_get_juju_version_quirks(self):
        self.addCleanup(os.environ.pop, 'JUJU_VERSION', None)

        fake_script(self, 'relation-get', '''echo '{"foo": "bar"}' ''')

        # on 2.7.0+, things proceed as expected
        for v in ['2.8.0', '2.7.0']:
            with self.subTest(v):
                os.environ['JUJU_VERSION'] = v
                rel_data = self.backend.relation_get(1, 'foo/0', is_app=True)
                self.assertEqual(rel_data, {"foo": "bar"})
                calls = [' '.join(i) for i in fake_script_calls(self, clear=True)]
                self.assertEqual(calls, ['relation-get -r 1 - foo/0 --app --format=json'])

        # before 2.7.0, it just fails (no --app support)
        os.environ['JUJU_VERSION'] = '2.6.9'
        with self.assertRaisesRegex(RuntimeError, 'not supported on Juju version 2.6.9'):
            self.backend.relation_get(1, 'foo/0', is_app=True)
        self.assertEqual(fake_script_calls(self), [])

    def test_relation_set_juju_version_quirks(self):
        self.addCleanup(os.environ.pop, 'JUJU_VERSION', None)

        # on 2.7.0+, things proceed as expected
        for v in ['2.8.0', '2.7.0']:
            with self.subTest(v):
                t = tempfile.NamedTemporaryFile()
                try:
                    fake_script(self, 'relation-set', textwrap.dedent("""
                        cat >> {}
                        """).format(pathlib.Path(t.name).as_posix()))
                    os.environ['JUJU_VERSION'] = v
                    self.backend.relation_set(1, 'foo', 'bar', is_app=True)
                    calls = [' '.join(i) for i in fake_script_calls(self, clear=True)]
                    self.assertEqual(calls, ['relation-set -r 1 --app --file -'])
                    t.seek(0)
                    content = t.read()
                finally:
                    t.close()
                decoded = content.decode('utf-8').replace('\r\n', '\n')
                self.assertEqual(decoded, 'foo: bar\n')

        # before 2.7.0, it just fails always (no --app support)
        os.environ['JUJU_VERSION'] = '2.6.9'
        with self.assertRaisesRegex(RuntimeError, 'not supported on Juju version 2.6.9'):
            self.backend.relation_set(1, 'foo', 'bar', is_app=True)
        self.assertEqual(fake_script_calls(self), [])

    def test_status_get(self):
        # taken from actual Juju output
        content = '{"message": "", "status": "unknown", "status-data": {}}'
        fake_script(self, 'status-get', f"echo '{content}'")
        s = self.backend.status_get(is_app=False)
        self.assertEqual(s['status'], "unknown")
        self.assertEqual(s['message'], "")
        # taken from actual Juju output
        content = textwrap.dedent("""
            {
                "application-status": {
                    "message": "installing",
                    "status": "maintenance",
                    "status-data": {},
                    "units": {
                        "uo/0": {
                            "message": "",
                            "status": "active",
                            "status-data": {}
                        }
                    }
                }
            }
            """)
        fake_script(self, 'status-get', f"echo '{content}'")
        s = self.backend.status_get(is_app=True)
        self.assertEqual(s['status'], "maintenance")
        self.assertEqual(s['message'], "installing")
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['status-get', '--include-data', '--application=False', '--format=json'],
            ['status-get', '--include-data', '--application=True', '--format=json'],
        ])

    def test_status_is_app_forced_kwargs(self):
        fake_script(self, 'status-get', 'exit 1')
        fake_script(self, 'status-set', 'exit 1')

        test_cases = (
            lambda: self.backend.status_get(False),
            lambda: self.backend.status_get(True),
            lambda: self.backend.status_set('active', '', False),
            lambda: self.backend.status_set('active', '', True),
        )

        for case in test_cases:
            with self.assertRaises(TypeError):
                case()

    def test_local_set_invalid_status(self):
        # juju returns exit code 1 if you ask to set status to 'unknown' or 'error'
        meta = ops.charm.CharmMeta.from_yaml('''
            name: myapp
        ''')
        model = ops.model.Model(meta, self.backend)
        fake_script(self, 'status-set', 'exit 1')
        fake_script(self, 'is-leader', 'echo true')

        with self.assertRaises(ops.model.ModelError):
            model.unit.status = ops.model.UnknownStatus()
        with self.assertRaises(ops.model.ModelError):
            model.unit.status = ops.model.ErrorStatus()

        self.assertEqual(fake_script_calls(self, True), [
            ['status-set', '--application=False', 'unknown', ''],
            ['status-set', '--application=False', 'error', ''],
        ])

        with self.assertRaises(ops.model.ModelError):
            model.app.status = ops.model.UnknownStatus()
        with self.assertRaises(ops.model.ModelError):
            model.app.status = ops.model.ErrorStatus()

        # A leadership check is needed for application status.
        self.assertEqual(fake_script_calls(self, True), [
            ['is-leader', '--format=json'],
            ['status-set', '--application=True', 'unknown', ''],
            ['status-set', '--application=True', 'error', ''],
        ])

    def test_local_get_status(self):
        for name, expected_cls in (
                ("active", ops.model.ActiveStatus),
                ("waiting", ops.model.WaitingStatus),
                ("blocked", ops.model.BlockedStatus),
                ("maintenance", ops.model.MaintenanceStatus),
                ("error", ops.model.ErrorStatus),
        ):
            meta = ops.charm.CharmMeta.from_yaml('''
                name: myapp
            ''')
            model = ops.model.Model(meta, self.backend)

            with self.subTest(name):
                content = json.dumps({
                    "message": "foo",
                    "status": name,
                    "status-data": {},
                })
                fake_script(self, 'status-get', f"echo '{content}'")

                self.assertIsInstance(model.unit.status, expected_cls)
                self.assertEqual(model.unit.status.name, name)
                self.assertEqual(model.unit.status.message, "foo")

                content = json.dumps({
                    "application-status": {
                        "message": "bar",
                        "status": name,
                        "status-data": {},
                    }
                })
                fake_script(self, 'status-get', f"echo '{content}'")
                fake_script(self, 'is-leader', 'echo true')

                self.assertIsInstance(model.app.status, expected_cls)
                self.assertEqual(model.app.status.name, name)
                self.assertEqual(model.app.status.message, "bar")

    def test_status_set_is_app_not_bool_raises(self):
        for is_app_v in [None, 1, 2.0, 'a', b'beef', object]:
            with self.assertRaises(TypeError):
                self.backend.status_set(ops.model.ActiveStatus, is_app=is_app_v)

    def test_storage_tool_errors(self):
        test_cases = [(
            lambda: fake_script(self, 'storage-list', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_list('foobar'),
            ops.model.ModelError,
            [['storage-list', 'foobar', '--format=json']],
        ), (
            lambda: fake_script(self, 'storage-get', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_get('foobar', 'someattr'),
            ops.model.ModelError,
            [['storage-get', '-s', 'foobar', 'someattr', '--format=json']],
        ), (
            lambda: fake_script(self, 'storage-add', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_add('foobar', count=2),
            ops.model.ModelError,
            [['storage-add', 'foobar=2']],
        ), (
            lambda: fake_script(self, 'storage-add', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_add('foobar', count=object),
            TypeError,
            [],
        ), (
            lambda: fake_script(self, 'storage-add', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_add('foobar', count=True),
            TypeError,
            [],
        )]
        for do_fake, run, exception, calls in test_cases:
            do_fake()
            with self.assertRaises(exception):
                run()
            self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_network_get(self):
        network_get_out = '''{
  "bind-addresses": [
    {
      "mac-address": "",
      "interface-name": "",
      "addresses": [
        {
          "hostname": "",
          "value": "192.0.2.2",
          "cidr": ""
        }
      ]
    }
  ],
  "egress-subnets": [
    "192.0.2.2/32"
  ],
  "ingress-addresses": [
    "192.0.2.2"
  ]
}'''
        fake_script(self, 'network-get',
                    f'''[ "$1" = deadbeef ] && echo '{network_get_out}' || exit 1''')
        network_info = self.backend.network_get('deadbeef')
        self.assertEqual(network_info, json.loads(network_get_out))
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['network-get', 'deadbeef', '--format=json']])

        network_info = self.backend.network_get('deadbeef', 1)
        self.assertEqual(network_info, json.loads(network_get_out))
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['network-get', 'deadbeef', '-r', '1', '--format=json']])

    def test_network_get_errors(self):
        err_no_endpoint = 'ERROR no network config found for binding "$2"'
        err_no_rel = 'ERROR invalid value "$3" for option -r: relation not found'

        test_cases = [(
            lambda: fake_script(self, 'network-get',
                                f'echo {err_no_endpoint} >&2 ; exit 1'),
            lambda: self.backend.network_get("deadbeef"),
            ops.model.ModelError,
            [['network-get', 'deadbeef', '--format=json']],
        ), (
            lambda: fake_script(self, 'network-get', f'echo {err_no_rel} >&2 ; exit 2'),
            lambda: self.backend.network_get("deadbeef", 3),
            ops.model.RelationNotFoundError,
            [['network-get', 'deadbeef', '-r', '3', '--format=json']],
        )]
        for do_fake, run, exception, calls in test_cases:
            do_fake()
            with self.assertRaises(exception):
                run()
            self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_action_get_error(self):
        fake_script(self, 'action-get', '')
        fake_script(self, 'action-get', 'echo fooerror >&2 ; exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.action_get()
        calls = [['action-get', '--format=json']]
        self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_action_set_error(self):
        fake_script(self, 'action-get', '')
        fake_script(self, 'action-set', 'echo fooerror >&2 ; exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.action_set(OrderedDict([('foo', 'bar'), ('dead', 'beef cafe')]))
        self.assertCountEqual(
            ["action-set", "dead=beef cafe", "foo=bar"], fake_script_calls(self, clear=True)[0])

    def test_action_log_error(self):
        fake_script(self, 'action-get', '')
        fake_script(self, 'action-log', 'echo fooerror >&2 ; exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.action_log('log-message')
        calls = [["action-log", "log-message"]]
        self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_action_get(self):
        fake_script(self, 'action-get', """echo '{"foo-name": "bar", "silent": false}'""")
        params = self.backend.action_get()
        self.assertEqual(params['foo-name'], 'bar')
        self.assertEqual(params['silent'], False)
        self.assertEqual(fake_script_calls(self), [['action-get', '--format=json']])

    def test_action_set(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-set', 'exit 0')
        self.backend.action_set({'x': 'dead beef', 'y': 1})
        self.assertCountEqual(['action-set', 'x=dead beef', 'y=1'], fake_script_calls(self)[0])

    def test_action_set_key_validation(self):
        with self.assertRaises(ValueError):
            self.backend.action_set({'X': 'dead beef', 'y': 1})
        with self.assertRaises(ValueError):
            self.backend.action_set({'some&key': 'dead beef', 'y': 1})
        with self.assertRaises(ValueError):
            self.backend.action_set({'someKey': 'dead beef', 'y': 1})
        with self.assertRaises(ValueError):
            self.backend.action_set({'some_key': 'dead beef', 'y': 1})

    def test_action_set_nested(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-set', 'exit 0')
        self.backend.action_set({'a': {'b': 1, 'c': 2}, 'd': 3})
        self.assertCountEqual(['action-set', 'a.b=1', 'a.c=2', 'd=3'], fake_script_calls(self)[0])

    def test_action_set_more_nested(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-set', 'exit 0')
        self.backend.action_set({'a': {'b': 1, 'c': 2, 'd': {'e': 3}}, 'f': 4})
        self.assertCountEqual(
            ['action-set', 'a.b=1', 'a.c=2', 'a.d.e=3', 'f=4'], fake_script_calls(self)[0])

    def test_action_set_dotted_dict(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-set', 'exit 0')
        self.backend.action_set({'a.b': 1, 'a': {'c': 2}, 'd': 3})
        self.assertCountEqual(['action-set', 'a.b=1', 'a.c=2', 'd=3'], fake_script_calls(self)[0])

    def test_action_set_duplicated_keys(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-set', 'exit 0')
        with self.assertRaises(ValueError):
            self.backend.action_set({'a.b': 1, 'a': {'b': 2}, 'd': 3})
        with self.assertRaises(ValueError):
            self.backend.action_set({'a': {'b': 1, 'c': 2, 'd': {'e': 3}}, 'f': 4, 'a.d.e': 'foo'})

    def test_action_fail(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-fail', 'exit 0')
        self.backend.action_fail('error 42')
        self.assertEqual(fake_script_calls(self), [['action-fail', 'error 42']])

    def test_action_log(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-log', 'exit 0')
        self.backend.action_log('progress: 42%')
        self.assertEqual(fake_script_calls(self), [['action-log', 'progress: 42%']])

    def test_application_version_set(self):
        fake_script(self, 'application-version-set', 'exit 0')
        self.backend.application_version_set('1.2b3')
        self.assertEqual(fake_script_calls(self), [['application-version-set', '--', '1.2b3']])

    def test_application_version_set_invalid(self):
        fake_script(self, 'application-version-set', 'exit 0')
        with self.assertRaises(TypeError):
            self.backend.application_version_set(2)
        with self.assertRaises(TypeError):
            self.backend.application_version_set()
        self.assertEqual(fake_script_calls(self), [])

    def test_juju_log(self):
        fake_script(self, 'juju-log', 'exit 0')
        self.backend.juju_log('WARNING', 'foo')
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['juju-log', '--log-level', 'WARNING', '--', 'foo']])

        with self.assertRaises(TypeError):
            self.backend.juju_log('DEBUG')
        self.assertEqual(fake_script_calls(self, clear=True), [])

        fake_script(self, 'juju-log', 'exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.juju_log('BAR', 'foo')
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['juju-log', '--log-level', 'BAR', '--', 'foo']])

    def test_valid_metrics(self):
        fake_script(self, 'add-metric', 'exit 0')
        test_cases = [(
            OrderedDict([('foo', 42), ('b-ar', 4.5), ('ba_-z', 4.5), ('a', 1)]),
            OrderedDict([('de', 'ad'), ('be', 'ef_ -')]),
            [['add-metric', '--labels', 'de=ad,be=ef_ -',
              'foo=42', 'b-ar=4.5', 'ba_-z=4.5', 'a=1']]
        ), (
            OrderedDict([('foo1', 0), ('b2r', 4.5)]),
            OrderedDict([('d3', 'aд'), ('b33f', '3_ -')]),
            [['add-metric', '--labels', 'd3=aд,b33f=3_ -', 'foo1=0', 'b2r=4.5']],
        )]
        for metrics, labels, expected_calls in test_cases:
            self.backend.add_metrics(metrics, labels)
            self.assertEqual(fake_script_calls(self, clear=True), expected_calls)

    def test_invalid_metric_names(self):
        invalid_inputs = [
            ({'': 4.2}, {}),
            ({'1': 4.2}, {}),
            ({'1': -4.2}, {}),
            ({'123': 4.2}, {}),
            ({'1foo': 4.2}, {}),
            ({'-foo': 4.2}, {}),
            ({'_foo': 4.2}, {}),
            ({'foo-': 4.2}, {}),
            ({'foo_': 4.2}, {}),
            ({'a-': 4.2}, {}),
            ({'a_': 4.2}, {}),
            ({'BAЯ': 4.2}, {}),
        ]
        for metrics, labels in invalid_inputs:
            with self.assertRaises(ops.model.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_values(self):
        invalid_inputs = [
            ({'a': float('+inf')}, {}),
            ({'a': float('-inf')}, {}),
            ({'a': float('nan')}, {}),
            ({'foo': 'bar'}, {}),
            ({'foo': '1O'}, {}),
        ]
        for metrics, labels in invalid_inputs:
            with self.assertRaises(ops.model.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_labels(self):
        invalid_inputs = [
            ({'foo': 4.2}, {'': 'baz'}),
            ({'foo': 4.2}, {',bar': 'baz'}),
            ({'foo': 4.2}, {'b=a=r': 'baz'}),
            ({'foo': 4.2}, {'BAЯ': 'baz'}),
        ]
        for metrics, labels in invalid_inputs:
            with self.assertRaises(ops.model.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_label_values(self):
        invalid_inputs = [
            ({'foo': 4.2}, {'bar': ''}),
            ({'foo': 4.2}, {'bar': 'b,az'}),
            ({'foo': 4.2}, {'bar': 'b=az'}),
        ]
        for metrics, labels in invalid_inputs:
            with self.assertRaises(ops.model.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_relation_remote_app_name_env(self):
        self.addCleanup(os.environ.pop, 'JUJU_RELATION_ID', None)
        self.addCleanup(os.environ.pop, 'JUJU_REMOTE_APP', None)

        os.environ['JUJU_RELATION_ID'] = 'x:5'
        os.environ['JUJU_REMOTE_APP'] = 'remoteapp1'
        self.assertEqual(self.backend.relation_remote_app_name(5), 'remoteapp1')
        os.environ['JUJU_RELATION_ID'] = '5'
        self.assertEqual(self.backend.relation_remote_app_name(5), 'remoteapp1')

    def test_relation_remote_app_name_script_success(self):
        self.addCleanup(os.environ.pop, 'JUJU_RELATION_ID', None)
        self.addCleanup(os.environ.pop, 'JUJU_REMOTE_APP', None)

        # JUJU_RELATION_ID and JUJU_REMOTE_APP both unset
        fake_script(self, 'relation-list', r"""
echo '"remoteapp2"'
""")
        self.assertEqual(self.backend.relation_remote_app_name(1), 'remoteapp2')
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['relation-list', '-r', '1', '--app', '--format=json'],
        ])

        # JUJU_RELATION_ID set but JUJU_REMOTE_APP unset
        os.environ['JUJU_RELATION_ID'] = 'x:5'
        self.assertEqual(self.backend.relation_remote_app_name(5), 'remoteapp2')

        # JUJU_RELATION_ID unset but JUJU_REMOTE_APP set
        del os.environ['JUJU_RELATION_ID']
        os.environ['JUJU_REMOTE_APP'] = 'remoteapp1'
        self.assertEqual(self.backend.relation_remote_app_name(5), 'remoteapp2')

        # Both set, but JUJU_RELATION_ID a different relation
        os.environ['JUJU_RELATION_ID'] = 'x:6'
        self.assertEqual(self.backend.relation_remote_app_name(5), 'remoteapp2')

    def test_relation_remote_app_name_script_errors(self):
        fake_script(self, 'relation-list', r"""
echo "ERROR invalid value \"6\" for option -r: relation not found" >&2  # NOQA
exit 2
""")
        self.assertIs(self.backend.relation_remote_app_name(6), None)
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['relation-list', '-r', '6', '--app', '--format=json'],
        ])

        fake_script(self, 'relation-list', r"""
echo "ERROR option provided but not defined: --app" >&2
exit 2
""")
        self.assertIs(self.backend.relation_remote_app_name(6), None)
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['relation-list', '-r', '6', '--app', '--format=json'],
        ])
