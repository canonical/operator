# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import dataclasses
import datetime
import io
import pathlib
from typing import TYPE_CHECKING

import pytest
from scenario import Context
from scenario.state import CheckInfo, Container, Exec, Mount, Notice, State

import ops
from ops.log import _get_juju_log_and_app_id

from ..helpers import jsonpatch_delta, trigger  # type: ignore

if TYPE_CHECKING:
    from ops.pebble import LayerDict, ServiceDict


class Charm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        for evt in self.on.events().values():
            framework.observe(evt, self._on_event)

    def _on_event(self, event: ops.EventBase):
        pass


def test_no_containers():
    def callback(self: ops.CharmBase):
        assert not self.unit.containers

    trigger(
        State(),
        charm_type=Charm,
        meta={'name': 'foo'},
        event='start',
        post_event=callback,
    )


def test_containers_from_meta():
    def callback(self: ops.CharmBase):
        assert self.unit.containers
        assert self.unit.get_container('foo')

    trigger(
        State(),
        charm_type=Charm,
        meta={'name': 'foo', 'containers': {'foo': {}}},
        event='start',
        post_event=callback,
    )


@pytest.mark.parametrize('can_connect', (True, False))
def test_connectivity(can_connect: bool):
    def callback(self: ops.CharmBase):
        assert can_connect == self.unit.get_container('foo').can_connect()

    trigger(
        State(containers={Container(name='foo', can_connect=can_connect)}),
        charm_type=Charm,
        meta={'name': 'foo', 'containers': {'foo': {}}},
        event='start',
        post_event=callback,
    )


def test_fs_push(tmp_path: pathlib.Path):
    text = 'lorem ipsum/n alles amat gloriae foo'

    pth = tmp_path / 'textfile'
    pth.write_text(text)

    def callback(self: ops.CharmBase):
        container = self.unit.get_container('foo')
        baz = container.pull('/bar/baz.txt')
        assert baz.read() == text

    trigger(
        State(
            containers={
                Container(
                    name='foo',
                    can_connect=True,
                    mounts={'bar': Mount(location='/bar/baz.txt', source=pth)},
                )
            }
        ),
        charm_type=Charm,
        meta={'name': 'foo', 'containers': {'foo': {}}},
        event='start',
        post_event=callback,
    )


@pytest.mark.parametrize('make_dirs', (True, False))
def test_fs_pull(tmp_path: pathlib.Path, make_dirs: bool):
    text = 'lorem ipsum/n alles amat gloriae foo'

    def callback(self: ops.CharmBase):
        container = self.unit.get_container('foo')
        if make_dirs:
            container.push('/foo/bar/baz.txt', text, make_dirs=make_dirs)
            # check that pulling immediately 'works'
            baz = container.pull('/foo/bar/baz.txt')
            assert baz.read() == text
        else:
            with pytest.raises(ops.pebble.PathError):
                container.push('/foo/bar/baz.txt', text, make_dirs=make_dirs)

            # check that nothing was changed
            with pytest.raises((FileNotFoundError, ops.pebble.PathError)):
                container.pull('/foo/bar/baz.txt')

    container = Container(
        name='foo',
        can_connect=True,
        mounts={'foo': Mount(location='/foo', source=tmp_path)},
    )
    state = State(containers={container})

    ctx = Context(
        charm_type=Charm,
        meta={'name': 'foo', 'containers': {'foo': {}}},
    )
    with ctx(ctx.on.start(), state=state) as mgr:
        out = mgr.run()
        callback(mgr.charm)

    if make_dirs:
        # this is one way to retrieve the file
        file = tmp_path / 'bar' / 'baz.txt'

        # another is:
        base = pathlib.Path(out.get_container('foo').mounts['foo'].source)
        assert file == base / 'bar' / 'baz.txt'

        # but that is actually a symlink to the context's root tmp folder:
        base = pathlib.Path(ctx._tmp.name)
        assert (base / 'containers' / 'foo' / 'foo' / 'bar' / 'baz.txt').read_text() == text
        assert file.read_text() == text

        # shortcut for API niceness purposes:
        file = container.get_filesystem(ctx) / 'foo' / 'bar' / 'baz.txt'
        assert file.read_text() == text

    else:
        # nothing has changed
        out_purged = dataclasses.replace(out, stored_states=state.stored_states)
        assert not jsonpatch_delta(out_purged, state)


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
    'cmd, out',
    (
        ('ls', LS),
        ('ps', PS),
    ),
)
def test_exec(cmd: str, out: str):
    def callback(self: ops.CharmBase):
        container = self.unit.get_container('foo')
        proc = container.exec([cmd])
        proc.wait()
        assert proc.stdout is not None
        assert proc.stdout.read() == out

    trigger(
        State(
            containers={
                Container(
                    name='foo',
                    can_connect=True,
                    execs={Exec([cmd], stdout=out)},
                )
            }
        ),
        charm_type=Charm,
        meta={'name': 'foo', 'containers': {'foo': {}}},
        event='start',
        post_event=callback,
    )


