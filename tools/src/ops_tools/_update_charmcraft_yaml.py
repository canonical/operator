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
import importlib

import yaml

from . import ActionDict, OptionDict, action_to_juju_schema, config_to_juju_schema


def get_class_from_module(class_specifier: str) -> type:
    """Import the specified module and get the class from the top-level namespace."""
    module_name, class_name = class_specifier.rsplit(':', 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name, None)
    if cls is None:
        raise ImportError(f"Class '{class_name}' not found in module '{module_name}'")
    return cls


def main():
    """Merge generated config and action sections into charmcraft.yaml."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'charmcraft_yaml',
        help='Path to the charmcraft.yaml file to update.',
    )
    parser.add_argument(
        '--config-class',
        action='append',
        help='Python class with config classes (can be specified multiple times). '
        'For example, "src.charm:Config"',
        default=[],
    )
    parser.add_argument(
        '--action-class',
        action='append',
        help='Python class with action classes (can be specified multiple times). '
        'For example, "src.charm:BackupAction"',
        default=[],
    )
    args = parser.parse_args()

    with open(args.charmcraft_yaml) as raw:
        charmcraft_yaml = yaml.safe_load(raw)

    config: dict[str, dict[str, OptionDict]] = {}
    for class_specifier in args.config_class:
        cls = get_class_from_module(class_specifier)
        config.update(config_to_juju_schema(cls))
    actions: list[dict[str, ActionDict]] = []
    for class_specifier in args.action_class:
        cls = get_class_from_module(class_specifier)
        actions.append(action_to_juju_schema(cls))
    actions.sort(key=lambda x: next(iter(x.keys())))  # Sort actions by name.

    if config:
        charmcraft_yaml['config'] = config
    if actions:
        charmcraft_yaml['actions'] = actions

    with open(args.charmcraft_yaml, 'w') as raw:
        yaml.safe_dump(charmcraft_yaml, raw)


if __name__ == '__main__':
    main()
