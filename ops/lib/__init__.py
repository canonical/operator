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

"""Infrastructure for the opslib functionality.

.. deprecated:: 2.1.0
    The ops.lib functionality is deprecated, and is superseded by
    charm libraries (https://juju.is/docs/sdk/library) and regular Python imports.
    We now prefer to do version selection at build (charmcraft pack) time.
"""

import logging
import os
import re
import sys
import typing
import warnings
from ast import literal_eval
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec
from pkgutil import get_importer
from types import ModuleType
from typing import List

__all__ = ('autoimport', 'use')

logger = logging.getLogger(__name__)

_libraries = None

_libline_re = re.compile(r"""^LIB([A-Z]+)\s*=\s*([0-9]+|['"][a-zA-Z0-9_.\-@]+['"])""")
_libname_re = re.compile(r"""^[a-z][a-z0-9]+$""")

# Not perfect, but should do for now.
_libauthor_re = re.compile(r"""^[A-Za-z0-9_+.-]+@[a-z0-9_-]+(?:\.[a-z0-9_-]+)*\.[a-z]{2,3}$""")


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

    .. deprecated:: 2.1.0
        This function is deprecated. Prefer charm libraries instead
        (https://juju.is/docs/sdk/library).
    """
    warnings.warn(
        'ops.lib is deprecated, prefer charm libraries instead', category=DeprecationWarning
    )
    if not isinstance(name, str):
        raise TypeError(f'invalid library name: {name!r} (must be a str)')
    if not isinstance(author, str):
        raise TypeError(f'invalid library author: {author!r} (must be a str)')
    if not isinstance(api, int):
        raise TypeError(f'invalid library API: {api!r} (must be an int)')
    if api < 0:
        raise ValueError(f'invalid library api: {api} (must be ≥0)')
    if not _libname_re.match(name):
        raise ValueError(f'invalid library name: {name!r} (chars and digits only)')
    if not _libauthor_re.match(author):
        raise ValueError(f'invalid library author email: {author!r}')

    if _libraries is None:
        autoimport()

    versions = _libraries.get((name, author), ())
    for lib in versions:
        if lib.api == api:
            return lib.import_module()

    others = ', '.join(str(lib.api) for lib in versions)
    if others:
        msg = f'cannot find "{name}" from "{author}" with API version {api} (have {others})'
    else:
        msg = f'cannot find library "{name}" from "{author}"'

    raise ImportError(msg, name=name)


def autoimport():
    """Find all libs in the path and enable use of them.

    Call this function only when a package has been installed or sys.path has been
    otherwise changed in the current run, and the changes need to be seen.
    Otherwise libraries are found on first call of `use`.

    .. deprecated:: 2.1.0
        This function is deprecated. Prefer charm libraries instead
        (https://juju.is/docs/sdk/library).
    """
    warnings.warn(
        'ops.lib is deprecated, prefer charm libraries instead', category=DeprecationWarning
    )
    global _libraries
    _libraries = {}
    for spec in _find_all_specs(sys.path):
        lib = _parse_lib(spec)
        if lib is None:
            continue

        versions = _libraries.setdefault((lib.name, lib.author), [])
        versions.append(lib)
        versions.sort(reverse=True)


def _find_all_specs(path: typing.Iterable[str]) -> typing.Iterator[ModuleSpec]:
    for sys_dir in path:
        if sys_dir == '':
            sys_dir = '.'
        try:
            top_dirs = os.listdir(sys_dir)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError as e:
            logger.debug("Tried to look for ops.lib packages under '%s': %s", sys_dir, e)
            continue
        logger.debug("Looking for ops.lib packages under '%s'", sys_dir)
        for top_dir in top_dirs:
            opslib = os.path.join(sys_dir, top_dir, 'opslib')
            try:
                lib_dirs = os.listdir(opslib)
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError as e:
                logger.debug("  Tried '%s': %s", opslib, e)  # *lots* of things checked here
                continue
            else:
                logger.debug("  Trying '%s'", opslib)
            finder = get_importer(opslib)
            if finder is None:
                logger.debug("  Finder for '%s' is None", opslib)
                continue
            if not hasattr(finder, 'find_spec'):
                logger.debug("  Finder for '%s' is None", opslib)
                continue
            for lib_dir in lib_dirs:
                spec_name = f'{top_dir}.opslib.{lib_dir}'
                spec = finder.find_spec(spec_name)
                if spec is None:
                    logger.debug('    No spec for %r', spec_name)
                    continue
                if spec.loader is None:
                    # a namespace package; not supported
                    logger.debug('    No loader for %r (probably a namespace package)', spec_name)
                    continue

                logger.debug('    Found %r', spec_name)
                yield spec


# only the first this many lines of a file are looked at for the LIB* constants
_MAX_LIB_LINES = 99
# these keys, with these types, are needed to have an opslib
_NEEDED_KEYS = {'NAME': str, 'AUTHOR': str, 'API': int, 'PATCH': int}


def _join_and(keys: List[str]) -> str:
    if len(keys) == 0:
        return ''
    if len(keys) == 1:
        return keys[0]
    all_except_last = ', '.join(keys[:-1])
    last = keys[-1]
    return f'{all_except_last}, and {last}'


class _Missing:
    """Helper to get the difference between what was found and what was needed when logging."""

    def __init__(self, found: bool):
        self._found = found

    def __str__(self):
        exp = set(_NEEDED_KEYS)
        got = set(self._found)
        if len(got) == 0:
            return f'missing {_join_and(sorted(exp))}'
        return f'got {_join_and(sorted(got))}, but missing {_join_and(sorted(exp - got))}'


def _parse_lib(spec: ModuleSpec) -> typing.Optional['_Lib']:
    if spec.origin is None:
        # "can't happen"
        logger.warning('No origin for %r (no idea why; please report)', spec.name)
        return None

    logger.debug('    Parsing %r', spec.name)

    try:
        with open(spec.origin, encoding='utf-8') as f:
            libinfo = {}
            for n, line in enumerate(f):
                if len(libinfo) == len(_NEEDED_KEYS):
                    break
                if n > _MAX_LIB_LINES:
                    logger.debug(
                        '      Missing opslib metadata after reading to line %d: %s',
                        _MAX_LIB_LINES,
                        _Missing(libinfo),
                    )
                    return None
                m = _libline_re.match(line)
                if m is None:
                    continue
                key, value = m.groups()
                if key in _NEEDED_KEYS:
                    value = literal_eval(value)
                    if not isinstance(value, _NEEDED_KEYS[key]):
                        logger.debug(
                            '      Bad type for %s: expected %s, got %s',
                            key,
                            _NEEDED_KEYS[key].__name__,
                            type(value).__name__,
                        )
                        return None
                    libinfo[key] = value
            else:
                if len(libinfo) != len(_NEEDED_KEYS):
                    logger.debug(
                        '      Missing opslib metadata after reading to end of file: %s',
                        _Missing(libinfo),
                    )
                    return None
    except Exception as e:
        logger.debug('      Failed: %s', e)
        return None

    lib = _Lib(spec, libinfo['NAME'], libinfo['AUTHOR'], libinfo['API'], libinfo['PATCH'])
    logger.debug('    Success: found library %s', lib)

    return lib


class _Lib:
    def __init__(self, spec: ModuleSpec, name: str, author: str, api: int, patch: int):
        self.spec = spec
        self.name = name
        self.author = author
        self.api = api
        self.patch = patch

        self._module = None

    def __repr__(self):
        return f'<_Lib {self}>'

    def __str__(self):
        return f'{self.name} by {self.author}, API {self.api}, patch {self.patch}'

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
