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

"""A helper to work with the Juju version."""

import os
import re
from functools import total_ordering


@total_ordering
class JujuVersion:
    """Helper to work with the Juju version.

    It knows how to parse the ``JUJU_VERSION`` environment variable, and exposes different
    capabilities according to the specific version, allowing also to compare with other
    versions.
    """

    PATTERN = r'''^
    (?P<major>\d{1,9})\.(?P<minor>\d{1,9})       # <major> and <minor> numbers are always there
    ((?:\.|-(?P<tag>[a-z]+))(?P<patch>\d{1,9}))? # sometimes with .<patch> or -<tag><patch>
    (\.(?P<build>\d{1,9}))?$                     # and sometimes with a <build> number.
    '''

    def __init__(self, version):
        m = re.match(self.PATTERN, version, re.VERBOSE)
        if not m:
            raise RuntimeError('"{}" is not a valid Juju version string'.format(version))

        d = m.groupdict()
        self.major = int(m.group('major'))
        self.minor = int(m.group('minor'))
        self.tag = d['tag'] or ''
        self.patch = int(d['patch'] or 0)
        self.build = int(d['build'] or 0)

    def __repr__(self):
        if self.tag:
            s = '{}.{}-{}{}'.format(self.major, self.minor, self.tag, self.patch)
        else:
            s = '{}.{}.{}'.format(self.major, self.minor, self.patch)
        if self.build > 0:
            s += '.{}'.format(self.build)
        return s

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError('cannot compare Juju version "{}" with "{}"'.format(self, other))
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.tag == other.tag
            and self.build == other.build
            and self.patch == other.patch)

    def __lt__(self, other):
        if self is other:
            return False
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError('cannot compare Juju version "{}" with "{}"'.format(self, other))

        if self.major != other.major:
            return self.major < other.major
        elif self.minor != other.minor:
            return self.minor < other.minor
        elif self.tag != other.tag:
            if not self.tag:
                return False
            elif not other.tag:
                return True
            return self.tag < other.tag
        elif self.patch != other.patch:
            return self.patch < other.patch
        elif self.build != other.build:
            return self.build < other.build
        return False

    @classmethod
    def from_environ(cls) -> 'JujuVersion':
        """Build a JujuVersion from JUJU_VERSION."""
        v = os.environ.get('JUJU_VERSION')
        if v is None:
            v = '0.0.0'
        return cls(v)

    def has_app_data(self) -> bool:
        """Determine whether this juju version knows about app data."""
        return (self.major, self.minor, self.patch) >= (2, 7, 0)

    def is_dispatch_aware(self) -> bool:
        """Determine whether this juju version knows about dispatch."""
        return (self.major, self.minor, self.patch) >= (2, 8, 0)

    def has_controller_storage(self) -> bool:
        """Determine whether this juju version supports controller-side storage."""
        return (self.major, self.minor, self.patch) >= (2, 8, 0)
