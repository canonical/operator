# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Filesystem implementation for the mock Pebble client, matching real Pebble.

These helpers back ``_MockPebbleClient``'s ``pull``, ``push``,
``list_files``, ``make_dir`` and ``remove_path``. They mirror the behaviour
of Pebble's daemon (``internals/daemon/api_files.go``), so that a charm's
``ops.testing`` state-transition tests see the same outcomes, error types
and message wording as production: errors are ``pebble.PathError`` (or
``pebble.APIError`` for ``list_files``) with Pebble's kind or code and
reason phrases, worded '<op> <path>: <reason>'.

The module mirrors a Pebble daemon running as a non-root user. Permission
checks are made by the kernel, against the user running the tests, so
permission failures match those of a non-root Pebble. A Pebble running as
root would allow some calls that fail here, such as pushing into a directory
with mode 0o555.

Mount points (Scenario ``Mount``s) are symlinks in the container root
created by the test setup; they model real mounts, so pushing to a mounted
file writes through to its source, a mount point (or a directory containing
one, when removing recursively) cannot be removed, and a mount point in a
listing shows its target's type.
"""

from __future__ import annotations

import datetime
import errno
import http
import io
import os
import pathlib
import shutil
import stat
from collections.abc import Collection
from typing import BinaryIO, TextIO, cast

from ops import pebble
from ops._private.harness import ReadableBuffer

# The normalised container paths of the mount points declared by the test setup.
MountLocations = Collection[str]


def _is_mount_point(mount_locations: MountLocations, path: str) -> bool:
    """Whether the container path is a mount point.

    This compares the normalised path string only, so a path that reaches a
    mount through another symlink is not recognised as a mount point.
    """
    return os.path.normpath(path) in mount_locations


def _contains_mount_point(mount_locations: MountLocations, path: str) -> bool:
    """Whether any mount point is strictly below the container path."""
    prefix = os.path.normpath(path).rstrip('/') + '/'
    return any(location.startswith(prefix) for location in mount_locations)


def _make_tree_removable(path: pathlib.Path) -> None:
    """Give the owner rwx on every real directory in the tree at `path`.

    Symlinks are never followed or chmod-ed, as Mount locations are symlinks
    to files that belong to the test.
    """
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISDIR(mode):
            return
        path.chmod(stat.S_IMODE(mode) | stat.S_IRWXU)
        children = list(path.iterdir())
    except OSError:
        return
    for child in children:
        _make_tree_removable(child)


def remove_tree(path: pathlib.Path, *, ignore_errors: bool = False) -> None:
    """Remove the tree at `path`, even if it contains directories the user cannot access.

    A charm can create a directory with mode 0o000, which `shutil.rmtree`
    cannot clear. On a permission error, restore the owner's access within
    the tree (without following symlinks out of it) and try again.
    """
    try:
        shutil.rmtree(path)
    except PermissionError:
        _make_tree_removable(path)
        try:
            shutil.rmtree(path)
        except OSError:
            if not ignore_errors:
                raise
    except OSError:
        if not ignore_errors:
            raise


# Reason text that real Pebble's error messages use for these errnos (Go's
# lower-case syscall error strings). Charm and library error handlers match
# on these phrases.
_ERRNO_REASONS: dict[int, str] = {
    errno.ENOENT: 'no such file or directory',
    errno.ENOTDIR: 'not a directory',
    errno.ELOOP: 'too many levels of symbolic links',
    errno.EEXIST: 'file exists',
    errno.ENOTEMPTY: 'directory not empty',
    errno.EACCES: 'permission denied',
    errno.EPERM: 'permission denied',
    errno.EBUSY: 'device or resource busy',
}


def _errno_reason(error: OSError) -> str:
    """The reason text that real Pebble's error messages use for an OSError."""
    return _ERRNO_REASONS.get(error.errno or 0, error.strerror or str(error))


def path_error(op: str, path: str, error: OSError) -> pebble.PathError:
    """Translate an OSError to the PathError that real Pebble would return.

    Pebble's daemon words filesystem errors as '<op> <path>: <reason>', and
    reports ENOENT as a not-found error, permission errors as
    permission-denied, and anything else as a generic file error.
    """
    if error.errno == errno.ENOENT:
        kind = 'not-found'
    elif error.errno in (errno.EACCES, errno.EPERM):
        kind = 'permission-denied'
    else:
        kind = 'generic-file-error'
    return pebble.PathError(kind, f'{op} {path}: {_errno_reason(error)}')


