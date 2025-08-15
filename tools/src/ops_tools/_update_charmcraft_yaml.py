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

import argparse
import difflib
import importlib
import re
import sys
from typing import Generator

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


def main():
    """Merge generated config and action sections into charmcraft.yaml."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--charmcraft-yaml',
        help='Path to the charmcraft.yaml file to update.',
        default='charmcraft.yaml',
    )
    parser.add_argument(
        '--config-class',
        action='append',
        help='Python class with config classes (can be specified multiple times). '
        'For example, "src.config:Config". The module defaults to "src.charm".'
        'The class may be a regular expression.',
        default=[],
    )
    parser.add_argument(
        '--action-class',
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

    with open(args.charmcraft_yaml) as raw:
        charmcraft_yaml = yaml.safe_load(raw)

    config: dict[str, dict[str, OptionDict]] = {'options': {}}
    for class_specifier in args.config_class:
        for cls in get_class_from_module(class_specifier):
            config['options'].update(config_to_juju_schema(cls)['options'])
    actions: dict[str, ActionDict] = {}
    for class_specifier in args.action_class:
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

    if config:
        if args.merge and 'config' in charmcraft_yaml:
            charmcraft_yaml['config']['options'].update(config['options'])
        else:
            charmcraft_yaml['config'] = config
    if actions:
        if args.merge and 'actions' in charmcraft_yaml:
            charmcraft_yaml['actions'].update(actions)
        else:
            charmcraft_yaml['actions'] = actions

    with open(args.charmcraft_yaml, 'w') as raw:
        yaml.safe_dump(charmcraft_yaml, raw)


if __name__ == '__main__':
    main()
