# Copyright 2020 Canonical Ltd.
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


def builder(framework, meta, charm_cls):
    class TestClass(charm_cls):
        pass


class TestingModelBuilder:
    """This class represents a way to build up the model that will drive a test suite.

    The model that is created is from the viewpoint of the charm that you are testing.
    """

    def __init__(self, unit_name):
        self.unit_name = unit_name
        self._backend = TestingModelBackend(unit_name)
        self._relation_id_counter = 0

    def get_backend(self):
        return self._backend

    def _next_relation_id(self):
        rel_id = self._relation_id_counter
        self._relation_id_counter += 1

    def add_relation(self, relation_name, remote_app, remote_app_data={}):
        rel_id = self._next_relation_id()
        self._backend._relation_ids_map.setdefault(relation_name, []).append(rel_id)
        self._backend._relation_names[rel_id] = relation_name
        self._backend._relation_list_map[rel_id] = []
        self._backend._relation_data[rel_id] = {
            remote_app: remote_app_data,
            self._backend.unit_name: {},
            self._backend.app_name: {},
        }

    def add_relation_unit(self, relation_id, remote_unit, remote_unit_data={}):
        self._backend._relation_list_map[relation_id].append(remote_unit)
        self._backend._relation_data[relation_id][remote_unit] = remote_unit_data

    def add_relation_and_unit(self, relation_name, remote_unit, initial_unit_data={}, initial_app_data={}, remote_app_data={}, remote_unit_data={}):
        """Create a relation visible to your charm.

        It will be populated with the initial app and unit data that you have supplied.
        """
        remote_app_name = remote_unit.split('/')[0]
        rel_id = self._next_relation_id()
        self._backend._relation_ids_map.setdefault(relation_name, []).append(rel_id)
        self._backend._relation_names[rel_id] = relation_name
        self._backend._relation_list_map[rel_id] = [remote_unit]
        self._backend._relation_data[rel_id] = {
            remote_unit: remote_unit_data,
            remote_app_name: remote_app_data,
            self._backend.unit_name: initial_unit_data,
            self._backend.app_name: initial_app_data,
        }
        return rel_id

    def update_relation_data(self, relation_id, name, **kwargs):
        """Update the relation data for a given unit or application in a given relation.

        :param relation_id: The integer relation_id representing this relation.
        :param name: The unit or application name that is being updated.
          This can be the local or remote application.
        :param kwargs: Each key/value will be updated in the relation data.
        :return: None
        """
        existing = self._backend._relation_data[relation_id][name].copy()
        for k, v in kwargs:
            if v == '':
                existing.pop(k, None)
            else:
                existing[k] = v


class TestingModelBackend:
    """This conforms to the interface for ModelBackend but provides canned data.

    Use the TestingModelBuilder to populate the model.
    """

    def __init__(self, unit_name):
        self.unit_name = unit_name
        self.app_name = self.unit_name.split('/')[0]

        self._is_leader = None
        self._relation_ids_map = {}  # relation name to [relation_ids,...]
        self._relation_names = {}  # reverse map from relation_id to relation_name
        self._relation_list_map = {}  # relation_id: [unit_name,...]
        self._relation_data = {}  # {relation_id: {name: data}}
        self._config = {}
        self._is_leader = False
        self._resources_map = {}
        self._pod_spec = None
        self._app_status = None
        self._unit_status = None

    def relation_ids(self, relation_name):
        return self._relation_ids_map[relation_name]

    def relation_list(self, relation_id):
        return self._relation_list_map[relation_id]

    def relation_get(self, relation_id, member_name, is_app):
        if is_app and '/' in member_name:
            member_name = member_name.split('/')[0]
        return self._relation_data[relation_id][member_name].copy()

    def relation_set(self, relation_id, key, value, is_app):
        relation = self._relation_data[relation_id]
        if is_app:
            bucket_key = self.app_name
        else:
            bucket_key = self.unit_name
        if bucket_key not in relation:
            relation[bucket_key] = {}
        bucket = relation[bucket_key]
        bucket[key] = value

    def config_get(self):
        return self._config

    def is_leader(self):
        return self._is_leader

    def resource_get(self, resource_name):
        return self._resources_map[resource_name]

    def pod_spec_set(self, spec, k8s_resources):
        self._pod_spec = (spec, k8s_resources)

    def status_get(self, *, is_app=False):
        raise NotImplementedError(self.status_get)
        if is_app:
            return self._app_status
        else:
            return self._unit_status

    def status_set(self, status, message='', *, is_app=False):
        if is_app:
            self._app_status = (status, message)
        else:
            self._unit_status = (status, message)

    def storage_list(self, name):
        raise NotImplementedError(self.storage_list)

    def storage_get(self, storage_name_id, attribute):
        raise NotImplementedError(self.storage_get)

    def storage_add(self, name, count=1):
        raise NotImplementedError(self.storage_add)

    def action_get(self):
        raise NotImplementedError(self.action_get)

    def action_set(self, results):
        raise NotImplementedError(self.action_set)

    def action_log(self, message):
        raise NotImplementedError(self.action_log)

    def action_fail(self, message=''):
        raise NotImplementedError(self.action_fail)

    def network_get(self, endpoint_name, relation_id=None):
        raise NotImplementedError(self.network_get)
