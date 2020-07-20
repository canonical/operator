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

import logging
import os
import re
import sys

from ast import literal_eval
from importlib.util import module_from_spec
from importlib.machinery import ModuleSpec
from pkgutil import get_importer
from types import ModuleType

__all__ = ('use', 'autoimport')

logger = logging.getLogger(__name__)

_libraries = None

_libline_re = re.compile(r'''^LIB([A-Z]+)\s*=\s*([0-9]+|['"][a-zA-Z0-9_.\-@]+['"])''')
_libname_re = re.compile(r'''^[a-z][a-z0-9]+$''')

# Not perfect, but should do for now.
_libauthor_re = re.compile(r'''^[A-Za-z0-9_+.-]+@[a-z0-9_-]+(?:\.[a-z0-9_-]+)*\.[a-z]{2,3}$''')


def use(name: str, api: int, author: str) -> ModuleType:
    """Use a library from the ops libraries.

    Args:
        name: the name of the library requested.
        api: the API version of the library.
        author: the author of the library. If not given, requests the
            one in the standard library.
    Raises:
        ImportError: if the library cannot be found.
        TypeError: if the name, api, or author are the wrong type.
        ValueError: if the name, api, or author are invalid.
    """
    if not isinstance(name, str):
        raise TypeError("invalid library name: {!r} (must be a str)".format(name))
    if not isinstance(author, str):
        raise TypeError("invalid library author: {!r} (must be a str)".format(author))
    if not isinstance(api, int):
        raise TypeError("invalid library API: {!r} (must be an int)".format(api))
    if api < 0:
        raise ValueError('invalid library api: {} (must be ≥0)'.format(api))
    if not _libname_re.match(name):
        raise ValueError("invalid library name: {!r} (chars and digits only)".format(name))
    if not _libauthor_re.match(author):
        raise ValueError("invalid library author email: {!r}".format(author))

    if _libraries is None:
        autoimport()

    versions = _libraries.get((name, author), ())
    for lib in versions:
        if lib.api == api:
            return lib.import_module()

    others = ', '.join(str(lib.api) for lib in versions)
    if others:
        msg = 'cannot find "{}" from "{}" with API version {} (have {})'.format(
            name, author, api, others)
    else:
        msg = 'cannot find library "{}" from "{}"'.format(name, author)

    raise ImportError(msg, name=name)


def autoimport():
    """Find all libs in the path and enable use of them.

    You only need to call this if you've installed a package or
    otherwise changed sys.path in the current run, and need to see the
    changes. Otherwise libraries are found on first call of `use`.
    """
    global _libraries
    _libraries = {}
    for spec in _find_all_specs(sys.path):
        lib = _parse_lib(spec)
        if lib is None:
            continue

        versions = _libraries.setdefault((lib.name, lib.author), [])
        versions.append(lib)
        versions.sort(reverse=True)


def _find_all_specs(path):
    for sys_dir in path:
        logger.debug("Looking under %r.", sys_dir)
        if sys_dir == "":
            sys_dir = "."
        try:
            top_dirs = os.listdir(sys_dir)
        except OSError:
            continue
        for top_dir in top_dirs:
            opslib = os.path.join(sys_dir, top_dir, 'opslib')
            try:
                lib_dirs = os.listdir(opslib)
            except OSError:
                # logger.trace(...) # *lots* of things checked here
                continue
            else:
                logger.debug("Trying %r.", opslib)
            finder = get_importer(opslib)
            if finder is None:
                logger.debug("Finder for %r is None.", opslib)
                continue
            if not hasattr(finder, 'find_spec'):
                logger.debug("Finder for %r has no find_psec.", opslib)
                continue
            for lib_dir in lib_dirs:
                spec_name = "{}.opslib.{}".format(top_dir, lib_dir)
                spec = finder.find_spec(spec_name)
                if spec is None:
                    logger.debug("No spec for %r.", spec_name)
                    continue
                if spec.loader is None:
                    # a namespace package; not supported
                    logger.debug("No loader for %r (probably a namespace package)", spec_name)
                    continue

                logger.debug("Found %r.", spec_name)
                yield spec


# only the first this many lines of a file are looked at for the LIB* constants
_MAX_LIB_LINES = 99


_EXPECTED = {'NAME': str, 'AUTHOR': str, 'API': int, 'PATCH': int}


# XXX Names Are Hard™
class _NAH:
    """A silly little helper to only work out the difference between
    what was found and what was expected when logging"""

    def __init__(self, found):
        self._found = found

    def __str__(self):
        return ", ".join(set(_EXPECTED) - set(self._found))


def _parse_lib(spec):
    if spec.origin is None:
        # "can't happen"
        logger.debug("No origin for %r (no idea why; please report)", spec.name)
        return None

    logger.debug("Parsing %r:", spec.name)

    try:
        with open(spec.origin, 'rt', encoding='utf-8') as f:
            libinfo = {}
            for n, line in enumerate(f):
                if len(libinfo) == len(_EXPECTED):
                    break
                if n > _MAX_LIB_LINES:
                    logger.debug(
                        "  Reached line %d without finding %s.",
                        _MAX_LIB_LINES, _NAH(libinfo))
                    return None
                m = _libline_re.match(line)
                if m is None:
                    continue
                key, value = m.groups()
                if key in _EXPECTED:
                    value = literal_eval(value)
                    if not isinstance(value, _EXPECTED[key]):
                        logger.debug(
                            "  Bad type for %s: expected %s, got %s.",
                            key, _EXPECTED[key].__name__, type(value).__name__)
                        return None
                    libinfo[key] = value
            else:
                if len(libinfo) != len(_EXPECTED):
                    logger.debug("  Reached end without finding %s.", _NAH(libinfo))
                    return None
    except Exception as e:
        logger.debug("  Failed: %s.", e)
        return None

    logger.debug("  Success.")

    return _Lib(spec, libinfo['NAME'], libinfo['AUTHOR'], libinfo['API'], libinfo['PATCH'])


class _Lib:

    def __init__(self, spec: ModuleSpec, name: str, author: str, api: int, patch: int):
        self.spec = spec
        self.name = name
        self.author = author
        self.api = api
        self.patch = patch

        self._module = None

    def __repr__(self):
        return "<_Lib {0.name} by {0.author}, API {0.api}, patch {0.patch}>".format(self)

    def import_module(self) -> ModuleType:
        if self._module is None:
            module = module_from_spec(self.spec)
            self.spec.loader.exec_module(module)
            self._module = module
        return self._module

    def __eq__(self, other):
        if not isinstance(other, _Lib):
            return NotImplemented
        a = (self.name, self.author, self.api, self.patch)
        b = (other.name, other.author, other.api, other.patch)
        return a == b

    def __lt__(self, other):
        if not isinstance(other, _Lib):
            return NotImplemented
        a = (self.name, self.author, self.api, self.patch)
        b = (other.name, other.author, other.api, other.patch)
        return a < b
