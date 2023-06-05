#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import typing
from contextlib import contextmanager
from typing import ContextManager, List, Type, TypeVar

from ops.framework import (
    CommitEvent,
    EventBase,
    Framework,
    Handle,
    NoTypeError,
    PreCommitEvent,
)

_T = TypeVar("_T", bound=EventBase)


@contextmanager
def capture_events(
    *types: Type[EventBase],
    include_framework=False,
    include_deferred=True,
) -> ContextManager[List[EventBase]]:
    """Capture all events of type `*types` (using instance checks).

    Arguments exposed so that you can define your own fixtures if you want to.

    Example::
    >>> from ops.charm import StartEvent
    >>> from scenario import Event, State
    >>> from charm import MyCustomEvent, MyCharm  # noqa
    >>>
    >>> def test_my_event():
    >>>     with capture_events(StartEvent, MyCustomEvent) as captured:
    >>>         trigger(State(), ("start", MyCharm, meta=MyCharm.META)
    >>>
    >>>     assert len(captured) == 2
    >>>     e1, e2 = captured
    >>>     assert isinstance(e2, MyCustomEvent)
    >>>     assert e2.custom_attr == 'foo'
    """
    allowed_types = types or (EventBase,)

    captured = []
    _real_emit = Framework._emit
    _real_reemit = Framework.reemit

    def _wrapped_emit(self, evt):
        if not include_framework and isinstance(evt, (PreCommitEvent, CommitEvent)):
            return _real_emit(self, evt)

        if isinstance(evt, allowed_types):
            # dump/undump the event to ensure any custom attributes are (re)set by restore()
            evt.restore(evt.snapshot())
            captured.append(evt)

        return _real_emit(self, evt)

    def _wrapped_reemit(self):
        # Framework calls reemit() before emitting the main juju event. We intercept that call
        # and capture all events in storage.

        if not include_deferred:
            return _real_reemit(self)

        # load all notices from storage as events.
        for event_path, _, _ in self._storage.notices():
            event_handle = Handle.from_path(event_path)
            try:
                event = self.load_snapshot(event_handle)
            except NoTypeError:
                continue
            event = typing.cast(EventBase, event)
            event.deferred = False
            self._forget(event)  # prevent tracking conflicts

            if not include_framework and isinstance(
                event,
                (PreCommitEvent, CommitEvent),
            ):
                continue

            if isinstance(event, allowed_types):
                captured.append(event)

        return _real_reemit(self)

    Framework._emit = _wrapped_emit  # type: ignore
    Framework.reemit = _wrapped_reemit  # type: ignore

    yield captured

    Framework._emit = _real_emit  # type: ignore
    Framework.reemit = _real_reemit  # type: ignore
