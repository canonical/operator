import pytest
from ops import CharmBase

from scenario.state import _EventType, Event, _CharmSpec


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
        ("secret_removed", _EventType.secret),
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