class ExecCharm(ops.CharmBase):
    stdin: str | io.StringIO | None
    write: str | None

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.framework.observe(self.on.foo_pebble_ready, self._on_ready)

    def _on_ready(self, _: ops.EventBase):
        proc = self.unit.get_container('foo').exec(['ls'], stdin=self.stdin)
        if self.write:
            assert proc.stdin is not None
            proc.stdin.write(self.write)
        proc.wait()


@pytest.mark.parametrize(
    'stdin,write',
    (
        [None, 'hello world!'],
        ['hello world!', None],
        [io.StringIO('hello world!'), None],
    ),
)
def test_exec_history_stdin(
    monkeypatch: pytest.MonkeyPatch, stdin: str | io.StringIO | None, write: str | None
):
    monkeypatch.setattr(ExecCharm, 'stdin', stdin, raising=False)
    monkeypatch.setattr(ExecCharm, 'write', write, raising=False)
    ctx = Context(ExecCharm, meta={'name': 'foo', 'containers': {'foo': {}}})
    container = Container(name='foo', can_connect=True, execs={Exec([])})
    ctx.run(ctx.on.pebble_ready(container=container), State(containers={container}))
    assert ctx.exec_history[container.name][0].stdin == 'hello world!'


def test_pebble_ready():
    def callback(self: ops.CharmBase):
        foo = self.unit.get_container('foo')
        assert foo.can_connect()

    container = Container(name='foo', can_connect=True)

    trigger(
        State(containers={container}),
        charm_type=Charm,
        meta={'name': 'foo', 'containers': {'foo': {}}},
        event='pebble_ready',
        post_event=callback,
    )


class PlanCharm(ops.CharmBase):
    starting_service_status: ops.pebble.ServiceStatus

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_ready, self._on_ready)

    def _on_ready(self, event: ops.PebbleReadyEvent):
        foo = event.workload

        assert foo.get_plan().to_dict() == {'services': {'fooserv': {'startup': 'enabled'}}}
        fooserv = foo.get_services('fooserv')['fooserv']
        assert fooserv.startup == ops.pebble.ServiceStartup.ENABLED
        assert fooserv.current == ops.pebble.ServiceStatus.ACTIVE

        foo.add_layer(
            'bar',
            {
                'summary': 'bla',
                'description': 'deadbeef',
                'services': {'barserv': {'startup': 'disabled'}},
            },
        )

        foo.replan()
        assert foo.get_plan().to_dict() == {
            'services': {
                'barserv': {'startup': 'disabled'},
                'fooserv': {'startup': 'enabled'},
            }
        }

        assert foo.get_service('barserv').current == self.starting_service_status
        foo.start('barserv')
        # whatever the original state, starting a service sets it to active
        assert foo.get_service('barserv').current == ops.pebble.ServiceStatus.ACTIVE


