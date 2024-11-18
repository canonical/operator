import ops
import pytest
from ops import CharmBase

from scenario import Context
from scenario.state import State, _CharmSpec, _Event, _EventType


@pytest.mark.parametrize(
    "evt, expected_type",
    (
        ("foo_relation_changed", _EventType.RELATION),
        ("foo_relation_created", _EventType.RELATION),
        ("foo_bar_baz_relation_created", _EventType.RELATION),
        ("foo_storage_attached", _EventType.STORAGE),
        ("foo_storage_detaching", _EventType.STORAGE),
        ("foo_bar_baz_storage_detaching", _EventType.STORAGE),
        ("foo_pebble_ready", _EventType.WORKLOAD),
        ("foo_bar_baz_pebble_ready", _EventType.WORKLOAD),
        ("foo_pebble_custom_notice", _EventType.WORKLOAD),
        ("foo_bar_baz_pebble_custom_notice", _EventType.WORKLOAD),
        ("secret_remove", _EventType.SECRET),
        ("pre_commit", _EventType.FRAMEWORK),
        ("commit", _EventType.FRAMEWORK),
        ("collect_unit_status", _EventType.FRAMEWORK),
        ("collect_app_status", _EventType.FRAMEWORK),
        ("foo", _EventType.CUSTOM),
        ("kaboozle_bar_baz", _EventType.CUSTOM),
    ),
)
def test_event_type(evt, expected_type):
    event = _Event(evt)
    assert event._path.type is expected_type

    assert event._is_relation_event is (expected_type is _EventType.RELATION)
    assert event._is_storage_event is (expected_type is _EventType.STORAGE)
    assert event._is_workload_event is (expected_type is _EventType.WORKLOAD)
    assert event._is_secret_event is (expected_type is _EventType.SECRET)
    assert event._is_action_event is (expected_type is _EventType.ACTION)

    class MyCharm(CharmBase):
        pass

    spec = _CharmSpec(
        MyCharm,
        meta={
            "requires": {
                "foo": {"interface": "bar"},
                "foo_bar_baz": {"interface": "bar"},
            },
            "storage": {
                "foo": {"type": "filesystem"},
                "foo_bar_baz": {"type": "filesystem"},
            },
            "containers": {"foo": {}, "foo_bar_baz": {}},
        },
    )
    assert event._is_builtin_event(spec) is (expected_type is not _EventType.CUSTOM)


def test_emitted_framework():
    class MyCharm(CharmBase):
        META = {"name": "joop"}

    ctx = Context(MyCharm, meta=MyCharm.META, capture_framework_events=True)
    ctx.run(ctx.on.update_status(), State())
    assert len(ctx.emitted_events) == 4
    assert list(map(type, ctx.emitted_events)) == [
        ops.UpdateStatusEvent,
        ops.CollectStatusEvent,
        ops.PreCommitEvent,
        ops.CommitEvent,
    ]


def test_emitted_deferred():
    class MyCharm(CharmBase):
        META = {"name": "joop"}

        def _foo(self, e):
            pass

    ctx = Context(
        MyCharm,
        meta=MyCharm.META,
        capture_deferred_events=True,
        capture_framework_events=True,
    )
    ctx.run(
        ctx.on.start(), State(deferred=[_Event("update-status").deferred(MyCharm._foo)])
    )

    assert len(ctx.emitted_events) == 5
    assert [e.handle.kind for e in ctx.emitted_events] == [
        "update_status",
        "start",
        "collect_unit_status",
        "pre_commit",
        "commit",
    ]
