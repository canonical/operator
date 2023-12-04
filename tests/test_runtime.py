import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import pytest
import yaml
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase

from scenario import Context
from scenario.runtime import Runtime, UncaughtCharmError
from scenario.state import Event, Relation, State, _CharmSpec


def charm_type():
    class _CharmEvents(CharmEvents):
        pass

    class MyCharm(CharmBase):
        on = _CharmEvents()
        _event = None

        def __init__(self, framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._catchall)

        def _catchall(self, e):
            if self._event:
                return
            MyCharm._event = e

    return MyCharm


def test_event_emission():
    with TemporaryDirectory() as tempdir:
        meta = {
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        }

        my_charm_type = charm_type()

        class MyEvt(EventBase):
            pass

        my_charm_type.on.define_event("bar", MyEvt)

        runtime = Runtime(
            _CharmSpec(
                my_charm_type,
                meta=meta,
            ),
        )

        with runtime.exec(
            state=State(), event=Event("bar"), context=Context(my_charm_type, meta=meta)
        ) as ops:
            pass

        assert my_charm_type._event
        assert isinstance(my_charm_type._event, MyEvt)


@pytest.mark.parametrize("app_name", ("foo", "bar-baz", "QuX2"))
@pytest.mark.parametrize("unit_id", (1, 2, 42))
def test_unit_name(app_name, unit_id):
    meta = {
        "name": app_name,
    }

    my_charm_type = charm_type()

    runtime = Runtime(
        _CharmSpec(
            my_charm_type,
            meta=meta,
        ),
        unit_id=unit_id,
        app_name=app_name,
    )

    with runtime.exec(
        state=State(),
        event=Event("start"),
        context=Context(my_charm_type, meta=meta),
    ) as ops:
        assert ops.charm.unit.name == f"{app_name}/{unit_id}"


def test_env_cleanup_on_charm_error():
    meta = {"name": "frank", "requires": {"box": {"interface": "triangle"}}}

    my_charm_type = charm_type()

    runtime = Runtime(
        _CharmSpec(
            my_charm_type,
            meta=meta,
        ),
    )

    with pytest.raises(UncaughtCharmError):
        with runtime.exec(
            state=State(),
            event=Event("box_relation_changed", relation=Relation("box")),
            context=Context(my_charm_type, meta=meta),
        ):
            assert os.getenv("JUJU_REMOTE_APP")
            _ = 1 / 0  # raise some error

    assert os.getenv("JUJU_REMOTE_APP", None) is None
