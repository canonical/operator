import tempfile
from pathlib import Path

import pytest
from ops import pebble
from ops.charm import CharmBase
from ops.framework import Framework
from ops.pebble import ServiceStartup, ServiceStatus

from scenario.state import Container, ExecOutput, Mount, State
from tests.helpers import trigger


@pytest.fixture(scope="function")
def charm_cls():
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            pass

    return MyCharm


def test_no_containers(charm_cls):
    def callback(self: CharmBase):
        assert not self.unit.containers

    trigger(
        State(),
        charm_type=charm_cls,
        meta={"name": "foo"},
        event="start",
        post_event=callback,
    )


def test_containers_from_meta(charm_cls):
    def callback(self: CharmBase):
        assert self.unit.containers
        assert self.unit.get_container("foo")

    trigger(
        State(),
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )


@pytest.mark.parametrize("can_connect", (True, False))
def test_connectivity(charm_cls, can_connect):
    def callback(self: CharmBase):
        assert can_connect == self.unit.get_container("foo").can_connect()

    trigger(
        State(containers=[Container(name="foo", can_connect=can_connect)]),
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )


def test_fs_push(charm_cls):
    text = "lorem ipsum/n alles amat gloriae foo"
    file = tempfile.NamedTemporaryFile()
    pth = Path(file.name)
    pth.write_text(text)

    def callback(self: CharmBase):
        container = self.unit.get_container("foo")
        baz = container.pull("/bar/baz.txt")
        assert baz.read() == text

    trigger(
        State(
            containers=[
                Container(
                    name="foo",
                    can_connect=True,
                    mounts={"bar": Mount("/bar/baz.txt", pth)},
                )
            ]
        ),
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )


@pytest.mark.parametrize("make_dirs", (True, False))
def test_fs_pull(charm_cls, make_dirs):
    text = "lorem ipsum/n alles amat gloriae foo"

    def callback(self: CharmBase):
        container = self.unit.get_container("foo")
        if make_dirs:
            container.push("/foo/bar/baz.txt", text, make_dirs=make_dirs)
            # check that pulling immediately 'works'
            baz = container.pull("/foo/bar/baz.txt")
            assert baz.read() == text
        else:
            with pytest.raises(pebble.PathError):
                container.push("/foo/bar/baz.txt", text, make_dirs=make_dirs)

            # check that nothing was changed
            with pytest.raises((FileNotFoundError, pebble.PathError)):
                container.pull("/foo/bar/baz.txt")

    td = tempfile.TemporaryDirectory()
    state = State(
        containers=[
            Container(
                name="foo", can_connect=True, mounts={"foo": Mount("/foo", td.name)}
            )
        ]
    )

    out = trigger(
        state,
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )

    if make_dirs:
        file = out.get_container("foo").filesystem.open("/foo/bar/baz.txt")
        assert file.read() == text
    else:
        # nothing has changed
        out_purged = out.replace(stored_state=state.stored_state)
        assert not out_purged.jsonpatch_delta(state)


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
    def callback(self: CharmBase):
        container = self.unit.get_container("foo")
        proc = container.exec([cmd])
        proc.wait()
        assert proc.stdout.read() == "hello pebble"

    trigger(
        State(
            containers=[
                Container(
                    name="foo",
                    can_connect=True,
                    exec_mock={(cmd,): ExecOutput(stdout="hello pebble")},
                )
            ]
        ),
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event="start",
        post_event=callback,
    )


def test_pebble_ready(charm_cls):
    def callback(self: CharmBase):
        foo = self.unit.get_container("foo")
        assert foo.can_connect()

    container = Container(name="foo", can_connect=True)

    trigger(
        State(containers=[container]),
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event=container.pebble_ready_event,
        post_event=callback,
    )


@pytest.mark.parametrize("starting_service_status", pebble.ServiceStatus)
def test_pebble_plan(charm_cls, starting_service_status):
    def callback(self: CharmBase):
        foo = self.unit.get_container("foo")

        assert foo.get_plan().to_dict() == {
            "services": {"fooserv": {"startup": "enabled"}}
        }
        fooserv = foo.get_services("fooserv")["fooserv"]
        assert fooserv.startup == ServiceStartup.ENABLED
        assert fooserv.current == ServiceStatus.ACTIVE

        foo.add_layer(
            "bar",
            {
                "summary": "bla",
                "description": "deadbeef",
                "services": {"barserv": {"startup": "disabled"}},
            },
        )

        foo.replan()
        assert foo.get_plan().to_dict() == {
            "services": {
                "barserv": {"startup": "disabled"},
                "fooserv": {"startup": "enabled"},
            }
        }

        assert foo.get_service("barserv").current == starting_service_status
        foo.start("barserv")
        # whatever the original state, starting a service sets it to active
        assert foo.get_service("barserv").current == ServiceStatus.ACTIVE

    container = Container(
        name="foo",
        can_connect=True,
        layers={
            "foo": pebble.Layer(
                {
                    "summary": "bla",
                    "description": "deadbeef",
                    "services": {"fooserv": {"startup": "enabled"}},
                }
            )
        },
        service_status={
            "fooserv": pebble.ServiceStatus.ACTIVE,
            # todo: should we disallow setting status for services that aren't known YET?
            "barserv": starting_service_status,
        },
    )

    out = trigger(
        State(containers=[container]),
        charm_type=charm_cls,
        meta={"name": "foo", "containers": {"foo": {}}},
        event=container.pebble_ready_event,
        post_event=callback,
    )

    serv = lambda name, obj: pebble.Service(name, raw=obj)
    container = out.containers[0]
    assert container.plan.services == {
        "barserv": serv("barserv", {"startup": "disabled"}),
        "fooserv": serv("fooserv", {"startup": "enabled"}),
    }
    assert container.services["fooserv"].current == pebble.ServiceStatus.ACTIVE
    assert container.services["fooserv"].startup == pebble.ServiceStartup.ENABLED

    assert container.services["barserv"].current == pebble.ServiceStatus.ACTIVE
    assert container.services["barserv"].startup == pebble.ServiceStartup.DISABLED