def _api_error(code: int, message: str) -> pebble.APIError:
    status = http.HTTPStatus(code).phrase
    body = {
        'type': 'error',
        'status-code': code,
        'status': status,
        'result': {'message': message},
    }
    return pebble.APIError(body, code, status, message)


def files_api_error(op: str, path: str, error: OSError) -> pebble.APIError:
    """Translate an OSError to the APIError that real Pebble would return.

    Pebble's daemon reports ENOENT as a 404, permission errors as a 403,
    and anything else as a 400.
    """
    if error.errno == errno.ENOENT:
        code = 404
    elif error.errno in (errno.EACCES, errno.EPERM):
        code = 403
    else:
        code = 400
    return _api_error(code, f'{op} {path}: {_errno_reason(error)}')


def build_fileinfo(path: pathlib.Path, *, follow_symlinks: bool = False) -> pebble.FileInfo:
    """Construct a FileInfo object by stat'ing a local path."""
    info = path.stat() if follow_symlinks else path.lstat()
    # The same classification as Pebble's fileModeToType.
    mode = info.st_mode
    if stat.S_ISREG(mode):
        ftype = pebble.FileType.FILE
    elif stat.S_ISDIR(mode):
        ftype = pebble.FileType.DIRECTORY
    elif stat.S_ISLNK(mode):
        ftype = pebble.FileType.SYMLINK
    elif stat.S_ISSOCK(mode):
        ftype = pebble.FileType.SOCKET
    elif stat.S_ISFIFO(mode):
        ftype = pebble.FileType.NAMED_PIPE
    elif stat.S_ISCHR(mode) or stat.S_ISBLK(mode):
        ftype = pebble.FileType.DEVICE
    else:
        ftype = pebble.FileType.UNKNOWN

    import grp
    import pwd

    try:
        pw_name = pwd.getpwuid(info.st_uid).pw_name
    except KeyError:
        pw_name = None
    try:
        gr_name = grp.getgrgid(info.st_gid).gr_name
    except KeyError:
        gr_name = None
    return pebble.FileInfo(
        path=str(path),
        name=path.name,
        type=ftype,
        size=info.st_size,
        permissions=stat.S_IMODE(info.st_mode),
        # This is unused, but a required FileInfo field.
        last_modified=datetime.datetime.fromtimestamp(info.st_mtime),
        user_id=info.st_uid,
        user=pw_name,
        group_id=info.st_gid,
        group=gr_name,
    )


def _scan_chunk(pattern: str) -> tuple[bool, str, str]:
    """Split off the first chunk of a glob pattern (see Go's path.scanChunk)."""
    star = False
    while pattern.startswith('*'):
        pattern = pattern[1:]
        star = True
    inrange = False
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if char == '\\':
            # The error check for a dangling escape happens in _match_chunk.
            if i + 1 < len(pattern):
                i += 1
        elif char == '[':
            inrange = True
        elif char == ']':
            inrange = False
        elif char == '*' and not inrange:
            break
        i += 1
    return star, pattern[:i], pattern[i:]


def _get_esc(chunk: str) -> tuple[str, str]:
    """Take one character from a character class (see Go's path.getEsc)."""
    if not chunk or chunk[0] in '-]':
        raise ValueError('syntax error in pattern')
    if chunk[0] == '\\':
        chunk = chunk[1:]
        if not chunk:
            raise ValueError('syntax error in pattern')
    char, rest = chunk[0], chunk[1:]
    if not rest:
        raise ValueError('syntax error in pattern')
    return char, rest


