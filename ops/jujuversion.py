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

import re
from functools import total_ordering


@total_ordering
class _Tag:
    """_Tag is an internal class used to encapsulate how tags sort.

    tags are special because an empty tag sorts after a non-empty tag,
    which is backwards from string.
    """

    def __init__(self, tag):
        self.tag = tag

    def __eq__(self, other):
        return self.tag == other.tag

    def __lt__(self, other):
        if self.tag == other.tag:
            return False
        if not self.tag:
            return False
        if not other.tag:
            return True
        return self.tag < other.tag


@total_ordering
class JujuVersion:
    """JujuVersion can be used to compare different Juju versions.

    Juju uses some convetions for its versions which make comparing them
    slightly simpler than the generic version compare function you might find
    elsewhere (e.g. apt_pkg.version_compare). This class encapsulates the needed
    logic.

    """

    _matcher = re.compile(r'''^
    (?P<major>\d{1,9})\.(?P<minor>\d{1,9})       # <major> and <minor> numbers are always there
    ((?:\.|-(?P<tag>[a-z]+))(?P<patch>\d{1,9}))? # sometimes with .<patch> or -<tag><patch>
    (\.(?P<build>\d{1,9}))?$                     # and sometimes with a <build> number.
                          ''',
                          re.VERBOSE).match

    def __init__(self, version):
        # we could inherit from tuple (or namedtuple) but then again we'd have to
        # implement all the comparison funcs instead of using total_ordering.
        # end result would be faster and lighter so if performance is an issue start there

        m = self._matcher(version)
        if not m:
            raise RuntimeError('"{}" is not a valid Juju version string'.format(version))

        d = m.groupdict()

        self.major = int(d['major'])
        self.minor = int(d['minor'])
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

    def _tuple(self):
        return (self.major, self.minor, _Tag(self.tag), self.patch, self.build)

    def _adapt(self, other):
        cls = type(self)
        if isinstance(other, cls):
            return other
        if isinstance(other, str):
            return cls(other)
        raise RuntimeError('cannot compare Juju version "{}" with "{}"'.format(self, other))

    def __eq__(self, other):
        if self is other:
            return True
        return self._tuple() == self._adapt(other)._tuple()

    def __lt__(self, other):
        if self is other:
            return False
        return self._tuple() < self._adapt(other)._tuple()
