import sys
import tempfile
from pathlib import Path
from subprocess import Popen

import pytest

# keep this block before `ops` imports. This ensures that if you've called Runtime.install() on
# your current venv, ops.model won't break as it tries to import recorder.py

try:
    from memo import memo
except ModuleNotFoundError:
    from scenario.runtime.runtime import RUNTIME_MODULE
    sys.path.append(str(RUNTIME_MODULE.absolute()))

from ops.charm import CharmBase, CharmEvents

from scenario.runtime.runtime import Runtime

MEMO_TOOLS_RESOURCES_FOLDER = Path(__file__).parent / "memo_tools_test_files"


@pytest.fixture(scope="module", autouse=True)
def runtime_ctx():
    # helper to install the runtime and try and
    #    prevent ops from being destroyed every time
    import ops

    ops_dir = Path(ops.__file__).parent
    with tempfile.TemporaryDirectory() as td:
        # stash away the ops source
        Popen(f"cp -r {ops_dir} {td}".split())

        Runtime.install()
        yield

        Popen(f"mv {Path(td) / 'ops'} {ops_dir}".split())


def charm_type():
    class _CharmEvents(CharmEvents):
        pass

    class MyCharm(CharmBase):
        on = _CharmEvents()

        def __init__(self, framework, key=None):
            super().__init__(framework, key)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._catchall)
            self._event = None

        def _catchall(self, e):
            self._event = e

    return MyCharm


@pytest.mark.parametrize(
    "evt_idx, expected_name",
    (
        (0, "ingress_per_unit_relation_departed"),
        (1, "ingress_per_unit_relation_departed"),
        (2, "ingress_per_unit_relation_broken"),
        (3, "ingress_per_unit_relation_created"),
        (4, "ingress_per_unit_relation_joined"),
        (5, "ingress_per_unit_relation_changed"),
    ),
)
def test_run(evt_idx, expected_name):
    charm = charm_type()
    runtime = Runtime(
        charm,
        meta={
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        },
        local_db_path=MEMO_TOOLS_RESOURCES_FOLDER / "trfk-re-relate.json",
        install=True,
    )

    charm, scene = runtime.run(evt_idx)
    assert charm.unit.name == "trfk/0"
    assert charm.model.name == "foo"
    assert (
        charm._event.handle.kind == scene.event.name.replace("-", "_") == expected_name
    )


def test_relation_data():
    charm = charm_type()
    runtime = Runtime(
        charm,
        meta={
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        },
        local_db_path=MEMO_TOOLS_RESOURCES_FOLDER / "trfk-re-relate.json",
    )
    charm, scene = runtime.run(5)  # ipu-relation-changed

    assert scene.event.name == "ingress-per-unit-relation-changed"

    rel = charm.model.relations["ingress-per-unit"][0]

    for _ in range(2):
        # the order in which we call the hook tools should not matter because
        # relation-get is cached in 'loose' mode! yay!
        _ = rel.data[charm.app]

        remote_unit_data = rel.data[list(rel.units)[0]]
        assert remote_unit_data["host"] == "prom-1.prom-endpoints.foo.svc.cluster.local"
        assert remote_unit_data["port"] == "9090"
        assert remote_unit_data["model"] == "foo"
        assert remote_unit_data["name"] == "prom/1"

        local_app_data = rel.data[charm.app]
        assert local_app_data == {}


def test_local_run_loose():
    runtime = Runtime(
        charm_type(),
        meta={
            "name": "foo",
            "requires": {"ingress-per-unit": {"interface": "ingress_per_unit"}},
        },
        local_db_path=MEMO_TOOLS_RESOURCES_FOLDER / "trfk-re-relate.json",
    )
    charm, scene = runtime.run(5)  # ipu-relation-changed

    assert scene.event.name == "ingress-per-unit-relation-changed"

    rel = charm.model.relations["ingress-per-unit"][0]

    # fixme: we need to access the data in the same ORDER in which we did before.
    #  for relation-get, it should be safe to ignore the memo ordering,
    #  since the data is frozen for the hook duration.
    #  actually it should be fine for most hook tools, except leader and status.
    #  pebble is a different story.

    remote_unit_data = rel.data[list(rel.units)[0]]
    assert remote_unit_data["host"] == "prom-1.prom-endpoints.foo.svc.cluster.local"
    assert remote_unit_data["port"] == "9090"
    assert remote_unit_data["model"] == "foo"
    assert remote_unit_data["name"] == "prom/1"

    local_app_data = rel.data[charm.app]
    assert local_app_data == {}
