# Copyright 2021 Canonical Ltd.
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

# autopep8 hates monkeypatching
# autopep8: off
# flake8: noqa

"""Internal JSON helpers."""

from json import JSONEncoder

# Explicitly import to avoid circular ImportErrors
import ops.framework

# Monkeypatch so Stored[Dict|List|Set] can be serialized


def _storedstate_workaround(self, obj):
    if isinstance(obj, (ops.framework.StoredDict, ops.framework.StoredList)):
        return getattr(obj.__class__, "to_json")(obj)
    return _storedstate_workaround.default(obj)


_storedstate_workaround.default = JSONEncoder().default
JSONEncoder.default = _storedstate_workaround

from json import *
