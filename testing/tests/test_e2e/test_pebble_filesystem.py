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


needs_non_root = pytest.mark.skipif(
    os.geteuid() == 0, reason='root bypasses the permission checks under test'
)


@contextlib.contextmanager
def _restored_modes(*paths: pathlib.Path) -> Generator[None]:
    """Restore owner access to the paths afterwards, so that temp dir cleanup works."""
    try:
        yield
    finally:
        for path in paths:
            if path.exists():
                path.chmod(0o755)


@needs_non_root
class TestPermissions:
    """Permission failures match those of a non-root Pebble."""

    def test_make_dir_with_no_permissions(self):
        with running_container() as (container, root):
            with _restored_modes(root / 'd'):
                container.make_dir('/d', permissions=0)
                assert (root / 'd').stat().st_mode & 0o777 == 0
                (info,) = container.list_files('/d', itself=True)
                assert info.permissions == 0

    def test_make_parents_with_no_permissions(self):
        with running_container() as (container, root):
            with _restored_modes(root / 'a'):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.make_dir('/a/b', make_parents=True, permissions=0)
                assert excinfo.value.kind == 'permission-denied'

    def test_push_into_read_only_dir(self):
        with running_container() as (container, root):
            container.make_dir('/d', permissions=0o555)
            with _restored_modes(root / 'd'):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.push('/d/f', 'x')
                assert excinfo.value.kind == 'permission-denied'

    def test_pull_unreadable_file(self):
        with running_container() as (container, root):
            (root / 'f').write_text('x')
            (root / 'f').chmod(0)
            with pytest.raises(pebble.PathError) as excinfo:
                container.pull('/f')
            assert excinfo.value.kind == 'permission-denied'

    def test_list_unreadable_dir(self):
        with running_container() as (container, root):
            with _restored_modes(root / 'd'):
                container.make_dir('/d', permissions=0)
                with pytest.raises(pebble.APIError) as excinfo:
                    container.list_files('/d')
                assert excinfo.value.code == 403

    def test_make_dir_in_read_only_dir(self):
        with running_container() as (container, root):
            container.make_dir('/d', permissions=0o555)
            with _restored_modes(root / 'd'):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.make_dir('/d/e')
                assert excinfo.value.kind == 'permission-denied'

    def test_remove_file_in_read_only_dir(self):
        with running_container() as (container, root):
            container.make_dir('/d')
            container.push('/d/f', 'x')
            (root / 'd').chmod(0o555)
            with _restored_modes(root / 'd'):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.remove_path('/d/f')
                assert excinfo.value.kind == 'permission-denied'

    def test_recursive_remove_empty_unreadable_dir(self):
        with running_container() as (container, root):
            with _restored_modes(root / 'd'):
                container.make_dir('/d', permissions=0)
                # Removing an empty directory needs no access to it.
                container.remove_path('/d', recursive=True)
                assert not (root / 'd').exists()

    def test_recursive_remove_below_unreadable_file(self):
        with running_container() as (container, root):
            (root / 'f').write_text('x')
            (root / 'f').chmod(0)
            with pytest.raises(pebble.PathError) as excinfo:
                container.remove_path('/f/child', recursive=True)
            assert excinfo.value.kind == 'permission-denied'
            assert excinfo.value.message.startswith('open /f:')

    def test_recursive_remove_existing_behaviour(self):
        with running_container() as (container, root):
            container.remove_path('/missing', recursive=True)
            container.remove_path('/missing/child', recursive=True)
            (root / 'dir').mkdir()
            (root / 'dir' / 'f').write_text('x')
            (root / 'link').symlink_to('dir')
            (root / 'broken').symlink_to('nowhere')
            (root / 'loop').symlink_to('loop')
            for link in ('link', 'broken', 'loop'):
                container.remove_path(f'/{link}', recursive=True)
                assert not (root / link).is_symlink()
            assert (root / 'dir' / 'f').exists()
            (root / 'file').write_text('x')
            with pytest.raises(pebble.PathError) as excinfo:
                container.remove_path('/file/child', recursive=True)
            assert excinfo.value.kind == 'generic-file-error'
            assert 'not a directory' in excinfo.value.message
            (root / 'loop').symlink_to('loop')
            with pytest.raises(pebble.PathError) as excinfo:
                container.remove_path('/loop/child', recursive=True)
            assert 'too many levels of symbolic links' in excinfo.value.message
            container.remove_path('/dir', recursive=True)
            assert not (root / 'dir').exists()

    def test_push_over_read_only_file(self):
        with running_container() as (container, root):
            container.push('/f', 'old', permissions=0o444)
            # The content goes to a temporary file that is renamed over the
            # target, so the target's own mode does not matter.
            container.push('/f', 'new')
            assert (root / 'f').read_text() == 'new'


