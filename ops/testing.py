# Copyright 2024 Canonical Ltd.
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

"""Infrastructure to build unit tests for charms using the ops library."""

from ._private.harness import (
    ActionFailed,
    ActionOutput,
    AppUnitOrName,
    CharmBase,
    CharmMeta,
    CharmType,
    Container,
    ExecArgs,
    ExecHandler,
    ExecProcess,
    ExecResult,
    Harness,
    ReadableBuffer,
    RelationNotFoundError,
    RelationRole,
    YAMLStringOrFile,
    charm,
    framework,
    model,
    pebble,
    storage,
)

# The Harness testing framework.
_ = ActionFailed
_ = ActionOutput
_ = AppUnitOrName
_ = CharmType
_ = ExecArgs
_ = ExecHandler
_ = ExecResult
_ = Harness
_ = ReadableBuffer
_ = YAMLStringOrFile

# Names exposed for backwards compatibility
_ = CharmBase
_ = CharmMeta
_ = Container
_ = ExecProcess
_ = RelationNotFoundError
_ = RelationRole
_ = charm
_ = framework
_ = model
_ = pebble
_ = storage
