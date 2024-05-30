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
import pathlib
import sys
import typing
from importlib.machinery import ModuleSpec
from pathlib import Path
from random import shuffle
from textwrap import dedent
from unittest.mock import patch

import pytest

import ops.lib

# Ignore deprecation warnings for this module.
pytestmark: pytest.MarkDecorator = pytest.mark.filterwarnings('ignore::DeprecationWarning')


# ModuleSpec to pass when we know it will not be used but we want the
# type to match.
_dummy_spec = ModuleSpec('', loader=None)


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


def _flatten(specgen: typing.Iterable[ModuleSpec]) -> typing.List[str]:
    return sorted([
        os.path.dirname(spec.origin if spec.origin is not None else '') for spec in specgen
    ])


class TestLibFinder:
    def test_single(self, tmp_path: pathlib.Path):
        tmpdir = str(tmp_path)
        assert list(ops.lib._find_all_specs([tmpdir])) == []

        _mklib(tmpdir, 'foo', 'bar').write_text('')

        assert _flatten(ops.lib._find_all_specs([tmpdir])) == [
            os.path.join(tmpdir, 'foo', 'opslib', 'bar')
        ]

    def test_multi(self, tmp_path: pathlib.Path):
        tmp_dir_a = tmp_path / 'temp_dir1'
        tmp_dir_a.mkdir()

        tmp_dir_b = tmp_path / 'temp_dir2'
        tmp_dir_b.mkdir()

        if tmp_dir_a > tmp_dir_b:
            # keep sorting happy
            tmp_dir_a, tmp_dir_b = tmp_dir_b, tmp_dir_a

        dirs = [str(tmp_dir_a), str(tmp_dir_b)]

        for top in dirs:
            for pkg in ['bar', 'baz']:
                for lib in ['meep', 'quux']:
                    _mklib(top, pkg, lib).write_text('')

        expected = [
            os.path.join(tmp_dir_a, 'bar', 'opslib', 'meep'),
            os.path.join(tmp_dir_a, 'bar', 'opslib', 'quux'),
            os.path.join(tmp_dir_a, 'baz', 'opslib', 'meep'),
            os.path.join(tmp_dir_a, 'baz', 'opslib', 'quux'),
            os.path.join(tmp_dir_b, 'bar', 'opslib', 'meep'),
            os.path.join(tmp_dir_b, 'bar', 'opslib', 'quux'),
            os.path.join(tmp_dir_b, 'baz', 'opslib', 'meep'),
            os.path.join(tmp_dir_b, 'baz', 'opslib', 'quux'),
        ]

        assert _flatten(ops.lib._find_all_specs(dirs)) == expected

    def test_cwd(self, tmp_path: pathlib.Path):
        tmpcwd = str(tmp_path)
        os.chdir(tmpcwd)

        dirs = ['']

        assert list(ops.lib._find_all_specs(dirs)) == []

        _mklib(tmpcwd, 'foo', 'bar').write_text('')

        paths = _flatten(ops.lib._find_all_specs(dirs))
        assert [os.path.relpath(p) for p in paths] == [os.path.join('foo', 'opslib', 'bar')]

    def test_bogus_topdir(self, tmp_path: pathlib.Path):
        """Check that having one bogus dir in sys.path doesn't cause the finder to abort."""
        tmpdir = str(tmp_path)

        dirs = [tmpdir, '/bogus']

        assert list(ops.lib._find_all_specs(dirs)) == []

        _mklib(tmpdir, 'foo', 'bar').write_text('')

        assert _flatten(ops.lib._find_all_specs(dirs)) == [
            os.path.join(tmpdir, 'foo', 'opslib', 'bar')
        ]

    def test_bogus_opsdir(self, tmp_path: pathlib.Path):
        """Check that having one bogus opslib doesn't cause the finder to abort."""
        tmpdir = str(tmp_path)

        assert list(ops.lib._find_all_specs([tmpdir])) == []

        _mklib(tmpdir, 'foo', 'bar').write_text('')

        path = Path(tmpdir) / 'baz'
        path.mkdir()
        (path / 'opslib').write_text('')

        assert _flatten(ops.lib._find_all_specs([tmpdir])) == [
            os.path.join(tmpdir, 'foo', 'opslib', 'bar')
        ]

    def test_namespace(self, tmp_path: pathlib.Path):
        """Check that namespace packages are ignored."""
        tmpdir = str(tmp_path)

        assert list(ops.lib._find_all_specs([tmpdir])) == []

        _mklib(tmpdir, 'foo', 'bar')  # no __init__.py  =>  a namespace package

        assert list(ops.lib._find_all_specs([tmpdir])) == []


