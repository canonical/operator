# Copyright 2024 Canonical Ltd.
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

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ops.jujucontext import JujuContext
from ops.jujuversion import JujuVersion


class TestJujuContext:
    def test_both_str_and_int_fields_default_to_none(self):
        juju_context = JujuContext._from_dict({'JUJU_VERSION': '0.0.0'})
        assert juju_context.action_name is None
        assert juju_context.relation_id is None

    def test_parsing_int_fields(self):
        juju_context = JujuContext._from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_RELATION_ID': 'x:42',
        })
        assert juju_context.relation_id == 42

    def test_parsing_secret_revision_as_int(self):
        juju_context = JujuContext._from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_SECRET_REVISION': '42',
        })
        assert juju_context.secret_revision == 42

    def test_parsing_juju_debug_as_bool(self):
        juju_context = JujuContext._from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_DEBUG': 'true',
        })
        assert juju_context.debug is True

    def test_parsing_juju_debug_at_as_set(self):
        juju_context = JujuContext._from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_DEBUG_AT': 'all,hook',
        })
        assert juju_context.debug_at == set(('all', 'hook'))

    def test_parsing_juju_charm_dir(self):
        juju_context = JujuContext._from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_CHARM_DIR': '/dir',
        })
        assert juju_context.charm_dir == Path('/dir')

    def test_parsing_juju_charm_dir_not_set(self):
        juju_context = JujuContext._from_dict({'JUJU_VERSION': '0.0.0'})
        assert juju_context.charm_dir == Path(f'{__file__}/../../..').resolve()

    def test_parsing_juju_version(self):
        juju_context = JujuContext._from_dict({'JUJU_VERSION': '3.4.0'})
        assert juju_context.version == JujuVersion('3.4.0')

    def test_no_juju_version_provided(self):
        # Note that this only happens in the restricted context events, so can
        # be removed once ops requires Juju 4.
        juju_context = JujuContext._from_dict({})
        assert juju_context.version == JujuVersion('0.0.0')

    def test_parsing_storage_id_to_name(self):
        juju_context = JujuContext._from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_STORAGE_ID': 'my-storage/1',
        })
        assert juju_context.storage_name == 'my-storage'

    def test_parsing_all_str_fields(self):
        env = {
            'JUJU_ACTION_NAME': 'backup',
            'JUJU_ACTION_UUID': '1',
            'JUJU_DISPATCH_PATH': 'actions/do-something',
            'JUJU_MODEL_NAME': 'foo',
            'JUJU_MODEL_UUID': 'cdac5656-2423-4388-8f30-41854b4cca7d',
            'JUJU_NOTICE_ID': '1',
            'JUJU_NOTICE_KEY': 'example.com/a',
            'JUJU_NOTICE_TYPE': 'custom',
            'JUJU_PEBBLE_CHECK_NAME': 'http-check',
            'JUJU_DEPARTING_UNIT': 'remote/42',
            'JUJU_RELATION': 'database',
            'JUJU_REMOTE_APP': 'remoteapp1',
            'JUJU_REMOTE_UNIT': 'remoteapp1/0',
            'JUJU_SECRET_ID': 'secret:dcc7aa9c-7202-4da6-8d5f-0fbbaa4e1a41',
            'JUJU_SECRET_LABEL': 'db-password',
            'JUJU_UNIT_NAME': '42',
            'JUJU_VERSION': '0.0.0',
            'JUJU_WORKLOAD_NAME': 'workload',
        }

        juju_context = JujuContext._from_dict(env)

        assert juju_context.action_name == 'backup'
        assert juju_context.action_uuid == '1'
        assert juju_context.dispatch_path == 'actions/do-something'
        assert juju_context.model_name == 'foo'
        assert juju_context.model_uuid == 'cdac5656-2423-4388-8f30-41854b4cca7d'
        assert juju_context.notice_id == '1'
        assert juju_context.notice_key == 'example.com/a'
        assert juju_context.notice_type == 'custom'
        assert juju_context.pebble_check_name == 'http-check'
        assert juju_context.relation_departing_unit_name == 'remote/42'
        assert juju_context.relation_name == 'database'
        assert juju_context.remote_app_name == 'remoteapp1'
        assert juju_context.remote_unit_name == 'remoteapp1/0'
        assert juju_context.secret_id == 'secret:dcc7aa9c-7202-4da6-8d5f-0fbbaa4e1a41'
        assert juju_context.secret_label == 'db-password'
        assert juju_context.unit_name == '42'
        assert juju_context.workload_name == 'workload'


