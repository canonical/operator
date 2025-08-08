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

"""Tools to extend Ops charms.

Includes tools to:
 * Generate charmcraft.yaml from Python config and action classes.
"""

from ._generate_yaml import ActionDict, OptionDict, action_to_juju_schema, config_to_juju_schema

__all__ = [
    'ActionDict',
    'OptionDict',
    'action_to_juju_schema',
    'config_to_juju_schema',
]