def _match_chunk(chunk: str, name: str) -> tuple[str, bool]:
    """Match a star-free chunk against the start of name (see Go's path.matchChunk).

    Returns the unmatched rest of name and whether the chunk matched. Like
    Go, the whole chunk is validated even after the match has failed, so a
    malformed chunk raises ValueError regardless.
    """
    failed = False
    while chunk:
        if not failed and not name:
            failed = True
        char = chunk[0]
        if char == '[':
            r = ''
            if not failed:
                r, name = name[0], name[1:]
            chunk = chunk[1:]
            negated = False
            if chunk and chunk[0] == '^':
                negated = True
                chunk = chunk[1:]
            matched = False
            ranges = 0
            while True:
                if chunk and chunk[0] == ']' and ranges > 0:
                    chunk = chunk[1:]
                    break
                lo, chunk = _get_esc(chunk)
                hi = lo
                if chunk[0] == '-':
                    hi, chunk = _get_esc(chunk[1:])
                if lo <= r <= hi:
                    matched = True
                ranges += 1
            if matched == negated:
                failed = True
        elif char == '?':
            if not failed:
                if name[0] == '/':
                    failed = True
                name = name[1:]
            chunk = chunk[1:]
        else:
            if char == '\\':
                chunk = chunk[1:]
                if not chunk:
                    raise ValueError('syntax error in pattern')
                char = chunk[0]
            if not failed:
                if char != name[0]:
                    failed = True
                name = name[1:]
            chunk = chunk[1:]
    if failed:
        return '', False
    return name, True


def go_path_match(pattern: str, name: str) -> bool:
    r"""Match name against pattern, as Go's path.Match does.

    Real Pebble filters list_files results with path.Match: '*', '?' and
    character classes never match '/', classes use '^' (not '!') for
    negation, and '\' escapes the next character. A malformed pattern raises
    ValueError('syntax error in pattern'), even if the name would not match.
    """
    while pattern:
        star, chunk, pattern = _scan_chunk(pattern)
        if star and not chunk:
            # A trailing '*' matches the rest of the name unless it has a '/'.
            return '/' not in name
        # Look for a match at the current position. If this is the last
        # chunk, the whole name must be consumed; otherwise we'd get a false
        # result even if we could still match using the star.
        rest, ok = _match_chunk(chunk, name)
        if ok and (not rest or pattern):
            name = rest
            continue
        if star:
            # Look for a match skipping i+1 characters.
            accepted = False
            for i, char in enumerate(name):
                if char == '/':
                    break
                rest, ok = _match_chunk(chunk, name[i + 1 :])
                if ok:
                    # If this is the last chunk, it must exhaust the name.
                    if not pattern and rest:
                        continue
                    name = rest
                    accepted = True
                    break
            if accepted:
                continue
        # Like Go, validate the rest of the pattern before reporting no
        # match: a malformed pattern is an error even if nothing would match.
        while pattern:
            _, chunk, pattern = _scan_chunk(pattern)
            _match_chunk(chunk, '')
        return False
    return not name


def _write_source_to(dest: pathlib.Path, source: ReadableBuffer, encoding: str | None) -> None:
    if isinstance(source, str):
        dest.write_text(source, encoding=encoding)
    elif isinstance(source, bytes):
        dest.write_bytes(source)
    else:
        # If source is binary, open file in binary mode and ignore encoding param
        is_binary = isinstance(source.read(0), bytes)
        open_mode = 'wb' if is_binary else 'w'
        open_encoding = None if is_binary else encoding
        with dest.open(open_mode, encoding=open_encoding) as f:
            shutil.copyfileobj(cast('io.IOBase', source), cast('io.IOBase', f))


def _remove_quietly(path: pathlib.Path) -> None:
    """Remove a leftover temporary file, ignoring errors (as Pebble's Cancel does)."""
    try:
        path.unlink()
    except OSError:
        pass


def pull(root: pathlib.Path, path: str, *, encoding: str | None) -> BinaryIO | TextIO:
    """Read the file at the container path `path` from the mock filesystem at `root`."""
    file_path = root / path[1:]
    # Real Pebble stats the path (following symlinks) and refuses to read
    # anything that isn't a regular file.
    try:
        info = file_path.stat()
    except OSError as e:
        raise path_error('stat', path, e) from None
    if not stat.S_ISREG(info.st_mode):
        raise pebble.PathError('generic-file-error', f'can only read a regular file: "{path}"')
    try:
        return cast(
            'BinaryIO | TextIO',
            file_path.open('rb' if encoding is None else 'r', encoding=encoding),
        )
    except OSError as e:
        raise path_error('open', path, e) from None


