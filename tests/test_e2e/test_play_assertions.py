from typing import Optional, Type

import pytest
from ops.charm import CharmBase, CharmEvents, StartEvent
from ops.framework import EventBase, Framework

from scenario.scenario import Scenario
from scenario.structs import (
    CharmSpec,
    Context,
    Scene,
    State,
    event,
    relation,
)


@pytest.fixture(scope="function")
def mycharm():
    class MyCharmEvents(CharmEvents):
        @classmethod
        def define_event(cls, event_kind: str, event_type: "Type[EventBase]"):
            if getattr(cls, event_kind, None):
                delattr(cls, event_kind)
            return super().define_event(event_kind, event_type)

    class MyCharm(CharmBase):
        _call = None
        on = MyCharmEvents()

        def __init__(self, framework: Framework, key: Optional[str] = None):
            super().__init__(framework, key)
            self.called = False

            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            if self._call:
                self.called = True
                self._call(event)

    return MyCharm


def test_called(mycharm):
    mycharm._call = lambda *_: True
    scenario = Scenario(CharmSpec(mycharm, meta={"name": "foo"}))

    def pre_event(charm):
        pre_event._called = True
        assert not charm.called

    def post_event(charm):
        post_event._called = True

        from ops.model import ActiveStatus
        charm.unit.status = ActiveStatus('yabadoodle')

        assert charm.called

    out = scenario.play(
        Scene(
            event("start"),
            context=Context(
                state=State(config={"foo": "bar"}, leader=True))),
        pre_event=pre_event, post_event=post_event)

    assert pre_event._called
    assert post_event._called

    assert out.delta() == [
        {'op': 'replace', 'path': '/state/status/unit', 'value': ('active', 'yabadoodle')}
    ]


def test_relation_data_access(mycharm):
    mycharm._call = lambda *_: True
    scenario = Scenario(CharmSpec(
        mycharm,
        meta={"name": "foo",
              "requires": {"relation_test":
                               {"interface": "azdrubales"}}}))

    def check_relation_data(charm):
        foo_relations = charm.model.relations['relation_test']
        assert len(foo_relations) == 1
        foo_rel = foo_relations[0]
        assert len(foo_rel.units) == 2

        remote_units_data = {}
        for remote_unit in foo_rel.units:
            remote_units_data[remote_unit.name] = dict(foo_rel.data[remote_unit])

        remote_app_data = foo_rel.data[foo_rel.app]

        assert remote_units_data == {
            'karlos/0': {'foo': 'bar'},
            'karlos/1': {'baz': 'qux'}}

        assert remote_app_data == {'yaba': 'doodle'}

    scene = Scene(
        context=Context(
            state=State(relations=[
                relation(endpoint="relation_test",
                         interface="azdrubales",
                         remote_app_name="karlos",
                         remote_app_data={'yaba': 'doodle'},
                         remote_unit_ids=[0, 1],
                         remote_units_data={
                             '0': {'foo': 'bar'},
                             '1': {'baz': 'qux'}
                         }
                         )
            ])),
        event=event('update-status')
    )

    scenario.play(scene,
                  post_event=check_relation_data,
                  )
