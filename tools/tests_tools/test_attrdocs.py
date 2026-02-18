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
import dataclasses
import textwrap

import pytest

try:
    import pydantic
    import pydantic.dataclasses
except ImportError:
    pydantic = None

from ops_tools._attrdocs import AttributeDocstringExtractor, get_attr_docstrings

# -- AttributeDocstringExtractor tests --


def _extract(source: str) -> dict[str, str]:
    """Helper to parse source and extract attribute docstrings."""
    tree = ast.parse(textwrap.dedent(source))
    extractor = AttributeDocstringExtractor()
    extractor.visit(tree)
    return extractor.attribute_docs


def test_extractor_class_with_docstrings():
    docs = _extract("""\
        class Foo:
            bar: str = "bar"
            '''This is bar.'''
            baz: int = 42
            '''This is baz.'''
    """)
    assert docs == {'bar': 'This is bar.', 'baz': 'This is baz.'}


def test_extractor_class_without_docstrings():
    docs = _extract("""\
        class Foo:
            bar: str = "bar"
            baz: int = 42
    """)
    assert docs == {}


def test_extractor_mixed_docstrings():
    docs = _extract("""\
        class Foo:
            bar: str = "bar"
            '''This is bar.'''
            baz: int = 42
            qux: float = 3.14
            '''This is qux.'''
    """)
    assert docs == {'bar': 'This is bar.', 'qux': 'This is qux.'}
    assert 'baz' not in docs


def test_extractor_assign_without_annotation():
    docs = _extract("""\
        class Foo:
            bar = "bar"
            '''This is bar.'''
    """)
    assert docs == {'bar': 'This is bar.'}


# -- get_attr_docstrings tests --


class PlainClass:
    x: int = 1
    """X doc."""
    y: str = 'hello'
    """Y doc."""


def test_get_attr_docstrings_plain_class():
    docs = get_attr_docstrings(PlainClass)
    assert docs == {'x': 'X doc.', 'y': 'Y doc.'}


@dataclasses.dataclass
class StdlibDataclass:
    a: int = 10
    """A doc."""
    b: str = 'world'
    """B doc."""


def test_get_attr_docstrings_stdlib_dataclass():
    docs = get_attr_docstrings(StdlibDataclass)
    assert docs == {'a': 'A doc.', 'b': 'B doc.'}


class ParentClass:
    x: int = 1
    """Parent X."""
    y: str = 'hello'
    """Parent Y."""


class ChildClass(ParentClass):
    x: int = 2
    """Child X."""
    z: float = 3.14
    """Child Z."""


def test_get_attr_docstrings_inheritance():
    docs = get_attr_docstrings(ChildClass)
    # Child's docstring for x takes priority over parent.
    assert docs['x'] == 'Child X.'
    # Parent's y is inherited.
    assert docs['y'] == 'Parent Y.'
    # Child's own attribute.
    assert docs['z'] == 'Child Z.'


class GrandparentClass:
    a: int = 1
    """Grandparent A."""


class MiddleClass(GrandparentClass):
    b: str = 'mid'
    """Middle B."""


class GrandchildClass(MiddleClass):
    a: int = 99
    """Grandchild A."""
    c: float = 2.0
    """Grandchild C."""


def test_get_attr_docstrings_deep_inheritance():
    docs = get_attr_docstrings(GrandchildClass)
    assert docs['a'] == 'Grandchild A.'
    assert docs['b'] == 'Middle B.'
    assert docs['c'] == 'Grandchild C.'


@pytest.mark.skipif(pydantic is None, reason='pydantic not installed')
def test_get_attr_docstrings_pydantic_base_model():
    assert pydantic is not None

    class PydanticConfig(pydantic.BaseModel):
        x: int = pydantic.Field(default=1, description='X from Pydantic.')
        y: str = pydantic.Field(default='hi', description='Y from Pydantic.')

    docs = get_attr_docstrings(PydanticConfig)
    assert docs == {'x': 'X from Pydantic.', 'y': 'Y from Pydantic.'}


@pytest.mark.skipif(pydantic is None, reason='pydantic not installed')
def test_get_attr_docstrings_pydantic_dataclass():
    assert pydantic is not None

    @pydantic.dataclasses.dataclass
    class PydanticDC:
        x: int = pydantic.Field(default=1, description='X from Pydantic DC.')
        y: str = pydantic.Field(default='hi', description='Y from Pydantic DC.')

    docs = get_attr_docstrings(PydanticDC)
    assert docs == {'x': 'X from Pydantic DC.', 'y': 'Y from Pydantic DC.'}


class NoDocstringsClass:
    x: int = 1
    y: str = 'hello'


def test_get_attr_docstrings_no_docstrings():
    docs = get_attr_docstrings(NoDocstringsClass)
    assert docs == {}
