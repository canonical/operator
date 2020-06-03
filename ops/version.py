# Copyright 2020 Canonical Ltd.
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

import os.path
import subprocess

__all__ = ('version',)


def _get_version():
    version = "0.7.dev+UNKNOWN"

    p = os.path.dirname(__file__)
    if os.path.exists(os.path.join(p, "../.git")):
        try:
            proc = subprocess.run(
                ['git', 'describe', '--tags', '--long', '--dirty'],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=p,
                check=True)
        except Exception:
            pass
        else:
            version = proc.stdout.strip().decode('utf8')
            if '-' in version:
                # version will look like <tag>-<#commits>-g<hex>[-dirty]
                # everything after the first - is a 'local version' in PEP440 terms
                # so mangle it to fit that spec
                s = version.split('-', 1)
                version = s[0] + '+' + s[1].replace('-', '.')
                # version now <tag>+<#commits>.g<hex>[.dirty]
                # which is PEP440-compliant (as long as <tag> is :-)
    return version


version = _get_version()