@pytest.mark.parametrize('starting_service_status', ops.pebble.ServiceStatus)
def test_pebble_plan(
    monkeypatch: pytest.MonkeyPatch, starting_service_status: ops.pebble.ServiceStatus
):
    monkeypatch.setattr(
        PlanCharm, 'starting_service_status', starting_service_status, raising=False
    )

    container = Container(
        name='foo',
        can_connect=True,
        layers={
            'foo': ops.pebble.Layer({
                'summary': 'bla',
                'description': 'deadbeef',
                'services': {'fooserv': {'startup': 'enabled'}},
            })
        },
        service_statuses={
            'fooserv': ops.pebble.ServiceStatus.ACTIVE,
            # todo: should we disallow setting status for services that aren't known YET?
            'barserv': starting_service_status,
        },
    )

    out = trigger(
        State(containers={container}),
        charm_type=PlanCharm,
        meta={'name': 'foo', 'containers': {'foo': {}}},
        event='pebble_ready',
    )

    def serv(name: str, obj: ServiceDict) -> ops.pebble.Service:
        return ops.pebble.Service(name, raw=obj)

    container = out.get_container(container.name)
    assert container.plan.services == {
        'barserv': serv('barserv', {'startup': 'disabled'}),
        'fooserv': serv('fooserv', {'startup': 'enabled'}),
    }
    assert container.services['fooserv'].current == ops.pebble.ServiceStatus.ACTIVE
    assert container.services['fooserv'].startup == ops.pebble.ServiceStartup.ENABLED

    assert container.services['barserv'].current == ops.pebble.ServiceStatus.ACTIVE
    assert container.services['barserv'].startup == ops.pebble.ServiceStartup.DISABLED


def test_exec_wait_error():
    state = State(
        containers={
            Container(
                name='foo',
                can_connect=True,
                execs={Exec(['foo'], stdout='hello pebble', return_code=1)},
            )
        }
    )

    ctx = Context(Charm, meta={'name': 'foo', 'containers': {'foo': {}}})
    with ctx(ctx.on.start(), state) as mgr:
        container = mgr.charm.unit.get_container('foo')
        proc = container.exec(['foo'])
        with pytest.raises(ops.pebble.ExecError) as exc_info:  # type: ignore
            proc.wait_output()
        assert exc_info.value.stdout == 'hello pebble'  # type: ignore


@pytest.mark.parametrize('command', (['foo'], ['foo', 'bar'], ['foo', 'bar', 'baz']))
def test_exec_wait_output(command: list[str]):
    state = State(
        containers={
            Container(
                name='foo',
                can_connect=True,
                execs={Exec(['foo'], stdout='hello pebble', stderr='oepsie')},
            )
        }
    )

    ctx = Context(Charm, meta={'name': 'foo', 'containers': {'foo': {}}})
    with ctx(ctx.on.start(), state) as mgr:
        container = mgr.charm.unit.get_container('foo')
        proc = container.exec(command)
        out, err = proc.wait_output()
        assert out == 'hello pebble'
        assert err == 'oepsie'
        assert ctx.exec_history[container.name][0].command == command


def test_exec_wait_output_error():
    state = State(
        containers={
            Container(
                name='foo',
                can_connect=True,
                execs={Exec(['foo'], stdout='hello pebble', return_code=1)},
            )
        }
    )

    ctx = Context(Charm, meta={'name': 'foo', 'containers': {'foo': {}}})
    with ctx(ctx.on.start(), state) as mgr:
        container = mgr.charm.unit.get_container('foo')
        proc = container.exec(['foo'])
        with pytest.raises(ops.pebble.ExecError):
            proc.wait_output()


def test_pebble_custom_notice():
    notices = [
        Notice(key='example.com/foo'),
        Notice(key='example.com/bar', last_data={'a': 'b'}),
        Notice(key='example.com/baz', occurrences=42),
    ]
    container = Container(
        name='foo',
        can_connect=True,
        notices=notices,
    )

    state = State(containers=[container])
    ctx = Context(Charm, meta={'name': 'foo', 'containers': {'foo': {}}})
    with ctx(ctx.on.pebble_custom_notice(container=container, notice=notices[-1]), state) as mgr:
        container = mgr.charm.unit.get_container('foo')
        assert container.get_notices() == [n._to_ops() for n in notices]


