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

from pathlib import Path

from ops.jujucontext import _JujuContext
from ops.jujuversion import JujuVersion


class TestJujuContext:
    def test_both_str_and_int_fields_default_to_none(self):
        juju_context = _JujuContext.from_dict({'JUJU_VERSION': '0.0.0'})
        assert juju_context.action_name is None
        assert juju_context.relation_id is None

    def test_parsing_int_fields(self):
        juju_context = _JujuContext.from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_RELATION_ID': 'x:42',
        })
        assert juju_context.relation_id == 42

    def test_parsing_secret_revision_as_int(self):
        juju_context = _JujuContext.from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_SECRET_REVISION': '42',
        })
        assert juju_context.secret_revision == 42

    def test_parsing_juju_debug_as_bool(self):
        juju_context = _JujuContext.from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_DEBUG': 'true',
        })
        assert juju_context.debug is True

    def test_parsing_juju_debug_at_as_set(self):
        juju_context = _JujuContext.from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_DEBUG_AT': 'all,hook',
        })
        assert juju_context.debug_at == set(('all', 'hook'))

    def test_parsing_juju_charm_dir(self):
        juju_context = _JujuContext.from_dict({
            'JUJU_VERSION': '0.0.0',
            'JUJU_CHARM_DIR': '/dir',
        })
        assert juju_context.charm_dir == Path('/dir')

    def test_parsing_juju_charm_dir_not_set(self):
        juju_context = _JujuContext.from_dict({'JUJU_VERSION': '0.0.0'})
        assert juju_context.charm_dir == Path(f'{__file__}/../../..').resolve()

    def test_parsing_juju_version(self):
        juju_context = _JujuContext.from_dict({'JUJU_VERSION': '3.4.0'})
        assert juju_context.version == JujuVersion('3.4.0')

    def test_parsing_storage_id_to_name(self):
        juju_context = _JujuContext.from_dict({
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

        juju_context = _JujuContext.from_dict(env)

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
