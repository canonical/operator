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

import sys
import os
import re

from ast import literal_eval
from importlib.util import module_from_spec
from importlib.machinery import ModuleSpec
from pkgutil import get_importer
from types import ModuleType
from typing import Tuple, Dict, List, Iterator, Optional


_libraries = {} # type: Dict[Tuple[str,str], List[_Lib]]

_libline_re = re.compile(r'''^LIB([A-Z]+)\s+=\s+([0-9]+|['"][a-zA-Z0-9_.-@]+['"])\s*$''')
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

    versions = _libraries.get((name, author), ())
    for lib in versions:
        if lib.api == api:
            return lib.import_module()

    others = ', '.join(str(lib.api) for lib in versions)
    if others:
        msg = 'cannot find "{}" from {} with API {} (have {})'.format(name, author, api, others)
    else:
        msg = 'cannot find library "{}" from {}'.format(name, author)

    raise ImportError(msg, name=name)


def autoimport():
    _libraries.clear()
    for spec in _find_all_specs(sys.path):
        lib = _parse_lib(spec)
        if lib is None:
            continue

        versions = _libraries.setdefault((lib.name, lib.author), [])
        versions.append(lib)
        versions.sort(reverse=True)


def _find_all_specs(path: List[str]) -> Iterator[ModuleSpec]:
    for sys_dir in path:
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
                continue
            finder = get_importer(opslib)
            if finder is None or not hasattr(finder, 'find_spec'):
                continue
            for lib_dir in lib_dirs:
                # XXX: find_spec can raise ValueError (how?)
                spec = finder.find_spec(lib_dir)
                if spec is None:
                    continue
                yield spec

def _parse_lib(spec: ModuleSpec) -> Optional['_Lib']:
    if spec.origin is None:
        return None
    try:
        with open(spec.origin) as f:
            name = author = api = patch = None
            for line in f:
                if name and author and api and patch:
                    break
                m = _libline_re.match(line)
                if not m:
                    continue
                g = m.groups()
                key, value = g[0], g[1]
                if key == "NAME":
                    name = value
                    continue
                if key == "AUTHOR":
                    author = value
                    continue
                if key == "API":
                    api = value
                    continue
                if key == "PATCH":
                    patch = value
                    continue
    except OSError:
        return None

    if not (name and author and api and patch):
        return None

    try:
        # We could easily parse it but it'd still be more work than this,
        # and given the strict regexp above, this should hopefully be okay.
        name = literal_eval(name)
        author = literal_eval(author)
        api = literal_eval(api)
        patch = literal_eval(patch)
    except Exception:
        return None

    if not isinstance(name, str):
        return None
    if not isinstance(author, str):
        return None
    if not isinstance(api, int):
        return None
    if not isinstance(patch, int):
        return None

    return _Lib(spec, name, author, api, patch)


class _Lib:

    def __init__(self, spec: ModuleSpec, name: str, author: str, api: int, patch: int):
        self.spec = spec
        self.name = name
        self.author = author
        self.api = api
        self.patch = patch

        self._module = None # type: Optional[ModuleType]

    def __repr__(self):
        return "_Lib({0.name} by {0.author}, API {0.api}, patch {0.patch})".format(self)

    def import_module(self) -> ModuleType:
        if self._module is None:
            module = module_from_spec(self.spec)
            # XXX: loader can be None
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