class CustomNoticeCharm(ops.CharmBase):
    key: str
    data: dict[str, str]
    user_id: int
    first_occurred: datetime.datetime
    last_occurred: datetime.datetime
    last_repeated: datetime.datetime
    occurrences: int
    repeat_after: datetime.timedelta
    expire_after: datetime.timedelta

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_custom_notice, self._on_custom_notice)

    def _on_custom_notice(self, event: ops.PebbleCustomNoticeEvent):
        notice = event.notice
        assert notice.type == ops.pebble.NoticeType.CUSTOM
        assert notice.key == self.key
        assert notice.last_data == self.data
        assert notice.user_id == self.user_id
        assert notice.first_occurred == self.first_occurred
        assert notice.last_occurred == self.last_occurred
        assert notice.last_repeated == self.last_repeated
        assert notice.occurrences == self.occurrences
        assert notice.repeat_after == self.repeat_after
        assert notice.expire_after == self.expire_after


def test_pebble_custom_notice_in_charm(monkeypatch: pytest.MonkeyPatch):
    key = 'example.com/test/charm'
    data = {'foo': 'bar'}
    user_id = 100
    first_occurred = datetime.datetime(1979, 1, 25, 11, 0, 0)
    last_occurred = datetime.datetime(2006, 8, 28, 13, 28, 0)
    last_repeated = datetime.datetime(2023, 9, 4, 9, 0, 0)
    occurrences = 42
    repeat_after = datetime.timedelta(days=7)
    expire_after = datetime.timedelta(days=365)

    monkeypatch.setattr(CustomNoticeCharm, 'key', key, raising=False)
    monkeypatch.setattr(CustomNoticeCharm, 'data', data, raising=False)
    monkeypatch.setattr(CustomNoticeCharm, 'user_id', user_id, raising=False)
    monkeypatch.setattr(CustomNoticeCharm, 'first_occurred', first_occurred, raising=False)
    monkeypatch.setattr(CustomNoticeCharm, 'last_occurred', last_occurred, raising=False)
    monkeypatch.setattr(CustomNoticeCharm, 'last_repeated', last_repeated, raising=False)
    monkeypatch.setattr(CustomNoticeCharm, 'occurrences', occurrences, raising=False)
    monkeypatch.setattr(CustomNoticeCharm, 'repeat_after', repeat_after, raising=False)
    monkeypatch.setattr(CustomNoticeCharm, 'expire_after', expire_after, raising=False)

    notices = [
        Notice('example.com/test/other'),
        Notice('example.org/test/charm', last_data={'foo': 'baz'}),
        Notice(
            key,
            last_data=data,
            user_id=user_id,
            first_occurred=first_occurred,
            last_occurred=last_occurred,
            last_repeated=last_repeated,
            occurrences=occurrences,
            repeat_after=repeat_after,
            expire_after=expire_after,
        ),
    ]
    container = Container(
        name='foo',
        can_connect=True,
        notices=notices,
    )
    state = State(containers=[container])
    ctx = Context(CustomNoticeCharm, meta={'name': 'foo', 'containers': {'foo': {}}})
    ctx.run(ctx.on.pebble_custom_notice(container=container, notice=notices[-1]), state)


class CheckFailedCharm(ops.CharmBase):
    infos: list[ops.LazyCheckInfo]

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_check_failed, self._on_check_failed)

    def _on_check_failed(self, event: ops.PebbleCheckFailedEvent):
        self.infos.append(event.info)


@pytest.fixture
def capture_info_failure_charm(monkeypatch: pytest.MonkeyPatch) -> type[CheckFailedCharm]:
    monkeypatch.setattr(CheckFailedCharm, 'infos', [], raising=False)
    return CheckFailedCharm


