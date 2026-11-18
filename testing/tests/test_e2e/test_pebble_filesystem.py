# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for the mock Pebble client's filesystem behaviour.

The behaviour asserted here is checked against a real Pebble server by
TestMockPebbleFilesystemMatchesRealPebble in test/test_real_pebble.py.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import socket
from collections.abc import Generator, Mapping

import pytest
from scenario import _pebble_filesystem

import ops
import ops.testing
from ops import pebble


class Charm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        for evt in self.on.events().values():
            framework.observe(evt, self._on_event)

    def _on_event(self, event: ops.EventBase):
        pass


@contextlib.contextmanager
def running_container(
    mounts: Mapping[str, ops.testing.Mount] | None = None,
) -> Generator[tuple[ops.Container, pathlib.Path]]:
    """Yields a started charm's container and the root of its mock filesystem."""
    ctx = ops.testing.Context(Charm, meta={'name': 'test', 'containers': {'c': {}}})
    state = ops.testing.State(
        containers={ops.testing.Container(name='c', can_connect=True, mounts=mounts or {})}
    )
    with ctx(ctx.on.start(), state=state) as mgr:
        mgr.run()
        # Creating the container creates the mock client, which resets the
        # filesystem root; populate it only afterwards.
        container = mgr.charm.unit.get_container('c')
        root = state.get_container('c').get_filesystem(ctx)
        yield container, root


class TestGoPathMatch:
    """list_files pattern matching follows Go's path.Match."""

    @pytest.mark.parametrize(
        ('pattern', 'name', 'expected'),
        [
            # A literal match, and the whole name must match.
            ('abc', 'abc', True),
            ('abc', 'abd', False),
            ('abc', 'abcd', False),
            # '*' matches any sequence of non-'/' characters, including empty.
            ('*', 'abc', True),
            ('*', '', True),
            ('*', 'a/b', False),
            ('*c', 'abc', True),
            ('a*', 'a', True),
            ('a*', 'ab/c', False),
            ('a*/b', 'abc/b', True),
            ('a*/b', 'a/c/b', False),
            ('a*b*c*d*e*/f', 'axbxcxdxe/f', True),
            ('a*b*c*d*e*/f', 'axbxcxdxexxx/f', True),
            ('a*b*c*d*e*/f', 'axbxcxdxe/xxx/f', False),
            ('a*b*c*d*e*/f', 'axbxcxdxexxx/fff', False),
            ('a*x', 'aaa', False),
            # '?' matches any single non-'/' character.
            ('?', 'a', True),
            ('?', '/', False),
            ('?', '', False),
            ('a?c', 'abc', True),
            # Character classes: ranges, '^' negation, and literal '!'
            # (fnmatch, which the mock used before, negates with '!' instead).
            ('[abc]', 'b', True),
            ('[abc]', 'd', False),
            ('[^abc]', 'b', False),
            ('[^abc]', 'd', True),
            ('[a-c]', 'b', True),
            ('[a-c]', '-', False),
            ('[!a]', '!', True),
            ('[!a]', 'a', True),
            ('[!a]', 'b', False),
            ('[[]', '[', True),
            ('[[]x]', '[x]', True),
            ('[\\]]', ']', True),
            # '\\' escapes the next character.
            ('\\*', '*', True),
            ('\\*', 'a', False),
            ('\\[x\\]', '[x]', True),
            ('a\\b', 'ab', True),
        ],
    )
    def test_matches(self, pattern: str, name: str, expected: bool):
        assert _pebble_filesystem.go_path_match(pattern, name) == expected

    @pytest.mark.parametrize(
        'pattern',
        ['[', 'a\\', '\\', '[]]', '[]a]', '[a-]', '[-a]', 'x[]', 'z*['],
    )
    def test_bad_pattern(self, pattern: str):
        # A malformed pattern is an error even when the name would not match.
        with pytest.raises(ValueError, match='syntax error in pattern'):
            _pebble_filesystem.go_path_match(pattern, 'zzz-no-match')


