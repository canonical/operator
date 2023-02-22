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
import types
import unittest
from test.test_helpers import fake_script, fake_script_calls

import ops
from ops import model


class TestSecrets(unittest.TestCase):
    def setUp(self):
        self.model = ops.model.Model(ops.charm.CharmMeta(), ops.model._ModelBackend('myapp/0'))
        self.app = self.model.app
        self.unit = self.model.unit

    def test_app_add_secret_simple(self):
        fake_script(self, 'secret-add', 'echo secret:123')

        secret = self.app.add_secret({'foo': 'x'})
        self.assertIsInstance(secret, model.Secret)
        self.assertEqual(secret.id, 'secret:123')
        self.assertIsNone(secret.label)

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-add', '--owner', 'application', 'foo=x']])

    def test_app_add_secret_args(self):
        fake_script(self, 'secret-add', 'echo secret:234')

        expire = datetime.datetime(2022, 12, 9, 16, 17, 0)
        secret = self.app.add_secret({'foo': 'x', 'bar': 'y'}, label='lbl', description='desc',
                                     expire=expire, rotate=model.SecretRotate.HOURLY)
        self.assertEqual(secret.id, 'secret:234')
        self.assertEqual(secret.label, 'lbl')
        self.assertEqual(secret.get_content(), {'foo': 'x', 'bar': 'y'})

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-add', '--label', 'lbl', '--description', 'desc',
                           '--expire', '2022-12-09T16:17:00', '--rotate', 'hourly',
                           '--owner', 'application', 'foo=x', 'bar=y']])

    def test_unit_add_secret_simple(self):
        fake_script(self, 'secret-add', 'echo secret:345')

        secret = self.unit.add_secret({'foo': 'x'})
        self.assertIsInstance(secret, model.Secret)
        self.assertEqual(secret.id, 'secret:345')
        self.assertIsNone(secret.label)

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-add', '--owner', 'unit', 'foo=x']])

    def test_unit_add_secret_args(self):
        fake_script(self, 'secret-add', 'echo secret:456')

        expire = datetime.datetime(2022, 12, 9, 16, 22, 0)
        secret = self.unit.add_secret({'foo': 'w', 'bar': 'z'}, label='l2', description='xyz',
                                      expire=expire, rotate=model.SecretRotate.YEARLY)
        self.assertEqual(secret.id, 'secret:456')
        self.assertEqual(secret.label, 'l2')
        self.assertEqual(secret.get_content(), {'foo': 'w', 'bar': 'z'})

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-add', '--label', 'l2', '--description', 'xyz',
                           '--expire', '2022-12-09T16:22:00', '--rotate', 'yearly',
                           '--owner', 'unit', 'foo=w', 'bar=z']])

    def test_unit_add_secret_errors(self):
        # Additional add_secret tests are done in TestApplication
        errors = [
            ({'xy': 'bar'}, {}, ValueError),
            ({'foo': 'x'}, {'expire': 7}, TypeError),
        ]
        for content, kwargs, exc_type in errors:
            msg = f'expected {exc_type.__name__} when adding secret content {content}'
            with self.assertRaises(exc_type, msg=msg):
                self.unit.add_secret(content, **kwargs)

    def test_add_secret_errors(self):
        errors = [
            # Invalid content dict or types
            (None, {}, TypeError),
            ({}, {}, ValueError),
            ({b'foo', 'bar'}, {}, TypeError),
            ({3: 'bar'}, {}, TypeError),
            ({'foo': 1, 'bar': 2}, {}, TypeError),
            # Invalid content keys
            ({'xy': 'bar'}, {}, ValueError),
            ({'FOO': 'bar'}, {}, ValueError),
            ({'foo-': 'bar'}, {}, ValueError),
            ({'-foo': 'bar'}, {}, ValueError),
            # Invalid "expire" type
            ({'foo': 'x'}, {'expire': 7}, TypeError),
        ]
        for content, kwargs, exc_type in errors:
            msg = f'expected {exc_type.__name__} when adding secret content {content}'
            with self.assertRaises(exc_type, msg=msg):
                self.app.add_secret(content, **kwargs)
            with self.assertRaises(exc_type, msg=msg):
                self.unit.add_secret(content, **kwargs)

    def test_get_secret_id(self):
        fake_script(self, 'secret-get', """echo '{"foo": "g"}'""")

        secret = self.model.get_secret(id='123')
        self.assertEqual(secret.id, 'secret:123')
        self.assertIsNone(secret.label)
        self.assertEqual(secret.get_content(), {'foo': 'g'})

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-get', 'secret:123', '--format=json']])

    def test_get_secret_label(self):
        fake_script(self, 'secret-get', """echo '{"foo": "g"}'""")

        secret = self.model.get_secret(label='lbl')
        self.assertIsNone(secret.id)
        self.assertEqual(secret.label, 'lbl')
        self.assertEqual(secret.get_content(), {'foo': 'g'})

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-get', '--label', 'lbl', '--format=json']])

    def test_get_secret_id_and_label(self):
        fake_script(self, 'secret-get', """echo '{"foo": "h"}'""")

        secret = self.model.get_secret(id='123', label='l')
        self.assertEqual(secret.id, 'secret:123')
        self.assertEqual(secret.label, 'l')
        self.assertEqual(secret.get_content(), {'foo': 'h'})

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-get', 'secret:123', '--label', 'l', '--format=json']])

    def test_get_secret_no_args(self):
        with self.assertRaises(TypeError):
            self.model.get_secret()

    def test_get_secret_not_found(self):
        script = """echo 'ERROR secret "123" not found' >&2; exit 1"""
        fake_script(self, 'secret-get', script)
        fake_script(self, 'secret-info-get', script)

        with self.assertRaises(model.SecretNotFoundError):
            self.model.get_secret(id='123')

    def test_get_secret_other_error(self):
        script = """echo 'ERROR other error' >&2; exit 1"""
        fake_script(self, 'secret-get', script)
        fake_script(self, 'secret-info-get', script)

        with self.assertRaises(model.ModelError) as cm:
            self.model.get_secret(id='123')
        self.assertNotIsInstance(cm.exception, model.SecretNotFoundError)