def test_pebble_check_failed(capture_info_failure_charm: CheckFailedCharm):
    ctx: Context[CheckFailedCharm] = Context(
        capture_info_failure_charm, meta={'name': 'foo', 'containers': {'foo': {}}}
    )
    layer = ops.pebble.Layer({
        'checks': {'http-check': {'override': 'replace', 'startup': 'enabled', 'threshold': 3}}
    })
    assert layer.checks['http-check'].threshold is not None
    check = CheckInfo(
        'http-check',
        successes=3,
        failures=7,
        status=ops.pebble.CheckStatus.DOWN,
        level=ops.pebble.CheckLevel(layer.checks['http-check'].level),
        startup=ops.pebble.CheckStartup(layer.checks['http-check'].startup),
        threshold=layer.checks['http-check'].threshold,
    )
    container = Container('foo', check_infos={check}, layers={'layer1': layer})
    state = State(containers={container})
    ctx.run(ctx.on.pebble_check_failed(container, check), state=state)
    infos = capture_info_failure_charm.infos
    assert len(infos) == 1
    assert infos[0].name == 'http-check'
    assert infos[0].status == ops.pebble.CheckStatus.DOWN
    assert infos[0].successes == 3
    assert infos[0].failures == 7


class CheckRecoveredCharm(ops.CharmBase):
    infos: list[ops.LazyCheckInfo]

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_check_recovered, self._on_check_recovered)

    def _on_check_recovered(self, event: ops.PebbleCheckRecoveredEvent):
        self.infos.append(event.info)


@pytest.fixture
def capture_info_recovered_charm(monkeypatch: pytest.MonkeyPatch) -> type[CheckRecoveredCharm]:
    monkeypatch.setattr(CheckRecoveredCharm, 'infos', [], raising=False)
    return CheckRecoveredCharm


def test_pebble_check_recovered(capture_info_recovered_charm: CheckRecoveredCharm):
    ctx = Context(capture_info_recovered_charm, meta={'name': 'foo', 'containers': {'foo': {}}})
    layer = ops.pebble.Layer({
        'checks': {'http-check': {'override': 'replace', 'startup': 'enabled', 'threshold': 3}}
    })
    assert layer.checks['http-check'].threshold is not None
    check = CheckInfo(
        'http-check',
        successes=None,
        status=ops.pebble.CheckStatus.UP,
        level=ops.pebble.CheckLevel(layer.checks['http-check'].level),
        startup=ops.pebble.CheckStartup(layer.checks['http-check'].startup),
        threshold=layer.checks['http-check'].threshold,
    )
    container = Container('foo', check_infos={check}, layers={'layer1': layer})
    state = State(containers={container})
    ctx.run(ctx.on.pebble_check_recovered(container, check), state=state)
    infos = capture_info_recovered_charm.infos
    assert len(infos) == 1
    assert infos[0].name == 'http-check'
    assert infos[0].status == ops.pebble.CheckStatus.UP
    assert infos[0].successes is None
    assert infos[0].failures == 0


class DoubleCharm(ops.CharmBase):
    foo_infos: list[ops.LazyCheckInfo]
    bar_infos: list[ops.LazyCheckInfo]

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_check_failed, self._on_foo_check_failed)
        framework.observe(self.on.bar_pebble_check_failed, self._on_bar_check_failed)

    def _on_foo_check_failed(self, event: ops.PebbleCheckFailedEvent):
        self.foo_infos.append(event.info)

    def _on_bar_check_failed(self, event: ops.PebbleCheckFailedEvent):
        self.bar_infos.append(event.info)


@pytest.fixture
def capture_info_double_charm(monkeypatch: pytest.MonkeyPatch) -> type[DoubleCharm]:
    monkeypatch.setattr(DoubleCharm, 'foo_infos', [], raising=False)
    monkeypatch.setattr(DoubleCharm, 'bar_infos', [], raising=False)
    return DoubleCharm


