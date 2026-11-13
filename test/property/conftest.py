# Copyright 2026 Canonical Ltd.
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

"""Hypothesis settings profiles for the property tests.

The profile is chosen with the ``HYPOTHESIS_PROFILE`` environment variable:

* ``dev`` (the default): Hypothesis's usual budget, for running locally.
* ``ci``: Hypothesis's usual budget, derandomised, so a pull request's result
  doesn't depend on luck.
* ``nightly``: a large budget with fresh randomness, for the scheduled run.

Tests shouldn't set ``max_examples`` themselves, so that the profile decides
how hard each run looks. When the nightly run finds a failing example, add it
to the test with ``@example(...)`` so that every later run checks it.
"""

from __future__ import annotations

import os

from hypothesis import settings

# Generation is cheap here, but CI machines are noisy, and a timing-based
# failure would say nothing about the code.
settings.register_profile('dev', deadline=None)
settings.register_profile('ci', deadline=None, derandomize=True, print_blob=True)
settings.register_profile('nightly', deadline=None, max_examples=10_000, print_blob=True)

settings.load_profile(os.environ.get('HYPOTHESIS_PROFILE', 'dev'))
