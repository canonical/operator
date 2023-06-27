#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from collections import namedtuple
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Type, Union

from ops import EventBase

from scenario.logger import logger as scenario_logger
from scenario.runtime import Runtime
from scenario.state import Action, Event, _CharmSpec

if TYPE_CHECKING:
    from pathlib import Path

    from ops.testing import CharmType

    from scenario.state import JujuLogLine, State, _EntityStatus

    PathLike = Union[str, Path]

logger = scenario_logger.getChild("runtime")

ActionOutput = namedtuple("ActionOutput", ("state", "logs", "results", "failure"))


class InvalidEventError(RuntimeError):
    """raised when something is wrong with the event passed to Context.run_*"""


class InvalidActionError(InvalidEventError):
    """raised when something is wrong with the action passed to Context.run_action"""


class Context:
    """Scenario test execution context."""

    def __init__(
        self,
        charm_type: Type["CharmType"],
        meta: Optional[Dict[str, Any]] = None,
        actions: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        charm_root: "PathLike" = None,
        juju_version: str = "3.0",
    ):
        """Initializer.

        :arg charm_type: the CharmBase subclass to call ``ops.main()`` on.
        :arg meta: charm metadata to use. Needs to be a valid metadata.yaml format (as a dict).
            If none is provided, we will search for a ``metadata.yaml`` file in the charm root.
        :arg actions: charm actions to use. Needs to be a valid actions.yaml format (as a dict).
            If none is provided, we will search for a ``actions.yaml`` file in the charm root.
        :arg config: charm config to use. Needs to be a valid config.yaml format (as a dict).
            If none is provided, we will search for a ``config.yaml`` file in the charm root.
        :arg juju_version: Juju agent version to simulate.
        :arg charm_root: virtual charm root the charm will be executed with.
            If the charm, say, expects a `./src/foo/bar.yaml` file present relative to the
            execution cwd, you need to use this. E.g.:

            >>> import scenario
            >>> import tempfile
            >>> virtual_root = tempfile.TemporaryDirectory()
            >>> local_path = Path(local_path.name)
            >>> (local_path / 'foo').mkdir()
            >>> (local_path / 'foo' / 'bar.yaml').write_text('foo: bar')
            >>> scenario.Context(... charm_root=virtual_root).run(...)

        """

        if not any((meta, actions, config)):
            logger.debug("Autoloading charmspec...")
            spec = _CharmSpec.autoload(charm_type)
        else:
            if not meta:
                meta = {"name": str(charm_type.__name__)}
            spec = _CharmSpec(
                charm_type=charm_type,
                meta=meta,
                actions=actions,
                config=config,
            )

        self.charm_spec = spec
        self.charm_root = charm_root
        self.juju_version = juju_version

        # streaming side effects from running an event
        self.juju_log: List["JujuLogLine"] = []
        self.app_status_history: List["_EntityStatus"] = []
        self.unit_status_history: List["_EntityStatus"] = []
        self.workload_version_history: List[str] = []
        self.emitted_events: List[EventBase] = []

        # ephemeral side effects from running an action
        self._action_logs = []
        self._action_results = None
        self._action_failure = ""

    def clear(self):
        """Cleanup side effects histories."""
        self.juju_log = []
        self.app_status_history = []
        self.unit_status_history = []
        self.workload_version_history = []
        self.emitted_events = []
        self._action_logs = []
        self._action_results = None
        self._action_failure = ""

    def _record_status(self, state: "State", is_app: bool):
        """Record the previous status before a status change."""
        if is_app:
            self.app_status_history.append(state.app_status)
        else:
            self.unit_status_history.append(state.unit_status)

    def run(
        self,
        event: Union["Event", str],
        state: "State",
        pre_event: Optional[Callable[["CharmType"], None]] = None,
        post_event: Optional[Callable[["CharmType"], None]] = None,
    ) -> "State":
        """Trigger a charm execution with an Event and a State.

        Calling this function will call ``ops.main`` and set up the context according to the
        specified ``State``, then emit the event on the charm.

        :arg event: the Event that the charm will respond to. Can be a string or an Event instance.
        :arg state: the State instance to use as data source for the hook tool calls that the
            charm will invoke when handling the Event.
        :arg pre_event: callback to be invoked right before emitting the event on the newly
            instantiated charm. Will receive the charm instance as only positional argument.
        :arg post_event: callback to be invoked right after emitting the event on the charm.
            Will receive the charm instance as only positional argument.
        """
        """Validate the event and cast to Event."""
        if isinstance(event, str):
            event = Event(event)

        if not isinstance(event, Event):
            raise InvalidEventError(f"Expected Event | str, got {type(event)}")

        if event._is_action_event:
            raise InvalidEventError(
                "Cannot Context.run() action events. "
                "Use Context.run_action instead.",
            )

        return self._run(
            event,
            state=state,
            pre_event=pre_event,
            post_event=post_event,
        )

    def run_action(
        self,
        action: Union["Action", str],
        state: "State",
        pre_event: Optional[Callable[["CharmType"], None]] = None,
        post_event: Optional[Callable[["CharmType"], None]] = None,
    ) -> ActionOutput:
        """Trigger a charm execution with an Action and a State.

        Calling this function will call ``ops.main`` and set up the context according to the
        specified ``State``, then emit the event on the charm.

        :arg action: the Action that the charm will execute. Can be a string or an Action instance.
        :arg state: the State instance to use as data source for the hook tool calls that the
            charm will invoke when handling the Action (event).
        :arg pre_event: callback to be invoked right before emitting the event on the newly
            instantiated charm. Will receive the charm instance as only positional argument.
        :arg post_event: callback to be invoked right after emitting the event on the charm.
            Will receive the charm instance as only positional argument.
        """

        if isinstance(action, str):
            action = Action(action)

        if not isinstance(action, Action):
            raise InvalidActionError(
                f"Expected Action or action name; got {type(action)}",
            )

        state_out = self._run(
            action.event,
            state=state,
            pre_event=pre_event,
            post_event=post_event,
        )

        ao = ActionOutput(
            state_out,
            self._action_logs,
            self._action_results,
            self._action_failure,
        )

        # reset all action-related state
        self._action_logs = []
        self._action_results = None
        self._action_failure = ""

        return ao

    def _run(
        self,
        event: "Event",
        state: "State",
        pre_event: Optional[Callable[["CharmType"], None]] = None,
        post_event: Optional[Callable[["CharmType"], None]] = None,
    ) -> "State":
        runtime = Runtime(
            charm_spec=self.charm_spec,
            juju_version=self.juju_version,
            charm_root=self.charm_root,
        )

        return runtime.exec(
            state=state,
            event=event,
            pre_event=pre_event,
            post_event=post_event,
            context=self,
        )