def test_pebble_check_failed_two_containers(capture_info_recovered_charm: DoubleCharm):
    ctx = Context(
        capture_info_recovered_charm, meta={'name': 'foo', 'containers': {'foo': {}, 'bar': {}}}
    )

    layer = ops.pebble.Layer({
        'checks': {'http-check': {'override': 'replace', 'startup': 'enabled', 'threshold': 3}}
    })
    assert layer.checks['http-check'].threshold is not None
    check = CheckInfo(
        'http-check',
        failures=7,
        status=ops.pebble.CheckStatus.DOWN,
        level=ops.pebble.CheckLevel(layer.checks['http-check'].level),
        startup=ops.pebble.CheckStartup(layer.checks['http-check'].startup),
        threshold=layer.checks['http-check'].threshold,
    )
    foo_container = Container('foo', check_infos={check}, layers={'layer1': layer})
    bar_container = Container('bar', check_infos={check}, layers={'layer1': layer})
    state = State(containers={foo_container, bar_container})
    ctx.run(ctx.on.pebble_check_failed(foo_container, check), state=state)
    foo_infos = DoubleCharm.foo_infos
    bar_infos = DoubleCharm.bar_infos
    assert len(foo_infos) == 1
    assert foo_infos[0].name == 'http-check'
    assert foo_infos[0].status == ops.pebble.CheckStatus.DOWN
    assert foo_infos[0].successes == 0
    assert foo_infos[0].failures == 7
    assert len(bar_infos) == 0


class LayerCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_ready, self._on_foo_ready)

    def _on_foo_ready(self, _: ops.EventBase):
        self.unit.get_container('foo').add_layer(
            'foo',
            {'checks': {'chk1': {'override': 'replace'}}},
        )


def test_pebble_add_layer():
    ctx = Context(LayerCharm, meta={'name': 'foo', 'containers': {'foo': {}}})
    container = Container('foo', can_connect=True)
    state_out = ctx.run(ctx.on.pebble_ready(container), state=State(containers={container}))
    chk1_info = state_out.get_container('foo').get_check_info('chk1')
    assert chk1_info.status == ops.pebble.CheckStatus.UP


class StartCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.foo_pebble_ready, self._on_foo_ready)
        framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_foo_ready(self, _: ops.EventBase):
        container = self.unit.get_container('foo')
        container.add_layer(
            'foo',
            {
                'checks': {
                    'chk1': {
                        'override': 'replace',
                        'startup': 'disabled',
                        'threshold': 3,
                    }
                }
            },
        )

    def _on_config_changed(self, _: ops.EventBase):
        container = self.unit.get_container('foo')
        container.start_checks('chk1')


def test_pebble_start_check():
    ctx = Context(StartCharm, meta={'name': 'foo', 'containers': {'foo': {}}})
    container = Container('foo', can_connect=True)

    # Ensure that it starts as inactive.
    state_out = ctx.run(ctx.on.pebble_ready(container), state=State(containers={container}))
    chk1_info = state_out.get_container('foo').get_check_info('chk1')
    assert chk1_info.status == ops.pebble.CheckStatus.INACTIVE

    # Verify that start_checks works.
    state_out = ctx.run(ctx.on.config_changed(), state=state_out)
    chk1_info = state_out.get_container('foo').get_check_info('chk1')
    assert chk1_info.status == ops.pebble.CheckStatus.UP


@pytest.fixture
def reset_security_logging():
    """Ensure that we get a fresh juju-log for the security logging."""
    _get_juju_log_and_app_id.cache_clear()
    yield
    _get_juju_log_and_app_id.cache_clear()


class StopCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_config_changed(self, _: ops.EventBase):
        container = self.unit.get_container('foo')
        container.stop_checks('chk1')


