# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from scenario.context import Context
from scenario.state import CheckInfo, Container, State

import ops


def test_check_info_defaults():
    """The custom __init__ sets the expected default values."""
    check_info = CheckInfo(name='Mairon')
    assert check_info.name == 'Mairon'
    assert check_info.level is ops.pebble.CheckLevel.UNSET
    assert check_info.startup is ops.pebble.CheckStartup.ENABLED
    assert check_info.status is ops.pebble.CheckStatus.UP
    assert check_info.successes == 0
    assert check_info.failures == 0
    assert check_info.threshold == 3
    assert check_info.change_id is not None
    assert isinstance(check_info.change_id, ops.pebble.ChangeID)


@pytest.mark.parametrize(('level'), ['', 'alive', 'ready'])
def test_check_info_good_level_converted(level: str):
    """A valid level string is converted to the CheckLevel enum."""
    check_info = CheckInfo(name='Fëanor', level=level)
    assert check_info.level is ops.pebble.CheckLevel(level)


def test_check_info_level_none_is_unset():
    """None is the same as not passing a level, as it is for the state comparison."""
    assert CheckInfo(name='Beren', level=None).level is ops.pebble.CheckLevel.UNSET


def test_check_info_unset_level_seen_by_charm():
    """A charm sees the same level as with real Pebble, and the state is unchanged."""
    levels: list[ops.pebble.CheckLevel | str | None] = []

    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.update_status, self._on_update_status)

        def _on_update_status(self, _: ops.UpdateStatusEvent):
            checks = self.unit.get_container('foo').get_checks()
            levels.extend(info.level for info in checks.values())

    layer = ops.pebble.Layer({
        'checks': {'chk': {'override': 'replace', 'exec': {'command': 'true'}}}
    })
    check_info = CheckInfo(name='chk')
    container = Container('foo', can_connect=True, layers={'l': layer}, check_infos={check_info})
    ctx = Context(MyCharm, meta={'name': 'foo', 'containers': {'foo': {}}})

    state_out = ctx.run(ctx.on.update_status(), State(containers={container}))

    assert levels == [ops.pebble.CheckLevel.UNSET]
    assert state_out.get_container('foo').get_check_info('chk') == check_info


def test_check_info_bad_level():
    """An invalid level value raises a ValueError, and the type checker complains."""
    with pytest.raises(ValueError):
        CheckInfo(name='Melkor', level=1)  # type: ignore


def test_check_info_bad_startup_and_status():
    """Bad startup and status values are allowed at runtime, but the type checker complains."""
    check_info = CheckInfo(
        name='Maedhros',
        startup='bad',  # type: ignore
        status='worse',  # type: ignore
    )
    assert check_info.startup == 'bad'
    assert check_info.status == 'worse'


def test_check_info_threshold_none():
    """A bad threshold value of None is allowed at runtime, but the type checker complains."""
    check_info = CheckInfo(
        name='Fingon',
        threshold=None,  # type: ignore
    )
    assert check_info.threshold is None
