import re
from functools import total_ordering


@total_ordering
class JujuVersion:

    PATTERN = r'^(?P<major>\d{1,9})\.(?P<minor>\d{1,9})((?:\.|-(?P<tag>[a-z]+))(?P<patch>\d{1,9}))?(\.(?P<build>\d{1,9}))?$'

    def __init__(self, version):
        m = re.match(self.PATTERN, version)
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

    def __eq__(self, other):
        if self is other:
            return True
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f'cannot compare Juju version "{self}" with "{other}"')
        return self.major == other.major and self.minor == other.minor\
            and self.tag == other.tag and self.build == other.build and self.patch == other.patch

    def _less_than_property(self, other, prop):
        self_prop = getattr(self, prop)
        other_prop = getattr(other, prop)
        if self_prop != other_prop:
            if prop == 'tag':
                if not self_prop:
                    return False
                elif not other_prop:
                    return True
            return self_prop < other_prop
        return None

    def __lt__(self, other):
        if self is other:
            return False
        if isinstance(other, str):
            other = type(self)(other)
        elif not isinstance(other, JujuVersion):
            raise RuntimeError(f'cannot compare Juju version "{self}" with "{other}"')

        for prop in ['major', 'minor', 'tag', 'patch', 'build']:
            lt = self._less_than_property(other, prop)
            if lt is not None:
                return lt
        return False
