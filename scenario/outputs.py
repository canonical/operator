#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""
Output types.
Objects that wrap trigger outcomes which don't quite fit in State, as they can't be used as
input for the next trigger.
"""

from contextvars import ContextVar

# If you are using pytest, the scenario.pytest_plugin.action_output fixture should take care
# of managing this variable and set/reset it once per test.
# If you are not using pytest, then you'll need to .set() this var to a new ActionOutput
# instance before each Context.run() and reset it when you're done.
ACTION_OUTPUT = ContextVar("ACTION_OUTPUT")


class ActionOutput:
    """Object wrapping the results of executing an action."""

    def __init__(self):
        self.logs = []
        self.results = {}
        self.failure_message = ""

    @property
    def failed(self):
        return bool(self.failure_message)

    def __enter__(self):
        self.logs = []
        self.results = {}
        self.failure_message = ""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):  # noqa: U100
        pass

    @staticmethod
    def is_set() -> bool:
        try:
            ACTION_OUTPUT.get()
        except LookupError:
            return False
        return True