def test_pebble_stop_check(reset_security_logging: None):
    ctx = Context(StopCharm, meta={'name': 'foo', 'containers': {'foo': {}}})

    layer = ops.pebble.Layer({
        'checks': {'chk1': {'override': 'replace', 'startup': 'enabled', 'threshold': 3}}
    })
    assert layer.checks['chk1'].threshold is not None
    info_in = CheckInfo(
        'chk1',
        status=ops.pebble.CheckStatus.UP,
        level=ops.pebble.CheckLevel(layer.checks['chk1'].level),
        startup=ops.pebble.CheckStartup(layer.checks['chk1'].startup),
        threshold=layer.checks['chk1'].threshold,
    )
    container = Container(
        'foo',
        can_connect=True,
        check_infos=frozenset({info_in}),
        layers={'layer1': layer},
    )
    state_out = ctx.run(ctx.on.config_changed(), state=State(containers={container}))
    info_out = state_out.get_container('foo').get_check_info('chk1')
    assert info_out.status == ops.pebble.CheckStatus.INACTIVE


class ReplanCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_config_changed(self, _: ops.EventBase):
        container = self.unit.get_container('foo')
        container.replan()


def test_pebble_replan_checks():
    ctx = Context(ReplanCharm, meta={'name': 'foo', 'containers': {'foo': {}}})
    layer = ops.pebble.Layer({
        'checks': {'chk1': {'override': 'replace', 'startup': 'enabled', 'threshold': 3}}
    })
    assert layer.checks['chk1'].threshold is not None
    info_in = CheckInfo(
        'chk1',
        status=ops.pebble.CheckStatus.INACTIVE,
        level=ops.pebble.CheckLevel(layer.checks['chk1'].level),
        startup=ops.pebble.CheckStartup(layer.checks['chk1'].startup),
        threshold=layer.checks['chk1'].threshold,
    )
    container = Container(
        'foo',
        can_connect=True,
        check_infos=frozenset({info_in}),
        layers={'layer1': layer},
    )
    state_out = ctx.run(ctx.on.config_changed(), state=State(containers={container}))
    info_out = state_out.get_container('foo').get_check_info('chk1')
    assert info_out.status == ops.pebble.CheckStatus.UP


class CombineLayerCharm(ops.CharmBase):
    layer_name: str
    layer_dict: LayerDict
    combine: bool

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['my-container'].pebble_ready, self._on_pebble_ready)

    def _on_pebble_ready(self, _: ops.PebbleReadyEvent):
        container = self.unit.get_container('my-container')
        container.add_layer(
            self.layer_name, ops.pebble.Layer(self.layer_dict), combine=self.combine
        )


@pytest.mark.parametrize(
    'combine,new_layer_name',
    [
        (False, 'new-layer'),
        (True, 'base'),
    ],
)
@pytest.mark.parametrize(
    'new_layer_dict',
    [
        {
            'checks': {
                'server-ready': {
                    'override': 'merge',
                    'level': 'ready',
                    'http': {'url': 'http://localhost:5050/version'},
                }
            }
        },
        {
            'checks': {
                'server-ready': {
                    'override': 'merge',
                    'level': 'alive',
                    'threshold': 30,
                    'startup': 'disabled',
                    'http': {'url': 'http://localhost:5050/version'},
                }
            }
        },
    ],
)
def test_add_layer_merge_check(
    monkeypatch: pytest.MonkeyPatch, new_layer_name: str, combine: bool, new_layer_dict: LayerDict
):
    monkeypatch.setattr(CombineLayerCharm, 'layer_name', new_layer_name, raising=False)
    monkeypatch.setattr(CombineLayerCharm, 'layer_dict', new_layer_dict, raising=False)
    monkeypatch.setattr(CombineLayerCharm, 'combine', combine, raising=False)

    ctx = Context(CombineLayerCharm, meta={'name': 'foo', 'containers': {'my-container': {}}})
    layer_in = ops.pebble.Layer({
        'checks': {
            'server-ready': {
                'override': 'replace',
                'level': 'ready',
                'startup': 'enabled',
                'threshold': 10,
                'http': {'url': 'http://localhost:5000/version'},
            }
        }
    })
    assert layer_in.checks['server-ready'].threshold is not None
    check_in = CheckInfo(
        'server-ready',
        level=ops.pebble.CheckLevel(layer_in.checks['server-ready'].level),
        threshold=layer_in.checks['server-ready'].threshold,
        startup=ops.pebble.CheckStartup(layer_in.checks['server-ready'].startup),
    )
    container_in = Container(
        'my-container',
        can_connect=True,
        layers={'base': layer_in},
        check_infos={check_in},
    )
    assert container_in.get_check_info('server-ready').level == ops.pebble.CheckLevel.READY
    state_in = State(containers={container_in})

    state_out = ctx.run(ctx.on.pebble_ready(container_in), state_in)

    check_out = state_out.get_container(container_in.name).get_check_info('server-ready')
    new_layer_check = new_layer_dict.get('checks', {}).get('server-ready', {})
    assert check_out.level == ops.pebble.CheckLevel(new_layer_check.get('level', 'ready'))
    assert check_out.startup == ops.pebble.CheckStartup(new_layer_check.get('startup', 'enabled'))
    assert check_out.threshold == new_layer_check.get('threshold', 10)


