#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import pathlib
from typing import Dict

from ops.testing import _TestingFilesystem, _TestingStorageMount  # noqa


# todo consider duplicating the filesystem on State.copy() to be able to diff
#  and have true state snapshots
class _MockStorageMount(_TestingStorageMount):
    def __init__(self, location: pathlib.PurePosixPath, src: pathlib.Path):
        """Creates a new simulated storage mount.

        Args:
            location: The path within simulated filesystem at which this storage will be mounted.
            src: The temporary on-disk location where the simulated storage will live.
        """
        self._src = src
        self._location = location

        try:
            # for some reason this fails if src exists, even though exists_ok=True.
            super().__init__(location=location, src=src)
        except FileExistsError:
            pass


class _MockFileSystem(_TestingFilesystem):
    def __init__(self, mounts: Dict[str, _MockStorageMount]):
        super().__init__()
        self._mounts = mounts

    def add_mount(self, *args, **kwargs):  # noqa: U100
        raise NotImplementedError("Cannot mutate mounts; declare them all in State.")

    def remove_mount(self, *args, **kwargs):  # noqa: U100
        raise NotImplementedError("Cannot mutate mounts; declare them all in State.")
