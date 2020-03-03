# Copyright 2019 Canonical Ltd.
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

# note because the first import of ops can be from any of the
# namespace-providing packages, this __init__.py can't have any code
# beyond the extend_path call.

# import with underscore to keep the 'public' things clean
from pkgutil import extend_path as _extend_path
__path__ = _extend_path(__path__, __name__)
