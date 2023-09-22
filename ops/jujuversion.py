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
from typing import Union


@total_ordering
class JujuVersion:
    """Helper to work with the Juju version.

    It knows how to parse the ``JUJU_VERSION`` environment variable, and
    exposes different capabilities according to the specific version. It also
    allows users to compare ``JujuVersion`` instances with ``<`` and ``>``
    operators.
    """

    _pattern_re = re.compile(r'''^
    (?P<major>\d{1,9})\.(?P<minor>\d{1,9})       # <major> and <minor> numbers are always there
    ((?:\.|-(?P<tag>[a-z]+))(?P<patch>\d{1,9}))? # sometimes with .<patch> or -<tag><patch>
    (\.(?P<build>\d{1,9}))?$                     # and sometimes with a <build> number.
    ''', re.VERBOSE)

    def __init__(self, version: str):
        m = self._pattern_re.match(version)
        if not m:
            raise RuntimeError(f'"{version}" is not a valid Juju version string')

        d = m.groupdict()
        self.major = int(m.group('major'))
        self.minor = int(m.group('minor'))
        self.tag = d['tag'] or ''
        self.patch = int(d['patch'] or 0)
        self.build = int(d['build'] or 0)

    def __repr__(self):
        if self.tag:
            s = f'{self.major}.{self.minor}-{self.tag}{self.patch}'
        else:
            s = f'{self.major}.{self.minor}.{self.patch}'
        if self.build > 0:
            s += f'.{self.build}'
        return s

    def __eq__(self, other: Union[str, 'JujuVersion']) -> bool:
        if self is other:
            return True
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f'cannot compare Juju version "{self}" with "{other}"')
        return (
            self.major == other.major
            and self.minor == other.minor
            and self.tag == other.tag
            and self.build == other.build
            and self.patch == other.patch)

    def __lt__(self, other: Union[str, 'JujuVersion']) -> bool:
        if self is other:
            return False
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f'cannot compare Juju version "{self}" with "{other}"')
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
        """Build a version from the ``JUJU_VERSION`` environment variable."""
        v = os.environ.get('JUJU_VERSION')
        if v is None:
            v = '0.0.0'
        return cls(v)

    def has_app_data(self) -> bool:
        """Report whether this Juju version supports app data."""
        return (self.major, self.minor, self.patch) >= (2, 7, 0)

    def is_dispatch_aware(self) -> bool:
        """Report whether this Juju version supports dispatch."""
        return (self.major, self.minor, self.patch) >= (2, 8, 0)

    def has_controller_storage(self) -> bool:
        """Report whether this Juju version supports controller-side storage."""
        return (self.major, self.minor, self.patch) >= (2, 8, 0)

    @property
    def has_secrets(self) -> bool:
        """Report whether this Juju version supports the "secrets" feature."""
        # Juju version 3.0.0 had an initial version of secrets, but:
        # * In 3.0.2, secret-get "--update" was renamed to "--refresh", and
        #   secret-get-info was separated into its own hook tool
        # * In 3.0.3, a bug with observer labels was fixed (juju/juju#14916)
        return (self.major, self.minor, self.patch) >= (3, 0, 3)

    @property
    def supports_open_port_on_k8s(self) -> bool:
        """Report whether this Juju version supports open-port on Kubernetes."""
        # Support added: https://bugs.launchpad.net/juju/+bug/1920960
        return (self.major, self.minor, self.patch) >= (3, 0, 3)

    @property
    def supports_exec_service_context(self) -> bool:
        """Report whether this Juju version supports exec's service_context option."""
        if (self.major, self.minor, self.patch) < (3, 1, 6):
            # First released in 3.1.6
            return False
        if (self.major, self.minor, self.patch) == (3, 2, 0):
            # 3.2.0 was released before Pebble was updated, but all other 3.2
            # releases have the change (3.2.1 tag was never released).
            return False
        return True
