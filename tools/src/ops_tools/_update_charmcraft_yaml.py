#! /usr/bin/env python

# /// script
# dependencies = [
#   "pyyaml"
# ]
# ///

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

"""Update a charmcraft.yaml file with generated config and action sections."""

from __future__ import annotations

import argparse
import difflib
import importlib
import re
import sys
from typing import Any, Generator

import yaml

from . import ActionDict, OptionDict, action_to_juju_schema, config_to_juju_schema


def get_class_from_module(class_specifier: str) -> Generator[type]:
    """Import the specified module and get the class from the top-level namespace."""
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


def _insert_into_charmcraft_yaml(
    raw_yaml: str, section_name: str, replacement: dict[str, Any]
) -> str:
    """Surgically insert a section into charmcraft.yaml.

    The specified section of charmcraft.yaml is replaced with the provided data.
    However, the rest of the file is left unchanged; in particular, comments and
    ordering is preserved.
    """
    # To simplify the regular expressions, look for four variants. Firstly,
    # there is a section with YAML both before and after it.
    mo = re.match(
        rf'(?P<before>.*)^{section_name}:(?P<tab_size>\s+).+?^(?P<after>\w.*)',
        raw_yaml,
        re.DOTALL | re.MULTILINE,
    )
    if mo:
        replacement_section = yaml.safe_dump(replacement, indent=len(mo['tab_size']))
        return f'{mo["before"]}{replacement_section}{mo["after"]}'
    # Secondly, there is a section with YAML before it, but no section after it.
    mo = re.match(
        rf'(?P<before>.*)^{section_name}:(?P<tab_size>\s+).+', raw_yaml, re.DOTALL | re.MULTILINE
    )
    if mo:
        replacement_section = yaml.safe_dump(replacement, indent=len(mo['tab_size']))
        return f'{mo["before"]}{replacement_section}'
    # Next, there is a section with no YAML before it, but YAML after it.
    mo = re.match(
        rf'^{section_name}:(?P<tab_size>\s+).+?^(?P<after>\w.*)',
        raw_yaml,
        re.DOTALL | re.MULTILINE,
    )
    if mo:
        replacement_section = yaml.safe_dump(replacement, indent=len(mo['tab_size']))
        return f'{replacement_section}{mo["after"]}'
    # Finally, there is no existing config section.
    return f'{raw_yaml}\n{yaml.safe_dump(replacement, indent=2)}'


def main():
    """Merge generated config and action sections into charmcraft.yaml."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--path',
        help='Path to the charmcraft.yaml file to update.',
        default='charmcraft.yaml',
    )
    parser.add_argument(
        '--config',
        action='append',
        help='Python class with config classes (can be specified multiple times). '
        'For example, "src.config:Config". The module defaults to "src.charm".'
        'The class may be a regular expression.',
        default=[],
    )
    parser.add_argument(
        '--action',
        action='append',
        help='Python class with action classes (can be specified multiple times). '
        'For example, "src.backup:BackupAction". The module defaults to "src.charm".'
        'The class may be a regular expression.',
        default=[],
    )
    parser.add_argument(
        '--merge',
        action='store_true',
        help='Merge the generated config and action sections into the existing charmcraft.yaml '
        'file instead of overwriting those sections completely.',
        default=False,
    )
    parser.add_argument(
        '--diff',
        action='store_true',
        help='Show the differences between the generated config and action sections and the '
        'existing charmcraft.yaml file instead of writing to the file. Exit non-zero if there are '
        'differences.',
        default=False,
    )
    args = parser.parse_args()

    with open(args.path) as raw:
        raw_yaml = raw.read()
        charmcraft_yaml = yaml.safe_load(raw_yaml)

    config: dict[str, dict[str, OptionDict]] = {'options': {}}
    for class_specifier in args.config:
        for cls in get_class_from_module(class_specifier):
            config['options'].update(config_to_juju_schema(cls)['options'])
    actions: dict[str, ActionDict] = {}
    for class_specifier in args.action:
        for cls in get_class_from_module(class_specifier):
            actions.update(action_to_juju_schema(cls))
    actions = dict(sorted(actions.items()))  # Sort actions by name.

    if args.diff:
        exit_code = 0

        if 'config' in charmcraft_yaml:
            existing_config = charmcraft_yaml['config']['options']
        else:
            existing_config = {}
        if config != {'options': existing_config}:
            print('Config section differs from existing charmcraft.yaml:\n')
            existing = yaml.safe_dump({'config': {'options': existing_config}})
            generated = yaml.safe_dump({'config': config})
            differ = difflib.Differ()
            result = differ.compare(existing.splitlines(), generated.splitlines())
            print('\n'.join(result))
            exit_code += 1

        existing_actions = charmcraft_yaml.get('actions', {})
        if actions != existing_actions:
            print('Action section differs from existing charmcraft.yaml:\n')
            existing = yaml.safe_dump({'actions': existing_actions})
            generated = yaml.safe_dump({'actions': actions})
            differ = difflib.Differ()
            result = differ.compare(existing.splitlines(), generated.splitlines())
            print('\n'.join(result))
            exit_code += 2
        sys.exit(exit_code)

    if args.merge and 'config' in charmcraft_yaml:
        config = charmcraft_yaml['config']['options'].update(config['options'])
    raw_yaml = _insert_into_charmcraft_yaml(raw_yaml, 'config', {'config': config})
    if actions:
        if args.merge and 'actions' in charmcraft_yaml:
            actions = charmcraft_yaml['actions'].update(actions)
        raw_yaml = _insert_into_charmcraft_yaml(raw_yaml, 'actions', {'actions': actions})

    with open(args.path, 'w') as raw:
        raw.write(raw_yaml)


if __name__ == '__main__':
    main()
