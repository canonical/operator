#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Exceptions raised by the framework.

Note that these exceptions are not meant to be caught by charm authors. They are
used by the framework to signal errors or inconsistencies in the charm tests
themselves.
"""


class ContextSetupError(RuntimeError):
    """Raised by Context when setup fails."""


class AlreadyEmittedError(RuntimeError):
    """Raised when ``run()`` is called more than once."""


class ScenarioRuntimeError(RuntimeError):
    """Base class for exceptions raised by the runtime module."""


class UncaughtCharmError(ScenarioRuntimeError):
    """Error raised if the charm raises while handling the event being dispatched."""


class InconsistentScenarioError(ScenarioRuntimeError):
    """Error raised when the combination of state and event is inconsistent."""


class StateValidationError(RuntimeError):
    """Raised when individual parts of the State are inconsistent."""

    # as opposed to InconsistentScenario error where the **combination** of
    # several parts of the State are.


class MetadataNotFoundError(RuntimeError):
    """Raised when a metadata file can't be found in the provided charm root."""


class ActionMissingFromContextError(Exception):
    """Raised when the user attempts to invoke action hook tools outside an action context."""

    # This is not an ops error: in ops, you'd have to go exceptionally out of
    # your way to trigger this flow.


class NoObserverError(RuntimeError):
    """Error raised when the event being dispatched has no registered observers."""


class BadOwnerPath(RuntimeError):
    """Error raised when the owner path does not lead to a valid ObjectEvents instance."""
