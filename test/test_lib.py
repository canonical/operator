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

import os
import sys

from importlib.machinery import ModuleSpec
from pathlib import Path
from tempfile import mkdtemp, mkstemp
from unittest import TestCase
from unittest.mock import patch
from random import shuffle
from shutil import rmtree
from textwrap import dedent

import logassert

import ops.lib


def _mklib(topdir: str, pkgname: str, libname: str) -> Path:
    """Make a for-testing library.

    Args:
        topdir: the toplevel directory in which the package will be created.
             This directory must already exist.
        pkgname: the name of the package to create in the toplevel directory.
             this package will have an empty __init__.py.
        libname: the name of the library directory to create under the package.

    Returns:
        a :class:`Path` to the ``__init__.py`` of the created library.
        This file will not have been created yet.
    """
    pkg = Path(topdir) / pkgname
    try:
        pkg.mkdir()
    except FileExistsError:
        pass
    else:
        (pkg / '__init__.py').write_text('')

    lib = pkg / 'opslib' / libname
    lib.mkdir(parents=True)

    return lib / '__init__.py'


def _flatten(specgen):
    return sorted([os.path.dirname(spec.origin) for spec in specgen])


class TestLibFinder(TestCase):
    def setUp(self):
        logassert.setup(self, 'ops.lib')

    def _mkdtemp(self) -> str:
        tmpdir = mkdtemp()
        self.addCleanup(rmtree, tmpdir)
        return tmpdir

    def test_single(self):
        tmpdir = self._mkdtemp()

        self.assertEqual(list(ops.lib._find_all_specs([tmpdir])), [])
        self.assertLoggedDebug('Looking for ops.lib packages under', tmpdir)

        _mklib(tmpdir, "foo", "bar").write_text("")

        self.assertEqual(
            _flatten(ops.lib._find_all_specs([tmpdir])),
            [os.path.join(tmpdir, 'foo', 'opslib', 'bar')])
        self.assertLoggedDebug("Found", "foo.opslib.bar")

    def test_multi(self):
        tmpdirA = self._mkdtemp()
        tmpdirB = self._mkdtemp()

        if tmpdirA > tmpdirB:
            # keep sorting happy
            tmpdirA, tmpdirB = tmpdirB, tmpdirA

        dirs = [tmpdirA, tmpdirB]

        for top in [tmpdirA, tmpdirB]:
            for pkg in ["bar", "baz"]:
                for lib in ["meep", "quux"]:
                    _mklib(top, pkg, lib).write_text("")

        expected = [
            os.path.join(tmpdirA, "bar", "opslib", "meep"),
            os.path.join(tmpdirA, "bar", "opslib", "quux"),
            os.path.join(tmpdirA, "baz", "opslib", "meep"),
            os.path.join(tmpdirA, "baz", "opslib", "quux"),
            os.path.join(tmpdirB, "bar", "opslib", "meep"),
            os.path.join(tmpdirB, "bar", "opslib", "quux"),
            os.path.join(tmpdirB, "baz", "opslib", "meep"),
            os.path.join(tmpdirB, "baz", "opslib", "quux"),
        ]

        self.assertEqual(_flatten(ops.lib._find_all_specs(dirs)), expected)

    def test_cwd(self):
        tmpcwd = self._mkdtemp()
        cwd = os.getcwd()
        os.chdir(tmpcwd)
        self.addCleanup(os.chdir, cwd)

        dirs = [""]

        self.assertEqual(list(ops.lib._find_all_specs(dirs)), [])

        _mklib(tmpcwd, "foo", "bar").write_text("")

        self.assertEqual(
            _flatten(ops.lib._find_all_specs(dirs)),
            [os.path.join('.', 'foo', 'opslib', 'bar')])

    def test_bogus_topdir(self):
        """Check that having one bogus dir in sys.path doesn't cause the finder to abort."""
        tmpdir = self._mkdtemp()

        dirs = [tmpdir, "/bogus"]

        self.assertEqual(list(ops.lib._find_all_specs(dirs)), [])

        _mklib(tmpdir, "foo", "bar").write_text("")

        self.assertEqual(
            _flatten(ops.lib._find_all_specs(dirs)),
            [os.path.join(tmpdir, 'foo', 'opslib', 'bar')])

    def test_bogus_opsdir(self):
        """Check that having one bogus opslib doesn't cause the finder to abort."""

        tmpdir = self._mkdtemp()

        self.assertEqual(list(ops.lib._find_all_specs([tmpdir])), [])

        _mklib(tmpdir, "foo", "bar").write_text('')

        path = Path(tmpdir) / 'baz'
        path.mkdir()
        (path / 'opslib').write_text('')

        self.assertEqual(
            _flatten(ops.lib._find_all_specs([tmpdir])),
            [os.path.join(tmpdir, 'foo', 'opslib', 'bar')])

    def test_namespace(self):
        """Check that namespace packages are ignored."""
        tmpdir = self._mkdtemp()

        self.assertEqual(list(ops.lib._find_all_specs([tmpdir])), [])

        _mklib(tmpdir, "foo", "bar")  # no __init__.py  =>  a namespace package

        self.assertEqual(list(ops.lib._find_all_specs([tmpdir])), [])