class TestLibParser:
    def _mkmod(
        self,
        tmp_path: pathlib.Path,
        name: str,
        content: typing.Optional[str] = None,
    ) -> ModuleSpec:
        file = tmp_path / name
        if content is not None:
            file.write_text(dedent(content))
        return ModuleSpec(name=name, loader=None, origin=str(file))

    def test_simple(self, tmp_path: pathlib.Path):
        """Check that we can load a reasonably straightforward lib."""
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = "foo"
        LIBEACH = float('-inf')
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        LIBANANA = True
        """,
        )
        lib = ops.lib._parse_lib(m)
        assert lib == ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 2, 42)
        # also check the repr while we're at it
        assert repr(lib) == '<_Lib foo by alice@example.com, API 2, patch 42>'

    def test_libauthor_has_dashes(self, tmp_path: pathlib.Path):
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = "foo"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice-someone@example.com"
        LIBANANA = True
        """,
        )
        lib = ops.lib._parse_lib(m)
        assert lib == ops.lib._Lib(_dummy_spec, 'foo', 'alice-someone@example.com', 2, 42)
        # also check the repr while we're at it
        assert repr(lib) == '<_Lib foo by alice-someone@example.com, API 2, patch 42>'

    def test_lib_definitions_without_spaces(self, tmp_path: pathlib.Path):
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME="foo"
        LIBAPI=2
        LIBPATCH=42
        LIBAUTHOR="alice@example.com"
        LIBANANA=True
        """,
        )
        lib = ops.lib._parse_lib(m)
        assert lib == ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 2, 42)
        # also check the repr while we're at it
        assert repr(lib) == '<_Lib foo by alice@example.com, API 2, patch 42>'

    def test_lib_definitions_trailing_comments(self, tmp_path: pathlib.Path):
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = "foo" # comment style 1
        LIBAPI = 2 = comment style 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"anything after the quote is a comment
        LIBANANA = True
        """,
        )
        lib = ops.lib._parse_lib(m)
        assert lib == ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 2, 42)
        # also check the repr while we're at it
        assert repr(lib) == '<_Lib foo by alice@example.com, API 2, patch 42>'

    def test_incomplete(self, tmp_path: pathlib.Path):
        """Check that if anything is missing, nothing is returned."""
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = "foo"
        LIBAPI = 2
        LIBPATCH = 42
        """,
        )
        assert ops.lib._parse_lib(m) is None

    def test_too_long(self, tmp_path: pathlib.Path):
        """Check that if the file is too long, nothing is returned."""
        m = self._mkmod(
            tmp_path,
            'foo',
            '\n' * ops.lib._MAX_LIB_LINES
            + """
        LIBNAME = "foo"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """,
        )
        assert ops.lib._parse_lib(m) is None

    def test_no_origin(self):
        """Check that _parse_lib doesn't choke when given a spec with no origin."""
        # 'just don't crash'
        lib = ops.lib._parse_lib(ModuleSpec(name='hi', loader=None, origin=None))
        assert lib is None

    def test_bogus_origin(self):
        """Check that if the origin is messed up, we don't crash."""
        # 'just don't crash'
        lib = ops.lib._parse_lib(ModuleSpec(name='hi', loader=None, origin='/'))
        assert lib is None

    def test_bogus_lib(self, tmp_path: pathlib.Path):
        """Check our behaviour when the lib is messed up."""
        # note the syntax error (that is carefully chosen to pass the initial regexp)
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = "1'
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """,
        )
        assert ops.lib._parse_lib(m) is None

    def test_name_is_number(self, tmp_path: pathlib.Path):
        """Check our behaviour when the name in the lib is a number."""
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = 1
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """,
        )
        assert ops.lib._parse_lib(m) is None

    def test_api_is_string(self, tmp_path: pathlib.Path):
        """Check our behaviour when the api in the lib is a string."""
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = 'foo'
        LIBAPI = '2'
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """,
        )
        assert ops.lib._parse_lib(m) is None

    def test_patch_is_string(self, tmp_path: pathlib.Path):
        """Check our behaviour when the patch in the lib is a string."""
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = 'foo'
        LIBAPI = 2
        LIBPATCH = '42'
        LIBAUTHOR = "alice@example.com"
        """,
        )
        assert ops.lib._parse_lib(m) is None

    def test_author_is_number(self, tmp_path: pathlib.Path):
        """Check our behaviour when the author in the lib is a number."""
        m = self._mkmod(
            tmp_path,
            'foo',
            """
        LIBNAME = 'foo'
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = 43
        """,
        )
        assert ops.lib._parse_lib(m) is None

    def test_other_encoding(self, tmp_path: pathlib.Path):
        """Check that we don't crash when a library is not UTF-8."""
        m = self._mkmod(tmp_path, 'foo')
        # This should never be the case, but we need to show type checkers
        # that it's not.
        if m.origin is None:
            assert m.origin is not None
            return
        with open(m.origin, 'w', encoding='latin-1') as f:
            f.write(
                dedent("""
            LIBNAME = "foo"
            LIBAPI = 2
            LIBPATCH = 42
            LIBAUTHOR = "alice@example.com"
            LIBANANA = "Ñoño"
            """)
            )
        assert ops.lib._parse_lib(m) is None