class TestSecretInfo(unittest.TestCase):
    def test_init(self):
        info = model.SecretInfo(
            id='3',
            label='lbl',
            revision=7,
            expires=datetime.datetime(2022, 12, 9, 14, 10, 0),
            rotation=model.SecretRotate.MONTHLY,
            rotates=datetime.datetime(2023, 1, 9, 14, 10, 0),
        )
        self.assertEqual(info.id, 'secret:3')
        self.assertEqual(info.label, 'lbl')
        self.assertEqual(info.revision, 7)
        self.assertEqual(info.expires, datetime.datetime(2022, 12, 9, 14, 10, 0))
        self.assertEqual(info.rotation, model.SecretRotate.MONTHLY)
        self.assertEqual(info.rotates, datetime.datetime(2023, 1, 9, 14, 10, 0))

        self.assertTrue(repr(info).startswith('SecretInfo('))
        self.assertTrue(repr(info).endswith(')'))

    def test_from_dict(self):
        utc = datetime.timezone.utc
        info = model.SecretInfo.from_dict('secret:4', {
            'label': 'fromdict',
            'revision': 8,
            'expires': '2022-12-09T14:10:00Z',
            'rotation': 'yearly',
            'rotates': '2023-01-09T14:10:00Z',
        })
        self.assertEqual(info.id, 'secret:4')
        self.assertEqual(info.label, 'fromdict')
        self.assertEqual(info.revision, 8)
        self.assertEqual(info.expires, datetime.datetime(2022, 12, 9, 14, 10, 0, tzinfo=utc))
        self.assertEqual(info.rotation, model.SecretRotate.YEARLY)
        self.assertEqual(info.rotates, datetime.datetime(2023, 1, 9, 14, 10, 0, tzinfo=utc))

        info = model.SecretInfo.from_dict('secret:4', {
            'label': 'fromdict',
            'revision': 8,
            'rotation': 'badvalue',
        })
        self.assertEqual(info.id, 'secret:4')
        self.assertEqual(info.label, 'fromdict')
        self.assertEqual(info.revision, 8)
        self.assertIsNone(info.expires)
        self.assertIsNone(info.rotation)
        self.assertIsNone(info.rotates)

        info = model.SecretInfo.from_dict('5', {'revision': 9})
        self.assertEqual(info.id, 'secret:5')
        self.assertEqual(info.revision, 9)


