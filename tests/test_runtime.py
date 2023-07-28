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
            MyCharm._event = e

    return MyCharm


def test_event_hooks():
    with TemporaryDirectory() as tempdir:
        meta = {
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        }
        temppath = Path(tempdir)
        meta_file = temppath / "metadata.yaml"
        meta_file.write_text(yaml.safe_dump(meta))

        my_charm_type = charm_type()
        runtime = Runtime(
            _CharmSpec(
                my_charm_type,
                meta=meta,
            ),
        )

        pre_event = MagicMock(return_value=None)
        post_event = MagicMock(return_value=None)
        runtime.exec(
            state=State(),
            event=Event("update_status"),
            pre_event=pre_event,
            post_event=post_event,
            context=Context(my_charm_type, meta=meta),
        )

        assert pre_event.called
        assert post_event.called


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

        runtime.exec(
            state=State(), event=Event("bar"), context=Context(my_charm_type, meta=meta)
        )

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
    )

    def post_event(charm: CharmBase):
        assert charm.unit.name == f"{app_name}/{unit_id}"

    runtime.exec(
        state=State(unit_id=unit_id),
        event=Event("start"),
        post_event=post_event,
        context=Context(my_charm_type, meta=meta),
    )


def test_env_cleanup_on_charm_error():
    meta = {"name": "frank", "requires": {"box": {"interface": "triangle"}}}

    my_charm_type = charm_type()

    runtime = Runtime(
        _CharmSpec(
            my_charm_type,
            meta=meta,
        ),
    )

    def post_event(charm: CharmBase):
        assert os.getenv("JUJU_REMOTE_APP")
        raise TypeError

    with pytest.raises(UncaughtCharmError):
        runtime.exec(
            state=State(),
            event=Event("box_relation_changed", relation=Relation("box")),
            post_event=post_event,
            context=Context(my_charm_type, meta=meta),
        )

    assert os.getenv("JUJU_REMOTE_APP", None) is None