class TestLibParser(TestCase):
    def _mkmod(self, name: str, content: str = None) -> ModuleSpec:
        fd, fname = mkstemp(text=True)
        self.addCleanup(os.unlink, fname)
        if content is not None:
            with os.fdopen(fd, mode='wt', closefd=False) as f:
                f.write(dedent(content))
        os.close(fd)
        return ModuleSpec(name=name, loader=None, origin=fname)

    def setUp(self):
        logassert.setup(self, 'ops.lib')

    def test_simple(self):
        """Check that we can load a reasonably straightforward lib"""
        m = self._mkmod('foo', '''
        LIBNAME = "foo"
        LIBEACH = float('-inf')
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        LIBANANA = True
        ''')
        lib = ops.lib._parse_lib(m)
        self.assertEqual(lib, ops.lib._Lib(None, "foo", "alice@example.com", 2, 42))
        # also check the repr while we're at it
        self.assertEqual(repr(lib), '<_Lib foo by alice@example.com, API 2, patch 42>')
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug("Success")

    def test_libauthor_has_dashes(self):
        m = self._mkmod('foo', '''
        LIBNAME = "foo"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice-someone@example.com"
        LIBANANA = True
        ''')
        lib = ops.lib._parse_lib(m)
        self.assertEqual(lib, ops.lib._Lib(None, "foo", "alice-someone@example.com", 2, 42))
        # also check the repr while we're at it
        self.assertEqual(repr(lib), '<_Lib foo by alice-someone@example.com, API 2, patch 42>')

    def test_lib_definitions_without_spaces(self):
        m = self._mkmod('foo', '''
        LIBNAME="foo"
        LIBAPI=2
        LIBPATCH=42
        LIBAUTHOR="alice@example.com"
        LIBANANA=True
        ''')
        lib = ops.lib._parse_lib(m)
        self.assertEqual(lib, ops.lib._Lib(None, "foo", "alice@example.com", 2, 42))
        # also check the repr while we're at it
        self.assertEqual(repr(lib), '<_Lib foo by alice@example.com, API 2, patch 42>')

    def test_lib_definitions_trailing_comments(self):
        m = self._mkmod('foo', '''
        LIBNAME = "foo" # comment style 1
        LIBAPI = 2 = comment style 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"anything after the quote is a comment
        LIBANANA = True
        ''')
        lib = ops.lib._parse_lib(m)
        self.assertEqual(lib, ops.lib._Lib(None, "foo", "alice@example.com", 2, 42))
        # also check the repr while we're at it
        self.assertEqual(repr(lib), '<_Lib foo by alice@example.com, API 2, patch 42>')

    def test_incomplete(self):
        """Check that if anything is missing, nothing is returned"""
        m = self._mkmod('foo', '''
        LIBNAME = "foo"
        LIBAPI = 2
        LIBPATCH = 42
        ''')
        self.assertIsNone(ops.lib._parse_lib(m))
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug(
            "Missing opslib metadata after reading to end of file:"
            " got API, NAME, and PATCH, but missing AUTHOR")
        self.assertNotLogged("Success")

    def test_too_long(self):
        """Check that if the file is too long, nothing is returned"""
        m = self._mkmod('foo', '\n' * ops.lib._MAX_LIB_LINES + '''
        LIBNAME = "foo"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        ''')
        self.assertIsNone(ops.lib._parse_lib(m))
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug(
            "Missing opslib metadata after reading to line 99:"
            " missing API, AUTHOR, NAME, and PATCH")
        self.assertNotLogged("Success")

    def test_no_origin(self):
        """Check that _parse_lib doesn't choke when given a spec with no origin"""
        # 'just don't crash'
        lib = ops.lib._parse_lib(ModuleSpec(name='hi', loader=None, origin=None))
        self.assertIsNone(lib)

    def test_bogus_origin(self):
        """Check that if the origin is messed up, we don't crash"""
        # 'just don't crash'
        lib = ops.lib._parse_lib(ModuleSpec(name='hi', loader=None, origin='/'))
        self.assertIsNone(lib)

    def test_bogus_lib(self):
        """Check our behaviour when the lib is messed up"""
        # note the syntax error (that is carefully chosen to pass the initial regexp)
        m = self._mkmod('foo', '''
        LIBNAME = "1'
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        ''')
        self.assertIsNone(ops.lib._parse_lib(m))
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug("Failed")
        self.assertNotLogged("Success")

    def test_name_is_number(self):
        """Check our behaviour when the name in the lib is a number"""
        m = self._mkmod('foo', '''
        LIBNAME = 1
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        ''')
        self.assertIsNone(ops.lib._parse_lib(m))
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug("Bad type for NAME: expected str, got int")
        self.assertNotLogged("Success")

    def test_api_is_string(self):
        """Check our behaviour when the api in the lib is a string"""
        m = self._mkmod('foo', '''
        LIBNAME = 'foo'
        LIBAPI = '2'
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        ''')
        self.assertIsNone(ops.lib._parse_lib(m))
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug("Bad type for API: expected int, got str")
        self.assertNotLogged("Success")

    def test_patch_is_string(self):
        """Check our behaviour when the patch in the lib is a string"""
        m = self._mkmod('foo', '''
        LIBNAME = 'foo'
        LIBAPI = 2
        LIBPATCH = '42'
        LIBAUTHOR = "alice@example.com"
        ''')
        self.assertIsNone(ops.lib._parse_lib(m))
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug("Bad type for PATCH: expected int, got str")
        self.assertNotLogged("Success")

    def test_author_is_number(self):
        """Check our behaviour when the author in the lib is a number"""
        m = self._mkmod('foo', '''
        LIBNAME = 'foo'
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = 43
        ''')
        self.assertIsNone(ops.lib._parse_lib(m))
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug("Bad type for AUTHOR: expected str, got int")
        self.assertNotLogged("Success")

    def test_other_encoding(self):
        """Check that we don't crash when a library is not UTF-8"""
        m = self._mkmod('foo')
        with open(m.origin, 'wt', encoding='latin-1') as f:
            f.write(dedent('''
            LIBNAME = "foo"
            LIBAPI = 2
            LIBPATCH = 42
            LIBAUTHOR = "alice@example.com"
            LIBANANA = "Ñoño"
            '''))
        self.assertIsNone(ops.lib._parse_lib(m))
        self.assertLoggedDebug("Parsing", "foo")
        self.assertLoggedDebug("Failed", "can't decode")
        self.assertNotLogged("Success")