class TestSecretClass(unittest.TestCase):
    maxDiff = 64 * 1024

    def setUp(self):
        self.model = ops.model.Model(ops.charm.CharmMeta(), ops.model._ModelBackend('myapp/0'))

    def make_secret(self, id=None, label=None, content=None):
        return model.Secret(self.model._backend, id=id, label=label, content=content)

    def test_id_and_label(self):
        secret = self.make_secret(id=' abc ', label='lbl')
        self.assertEqual(secret.id, 'secret:abc')
        self.assertEqual(secret.label, 'lbl')

        secret = self.make_secret(id='x')
        self.assertEqual(secret.id, 'secret:x')
        self.assertIsNone(secret.label)

        secret = self.make_secret(label='y')
        self.assertIsNone(secret.id)
        self.assertEqual(secret.label, 'y')

    def test_get_content_cached(self):
        fake_script(self, 'secret-get', """exit 1""")

        secret = self.make_secret(id='x', label='y', content={'foo': 'bar'})
        content = secret.get_content()  # will use cached content, not run secret-get
        self.assertEqual(content, {'foo': 'bar'})

        self.assertEqual(fake_script_calls(self, clear=True), [])

    def test_get_content_refresh(self):
        fake_script(self, 'secret-get', """echo '{"foo": "refreshed"}'""")

        secret = self.make_secret(id='y', content={'foo': 'bar'})
        content = secret.get_content(refresh=True)
        self.assertEqual(content, {'foo': 'refreshed'})

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-get', 'secret:y', '--refresh', '--format=json']])

    def test_get_content_uncached(self):
        fake_script(self, 'secret-get', """echo '{"foo": "notcached"}'""")

        secret = self.make_secret(id='z')
        content = secret.get_content()
        self.assertEqual(content, {'foo': 'notcached'})

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-get', 'secret:z', '--format=json']])

    def test_peek_content(self):
        fake_script(self, 'secret-get', """echo '{"foo": "peeked"}'""")

        secret = self.make_secret(id='a', label='b')
        content = secret.peek_content()
        self.assertEqual(content, {'foo': 'peeked'})

        self.assertEqual(fake_script_calls(self, clear=True),
                         [['secret-get', 'secret:a', '--label', 'b', '--peek', '--format=json']])

    def test_get_info(self):
        fake_script(self, 'secret-info-get', """echo '{"x": {"label": "y", "revision": 7}}'""")

        # Secret with ID only
        secret = self.make_secret(id='x')
        info = secret.get_info()
        self.assertEqual(info.id, 'secret:x')
        self.assertEqual(info.label, 'y')
        self.assertEqual(info.revision, 7)

        # Secret with label only
        secret = self.make_secret(label='y')
        info = secret.get_info()
        self.assertEqual(info.id, 'secret:x')
        self.assertEqual(info.label, 'y')
        self.assertEqual(info.revision, 7)

        # Secret with ID and label
        secret = self.make_secret(id='x', label='y')
        info = secret.get_info()
        self.assertEqual(info.id, 'secret:x')
        self.assertEqual(info.label, 'y')
        self.assertEqual(info.revision, 7)

        self.assertEqual(
            fake_script_calls(self, clear=True),
            [
                ['secret-info-get', 'secret:x', '--format=json'],
                ['secret-info-get', '--label', 'y', '--format=json'],
                ['secret-info-get', 'secret:x', '--format=json'],
            ])

    def test_set_content(self):
        fake_script(self, 'secret-set', """exit 0""")
        fake_script(self, 'secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(id='x')
        secret.set_content({'foo': 'bar'})

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(label='y')
        self.assertIsNone(secret.id)
        secret.set_content({'bar': 'foo'})
        self.assertEqual(secret.id, 'secret:z')

        with self.assertRaises(ValueError):
            secret.set_content({'s': 't'})  # ensure it validates content (key too short)

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['secret-set', 'secret:x', 'foo=bar'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-set', 'secret:z', 'bar=foo'],
        ])

    def test_set_info(self):
        fake_script(self, 'secret-set', """exit 0""")
        fake_script(self, 'secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(id='x')
        expire = datetime.datetime(2022, 12, 9, 16, 59, 0)
        secret.set_info(
            label='lab',
            description='desc',
            expire=expire,
            rotate=model.SecretRotate.MONTHLY,
        )

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(label='y')
        self.assertIsNone(secret.id)
        secret.set_info(label='lbl')
        self.assertEqual(secret.id, 'secret:z')

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['secret-set', 'secret:x', '--label', 'lab', '--description', 'desc',
             '--expire', '2022-12-09T16:59:00', '--rotate', 'monthly'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-set', 'secret:z', '--label', 'lbl'],
        ])

        with self.assertRaises(TypeError):
            secret.set_info()  # no args provided

    def test_grant(self):
        fake_script(self, 'secret-grant', """exit 0""")
        fake_script(self, 'secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(id='x')
        secret.grant(types.SimpleNamespace(id=123))
        secret.grant(types.SimpleNamespace(id=234), unit=types.SimpleNamespace(name='app/0'))

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(label='y')
        self.assertIsNone(secret.id)
        secret.grant(types.SimpleNamespace(id=345))
        self.assertEqual(secret.id, 'secret:z')

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['secret-grant', 'secret:x', '--relation', '123'],
            ['secret-grant', 'secret:x', '--relation', '234', '--unit', 'app/0'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-grant', 'secret:z', '--relation', '345'],
        ])

    def test_revoke(self):
        fake_script(self, 'secret-revoke', """exit 0""")
        fake_script(self, 'secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(id='x')
        secret.revoke(types.SimpleNamespace(id=123))
        secret.revoke(types.SimpleNamespace(id=234), unit=types.SimpleNamespace(name='app/0'))

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(label='y')
        self.assertIsNone(secret.id)
        secret.revoke(types.SimpleNamespace(id=345))
        self.assertEqual(secret.id, 'secret:z')

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['secret-revoke', 'secret:x', '--relation', '123'],
            ['secret-revoke', 'secret:x', '--relation', '234', '--unit', 'app/0'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-revoke', 'secret:z', '--relation', '345'],
        ])

    def test_remove_revision(self):
        fake_script(self, 'secret-remove', """exit 0""")
        fake_script(self, 'secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(id='x')
        secret.remove_revision(123)

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(label='y')
        self.assertIsNone(secret.id)
        secret.remove_revision(234)
        self.assertEqual(secret.id, 'secret:z')

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['secret-remove', 'secret:x', '--revision', '123'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-remove', 'secret:z', '--revision', '234'],
        ])

    def test_remove_all_revisions(self):
        fake_script(self, 'secret-remove', """exit 0""")
        fake_script(self, 'secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(id='x')
        secret.remove_all_revisions()

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(label='y')
        self.assertIsNone(secret.id)
        secret.remove_all_revisions()
        self.assertEqual(secret.id, 'secret:z')

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['secret-remove', 'secret:x'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-remove', 'secret:z'],
        ])