class TestLib:
    def test_lib_comparison(self):
        assert ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 1, 0) != ops.lib._Lib(
            _dummy_spec, 'bar', 'bob@example.com', 0, 1
        )
        assert ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 1, 1) == ops.lib._Lib(
            _dummy_spec, 'foo', 'alice@example.com', 1, 1
        )

        assert ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 1, 0) < ops.lib._Lib(
            _dummy_spec, 'foo', 'alice@example.com', 1, 1
        )
        assert ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 0, 1) < ops.lib._Lib(
            _dummy_spec, 'foo', 'alice@example.com', 1, 1
        )
        assert ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 1, 1) < ops.lib._Lib(
            _dummy_spec, 'foo', 'bob@example.com', 1, 1
        )
        assert ops.lib._Lib(_dummy_spec, 'bar', 'alice@example.com', 1, 1) < ops.lib._Lib(
            _dummy_spec, 'foo', 'alice@example.com', 1, 1
        )

        with pytest.raises(TypeError):
            42 < ops.lib._Lib(_dummy_spec, 'bar', 'alice@example.com', 1, 1)  # type:ignore  # noqa: B015, SIM300
        with pytest.raises(TypeError):
            ops.lib._Lib(_dummy_spec, 'bar', 'alice@example.com', 1, 1) < 42  # type: ignore  # noqa: B015

        # these two might be surprising in that they don't raise an exception,
        # but they are correct: our __eq__ bailing means Python falls back to
        # its default of checking object identity.
        assert ops.lib._Lib(_dummy_spec, 'bar', 'alice@example.com', 1, 1) != 42
        assert ops.lib._Lib(_dummy_spec, 'bar', 'alice@example.com', 1, 1) != 42

    @pytest.mark.parametrize('execution_number', range(20))
    def test_lib_order(self, execution_number: range):
        a = ops.lib._Lib(_dummy_spec, 'bar', 'alice@example.com', 1, 0)
        b = ops.lib._Lib(_dummy_spec, 'bar', 'alice@example.com', 1, 1)
        c = ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 1, 0)
        d = ops.lib._Lib(_dummy_spec, 'foo', 'alice@example.com', 1, 1)
        e = ops.lib._Lib(_dummy_spec, 'foo', 'bob@example.com', 1, 1)

        libs = [a, b, c, d, e]
        shuffle(libs)
        assert sorted(libs) == [a, b, c, d, e]

    def test_use_bad_args_types(self):
        with pytest.raises(TypeError):
            ops.lib.use(1, 2, 'bob@example.com')  # type: ignore
        with pytest.raises(TypeError):
            ops.lib.use('foo', '2', 'bob@example.com')  # type: ignore
        with pytest.raises(TypeError):
            ops.lib.use('foo', 2, ops.lib.use)  # type: ignore

    def test_use_bad_args_values(self):
        with pytest.raises(ValueError):
            ops.lib.use('--help', 2, 'alice@example.com')
        with pytest.raises(ValueError):
            ops.lib.use('foo', -2, 'alice@example.com')
        with pytest.raises(ValueError):
            ops.lib.use('foo', 1, 'example.com')


