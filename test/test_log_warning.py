# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import functools
import logging
import sys
import warnings
from typing import Any, Callable, Type
from unittest.mock import ANY, Mock

import pytest

from ops.log import setup_root_logging
from ops.model import _ModelBackend


def deprecated(msg: str, *, category: Type[Warning] = DeprecationWarning, stacklevel: int = 1):
    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(f)
        def inner(*args: Any, **kwargs: Any):
            warnings.warn(category(msg), stacklevel=2)
            return f(*args, **kwargs)

        return inner

    return decorator


if sys.version_info >= (3, 13):
    from warnings import deprecated  # type: ignore


@deprecated('Use new_library_function instead')
def deprecated_library_function():
    pass


def dummy_charm_function():
    deprecated_library_function()


@pytest.fixture
def reset_warnings():
    del logging.root.handlers[:]
    logging.captureWarnings(False)
    warnings._onceregistry.clear()  # type: ignore
    yield
    del logging.root.handlers[:]
    logging.captureWarnings(False)
    warnings._onceregistry.clear()  # type: ignore


def test_fixme(monkeypatch: Any, reset_warnings: Any):
    monkeypatch.setenv('JUJU_UNIT_NAME', 'dummy')
    # I'd rather use pytest-subprocess instead of this crude mock
    monkeypatch.setattr(_ModelBackend, '_run', (run_mock := Mock()))
    logging.basicConfig()
    setup_root_logging(_ModelBackend())
    dummy_charm_function()
    assert run_mock.call_args == [('juju-log', '--log-level', 'WARNING', '--', ANY)]


def test_another(monkeypatch: Any, reset_warnings: Any):
    monkeypatch.setenv('JUJU_UNIT_NAME', 'dummy')
    # I'd rather use pytest-subprocess instead of this crude mock
    monkeypatch.setattr(_ModelBackend, '_run', (run_mock := Mock()))
    logging.basicConfig()
    setup_root_logging(_ModelBackend())
    dummy_charm_function()
    assert run_mock.call_args == [('juju-log', '--log-level', 'WARNING', '--', ANY)]
