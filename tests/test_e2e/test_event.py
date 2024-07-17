import ops
import pytest
from ops import CharmBase, StartEvent, UpdateStatusEvent

from scenario import Context
from scenario.state import Event, State, _CharmSpec, _EventType


@pytest.mark.parametrize(
    "evt, expected_type",
    (
        ("foo_relation_changed", _EventType.relation),
        ("foo_relation_created", _EventType.relation),
        ("foo_bar_baz_relation_created", _EventType.relation),
        ("foo_storage_attached", _EventType.storage),
        ("foo_storage_detaching", _EventType.storage),
        ("foo_bar_baz_storage_detaching", _EventType.storage),
        ("foo_pebble_ready", _EventType.workload),
        ("foo_bar_baz_pebble_ready", _EventType.workload),
        ("foo_pebble_custom_notice", _EventType.workload),
        ("foo_bar_baz_pebble_custom_notice", _EventType.workload),
        ("secret_remove", _EventType.secret),
        ("pre_commit", _EventType.framework),
        ("commit", _EventType.framework),
        ("collect_unit_status", _EventType.framework),
        ("collect_app_status", _EventType.framework),
        ("foo", _EventType.custom),
        ("kaboozle_bar_baz", _EventType.custom),
    ),
)
def test_event_type(evt, expected_type):
    event = Event(evt)
    assert event._path.type is expected_type

    assert event._is_relation_event is (expected_type is _EventType.relation)
    assert event._is_storage_event is (expected_type is _EventType.storage)
    assert event._is_workload_event is (expected_type is _EventType.workload)
    assert event._is_secret_event is (expected_type is _EventType.secret)
    assert event._is_action_event is (expected_type is _EventType.action)

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
    assert event._is_builtin_event(spec) is (expected_type is not _EventType.custom)


def test_emitted_framework():
    class MyCharm(CharmBase):
        META = {"name": "joop"}

    ctx = Context(MyCharm, meta=MyCharm.META, capture_framework_events=True)
    ctx.run("update-status", State())
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
    ctx.run("start", State(deferred=[Event("update-status").deferred(MyCharm._foo)]))

    assert len(ctx.emitted_events) == 5
    assert [e.handle.kind for e in ctx.emitted_events] == [
        "update_status",
        "start",
        "collect_unit_status",
        "pre_commit",
        "commit",
    ]
