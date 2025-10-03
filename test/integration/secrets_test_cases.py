# Copyright 2025 Canonical Ltd.
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

from __future__ import annotations

import ast
import inspect
import textwrap
from typing import Any, Callable, NamedTuple
from unittest.mock import ANY

import jubilant

import ops
import ops.testing
from test.charms.test_secrets.src.charm import TestSecretsCharm

UnitCode = Callable[[TestSecretsCharm, dict[str, Any]], None]
"""
Python code that will be executed in the test charm is defined
as a function with this type.

Arguments names must be exactly these, if used:
    self: TestSecretsCharm
    rv: dict[str, Any]

Example:

def code(self: TestSecretsCharm, rv: dict[str, Any]):
    '''Test get_secret by id.'''
    self.model.get_secret(id=self._stored.secret_id)
    rv['_result'] = 42
"""

ScenarioAssertions = Callable[[ops.testing.Secret | None, dict[str, Any] | None], None]
"""
Validate the result in Scenario.

Example:

assert result == {
    '_before': None,
    '_after': {
        'info': {
            'id': ANY,
            'label': None,
            'revision': 1,
            'expires': None,
            'rotation': None,
            'rotates': None,
            'description': None,
        },
        'tracked': {'foo': 'bar'},
        'latest': {'foo': 'bar'},
    },
}

assert secret
assert secret.owner == 'application'
assert not secret.remote_grants
"""

JubilantAssertions = Callable[[jubilant.RevealedSecret | None], None]
"""
Validate the result in Jubilant.
"""


# Note: this can't be called e.g. `TestCase` as pytest would trip
class Case(NamedTuple):
    func: UnitCode
    scenario_assertions: ScenarioAssertions | None
    jubilant_assertions: JubilantAssertions | None
    # Later:
    # - jubilant_assertions
    # - setup?
    # - cleanup?

    @property
    def code(self) -> str:
        func_src = inspect.getsource(self.func)
        func_def = ast.parse(func_src).body[0]
        assert isinstance(func_def, ast.FunctionDef)
        return '\n'.join(textwrap.dedent(ast.unparse(stmt)) for stmt in func_def.body)


def add_secret(self: TestSecretsCharm, rv: dict[str, Any]):
    """Add secret with content."""
    secret: ops.Secret = self.app.add_secret({'foo': 'bar'})
    secret_id = secret.id
    self._stored.secret_id = secret_id


def scenario_add_secret(secret: ops.testing.Secret | None, result: dict[str, Any] | None) -> None:
    assert result == {
        '_before': None,
        '_after': {
            'info': ANY,  # relying on scaffolding check
            'tracked': {'foo': 'bar'},
            'latest': {'foo': 'bar'},
        },
        '_result': None,
    }

    assert secret
    assert secret.owner == 'application'
    assert not secret.remote_grants


def jubilant_add_secret(secret: jubilant.RevealedSecret | None):
    # The signature of this function will likely change
    assert secret
    assert secret.revision == 1
    assert secret.content == {'foo': 'bar'}


TEST_CASES = [
    Case(add_secret, scenario_add_secret, jubilant_add_secret),
]
TEST_IDS = [t.func.__doc__ or t.func.__name__ for t in TEST_CASES]


# Note that if a unit modifies the secret content,
# it can see the new values with `--refresh` right away,
# but it doesn't see the new revision until the hook exits
#
# Example:
# juju exec --unit hexanator/1 "
#     secret-get --refresh d39p607mp25c761jrfc0;
#     secret-info-get d39p607mp25c761jrfc0;
#     secret-set d39p607mp25c761jrfc0 val=key77;
#     secret-get --refresh d39p607mp25c761jrfc0;
#     secret-info-get d39p607mp25c761jrfc0;
# "
# val: key56
# d39p607mp25c761jrfc0:
#   revision: 2
#   label: "77"
#   owner: application
#   rotation: never
# val: key77
# d39p607mp25c761jrfc0:
#   revision: 2
#   label: "77"
#   owner: application
#   rotation: never