class TestFileErrors:
    def test_pull_only_reads_regular_files(self):
        with running_container() as (container, root):
            (root / 'file').write_text('x')
            with container.pull('/file') as f:
                assert f.read() == 'x'

            (root / 'dir').mkdir()
            with pytest.raises(pebble.PathError) as excinfo:
                container.pull('/dir')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'can only read a regular file' in excinfo.value.message

            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(root / 'sock'))
            sock.close()
            with pytest.raises(pebble.PathError) as excinfo:
                container.pull('/sock')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'can only read a regular file' in excinfo.value.message

    def test_pull_error_messages(self):
        with running_container() as (container, root):
            (root / 'file').write_text('x')
            # A path below a regular file.
            with pytest.raises(pebble.PathError) as excinfo:
                container.pull('/file/child')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'not a directory' in excinfo.value.message

            # A looping symlink.
            (root / 'loop').symlink_to('loop')
            with pytest.raises(pebble.PathError) as excinfo:
                container.pull('/loop')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'too many levels of symbolic links' in excinfo.value.message

            # A broken symlink.
            (root / 'broken').symlink_to('missing')
            with pytest.raises(pebble.PathError) as excinfo:
                container.pull('/broken')
            assert excinfo.value.kind == 'not-found'
            assert 'no such file or directory' in excinfo.value.message

    def test_push_error_messages(self):
        with running_container() as (container, root):
            # Pushing over a directory fails.
            (root / 'dir').mkdir()
            with pytest.raises(pebble.PathError) as excinfo:
                container.push('/dir', 'x')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'file exists' in excinfo.value.message

            # A missing parent directory.
            with pytest.raises(pebble.PathError) as excinfo:
                container.push('/missing/child', 'x')
            assert excinfo.value.kind == 'not-found'
            assert 'no such file or directory' in excinfo.value.message

            # A path below a regular file, with and without make_dirs.
            (root / 'file').write_text('x')
            with pytest.raises(pebble.PathError) as excinfo:
                container.push('/file/child', 'x')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'not a directory' in excinfo.value.message
            with pytest.raises(pebble.PathError) as excinfo:
                container.push('/file/child', 'x', make_dirs=True)
            assert excinfo.value.kind == 'generic-file-error'
            assert 'not a directory' in excinfo.value.message

    def test_push_replaces_non_directories(self):
        with running_container() as (container, root):
            (root / 'target').write_text('old')
            (root / 'dir').mkdir()
            for name, target in (
                ('to_file', 'target'),
                ('to_dir', 'dir'),
                ('broken', 'missing'),
            ):
                (root / name).symlink_to(target)
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(root / 'sock'))
            sock.close()

            for name in ('target', 'to_file', 'to_dir', 'broken', 'sock'):
                container.push(f'/{name}', 'new')
                # The path itself is replaced, so symlinks do not survive and
                # their targets are untouched.
                assert not (root / name).is_symlink()
                assert (root / name).read_text() == 'new'
            assert (root / 'dir').is_dir()
            assert list((root / 'dir').iterdir()) == []

    def test_push_make_dirs_below_symlink(self):
        with running_container() as (container, root):
            (root / 'broken').symlink_to('missing')
            with pytest.raises(pebble.PathError) as excinfo:
                container.push('/broken/child', 'x', make_dirs=True)
            assert excinfo.value.kind == 'generic-file-error'
            assert 'not a directory' in excinfo.value.message

    def test_make_dir_error_messages(self):
        with running_container() as (container, root):
            (root / 'file').write_text('x')
            # A path below a regular file.
            with pytest.raises(pebble.PathError) as excinfo:
                container.make_dir('/file/child')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'not a directory' in excinfo.value.message

            # A missing parent directory.
            with pytest.raises(pebble.PathError) as excinfo:
                container.make_dir('/missing/child')
            assert excinfo.value.kind == 'not-found'
            assert 'no such file or directory' in excinfo.value.message

    def test_make_dir_existing_paths(self):
        with running_container() as (container, root):
            # An existing directory: 'file exists' without make_parents, a
            # no-op with it.
            (root / 'dir').mkdir()
            with pytest.raises(pebble.PathError) as excinfo:
                container.make_dir('/dir')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'file exists' in excinfo.value.message
            container.make_dir('/dir', make_parents=True)

            # An existing non-directory is 'not a directory', with or without
            # make_parents.
            (root / 'file').write_text('x')
            for make_parents in (False, True):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.make_dir('/file', make_parents=make_parents)
                assert excinfo.value.kind == 'generic-file-error'
                assert 'not a directory' in excinfo.value.message

    def test_make_dir_symlinks(self):
        with running_container() as (container, root):
            (root / 'broken').symlink_to('missing')
            (root / 'loop').symlink_to('loop')

            # make_parents fails when any existing component is a symlink,
            # however broken or looping: Pebble creates '<path>.mkdir-new'
            # and renames it into place, which cannot replace a symlink.
            for path in ('/broken', '/loop', '/broken/child', '/loop/child'):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.make_dir(path, make_parents=True)
                assert excinfo.value.kind == 'generic-file-error'
                assert 'not a directory' in excinfo.value.message

            # Without make_parents, a symlink in the path reports the errno.
            with pytest.raises(pebble.PathError) as excinfo:
                container.make_dir('/loop/child')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'too many levels of symbolic links' in excinfo.value.message

    def test_remove_path_unlinks_symlinks(self):
        with running_container() as (container, root):
            (root / 'target').write_text('x')
            (root / 'dir').mkdir()
            (root / 'to_file').symlink_to('target')
            (root / 'to_dir').symlink_to('dir')
            (root / 'broken').symlink_to('missing')
            (root / 'loop').symlink_to('loop')

            # A symlink is removed itself, whatever it points to.
            for name in ('to_file', 'to_dir', 'broken', 'loop'):
                container.remove_path(f'/{name}')
                assert not os.path.lexists(root / name)
            assert (root / 'target').read_text() == 'x'
            assert (root / 'dir').is_dir()

    def test_remove_path_errors(self):
        with running_container() as (container, root):
            (root / 'file').write_text('x')
            # A path below a regular file, with and without recursive.
            for recursive in (False, True):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.remove_path('/file/child', recursive=recursive)
                assert excinfo.value.kind == 'generic-file-error'
                assert 'not a directory' in excinfo.value.message

            # A path below a looping symlink, with and without recursive.
            (root / 'loop').symlink_to('loop')
            for recursive in (False, True):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.remove_path('/loop/child', recursive=recursive)
                assert excinfo.value.kind == 'generic-file-error'
                assert 'too many levels of symbolic links' in excinfo.value.message

            # A non-empty directory without recursive.
            (root / 'dir' / 'child').mkdir(parents=True)
            with pytest.raises(pebble.PathError) as excinfo:
                container.remove_path('/dir')
            assert excinfo.value.kind == 'generic-file-error'
            assert 'directory not empty' in excinfo.value.message

    def test_remove_path_recursive_symlink_to_dir(self):
        with running_container() as (container, root):
            (root / 'dir' / 'child').mkdir(parents=True)
            (root / 'link').symlink_to('dir')
            container.remove_path('/link', recursive=True)
            assert not (root / 'link').exists()
            assert (root / 'dir' / 'child').is_dir()

    def test_list_files_follows_the_queried_path(self):
        with running_container() as (container, root):
            (root / 'target').write_text('x')
            (root / 'dir').mkdir()
            (root / 'dir' / 'link').symlink_to('../target')
            (root / 'to_file').symlink_to('target')
            (root / 'to_dir').symlink_to('dir')

            info = container.list_files('/to_file')[0]
            assert (info.path, info.name, info.type) == (
                '/to_file',
                'to_file',
                pebble.FileType.FILE,
            )
            info = container.list_files('/to_file', itself=True)[0]
            assert info.type == pebble.FileType.FILE
            info = container.list_files('/to_dir', itself=True)[0]
            assert info.type == pebble.FileType.DIRECTORY

            # A symlink within a directory listing is still reported as a
            # symlink.
            infos = container.list_files('/dir')
            assert [(i.path, i.type) for i in infos] == [('/dir/link', pebble.FileType.SYMLINK)]

    def test_list_files_errors(self):
        with running_container() as (container, root):
            (root / 'file').write_text('x')
            # A path below a regular file is a 400, not a 404.
            for itself in (False, True):
                with pytest.raises(pebble.APIError) as excinfo:
                    container.list_files('/file/child', itself=itself)
                assert excinfo.value.code == 400
                assert 'not a directory' in excinfo.value.message

            # A looping symlink, and a path below one, is a 400, not a 404.
            (root / 'loop').symlink_to('loop')
            for path in ('/loop', '/loop/child'):
                with pytest.raises(pebble.APIError) as excinfo:
                    container.list_files(path)
                assert excinfo.value.code == 400
                assert 'too many levels of symbolic links' in excinfo.value.message

            # A missing path, and a path below a broken symlink, is a 404.
            (root / 'broken').symlink_to('missing')
            for path in ('/missing', '/broken/child'):
                with pytest.raises(pebble.APIError) as excinfo:
                    container.list_files(path)
                assert excinfo.value.code == 404
                assert 'no such file or directory' in excinfo.value.message

    def test_list_files_file_types(self):
        with running_container() as (container, root):
            (root / 'file').write_text('x')
            (root / 'dir').mkdir()
            (root / 'link').symlink_to('file')
            os.mkfifo(root / 'fifo')
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(root / 'sock'))
            sock.close()

            expected = {
                '/file': pebble.FileType.FILE,
                '/dir': pebble.FileType.DIRECTORY,
                '/link': pebble.FileType.SYMLINK,
                '/fifo': pebble.FileType.NAMED_PIPE,
                '/sock': pebble.FileType.SOCKET,
            }
            infos = container.list_files('/')
            assert {i.path: i.type for i in infos} == expected
            # The queried path itself is followed: a symlink reports its
            # target's type.
            expected['/link'] = pebble.FileType.FILE
            for path, file_type in expected.items():
                info = container.list_files(path, itself=True)[0]
                assert info.type == file_type

    def test_list_files_pattern_errors(self):
        with running_container() as (container, root):
            (root / 'dir').mkdir()
            (root / 'dir' / 'file').write_text('x')
            # A malformed pattern is a 400, not an empty result.
            for pattern in ('[', 'a\\'):
                with pytest.raises(pebble.APIError) as excinfo:
                    container.list_files('/dir', pattern=pattern)
                assert excinfo.value.code == 400
                assert 'syntax error in pattern' in excinfo.value.message
            # An empty pattern is no filter.
            assert len(container.list_files('/dir', pattern='')) == 1
