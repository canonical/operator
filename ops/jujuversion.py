import re
from functools import total_ordering


@total_ordering
class JujuVersion:

    PATTERN = r'^(?P<major>\d{1,9})\.(?P<minor>\d{1,9})((?:\.|-(?P<tag>[a-z]+))(?P<patch>\d{1,9}))?(\.(?P<build>\d{1,9}))?$'

    def __init__(self, version):
        m = re.match(self.PATTERN, version)
        if not m:
            raise RuntimeError(f"{version} is not a valid Juju version string.")

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

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f"Cannot compare Juju version {self} with {other}")
        return self.major == other.major and self.minor == other.minor\
            and self.tag == other.tag and self.build == other.build and self.patch == other.patch

    def __lt__(self, other):
        if self is other:
            return False
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f"Cannot compare Juju version {self} with {other}")

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