class TestLib(TestCase):

    def test_lib_comparison(self):
        self.assertNotEqual(
            ops.lib._Lib(None, "foo", "alice@example.com", 1, 0),
            ops.lib._Lib(None, "bar", "bob@example.com", 0, 1))
        self.assertEqual(
            ops.lib._Lib(None, "foo", "alice@example.com", 1, 1),
            ops.lib._Lib(None, "foo", "alice@example.com", 1, 1))

        self.assertLess(
            ops.lib._Lib(None, "foo", "alice@example.com", 1, 0),
            ops.lib._Lib(None, "foo", "alice@example.com", 1, 1))
        self.assertLess(
            ops.lib._Lib(None, "foo", "alice@example.com", 0, 1),
            ops.lib._Lib(None, "foo", "alice@example.com", 1, 1))
        self.assertLess(
            ops.lib._Lib(None, "foo", "alice@example.com", 1, 1),
            ops.lib._Lib(None, "foo", "bob@example.com", 1, 1))
        self.assertLess(
            ops.lib._Lib(None, "bar", "alice@example.com", 1, 1),
            ops.lib._Lib(None, "foo", "alice@example.com", 1, 1))

        with self.assertRaises(TypeError):
            42 < ops.lib._Lib(None, "bar", "alice@example.com", 1, 1)
        with self.assertRaises(TypeError):
            ops.lib._Lib(None, "bar", "alice@example.com", 1, 1) < 42

        # these two might be surprising in that they don't raise an exception,
        # but they are correct: our __eq__ bailing means Python falls back to
        # its default of checking object identity.
        self.assertNotEqual(ops.lib._Lib(None, "bar", "alice@example.com", 1, 1), 42)
        self.assertNotEqual(42, ops.lib._Lib(None, "bar", "alice@example.com", 1, 1))

    def test_lib_order(self):
        a = ops.lib._Lib(None, "bar", "alice@example.com", 1, 0)
        b = ops.lib._Lib(None, "bar", "alice@example.com", 1, 1)
        c = ops.lib._Lib(None, "foo", "alice@example.com", 1, 0)
        d = ops.lib._Lib(None, "foo", "alice@example.com", 1, 1)
        e = ops.lib._Lib(None, "foo", "bob@example.com", 1, 1)

        for i in range(20):
            with self.subTest(i):
                libs = [a, b, c, d, e]
                shuffle(libs)
                self.assertEqual(sorted(libs), [a, b, c, d, e])

    def test_use_bad_args_types(self):
        with self.assertRaises(TypeError):
            ops.lib.use(1, 2, 'bob@example.com')
        with self.assertRaises(TypeError):
            ops.lib.use('foo', '2', 'bob@example.com')
        with self.assertRaises(TypeError):
            ops.lib.use('foo', 2, ops.lib.use)

    def test_use_bad_args_values(self):
        with self.assertRaises(ValueError):
            ops.lib.use('--help', 2, 'alice@example.com')
        with self.assertRaises(ValueError):
            ops.lib.use('foo', -2, 'alice@example.com')
        with self.assertRaises(ValueError):
            ops.lib.use('foo', 1, 'example.com')


