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

"""Generate Juju config/actions YAML from Python classes, to stdout.

These tools complement ``update-charmcraft-schema``: they emit the raw
``config.yaml`` / ``actions.yaml`` fragment for one or more Python classes
without reading or modifying ``charmcraft.yaml``. They are intended for
ad-hoc use, piping into other tooling, or driving from a ``charmcraft``
override-build part.
"""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from collections.abc import Generator

import yaml

from . import ActionDict, OptionDict, action_to_juju_schema, config_to_juju_schema


def get_class_from_module(class_specifier: str) -> Generator[type]:
    """Import the specified module and get the class from the top-level namespace.

    ``class_specifier`` is either ``"ClassName"`` (module defaults to
    ``src.charm``) or ``"module.path:ClassName"``. ``ClassName`` may be a
    regular expression; any matching top-level class in the module is
    yielded.
    """
    if ':' in class_specifier:
        module_name, class_name = class_specifier.rsplit(':', 1)
    else:
        module_name = 'src.charm'
        class_name = class_specifier
    module = importlib.import_module(module_name)
    for attr in dir(module):
        if not isinstance(getattr(module, attr), type):
            continue
        if re.fullmatch(class_name, attr):
            yield getattr(module, attr)


def _build_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'classes',
        nargs='+',
        metavar='CLASS',
        help='Python class with optional module path. For example, '
        '"src.config:Config". The module defaults to "src.charm". The '
        'class name may be a regular expression, in which case every '
        'matching top-level class in the module is included.',
    )
    return parser


def config_main():
    """Write Juju config YAML for the given class(es) to stdout.

    The output matches the ``config.yaml`` format: a top-level ``options``
    mapping. It can also be pasted under the ``config:`` key of a
    ``charmcraft.yaml`` file.
    """
    parser = _build_parser(config_main.__doc__ or '')
    args = parser.parse_args()

    options: dict[str, OptionDict] = {}
    for class_specifier in args.classes:
        for cls in get_class_from_module(class_specifier):
            options.update(config_to_juju_schema(cls)['options'])
    sys.stdout.write(yaml.safe_dump({'options': options}))


def action_main():
    """Write Juju actions YAML for the given class(es) to stdout.

    The output matches the ``actions.yaml`` format: a top-level mapping of
    action name to action definition. It can also be pasted under the
    ``actions:`` key of a ``charmcraft.yaml`` file. Actions are sorted by
    name for stable output.
    """
    parser = _build_parser(action_main.__doc__ or '')
    args = parser.parse_args()

    actions: dict[str, ActionDict] = {}
    for class_specifier in args.classes:
        for cls in get_class_from_module(class_specifier):
            actions.update(action_to_juju_schema(cls))
    actions = dict(sorted(actions.items()))
    sys.stdout.write(yaml.safe_dump(actions))