def push(
    root: pathlib.Path,
    path: str,
    source: ReadableBuffer,
    *,
    encoding: str = 'utf-8',
    make_dirs: bool = False,
    permissions: int | None = None,
    mount_locations: MountLocations,
) -> None:
    """Write `source` to the container path `path` in the mock filesystem at `root`."""
    file_path = root / path[1:]
    if make_dirs and not file_path.parent.exists():
        try:
            make_dir(root, os.path.dirname(path), make_parents=True, permissions=None)
        except pebble.PathError as e:
            # Real Pebble reports make_dirs failures with this prefix.
            raise pebble.PathError(e.kind, f'cannot create directory: {e.message}') from None
    permissions = permissions if permissions is not None else 0o644
    if _is_mount_point(mount_locations, path):
        # A mount point models a real mount: pushing writes the content
        # through to the mounted file, keeping its identity, rather than
        # replacing the path with a new file. This is deliberate and follows
        # the Mount docstring; a real file bind mount would instead make
        # Pebble's rename fail with EBUSY.
        if file_path.is_dir():
            raise pebble.PathError('generic-file-error', f'rename {path}.~ {path}: file exists')
        try:
            _write_source_to(file_path, source, encoding)
            os.chmod(file_path, permissions)
        except OSError as e:
            raise path_error('open', path, e) from None
        return
    # Real Pebble writes the content to a temporary sibling file and renames
    # it over the target, so pushing replaces symlinks and other
    # non-directories, and only fails if the target is a directory.
    # Real Pebble uses '<name>.<random digits>~'; a fixed name keeps the
    # error messages (which include it) deterministic.
    temp_path = file_path.with_name(file_path.name + '.~')
    try:
        _write_source_to(temp_path, source, encoding)
        os.chmod(temp_path, permissions)
    except OSError as e:
        _remove_quietly(temp_path)
        raise path_error('open', f'{path}.~', e) from None
    if file_path.is_dir() and not file_path.is_symlink():
        _remove_quietly(temp_path)
        raise pebble.PathError('generic-file-error', f'rename {path}.~ {path}: file exists')
    try:
        os.rename(temp_path, file_path)
    except OSError as e:
        _remove_quietly(temp_path)
        raise path_error('rename', f'{path}.~ {path}', e) from None


def list_files(
    root: pathlib.Path,
    path: str,
    *,
    pattern: str | None,
    itself: bool,
    mount_locations: MountLocations,
) -> list[pebble.FileInfo]:
    """List the files at the container path `path` in the mock filesystem at `root`."""
    file_path = root / path[1:]
    # Real Pebble stats the path (following symlinks) and reports a missing
    # path as a 404 and anything else (for example a path below a file, or a
    # looping symlink) as a 400.
    try:
        info = file_path.stat()
    except OSError as e:
        raise files_api_error('stat', path, e) from None
    # The queried path itself is followed and reported as its target's type,
    # but entries within a directory listing are reported unfollowed: a
    # symlink entry stays a symlink, as real Pebble does.
    files = [file_path]
    is_entry_listing = False
    if stat.S_ISDIR(info.st_mode) and not itself:
        try:
            files = [file_path / entry for entry in os.listdir(file_path)]
            is_entry_listing = True
        except OSError as e:
            raise files_api_error('open', path, e) from None

    # Real Pebble filters with Go's path.Match and treats an empty pattern as
    # no filter.
    if pattern:
        filtered: list[pathlib.Path] = []
        for file in files:
            try:
                matched = go_path_match(pattern, file.name)
            except ValueError:
                raise _api_error(400, 'syntax error in pattern') from None
            if matched:
                filtered.append(file)
        files = filtered

    file_infos: list[pebble.FileInfo] = []
    for file in files:
        # A mount point appears as its target's type, like a real mount
        # point; any other symlink entry stays a symlink.
        entry_container_path = os.path.join(path, file.name) if is_entry_listing else path
        follow = not is_entry_listing or _is_mount_point(mount_locations, entry_container_path)
        try:
            file_info = build_fileinfo(file, follow_symlinks=follow)
        except OSError:
            # A mount whose source is missing (or loops) cannot be followed;
            # list the entry itself rather than failing the whole listing.
            file_info = build_fileinfo(file)
        rel_path = os.path.relpath(file_info.path, start=root)
        rel_path = '/' if rel_path == '.' else '/' + rel_path
        file_info.path = rel_path
        if rel_path == '/':
            file_info.name = '/'
        file_infos.append(file_info)
    return file_infos


