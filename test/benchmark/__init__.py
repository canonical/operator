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

"""Benchmark tests for ops.

Optimising performance is not a current goal with ops - any gains are
unlikely to be significant compared with ones from Juju or the charm and
its workload. However, we do want to ensure that we do not unknowingly
regress in performance.

This package is for tests that cover core functionality, to be used for
performance benchmarking.
"""