@pytest.mark.parametrize('layer1_name,layer2_name', [('a-base', 'b-base'), ('b-base', 'a-base')])
def test_layers_merge_in_plan(layer1_name: str, layer2_name: str):
    layer1_dict: LayerDict = {
        'services': {
            'server': {
                'override': 'replace',
                'command': '/bin/sleep 10',
                'summary': 'sum',
                'description': 'desc',
                'startup': 'enabled',
            },
        },
        'checks': {
            'server-ready': {
                'override': 'replace',
                'level': 'ready',
                'startup': 'enabled',
                'threshold': 10,
                'period': '1s',
                'timeout': '28s',
                'http': {'url': 'http://localhost:5000/version'},
            }
        },
        'log-targets': {
            'loki': {
                'override': 'replace',
                'type': 'loki',
                'location': 'https://loki.example.com',
                'services': ['server'],
                'labels': {'foo': 'bar'},
            }
        },
    }
    layer2_dict: LayerDict = {
        'services': {
            'server': {
                'override': 'merge',
                'command': '/bin/sleep 20',
            }
        },
        'checks': {
            'server-ready': {
                'override': 'merge',
                'level': 'alive',
                'http': {'url': 'http://localhost:5050/version'},
            }
        },
        'log-targets': {
            'loki': {
                'override': 'merge',
                'location': 'https://loki2.example.com',
            },
        },
    }
    layer1 = ops.pebble.Layer(layer1_dict)
    layer2 = ops.pebble.Layer(layer2_dict)

    ctx = Context(ops.CharmBase, meta={'name': 'foo', 'containers': {'my-container': {}}})
    # TODO also a starting layer.
    container = Container('my-container', can_connect=True)

    with ctx(ctx.on.update_status(), State(containers={container})) as mgr:
        mgr.charm.unit.get_container('my-container').add_layer(layer1_name, layer1)
        mgr.charm.unit.get_container('my-container').add_layer(layer2_name, layer2)
        state_out = mgr.run()

    plan = state_out.get_container(container.name).plan

    service = plan.services['server']
    assert service.summary == 'sum'
    assert service.description == 'desc'
    # Service.startup is always a string, even though we have the enum.
    assert service.startup == ops.pebble.ServiceStartup.ENABLED.value
    assert service.override == 'merge'
    assert service.command == '/bin/sleep 20'

    check = plan.checks['server-ready']
    assert check.startup == ops.pebble.CheckStartup.ENABLED
    assert check.threshold == 10
    assert check.period == '1s'
    assert check.timeout == '28s'
    assert check.override == 'merge'
    assert check.level == ops.pebble.CheckLevel.ALIVE
    http = check.http
    assert http is not None
    assert http.get('url') == 'http://localhost:5050/version'

    log_target = plan.log_targets['loki']
    assert log_target.type == 'loki'
    assert log_target.services == ['server']
    assert log_target.labels == {'foo': 'bar'}
    assert log_target.override == 'merge'
    assert log_target.location == 'https://loki2.example.com'
