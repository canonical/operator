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

from pkgutil import get_importer
from importlib.util import module_from_spec
from functools import total_ordering


_libraries = {}

_libline_re = re.compile(r'''^LIB([A-Z]+)\s+=\s+([0-9]+|['"][a-zA-Z0-9_.-@]+['"])\s*$''')
_libname_re = re.compile(r'''^[a-z][a-z0-9]+$''')

# Not perfect, but should do for now.
_libauthor_re = re.compile(r'''^[A-Za-z0-9_+.-]+@[a-z0-9_-]+(?:\.[a-z0-9_-]+)*\.[a-z]{2,3}$''')


def use(name, author, api):
    if not _libname_re.match(name):
        raise ValueError("invalid library name: {} (chars and digits only)".format(name))
    if not _libauthor_re.match(author):
        raise ValueError("invalid library author email: {}".format(author))
    if not isinstance(api, int):
        raise ValueError("invalid library API: {} (must be an int)".format(api))

    versions = _libraries.get((name, author), ())
    for lib in versions:
        if lib.api == api:
            return lib.import_module()

    others = ', '.join(str(lib.api) for lib in versions)
    if others:
        raise RuntimeError('cannot find "{}" from {} with API {} (have {})'.format(
            name, author, api, others))
    else:
        raise RuntimeError('cannot find library "{}" from {}'.format(
            name, author))


def autoimport():
    _libraries.clear()
    for sys_dir in sys.path:
        if not isinstance(sys_dir, str):
            continue
        if sys_dir == "":
            sys_dir = "."
        try:
            top_dirs = os.listdir(sys_dir)
        except OSError:
            continue
        for top_dir in top_dirs:
            try:
                lib_dirs = os.listdir(os.path.join(sys_dir, top_dir, 'opslib'))
            except OSError:
                continue
            finder = get_importer(os.path.join(sys_dir, top_dir, 'opslib'))
            if finder is None or not hasattr(finder, 'find_spec'):
                continue
            for lib_dir in lib_dirs:
                spec = finder.find_spec(lib_dir)
                if spec is None:
                    continue
                lib = _parse_lib(spec)
                if lib is None:
                    continue

                versions = _libraries.setdefault((lib.name, lib.author), [])
                versions.append(lib)
                versions.sort(reverse=True)


def _parse_lib(spec):
    try:
        with open(spec.origin) as f:
            name = author = api = patch = None
            for line in f:
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
                if name and author and api and patch:
                    break
    except OSError:
        return None

    if not (name and author and api and patch):
        return None

    try:
        # We could easily parse it but it'd still be more work than this,
        # and given the strict regexp above, this should hopefully be okay.
        empty = {}
        name = eval(name, empty)
        author = eval(author, empty)
        api = eval(api, empty)
        patch = eval(patch, empty)
    except Exception:
        return None

    for s in (name, author):
        if not isinstance(s, str):
            return None
    for n in (api, patch):
        if not isinstance(n, int):
            return None

    return _Lib(spec, name, author, api, patch)


class _Lib:

    def __init__(self, spec, name, author, api, patch):
        self.spec = spec
        self.name = name
        self.author = author
        self.api = api
        self.patch = patch

        self._module = None

    def import_module(self):
        if self._module is None:
            module = module_from_spec(self.spec)
            self.spec.loader.exec_module(module)
            self._module = module
        return self._module

    def __eq__(self, other):
        if not isinstance(other, _Lib):
            raise NotImplemented
        a = (self.name, self.author, self.api, self.patch)
        b = (other.name, other.author, other.api, other.patch)
        return a == b

    def __lt__(self, other):
        if not isinstance(other, _Lib):
            raise NotImplemented
        a = (self.name, self.author, self.api, self.patch)
        b = (other.name, other.author, other.api, other.patch)
        return a < b