def make_dir(
    root: pathlib.Path,
    path: str,
    *,
    make_parents: bool = False,
    permissions: int | None = None,
) -> None:
    """Create the directory at the container path `path` in the mock filesystem at `root`."""
    dir_path = root / path[1:]
    # Real Pebble (osutil.Mkdir) stats the path first: any stat failure means
    # the path is missing and gets created, an existing directory is
    # 'file exists' (or a no-op with make_parents), and any other existing
    # path is 'not a directory'.
    try:
        info = dir_path.stat()
    except OSError:
        info = None
    if info is not None:
        if not stat.S_ISDIR(info.st_mode):
            raise pebble.PathError('generic-file-error', f'mkdir {path}: not a directory')
        if make_parents:
            return
        raise pebble.PathError('generic-file-error', f'mkdir {path}: file exists')
    if make_parents and dir_path.parent != dir_path:
        make_dir(root, os.path.dirname(path), make_parents=True, permissions=permissions)
    # Real Pebble creates '<path>.mkdir-new' and renames it into place, which
    # fails with 'not a directory' when the missing path turns out to be a
    # symlink (broken or looping). A failed rename leaves the temporary
    # directory behind, in Pebble as here.
    temp_path = dir_path.with_name(dir_path.name + '.mkdir-new')
    try:
        temp_path.mkdir()
    except FileExistsError:
        pass
    except OSError as e:
        raise path_error('mkdir', f'{path}.mkdir-new', e) from None
    os.chmod(temp_path, permissions if permissions is not None else 0o755)
    try:
        os.rename(temp_path, dir_path)
    except OSError as e:
        raise path_error('rename', f'{path}.mkdir-new {path}', e) from None


def _recursive_prechecks(root: pathlib.Path, file_path: pathlib.Path, path: str) -> bool:
    """Mirror the first steps of Go's os.RemoveAll, which Pebble uses.

    RemoveAll first tries a plain remove (unlink, then rmdir) and is done if
    that succeeds or the path doesn't exist. Otherwise it opens the parent
    directory before recursing, so a parent that cannot be opened is reported
    as 'open <parent>: <reason>'. Returns True if the path was removed.
    """
    try:
        file_path.unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        pass
    try:
        file_path.rmdir()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        pass
    parent = os.path.dirname(path)
    if path != '/':
        # O_NONBLOCK so that a FIFO parent cannot hang the test, which real
        # Pebble would.
        try:
            os.close(os.open(root / parent[1:], os.O_RDONLY | os.O_NONBLOCK))
        except OSError as e:
            raise path_error('open', parent, e) from None
    return False


def remove_path(
    root: pathlib.Path,
    path: str,
    *,
    recursive: bool = False,
    mount_locations: MountLocations,
) -> None:
    """Remove the container path `path` from the mock filesystem at `root`."""
    file_path = root / path[1:]
    if recursive:
        # Mount points cannot be removed. These checks come before anything
        # is deleted, since a plain unlink would remove the mount's symlink.
        # Real Pebble (os.RemoveAll) would delete the other entries,
        # including the mounted contents, before failing with EBUSY; nothing
        # is deleted here, because mount sources are the test's own files.
        if _is_mount_point(mount_locations, path) or _contains_mount_point(mount_locations, path):
            raise pebble.PathError('generic-file-error', f'remove {path}: device or resource busy')
        if _recursive_prechecks(root, file_path, path):
            return
    # Real Pebble removes the path itself: a symlink is unlinked, never
    # followed, however broken or looping its target is. lstat, rather than
    # exists(), so that broken links and loops are not 'not found', and so
    # that paths below a non-directory report their real errno.
    try:
        info = file_path.lstat()
    except FileNotFoundError:
        if recursive:
            return
        raise pebble.PathError('not-found', f'remove {path}: no such file or directory') from None
    except OSError as e:
        raise path_error('remove', path, e) from None
    if _is_mount_point(mount_locations, path):
        # A mount point cannot be removed, like a real mount point.
        raise pebble.PathError('generic-file-error', f'remove {path}: device or resource busy')
    if stat.S_ISDIR(info.st_mode):
        if recursive:
            try:
                shutil.rmtree(file_path)
            except OSError as e:
                raise path_error('remove', path, e) from None
        else:
            try:
                file_path.rmdir()
            except OSError as e:
                raise path_error('remove', path, e) from None
    else:
        try:
            file_path.unlink()
        except OSError as e:
            raise path_error('remove', path, e) from None