@patch('sys.path', new=())
class TestLibFunctional(TestCase):

    def _mkdtemp(self) -> str:
        tmpdir = mkdtemp()
        self.addCleanup(rmtree, tmpdir)
        return tmpdir

    def test_use_finds_subs(self):
        """Test that ops.lib.use("baz") works when baz is inside a package in the python path."""
        tmpdir = self._mkdtemp()
        sys.path = [tmpdir]

        _mklib(tmpdir, "foo", "bar").write_text(dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """))

        # autoimport to reset things
        ops.lib.autoimport()

        # ops.lib.use done by charm author
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        self.assertEqual(baz.LIBNAME, 'baz')
        self.assertEqual(baz.LIBAPI, 2)
        self.assertEqual(baz.LIBPATCH, 42)
        self.assertEqual(baz.LIBAUTHOR, 'alice@example.com')

    def test_use_finds_best_same_toplevel(self):
        """Test that ops.lib.use("baz") works when there are two baz in the same toplevel."""

        pkg_b = "foo"
        lib_b = "bar"
        patch_b = 40
        for pkg_a in ["foo", "fooA"]:
            for lib_a in ["bar", "barA"]:
                if (pkg_a, lib_a) == (pkg_b, lib_b):
                    # everything-is-the-same :-)
                    continue
                for patch_a in [38, 42]:
                    desc = "A: {}/{}/{}; B: {}/{}/{}".format(
                        pkg_a, lib_a, patch_a, pkg_b, lib_b, patch_b)
                    with self.subTest(desc):
                        tmpdir = self._mkdtemp()
                        sys.path = [tmpdir]

                        _mklib(tmpdir, pkg_a, lib_a).write_text(dedent("""
                        LIBNAME = "baz"
                        LIBAPI = 2
                        LIBPATCH = {}
                        LIBAUTHOR = "alice@example.com"
                        """).format(patch_a))

                        _mklib(tmpdir, pkg_b, lib_b).write_text(dedent("""
                        LIBNAME = "baz"
                        LIBAPI = 2
                        LIBPATCH = {}
                        LIBAUTHOR = "alice@example.com"
                        """).format(patch_b))

                        # autoimport to reset things
                        ops.lib.autoimport()

                        # ops.lib.use done by charm author
                        baz = ops.lib.use('baz', 2, 'alice@example.com')
                        self.assertEqual(baz.LIBNAME, 'baz')
                        self.assertEqual(baz.LIBAPI, 2)
                        self.assertEqual(baz.LIBPATCH, max(patch_a, patch_b))
                        self.assertEqual(baz.LIBAUTHOR, 'alice@example.com')

    def test_use_finds_best_diff_toplevel(self):
        """Test that ops.lib.use("baz") works when there are two baz in the different toplevels."""

        pkg_b = "foo"
        lib_b = "bar"
        patch_b = 40
        for pkg_a in ["foo", "fooA"]:
            for lib_a in ["bar", "barA"]:
                for patch_a in [38, 42]:
                    desc = "A: {}/{}/{}; B: {}/{}/{}".format(
                        pkg_a, lib_a, patch_a, pkg_b, lib_b, patch_b)
                    with self.subTest(desc):
                        tmpdirA = self._mkdtemp()
                        tmpdirB = self._mkdtemp()
                        sys.path = [tmpdirA, tmpdirB]

                        _mklib(tmpdirA, pkg_a, lib_a).write_text(dedent("""
                        LIBNAME = "baz"
                        LIBAPI = 2
                        LIBPATCH = {}
                        LIBAUTHOR = "alice@example.com"
                        """).format(patch_a))

                        _mklib(tmpdirB, pkg_b, lib_b).write_text(dedent("""
                        LIBNAME = "baz"
                        LIBAPI = 2
                        LIBPATCH = {}
                        LIBAUTHOR = "alice@example.com"
                        """).format(patch_b))

                        # autoimport to reset things
                        ops.lib.autoimport()

                        # ops.lib.use done by charm author
                        baz = ops.lib.use('baz', 2, 'alice@example.com')
                        self.assertEqual(baz.LIBNAME, 'baz')
                        self.assertEqual(baz.LIBAPI, 2)
                        self.assertEqual(baz.LIBPATCH, max(patch_a, patch_b))
                        self.assertEqual(baz.LIBAUTHOR, 'alice@example.com')

    def test_none_found(self):
        with self.assertRaises(ImportError):
            ops.lib.use('foo', 1, 'alice@example.com')

    def test_from_scratch(self):
        tmpdir = self._mkdtemp()
        sys.path = [tmpdir]

        _mklib(tmpdir, "foo", "bar").write_text(dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """))

        # hard reset
        ops.lib._libraries = None

        # sanity check that ops.lib.use works
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        self.assertEqual(baz.LIBAPI, 2)

    def _test_submodule(self, *, relative=False):
        tmpdir = self._mkdtemp()
        sys.path = [tmpdir]

        path = _mklib(tmpdir, "foo", "bar")
        path.write_text(dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"

        from {} import quux
        """).format("." if relative else "foo.opslib.bar"))
        (path.parent / 'quux.py').write_text(dedent("""
        this = 42
        """))

        # reset
        ops.lib.autoimport()

        # sanity check that ops.lib.use works
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        self.assertEqual(baz.LIBAPI, 2)
        self.assertEqual(baz.quux.this, 42)

    def test_submodule_absolute(self):
        self._test_submodule(relative=False)

    def test_submodule_relative(self):
        self._test_submodule(relative=True)

    def test_others_found(self):
        tmpdir = self._mkdtemp()
        sys.path = [tmpdir]

        _mklib(tmpdir, "foo", "bar").write_text(dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """))

        # reload
        ops.lib.autoimport()

        # sanity check that ops.lib.use works
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        self.assertEqual(baz.LIBAPI, 2)

        with self.assertRaises(ImportError):
            ops.lib.use('baz', 1, 'alice@example.com')

        with self.assertRaises(ImportError):
            ops.lib.use('baz', 2, 'bob@example.com')
