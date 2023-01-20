import tempfile
from io import StringIO
from pathlib import Path
from typing import Optional

import pytest
from ops.charm import ActionEvent, CharmBase, StartEvent
from ops.framework import Framework

from scenario.scenario import Scenario
from scenario.structs import CharmSpec, ContainerSpec, ExecOutput, Scene, State, event


@pytest.fixture(scope="function")
def charm_cls():
    class MyCharm(CharmBase):
        callback = None

        def __init__(self, framework: Framework, key: Optional[str] = None):
            super().__init__(framework, key)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            self.callback(event)

    return MyCharm


def test_no_containers(charm_cls):
    scenario = Scenario(CharmSpec(charm_cls, meta={"name": "foo"}))
    scene = Scene(event("start"), state=State())

    def callback(self: CharmBase, evt):
        assert not self.unit.containers

    charm_cls.callback = callback
    scenario.play(scene)


def test_containers_from_meta(charm_cls):
    scenario = Scenario(
        CharmSpec(charm_cls, meta={"name": "foo", "containers": {"foo": {}}})
    )
    scene = Scene(event("start"), state=State())

    def callback(self: CharmBase, evt):
        assert self.unit.containers
        assert self.unit.get_container("foo")

    charm_cls.callback = callback
    scenario.play(scene)


@pytest.mark.parametrize("can_connect", (True, False))
def test_connectivity(charm_cls, can_connect):
    scenario = Scenario(
        CharmSpec(charm_cls, meta={"name": "foo", "containers": {"foo": {}}})
    )
    scene = Scene(
        event("start"),
        state=State(containers=[ContainerSpec(name="foo", can_connect=can_connect)]),
    )

    def callback(self: CharmBase, evt):
        assert can_connect == self.unit.get_container("foo").can_connect()

    charm_cls.callback = callback
    scenario.play(scene)


def test_fs_push(charm_cls):
    scenario = Scenario(
        CharmSpec(charm_cls, meta={"name": "foo", "containers": {"foo": {}}})
    )

    text = "lorem ipsum/n alles amat gloriae foo"
    file = tempfile.NamedTemporaryFile()
    pth = Path(file.name)
    pth.write_text(text)

    scene = Scene(
        event("start"),
        state=State(
            containers=[
                ContainerSpec(
                    name="foo", can_connect=True, filesystem={"bar": {"baz.txt": pth}}
                )
            ]
        ),
    )

    def callback(self: CharmBase, evt):
        container = self.unit.get_container("foo")
        baz = container.pull("/bar/baz.txt")
        assert baz.read() == text

    charm_cls.callback = callback
    scenario.play(scene)


@pytest.mark.parametrize("make_dirs", (True, False))
def test_fs_pull(charm_cls, make_dirs):
    scenario = Scenario(
        CharmSpec(charm_cls, meta={"name": "foo", "containers": {"foo": {}}})
    )

    scene = Scene(
        event("start"),
        state=State(containers=[ContainerSpec(name="foo", can_connect=True)]),
    )

    text = "lorem ipsum/n alles amat gloriae foo"

    def callback(self: CharmBase, evt):
        container = self.unit.get_container("foo")
        if make_dirs:
            container.push("/bar/baz.txt", text, make_dirs=make_dirs)
            # check that pulling immediately 'works'
            baz = container.pull("/bar/baz.txt")
            assert baz.read() == text
        else:
            with pytest.raises(FileNotFoundError):
                container.push("/bar/baz.txt", text, make_dirs=make_dirs)

            # check that nothing was changed
            with pytest.raises(FileNotFoundError):
                container.pull("/bar/baz.txt")

    charm_cls.callback = callback
    out = scenario.play(scene)

    if make_dirs:
        file = out.get_container("foo").filesystem["bar"]["baz.txt"]
        assert file.read_text() == text
    else:
        # nothing has changed
        assert not out.delta(scene.state)


LS = """
.rw-rw-r--  228 ubuntu ubuntu 18 jan 12:05 -- charmcraft.yaml    
.rw-rw-r--  497 ubuntu ubuntu 18 jan 12:05 -- config.yaml        
.rw-rw-r--  900 ubuntu ubuntu 18 jan 12:05 -- CONTRIBUTING.md    
drwxrwxr-x    - ubuntu ubuntu 18 jan 12:06 -- lib                
.rw-rw-r--  11k ubuntu ubuntu 18 jan 12:05 -- LICENSE            
.rw-rw-r-- 1,6k ubuntu ubuntu 18 jan 12:05 -- metadata.yaml      
.rw-rw-r--  845 ubuntu ubuntu 18 jan 12:05 -- pyproject.toml     
.rw-rw-r--  831 ubuntu ubuntu 18 jan 12:05 -- README.md          
.rw-rw-r--   13 ubuntu ubuntu 18 jan 12:05 -- requirements.txt   
drwxrwxr-x    - ubuntu ubuntu 18 jan 12:05 -- src                
drwxrwxr-x    - ubuntu ubuntu 18 jan 12:05 -- tests              
.rw-rw-r-- 1,9k ubuntu ubuntu 18 jan 12:05 -- tox.ini            
"""
PS = """
    PID TTY          TIME CMD    
 298238 pts/3    00:00:04 zsh    
1992454 pts/3    00:00:00 ps     
"""


@pytest.mark.parametrize(
    "cmd, out",
    (
        ("ls", LS),
        ("ps", PS),
    ),
)
def test_exec(charm_cls, cmd, out):
    scenario = Scenario(
        CharmSpec(charm_cls, meta={"name": "foo", "containers": {"foo": {}}})
    )

    scene = Scene(
        event("start"),
        state=State(
            containers=[
                ContainerSpec(
                    name="foo",
                    can_connect=True,
                    exec_mock={(cmd,): ExecOutput(stdout="hello pebble")},
                )
            ]
        ),
    )

    def callback(self: CharmBase, evt):
        container = self.unit.get_container("foo")
        proc = container.exec([cmd])
        proc.wait()
        assert proc.stdout.read() == "hello pebble"

    charm_cls.callback = callback
    scenario.play(scene)
