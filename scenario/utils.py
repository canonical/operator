#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import re
import typing
from typing import List, Literal, NamedTuple, Optional

if typing.TYPE_CHECKING:
    from scenario.state import State


JUJU_EVT_REGEX = re.compile(r"Emitting Juju event (?P<event>\S+)\.")
_EVENT_REPR = (
    r"<(?P<event_cls>\S+) via (?P<charm_name>\S+)/on/(?P<event>\S+)\[(?P<n>\d+)\]>\."
)

REEMITTING_EVT_REGEX_NEW = re.compile(f"Re-emitting deferred event {_EVENT_REPR}")  # ops >= 2.1
REEMITTING_EVT_REGEX_OLD = re.compile(f"Re-emitting {_EVENT_REPR}")  # ops < 2.1
CUSTOM_EVT_REGEX = re.compile(f"Emitting custom event {_EVENT_REPR}")  # ops >= 2.1
OPERATOR_EVT_REGEX = re.compile(r"Charm called itself via hooks/(?P<event>\S+)\.")

class EventEmissionLog(NamedTuple):
    name: str
    source: Literal['juju', 'custom', 'deferral', 'framework']
    raw: str


def match_line(line: str) -> Optional[EventEmissionLog]:
    if grps := JUJU_EVT_REGEX.findall(line):
        return EventEmissionLog(grps[0], 'juju', line)
    elif grps := CUSTOM_EVT_REGEX.findall(line):
        _type_name, source, name, _id  = grps[0]
        return EventEmissionLog(name, 'custom', line)
    elif grps := (REEMITTING_EVT_REGEX_OLD.findall(line) or
                  REEMITTING_EVT_REGEX_NEW.findall(line)):
        _type_name, source, name, _id  = grps[0]
        return EventEmissionLog(name, 'deferral', line)
    elif grps := OPERATOR_EVT_REGEX.findall(line):
        return EventEmissionLog(grps[0], 'framework', line)
    else:
        return None


def emitted_events(state: "State") -> List[EventEmissionLog]:
    """Scrapes the juju-log for event-emission log messages.

    Most messages only get printed with loglevel >= DEBUG, so beware.
    """
    evts: List[EventEmissionLog] = []
    for _, line in state.juju_log:
        if match := match_line(line):
            evts.append(match)
    return evts