@patch('sys.path', new=())
class TestLibFunctional:
    def test_use_finds_subs(self, tmp_path: pathlib.Path):
        """Test that ops.lib.use("baz") works when baz is inside a package in the python path."""
        tmpdir = str(tmp_path)
        sys.path = [tmpdir]

        _mklib(tmpdir, 'foo', 'bar').write_text(
            dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """)
        )

        # autoimport to reset things
        ops.lib.autoimport()

        # ops.lib.use done by charm author
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        assert baz.LIBNAME == 'baz'
        assert baz.LIBAPI == 2
        assert baz.LIBPATCH == 42
        assert baz.LIBAUTHOR == 'alice@example.com'

    @pytest.mark.parametrize('pkg_a', ['foo', 'fooA'])
    @pytest.mark.parametrize('lib_a', ['bar', 'barA'])
    @pytest.mark.parametrize('patch_a', [38, 42])
    def test_use_finds_best_same_toplevel(
        self,
        tmp_path: pathlib.Path,
        pkg_a: str,
        lib_a: str,
        patch_a: int,
    ):
        """Test that ops.lib.use("baz") works when there are two baz in the same toplevel."""
        pkg_b = 'foo'
        lib_b = 'bar'
        patch_b = 40

        if (pkg_a, lib_a) == (pkg_b, lib_b):
            return

        tmpdir = str(tmp_path)
        sys.path = [tmpdir]

        _mklib(tmpdir, pkg_a, lib_a).write_text(
            dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = {}
        LIBAUTHOR = "alice@example.com"
        """).format(patch_a)
        )

        _mklib(tmpdir, pkg_b, lib_b).write_text(
            dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = {}
        LIBAUTHOR = "alice@example.com"
        """).format(patch_b)
        )

        # autoimport to reset things
        ops.lib.autoimport()

        # ops.lib.use done by charm author
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        assert baz.LIBNAME == 'baz'
        assert baz.LIBAPI == 2
        assert max(patch_a, patch_b) == baz.LIBPATCH
        assert baz.LIBAUTHOR == 'alice@example.com'

    @pytest.mark.parametrize('pkg_a', ['foo', 'fooA'])
    @pytest.mark.parametrize('lib_a', ['bar', 'barA'])
    @pytest.mark.parametrize('patch_a', [38, 42])
    def test_use_finds_best_diff_toplevel(
        self,
        tmp_path: pathlib.Path,
        pkg_a: str,
        lib_a: str,
        patch_a: int,
    ):
        """Test that ops.lib.use("baz") works when there are two baz in the different toplevels."""
        pkg_b = 'foo'
        lib_b = 'bar'
        patch_b = 40

        tmp_dir_a = tmp_path / 'temp_dir1'
        tmp_dir_a.mkdir()

        tmp_dir_b = tmp_path / 'temp_dir2'
        tmp_dir_b.mkdir()

        sys.path = [tmp_dir_a, tmp_dir_b]

        _mklib(str(tmp_dir_a), pkg_a, lib_a).write_text(
            dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = {}
        LIBAUTHOR = "alice@example.com"
        """).format(patch_a)
        )

        _mklib(str(tmp_dir_b), pkg_b, lib_b).write_text(
            dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = {}
        LIBAUTHOR = "alice@example.com"
        """).format(patch_b)
        )

        # autoimport to reset things
        ops.lib.autoimport()

        # ops.lib.use done by charm author
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        assert baz.LIBNAME == 'baz'
        assert baz.LIBAPI == 2
        assert max(patch_a, patch_b) == baz.LIBPATCH
        assert baz.LIBAUTHOR == 'alice@example.com'

    def test_none_found(self):
        with pytest.raises(ImportError):
            ops.lib.use('foo', 1, 'alice@example.com')

    def test_from_scratch(self, tmp_path: pathlib.Path):
        tmpdir = str(tmp_path)
        sys.path = [tmpdir]

        _mklib(tmpdir, 'foo', 'bar').write_text(
            dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """)
        )

        # hard reset
        ops.lib._libraries = None

        # sanity check that ops.lib.use works
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        assert baz.LIBAPI == 2

    def _test_submodule(
        self,
        tmp_path: pathlib.Path,
        *,
        relative: bool = False,
    ):
        tmpdir = str(tmp_path)
        sys.path = [tmpdir]

        path = _mklib(tmpdir, 'foo', 'bar')
        path.write_text(
            dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"

        from {} import quux
        """).format('.' if relative else 'foo.opslib.bar')
        )
        (path.parent / 'quux.py').write_text(
            dedent("""
        this = 42
        """)
        )

        # reset
        ops.lib.autoimport()

        # sanity check that ops.lib.use works
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        assert baz.LIBAPI == 2
        assert baz.quux.this == 42

    def test_submodule_absolute(self, tmp_path: pathlib.Path):
        self._test_submodule(tmp_path, relative=False)

    def test_submodule_relative(self, tmp_path: pathlib.Path):
        self._test_submodule(tmp_path, relative=True)

    def test_others_found(self, tmp_path: pathlib.Path):
        tmpdir = str(tmp_path)
        sys.path = [tmpdir]

        _mklib(tmpdir, 'foo', 'bar').write_text(
            dedent("""
        LIBNAME = "baz"
        LIBAPI = 2
        LIBPATCH = 42
        LIBAUTHOR = "alice@example.com"
        """)
        )

        # reload
        ops.lib.autoimport()

        # sanity check that ops.lib.use works
        baz = ops.lib.use('baz', 2, 'alice@example.com')
        assert baz.LIBAPI == 2

        with pytest.raises(ImportError):
            ops.lib.use('baz', 1, 'alice@example.com')

        with pytest.raises(ImportError):
            ops.lib.use('baz', 2, 'bob@example.com')


class TestDeprecationWarning:
    def test_autoimport_deprecated(self):
        with pytest.warns(DeprecationWarning):
            ops.lib.autoimport()

    def test_use_deprecated(self):
        with pytest.warns(DeprecationWarning):
            with pytest.raises(ImportError):
                ops.lib.use('foo', 1, 'bob@example.com')
