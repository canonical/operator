# Copyright 2014 Canonical Ltd.
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

# A small number of objects are common to both testing frameworks.
from ._core import ExecArgs as ExecArgs

# Expose the Harness functionality in this namespace.
from ._harness import *  # noqa: F403 (import *)

# If the 'ops.testing' optional extra is installed, make those
# names available in this namespace.
try:
    from scenario import *  # noqa: F403 (import *)
except ImportError:
    pass

# These names are exposed for backwards compatibility but not expected to be
# used by charms.
from ._core import CharmType as CharmType
from ._core import ReadableBuffer as ReadableBuffer
