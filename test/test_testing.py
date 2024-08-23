# Copyright 2019 Canonical Ltd.
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

import collections
import datetime
import grp
import importlib
import inspect
import io
import ipaddress
import os
import pathlib
import platform
import pwd
import shutil
import sys
import tempfile
import textwrap
import time
import typing
import unittest
import uuid
from unittest.mock import MagicMock, patch

import pytest
import yaml

import ops
import ops.testing
from ops import pebble
from ops.jujuversion import JujuVersion
from ops.model import _ModelBackend
from ops.pebble import FileType
from ops.testing import ExecResult, _TestingPebbleClient

is_linux = platform.system() == 'Linux'


class StorageTester(ops.CharmBase):
    """Record the relation-changed events."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.observed_events: typing.List[ops.EventBase] = []
        self.framework.observe(self.on.test_storage_attached, self._on_test_storage_attached)
        self.framework.observe(self.on.test_storage_detaching, self._on_test_storage_detaching)

    def _on_test_storage_attached(self, event: ops.EventBase):
        self.observed_events.append(event)

    def _on_test_storage_detaching(self, event: ops.EventBase):
        self.observed_events.append(event)


class StorageWithHyphensHelper(ops.Object):
    def __init__(self, parent: ops.Object, key: str):
        super().__init__(parent, key)
        self.changes: typing.List[ops.EventBase] = []
        parent.framework.observe(
            parent.on.test_with_hyphens_storage_attached, self.on_storage_changed
        )
        parent.framework.observe(
            parent.on.test_with_hyphens_storage_detaching, self.on_storage_changed
        )

    def on_storage_changed(self, event: ops.EventBase):
        self.changes.append(event)


class TestHarness:
    def test_add_relation_no_meta_fails(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: mycharm')
        request.addfinalizer(harness.cleanup)
        with pytest.raises(ops.RelationNotFoundError):
            harness.add_relation('db', 'postgresql')

    def test_add_relation(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id, int)
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == []
        # Make sure the initial data bags for our app and unit are empty.
        assert backend.relation_get(rel_id, 'test-app', is_app=True) == {}
        assert backend.relation_get(rel_id, 'test-app/0', is_app=False) == {}

    def test_add_relation_with_app_data(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql', app_data={'x': '1', 'y': '2'})
        assert isinstance(rel_id, int)
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == ['postgresql/0']
        assert harness.get_relation_data(rel_id, 'postgresql') == {'x': '1', 'y': '2'}
        assert harness.get_relation_data(rel_id, 'postgresql/0') == {}

    def test_add_relation_with_unit_data(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql', unit_data={'a': '1', 'b': '2'})
        assert isinstance(rel_id, int)
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == ['postgresql/0']
        assert harness.get_relation_data(rel_id, 'postgresql') == {}
        assert harness.get_relation_data(rel_id, 'postgresql/0') == {'a': '1', 'b': '2'}

    def test_can_connect_default(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              foo:
                resource: foo-image
            """,
        )
        request.addfinalizer(harness.cleanup)

        harness.begin()
        c = harness.model.unit.get_container('foo')

        assert not c.can_connect()
        with pytest.raises(pebble.ConnectionError):
            c.get_plan()

        harness.set_can_connect('foo', True)
        assert c.can_connect()

        harness.set_can_connect('foo', False)
        assert not c.can_connect()

        harness.container_pebble_ready('foo')
        assert c.can_connect()
        c.get_plan()  # shouldn't raise ConnectionError

    def test_can_connect_begin_with_initial_hooks(self, request: pytest.FixtureRequest):
        pebble_ready_calls: collections.defaultdict[str, int] = collections.defaultdict(int)

        class MyCharm(ops.CharmBase):
            def __init__(self, *args: typing.Any):
                super().__init__(*args)
                self.framework.observe(self.on.foo_pebble_ready, self._on_pebble_ready)
                self.framework.observe(self.on.bar_pebble_ready, self._on_pebble_ready)

            def _on_pebble_ready(self, event: ops.PebbleReadyEvent):
                assert event.workload.can_connect()
                pebble_ready_calls[event.workload.name] += 1

        harness = ops.testing.Harness(
            MyCharm,
            meta="""
            name: test-app
            containers:
              foo:
                resource: foo-image
              bar:
                resource: bar-image
            """,
        )
        request.addfinalizer(harness.cleanup)

        harness.begin_with_initial_hooks()
        assert dict(pebble_ready_calls) == {'foo': 1, 'bar': 1}
        assert harness.model.unit.containers['foo'].can_connect()
        assert harness.model.unit.containers['bar'].can_connect()

        harness.set_can_connect('foo', False)
        assert not harness.model.unit.containers['foo'].can_connect()

        harness.set_can_connect('foo', True)
        container = harness.model.unit.containers['foo']
        assert container.can_connect()
        container.get_plan()  # shouldn't raise ConnectionError

    def test_add_relation_and_unit(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo': 'bar'})
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == ['postgresql/0']
        assert backend.relation_get(rel_id, 'postgresql/0', is_app=False) == {'foo': 'bar'}

    def test_add_relation_with_remote_app_data(self, request: pytest.FixtureRequest):
        # language=YAML
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        remote_app = 'postgresql'
        rel_id = harness.add_relation('db', remote_app)
        harness.update_relation_data(rel_id, 'postgresql', {'app': 'data'})
        assert isinstance(rel_id, int)
        backend = harness._backend
        assert [rel_id] == backend.relation_ids('db')
        assert backend.relation_get(rel_id, remote_app, is_app=True) == {'app': 'data'}

    def test_add_relation_with_our_initial_data(self, request: pytest.FixtureRequest):
        class InitialDataTester(ops.CharmBase):
            """Record the relation-changed events."""

            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observed_events: typing.List[ops.EventBase] = []
                self.framework.observe(self.on.db_relation_changed, self._on_db_relation_changed)

            def _on_db_relation_changed(self, event: ops.EventBase):
                self.observed_events.append(event)

        # language=YAML
        harness = ops.testing.Harness(
            InitialDataTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v1'})
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.1'})
        backend = harness._backend
        assert backend.relation_get(rel_id, 'test-app', is_app=True) == {'k': 'v1'}
        assert backend.relation_get(rel_id, 'test-app/0', is_app=False) == {
            'ingress-address': '192.0.2.1'
        }

        harness.begin()
        assert backend.relation_get(rel_id, 'test-app', is_app=True) == {'k': 'v1'}
        assert backend.relation_get(rel_id, 'test-app/0', is_app=False) == {
            'ingress-address': '192.0.2.1'
        }
        # Make sure no relation-changed events are emitted for our own data bags.
        assert harness.charm.observed_events == []

        # A remote unit can still update our app relation data bag since our unit is not a leader.
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v2'})
        # And we get an event
        assert harness.charm.observed_events == []
        # We can also update our own relation data, even if it is a bit 'cheaty'
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.2'})
        # But no event happens

        # Updating our data app relation data bag and our unit data bag does not generate events.
        harness.set_leader(True)
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v3'})
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.2'})
        assert harness.charm.observed_events == []

    def test_add_peer_relation_with_initial_data_leader(self, request: pytest.FixtureRequest):
        class InitialDataTester(ops.CharmBase):
            """Record the relation-changed events."""

            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observed_events: typing.List[ops.EventBase] = []
                self.framework.observe(
                    self.on.cluster_relation_changed, self._on_cluster_relation_changed
                )

            def _on_cluster_relation_changed(self, event: ops.EventBase):
                self.observed_events.append(event)

        # language=YAML
        harness = ops.testing.Harness(
            InitialDataTester,
            meta="""
            name: test-app
            peers:
                cluster:
                    interface: cluster
            """,
        )
        request.addfinalizer(harness.cleanup)
        # TODO: dmitriis 2020-04-07 test a minion unit and initial peer relation app data
        # events when the harness begins to emit events for initial data.
        harness.set_leader(is_leader=True)
        rel_id = harness.add_relation('cluster', 'test-app')
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v'})
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.1'})
        backend = harness._backend
        assert backend.relation_get(rel_id, 'test-app', is_app=True) == {'k': 'v'}
        assert backend.relation_get(rel_id, 'test-app/0', is_app=False) == {
            'ingress-address': '192.0.2.1'
        }

        harness.begin()
        assert backend.relation_get(rel_id, 'test-app', is_app=True) == {'k': 'v'}
        assert backend.relation_get(rel_id, 'test-app/0', is_app=False) == {
            'ingress-address': '192.0.2.1'
        }
        # Make sure no relation-changed events are emitted for our own data bags.
        assert harness.charm.observed_events == []

        # Updating our app relation data bag and our unit data bag does not trigger events
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v2'})
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.2'})
        assert harness.charm.observed_events == []

        # If our unit becomes a minion, updating app relation data indirectly becomes possible
        # and our charm gets notifications.
        harness.set_leader(False)
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v3'})
        assert backend.relation_get(rel_id, 'test-app', is_app=True) == {'k': 'v3'}
        assert len(harness.charm.observed_events), 1
        assert isinstance(harness.charm.observed_events[0], ops.RelationEvent)

    def test_remove_relation(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # First create a relation
        rel_id = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        backend = harness._backend
        # Check relation was created
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == ['postgresql/0']
        harness.charm.get_changes(reset=True)  # created event ignored
        # Now remove relation
        harness.remove_relation(rel_id)
        # Check relation no longer exists
        assert backend.relation_ids('db') == []
        pytest.raises(ops.RelationNotFoundError, backend.relation_list, rel_id)
        # Check relation broken event is raised with correct data
        changes = harness.charm.get_changes()
        assert changes[0] == {
            'name': 'relation-departed',
            'relation': 'db',
            'data': {
                'app': 'postgresql',
                'unit': 'postgresql/0',
                'departing_unit': 'postgresql/0',
                'relation_id': 0,
            },
        }
        assert changes[1] == {
            'name': 'relation-broken',
            'relation': 'db',
            'data': {'app': 'postgresql', 'unit': None, 'relation_id': rel_id},
        }

    def test_remove_specific_relation_id(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')

        # Create the first relation
        rel_id_1 = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id_1, int)
        harness.add_relation_unit(rel_id_1, 'postgresql/0')
        backend = harness._backend
        # Check relation was created
        assert rel_id_1 in backend.relation_ids('db')
        assert backend.relation_list(rel_id_1) == ['postgresql/0']
        harness.charm.get_changes(reset=True)  # created event ignored

        # Create the second relation
        rel_id_2 = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id_2, int)
        harness.add_relation_unit(rel_id_2, 'postgresql/1')
        backend = harness._backend
        # Check relation was created and both relations exist
        assert rel_id_1 in backend.relation_ids('db')
        assert rel_id_2 in backend.relation_ids('db')
        assert backend.relation_list(rel_id_2) == ['postgresql/1']
        harness.charm.get_changes(reset=True)  # created event ignored

        # Now remove second relation
        harness.remove_relation(rel_id_2)
        # Check second relation no longer exists but first does
        assert backend.relation_ids('db') == [rel_id_1]
        pytest.raises(ops.RelationNotFoundError, backend.relation_list, rel_id_2)

        # Check relation broken event is raised with correct data
        changes = harness.charm.get_changes()
        assert changes[0] == {
            'name': 'relation-departed',
            'relation': 'db',
            'data': {
                'app': 'postgresql',
                'unit': 'postgresql/1',
                'departing_unit': 'postgresql/1',
                'relation_id': rel_id_2,
            },
        }
        assert changes[1] == {
            'name': 'relation-broken',
            'relation': 'db',
            'data': {'app': 'postgresql', 'unit': None, 'relation_id': rel_id_2},
        }

    def test_removing_invalid_relation_id_raises_exception(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # First create a relation
        rel_id = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        backend = harness._backend
        # Check relation was created
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == ['postgresql/0']
        harness.charm.get_changes(reset=True)  # created event ignored
        # Check exception is raised if relation id is invalid
        with pytest.raises(ops.RelationNotFoundError):
            harness.remove_relation(rel_id + 1)

    def test_remove_relation_unit(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # First add a relation and unit
        rel_id = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo': 'bar'})
        # Check relation and unit were created
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == ['postgresql/0']
        harness.charm.get_changes(reset=True)  # ignore relation created events
        relation = harness.charm.model.get_relation('db')
        assert relation is not None
        assert len(relation.units) == 1
        # Check relation data is correct
        rel_unit = harness.charm.model.get_unit('postgresql/0')
        assert relation.data[rel_unit]['foo'] == 'bar'
        # Instruct the charm to record the relation data it sees in the list of changes
        harness.charm.record_relation_data_on_events = True
        # Now remove unit
        harness.remove_relation_unit(rel_id, 'postgresql/0')
        # Check relation still exists
        assert backend.relation_ids('db') == [rel_id]
        # Check removed unit does not exist
        assert backend.relation_list(rel_id) == []
        # Check the unit is actually removed from the relations the model knows about
        rel = harness.charm.model.get_relation('db')
        assert rel is not None
        assert len(rel.units) == 0
        assert rel_unit not in rel.data
        # Check relation departed was raised with correct data
        assert harness.charm.get_changes()[0] == {
            'name': 'relation-departed',
            'relation': 'db',
            'data': {
                'app': 'postgresql',
                'unit': 'postgresql/0',
                'departing_unit': 'postgresql/0',
                'relation_id': 0,
                'relation_data': {
                    'test-app/0': {},
                    'test-app': {},
                    'postgresql/0': {'foo': 'bar'},
                    'postgresql': {},
                },
            },
        }

    def test_removing_relation_removes_remote_app_data(self, request: pytest.FixtureRequest):
        # language=YAML
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # Add a relation and update app data
        remote_app = 'postgresql'
        rel_id = harness.add_relation('db', remote_app)
        harness.update_relation_data(rel_id, 'postgresql', {'app': 'data'})
        assert isinstance(rel_id, int)
        # Check relation app data exists
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_get(rel_id, remote_app, is_app=True) == {'app': 'data'}
        harness.remove_relation(rel_id)
        # Check relation and app data are removed
        assert backend.relation_ids('db') == []
        with harness._event_context('foo'):
            pytest.raises(
                ops.RelationNotFoundError, backend.relation_get, rel_id, remote_app, is_app=True
            )

    def test_removing_relation_refreshes_charm_model(self, request: pytest.FixtureRequest):
        # language=YAML
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # Add a relation and update app data
        remote_app = 'postgresql'
        rel_id = harness.add_relation('db', remote_app)
        harness.update_relation_data(rel_id, 'postgresql', {'app': 'data'})
        assert isinstance(rel_id, int)
        assert self._find_relation_in_model_by_id(harness, rel_id) is not None

        # Check relation app data exists
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_get(rel_id, remote_app, is_app=True) == {'app': 'data'}
        harness.remove_relation(rel_id)
        assert self._find_relation_in_model_by_id(harness, rel_id) is None

    def test_remove_relation_marks_relation_as_inactive(self, request: pytest.FixtureRequest):
        relations: typing.List[str] = []
        is_broken = False

        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                framework.observe(self.on.db_relation_broken, self._db_relation_broken)

            def _db_relation_broken(self, event: ops.RelationBrokenEvent):
                nonlocal is_broken, relations
                is_broken = not event.relation.active
                relations = [rel.name for rel in self.model.relations['db']]

        harness = ops.testing.Harness(
            MyCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        rel_id = harness.add_relation('db', 'postgresql')
        harness.remove_relation(rel_id)
        assert is_broken, 'event.relation.active not False in relation-broken event'
        assert not relations, 'Model.relations contained broken relation'

    def _find_relation_in_model_by_id(
        self, harness: ops.testing.Harness['RelationEventCharm'], rel_id: int
    ):
        for relations in harness.charm.model.relations.values():
            for relation in relations:
                if rel_id == relation.id:
                    return relation
        return None

    def test_removing_relation_unit_removes_data_also(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # Add a relation and unit with data
        rel_id = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo': 'bar'})
        # Check relation, unit and data exist
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == ['postgresql/0']
        assert backend.relation_get(rel_id, 'postgresql/0', is_app=False) == {'foo': 'bar'}
        harness.charm.get_changes(reset=True)  # ignore relation created events
        # Remove unit but not relation
        harness.remove_relation_unit(rel_id, 'postgresql/0')
        # Check relation exists but unit and data are removed
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == []
        pytest.raises(KeyError, backend.relation_get, rel_id, 'postgresql/0', is_app=False)
        # Check relation departed was raised with correct data
        assert harness.charm.get_changes()[0] == {
            'name': 'relation-departed',
            'relation': 'db',
            'data': {
                'app': 'postgresql',
                'unit': 'postgresql/0',
                'departing_unit': 'postgresql/0',
                'relation_id': rel_id,
            },
        }

    def test_removing_relation_unit_does_not_remove_other_unit_and_data(
        self,
        request: pytest.FixtureRequest,
    ):
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # Add a relation with two units with data
        rel_id = harness.add_relation('db', 'postgresql')
        assert isinstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.add_relation_unit(rel_id, 'postgresql/1')
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo0': 'bar0'})
        harness.update_relation_data(rel_id, 'postgresql/1', {'foo1': 'bar1'})
        # Check both unit and data are present
        backend = harness._backend
        assert backend.relation_ids('db') == [rel_id]
        assert backend.relation_list(rel_id) == ['postgresql/0', 'postgresql/1']
        assert backend.relation_get(rel_id, 'postgresql/0', is_app=False) == {'foo0': 'bar0'}
        assert backend.relation_get(rel_id, 'postgresql/1', is_app=False) == {'foo1': 'bar1'}
        harness.charm.get_changes(reset=True)  # ignore relation created events
        # Remove only one unit
        harness.remove_relation_unit(rel_id, 'postgresql/1')
        # Check other unit and data still exists
        assert backend.relation_list(rel_id) == ['postgresql/0']
        assert backend.relation_get(rel_id, 'postgresql/0', is_app=False) == {'foo0': 'bar0'}
        # Check relation departed was raised with correct data
        assert harness.charm.get_changes()[0] == {
            'name': 'relation-departed',
            'relation': 'db',
            'data': {
                'app': 'postgresql',
                'unit': 'postgresql/1',
                'departing_unit': 'postgresql/1',
                'relation_id': rel_id,
            },
        }

    def test_relation_events(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RelationEventCharm,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
        """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        assert harness.charm.get_changes() == []
        rel_id = harness.add_relation('db', 'postgresql')
        assert harness.charm.get_changes() == [
            {
                'name': 'relation-created',
                'relation': 'db',
                'data': {
                    'app': 'postgresql',
                    'unit': None,
                    'relation_id': rel_id,
                },
            }
        ]
        harness.add_relation_unit(rel_id, 'postgresql/0')
        assert harness.charm.get_changes() == [
            {
                'name': 'relation-joined',
                'relation': 'db',
                'data': {
                    'app': 'postgresql',
                    'unit': 'postgresql/0',
                    'relation_id': rel_id,
                },
            }
        ]
        harness.update_relation_data(rel_id, 'postgresql', {'foo': 'bar'})
        assert harness.charm.get_changes() == [
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'app': 'postgresql',
                    'unit': None,
                    'relation_id': rel_id,
                },
            }
        ]
        harness.update_relation_data(rel_id, 'postgresql/0', {'baz': 'bing'})
        assert harness.charm.get_changes() == [
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'app': 'postgresql',
                    'unit': 'postgresql/0',
                    'relation_id': rel_id,
                },
            }
        ]

    def test_get_relation_data(self, request: pytest.FixtureRequest):
        charm_meta = """
            name: test-app
            requires:
                db:
                    interface: pgsql
        """
        harness = ops.testing.Harness(ops.CharmBase, meta=charm_meta)
        request.addfinalizer(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.update_relation_data(rel_id, 'postgresql', {'remote': 'data'})
        assert harness.get_relation_data(rel_id, 'test-app') == {}
        assert harness.get_relation_data(rel_id, 'test-app/0') == {}
        assert harness.get_relation_data(rel_id, 'test-app/1') is None
        assert harness.get_relation_data(rel_id, 'postgresql') == {'remote': 'data'}
        with pytest.raises(KeyError):
            # unknown relation id
            harness.get_relation_data(99, 'postgresql')

        meta = yaml.safe_load(charm_meta)
        t_cache = ops.model._ModelCache(meta, harness._backend)
        t_app = ops.Application('test-app', meta, harness._backend, t_cache)
        t_unit0 = ops.Unit('test-app/0', meta, harness._backend, t_cache)
        t_unit1 = ops.Unit('test-app/1', meta, harness._backend, t_cache)
        assert harness.get_relation_data(rel_id, t_app) == {}
        assert harness.get_relation_data(rel_id, t_unit0) == {}
        assert harness.get_relation_data(rel_id, t_unit1) is None
        pg_app = ops.Application('postgresql', meta, harness._backend, t_cache)
        assert harness.get_relation_data(rel_id, pg_app) == {'remote': 'data'}

    def test_create_harness_twice(self, request: pytest.FixtureRequest):
        metadata = """
            name: my-charm
            requires:
              db:
                interface: pgsql
            """
        harness1 = ops.testing.Harness(ops.CharmBase, meta=metadata)
        request.addfinalizer(harness1.cleanup)
        harness2 = ops.testing.Harness(ops.CharmBase, meta=metadata)
        request.addfinalizer(harness2.cleanup)
        harness1.begin()
        harness2.begin()
        helper1 = DBRelationChangedHelper(harness1.charm, 'helper1')
        helper2 = DBRelationChangedHelper(harness2.charm, 'helper2')
        rel_id = harness2.add_relation('db', 'postgresql')
        harness2.update_relation_data(rel_id, 'postgresql', {'key': 'value'})
        # Helper2 should see the event triggered by harness2, but helper1 should see no events.
        assert helper1.changes == []
        assert helper2.changes == [(rel_id, 'postgresql')]

    def test_begin_twice(self, request: pytest.FixtureRequest):
        # language=YAML
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        with pytest.raises(RuntimeError):
            harness.begin()

    def test_update_relation_exposes_new_data(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: my-charm
            requires:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': 'data'})
        assert viewer.changes == [{'initial': 'data'}]
        harness.update_relation_data(rel_id, 'postgresql/0', {'new': 'value'})
        assert viewer.changes == [{'initial': 'data'}, {'initial': 'data', 'new': 'value'}]

    def test_update_relation_no_local_unit_change_event(self, request: pytest.FixtureRequest):
        # language=YAML
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: my-charm
            requires:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        helper = DBRelationChangedHelper(harness.charm, 'helper')
        rel_id = harness.add_relation('db', 'postgresql')
        rel = harness.charm.model.get_relation('db')
        assert rel is not None
        rel.data[harness.charm.model.unit]['key'] = 'value'
        # there should be no event for updating our own data
        harness.update_relation_data(rel_id, 'my-charm/0', {'new': 'other'})
        # but the data will be updated.
        assert rel.data[harness.charm.model.unit] == {'key': 'value', 'new': 'other'}

        rel.data[harness.charm.model.unit]['new'] = 'value'
        # Our unit data bag got updated.
        assert rel.data[harness.charm.model.unit]['new'] == 'value'
        # But there were no changed events registered by our unit.
        assert helper.changes == []

    def test_update_peer_relation_no_local_unit_change_event(self, request: pytest.FixtureRequest):
        # language=YAML
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: postgresql
            peers:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        helper = DBRelationChangedHelper(harness.charm, 'helper')
        rel_id = harness.add_relation('db', 'postgresql')

        rel = harness.charm.model.get_relation('db')
        assert rel is not None
        rel.data[harness.charm.model.unit]['key'] = 'value'
        rel = harness.charm.model.get_relation('db')
        assert rel is not None
        harness.update_relation_data(rel_id, 'postgresql/0', {'key': 'v1'})
        assert rel.data[harness.charm.model.unit] == {'key': 'v1'}
        # Make sure there was no event
        assert helper.changes == []

        rel.data[harness.charm.model.unit]['key'] = 'v2'
        # Our unit data bag got updated.
        assert dict(rel.data[harness.charm.model.unit]) == {'key': 'v2'}
        # But there were no changed events registered by our unit.
        assert helper.changes == []

        # Same for when our unit is a leader.
        harness.set_leader(is_leader=True)
        harness.update_relation_data(rel_id, 'postgresql/0', {'key': 'v3'})
        assert dict(rel.data[harness.charm.model.unit]) == {'key': 'v3'}
        assert helper.changes == []

        rel.data[harness.charm.model.unit]['key'] = 'v4'
        assert rel.data[harness.charm.model.unit]['key'] == 'v4'
        assert helper.changes == []

    def test_update_peer_relation_app_data(self, request: pytest.FixtureRequest):
        # language=YAML
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: postgresql
            peers:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_leader(is_leader=True)
        helper = DBRelationChangedHelper(harness.charm, 'helper')
        rel_id = harness.add_relation('db', 'postgresql')
        rel = harness.charm.model.get_relation('db')
        assert rel is not None
        rel.data[harness.charm.app]['key'] = 'value'
        harness.update_relation_data(rel_id, 'postgresql', {'key': 'v1'})
        assert rel.data[harness.charm.app] == {'key': 'v1'}
        assert helper.changes == []

        rel.data[harness.charm.app]['key'] = 'v2'
        # Our unit data bag got updated.
        assert rel.data[harness.charm.model.app]['key'] == 'v2'
        # But there were no changed events registered by our unit.
        assert helper.changes == []

        # If our unit is not a leader unit we get an update about peer app relation data changes.
        harness.set_leader(is_leader=False)
        harness.update_relation_data(rel_id, 'postgresql', {'k2': 'v2'})
        assert rel.data[harness.charm.model.app]['k2'] == 'v2'
        assert helper.changes == [(0, 'postgresql')]

    def test_update_relation_no_local_app_change_event(self, request: pytest.FixtureRequest):
        # language=YAML
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: my-charm
            requires:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_leader(False)
        helper = DBRelationChangedHelper(harness.charm, 'helper')
        rel_id = harness.add_relation('db', 'postgresql')
        # TODO: remove this as soon as https://github.com/canonical/operator/issues/175 is fixed.
        harness.add_relation_unit(rel_id, 'postgresql/0')
        assert helper.changes == []

        harness.update_relation_data(rel_id, 'my-charm', {'new': 'value'})
        rel = harness.charm.model.get_relation('db')
        assert rel is not None
        assert rel.data[harness.charm.app]['new'] == 'value'

        # Our app data bag got updated.
        assert rel.data[harness.charm.model.app]['new'] == 'value'
        # But there were no changed events registered by our unit.
        assert helper.changes == []

    def test_update_relation_remove_data(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: my-charm
            requires:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': 'data'})
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': ''})
        assert viewer.changes == [{'initial': 'data'}, {}]

    def test_no_event_on_empty_update_relation_unit_app(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: my-charm
            requires:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql', {'initial': 'data'})
        harness.update_relation_data(rel_id, 'postgresql', {})
        assert viewer.changes == [{'initial': 'data'}]

    def test_no_event_on_no_diff_update_relation_unit_app(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: my-charm
            requires:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql', {'initial': 'data'})
        harness.update_relation_data(rel_id, 'postgresql', {'initial': 'data'})
        assert viewer.changes == [{'initial': 'data'}]

    def test_no_event_on_empty_update_relation_unit_bag(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: my-charm
            requires:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': 'data'})
        harness.update_relation_data(rel_id, 'postgresql/0', {})
        assert viewer.changes == [{'initial': 'data'}]

    def test_no_event_on_no_diff_update_relation_unit_bag(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: my-charm
            requires:
              db:
                interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': 'data'})
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': 'data'})
        assert viewer.changes == [{'initial': 'data'}]

    def test_empty_config_raises(self):
        with pytest.raises(TypeError):
            ops.testing.Harness(RecordingCharm, config='')

    def test_update_config(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            config="""
            options:
                a:
                    description: a config option
                    type: string
                b:
                    description: another config option
                    type: int
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.update_config(key_values={'a': 'foo', 'b': 2})
        assert harness.charm.changes == [{'name': 'config-changed', 'data': {'a': 'foo', 'b': 2}}]
        harness.update_config(key_values={'b': 3})
        assert harness.charm.changes == [
            {'name': 'config-changed', 'data': {'a': 'foo', 'b': 2}},
            {'name': 'config-changed', 'data': {'a': 'foo', 'b': 3}},
        ]
        # you can set config values to the empty string, you can use unset to actually remove items
        harness.update_config(key_values={'a': ''}, unset=set('b'))
        assert harness.charm.changes == [
            {'name': 'config-changed', 'data': {'a': 'foo', 'b': 2}},
            {'name': 'config-changed', 'data': {'a': 'foo', 'b': 3}},
            {'name': 'config-changed', 'data': {'a': ''}},
        ]

    def test_update_config_undefined_option(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(RecordingCharm)
        request.addfinalizer(harness.cleanup)
        harness.begin()
        with pytest.raises(ValueError):
            harness.update_config(key_values={'nonexistent': 'foo'})

    def test_update_config_bad_type(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            config="""
            options:
                a:
                    description: a config option
                    type: boolean
                    default: false
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        with pytest.raises(RuntimeError):
            # cannot cast to bool
            harness.update_config(key_values={'a': 'foo'})

        with pytest.raises(RuntimeError):
            # cannot cast to float
            harness.update_config(key_values={'a': 42.42})

        with pytest.raises(RuntimeError):
            # cannot cast to int
            harness.update_config(key_values={'a': 42})

        # can cast to bool!
        harness.update_config(key_values={'a': False})

    def test_bad_config_option_type(self):
        with pytest.raises(RuntimeError):
            ops.testing.Harness(
                RecordingCharm,
                config="""
                options:
                    a:
                        description: a config option
                        type: gibberish
                        default: False
                """,
            )

    def test_config_secret_option(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            config="""
            options:
                a:
                    description: a config option
                    type: secret
                    default: ""
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        secret_id = harness.add_user_secret({'key': 'value'})
        harness.update_config(key_values={'a': secret_id})
        assert harness.charm.changes == [{'name': 'config-changed', 'data': {'a': secret_id}}]

    def test_no_config_option_type(self):
        with pytest.raises(RuntimeError):
            ops.testing.Harness(
                RecordingCharm,
                config="""
                options:
                    a:
                        description: a config option
                        default: False
                """,
            )

    def test_uncastable_config_option_type(self):
        with pytest.raises(RuntimeError):
            ops.testing.Harness(
                RecordingCharm,
                config="""
                options:
                    a:
                        description: a config option
                        type: boolean
                        default: peek-a-bool!
                """,
            )

    def test_update_config_unset_boolean(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            config="""
            options:
                a:
                    description: a config option
                    type: boolean
                    default: False
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        # Check the default was set correctly
        assert harness.charm.config == {'a': False}
        # Set the boolean value to True
        harness.update_config(key_values={'a': True})
        assert harness.charm.changes == [{'name': 'config-changed', 'data': {'a': True}}]
        # Unset the boolean value
        harness.update_config(unset={'a'})
        assert harness.charm.changes == [
            {'name': 'config-changed', 'data': {'a': True}},
            {'name': 'config-changed', 'data': {'a': False}},
        ]

    def test_set_leader(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(RecordingCharm)
        request.addfinalizer(harness.cleanup)
        # No event happens here
        harness.set_leader(False)
        harness.begin()
        assert not harness.charm.model.unit.is_leader()
        harness.set_leader(True)
        assert harness.charm.get_changes(reset=True) == [{'name': 'leader-elected'}]
        assert harness.charm.model.unit.is_leader()
        harness.set_leader(False)
        assert not harness.charm.model.unit.is_leader()
        # No hook event when you lose leadership.
        # TODO: verify if Juju always triggers `leader-settings-changed` if you
        #   lose leadership.
        assert harness.charm.get_changes(reset=True) == []
        harness.disable_hooks()
        harness.set_leader(True)
        # No hook event if you have disabled them
        assert harness.charm.get_changes(reset=True) == []

    def test_relation_set_app_not_leader(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
            name: test-charm
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_leader(False)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        rel = harness.charm.model.get_relation('db')
        assert rel is not None
        with harness._event_context('foo'):
            with pytest.raises(ops.ModelError):
                rel.data[harness.charm.app]['foo'] = 'bar'
        # The data has not actually been changed
        assert harness.get_relation_data(rel_id, 'test-charm') == {}
        harness.set_leader(True)
        rel.data[harness.charm.app]['foo'] = 'bar'
        assert harness.get_relation_data(rel_id, 'test-charm') == {'foo': 'bar'}

    def test_hooks_enabled_and_disabled(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
                    name: test-charm
                """,
            config="""
                    options:
                        value:
                            type: string
                        third:
                            type: string
                    """,
        )
        request.addfinalizer(harness.cleanup)
        # Before begin() there are no events.
        harness.update_config({'value': 'first'})
        # By default, after begin the charm is set up to receive events.
        harness.begin()
        harness.update_config({'value': 'second'})
        assert harness.charm.get_changes(reset=True) == [
            {'name': 'config-changed', 'data': {'value': 'second'}}
        ]
        # Once disabled, we won't see config-changed when we make an update
        harness.disable_hooks()
        harness.update_config({'third': '3'})
        assert harness.charm.get_changes(reset=True) == []
        harness.enable_hooks()
        harness.update_config({'value': 'fourth'})
        assert harness.charm.get_changes(reset=True) == [
            {'name': 'config-changed', 'data': {'value': 'fourth', 'third': '3'}}
        ]

    def test_hooks_disabled_contextmanager(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
                name: test-charm
                """,
            config="""
                options:
                    value:
                        type: string
                    third:
                        type: string
            """,
        )
        request.addfinalizer(harness.cleanup)
        # Before begin() there are no events.
        harness.update_config({'value': 'first'})
        # By default, after begin the charm is set up to receive events.
        harness.begin()
        harness.update_config({'value': 'second'})
        assert harness.charm.get_changes(reset=True) == [
            {'name': 'config-changed', 'data': {'value': 'second'}}
        ]
        # Once disabled, we won't see config-changed when we make an update
        with harness.hooks_disabled():
            harness.update_config({'third': '3'})
        assert harness.charm.get_changes(reset=True) == []
        harness.update_config({'value': 'fourth'})
        assert harness.charm.get_changes(reset=True) == [
            {'name': 'config-changed', 'data': {'value': 'fourth', 'third': '3'}}
        ]

    def test_hooks_disabled_nested_contextmanager(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
                name: test-charm
            """,
            config="""
                options:
                    fifth:
                        type: string
                    sixth:
                        type: string
                """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        # Context manager can be nested, so a test using it can invoke a helper using it.
        with harness.hooks_disabled():
            with harness.hooks_disabled():
                harness.update_config({'fifth': '5'})
            harness.update_config({'sixth': '6'})
        assert harness.charm.get_changes(reset=True) == []

    def test_hooks_disabled_noop(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
                name: test-charm
            """,
            config="""
            options:
                seventh:
                    type: string
                eighth:
                    type: string
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        # If hooks are already disabled, it is a no op, and on exit hooks remain disabled.
        harness.disable_hooks()
        with harness.hooks_disabled():
            harness.update_config({'seventh': '7'})
        harness.update_config({'eighth': '8'})
        assert harness.charm.get_changes(reset=True) == []

    def test_metadata_from_directory(self, request: pytest.FixtureRequest):
        tmp = pathlib.Path(tempfile.mkdtemp())
        request.addfinalizer(lambda: shutil.rmtree(tmp))
        metadata_filename = tmp / 'metadata.yaml'
        with metadata_filename.open('wt') as metadata:
            metadata.write(
                textwrap.dedent("""
            name: my-charm
            requires:
                db:
                    interface: pgsql
            """)
            )
        harness = self._get_dummy_charm_harness(request, tmp)
        harness.begin()
        assert list(harness.model.relations) == ['db']
        # The charm_dir also gets set
        assert harness.framework.charm_dir == tmp

    def test_metadata_from_directory_charmcraft_yaml(self, request: pytest.FixtureRequest):
        tmp = pathlib.Path(tempfile.mkdtemp())
        request.addfinalizer(lambda: shutil.rmtree(tmp))
        charmcraft_filename = tmp / 'charmcraft.yaml'
        charmcraft_filename.write_text(
            textwrap.dedent("""
            type: charm
            bases:
              - build-on:
                - name: ubuntu
                  channel: "22.04"
                run-on:
                - name: ubuntu
                  channel: "22.04"

            name: my-charm
            requires:
                db:
                    interface: pgsql
            """)
        )
        harness = self._get_dummy_charm_harness(request, tmp)
        harness.begin()
        assert list(harness.model.relations) == ['db']
        # The charm_dir also gets set
        assert harness.framework.charm_dir == tmp

    def test_config_from_directory(self, request: pytest.FixtureRequest):
        tmp = pathlib.Path(tempfile.mkdtemp())
        request.addfinalizer(lambda: shutil.rmtree(tmp))
        config_filename = tmp / 'config.yaml'
        with config_filename.open('wt') as config:
            config.write(
                textwrap.dedent("""
            options:
                opt_str:
                    type: string
                    default: "val"
                opt_str_empty:
                    type: string
                    default: ""
                opt_null:
                    type: string
                    default: null
                opt_bool:
                    type: boolean
                    default: true
                opt_int:
                    type: int
                    default: 1
                opt_float:
                    type: float
                    default: 1.0
                opt_no_default:
                    type: string
            """)
            )
        harness = self._get_dummy_charm_harness(request, tmp)
        assert harness.model.config['opt_str'] == 'val'
        assert harness.model.config['opt_str_empty'] == ''
        assert harness.model.config['opt_bool'] is True
        assert harness.model.config['opt_int'] == 1
        assert isinstance(harness.model.config['opt_int'], int)
        assert harness.model.config['opt_float'] == 1.0
        assert isinstance(harness.model.config['opt_float'], float)
        assert 'opt_null' not in harness.model.config
        assert harness._backend._config._defaults['opt_null'] is None
        assert harness._backend._config._defaults['opt_no_default'] is None

    def test_config_from_directory_charmcraft_yaml(self, request: pytest.FixtureRequest):
        tmp = pathlib.Path(tempfile.mkdtemp())
        request.addfinalizer(lambda: shutil.rmtree(tmp))
        charmcraft_filename = tmp / 'charmcraft.yaml'
        charmcraft_filename.write_text(
            textwrap.dedent("""
            type: charm
            bases:
              - build-on:
                - name: ubuntu
                  channel: "22.04"
                run-on:
                - name: ubuntu
                  channel: "22.04"

            config:
                options:
                    opt_str:
                        type: string
                        default: "val"
                    opt_int:
                        type: int
                        default: 1
            """)
        )
        harness = self._get_dummy_charm_harness(request, tmp)
        assert harness.model.config['opt_str'] == 'val'
        assert harness.model.config['opt_int'] == 1
        assert isinstance(harness.model.config['opt_int'], int)

    def test_config_in_repl(self, request: pytest.FixtureRequest):
        # In a REPL, there is no "source file", but we should still be able to
        # provide explicit metadata, and fall back to the default otherwise.
        with patch.object(inspect, 'getfile', side_effect=OSError()):
            harness = ops.testing.Harness(
                ops.CharmBase,
                meta="""
                name: repl-charm
            """,
                config="""
                options:
                    foo:
                        type: int
                        default: 42
            """,
            )
            request.addfinalizer(harness.cleanup)
            harness.begin()
            assert harness._meta.name == 'repl-charm'
            assert harness.charm.model.config['foo'] == 42

            harness = ops.testing.Harness(ops.CharmBase)
            request.addfinalizer(harness.cleanup)
            assert harness._meta.name == 'test-charm'

    def test_set_model_name(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
        """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_model_name('foo')
        assert harness.model.name == 'foo'

    def test_set_model_name_after_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
        """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_model_name('bar')
        harness.begin()
        with pytest.raises(RuntimeError):
            harness.set_model_name('foo')
        assert harness.model.name == 'bar'

    def test_set_model_uuid_after_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
        """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_model_name('bar')
        harness.set_model_uuid('96957e90-e006-11eb-ba80-0242ac130004')
        harness.begin()
        with pytest.raises(RuntimeError):
            harness.set_model_uuid('af0479ea-e006-11eb-ba80-0242ac130004')
        assert harness.model.uuid == '96957e90-e006-11eb-ba80-0242ac130004'

    def test_set_model_info_after_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
        """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_model_info('foo', '96957e90-e006-11eb-ba80-0242ac130004')
        harness.begin()
        with pytest.raises(RuntimeError):
            harness.set_model_info('bar', 'af0479ea-e006-11eb-ba80-0242ac130004')
        with pytest.raises(RuntimeError):
            harness.set_model_info('bar')
        with pytest.raises(RuntimeError):
            harness.set_model_info(uuid='af0479ea-e006-11eb-ba80-0242ac130004')
        with pytest.raises(RuntimeError):
            harness.set_model_name('bar')
        with pytest.raises(RuntimeError):
            harness.set_model_uuid('af0479ea-e006-11eb-ba80-0242ac130004')
        assert harness.model.name == 'foo'
        assert harness.model.uuid == '96957e90-e006-11eb-ba80-0242ac130004'

    def test_add_storage_before_harness_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
                    multiple:
                        range: 1-3
            """,
        )
        request.addfinalizer(harness.cleanup)

        stor_ids = harness.add_storage('test', count=3)
        for s in stor_ids:
            # before begin, adding storage does not attach it.
            assert s not in harness._backend.storage_list('test')

        with pytest.raises(ops.ModelError):
            harness._backend.storage_get('test/0', 'location')[-6:]

    def test_add_storage_then_harness_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
                    multiple:
                        range: 1-3
            """,
        )
        request.addfinalizer(harness.cleanup)

        harness.add_storage('test', count=3)

        with pytest.raises(ops.ModelError):
            harness._backend.storage_get('test/0', 'location')[-6:]

        harness.begin_with_initial_hooks()
        assert len(harness.charm.observed_events) == 3
        for i in range(3):
            assert isinstance(harness.charm.observed_events[i], ops.StorageAttachedEvent)

        want = str(pathlib.PurePath('test', '0'))
        assert want == harness._backend.storage_get('test/0', 'location')[-6:]

    def test_add_storage_not_attached_default(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
            """,
        )
        request.addfinalizer(harness.cleanup)

        harness.add_storage('test')
        harness.begin()
        assert (
            len(harness.model.storages['test']) == 0
        ), 'storage should start in detached state and be excluded from storage listing'

    def test_add_storage_without_metadata_key_fails(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)

        with pytest.raises(RuntimeError) as excinfo:
            harness.add_storage('test')
        assert (
            excinfo.value.args[0] == "the key 'test' is not specified as a storage key in metadata"
        )

    def test_add_storage_after_harness_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
                    multiple:
                        range: 1-3
            """,
        )
        request.addfinalizer(harness.cleanup)

        # Set up initial storage
        harness.add_storage('test')[0]
        harness.begin_with_initial_hooks()
        assert len(harness.charm.observed_events) == 1
        assert isinstance(harness.charm.observed_events[0], ops.StorageAttachedEvent)

        # Add additional storage
        stor_ids = harness.add_storage('test', count=3, attach=True)
        # NOTE: stor_id now reflects the 4th ID.  The 2nd and 3rd IDs are created and
        # used, but not returned by Harness.add_storage.
        # (Should we consider changing its return type?)

        added_indices = {self._extract_storage_index(stor_id) for stor_id in stor_ids}
        assert added_indices.issubset(set(harness._backend.storage_list('test')))

        for i in ['1', '2', '3']:
            storage_name = f'test/{i}'
            want = str(pathlib.PurePath('test', i))
            assert harness._backend.storage_get(storage_name, 'location').endswith(want)
        assert len(harness.charm.observed_events) == 4
        for i in range(1, 4):
            assert isinstance(harness.charm.observed_events[i], ops.StorageAttachedEvent)

    def test_detach_storage(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
            """,
        )
        request.addfinalizer(harness.cleanup)

        # Set up initial storage
        stor_id = harness.add_storage('test')[0]
        harness.begin_with_initial_hooks()
        assert len(harness.charm.observed_events) == 1
        assert isinstance(harness.charm.observed_events[0], ops.StorageAttachedEvent)

        # Detach storage
        harness.detach_storage(stor_id)
        assert len(harness.charm.observed_events) == 2
        assert isinstance(harness.charm.observed_events[1], ops.StorageDetachingEvent)

        # Verify backend functions return appropriate values.
        # Real backend would return info only for actively attached storage units.
        assert stor_id not in harness._backend.storage_list('test')
        with pytest.raises(ops.ModelError) as excinfo:
            harness._backend.storage_get('test/0', 'location')
        # Error message modeled after output of
        # "storage-get -s <invalid/inactive id> location" on real deployment
        assert (
            excinfo.value.args[0]
            == 'ERROR invalid value "test/0" for option -s: storage not found'
        )

        # Retry detach
        # Since already detached, no more hooks should fire
        harness.detach_storage(stor_id)
        assert len(harness.charm.observed_events) == 2
        assert isinstance(harness.charm.observed_events[1], ops.StorageDetachingEvent)

    def test_detach_storage_before_harness_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
            """,
        )
        request.addfinalizer(harness.cleanup)

        stor_id = harness.add_storage('test')[0]
        with pytest.raises(RuntimeError) as excinfo:
            harness.detach_storage(f'test/{stor_id}')
        assert excinfo.value.args[0] == 'cannot detach storage before Harness is initialised'

    def test_storage_with_hyphens_works(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
                test-with-hyphens:
                    type: filesystem
            """,
        )
        request.addfinalizer(harness.cleanup)

        # Set up initial storage
        harness.begin()
        helper = StorageWithHyphensHelper(harness.charm, 'helper')
        harness.add_storage('test-with-hyphens', attach=True)[0]

        assert len(helper.changes) == 1

    def test_attach_storage(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
            """,
        )
        request.addfinalizer(harness.cleanup)

        # Set up initial storage
        stor_id = harness.add_storage('test')[0]
        harness.begin_with_initial_hooks()
        assert len(harness.charm.observed_events) == 1
        assert isinstance(harness.charm.observed_events[0], ops.StorageAttachedEvent)

        # Detach storage
        harness.detach_storage(stor_id)
        assert len(harness.charm.observed_events) == 2
        assert isinstance(harness.charm.observed_events[1], ops.StorageDetachingEvent)

        # Re-attach storage
        harness.attach_storage(stor_id)
        assert len(harness.charm.observed_events) == 3
        assert isinstance(harness.charm.observed_events[2], ops.StorageAttachedEvent)

        # Verify backend functions return appropriate values.
        # Real backend would return info only for actively attached storage units.
        assert self._extract_storage_index(stor_id) in harness._backend.storage_list('test')
        want = str(pathlib.PurePath('test', '0'))
        assert want == harness._backend.storage_get('test/0', 'location')[-6:]

        # Retry attach
        # Since already detached, no more hooks should fire
        harness.attach_storage(stor_id)
        assert len(harness.charm.observed_events) == 3
        assert isinstance(harness.charm.observed_events[2], ops.StorageAttachedEvent)

    def test_attach_storage_before_harness_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
            """,
        )
        request.addfinalizer(harness.cleanup)

        # We deliberately don't guard against attaching storage before the harness begins,
        # as there are legitimate reasons to do so.
        stor_id = harness.add_storage('test')[0]
        assert stor_id

    def test_remove_storage_before_harness_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
                    multiple:
                        range: 1-3
            """,
        )
        request.addfinalizer(harness.cleanup)

        stor_ids = harness.add_storage('test', count=2)
        harness.remove_storage(stor_ids[0])
        # Note re: delta between real behavior and Harness: Juju doesn't allow removal
        # of the last attached storage unit while a workload is still running.  To more
        # easily allow testing of storage removal, I am presently ignoring this detail.
        # (Otherwise, the user would need to flag somehow that they are intentionally
        # removing the final unit as part of a shutdown procedure, else it'd block the
        # removal.  I'm not sure such behavior is productive.)

        harness.begin_with_initial_hooks()
        # Only one hook will fire; one won't since it was removed
        assert len(harness.charm.observed_events) == 1
        assert isinstance(harness.charm.observed_events[0], ops.StorageAttachedEvent)

    def test_remove_storage_without_metadata_key_fails(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)

        # Doesn't really make sense since we already can't add storage which isn't in the metadata,
        # but included for completeness.
        with pytest.raises(RuntimeError) as excinfo:
            harness.remove_storage('test/0')
        assert (
            excinfo.value.args[0] == "the key 'test' is not specified as a storage key in metadata"
        )

    def test_remove_storage_after_harness_begin(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
                    multiple:
                        range: 1-3
            """,
        )
        request.addfinalizer(harness.cleanup)

        stor_ids = harness.add_storage('test', count=2)
        harness.begin_with_initial_hooks()
        assert len(harness.charm.observed_events) == 2
        assert isinstance(harness.charm.observed_events[0], ops.StorageAttachedEvent)
        assert isinstance(harness.charm.observed_events[1], ops.StorageAttachedEvent)

        harness.remove_storage(stor_ids[1])
        assert len(harness.charm.observed_events) == 3
        assert isinstance(harness.charm.observed_events[2], ops.StorageDetachingEvent)

        attached_storage_ids = harness._backend.storage_list('test')
        assert self._extract_storage_index(stor_ids[0]) in attached_storage_ids
        assert self._extract_storage_index(stor_ids[1]) not in attached_storage_ids

    def _extract_storage_index(self, stor_id: str):
        return int(stor_id.split('/')[-1])

    def test_remove_detached_storage(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            StorageTester,
            meta="""
            name: test-app
            requires:
                db:
                    interface: pgsql
            storage:
                test:
                    type: filesystem
                    multiple:
                        range: 1-3
            """,
        )
        request.addfinalizer(harness.cleanup)

        stor_ids = harness.add_storage('test', count=2)
        harness.begin_with_initial_hooks()
        harness.detach_storage(stor_ids[0])
        harness.remove_storage(stor_ids[0])  # Already detached, so won't fire a hook
        assert len(harness.charm.observed_events) == 3
        assert isinstance(harness.charm.observed_events[0], ops.StorageAttachedEvent)
        assert isinstance(harness.charm.observed_events[1], ops.StorageAttachedEvent)
        assert isinstance(harness.charm.observed_events[2], ops.StorageDetachingEvent)

    def test_actions_from_directory(self, request: pytest.FixtureRequest):
        tmp = pathlib.Path(tempfile.mkdtemp())
        request.addfinalizer(lambda: shutil.rmtree(tmp))
        actions_filename = tmp / 'actions.yaml'
        with actions_filename.open('wt') as actions:
            actions.write(
                textwrap.dedent("""
            test:
                description: a dummy action
            """)
            )
        harness = self._get_dummy_charm_harness(request, tmp)
        harness.begin()
        assert list(harness.framework.meta.actions) == ['test']
        # The charm_dir also gets set
        assert harness.framework.charm_dir == tmp

    def test_actions_from_directory_charmcraft_yaml(self, request: pytest.FixtureRequest):
        tmp = pathlib.Path(tempfile.mkdtemp())
        request.addfinalizer(lambda: shutil.rmtree(tmp))
        charmcraft_filename = tmp / 'charmcraft.yaml'
        charmcraft_filename.write_text(
            textwrap.dedent("""
            type: charm
            bases:
              - build-on:
                  - name: ubuntu
                    channel: "22.04"
                run-on:
                  - name: ubuntu
                    channel: "22.04"

            actions:
              test:
                description: a dummy action
        """)
        )
        harness = self._get_dummy_charm_harness(request, tmp)
        harness.begin()
        assert list(harness.framework.meta.actions) == ['test']
        # The charm_dir also gets set
        assert harness.framework.charm_dir == tmp

    def _get_dummy_charm_harness(self, request: pytest.FixtureRequest, tmp: pathlib.Path):
        self._write_dummy_charm(request, tmp)
        charm_mod = importlib.import_module('testcharm')
        harness = ops.testing.Harness(charm_mod.MyTestingCharm)
        request.addfinalizer(harness.cleanup)
        return harness

    def _write_dummy_charm(self, request: pytest.FixtureRequest, tmp: pathlib.Path):
        srcdir = tmp / 'src'
        srcdir.mkdir(0o755)
        charm_filename = srcdir / 'testcharm.py'
        with charm_filename.open('wt') as charmpy:
            # language=Python
            charmpy.write(
                textwrap.dedent("""
                from ops import CharmBase
                class MyTestingCharm(CharmBase):
                    pass
                """)
            )
        orig = sys.path[:]
        sys.path.append(str(srcdir))

        def cleanup():
            sys.path = orig
            sys.modules.pop('testcharm')

        request.addfinalizer(cleanup)

    def test_actions_passed_in(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
                name: test-app
            """,
            actions="""
                test-action:
                    description: a dummy test action
            """,
        )
        request.addfinalizer(harness.cleanup)
        assert list(harness.framework.meta.actions) == ['test-action']

    def test_event_context(self):
        class MyCharm(ops.CharmBase):
            def event_handler(self, evt: ops.RelationEvent):
                rel = evt.relation
                assert rel is not None and rel.app is not None
                rel.data[rel.app]['foo'] = 'bar'

        harness = ops.testing.Harness(
            MyCharm,
            meta="""
            name: test-charm
            requires:
                db:
                    interface: pgsql
            """,
        )
        harness.begin()
        rel_id = harness.add_relation('db', 'postgresql')
        rel = harness.charm.model.get_relation('db', rel_id)

        event = MagicMock()
        event.relation = rel

        with harness._event_context('my_relation_joined'):
            with pytest.raises(ops.RelationDataError):
                harness.charm.event_handler(event)

    def test_event_context_inverse(self):
        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.framework.observe(self.on.db_relation_joined, self._join_db)

            def _join_db(self, event: ops.EventBase) -> None:
                # do things with APIs we cannot easily mock
                raise NotImplementedError

        harness = ops.testing.Harness(
            MyCharm,
            meta="""
            name: test-charm
            requires:
                db:
                    interface: pgsql
            """,
        )
        harness.begin()

        def mock_join_db(event: ops.EventBase):
            # the harness thinks we're inside a db_relation_joined hook
            # but we want to mock the remote data here:
            assert isinstance(event, ops.RelationEvent)
            with harness._event_context(''):
                # pretend for a moment we're not in a hook context,
                # so the harness will let us:
                event.relation.data[harness.charm.app]['foo'] = 'bar'

        harness.charm._join_db = mock_join_db
        rel_id = harness.add_relation('db', 'remote')
        harness.add_relation_unit(rel_id, 'remote/0')
        rel = harness.charm.model.get_relation('db', rel_id)
        assert rel is not None
        assert harness.get_relation_data(rel_id, 'test-charm') == {'foo': 'bar'}

        # now we're outside of the hook context:
        assert not harness._backend._hook_is_running
        assert rel.data[harness.charm.app]['foo'] == 'bar'

    def test_relation_set_deletes(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_leader(False)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.update_relation_data(rel_id, 'test-charm/0', {'foo': 'bar'})
        harness.add_relation_unit(rel_id, 'postgresql/0')
        rel = harness.charm.model.get_relation('db', rel_id)
        assert rel is not None
        del rel.data[harness.charm.model.unit]['foo']
        assert harness.get_relation_data(rel_id, 'test-charm/0') == {}

    def test_relation_set_nonstring(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_leader(False)
        rel_id = harness.add_relation('db', 'postgresql')
        for invalid_value in (1, 1.2, {}, [], set(), True, object(), type):  # type: ignore
            with pytest.raises(ops.RelationDataError):
                harness.update_relation_data(rel_id, 'test-charm/0', {'foo': invalid_value})  # type: ignore

    def test_set_workload_version(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: app
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        assert harness.get_workload_version() is None
        harness.charm.model.unit.set_workload_version('1.2.3')
        assert harness.get_workload_version() == '1.2.3'

    def test_get_backend_calls(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        # No calls to the backend yet
        assert harness._get_backend_calls() == []
        rel_id = harness.add_relation('db', 'postgresql')

        assert harness._get_backend_calls() == [
            ('relation_ids', 'db'),
            ('relation_list', rel_id),
            ('relation_remote_app_name', 0),
        ]

        # update_relation_data ensures the cached data for the relation is wiped
        harness.update_relation_data(rel_id, 'test-charm/0', {'foo': 'bar'})
        test_charm_unit = harness.model.get_unit('test-charm/0')
        assert harness._get_backend_calls(reset=True) == [
            ('relation_get', 0, 'test-charm/0', False),
            ('update_relation_data', 0, test_charm_unit, 'foo', 'bar'),
        ]

        # add_relation_unit resets the relation_list, but doesn't trigger backend calls
        harness.add_relation_unit(rel_id, 'postgresql/0')
        assert harness._get_backend_calls(reset=False) == []
        # however, update_relation_data does, because we are preparing relation-changed
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo': 'bar'})
        pgql_unit = harness.model.get_unit('postgresql/0')

        assert harness._get_backend_calls(reset=False) == [
            ('relation_ids', 'db'),
            ('relation_list', rel_id),
            ('relation_get', 0, 'postgresql/0', False),
            ('update_relation_data', 0, pgql_unit, 'foo', 'bar'),
        ]
        # If we check again, they are still there, but now we reset it
        assert harness._get_backend_calls(reset=True) == [
            ('relation_ids', 'db'),
            ('relation_list', rel_id),
            ('relation_get', 0, 'postgresql/0', False),
            ('update_relation_data', 0, pgql_unit, 'foo', 'bar'),
        ]
        # And the calls are gone
        assert harness._get_backend_calls() == []

    def test_get_backend_calls_with_kwargs(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            requires:
                db:
                    interface: pgsql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        unit = harness.charm.model.unit
        # Reset the list, because we don't care what it took to get here
        harness._get_backend_calls(reset=True)
        unit.status = ops.ActiveStatus()
        assert harness._get_backend_calls() == [('status_set', 'active', '', {'is_app': False})]
        harness.set_leader(True)
        app = harness.charm.model.app
        harness._get_backend_calls(reset=True)
        app.status = ops.ActiveStatus('message')
        assert harness._get_backend_calls() == [
            ('is_leader',),
            ('status_set', 'active', 'message', {'is_app': True}),
        ]

    def test_unit_status(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: test-app')
        request.addfinalizer(harness.cleanup)
        harness.set_leader(True)
        harness.begin()
        # default status
        assert harness.model.unit.status == ops.MaintenanceStatus('')
        status = ops.ActiveStatus('message')
        harness.model.unit.status = status
        assert harness.model.unit.status == status

    def test_app_status(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: test-app')
        request.addfinalizer(harness.cleanup)
        harness.set_leader(True)
        harness.begin()
        # default status
        assert harness.model.app.status == ops.UnknownStatus()
        status = ops.ActiveStatus('message')
        harness.model.app.status = status
        assert harness.model.app.status == status

    def test_populate_oci_resources(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
              image2:
                type: oci-image
                description: "Another image."
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.populate_oci_resources()
        path = harness.model.resources.fetch('image')
        assert path.name == 'contents.yaml'
        assert path.parent.name == 'image'
        with path.open('r') as resource_file:
            contents = yaml.safe_load(resource_file.read())
        assert contents['registrypath'] == 'registrypath'
        assert contents['username'] == 'username'
        assert contents['password'] == 'password'
        path = harness.model.resources.fetch('image2')
        assert path.name == 'contents.yaml'
        assert path.parent.name == 'image2'

    def test_resource_folder_cleanup(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.populate_oci_resources()
        path = harness.model.resources.fetch('image')
        assert path.exists()
        harness.cleanup()
        assert not path.exists()
        assert not path.parent.exists()
        assert not path.parent.parent.exists()

    def test_container_isdir_and_exists(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              foo:
                resource: foo-image
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_can_connect('foo', True)
        c = harness.model.unit.containers['foo']

        dir_path = '/tmp/foo/dir'  # noqa: S108
        file_path = '/tmp/foo/file'  # noqa: S108

        assert not c.isdir(dir_path)
        assert not c.exists(dir_path)
        assert not c.isdir(file_path)
        assert not c.exists(file_path)

        c.make_dir(dir_path, make_parents=True)
        c.push(file_path, 'data')

        assert c.isdir(dir_path)
        assert c.exists(dir_path)
        assert not c.isdir(file_path)
        assert c.exists(file_path)

    def test_add_oci_resource_custom(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        custom = {
            'registrypath': 'custompath',
            'username': 'custom_username',
            'password': 'custom_password',
        }
        harness.add_oci_resource('image', custom)
        resource = harness.model.resources.fetch('image')
        with resource.open('r') as resource_file:
            contents = yaml.safe_load(resource_file.read())
        assert contents['registrypath'] == 'custompath'
        assert contents['username'] == 'custom_username'
        assert contents['password'] == 'custom_password'

    def test_add_oci_resource_no_image(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        with pytest.raises(RuntimeError):
            harness.add_oci_resource('image')
        with pytest.raises(RuntimeError):
            harness.add_oci_resource('missing-resource')
        assert len(harness._backend._resources_map) == 0

    def test_add_resource_unknown(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        with pytest.raises(RuntimeError):
            harness.add_resource('unknown', 'content')

    def test_add_resource_but_oci(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        with pytest.raises(RuntimeError):
            harness.add_resource('image', 'content')

    def test_add_resource_string(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: file
                filename: foo.txt
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.add_resource('image', 'foo contents\n')
        path = harness.model.resources.fetch('image')
        assert path.name == 'foo.txt'
        assert path.parent.name == 'image'
        with path.open('rt') as f:
            assert f.read() == 'foo contents\n'

    def test_add_resource_bytes(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: file
                filename: foo.zip
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        raw_contents = b'\xff\xff\x00blah\n'
        harness.add_resource('image', raw_contents)
        path = harness.model.resources.fetch('image')
        assert path.name == 'foo.zip'
        assert path.parent.name == 'image'
        with path.open('rb') as f:
            assert raw_contents == f.read()

    def test_add_resource_unknown_filename(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.add_resource('image', 'foo contents\n')
        path = harness.model.resources.fetch('image')
        assert path.name == 'image'
        assert path.parent.name == 'image'

    def test_get_pod_spec(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_leader(True)
        container_spec = {'container': 'spec'}
        k8s_resources = {'k8s': 'spec'}
        harness.model.pod.set_spec(container_spec, k8s_resources)
        assert harness.get_pod_spec() == (container_spec, k8s_resources)

    def test_begin_with_initial_hooks_no_relations(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
            name: test-app
            """,
            config="""
            options:
                foo:
                    description: a config option
                    type: string
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.update_config({'foo': 'bar'})
        harness.set_leader(True)
        with pytest.raises(RuntimeError):
            _ = harness.charm
        harness.begin_with_initial_hooks()
        assert harness.charm is not None
        assert harness.charm.changes == [
            {'name': 'install'},
            {'name': 'leader-elected'},
            {'name': 'config-changed', 'data': {'foo': 'bar'}},
            {'name': 'start'},
        ]

    def test_begin_with_initial_hooks_no_relations_not_leader(
        self,
        request: pytest.FixtureRequest,
    ):
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
            name: test-app
            """,
            config="""
            options:
                foo:
                    description: a config option
                    type: string
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.update_config({'foo': 'bar'})
        with pytest.raises(RuntimeError):
            _ = harness.charm
        harness.begin_with_initial_hooks()
        assert harness.charm is not None
        assert harness.charm.changes == [
            {'name': 'install'},
            {'name': 'leader-settings-changed'},
            {'name': 'config-changed', 'data': {'foo': 'bar'}},
            {'name': 'start'},
        ]

    def test_begin_with_initial_hooks_with_peer_relation(self, request: pytest.FixtureRequest):
        class PeerCharm(RelationEventCharm):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observe_relation_events('peer')

        harness = ops.testing.Harness(
            PeerCharm,
            meta="""
            name: test-app
            peers:
              peer:
                interface: app-peer
            """,
            config="""
            options:
                foo:
                    description: a config option
                    type: string
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.update_config({'foo': 'bar'})
        with pytest.raises(RuntimeError):
            _ = harness.charm
        harness.begin_with_initial_hooks()
        assert harness.charm is not None
        rel = harness.model.get_relation('peer')
        assert rel is not None
        rel_id = rel.id
        assert harness.charm.changes == [
            {'name': 'install'},
            {
                'name': 'relation-created',
                'relation': 'peer',
                'data': {
                    'relation_id': rel_id,
                    'unit': None,
                    'app': 'test-app',
                },
            },
            {'name': 'leader-settings-changed'},
            {'name': 'config-changed', 'data': {'foo': 'bar'}},
            {'name': 'start'},
        ]
        # With a single unit, no peer-relation-joined is fired

    def test_begin_with_initial_hooks_peer_relation_pre_defined(
        self,
        request: pytest.FixtureRequest,
    ):
        class PeerCharm(RelationEventCharm):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observe_relation_events('peer')

        harness = ops.testing.Harness(
            PeerCharm,
            meta="""
            name: test-app
            peers:
              peer:
                interface: app-peer
            """,
        )
        request.addfinalizer(harness.cleanup)
        peer_rel_id = harness.add_relation('peer', 'test-app')
        harness.begin_with_initial_hooks()
        # If the peer relation is already defined by the user, we don't create the relation a
        # second time, but we do still fire relation-created.
        assert harness.charm.changes == [
            {'name': 'install'},
            {
                'name': 'relation-created',
                'relation': 'peer',
                'data': {
                    'relation_id': peer_rel_id,
                    'unit': None,
                    'app': 'test-app',
                },
            },
            {'name': 'leader-settings-changed'},
            {'name': 'config-changed', 'data': {}},
            {'name': 'start'},
        ]

    def test_begin_with_initial_hooks_relation_charm_with_no_relation(
        self,
        request: pytest.FixtureRequest,
    ):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observe_relation_events('db')

        harness = ops.testing.Harness(
            CharmWithDB,
            meta="""
            name: test-app
            requires:
              db:
                interface: sql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_leader()
        harness.begin_with_initial_hooks()
        assert harness.charm.changes == [
            {'name': 'install'},
            {'name': 'leader-elected'},
            {'name': 'config-changed', 'data': {}},
            {'name': 'start'},
        ]

    def test_begin_with_initial_hooks_with_one_relation(self, request: pytest.FixtureRequest):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observe_relation_events('db')

        harness = ops.testing.Harness(
            CharmWithDB,
            meta="""
            name: test-app
            requires:
              db:
                interface: sql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_leader()
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'new': 'data'})
        harness.begin_with_initial_hooks()
        assert harness.charm.changes == [
            {'name': 'install'},
            {
                'name': 'relation-created',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': None,
                    'app': 'postgresql',
                },
            },
            {'name': 'leader-elected'},
            {'name': 'config-changed', 'data': {}},
            {'name': 'start'},
            {
                'name': 'relation-joined',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': 'postgresql/0',
                    'app': 'postgresql',
                },
            },
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': 'postgresql/0',
                    'app': 'postgresql',
                },
            },
        ]

    def test_begin_with_initial_hooks_with_application_data(self, request: pytest.FixtureRequest):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observe_relation_events('db')

        harness = ops.testing.Harness(
            CharmWithDB,
            meta="""
            name: test-app
            requires:
              db:
                interface: sql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_leader()
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'new': 'data'})
        harness.update_relation_data(rel_id, 'postgresql', {'app': 'data'})
        harness.begin_with_initial_hooks()
        assert harness.charm.changes == [
            {'name': 'install'},
            {
                'name': 'relation-created',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': None,
                    'app': 'postgresql',
                },
            },
            {'name': 'leader-elected'},
            {'name': 'config-changed', 'data': {}},
            {'name': 'start'},
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': None,
                    'app': 'postgresql',
                },
            },
            {
                'name': 'relation-joined',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': 'postgresql/0',
                    'app': 'postgresql',
                },
            },
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': 'postgresql/0',
                    'app': 'postgresql',
                },
            },
        ]

    def test_begin_with_initial_hooks_with_multiple_units(self, request: pytest.FixtureRequest):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observe_relation_events('db')

        harness = ops.testing.Harness(
            CharmWithDB,
            meta="""
            name: test-app
            requires:
              db:
                interface: sql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_leader()
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/1')
        harness.update_relation_data(rel_id, 'postgresql/1', {'new': 'data'})
        # We intentionally add 0 after 1 to assert that the code triggers them in order
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.begin_with_initial_hooks()
        assert harness.charm.changes == [
            {'name': 'install'},
            {
                'name': 'relation-created',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': None,
                    'app': 'postgresql',
                },
            },
            {'name': 'leader-elected'},
            {'name': 'config-changed', 'data': {}},
            {'name': 'start'},
            {
                'name': 'relation-joined',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': 'postgresql/0',
                    'app': 'postgresql',
                },
            },
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': 'postgresql/0',
                    'app': 'postgresql',
                },
            },
            {
                'name': 'relation-joined',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': 'postgresql/1',
                    'app': 'postgresql',
                },
            },
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id,
                    'unit': 'postgresql/1',
                    'app': 'postgresql',
                },
            },
        ]

    def test_begin_with_initial_hooks_multiple_relation_same_endpoint(
        self,
        request: pytest.FixtureRequest,
    ):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.observe_relation_events('db')

        harness = ops.testing.Harness(
            CharmWithDB,
            meta="""
            name: test-app
            requires:
              db:
                interface: sql
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_leader()
        rel_id_a = harness.add_relation('db', 'pg-a')
        harness.add_relation_unit(rel_id_a, 'pg-a/0')
        rel_id_b = harness.add_relation('db', 'pg-b')
        harness.add_relation_unit(rel_id_b, 'pg-b/0')
        harness.begin_with_initial_hooks()
        changes = harness.charm.changes[:]
        expected_prefix = [
            {'name': 'install'},
        ]
        # The first events are always the same
        assert changes[: len(expected_prefix)] == expected_prefix
        changes = changes[len(expected_prefix) :]
        # However, the order of relation-created events can be in any order
        expected_relation_created = [
            {
                'name': 'relation-created',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id_a,
                    'unit': None,
                    'app': 'pg-a',
                },
            },
            {
                'name': 'relation-created',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id_b,
                    'unit': None,
                    'app': 'pg-b',
                },
            },
        ]
        if changes[:2] != expected_relation_created:
            # change the order
            expected_relation_created = [
                expected_relation_created[1],
                expected_relation_created[0],
            ]
        assert changes[:2] == expected_relation_created
        changes = changes[2:]
        expected_middle: typing.List[typing.Dict[str, typing.Any]] = [
            {'name': 'leader-elected'},
            {'name': 'config-changed', 'data': {}},
            {'name': 'start'},
        ]
        assert changes[: len(expected_middle)] == expected_middle
        changes = changes[len(expected_middle) :]
        a_first = [
            {
                'name': 'relation-joined',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id_a,
                    'unit': 'pg-a/0',
                    'app': 'pg-a',
                },
            },
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id_a,
                    'unit': 'pg-a/0',
                    'app': 'pg-a',
                },
            },
            {
                'name': 'relation-joined',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id_b,
                    'unit': 'pg-b/0',
                    'app': 'pg-b',
                },
            },
            {
                'name': 'relation-changed',
                'relation': 'db',
                'data': {
                    'relation_id': rel_id_b,
                    'unit': 'pg-b/0',
                    'app': 'pg-b',
                },
            },
        ]
        if changes != a_first:
            b_first = [a_first[2], a_first[3], a_first[0], a_first[1]]
            assert changes == b_first

    def test_begin_with_initial_hooks_unknown_status(self, request: pytest.FixtureRequest):
        # Verify that a charm that does not set a status in the install hook will have an
        # unknown status in the harness.
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
            name: test-app
            """,
            config="""
          options:
                foo:
                    description: a config option
                    type: string
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        harness.begin_with_initial_hooks()

        assert backend.status_get(is_app=False) == {'status': 'unknown', 'message': ''}

        assert backend.status_get(is_app=True) == {'status': 'unknown', 'message': ''}

    def test_begin_with_initial_hooks_install_sets_status(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            RecordingCharm,
            meta="""
            name: test-app
            """,
            config="""
            options:
                set_status:
                    description: a config option
                    type: boolean

            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        harness.update_config(key_values={'set_status': True})
        harness.begin_with_initial_hooks()

        assert backend.status_get(is_app=False) == {
            'status': 'maintenance',
            'message': 'Status set on install',
        }

    def test_get_pebble_container_plan(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              foo:
                resource: foo-image
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_can_connect('foo', True)
        initial_plan = harness.get_container_pebble_plan('foo')
        assert initial_plan.to_yaml() == '{}\n'
        container = harness.model.unit.get_container('foo')
        container.pebble.add_layer(
            'test-ab',
            """\
            summary: test-layer
            description: a layer that we can use for testing
            services:
              a:
                command: /bin/echo hello from a
              b:
                command: /bin/echo hello from b
            """,
        )
        container.pebble.add_layer(
            'test-c',
            """\
            summary: test-for-c
            services:
              c:
                command: /bin/echo hello from c
            """,
        )
        plan = container.pebble.get_plan()
        assert plan.to_yaml() == textwrap.dedent("""\
            services:
              a:
                command: /bin/echo hello from a
              b:
                command: /bin/echo hello from b
              c:
                command: /bin/echo hello from c
            """)
        harness_plan = harness.get_container_pebble_plan('foo')
        assert harness_plan.to_yaml() == plan.to_yaml()

    def test_add_layer_with_log_targets_to_plan(self):
        layer_yaml = """\
        services:
         foo:
          override: replace
          command: echo foo

        checks:
         bar:
          http:
           https://example.com/

        log-targets:
         baz:
          override: replace
          type: loki
          location: https://example.com:3100/loki/api/v1/push
        """
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({
                'name': 'foo',
                'containers': {'consumer': {'type': 'oci-image'}},
            }),
        )
        harness.begin()
        harness.set_can_connect('consumer', True)

        container = harness.charm.unit.containers['consumer']
        layer = pebble.Layer(layer_yaml)
        container.add_layer('foo', layer)

        plan = container.get_plan()

        assert plan.services.get('foo') is not None
        assert plan.checks.get('bar') is not None
        assert plan.log_targets.get('baz') is not None

    def test_get_pebble_container_plan_unknown(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              foo:
                resource: foo-image
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_can_connect('foo', True)
        with pytest.raises(KeyError):
            harness.get_container_pebble_plan('unknown')
        plan = harness.get_container_pebble_plan('foo')
        assert plan.to_yaml() == '{}\n'

    def test_container_pebble_ready(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ContainerEventCharm,
            meta="""
            name: test-app
            containers:
              foo:
                resource: foo-image
        """,
        )
        request.addfinalizer(harness.cleanup)
        # This is a no-op if it is called before begin(), but it isn't an error
        harness.container_pebble_ready('foo')
        harness.begin()
        harness.charm.observe_container_events('foo')
        harness.container_pebble_ready('foo')
        assert harness.charm.changes == [
            {
                'name': 'pebble-ready',
                'container': 'foo',
            },
        ]

    def test_get_filesystem_root(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              foo:
                resource: foo-image
        """,
        )
        foo_root = harness.get_filesystem_root('foo')
        assert foo_root.exists()
        assert foo_root.is_dir()
        harness.begin()
        container = harness.charm.unit.get_container('foo')
        assert foo_root == harness.get_filesystem_root(container)

    def test_evaluate_status(self):
        class TestCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.framework.observe(self.on.collect_app_status, self._on_collect_app_status)
                self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)
                self.app_status_to_add = ops.BlockedStatus('blocked app')
                self.unit_status_to_add = ops.BlockedStatus('blocked unit')

            def _on_collect_app_status(self, event: ops.CollectStatusEvent):
                event.add_status(self.app_status_to_add)

            def _on_collect_unit_status(self, event: ops.CollectStatusEvent):
                event.add_status(self.unit_status_to_add)

        harness = ops.testing.Harness(TestCharm)
        harness.set_leader(True)
        harness.begin()
        # Tests for the behaviour of status evaluation are in test_charm.py
        harness.evaluate_status()
        assert harness.model.app.status == ops.BlockedStatus('blocked app')
        assert harness.model.unit.status == ops.BlockedStatus('blocked unit')

        harness.charm.app_status_to_add = ops.ActiveStatus('active app')
        harness.charm.unit_status_to_add = ops.ActiveStatus('active unit')
        harness.evaluate_status()
        assert harness.model.app.status == ops.ActiveStatus('active app')
        assert harness.model.unit.status == ops.ActiveStatus('active unit')

    def test_invalid_status_set(self):
        harness = ops.testing.Harness(ops.CharmBase)
        harness.set_leader(True)
        harness.begin()

        with pytest.raises(ops.model.ModelError):
            harness.model.app.status = ops.UnknownStatus()
        with pytest.raises(ops.model.ModelError):
            harness.model.app.status = ops.ErrorStatus()
        harness.model.app.status = ops.ActiveStatus()

        with pytest.raises(ops.model.ModelError):
            harness.model.unit.status = ops.UnknownStatus()
        with pytest.raises(ops.model.ModelError):
            harness.model.unit.status = ops.ErrorStatus()
        harness.model.unit.status = ops.ActiveStatus()


class TestNetwork:
    @pytest.fixture
    def harness(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            requires:
               db:
                 interface: database
               foo:
                 interface: xyz
            """,
        )
        yield harness
        harness.cleanup()

    def test_add_network_defaults(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.add_network('10.0.0.10')

        binding = harness.model.get_binding('db')
        assert binding is not None
        assert binding.name == 'db'
        network = binding.network
        assert network.bind_address == ipaddress.IPv4Address('10.0.0.10')
        assert network.ingress_address == ipaddress.IPv4Address('10.0.0.10')
        assert network.ingress_addresses == [ipaddress.IPv4Address('10.0.0.10')]
        assert network.egress_subnets == [ipaddress.IPv4Network('10.0.0.0/24')]
        assert len(network.interfaces) == 1
        interface = network.interfaces[0]
        assert interface.name == 'eth0'
        assert interface.address == ipaddress.IPv4Address('10.0.0.10')
        assert interface.subnet == ipaddress.IPv4Network('10.0.0.0/24')

    def test_add_network_all_args(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db', 'postgresql')
        harness.add_network(
            '10.0.0.10',
            endpoint='db',
            relation_id=relation_id,
            cidr='10.0.0.0/8',
            interface='eth1',
            ingress_addresses=['10.0.0.1', '10.0.0.2'],
            egress_subnets=['10.0.0.0/8', '10.10.0.0/16'],
        )

        relation = harness.model.get_relation('db', relation_id)
        assert relation is not None
        binding = harness.model.get_binding(relation)
        assert binding is not None
        assert binding.name == 'db'
        network = binding.network
        assert network.bind_address == ipaddress.IPv4Address('10.0.0.10')
        assert network.ingress_address == ipaddress.IPv4Address('10.0.0.1')
        assert network.ingress_addresses == [
            ipaddress.IPv4Address('10.0.0.1'),
            ipaddress.IPv4Address('10.0.0.2'),
        ]
        assert network.egress_subnets == [
            ipaddress.IPv4Network('10.0.0.0/8'),
            ipaddress.IPv4Network('10.10.0.0/16'),
        ]
        assert len(network.interfaces) == 1
        interface = network.interfaces[0]
        assert interface.name == 'eth1'
        assert interface.address == ipaddress.IPv4Address('10.0.0.10')
        assert interface.subnet == ipaddress.IPv4Network('10.0.0.0/8')

    def test_add_network_specific_endpoint(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.add_network('10.0.0.1')
        harness.add_network('10.0.2.1', endpoint='db')

        binding = harness.model.get_binding('db')
        assert binding is not None
        assert binding.name == 'db'
        network = binding.network
        assert network.bind_address == ipaddress.IPv4Address('10.0.2.1')

        # Ensure binding for the other interface is still on the default value
        foo_binding = harness.model.get_binding('foo')
        assert foo_binding is not None
        assert foo_binding.network.bind_address == ipaddress.IPv4Address('10.0.0.1')

    def test_add_network_specific_relation(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.add_network('10.0.0.1')
        harness.add_network('10.0.2.1', endpoint='db')
        relation_id = harness.add_relation('db', 'postgresql')
        harness.add_network('35.0.0.1', endpoint='db', relation_id=relation_id)

        relation = harness.model.get_relation('db', relation_id)
        assert relation is not None
        binding = harness.model.get_binding(relation)
        assert binding is not None
        assert binding.name == 'db'
        network = binding.network
        assert network.bind_address == ipaddress.IPv4Address('35.0.0.1')

        # Ensure binding for the other interface is still on the default value
        foo_binding = harness.model.get_binding('foo')
        assert foo_binding is not None
        assert foo_binding.network.bind_address == ipaddress.IPv4Address('10.0.0.1')

    def test_add_network_endpoint_fallback(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db', 'postgresql')
        harness.add_network('10.0.0.10', endpoint='db')

        relation = harness.model.get_relation('db', relation_id)
        assert relation is not None
        binding = harness.model.get_binding(relation)
        assert binding is not None
        assert binding.name == 'db'
        network = binding.network
        assert network.bind_address == ipaddress.IPv4Address('10.0.0.10')

    def test_add_network_default_fallback(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.add_network('10.0.0.10')

        binding = harness.model.get_binding('db')
        assert binding is not None
        assert binding.name == 'db'
        network = binding.network
        assert network.bind_address == ipaddress.IPv4Address('10.0.0.10')

    def test_add_network_ipv6(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.add_network('2001:0db8::a:0:0:1')

        binding = harness.model.get_binding('db')
        assert binding is not None
        assert binding.name == 'db'
        network = binding.network
        assert network.bind_address == ipaddress.IPv6Address('2001:0db8::a:0:0:1')
        assert network.ingress_address == ipaddress.IPv6Address('2001:0db8::a:0:0:1')
        assert network.ingress_addresses == [ipaddress.IPv6Address('2001:0db8::a:0:0:1')]
        assert network.egress_subnets == [ipaddress.IPv6Network('2001:0db8::0:0:0:0/64')]
        assert len(network.interfaces) == 1
        interface = network.interfaces[0]
        assert interface.name == 'eth0'
        assert interface.address == ipaddress.IPv6Address('2001:0db8::a:0:0:1')
        assert interface.subnet == ipaddress.IPv6Network('2001:0db8::0:0:0:0/64')

    def test_network_get_relation_not_found(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(ops.RelationNotFoundError):
            binding = harness.model.get_binding('db')
            assert binding is not None
            binding.network

    def test_add_relation_network_get(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.add_relation('db', 'remote')
        binding = harness.model.get_binding('db')
        assert binding is not None
        assert binding.network

    def test_add_network_endpoint_not_in_meta(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(ops.ModelError):
            harness.add_network('35.0.0.1', endpoint='xyz')

    def test_add_network_relation_id_set_endpoint_not_set(
        self, harness: ops.testing.Harness[ops.CharmBase]
    ):
        relation_id = harness.add_relation('db', 'postgresql')
        with pytest.raises(TypeError):
            harness.add_network('35.0.0.1', relation_id=relation_id)

    def test_add_network_relation_id_incorrect(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db', 'postgresql')
        with pytest.raises(ops.ModelError):
            harness.add_network('35.0.0.1', endpoint='db', relation_id=relation_id + 1)

    def test_add_network_endpoint_and_relation_id_do_not_correspond(
        self, harness: ops.testing.Harness[ops.CharmBase]
    ):
        relation_id = harness.add_relation('db', 'postgresql')
        with pytest.raises(ops.ModelError):
            harness.add_network('35.0.0.1', endpoint='foo', relation_id=relation_id)


class DBRelationChangedHelper(ops.Object):
    def __init__(self, parent: ops.Object, key: str):
        super().__init__(parent, key)
        self.changes: typing.List[typing.Tuple[int, str]] = []
        parent.framework.observe(parent.on.db_relation_changed, self.on_relation_changed)

    def on_relation_changed(self, event: ops.RelationEvent):
        if event.unit is not None:
            self.changes.append((event.relation.id, event.unit.name))
        else:
            app = event.app
            assert app is not None
            self.changes.append((event.relation.id, app.name))


class RelationChangedViewer(ops.Object):
    """Track relation_changed events and saves the data seen in the relation bucket."""

    def __init__(self, charm: ops.CharmBase, relation_name: str):
        super().__init__(charm, relation_name)
        self.changes: typing.List[typing.Dict[str, typing.Any]] = []
        charm.framework.observe(charm.on[relation_name].relation_changed, self.on_relation_changed)

    def on_relation_changed(self, event: ops.RelationEvent):
        if event.unit is not None:
            data = event.relation.data[event.unit]
        else:
            app = event.app
            assert app is not None
            data = event.relation.data[app]
        self.changes.append(dict(data))


class RecordingCharm(ops.CharmBase):
    """Record the events that we see, and any associated data."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.changes: typing.List[typing.Dict[str, typing.Any]] = []
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.leader_settings_changed, self._on_leader_settings_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.secret_changed, self._on_secret_changed)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.update_status, self._on_update_status)

    def get_changes(self, reset: bool = True):
        changes = self.changes
        if reset:
            self.changes = []
        return changes

    def _on_install(self, _: ops.InstallEvent):
        if self.config.get('set_status'):
            self.unit.status = ops.MaintenanceStatus('Status set on install')
        self.changes.append({'name': 'install'})

    def _on_start(self, _: ops.StartEvent):
        self.changes.append({'name': 'start'})

    def _on_stop(self, _: ops.StopEvent):
        self.changes.append({'name': 'stop'})

    def _on_remove(self, _: ops.RemoveEvent):
        self.changes.append({'name': 'remove'})

    def _on_config_changed(self, _: ops.ConfigChangedEvent):
        self.changes.append({'name': 'config-changed', 'data': dict(self.framework.model.config)})

    def _on_leader_elected(self, _: ops.LeaderElectedEvent):
        self.changes.append({'name': 'leader-elected'})

    def _on_leader_settings_changed(self, _: ops.LeaderSettingsChangedEvent):
        self.changes.append({'name': 'leader-settings-changed'})

    def _on_secret_changed(self, _: ops.SecretChangedEvent):
        self.changes.append({'name': 'secret-changed'})

    def _on_upgrade_charm(self, _: ops.UpgradeCharmEvent):
        self.changes.append({'name': 'upgrade-charm'})

    def _on_update_status(self, _: ops.UpdateStatusEvent):
        self.changes.append({'name': 'update-status'})


class RelationEventCharm(RecordingCharm):
    """Record events related to relation lifecycles."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        # When set, this instructs the charm to include a 'relation_data' field in the 'data'
        # section of each change it logs, which allows us to test which relation data was available
        # in each hook invocation
        self.record_relation_data_on_events = False

    def observe_relation_events(self, relation_name: str):
        self.relation_name = relation_name
        self.framework.observe(self.on[relation_name].relation_created, self._on_relation_created)
        self.framework.observe(self.on[relation_name].relation_joined, self._on_relation_joined)
        self.framework.observe(self.on[relation_name].relation_changed, self._on_relation_changed)
        self.framework.observe(
            self.on[relation_name].relation_departed, self._on_relation_departed
        )
        self.framework.observe(self.on[relation_name].relation_broken, self._on_relation_broken)

    def _on_relation_created(self, event: ops.RelationCreatedEvent):
        self._observe_relation_event('relation-created', event)

    def _on_relation_joined(self, event: ops.RelationJoinedEvent):
        self._observe_relation_event('relation-joined', event)

    def _on_relation_changed(self, event: ops.RelationChangedEvent):
        self._observe_relation_event('relation-changed', event)

    def _on_relation_departed(self, event: ops.RelationDepartedEvent):
        self._observe_relation_event('relation-departed', event)

    def _on_relation_broken(self, event: ops.RelationBrokenEvent):
        self._observe_relation_event('relation-broken', event)

    def _observe_relation_event(self, event_name: str, event: ops.RelationEvent):
        unit_name = None
        if event.unit is not None:
            unit_name = event.unit.name
        app_name = None
        if event.app is not None:
            app_name = event.app.name

        data = dict(app=app_name, unit=unit_name, relation_id=event.relation.id)
        if isinstance(event, ops.RelationDepartedEvent):
            assert event.departing_unit is not None
            data['departing_unit'] = event.departing_unit.name

        recording: typing.Dict[str, typing.Any] = {
            'name': event_name,
            'relation': event.relation.name,
            'data': data,
        }

        if self.record_relation_data_on_events:
            recording['data'].update({
                'relation_data': {
                    str(x.name): dict(event.relation.data[x]) for x in event.relation.data
                }
            })

        self.changes.append(recording)


class ContainerEventCharm(RecordingCharm):
    """Record events related to container lifecycles."""

    def observe_container_events(self, container_name: str):
        self.framework.observe(self.on[container_name].pebble_ready, self._on_pebble_ready)
        self.framework.observe(
            self.on[container_name].pebble_custom_notice, self._on_pebble_custom_notice
        )
        self.framework.observe(
            self.on[container_name].pebble_check_failed, self._on_pebble_check_failed
        )
        self.framework.observe(
            self.on[container_name].pebble_check_recovered, self._on_pebble_check_recovered
        )

    def _on_pebble_ready(self, event: ops.PebbleReadyEvent):
        self.changes.append({
            'name': 'pebble-ready',
            'container': event.workload.name,
        })

    def _on_pebble_custom_notice(self, event: ops.PebbleCustomNoticeEvent):
        type_str = (
            event.notice.type.value
            if isinstance(event.notice.type, pebble.NoticeType)
            else event.notice.type
        )
        self.changes.append({
            'name': 'pebble-custom-notice',
            'container': event.workload.name,
            'notice_id': event.notice.id,
            'notice_type': type_str,
            'notice_key': event.notice.key,
        })

    def _on_pebble_check_failed(self, event: ops.PebbleCheckFailedEvent):
        self.changes.append({
            'name': 'pebble-check-failed',
            'container': event.workload.name,
            'check_name': event.info.name,
        })

    def _on_pebble_check_recovered(self, event: ops.PebbleCheckRecoveredEvent):
        self.changes.append({
            'name': 'pebble-check-recovered',
            'container': event.workload.name,
            'check_name': event.info.name,
        })


def get_public_methods(obj: object):
    """Get the public attributes of obj to compare to another object."""
    public: typing.Set[str] = set()
    members = inspect.getmembers(obj)
    for name, member in members:
        if name.startswith('_'):
            continue
        if inspect.isfunction(member) or inspect.ismethod(member):
            public.add(name)
    return public


class TestTestingModelBackend:
    def test_conforms_to_model_backend(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: app
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        mb_methods = get_public_methods(_ModelBackend)
        backend_methods = get_public_methods(backend)
        assert mb_methods == backend_methods

    def test_model_uuid_is_uuid_v4(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
        """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        assert uuid.UUID(backend.model_uuid).version == 4

    def test_status_set_get_unit(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: app
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        backend.status_set('blocked', 'message', is_app=False)
        assert backend.status_get(is_app=False) == {'status': 'blocked', 'message': 'message'}
        assert backend.status_get(is_app=True) == {'status': 'unknown', 'message': ''}

    def test_status_set_get_app(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: app
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        backend.status_set('blocked', 'message', is_app=True)
        assert backend.status_get(is_app=True) == {'status': 'blocked', 'message': 'message'}
        assert backend.status_get(is_app=False) == {'status': 'maintenance', 'message': ''}

    def test_relation_ids_unknown_relation(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            provides:
              db:
                interface: mydb
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        # With no relations added, we just get an empty list for the interface
        assert backend.relation_ids('db') == []
        # But an unknown interface raises a ModelError
        with pytest.raises(ops.ModelError):
            backend.relation_ids('unknown')

    def test_relation_get_unknown_relation_id(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        with pytest.raises(ops.RelationNotFoundError):
            backend.relation_get(1234, 'unit/0', False)

    def test_relation_list_unknown_relation_id(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        with pytest.raises(ops.RelationNotFoundError):
            backend.relation_list(1234)

    def test_lazy_resource_directory(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        harness.populate_oci_resources()
        backend = harness._backend
        assert backend._resource_dir is None
        path = backend.resource_get('image')
        assert backend._resource_dir is not None
        assert str(path).startswith(
            str(backend._resource_dir.name)
        ), f'expected {path} to be a subdirectory of {backend._resource_dir.name}'

    def test_resource_get_no_resource(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend
        with pytest.raises(ops.ModelError) as excinfo:
            backend.resource_get('foo')
        assert 'units/unit-test-app-0/resources/foo: resource#test-app/foo not found' in str(
            excinfo.value
        )

    def test_relation_remote_app_name(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-charm
            requires:
               db:
                 interface: foo
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend

        assert backend.relation_remote_app_name(1) is None

        rel_id = harness.add_relation('db', 'postgresql')
        assert backend.relation_remote_app_name(rel_id) == 'postgresql'
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.add_relation_unit(rel_id, 'postgresql/1')
        assert backend.relation_remote_app_name(rel_id) == 'postgresql'

        assert backend.relation_remote_app_name(7) is None

    def test_get_pebble_methods(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            """,
        )
        request.addfinalizer(harness.cleanup)
        backend = harness._backend

        client = backend.get_pebble('/custom/socket/path')
        assert isinstance(client, _TestingPebbleClient)

    def test_reboot(self, request: pytest.FixtureRequest):
        class RebootingCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.framework.observe(self.on.install, self._reboot_now)
                self.framework.observe(self.on.remove, self._reboot)

            def _reboot_now(self, event: ops.InstallEvent):
                self.unit.reboot(now=True)

            def _reboot(self, event: ops.RemoveEvent):
                self.unit.reboot()

        harness = ops.testing.Harness(
            RebootingCharm,
            meta="""
            name: test-app
            """,
        )
        request.addfinalizer(harness.cleanup)
        assert harness.reboot_count == 0
        backend = harness._backend
        backend.reboot()
        assert harness.reboot_count == 1
        with pytest.raises(SystemExit):
            backend.reboot(now=True)
        assert harness.reboot_count == 2
        harness.begin()
        with pytest.raises(SystemExit):
            harness.charm.on.install.emit()
        assert harness.reboot_count == 3
        harness.charm.on.remove.emit()
        assert harness.reboot_count == 4


# For testing non file ops of the pebble testing client.
class TestTestingPebbleClient:
    @pytest.fixture
    def client(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              mycontainer: {}
            """,
        )
        backend = harness._backend
        client = backend.get_pebble('/charm/containers/mycontainer/pebble.socket')
        harness.set_can_connect('mycontainer', True)
        yield client
        harness.cleanup()

    def test_methods_match_pebble_client(self, client: _TestingPebbleClient):
        assert client is not None
        pebble_client_methods = get_public_methods(pebble.Client)
        testing_client_methods = get_public_methods(client)
        assert pebble_client_methods == testing_client_methods

    def test_add_layer(self, client: _TestingPebbleClient):
        plan = client.get_plan()
        assert isinstance(plan, pebble.Plan)
        assert plan.to_yaml() == '{}\n'
        client.add_layer(
            'foo',
            pebble.Layer("""\
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
            """),
        )
        plan = client.get_plan()
        # The YAML should be normalized
        assert (
            textwrap.dedent("""\
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
            """)
            == plan.to_yaml()
        )

    def test_add_layer_merge(self, client: _TestingPebbleClient):
        plan = client.get_plan()
        assert isinstance(plan, pebble.Plan)
        assert plan.to_yaml() == '{}\n'
        client.add_layer(
            'foo',
            pebble.Layer("""\
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
            """),
        )
        plan = client.get_plan()
        # The YAML should be normalized
        assert (
            textwrap.dedent("""\
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
            """)
            == plan.to_yaml()
        )

        client.add_layer(
            'foo',
            pebble.Layer("""\
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
            """),
            combine=True,
        )
        plan = client.get_plan()
        # The YAML should be normalized
        assert (
            textwrap.dedent("""\
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
            """)
            == plan.to_yaml()
        )

    def test_add_layer_checks_combine_override_replace(self, client: _TestingPebbleClient):
        plan = client.get_plan()
        assert isinstance(plan, pebble.Plan)
        assert plan.to_yaml() == '{}\n'
        client.add_layer(
            'foo',
            pebble.Layer("""\
            checks:
                up:
                    level: alive
                    period: 30s
                    threshold: 1
                    exec:
                        command: service nginx status
                ready-http:
                    level: ready
                    period: 30s
                    threshold: 1
                    http:
                        url: https://example.com:3100/health
                        headers:
                            header1: value1
                ready-tcp:
                    level: ready
                    period: 30s
                    threshold: 1
                    tcp:
                        port: 8080
                        host: localhost
            """),
        )
        client.add_layer(
            'foo',
            """\
            checks:
                up:
                    override: replace
                    level: alive
                    period: 10s
                    threshold: 5
                    exec:
                        command: service nginx status
                        environment:
                            key1: value1
                ready-http:
                    override: replace
                    level: ready
                    period: 10s
                    threshold: 5
                    http:
                        url: https://example.com:3101/health
                ready-tcp:
                    override: replace
                    level: ready
                    period: 10s
                    threshold: 5
                    tcp:
                        port: 8081
                        host: localhost1
            """,
            combine=True,
        )
        # Expected changes:
        #  * All checks should have `period` 10s and `threshold` 5
        #  * `environment` should be added to `up` check
        #  * `headers` should be removed from `ready-http` check
        #  * `port` and `host` should be replaced by new ones in `ready-tcp` check
        plan = client.get_plan()
        assert (
            textwrap.dedent("""\
            checks:
              ready-http:
                http:
                  url: https://example.com:3101/health
                level: ready
                override: replace
                period: 10s
                threshold: 5
              ready-tcp:
                level: ready
                override: replace
                period: 10s
                tcp:
                  host: localhost1
                  port: 8081
                threshold: 5
              up:
                exec:
                  command: service nginx status
                  environment:
                    key1: value1
                level: alive
                override: replace
                period: 10s
                threshold: 5
            """)
            == plan.to_yaml()
        )

    def test_add_layer_checks_combine_override_merge(self, client: _TestingPebbleClient):
        plan = client.get_plan()
        assert isinstance(plan, pebble.Plan)
        assert plan.to_yaml() == '{}\n'
        client.add_layer(
            'foo',
            pebble.Layer("""\
            checks:
                up:
                    level: alive
                    period: 30s
                    threshold: 1
                    exec:
                        command: service nginx status
                        environment:
                            key1: value1
                ready-http:
                    level: ready
                    period: 30s
                    threshold: 1
                    http:
                        url: https://example.com:3100/health
                        headers:
                            header1: value1
                ready-tcp:
                    level: ready
                    period: 30s
                    threshold: 1
                    tcp:
                        port: 8080
                        host: localhost
            """),
        )
        client.add_layer(
            'foo',
            """\
            checks:
                up:
                    level: alive
                    override: merge
                    exec:
                        command: service nginx status 1
                        environment:
                            key2: value2
                ready-http:
                    level: ready
                    override: merge
                    http:
                        headers:
                            header2: value2
                ready-tcp:
                    level: ready
                    override: merge
                    tcp:
                        port: 8082
            """,
            combine=True,
        )
        # Expected changes:
        #  * `key2` should be added to `environment` in `up` check
        #  * `header2` should be added to `headers` in `ready-http` check
        #  * `port` should be changed to 8082 in `ready-tcp` check
        #  * All other properties should remain the same
        plan = client.get_plan()
        assert (
            textwrap.dedent("""\
            checks:
              ready-http:
                http:
                  headers:
                    header1: value1
                    header2: value2
                  url: https://example.com:3100/health
                level: ready
                override: merge
                period: 30s
                threshold: 1
              ready-tcp:
                level: ready
                override: merge
                period: 30s
                tcp:
                  host: localhost
                  port: 8082
                threshold: 1
              up:
                exec:
                  command: service nginx status 1
                  environment:
                    key1: value1
                    key2: value2
                level: alive
                override: merge
                period: 30s
                threshold: 1
            """)
            == plan.to_yaml()
        )

    def test_add_layer_log_targets_combine_override_replace(self, client: _TestingPebbleClient):
        plan = client.get_plan()
        assert isinstance(plan, pebble.Plan)
        assert plan.to_yaml() == '{}\n'
        client.add_layer(
            'foo',
            pebble.Layer("""\
            log-targets:
                baz:
                    override: replace
                    type: loki
                    location: https://example.com:3100/loki/api/v1/push
                    services:
                        - foo
                    labels:
                        key: value
                        key1: value1
            """),
        )
        client.add_layer(
            'foo',
            pebble.Layer("""\
            log-targets:
                baz:
                    override: replace
                    type: loki
                    location: https://example123.com:3100/loki/api/v1/push
                    services:
                        - foo
                    labels:
                        key1: value1
            """),
            combine=True,
        )
        plan = client.get_plan()
        assert (
            textwrap.dedent("""\
            log-targets:
              baz:
                labels:
                  key1: value1
                location: https://example123.com:3100/loki/api/v1/push
                override: replace
                services:
                - foo
                type: loki
            """)
            == plan.to_yaml()
        )

    def test_add_layer_log_targets_combine_override_merge(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            pebble.Layer("""\
            log-targets:
                baz:
                    type: loki
                    location: https://example123.com:3100/loki/api/v1/push
                    services:
                        - foo
                    labels:
                        key1: value1
            """),
        )
        client.add_layer(
            'foo',
            pebble.Layer("""\
            log-targets:
                baz:
                    override: merge
                    services:
                        - foo1
                        - foo2
            """),
            combine=True,
        )
        assert (
            textwrap.dedent("""\
            log-targets:
              baz:
                labels:
                  key1: value1
                location: https://example123.com:3100/loki/api/v1/push
                override: merge
                services:
                - foo
                - foo1
                - foo2
                type: loki
            """)
            == client.get_plan().to_yaml()
        )

    def test_add_layer_not_combined(self, client: _TestingPebbleClient):
        plan = client.get_plan()
        assert isinstance(plan, pebble.Plan)
        assert plan.to_yaml() == '{}\n'
        service = textwrap.dedent("""\
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
            """)
        client.add_layer('foo', pebble.Layer(service))
        # TODO: jam 2021-04-19 We should have a clearer error type for this case. The actual
        #  pebble raises an HTTP exception. See https://github.com/canonical/operator/issues/514
        #  that this should be cleaned up into a clearer error type, however, they should get an
        #  error
        with pytest.raises(RuntimeError):
            client.add_layer('foo', pebble.Layer(service))

    def test_add_layer_three_services(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                override: replace
                command: '/bin/echo foo'
            """,
        )
        client.add_layer(
            'bar',
            """\
            summary: bar
            services:
              bar:
                summary: The Great Bar
                startup: enabled
                override: replace
                command: '/bin/echo bar'
            """,
        )
        client.add_layer(
            'baz',
            """\
            summary: baz
            services:
              baz:
                summary: Not Bar, but Baz
                startup: enabled
                override: replace
                command: '/bin/echo baz'
            """,
        )
        plan = client.get_plan()
        # Alphabetical services, and the YAML should be normalized
        assert (
            textwrap.dedent("""\
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
            """)
            == plan.to_yaml()
        )

    def test_add_layer_combine_no_override(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
            command: '/bin/echo foo'
            """,
        )
        # TODO: jam 2021-04-19 Pebble currently raises a HTTP Error 500 Internal Service Error
        #  if you don't supply an override directive. That needs to be fixed and this test
        #  should be updated. https://github.com/canonical/operator/issues/514
        with pytest.raises(RuntimeError):
            client.add_layer(
                'foo',
                """\
                summary: foo
                services:
                  foo:
                    summary: Foo
                    command: '/bin/echo foo'
                """,
                combine=True,
            )

    def test_add_layer_combine_override_replace(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              bar:
                summary: Bar
                command: '/bin/echo bar'
              foo:
                summary: Foo
                command: '/bin/echo foo'
            """,
        )
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                command: '/bin/echo foo new'
                override: replace
            """,
            combine=True,
        )
        assert (
            textwrap.dedent("""\
            services:
              bar:
                command: /bin/echo bar
                summary: Bar
              foo:
                command: /bin/echo foo new
                override: replace
            """)
            == client.get_plan().to_yaml()
        )

    def test_add_layer_combine_override_merge(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              bar:
                summary: Bar
                command: '/bin/echo bar'
              foo:
                summary: Foo
                command: '/bin/echo foo'
            """,
        )
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                command: '/bin/echo foob'
                override: merge
            """,
            combine=True,
        )
        assert (
            textwrap.dedent("""\
            services:
              bar:
                command: /bin/echo bar
                summary: Bar
              foo:
                command: /bin/echo foob
                override: merge
                summary: Foo
            """)
            == client.get_plan().to_yaml()
        )

    def test_add_layer_combine_override_unknown(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              bar:
                summary: Bar
                command: '/bin/echo bar'
              foo:
                summary: Foo
                command: '/bin/echo foo'
            """,
        )
        with pytest.raises(RuntimeError):
            client.add_layer(
                'foo',
                """\
                summary: foo
                services:
                  foo:
                    summary: Foo
                    command: '/bin/echo foob'
                    override: blah
                """,
                combine=True,
            )

    def test_get_services_none(self, client: _TestingPebbleClient):
        service_info = client.get_services()
        assert service_info == []

    def test_get_services_not_started(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        infos = client.get_services()
        assert len(infos) == 2
        bar_info = infos[0]
        assert bar_info.name == 'bar'
        # Default when not specified is DISABLED
        assert bar_info.startup == pebble.ServiceStartup.DISABLED
        assert bar_info.current == pebble.ServiceStatus.INACTIVE
        assert not bar_info.is_running()
        foo_info = infos[1]
        assert foo_info.name == 'foo'
        assert foo_info.startup == pebble.ServiceStartup.ENABLED
        assert foo_info.current == pebble.ServiceStatus.INACTIVE
        assert not foo_info.is_running()

    def test_get_services_autostart(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        client.autostart_services()
        infos = client.get_services()
        assert len(infos) == 2
        bar_info = infos[0]
        assert bar_info.name == 'bar'
        # Default when not specified is DISABLED
        assert bar_info.startup == pebble.ServiceStartup.DISABLED
        assert bar_info.current == pebble.ServiceStatus.INACTIVE
        assert not bar_info.is_running()
        foo_info = infos[1]
        assert foo_info.name == 'foo'
        assert foo_info.startup == pebble.ServiceStartup.ENABLED
        assert foo_info.current == pebble.ServiceStatus.ACTIVE
        assert foo_info.is_running()

    def test_get_services_start_stop(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        client.start_services(['bar'])
        infos = client.get_services()
        assert len(infos) == 2
        bar_info = infos[0]
        assert bar_info.name == 'bar'
        # Even though bar defaults to DISABLED, we explicitly started it
        assert bar_info.startup == pebble.ServiceStartup.DISABLED
        assert bar_info.current == pebble.ServiceStatus.ACTIVE
        # foo would be started by autostart, but we only called start_services
        foo_info = infos[1]
        assert foo_info.name == 'foo'
        assert foo_info.startup == pebble.ServiceStartup.ENABLED
        assert foo_info.current == pebble.ServiceStatus.INACTIVE
        client.stop_services(['bar'])
        infos = client.get_services()
        bar_info = infos[0]
        assert bar_info.name == 'bar'
        assert bar_info.startup == pebble.ServiceStartup.DISABLED
        assert bar_info.current == pebble.ServiceStatus.INACTIVE

    def test_get_services_bad_request(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        # It is a common mistake to pass just a name vs a list of names, so catch it with a
        # TypeError
        with pytest.raises(TypeError):
            client.get_services('foo')

    def test_get_services_subset(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        infos = client.get_services(['foo'])
        assert len(infos) == 1
        foo_info = infos[0]
        assert foo_info.name == 'foo'
        assert foo_info.startup == pebble.ServiceStartup.ENABLED
        assert foo_info.current == pebble.ServiceStatus.INACTIVE

    def test_get_services_unknown(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        # This doesn't seem to be an error at the moment.
        # pebble_cli.py service just returns an empty list
        # pebble service unknown says "No matching services" (but exits 0)
        infos = client.get_services(['unknown'])
        assert infos == []

    def test_invalid_start_service(self, client: _TestingPebbleClient):
        # TODO: jam 2021-04-20 This should become a better error
        with pytest.raises(RuntimeError):
            client.start_services(['unknown'])

    def test_start_service_str(self, client: _TestingPebbleClient):
        # Start service takes a list of names, but it is really easy to accidentally pass just a
        # name
        with pytest.raises(TypeError):
            client.start_services('unknown')

    def test_stop_service_str(self, client: _TestingPebbleClient):
        # Start service takes a list of names, but it is really easy to accidentally pass just a
        # name
        with pytest.raises(TypeError):
            client.stop_services('unknown')

    def test_mixed_start_service(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
            """,
        )
        # TODO: jam 2021-04-20 better error type
        with pytest.raises(RuntimeError):
            client.start_services(['foo', 'unknown'])
        # foo should not be started
        infos = client.get_services()
        assert len(infos) == 1
        foo_info = infos[0]
        assert foo_info.name == 'foo'
        assert foo_info.startup == pebble.ServiceStartup.ENABLED
        assert foo_info.current == pebble.ServiceStatus.INACTIVE

    def test_stop_services_unknown(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
            """,
        )
        client.autostart_services()
        # TODO: jam 2021-04-20 better error type
        with pytest.raises(RuntimeError):
            client.stop_services(['foo', 'unknown'])
        # foo should still be running
        infos = client.get_services()
        assert len(infos) == 1
        foo_info = infos[0]
        assert foo_info.name == 'foo'
        assert foo_info.startup == pebble.ServiceStartup.ENABLED
        assert foo_info.current == pebble.ServiceStatus.ACTIVE

    def test_start_started_service(self, client: _TestingPebbleClient):
        # Pebble maintains idempotency even if you start a service
        # which is already started.
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        client.autostart_services()
        # Foo is now started, but Bar is not
        client.start_services(['bar', 'foo'])
        # foo and bar are both started
        infos = client.get_services()
        assert len(infos) == 2
        bar_info = infos[0]
        assert bar_info.name == 'bar'
        # Default when not specified is DISABLED
        assert bar_info.startup == pebble.ServiceStartup.DISABLED
        assert bar_info.current == pebble.ServiceStatus.ACTIVE
        foo_info = infos[1]
        assert foo_info.name == 'foo'
        assert foo_info.startup == pebble.ServiceStartup.ENABLED
        assert foo_info.current == pebble.ServiceStatus.ACTIVE

    def test_stop_stopped_service(self, client: _TestingPebbleClient):
        # Pebble maintains idempotency even if you stop a service
        # which is already stopped.
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        client.autostart_services()
        # Foo is now started, but Bar is not
        client.stop_services(['foo', 'bar'])
        # foo and bar are both stopped
        infos = client.get_services()
        assert len(infos) == 2
        bar_info = infos[0]
        assert bar_info.name == 'bar'
        # Default when not specified is DISABLED
        assert bar_info.startup == pebble.ServiceStartup.DISABLED
        assert bar_info.current == pebble.ServiceStatus.INACTIVE
        foo_info = infos[1]
        assert foo_info.name == 'foo'
        assert foo_info.startup == pebble.ServiceStartup.ENABLED
        assert foo_info.current == pebble.ServiceStatus.INACTIVE

    @unittest.skipUnless(is_linux, 'Pebble runs on Linux')
    def test_send_signal(self, client: _TestingPebbleClient):
        client.add_layer(
            'foo',
            """\
            summary: foo
            services:
              foo:
                summary: Foo
                startup: enabled
                command: '/bin/echo foo'
              bar:
                summary: Bar
                command: '/bin/echo bar'
            """,
        )
        client.autostart_services()
        # Foo is now started, but Bar is not

        # Send a valid signal to a running service
        client.send_signal('SIGINT', ('foo',))

        # Send a valid signal but omit service name
        with pytest.raises(TypeError):
            client.send_signal('SIGINT', tuple())

        # Send an invalid signal to a running service
        with pytest.raises(pebble.APIError):
            client.send_signal('sigint', ('foo',))

        # Send a valid signal to a stopped service
        with pytest.raises(pebble.APIError):
            client.send_signal('SIGINT', ('bar',))

        # Send a valid signal to a non-existing service
        with pytest.raises(pebble.APIError):
            client.send_signal('SIGINT', ('baz',))

        # Send a valid signal to a multiple services, one of which is not running
        with pytest.raises(pebble.APIError):
            client.send_signal(
                'SIGINT',
                (
                    'foo',
                    'bar',
                ),
            )


PebbleClientType = typing.Union[_TestingPebbleClient, pebble.Client]


# For testing file-ops of the pebble client.  This is refactored into a
# separate mixin so we can run these tests against both the mock client as
# well as a real pebble server instance.
class PebbleStorageAPIsTestMixin:
    def test_push_and_pull_bytes(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        self._test_push_and_pull_data(
            pebble_dir,
            client,
            original_data=b'\x00\x01\x02\x03\x04',
            encoding=None,
            stream_class=io.BytesIO,
        )

    def test_push_and_pull_non_utf8_data(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        self._test_push_and_pull_data(
            pebble_dir,
            client,
            original_data='日本語',  # "Japanese" in Japanese
            encoding='sjis',
            stream_class=io.StringIO,
        )

    def _test_push_and_pull_data(
        self,
        pebble_dir: str,
        client: PebbleClientType,
        original_data: typing.Union[str, bytes],
        encoding: typing.Optional[str],
        stream_class: typing.Union[typing.Type[io.BytesIO], typing.Type[io.StringIO]],
    ):
        # We separate out the calls to make it clearer to type checkers what's happening.
        if encoding is None:
            client.push(f'{pebble_dir}/test', original_data)
        else:
            client.push(f'{pebble_dir}/test', original_data, encoding=encoding)
        with client.pull(f'{pebble_dir}/test', encoding=encoding) as infile:
            received_data = infile.read()
        assert original_data == received_data

        # We also support file-like objects as input, so let's test that case as well.
        if encoding is None:
            stream_class = typing.cast(typing.Type[io.BytesIO], stream_class)
            small_file = stream_class(typing.cast(bytes, original_data))
            client.push(f'{pebble_dir}/test', small_file)
        else:
            stream_class = typing.cast(typing.Type[io.StringIO], stream_class)
            small_file = stream_class(typing.cast(str, original_data))
            client.push(f'{pebble_dir}/test', small_file, encoding=encoding)
        with client.pull(f'{pebble_dir}/test', encoding=encoding) as infile:
            received_data = infile.read()
        assert original_data == received_data

    def test_push_bytes_ignore_encoding(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        # push() encoding param should be ignored if source is bytes
        client.push(f'{pebble_dir}/test', b'\x00\x01', encoding='utf-8')
        with client.pull(f'{pebble_dir}/test', encoding=None) as infile:
            received_data = infile.read()
        assert received_data == b'\x00\x01'

    def test_push_bytesio_ignore_encoding(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        # push() encoding param should be ignored if source is binary stream
        client.push(f'{pebble_dir}/test', io.BytesIO(b'\x00\x01'), encoding='utf-8')
        with client.pull(f'{pebble_dir}/test', encoding=None) as infile:
            received_data = infile.read()
        assert received_data == b'\x00\x01'

    def test_push_and_pull_larger_file(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        # Intent: to ensure things work appropriately with larger files.
        # Larger files may be sent/received in multiple chunks; this should help for
        # checking that such logic is correct.
        data_size = 1024 * 1024
        original_data = os.urandom(data_size)

        client.push(f'{pebble_dir}/test', original_data)
        with client.pull(f'{pebble_dir}/test', encoding=None) as infile:
            received_data = infile.read()
        assert original_data == received_data

    def test_push_to_non_existent_subdir(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        data = 'data'

        with pytest.raises(pebble.PathError) as excinfo:
            client.push(f'{pebble_dir}/nonexistent_dir/test', data, make_dirs=False)
        assert excinfo.value.kind == 'not-found'

        client.push(f'{pebble_dir}/nonexistent_dir/test', data, make_dirs=True)

    def test_push_as_child_of_file_raises_error(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        data = 'data'
        client.push(f'{pebble_dir}/file', data)
        with pytest.raises(pebble.PathError) as excinfo:
            client.push(f'{pebble_dir}/file/file', data)
        assert excinfo.value.kind == 'generic-file-error'

    def test_push_with_permission_mask(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        data = 'data'
        client.push(f'{pebble_dir}/file', data, permissions=0o600)
        client.push(f'{pebble_dir}/file', data, permissions=0o777)
        # If permissions are outside of the range 0o000 through 0o777, an exception should be
        # raised.
        for bad_permission in (
            0o1000,  # Exceeds 0o777
            -1,  # Less than 0o000
        ):
            with pytest.raises(pebble.PathError) as excinfo:
                client.push(f'{pebble_dir}/file', data, permissions=bad_permission)
            assert excinfo.value.kind == 'generic-file-error'

    def test_push_files_and_list(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        data = 'data'

        # Let's push the first file with a bunch of details.  We'll check on this later.
        client.push(f'{pebble_dir}/file1', data, permissions=0o620)

        # Do a quick push with defaults for the other files.
        client.push(f'{pebble_dir}/file2', data)
        client.push(f'{pebble_dir}/file3', data)

        files = client.list_files(f'{pebble_dir}/')
        assert {file.path for file in files} == {
            pebble_dir + file for file in ('/file1', '/file2', '/file3')
        }

        # Let's pull the first file again and check its details
        file = [f for f in files if f.path == f'{pebble_dir}/file1'][0]
        assert file.name == 'file1'
        assert file.type == pebble.FileType.FILE
        assert file.size == 4
        assert isinstance(file.last_modified, datetime.datetime)
        assert file.permissions == 0o620
        # Skipping ownership checks here; ownership will be checked in purely-mocked tests

    def test_push_and_list_file(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        data = 'data'
        client.push(f'{pebble_dir}/file', data)
        files = client.list_files(f'{pebble_dir}/')
        assert {file.path for file in files} == {f'{pebble_dir}/file'}

    def test_push_file_with_relative_path_fails(
        self,
        client: PebbleClientType,
    ):
        with pytest.raises(pebble.PathError) as excinfo:
            client.push('file', '')
        assert excinfo.value.kind == 'generic-file-error'

    def test_pull_not_found(
        self,
        client: PebbleClientType,
    ):
        with pytest.raises(pebble.PathError) as excinfo:
            client.pull('/not/found')
        assert excinfo.value.kind == 'not-found'
        assert '/not/found' in excinfo.value.message

    def test_pull_directory(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        client.make_dir(f'{pebble_dir}/subdir')
        with pytest.raises(pebble.PathError) as excinfo:
            client.pull(f'{pebble_dir}/subdir')
        assert excinfo.value.kind == 'generic-file-error'
        assert f'{pebble_dir}/subdir' in excinfo.value.message

    def test_list_files_not_found_raises(
        self,
        client: PebbleClientType,
    ):
        with pytest.raises(pebble.APIError) as excinfo:
            client.list_files('/not/existing/file/')
        assert excinfo.value.code == 404
        assert excinfo.value.status == 'Not Found'
        assert excinfo.value.message == 'stat /not/existing/file/: no ' 'such file or directory'

    def test_list_directory_object_itself(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        # Test with root dir
        # (Special case; we won't prefix this, even when using the real Pebble server.)
        files = client.list_files('/', itself=True)
        assert len(files) == 1
        dir_ = files[0]
        assert dir_.path == '/'
        assert dir_.name == '/'
        assert dir_.type == pebble.FileType.DIRECTORY

        # Test with subdirs
        client.make_dir(f'{pebble_dir}/subdir')
        files = client.list_files(f'{pebble_dir}/subdir', itself=True)
        assert len(files) == 1
        dir_ = files[0]
        assert dir_.name == 'subdir'
        assert dir_.type == pebble.FileType.DIRECTORY

    def test_push_files_and_list_by_pattern(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        # Note: glob pattern deltas do exist between golang and Python, but here,
        # we'll just use a simple * pattern.
        data = 'data'
        for filename in (
            '/file1.gz',
            '/file2.tar.gz',
            '/file3.tar.bz2',
            '/backup_file.gz',
        ):
            client.push(pebble_dir + filename, data)
        files = client.list_files(f'{pebble_dir}/', pattern='file*.gz')
        assert {file.path for file in files} == {
            pebble_dir + file for file in ('/file1.gz', '/file2.tar.gz')
        }

    def test_make_directory(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        client.make_dir(f'{pebble_dir}/subdir')
        assert (
            client.list_files(f'{pebble_dir}/', pattern='subdir')[0].path == f'{pebble_dir}/subdir'
        )
        client.make_dir(f'{pebble_dir}/subdir/subdir')
        assert (
            client.list_files(f'{pebble_dir}/subdir', pattern='subdir')[0].path
            == f'{pebble_dir}/subdir/subdir'
        )

    def test_make_directory_recursively(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        with pytest.raises(pebble.PathError) as excinfo:
            client.make_dir(f'{pebble_dir}/subdir/subdir', make_parents=False)
        assert excinfo.value.kind == 'not-found'

        client.make_dir(f'{pebble_dir}/subdir/subdir', make_parents=True)
        assert (
            client.list_files(f'{pebble_dir}/subdir', pattern='subdir')[0].path
            == f'{pebble_dir}/subdir/subdir'
        )

    def test_make_directory_with_relative_path_fails(
        self,
        client: PebbleClientType,
    ):
        with pytest.raises(pebble.PathError) as excinfo:
            client.make_dir('dir')
        assert excinfo.value.kind == 'generic-file-error'

    def test_make_subdir_of_file_fails(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        client.push(f'{pebble_dir}/file', 'data')

        # Direct child case
        with pytest.raises(pebble.PathError) as excinfo:
            client.make_dir(f'{pebble_dir}/file/subdir')
        assert excinfo.value.kind == 'generic-file-error'

        # Recursive creation case, in case its flow is different
        with pytest.raises(pebble.PathError) as excinfo:
            client.make_dir(f'{pebble_dir}/file/subdir/subdir', make_parents=True)
        assert excinfo.value.kind == 'generic-file-error'

    def test_make_dir_with_permission_mask(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        client.make_dir(f'{pebble_dir}/dir1', permissions=0o700)
        client.make_dir(f'{pebble_dir}/dir2', permissions=0o777)

        files = client.list_files(f'{pebble_dir}/', pattern='dir*')
        assert [f for f in files if f.path == f'{pebble_dir}/dir1'][0].permissions == 0o700
        assert [f for f in files if f.path == f'{pebble_dir}/dir2'][0].permissions == 0o777

        # If permissions are outside of the range 0o000 through 0o777, an exception should be
        # raised.
        for i, bad_permission in enumerate((
            0o1000,  # Exceeds 0o777
            -1,  # Less than 0o000
        )):
            with pytest.raises(pebble.PathError) as excinfo:
                client.make_dir(f'{pebble_dir}/dir3_{i}', permissions=bad_permission)
            assert excinfo.value.kind == 'generic-file-error'

    def test_remove_path(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        client.push(f'{pebble_dir}/file', '')
        client.make_dir(f'{pebble_dir}/dir/subdir', make_parents=True)
        client.push(f'{pebble_dir}/dir/subdir/file1', '')
        client.push(f'{pebble_dir}/dir/subdir/file2', '')
        client.push(f'{pebble_dir}/dir/subdir/file3', '')
        client.make_dir(f'{pebble_dir}/empty_dir')

        client.remove_path(f'{pebble_dir}/file')

        client.remove_path(f'{pebble_dir}/empty_dir')

        # Remove non-empty directory, recursive=False: error
        with pytest.raises(pebble.PathError) as excinfo:
            client.remove_path(f'{pebble_dir}/dir', recursive=False)
        assert excinfo.value.kind == 'generic-file-error'

        # Remove non-empty directory, recursive=True: succeeds (and removes child objects)
        client.remove_path(f'{pebble_dir}/dir', recursive=True)

        # Remove non-existent path, recursive=False: error
        with pytest.raises(pebble.PathError) as excinfo:
            client.remove_path(f'{pebble_dir}/dir/does/not/exist/asdf', recursive=False)
        assert excinfo.value.kind == 'not-found'

        # Remove non-existent path, recursive=True: succeeds
        client.remove_path(f'{pebble_dir}/dir/does/not/exist/asdf', recursive=True)

    # Other notes:
    # * Parent directories created via push(make_dirs=True) default to root:root ownership
    #   and whatever permissions are specified via the permissions argument; as we default to None
    #   for ownership/permissions, we do ignore this nuance.
    # * Parent directories created via make_dir(make_parents=True) default to root:root ownership
    #   and 0o755 permissions; as we default to None for ownership/permissions, we do ignore this
    #   nuance.


class _MakedirArgs(typing.TypedDict):
    user_id: typing.Optional[int]
    user: typing.Optional[str]
    group_id: typing.Optional[int]
    group: typing.Optional[str]


class TestPebbleStorageAPIsUsingMocks(PebbleStorageAPIsTestMixin):
    @pytest.fixture
    def client(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              mycontainer: {}
            """,
        )
        backend = harness._backend
        client = backend.get_pebble('/charm/containers/mycontainer/pebble.socket')
        harness.set_can_connect('mycontainer', True)
        yield client
        harness.cleanup()

    @pytest.fixture
    def pebble_dir(self, client: PebbleClientType):
        pebble_dir = '/prefix'
        client.make_dir(pebble_dir, make_parents=True)
        return pebble_dir

    def test_container_storage_mounts(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
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
            """,
        )
        request.addfinalizer(harness.cleanup)

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
        assert c1.exists(c1_fpath)
        fpath = os.path.join(str(harness.model.storages['store1'][0].location), 'foo.txt')
        with open(fpath) as f:
            assert f.read() == '42'

        # check that the file is not visible in c2 which has a different storage mount
        c2 = harness.model.unit.get_container('c2')
        c2_fpath = os.path.join('/mounts/foo', c1_fname)
        assert not c2.exists(c2_fpath)

        # check that the file is visible in c3 which has the same storage mount
        c3 = harness.model.unit.get_container('c3')
        c3_fpath = os.path.join('/mounts/bar', c1_fname)
        assert c3.exists(c3_fpath)
        with c3.pull(c3_fpath) as f:
            assert f.read() == '42'

        # test all other container file ops
        with c1.pull(c1_fpath) as f:
            assert f.read() == '42'
        files = c1.list_files(c1_fpath)
        assert [c1_fpath] == [fi.path for fi in files]
        c1.remove_path(c1_fpath)
        assert not c1.exists(c1_fpath)

        # test detaching storage
        c1.push(c1_fpath, '42')
        assert c1.exists(c1_fpath)
        store1_id = harness.model.storages['store1'][0].full_id
        harness.remove_storage(store1_id)
        assert not c1.exists(c1_fpath)

    def _select_testing_user_group(self):
        user = [u for u in pwd.getpwall() if u.pw_uid != os.getuid()][0]
        group = [g for g in grp.getgrall() if g.gr_gid != os.getgid()][0]
        return user, group

    def test_push_with_ownership(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        data = 'data'
        user, group = self._select_testing_user_group()
        cases: typing.List[_MakedirArgs] = [
            {'user_id': user.pw_uid, 'user': None, 'group_id': group.gr_gid, 'group': None},
            {'user_id': None, 'user': user.pw_name, 'group_id': None, 'group': group.gr_name},
            {'user_id': None, 'user': user.pw_name, 'group_id': group.gr_gid, 'group': None},
            {'user_id': user.pw_uid, 'user': None, 'group_id': None, 'group': group.gr_name},
            {
                'user_id': user.pw_uid,
                'user': user.pw_name,
                'group_id': group.gr_gid,
                'group': group.gr_name,
            },
        ]
        for idx, case in enumerate(cases):
            client.push(f'{pebble_dir}/file{idx}', data, **case)
            file_ = client.list_files(f'{pebble_dir}/file{idx}')[0]
            assert file_.path == f'{pebble_dir}/file{idx}'

    def test_make_dir_with_ownership(
        self,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        user, group = self._select_testing_user_group()
        cases: typing.List[_MakedirArgs] = [
            {'user_id': user.pw_uid, 'user': None, 'group_id': group.gr_gid, 'group': None},
            {'user_id': None, 'user': user.pw_name, 'group_id': None, 'group': group.gr_name},
            {'user_id': None, 'user': user.pw_name, 'group_id': group.gr_gid, 'group': None},
            {'user_id': user.pw_uid, 'user': None, 'group_id': None, 'group': group.gr_name},
            {
                'user_id': user.pw_uid,
                'user': user.pw_name,
                'group_id': group.gr_gid,
                'group': group.gr_name,
            },
        ]
        for idx, case in enumerate(cases):
            client.make_dir(f'{pebble_dir}/dir{idx}', **case)
            dir_ = client.list_files(f'{pebble_dir}/dir{idx}', itself=True)[0]
            assert dir_.path == f'{pebble_dir}/dir{idx}'

    @patch('grp.getgrgid')
    @patch('pwd.getpwuid')
    def test_list_files_unnamed(
        self,
        getpwuid: MagicMock,
        getgrgid: MagicMock,
        pebble_dir: str,
        client: PebbleClientType,
    ):
        getpwuid.side_effect = KeyError
        getgrgid.side_effect = KeyError
        data = 'data'
        client.push(f'{pebble_dir}/file', data)
        files = client.list_files(f'{pebble_dir}/')
        assert len(files) == 1
        assert files[0].user is None
        assert files[0].group is None


class TestFilesystem:
    @pytest.fixture
    def harness(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test
            containers:
                test-container:
                    mounts:
                        - storage: test-storage
                          location: /mounts/foo
            storage:
                test-storage:
                    type: filesystem
            """,
        )
        harness.begin()
        harness.set_can_connect('test-container', True)
        yield harness
        harness.cleanup()

    @pytest.fixture
    def container_fs_root(self, harness: ops.testing.Harness[ops.CharmBase]):
        return harness.get_filesystem_root('test-container')

    @pytest.fixture
    def container(self, harness: ops.testing.Harness[ops.CharmBase]):
        return harness.charm.unit.get_container('test-container')

    def test_push(self, container: ops.Container, container_fs_root: pathlib.Path):
        container.push('/foo', source='foo')
        assert (container_fs_root / 'foo').is_file()
        assert (container_fs_root / 'foo').read_text() == 'foo'

    def test_push_create_parent(self, container: ops.Container, container_fs_root: pathlib.Path):
        container.push('/foo/bar', source='bar', make_dirs=True)
        assert (container_fs_root / 'foo').is_dir()
        assert (container_fs_root / 'foo' / 'bar').read_text() == 'bar'

    def test_push_path(self, container: ops.Container, container_fs_root: pathlib.Path):
        with tempfile.TemporaryDirectory() as temp:
            tempdir = pathlib.Path(temp)
            (tempdir / 'foo/bar').mkdir(parents=True)
            (tempdir / 'foo/test').write_text('test')
            (tempdir / 'foo/bar/foobar').write_text('foobar')
            (tempdir / 'foo/baz').mkdir(parents=True)
            container.push_path(tempdir / 'foo', '/tmp')  # noqa: S108

            assert (container_fs_root / 'tmp').is_dir()
            assert (container_fs_root / 'tmp/foo').is_dir()
            assert (container_fs_root / 'tmp/foo/bar').is_dir()
            assert (container_fs_root / 'tmp/foo/baz').is_dir()
            assert (container_fs_root / 'tmp/foo/test').read_text() == 'test'
            assert (container_fs_root / 'tmp/foo/bar/foobar').read_text() == 'foobar'

    def test_make_dir(self, container: ops.Container, container_fs_root: pathlib.Path):
        container.make_dir('/tmp')  # noqa: S108
        assert (container_fs_root / 'tmp').is_dir()
        container.make_dir('/foo/bar/foobar', make_parents=True)
        assert (container_fs_root / 'foo/bar/foobar').is_dir()

    def test_pull(self, container: ops.Container, container_fs_root: pathlib.Path):
        (container_fs_root / 'foo').write_text('foo')
        assert container.pull('/foo').read() == 'foo'

    def test_pull_path(self, container: ops.Container, container_fs_root: pathlib.Path):
        (container_fs_root / 'foo').mkdir()
        (container_fs_root / 'foo/bar').write_text('bar')
        (container_fs_root / 'foobar').mkdir()
        (container_fs_root / 'test').write_text('test')
        with tempfile.TemporaryDirectory() as temp:
            tempdir = pathlib.Path(temp)
            container.pull_path('/', tempdir)
            assert (tempdir / 'foo').is_dir()
            assert (tempdir / 'foo/bar').read_text() == 'bar'
            assert (tempdir / 'foobar').is_dir()
            assert (tempdir / 'test').read_text() == 'test'

    def test_list_files(self, container: ops.Container, container_fs_root: pathlib.Path):
        (container_fs_root / 'foo').mkdir()
        assert container.list_files('/foo') == []
        assert len(container.list_files('/')) == 1
        file_info = container.list_files('/')[0]
        assert file_info.path == '/foo'
        assert file_info.type == FileType.DIRECTORY
        assert container.list_files('/foo', itself=True)[0].path == '/foo'
        (container_fs_root / 'foo/bar').write_text('foobar')
        assert len(container.list_files('/foo')) == 1
        assert len(container.list_files('/foo', pattern='*ar')) == 1
        assert len(container.list_files('/foo', pattern='*oo')) == 0
        file_info = container.list_files('/foo')[0]
        assert file_info.path == '/foo/bar'
        assert file_info.type == FileType.FILE
        root_info = container.list_files('/', itself=True)[0]
        assert root_info.path == '/'
        assert root_info.name == '/'

    def test_storage_mount(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
        container_fs_root: pathlib.Path,
    ):
        storage_id = harness.add_storage('test-storage', 1, attach=True)[0]
        assert (container_fs_root / 'mounts/foo').exists()
        (container_fs_root / 'mounts/foo/bar').write_text('foobar')
        assert container.pull('/mounts/foo/bar').read() == 'foobar'
        harness.detach_storage(storage_id)
        assert not (container_fs_root / 'mounts/foo/bar').is_file()
        harness.attach_storage(storage_id)
        assert (container_fs_root / 'mounts/foo/bar').read_text(), 'foobar'

    def _make_storage_attach_harness(
        self,
        request: pytest.FixtureRequest,
        meta: typing.Optional[str] = None,
    ):
        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.attached: typing.List[str] = []
                self.locations: typing.List[pathlib.Path] = []
                framework.observe(self.on['test-storage'].storage_attached, self._on_attach)

            def _on_attach(self, event: ops.StorageAttachedEvent):
                self.attached.append(event.storage.full_id)
                self.locations.append(event.storage.location)

        if meta is None:
            meta = """
                name: test
                containers:
                    test-container:
                        mounts:
                            - storage: test-storage
                              location: /mounts/foo
                storage:
                    test-storage:
                        type: filesystem
                """
        harness = ops.testing.Harness(MyCharm, meta=meta)
        request.addfinalizer(harness.cleanup)
        return harness

    def test_storage_attach_begin_no_emit(self, request: pytest.FixtureRequest):
        """If `begin()` hasn't been called, `attach` does not emit storage-attached."""
        harness = self._make_storage_attach_harness(request)
        harness.add_storage('test-storage', attach=True)
        harness.begin()
        assert 'test-storage/0' not in harness.charm.attached

    def test_storage_attach_begin_with_hooks_emits(self, request: pytest.FixtureRequest):
        """`attach` doesn't emit storage-attached before `begin_with_initial_hooks`."""
        harness = self._make_storage_attach_harness(request)
        harness.add_storage('test-storage', attach=True)
        harness.begin_with_initial_hooks()
        assert 'test-storage/0' in harness.charm.attached
        assert harness.charm.locations[0]

    def test_storage_add_with_later_attach(self, request: pytest.FixtureRequest):
        harness = self._make_storage_attach_harness(request)
        harness.begin()
        storage_ids = harness.add_storage('test-storage', attach=False)
        assert 'test-storage/0' not in harness.charm.attached
        for s_id in storage_ids:
            harness.attach_storage(s_id)
            # It's safe to call `attach_storage` more than once, and this will
            # only trigger the event once - this is the same as executing
            # `juju attach-storage <unit> <storage>` more than once.
            harness.attach_storage(s_id)
        assert harness.charm.attached.count('test-storage/0') == 1

    def test_storage_machine_charm_metadata(self, request: pytest.FixtureRequest):
        meta = """
            name: test
            storage:
                test-storage:
                    type: filesystem
                    mount: /mounts/foo
            """
        harness = self._make_storage_attach_harness(request, meta)
        harness.begin()
        harness.add_storage('test-storage', attach=True)
        assert 'test-storage/0' in harness.charm.attached

    def test_storage_multiple_storage_instances(self, request: pytest.FixtureRequest):
        meta = """
            name: test
            storage:
                test-storage:
                    type: filesystem
                    mount: /mounts/foo
                    multiple:
                        range: 2-4
            """
        harness = self._make_storage_attach_harness(request, meta)
        harness.begin()
        harness.add_storage('test-storage', 2, attach=True)
        assert harness.charm.attached == ['test-storage/0', 'test-storage/1']
        assert harness.charm.locations[0] != harness.charm.locations[1]
        harness.add_storage('test-storage', 2, attach=True)
        assert harness.charm.attached == [
            'test-storage/0',
            'test-storage/1',
            'test-storage/2',
            'test-storage/3',
        ]
        assert len(set(harness.charm.locations)) == 4


class TestSecrets:
    def test_add_model_secret_by_app_name_str(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({'name': 'webapp', 'requires': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        assert secret.id == secret_id
        assert secret.get_content() == {'password': 'hunter2'}

    def test_add_model_secret_by_app_instance(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({'name': 'webapp', 'requires': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        app = harness.model.get_app('database')
        secret_id = harness.add_model_secret(app, {'password': 'hunter3'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        assert secret.id == secret_id
        assert secret.get_content() == {'password': 'hunter3'}

    def test_add_model_secret_by_unit_instance(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({'name': 'webapp', 'requires': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        unit = harness.model.get_unit('database/0')
        secret_id = harness.add_model_secret(unit, {'password': 'hunter4'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        assert secret.id == secret_id
        assert secret.get_content() == {'password': 'hunter4'}

    def test_get_secret_as_owner(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({'name': 'webapp', 'requires': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        # App secret.
        secret_id = harness.charm.app.add_secret({'password': 'hunter5'}).id
        secret = harness.model.get_secret(id=secret_id)
        assert secret.id == secret_id
        assert secret.get_content() == {'password': 'hunter5'}
        # Unit secret.
        secret_id = harness.charm.unit.add_secret({'password': 'hunter6'}).id
        secret = harness.model.get_secret(id=secret_id)
        assert secret.id == secret_id
        assert secret.get_content() == {'password': 'hunter6'}

    def test_get_secret_and_refresh(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_leader(True)
        secret = harness.charm.app.add_secret({'password': 'hunter6'})
        secret.set_content({'password': 'hunter7'})
        retrieved_secret = harness.model.get_secret(id=secret.id)
        assert retrieved_secret.id == secret.id
        assert retrieved_secret.get_content() == {'password': 'hunter6'}
        assert retrieved_secret.peek_content() == {'password': 'hunter7'}
        assert retrieved_secret.get_content(refresh=True) == {'password': 'hunter7'}
        assert retrieved_secret.get_content() == {'password': 'hunter7'}

    def test_get_secret_removed(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.set_leader(True)
        secret = harness.charm.app.add_secret({'password': 'hunter8'})
        secret.set_content({'password': 'hunter9'})
        secret.remove_revision(secret.get_info().revision)
        with pytest.raises(ops.SecretNotFoundError):
            harness.model.get_secret(id=secret.id)

    def test_get_secret_by_label(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)
        harness.begin()
        secret_id = harness.charm.app.add_secret({'password': 'hunter9'}, label='my-pass').id
        secret = harness.model.get_secret(label='my-pass')
        assert secret.label == 'my-pass'
        assert secret.get_content() == {'password': 'hunter9'}
        secret = harness.model.get_secret(id=secret_id, label='other-name')
        assert secret.get_content() == {'password': 'hunter9'}
        secret = harness.model.get_secret(label='other-name')
        assert secret.get_content() == {'password': 'hunter9'}

    def test_add_model_secret_invalid_content(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)

        with pytest.raises(ValueError):
            harness.add_model_secret('database', {'x': 'y'})  # key too short

    def test_set_secret_content(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            EventRecorder,
            meta=yaml.safe_dump({'name': 'webapp', 'requires': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'foo': '1'})
        harness.grant_secret(secret_id, 'webapp')
        harness.begin()
        harness.framework.observe(harness.charm.on.secret_changed, harness.charm.record_event)
        harness.set_secret_content(secret_id, {'foo': '2'})

        assert len(harness.charm.events) == 1
        event = harness.charm.events[0]
        # Not assertIsInstance to help type checkers.
        assert isinstance(event, ops.SecretChangedEvent)
        assert event.secret.get_content() == {'foo': '1'}
        assert event.secret.get_content(refresh=True) == {'foo': '2'}
        assert event.secret.get_content() == {'foo': '2'}

        assert harness.get_secret_revisions(secret_id) == [1, 2]

    def test_set_secret_content_wrong_owner(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)

        secret = harness.model.app.add_secret({'foo': 'bar'})
        with pytest.raises(RuntimeError):
            assert secret.id is not None
            harness.set_secret_content(secret.id, {'bar': 'foo'})

    def test_set_secret_content_invalid_secret_id(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)

        with pytest.raises(RuntimeError):
            harness.set_secret_content('asdf', {'foo': 'bar'})

    def test_set_secret_content_invalid_content(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)

        secret_id = harness.add_model_secret('database', {'foo': 'bar'})
        with pytest.raises(ValueError):
            harness.set_secret_content(secret_id, {'x': 'y'})

    def test_grant_secret_and_revoke_secret(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({'name': 'webapp', 'requires': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        assert secret.id == secret_id
        assert secret.get_content() == {'password': 'hunter2'}

        harness.revoke_secret(secret_id, 'webapp')
        with pytest.raises(ops.SecretNotFoundError):
            harness.model.get_secret(id=secret_id)

    def test_grant_secret_wrong_app(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({'name': 'webapp', 'requires': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        harness.grant_secret(secret_id, 'otherapp')
        with pytest.raises(ops.SecretNotFoundError):
            harness.model.get_secret(id=secret_id)

    def test_grant_secret_wrong_unit(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({'name': 'webapp', 'requires': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)
        relation_id = harness.add_relation('db', 'database')
        harness.add_relation_unit(relation_id, 'database/0')

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        harness.grant_secret(secret_id, 'webapp/1')  # should be webapp/0
        with pytest.raises(ops.SecretNotFoundError):
            harness.model.get_secret(id=secret_id)

    def test_grant_secret_no_relation(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)

        secret_id = harness.add_model_secret('database', {'password': 'hunter2'})
        with pytest.raises(RuntimeError):
            harness.grant_secret(secret_id, 'webapp')

    def test_get_secret_grants(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta=yaml.safe_dump({'name': 'database', 'provides': {'db': {'interface': 'pgsql'}}}),
        )
        request.addfinalizer(harness.cleanup)

        relation_id = harness.add_relation('db', 'webapp')
        harness.add_relation_unit(relation_id, 'webapp/0')
        assert harness is not None

        harness.set_leader(True)
        secret = harness.model.app.add_secret({'foo': 'x'})
        assert secret.id is not None
        assert harness.get_secret_grants(secret.id, relation_id) == set()
        rel = harness.model.get_relation('db')
        assert rel is not None
        secret.grant(rel)
        assert harness.get_secret_grants(secret.id, relation_id) == {'webapp'}

        secret.revoke(rel)
        assert harness.get_secret_grants(secret.id, relation_id) == set()
        secret.grant(rel, unit=harness.model.get_unit('webapp/0'))
        assert harness.get_secret_grants(secret.id, relation_id) == {'webapp/0'}

    def test_trigger_secret_rotation(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(EventRecorder, meta='name: database')
        request.addfinalizer(harness.cleanup)

        secret = harness.model.app.add_secret({'foo': 'x'}, label='lbl')
        assert secret.id is not None
        harness.begin()
        harness.framework.observe(harness.charm.on.secret_rotate, harness.charm.record_event)
        harness.trigger_secret_rotation(secret.id)
        harness.trigger_secret_rotation(secret.id, label='override')

        assert len(harness.charm.events) == 2
        event = harness.charm.events[0]
        # Not assertIsInstance to help type checkers.
        assert isinstance(event, ops.SecretRotateEvent)
        assert event.secret.label == 'lbl'
        assert event.secret.get_content() == {'foo': 'x'}
        event = harness.charm.events[1]
        # Not assertIsInstance to help type checkers.
        assert isinstance(event, ops.SecretRotateEvent)
        assert event.secret.label == 'override'
        assert event.secret.get_content() == {'foo': 'x'}

        with pytest.raises(RuntimeError):
            harness.trigger_secret_rotation('nosecret')

    def test_trigger_secret_rotation_on_user_secret(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(EventRecorder, meta='name: database')
        request.addfinalizer(harness.cleanup)

        secret_id = harness.add_user_secret({'foo': 'bar'})
        assert secret_id is not None
        harness.begin()

        with pytest.raises(RuntimeError):
            harness.trigger_secret_rotation(secret_id)

    def test_trigger_secret_removal(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(EventRecorder, meta='name: database')
        request.addfinalizer(harness.cleanup)

        secret = harness.model.app.add_secret({'foo': 'x'}, label='lbl')
        assert secret.id is not None
        harness.begin()
        harness.framework.observe(harness.charm.on.secret_remove, harness.charm.record_event)
        harness.trigger_secret_removal(secret.id, 1)
        harness.trigger_secret_removal(secret.id, 42, label='override')

        assert len(harness.charm.events) == 2
        event = harness.charm.events[0]
        # Not assertIsInstance to help type checkers.
        assert isinstance(event, ops.SecretRemoveEvent)
        assert event.secret.label == 'lbl'
        assert event.revision == 1
        assert event.secret.get_content() == {'foo': 'x'}
        event = harness.charm.events[1]
        # Not assertIsInstance to help type checkers.
        assert isinstance(event, ops.SecretRemoveEvent)
        assert event.secret.label == 'override'
        assert event.revision == 42
        assert event.secret.get_content() == {'foo': 'x'}

        with pytest.raises(RuntimeError):
            harness.trigger_secret_removal('nosecret', 1)

    def test_trigger_secret_expiration(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(EventRecorder, meta='name: database')
        request.addfinalizer(harness.cleanup)

        secret = harness.model.app.add_secret({'foo': 'x'}, label='lbl')
        assert secret.id is not None
        harness.begin()
        harness.framework.observe(harness.charm.on.secret_remove, harness.charm.record_event)
        harness.trigger_secret_removal(secret.id, 1)
        harness.trigger_secret_removal(secret.id, 42, label='override')

        assert len(harness.charm.events) == 2
        event = harness.charm.events[0]
        # Not assertIsInstance to help type checkers.
        assert isinstance(event, ops.SecretRemoveEvent)
        assert event.secret.label == 'lbl'
        assert event.revision == 1
        assert event.secret.get_content() == {'foo': 'x'}
        event = harness.charm.events[1]
        # Not assertIsInstance to help type checkers.
        assert isinstance(event, ops.SecretRemoveEvent)
        assert event.secret.label == 'override'
        assert event.revision == 42
        assert event.secret.get_content() == {'foo': 'x'}

        with pytest.raises(RuntimeError):
            harness.trigger_secret_removal('nosecret', 1)

    def test_trigger_secret_expiration_on_user_secret(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(EventRecorder, meta='name: database')
        request.addfinalizer(harness.cleanup)

        secret_id = harness.add_user_secret({'foo': 'bar'})
        assert secret_id is not None
        harness.begin()

        with pytest.raises(RuntimeError):
            harness.trigger_secret_expiration(secret_id, 1)

    def test_secret_permissions_unit(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: database')
        request.addfinalizer(harness.cleanup)
        harness.begin()

        # The charm can always manage a local unit secret.
        secret_id = harness.charm.unit.add_secret({'password': '1234'}).id
        secret = harness.charm.model.get_secret(id=secret_id)
        assert secret.get_content() == {'password': '1234'}
        info = secret.get_info()
        assert info.id == secret_id
        secret.set_content({'password': '5678'})
        secret.remove_all_revisions()

    def test_secret_permissions_leader(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: database')
        request.addfinalizer(harness.cleanup)
        harness.begin()

        # The leader can manage an application secret.
        harness.set_leader(True)
        secret_id = harness.charm.app.add_secret({'password': '1234'}).id
        secret = harness.charm.model.get_secret(id=secret_id)
        assert secret.get_content() == {'password': '1234'}
        info = secret.get_info()
        assert info.id == secret_id
        secret.set_content({'password': '5678'})
        secret.remove_all_revisions()

    def test_secret_permissions_nonleader(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: database')
        request.addfinalizer(harness.cleanup)
        harness.begin()

        # Non-leaders can only view an application secret.
        harness.set_leader(False)
        secret_id = harness.charm.app.add_secret({'password': '1234'}).id
        secret = harness.charm.model.get_secret(id=secret_id)
        assert secret.get_content() == {'password': '1234'}
        with pytest.raises(ops.model.SecretNotFoundError):
            secret.get_info()
        with pytest.raises(RuntimeError):
            secret.set_content({'password': '5678'})
        with pytest.raises(RuntimeError):
            secret.remove_all_revisions()

    def test_add_user_secret(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta=yaml.safe_dump({'name': 'webapp'}))
        request.addfinalizer(harness.cleanup)
        harness.begin()

        secret_content = {'password': 'foo'}
        secret_id = harness.add_user_secret(secret_content)
        harness.grant_secret(secret_id, 'webapp')

        secret = harness.model.get_secret(id=secret_id)
        assert secret.id == secret_id
        assert secret.get_content() == secret_content

    def test_get_user_secret_without_grant(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta=yaml.safe_dump({'name': 'webapp'}))
        request.addfinalizer(harness.cleanup)
        harness.begin()
        secret_id = harness.add_user_secret({'password': 'foo'})
        with pytest.raises(ops.ModelError):
            harness.model.get_secret(id=secret_id)

    def test_revoke_user_secret(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta=yaml.safe_dump({'name': 'webapp'}))
        request.addfinalizer(harness.cleanup)
        harness.begin()

        secret_content = {'password': 'foo'}
        secret_id = harness.add_user_secret(secret_content)
        harness.grant_secret(secret_id, 'webapp')
        harness.revoke_secret(secret_id, 'webapp')
        with pytest.raises(ops.ModelError):
            harness.model.get_secret(id=secret_id)

    def test_set_user_secret_content(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(EventRecorder, meta=yaml.safe_dump({'name': 'webapp'}))
        request.addfinalizer(harness.cleanup)
        harness.begin()
        secret_id = harness.add_user_secret({'password': 'foo'})
        harness.grant_secret(secret_id, 'webapp')
        secret = harness.model.get_secret(id=secret_id)
        assert secret.get_content() == {'password': 'foo'}
        harness.set_secret_content(secret_id, {'password': 'bar'})
        secret = harness.model.get_secret(id=secret_id)
        assert secret.get_content(refresh=True) == {'password': 'bar'}

    def test_user_secret_permissions(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: database')
        request.addfinalizer(harness.cleanup)
        harness.begin()

        # Charms can only view a user secret.
        secret_id = harness.add_user_secret({'password': '1234'})
        harness.grant_secret(secret_id, 'database')
        secret = harness.charm.model.get_secret(id=secret_id)
        assert secret.get_content() == {'password': '1234'}
        with pytest.raises(ops.model.SecretNotFoundError):
            secret.get_info()
        with pytest.raises(RuntimeError):
            secret.set_content({'password': '5678'})
        with pytest.raises(RuntimeError):
            secret.remove_all_revisions()


class EventRecorder(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.events: typing.List[ops.EventBase] = []

    def record_event(self, event: ops.EventBase):
        self.events.append(event)


class TestPorts:
    def test_ports(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)
        unit = harness.model.unit

        unit.open_port('tcp', 8080)
        unit.open_port('udp', 4000)
        unit.open_port('icmp')

        ports_set = unit.opened_ports()
        assert isinstance(ports_set, set)
        ports = sorted(ports_set, key=lambda p: (p.protocol, p.port))
        assert len(ports) == 3
        assert isinstance(ports[0], ops.Port)
        assert ports[0].protocol == 'icmp'
        assert ports[0].port is None
        assert ports[1].protocol == 'tcp'
        assert ports[1].port == 8080
        assert isinstance(ports[1], ops.Port)
        assert ports[2].protocol == 'udp'
        assert ports[2].port == 4000

        unit.close_port('tcp', 8080)
        unit.close_port('tcp', 8080)  # closing same port again has no effect
        unit.close_port('udp', 4000)

        ports_set = unit.opened_ports()
        assert isinstance(ports_set, set)
        ports = sorted(ports_set, key=lambda p: (p.protocol, p.port))
        assert len(ports) == 1
        assert isinstance(ports[0], ops.Port)
        assert ports[0].protocol == 'icmp'
        assert ports[0].port is None

        unit.close_port('icmp')

        ports_set = unit.opened_ports()
        assert ports_set == set()

    def test_errors(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase, meta='name: webapp')
        request.addfinalizer(harness.cleanup)
        unit = harness.model.unit

        with pytest.raises(ops.ModelError):
            unit.open_port('icmp', 8080)  # icmp cannot have port
        with pytest.raises(ops.ModelError):
            unit.open_port('ftp', 8080)  # invalid protocol  # type: ignore
        with pytest.raises(ops.ModelError):
            unit.open_port('tcp')  # tcp must have port
        with pytest.raises(ops.ModelError):
            unit.open_port('udp')  # udp must have port
        with pytest.raises(ops.ModelError):
            unit.open_port('tcp', 0)  # port out of range
        with pytest.raises(ops.ModelError):
            unit.open_port('tcp', 65536)  # port out of range


class TestHandleExec:
    @pytest.fixture
    def harness(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test
            containers:
                test-container:
            """,
        )
        harness.begin()
        harness.set_can_connect('test-container', True)
        yield harness
        harness.cleanup()

    @pytest.fixture
    def container(self, harness: ops.testing.Harness[ops.CharmBase]):
        return harness.charm.unit.get_container('test-container')

    def test_register_handler(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        harness.handle_exec(container, ['foo'], result='foo')
        harness.handle_exec(container, ['foo', 'bar', 'foobar'], result='foobar2')
        harness.handle_exec(container, ['foo', 'bar'], result='foobar')

        stdout, _ = container.exec(['foo', 'bar', 'foobar', '--help']).wait_output()
        assert stdout == 'foobar2'

        stdout, _ = container.exec(['foo', 'bar', '--help']).wait_output()
        assert stdout == 'foobar'

        stdout, _ = container.exec(['foo', 'bar']).wait_output()
        assert stdout == 'foobar'

        stdout, _ = container.exec(['foo', '--help']).wait_output()
        assert stdout == 'foo'

    def test_re_register_handler(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        harness.handle_exec(container, ['foo', 'bar'], result='foobar')
        harness.handle_exec(container, ['foo'], result='foo')

        stdout, _ = container.exec(['foo', 'bar']).wait_output()
        assert stdout == 'foobar'

        harness.handle_exec(container, ['foo', 'bar'], result='hello')
        stdout, _ = container.exec(['foo', 'bar']).wait_output()
        assert stdout == 'hello'

        harness.handle_exec(container.name, ['foo'], result='hello2')
        stdout, _ = container.exec(['foo']).wait_output()
        assert stdout == 'hello2'

        with pytest.raises(pebble.APIError):
            container.exec(['abc']).wait()

    def test_register_match_all_prefix(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        harness.handle_exec(container, [], result='hello')

        stdout, _ = container.exec(['foo', 'bar']).wait_output()
        assert stdout == 'hello'

        stdout, _ = container.exec(['ls']).wait_output()
        assert stdout == 'hello'

    def test_register_with_result(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        harness.handle_exec(container, ['foo'], result=10)

        excinfo: pytest.ExceptionInfo[pebble.ExecError[str]]
        with pytest.raises(pebble.ExecError) as excinfo:
            container.exec(['foo']).wait()
        assert excinfo.value.exit_code == 10

        harness.handle_exec(container, ['foo'], result='hello')
        stdout, stderr = container.exec(['foo']).wait_output()
        assert stdout == 'hello'
        assert stderr == ''
        with pytest.raises(ValueError):
            container.exec(['foo'], encoding=None).wait_output()

        harness.handle_exec(container, ['foo'], result=b'hello2')
        stdout, stderr = container.exec(['foo'], encoding=None).wait_output()
        assert stdout == b'hello2'
        assert stderr == b''
        stdout, stderr = container.exec(['foo']).wait_output()
        assert stdout == 'hello2'
        assert stderr == ''

    def test_register_with_handler(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        args_history: typing.List[ops.testing.ExecArgs] = []
        return_value = None

        def handler(args: ops.testing.ExecArgs):
            args_history.append(args)
            return return_value

        harness.handle_exec(container, ['foo'], handler=handler)

        container.exec(['foo', 'bar']).wait()
        assert len(args_history) == 1
        assert args_history[-1].command == ['foo', 'bar']

        return_value = ExecResult(exit_code=1)
        with pytest.raises(pebble.ExecError):
            container.exec(['foo', 'bar']).wait()

        return_value = ExecResult(stdout='hello', stderr='error')
        stdout, stderr = container.exec(['foo']).wait_output()
        assert stdout == 'hello'
        assert stderr == 'error'
        assert len(args_history) == 3

        container.exec(['foo'], environment={'bar': 'foobar'}).wait_output()
        assert args_history[-1].environment == {'bar': 'foobar'}

        return_value = ExecResult(stdout=b'hello')
        stdout, _ = container.exec(['foo'], encoding=None).wait_output()
        assert args_history[-1].encoding is None
        assert stdout == b'hello'

        container.exec(['foo'], working_dir='/test').wait_output()
        assert args_history[-1].working_dir == '/test'

        container.exec(['foo'], user='foo', user_id=1, group='bar', group_id=2).wait()
        assert args_history[-1].user == 'foo'
        assert args_history[-1].user_id == 1
        assert args_history[-1].group == 'bar'
        assert args_history[-1].group_id == 2

    def test_exec_timeout(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        def handler(_: ops.testing.ExecArgs):
            raise TimeoutError

        harness.handle_exec(container, [], handler=handler)
        with pytest.raises(TimeoutError):
            container.exec(['ls'], timeout=1).wait()
        with pytest.raises(RuntimeError):
            container.exec(['ls']).wait()

    def test_combined_error(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        return_value = ExecResult(stdout='foobar')
        harness.handle_exec(container, [], handler=lambda _: return_value)
        stdout, stderr = container.exec(['ls'], combine_stderr=True).wait_output()
        assert stdout == 'foobar'
        assert stderr == ''

        return_value = ExecResult(stdout='foobar', stderr='error')
        with pytest.raises(ValueError):
            container.exec(['ls'], combine_stderr=True).wait_output()

    def test_exec_stdin(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        args_history: typing.List[ops.testing.ExecArgs] = []

        def handler(args: ops.testing.ExecArgs):
            args_history.append(args)

        harness.handle_exec(container, [], handler=handler)
        proc = container.exec(['ls'], stdin='test')
        assert proc.stdin is None
        assert args_history[-1].stdin == 'test'

        proc = container.exec(['ls'])
        assert proc.stdin is not None
        assert args_history[-1].stdin is None

    def test_exec_stdout_stderr(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        harness.handle_exec(container, [], result=ExecResult(stdout='output', stderr='error'))
        stdout = io.StringIO()
        stderr = io.StringIO()
        proc = container.exec(['ls'], stderr=stderr, stdout=stdout)
        assert proc.stdout is None
        assert proc.stderr is None
        proc.wait()
        assert stdout.getvalue() == 'output'
        assert stderr.getvalue() == 'error'

        proc = container.exec(['ls'])
        assert proc.stdout is not None  # Not assertIsNotNone to help type checkers.
        assert proc.stderr is not None  # Not assertIsNotNone to help type checkers.
        proc.wait()
        assert proc.stdout.read() == 'output'
        assert proc.stderr.read() == 'error'

        harness.handle_exec(container, [], result=ExecResult(stdout=b'output', stderr=b'error'))
        stdout = io.StringIO()
        stderr = io.StringIO()
        proc = container.exec(['ls'], stderr=stderr, stdout=stdout)
        assert stdout.getvalue() == 'output'
        assert stderr.getvalue() == 'error'
        proc = container.exec(['ls'])
        assert proc.stdout is not None  # Not assertIsNotNone to help type checkers.
        assert proc.stderr is not None  # Not assertIsNotNone to help type checkers.
        assert proc.stdout.read() == 'output'
        assert proc.stderr.read() == 'error'

        stdout = io.BytesIO()
        stderr = io.BytesIO()
        proc = container.exec(['ls'], stderr=stderr, stdout=stdout, encoding=None)
        assert stdout.getvalue() == b'output'
        assert stderr.getvalue() == b'error'
        proc = container.exec(['ls'], encoding=None)
        assert proc.stdout is not None  # Not assertIsNotNone to help type checkers.
        assert proc.stderr is not None  # Not assertIsNotNone to help type checkers.
        assert proc.stdout.read() == b'output'
        assert proc.stderr.read() == b'error'

    def test_exec_service_context(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        container: ops.Container,
    ):
        service: ops.pebble.ServiceDict = {
            'command': 'test',
            'working-dir': '/tmp',  # noqa: S108
            'user': 'foo',
            'user-id': 1,
            'group': 'bar',
            'group-id': 2,
            'environment': {'foo': 'bar', 'foobar': 'barfoo'},
        }
        layer: ops.pebble.LayerDict = {
            'summary': '',
            'description': '',
            'services': {'test': service},
        }
        container.add_layer(label='test', layer=ops.pebble.Layer(layer))
        args_history: typing.List[ops.testing.ExecArgs] = []

        def handler(args: ops.testing.ExecArgs):
            args_history.append(args)

        container._juju_version = JujuVersion('3.2.1')
        harness.handle_exec(container, ['ls'], handler=handler)

        container.exec(['ls'], service_context='test').wait()
        assert args_history[-1].working_dir == '/tmp'  # noqa: S108
        assert args_history[-1].user == 'foo'
        assert args_history[-1].user_id == 1
        assert args_history[-1].group == 'bar'
        assert args_history[-1].group_id == 2
        assert args_history[-1].environment == {'foo': 'bar', 'foobar': 'barfoo'}

        container.exec(
            ['ls'],
            service_context='test',
            working_dir='/test',
            user='test',
            user_id=3,
            group='test_group',
            group_id=4,
            environment={'foo': 'hello'},
        ).wait()
        assert args_history[-1].working_dir == '/test'
        assert args_history[-1].user == 'test'
        assert args_history[-1].user_id == 3
        assert args_history[-1].group == 'test_group'
        assert args_history[-1].group_id == 4
        assert args_history[-1].environment == {'foo': 'hello', 'foobar': 'barfoo'}


class TestActions:
    @pytest.fixture
    def action_results(self):
        action_results: typing.Dict[str, typing.Any] = {}
        return action_results

    @pytest.fixture
    def harness(self, action_results: typing.Dict[str, typing.Any]):
        class ActionCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.framework.observe(self.on.simple_action, self._on_simple_action)
                self.framework.observe(self.on.fail_action, self._on_fail_action)
                self.framework.observe(self.on.results_action, self._on_results_action)
                self.framework.observe(
                    self.on.log_and_results_action, self._on_log_and_results_action
                )
                self.simple_was_called = False

            def _on_simple_action(self, event: ops.ActionEvent):
                """An action that doesn't generate logs, have any results, or fail."""
                self.simple_was_called = True
                assert isinstance(event.id, str)

            def _on_fail_action(self, event: ops.ActionEvent):
                event.fail('this will be ignored')
                event.log('some progress')
                if event.params.get('empty-failure-message'):
                    event.fail()
                else:
                    event.fail('something went wrong')
                event.log('more progress')
                event.set_results(action_results)

            def _on_log_and_results_action(self, event: ops.ActionEvent):
                event.log('Step 1')
                event.set_results({'result1': event.params['foo']})
                event.log('Step 2')
                event.set_results({'result2': event.params.get('bar')})

            def _on_results_action(self, event: ops.ActionEvent):
                event.set_results(action_results)

        harness = ops.testing.Harness(
            ActionCharm,
            meta="""
            name: test
            """,
            actions="""
            simple:
              description: lorem ipsum
            fail:
              description: dolor sit amet
            unobserved-param-tester:
              description: consectetur adipiscing elit
              params:
                foo
                bar
              required: [foo]
              additionalProperties: false
            log-and-results:
              description: sed do eiusmod tempor
              params:
                foo:
                  type: string
                  default: foo-default
                bar:
                  type: integer
            results:
              description: incididunt ut labore
            """,
        )
        harness.begin()
        yield harness
        harness.cleanup()

    def test_before_begin(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test
            """,
        )
        with pytest.raises(RuntimeError):
            harness.run_action('fail')

    def test_invalid_action(self, harness: ops.testing.Harness[ops.CharmBase]):
        # This action isn't in the metadata at all.
        with pytest.raises(RuntimeError):
            harness.run_action('another-action')
        # Also check that we're not exposing the action with the dash to underscore replacement.
        with pytest.raises(RuntimeError):
            harness.run_action('log_and_results')

    def test_run_action(self, harness: ops.testing.Harness[ops.CharmBase]):
        out = harness.run_action('simple')
        assert out.logs == []
        assert out.results == {}
        assert harness.charm.simple_was_called  # type: ignore

    def test_fail_action_no_message(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(ops.testing.ActionFailed) as excinfo:
            harness.run_action('fail', {'empty-failure-message': True})
            assert 'called `fail()`' in str(excinfo.value)
        assert excinfo.value.message == ''

    def test_fail_action(
        self,
        action_results: typing.Dict[str, typing.Any],
        harness: ops.testing.Harness[ops.CharmBase],
    ):
        action_results['partial'] = 'foo'
        with pytest.raises(ops.testing.ActionFailed) as excinfo:
            harness.run_action('fail')

        assert excinfo.value.message == 'something went wrong'
        assert excinfo.value.output.logs == ['some progress', 'more progress']
        assert excinfo.value.output.results == {'partial': 'foo'}

    def test_required_param(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(RuntimeError):
            harness.run_action('unobserved-param-tester')
        with pytest.raises(RuntimeError):
            harness.run_action('unobserved-param-tester', {'bar': 'baz'})
        harness.run_action('unobserved-param-tester', {'foo': 'baz'})
        harness.run_action('unobserved-param-tester', {'foo': 'baz', 'bar': 'qux'})

    def test_additional_params(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.run_action('simple', {'foo': 'bar'})
        with pytest.raises(ops.ModelError):
            harness.run_action('unobserved-param-tester', {'foo': 'bar', 'qux': 'baz'})
        harness.run_action(
            'simple',
            {
                'string': 'hello',
                'number': 28.8,
                'object': {'a': {'b': 'c'}},
                'array': [1, 2, 3],
                'boolean': True,
                'null': None,
            },
        )

    def test_logs_and_results(self, harness: ops.testing.Harness[ops.CharmBase]):
        out = harness.run_action('log-and-results')
        assert out.logs == ['Step 1', 'Step 2']
        assert out.results == {'result1': 'foo-default', 'result2': None}
        out = harness.run_action('log-and-results', {'foo': 'baz', 'bar': 28})
        assert out.results == {'result1': 'baz', 'result2': 28}

    @pytest.mark.parametrize(
        'prohibited_key', ['stdout', 'stdout-encoding', 'stderr', 'stderr-encoding']
    )
    def test_bad_results(
        self,
        action_results: typing.Dict[str, typing.Any],
        harness: ops.testing.Harness[ops.CharmBase],
        prohibited_key: str,
    ):
        action_results['a'] = {'b': 1}
        action_results['a.b'] = 2
        with pytest.raises(ValueError):
            harness.run_action('results')

        # There are some result key names we cannot use.
        action_results.clear()
        action_results[prohibited_key] = 'foo'
        with pytest.raises(ops.ModelError):
            harness.run_action('results')

        # There are some additional rules around what result keys are valid.
        action_results.clear()
        action_results['A'] = 'foo'
        with pytest.raises(ValueError):
            harness.run_action('results')


class TestNotify:
    def test_notify_basics(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(
            ContainerEventCharm,
            meta="""
            name: notifier
            containers:
              foo:
                resource: foo-image
              bar:
                resource: foo-image
        """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_container_events('foo')
        harness.charm.observe_container_events('bar')

        id1a = harness.pebble_notify('foo', 'example.com/n1')
        id2 = harness.pebble_notify('foo', 'foo.com/n2')
        id3 = harness.pebble_notify('bar', 'example.com/n1')
        id1b = harness.pebble_notify('foo', 'example.com/n1')

        assert isinstance(id1a, str)
        assert id1a != ''
        assert id1a == id1b

        assert isinstance(id2, str)
        assert id2 != ''
        assert id2 != id1a

        assert isinstance(id3, str)
        assert id3 != ''
        assert id3 != id2

        expected_changes = [
            {
                'name': 'pebble-custom-notice',
                'container': 'foo',
                'notice_id': id1a,
                'notice_type': 'custom',
                'notice_key': 'example.com/n1',
            },
            {
                'name': 'pebble-custom-notice',
                'container': 'foo',
                'notice_id': id2,
                'notice_type': 'custom',
                'notice_key': 'foo.com/n2',
            },
            {
                'name': 'pebble-custom-notice',
                'container': 'bar',
                'notice_id': id3,
                'notice_type': 'custom',
                'notice_key': 'example.com/n1',
            },
            {
                'name': 'pebble-custom-notice',
                'container': 'foo',
                'notice_id': id1a,
                'notice_type': 'custom',
                'notice_key': 'example.com/n1',
            },
        ]
        assert harness.charm.changes == expected_changes

    def test_notify_no_repeat(self, request: pytest.FixtureRequest):
        """Ensure event doesn't get triggered when notice occurs but doesn't repeat."""
        harness = ops.testing.Harness(
            ContainerEventCharm,
            meta="""
            name: notifier
            containers:
              foo:
                resource: foo-image
        """,
        )
        request.addfinalizer(harness.cleanup)
        harness.begin()
        harness.charm.observe_container_events('foo')

        id1a = harness.pebble_notify(
            'foo', 'example.com/n1', repeat_after=datetime.timedelta(days=1)
        )
        id1b = harness.pebble_notify(
            'foo', 'example.com/n1', repeat_after=datetime.timedelta(days=1)
        )

        assert id1a == id1b

        expected_changes = [
            {
                'name': 'pebble-custom-notice',
                'container': 'foo',
                'notice_id': id1a,
                'notice_type': 'custom',
                'notice_key': 'example.com/n1',
            }
        ]
        assert harness.charm.changes == expected_changes

    def test_notify_no_begin(self, request: pytest.FixtureRequest):
        num_notices = 0

        class TestCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.framework.observe(
                    self.on['c1'].pebble_custom_notice, self._on_pebble_custom_notice
                )

            def _on_pebble_custom_notice(self, event: ops.PebbleCustomNoticeEvent):
                nonlocal num_notices
                num_notices += 1

        harness = ops.testing.Harness(
            TestCharm,
            meta="""
            name: notifier
            containers:
              c1:
                resource: c1-image
        """,
        )
        request.addfinalizer(harness.cleanup)

        id = harness.pebble_notify('c1', 'example.com/n1')

        assert isinstance(id, str)
        assert id != ''
        assert num_notices == 0

    def test_check_failed(self, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
        harness = ops.testing.Harness(
            ContainerEventCharm,
            meta="""
            name: notifier
            containers:
              foo:
                resource: foo-image
        """,
        )
        request.addfinalizer(harness.cleanup)
        harness.set_can_connect('foo', True)
        harness.begin()
        harness.charm.observe_container_events('foo')

        def get_change(_: ops.pebble.Client, change_id: str):
            return ops.pebble.Change.from_dict({
                'id': change_id,
                'kind': pebble.ChangeKind.PERFORM_CHECK.value,
                'summary': '',
                'status': pebble.ChangeStatus.ERROR.value,
                'ready': False,
                'spawn-time': '2021-02-10T04:36:22.118970777Z',
            })

        monkeypatch.setattr(ops.testing._TestingPebbleClient, 'get_change', get_change)
        harness.pebble_notify(
            'foo',
            '123',
            type=pebble.NoticeType.CHANGE_UPDATE,
            data={'kind': 'perform-check', 'check-name': 'http-check'},
        )

        expected_changes = [
            {
                'name': 'pebble-check-failed',
                'container': 'foo',
                'check_name': 'http-check',
            }
        ]
        assert harness.charm.changes == expected_changes


class PebbleNoticesMixin:
    def test_get_notice_by_id(self, client: PebbleClientType):
        key1 = 'example.com/' + os.urandom(16).hex()
        key2 = 'example.com/' + os.urandom(16).hex()
        id1 = client.notify(pebble.NoticeType.CUSTOM, key1)
        id2 = client.notify(pebble.NoticeType.CUSTOM, key2, data={'x': 'y'})
        time.sleep(0.000_001)  # Ensure times are different.
        client.notify(pebble.NoticeType.CUSTOM, key2, data={'k': 'v', 'foo': 'bar'})

        notice = client.get_notice(id1)
        assert notice.id == id1
        assert notice.type == pebble.NoticeType.CUSTOM
        assert notice.key == key1
        assert notice.first_occurred == notice.last_occurred
        assert notice.first_occurred == notice.last_repeated
        assert notice.occurrences == 1
        assert notice.last_data == {}
        assert notice.repeat_after is None
        assert notice.expire_after == datetime.timedelta(days=7)

        notice = client.get_notice(id2)
        assert notice.id == id2
        assert notice.type == pebble.NoticeType.CUSTOM
        assert notice.key == key2
        assert notice.first_occurred < notice.last_occurred
        assert notice.first_occurred < notice.last_repeated
        assert notice.last_occurred == notice.last_repeated
        assert notice.occurrences == 2
        assert notice.last_data == {'k': 'v', 'foo': 'bar'}
        assert notice.repeat_after is None
        assert notice.expire_after == datetime.timedelta(days=7)

    def test_get_notices(self, client: PebbleClientType):
        key1 = 'example.com/' + os.urandom(16).hex()
        key2 = 'example.com/' + os.urandom(16).hex()
        key3 = 'example.com/' + os.urandom(16).hex()

        client.notify(pebble.NoticeType.CUSTOM, key1)
        time.sleep(0.000_001)  # Ensure times are different.
        client.notify(pebble.NoticeType.CUSTOM, key2)
        time.sleep(0.000_001)  # Ensure times are different.
        client.notify(pebble.NoticeType.CUSTOM, key3)

        notices = client.get_notices()
        assert len(notices) >= 3

        notices = client.get_notices(keys=[key1, key2, key3])
        assert len(notices) == 3
        assert notices[0].key == key1
        assert notices[1].key == key2
        assert notices[2].key == key3
        assert notices[0].last_repeated < notices[1].last_repeated
        assert notices[1].last_repeated < notices[2].last_repeated

        notices = client.get_notices(keys=[key2])
        assert len(notices) == 1
        assert notices[0].key == key2

        notices = client.get_notices(keys=[key1, key3])
        assert len(notices) == 2
        assert notices[0].key == key1
        assert notices[1].key == key3
        assert notices[0].last_repeated < notices[1].last_repeated


class TestNotices(PebbleNoticesMixin):
    @pytest.fixture
    def client(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              mycontainer: {}
            """,
        )
        backend = harness._backend
        client = backend.get_pebble('/charm/containers/mycontainer/pebble.socket')
        harness.set_can_connect('mycontainer', True)
        yield client
        harness.cleanup()


class TestCloudSpec:
    def test_set_cloud_spec(self, request: pytest.FixtureRequest):
        class TestCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                framework.observe(self.on.start, self._on_start)

            def _on_start(self, event: ops.StartEvent):
                self.cloud_spec = self.model.get_cloud_spec()

        harness = ops.testing.Harness(TestCharm)
        request.addfinalizer(harness.cleanup)
        cloud_spec_dict = {
            'name': 'localhost',
            'type': 'lxd',
            'endpoint': 'https://127.0.0.1:8443',
            'credential': {
                'auth-type': 'certificate',
                'attrs': {'client-cert': 'foo', 'client-key': 'bar', 'server-cert': 'baz'},
            },
        }
        harness.set_cloud_spec(ops.CloudSpec.from_dict(cloud_spec_dict))
        harness.begin()
        harness.charm.on.start.emit()
        assert harness.charm.cloud_spec == ops.CloudSpec.from_dict(cloud_spec_dict)

    def test_get_cloud_spec_without_set_error(self, request: pytest.FixtureRequest):
        harness = ops.testing.Harness(ops.CharmBase)
        request.addfinalizer(harness.cleanup)
        harness.begin()
        with pytest.raises(ops.ModelError):
            harness.model.get_cloud_spec()
