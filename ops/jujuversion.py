import re
from functools import total_ordering


@total_ordering
class JujuVersion:

    PATTERN = r'^(\d{1,9})\.(\d{1,9})((?:\.|-([a-z]+))(\d{1,9}))?(\.(\d{1,9}))?$'

    def __init__(self, version):
        m = re.match(self.PATTERN, version)
        if not m:
            raise RuntimeError(f"{version} is not a valid Juju version string.")

        self.major = int(m.group(1))
        self.minor = int(m.group(2))
        tag = m.group(4)
        if tag is None:
            tag = ''
        self.tag = tag

        patch = m.group(5)
        if patch is None:
            self.patch = 0
        else:
            self.patch = int(patch)

        build = m.group(7)
        if build is None:
            self.build = 0
        else:
            self.build = int(build)

    def __repr__(self):
        if self.tag:
            s = f'{self.major}.{self.minor}-{self.tag}{self.patch}'
        else:
            s = f'{self.major}.{self.minor}.{self.patch}'
        if isinstance(self.build, int) and self.build > 0:
            s += f'.{self.build}'
        return s

    def __eq__(self, other):
        if id(self) == id(other):
            return True
        if not isinstance(other, JujuVersion) and isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f"Cannot compare Juju version {self} with {other}")
        return self.major == other.major and self.minor == other.minor\
            and self.tag == other.tag and self.build == other.build and self.patch == other.patch

    def __lt__(self, other):
        if id(self) == id(other):
            return False
        if not isinstance(other, JujuVersion) and isinstance(other, str):
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