class MakeDirCharm(Charm):
    def _on_event(self, event: ops.EventBase):
        if isinstance(event, ops.StartEvent):
            self.unit.get_container('c').make_dir('/d', permissions=0)


def _new_context() -> ops.testing.Context[MakeDirCharm]:
    return ops.testing.Context(MakeDirCharm, meta={'name': 'test', 'containers': {'c': {}}})


@needs_non_root
class TestCleanup:
    def _run_creating_unreadable_dir(self, ctx: ops.testing.Context[MakeDirCharm]) -> pathlib.Path:
        state = ops.testing.State(containers={ops.testing.Container('c', can_connect=True)})
        out = ctx.run(ctx.on.start(), state)
        return out.get_container('c').get_filesystem(ctx)

    def test_context_reuse(self):
        ctx = _new_context()
        with ctx:
            root = self._run_creating_unreadable_dir(ctx)
            assert (root / 'd').stat().st_mode & 0o777 == 0
            # The second run wipes the container filesystem again.
            self._run_creating_unreadable_dir(ctx)

    def test_close_removes_unreadable_dir(self):
        ctx = _new_context()
        self._run_creating_unreadable_dir(ctx)
        tmp_path = ctx._tmp_path
        assert tmp_path.exists()
        ctx.close()
        assert not tmp_path.exists()

    def test_remove_tree_does_not_follow_symlinks(self, tmp_path: pathlib.Path):
        source = tmp_path / 'source'
        source.mkdir()
        (source / 'f').write_text('x')
        source.chmod(0o555)
        tree = tmp_path / 'tree'
        (tree / 'locked').mkdir(parents=True)
        (tree / 'link').symlink_to(source)
        (tree / 'locked').chmod(0)
        try:
            _pebble_filesystem.remove_tree(tree)
            assert not tree.exists()
            # The target of the symlink was neither changed nor removed.
            assert source.stat().st_mode & 0o777 == 0o555
            assert (source / 'f').read_text() == 'x'
        finally:
            source.chmod(0o755)


class TestMounts:
    def test_remove_parent_of_mount_point(self, tmp_path: pathlib.Path):
        source = tmp_path / 'source'
        source.mkdir()
        (source / 'f').write_text('x')
        mounts = {'m': ops.testing.Mount(location='/a/b/mnt', source=source)}
        with running_container(mounts) as (container, root):
            (root / 'a' / 'other').write_text('y')
            for path in ('/a', '/a/b', '/'):
                with pytest.raises(pebble.PathError) as excinfo:
                    container.remove_path(path, recursive=True)
                assert excinfo.value.kind == 'generic-file-error'
                assert 'device or resource busy' in excinfo.value.message
            # Nothing was deleted, not even unrelated entries.
            assert (root / 'a' / 'other').read_text() == 'y'
            assert (root / 'a' / 'b' / 'mnt').is_symlink()
            assert (source / 'f').read_text() == 'x'
            # A sibling with a similar name is not a parent of the mount.
            (root / 'a' / 'b' / 'mnt2').mkdir()
            container.remove_path('/a/b/mnt2', recursive=True)

    def test_list_parent_of_mount_with_missing_source(self, tmp_path: pathlib.Path):
        mounts = {'m': ops.testing.Mount(location='/d/mnt', source=tmp_path / 'missing')}
        with running_container(mounts) as (container, _):
            (info,) = container.list_files('/d')
            assert info.path == '/d/mnt'
            assert info.type == pebble.FileType.SYMLINK
