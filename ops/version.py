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

"""Helper to define the version of the Operator Framework project.

This module is NOT to be used when developing charms using the Operator Framework.
"""

import subprocess
from pathlib import Path

__all__ = ('version',)

_FALLBACK = '1.0'  # this gets bumped after release


def _get_version():
    version = _FALLBACK + ".dev0+unknown"

    p = Path(__file__).parent
    if (p.parent / '.git').exists():
        try:
            proc = subprocess.run(
                ['git', 'describe', '--tags', '--dirty'],
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
                # in terms of PEP 440, the tag we'll make sure is a 'public version identifier';
                # everything after the first - needs to be a 'local version'
                public, local = version.split('-', 1)
                version = public + '+' + local.replace('-', '.')
                # version now <tag>+<#commits>.g<hex>[.dirty]
                # which is PEP440-compliant (as long as <tag> is :-)
    return version


version = _get_version()
