from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import yaml

from charm import CharmEvents, CharmBase
from ops.framework import EventBase
from scenario.runtime import Runtime
from scenario.structs import CharmSpec, Scene, event


def charm_type():
    class _CharmEvents(CharmEvents):
        pass

    class MyCharm(CharmBase):
        on = _CharmEvents()
        _event = None

        def __init__(self, framework, key=None):
            super().__init__(framework, key)
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
        meta_file = (temppath / 'metadata.yaml')
        meta_file.write_text(yaml.safe_dump(meta))

        runtime = Runtime(
            CharmSpec(
                charm_type(),
                meta=meta,
            )
        )

        pre_event = MagicMock(return_value=None)
        post_event = MagicMock(return_value=None)
        runtime.play(Scene(event=event('foo')),
                     pre_event=pre_event,
                     post_event=post_event)

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

        my_charm_type.on.define_event('bar', MyEvt)

        runtime = Runtime(
            CharmSpec(
                my_charm_type,
                meta=meta,
            ),
        )

        runtime.play(Scene(event=event('bar')))

        assert my_charm_type._event
        assert isinstance(my_charm_type._event, MyEvt)