_valid_minimal = {
    'JUJU_DISPATCH_PATH': 'hooks/install',
    'JUJU_HOOK_NAME': 'install',
    'JUJU_MODEL_NAME': 'foo',
    'JUJU_MODEL_UUID': 'cdac5656-2423-4388-8f30-41854b4cca7d',
    'JUJU_UNIT_NAME': '42',
    'JUJU_VERSION': '3.4.0',
}


def test_context_from_os_environ(monkeypatch: pytest.MonkeyPatch):
    with monkeypatch.context() as m:
        m.setattr(os, 'environ', _valid_minimal)
        juju_context = JujuContext.from_environ()
    assert juju_context.dispatch_path == 'hooks/install'
    assert juju_context.hook_name == 'install'
    assert juju_context.model_name == 'foo'
    assert juju_context.model_uuid == 'cdac5656-2423-4388-8f30-41854b4cca7d'
    assert juju_context.unit_name == '42'
    assert juju_context.version == JujuVersion('3.4.0')


@pytest.mark.parametrize(
    'event',
    ['install', 'start', 'stop', 'remove', 'config-changed', 'update-status', 'leader-elected'],
)
@pytest.mark.parametrize(
    'missing',
    [
        'JUJU_DISPATCH_PATH',
        'JUJU_HOOK_NAME',
        'JUJU_MODEL_NAME',
        'JUJU_MODEL_UUID',
        'JUJU_UNIT_NAME',
        'JUJU_VERSION',
    ],
)
def test_invalid_context_from_environ_simple(event: str, missing: str):
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = event
    del environ[missing]
    with pytest.raises(ValueError):
        JujuContext.from_environ(environ)


@pytest.mark.parametrize(
    'event,additional_env',
    [
        ('secret-changed', {}),
        ('secret-rotate', {}),
        ('secret-remove', {'JUJU_SECRET_ID': 'secret:1'}),
        ('secret-expired', {'JUJU_SECRET_ID': 'secret:1'}),
        ('a-workload-pebble-ready', {}),
        ('a-workload-pebble-check-failed', {'JUJU_WORKLOAD_NAME': 'a-workload'}),
        ('a-workload-pebble-check-recovered', {'JUJU_PEBBLE_CHECK_NAME': 'chk1'}),
        ('a-workload-pebble-custom-notice', {}),
        ('storage-1-storage-attached', {}),
        ('storage-1-storage-detaching', {}),
        ('the-act', {'JUJU_DISPATCH_PATH': 'actions/the-act', 'JUJU_HOOK_NAME': ''}),
        ('some-rel-relation-created', {}),
        ('some-rel-relation-joined', {}),
        ('some-rel-relation-changed', {}),
        ('some-rel-relation-departed', {}),
        ('some-rel-relation-broken', {}),
    ],
)
def test_invalid_context_from_environ(event: str, additional_env: dict[str, str]):
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = event
    environ.update(additional_env)
    with pytest.raises(ValueError):
        JujuContext.from_environ(environ)


@pytest.mark.parametrize(
    'event',
    [
        'install',
        'start',
        'stop',
        'remove',
        'config-changed',
        'update-status',
        'upgrade-charm',
        'leader-elected',
    ],
)
def test_from_environ_simple(event: str):
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = event
    environ['JUJU_DISPATCH_PATH'] = f'hooks/{event}'
    context = JujuContext.from_environ(environ)
    assert context.dispatch_path == f'hooks/{event}'
    assert context.hook_name == event
    assert context.model_name == 'foo'
    assert context.model_uuid == 'cdac5656-2423-4388-8f30-41854b4cca7d'
    assert context.unit_name == '42'
    assert context.version == JujuVersion('3.4.0')


@pytest.mark.parametrize(
    'event,additional_env',
    [
        ('secret-changed', {'JUJU_SECRET_ID': 'secret:1'}),
        ('secret-rotate', {'JUJU_SECRET_ID': 'secret:1'}),
        ('secret-remove', {'JUJU_SECRET_ID': 'secret:1', 'JUJU_SECRET_REVISION': '1'}),
        ('secret-expired', {'JUJU_SECRET_ID': 'secret:1', 'JUJU_SECRET_REVISION': '1'}),
    ],
)
def test_from_environ_secret(event: str, additional_env: dict[str, str]):
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = event
    environ['JUJU_DISPATCH_PATH'] = f'hooks/{event}'
    environ.update(additional_env)
    context = JujuContext.from_environ(environ)
    assert context.secret_id == 'secret:1'
    if 'JUJU_SECRET_REVISION' in additional_env:
        assert context.secret_revision == 1


