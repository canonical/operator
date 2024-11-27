import os
from tempfile import TemporaryDirectory

import pytest

import ops

from scenario import Context
from scenario.state import Relation, State, _CharmSpec, _Event
from scenario._runtime import Runtime, UncaughtCharmError


def charm_type():
    class _CharmEvents(ops.CharmEvents):
        pass

    class MyCharm(ops.CharmBase):
        on = _CharmEvents()  # type: ignore
        _event = None

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._catchall)

        def _catchall(self, e: ops.EventBase):
            if self._event:
                return
            MyCharm._event = e

    return MyCharm


def test_event_emission():
    with TemporaryDirectory():
        meta = {
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        }

        my_charm_type = charm_type()

        class MyEvt(ops.EventBase):
            pass

        my_charm_type.on.define_event("bar", MyEvt)

        runtime = Runtime(
            _CharmSpec(
                my_charm_type,
                meta=meta,
            ),
        )

        with runtime.exec(
            state=State(),
            event=_Event("bar"),
            context=Context(my_charm_type, meta=meta),
        ) as manager:
            manager.run()

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
        event=_Event("start"),
        context=Context(my_charm_type, meta=meta),
    ) as manager:
        assert manager.charm.unit.name == f"{app_name}/{unit_id}"


def test_env_clean_on_charm_error():
    meta = {"name": "frank", "requires": {"box": {"interface": "triangle"}}}

    my_charm_type = charm_type()

    runtime = Runtime(
        _CharmSpec(
            my_charm_type,
            meta=meta,
        ),
    )

    remote_name = "ava"
    rel = Relation("box", remote_app_name=remote_name)
    with pytest.raises(UncaughtCharmError) as exc:
        with runtime.exec(
            state=State(relations={rel}),
            event=_Event("box_relation_changed", relation=rel),
            context=Context(my_charm_type, meta=meta),
        ) as manager:
            assert manager._juju_context.remote_app_name == remote_name
            assert "JUJU_REMOTE_APP" not in os.environ
            _ = 1 / 0  # raise some error
    # Ensure that some other error didn't occur (like AssertionError!).
    assert "ZeroDivisionError" in str(exc.value)

    # Ensure that the Juju environment didn't leak into the outside one.
    assert os.getenv("JUJU_REMOTE_APP", None) is None
