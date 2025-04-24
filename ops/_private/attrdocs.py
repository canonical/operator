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

"""Extract attribute docstrings from classes.

This essentially provides __doc__ type support for class attributes. For example::

    class Foo:
        bar: str = "bar"
        '''This is the docstring for bar.'''

Would provide a docstring of "This is the docstring for bar." for the ``Foo.bar``
attribute.
"""

from __future__ import annotations

import ast
import inspect
import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


class AttributeDocstringExtractor(ast.NodeVisitor):
    def __init__(self):
        self.attribute_docs: dict[str, str] = {}
        self._last_attr = None

    def visit_ClassDef(self, node: ast.ClassDef):  # noqa: N802
        # We iterate over the class definition, looking for attribute assignments.
        # We also track any standalone strings, and when we find one we use it
        # for the docstring of the most recent attribute assignments.
        # This isn't perfect - but it should cover the majority of cases.
        for child in node.body:
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                target = None  # Make the type checker happy.
                if isinstance(child, ast.Assign):
                    target = child.targets[0]
                elif isinstance(child, ast.AnnAssign):
                    target = child.target
                assert isinstance(target, ast.Name)
                self._last_attr = target.id
            elif (
                isinstance(child, ast.Expr)
                and isinstance(child.value, ast.Constant)
                and self._last_attr
            ):
                self.attribute_docs[self._last_attr] = child.value.value
                self._last_attr = None
        self.generic_visit(node)


def get_attr_docstrings(cls: type[object]) -> dict[str, str]:
    docs: dict[str, str] = {}
    # pydantic stores descriptions in the field object.
    if hasattr(cls, '__dataclass_fields__'):
        fields = cast(dict[str, Any], cls.__dataclass_fields__)  # type: ignore
        for attr, field in fields.items():
            if (
                hasattr(field, 'default')
                and hasattr(field.default, 'description')
                and field.default.description
            ):
                docs[attr] = field.default.description

    try:
        source_code = inspect.getsource(cls)
    except OSError:
        logger.debug('No source code found for %s', cls.__name__)
    else:
        try:
            tree = ast.parse(source_code)
        except (SyntaxError, IndentationError):
            logger.debug('Failed to parse source code for %s', cls.__name__)
        else:
            extractor = AttributeDocstringExtractor()
            extractor.visit(tree)
            docs.update(extractor.attribute_docs)

    return docs