def test_from_environ_action():
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = ''
    environ['JUJU_DISPATCH_PATH'] = 'actions/my-act'
    environ['JUJU_ACTION_NAME'] = 'my-act'
    environ['JUJU_ACTION_UUID'] = '1'
    context = JujuContext.from_environ(environ)
    assert context.action_name == 'my-act'
    assert context.action_uuid == '1'


def test_from_environ_pebble_ready():
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = 'a-workload-pebble-ready'
    environ['JUJU_DISPATCH_PATH'] = 'hooks/a-workload-pebble-ready'
    environ['JUJU_WORKLOAD_NAME'] = 'a-workload'
    context = JujuContext.from_environ(environ)
    assert context.workload_name == 'a-workload'


def test_from_environ_pebble_notice():
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = 'a-workload-pebble-custom-notice'
    environ['JUJU_DISPATCH_PATH'] = 'hooks/a-workload-pebble-custom-notice'
    environ['JUJU_WORKLOAD_NAME'] = 'a-workload'
    environ['JUJU_NOTICE_ID'] = '1'
    environ['JUJU_NOTICE_KEY'] = 'example.com/k'
    environ['JUJU_NOTICE_TYPE'] = 'custom'
    context = JujuContext.from_environ(environ)
    assert context.workload_name == 'a-workload'
    assert context.notice_id == '1'
    assert context.notice_key == 'example.com/k'
    assert context.notice_type == 'custom'


@pytest.mark.parametrize(
    'event', ['a-workload-pebble-check-failed', 'a-workload-pebble-check-recovered']
)
def test_from_environ_pebble_check(event: str):
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = event
    environ['JUJU_DISPATCH_PATH'] = f'hooks/{event}'
    environ['JUJU_WORKLOAD_NAME'] = 'a-workload'
    environ['JUJU_PEBBLE_CHECK_NAME'] = 'chk1'
    context = JujuContext.from_environ(environ)
    assert context.workload_name == 'a-workload'
    assert context.pebble_check_name == 'chk1'


@pytest.mark.parametrize('event', ['some-stor-storage-attached', 'some-stor-storage-detaching'])
def test_from_environ_storage(event: str):
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = event
    environ['JUJU_DISPATCH_PATH'] = f'hooks/{event}'
    environ['JUJU_STORAGE_ID'] = 'some-stor/2'
    context = JujuContext.from_environ(environ)
    assert context.storage_name == 'some-stor'
    assert context.storage_index == 2


@pytest.mark.parametrize(
    'event,additional_env',
    [
        ('one-rel-relation-created', {}),
        ('one-rel-relation-joined', {'JUJU_REMOTE_UNIT': 'remoteunit'}),
        ('one-rel-relation-changed', {'JUJU_REMOTE_UNIT': 'remoteunit'}),
        (
            'one-rel-relation-departed',
            {'JUJU_REMOTE_UNIT': 'remoteunit', 'JUJU_DEPARTING_UNIT': 'd-unit'},
        ),
        ('one-rel-relation-broken', {}),
    ],
)
def test_from_environ_relation(event: str, additional_env: dict[str, str]):
    environ = _valid_minimal.copy()
    environ['JUJU_HOOK_NAME'] = event
    environ['JUJU_DISPATCH_PATH'] = f'hooks/{event}'
    environ['JUJU_RELATION'] = 'one-rel'
    environ['JUJU_RELATION_ID'] = 'one-rel:1'
    environ['JUJU_REMOTE_APP'] = 'remoteapp'
    environ.update(additional_env)
    context = JujuContext.from_environ(environ)
    assert context.relation_id == 1
    assert context.relation_name == 'one-rel'
    assert context.remote_app_name == 'remoteapp'
    if 'JUJU_REMOTE_UNIT' in environ:
        assert context.remote_unit_name == 'remoteunit'
    if 'JUJU_DEPARTING_UNIT' in environ:
        assert context.relation_departing_unit_name == 'd-unit'
