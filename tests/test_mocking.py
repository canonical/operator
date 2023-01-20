import dataclasses
from typing import Any, Callable, Dict, Tuple

import pytest

from scenario.mocking import DecorateSpec, patch_module
from scenario.structs import Event, Scene, State, _DCBase, relation


def mock_simulator(
    fn: Callable,
    namespace: str,
    tool_name: str,
    scene: "Scene",
    charm_spec: "CharmSpec",
    call_args: Tuple[Any, ...],
    call_kwargs: Dict[str, Any],
):
    assert namespace == "MyDemoClass"

    if tool_name == "get_foo":
        return scene.state.foo
    if tool_name == "set_foo":
        scene.state.foo = call_args[1]
        return
    raise RuntimeError()


@dataclasses.dataclass
class MockState(_DCBase):
    foo: int


@pytest.mark.parametrize("mock_foo", (42, 12, 20))
def test_patch_generic_module(mock_foo):
    state = MockState(foo=mock_foo)
    scene = Scene(state=state.copy(), event=Event("foo"))

    from tests.resources import demo_decorate_class

    patch_module(
        demo_decorate_class,
        {
            "MyDemoClass": {
                "get_foo": DecorateSpec(simulator=mock_simulator),
                "set_foo": DecorateSpec(simulator=mock_simulator),
            }
        },
        scene=scene,
    )

    from tests.resources.demo_decorate_class import MyDemoClass

    assert MyDemoClass._foo == 0
    assert MyDemoClass().get_foo() == mock_foo

    MyDemoClass().set_foo(12)
    assert MyDemoClass._foo == 0  # set_foo didn't "really" get called
    assert MyDemoClass().get_foo() == 12  # get_foo now returns the updated value

    assert state.foo == mock_foo  # initial state has original value


def test_patch_ops():
    state = State(
        relations=[
            relation(
                endpoint="dead",
                interface="beef",
                local_app_data={"foo": "bar"},
                local_unit_data={"foo": "wee"},
                remote_units_data={0: {"baz": "qux"}},
            )
        ]
    )
    scene = Scene(state=state.copy(), event=Event("foo"))

    from ops import model

    patch_module(
        model,
        {
            "_ModelBackend": {
                "relation_ids": DecorateSpec(),
                "relation_get": DecorateSpec(),
                "relation_set": DecorateSpec(),
            }
        },
        scene=scene,
    )

    mb = model._ModelBackend("foo", "bar", "baz")
    assert mb.relation_ids("dead") == [0]
    assert mb.relation_get(0, "local/0", False) == {"foo": "wee"}
    assert mb.relation_get(0, "local", True) == {"foo": "bar"}
    assert mb.relation_get(0, "remote/0", False) == {"baz": "qux"}
