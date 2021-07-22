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

"""Internal YAML helpers."""

import yaml as pyyaml


# Use C speedups if available
_safe_loader = getattr(pyyaml, "CSafeLoader", pyyaml.SafeLoader)
_safe_dumper = getattr(pyyaml, "CSafeDumper", pyyaml.SafeDumper)


def safe_load(stream):
    """Same as yaml.safe_load, but use fast C loader if available."""
    return pyyaml.load(stream, Loader=_safe_loader)


def safe_dump(data, stream=None, **kwargs):
    """Same as yaml.safe_dump, but use fast C dumper if available."""
    return pyyaml.dump(data, stream=stream, Dumper=_safe_dumper, **kwargs)


pyyaml.safe_load = safe_load
pyyaml.safe_dump = safe_dump

del safe_load, safe_dump
from yaml import *
