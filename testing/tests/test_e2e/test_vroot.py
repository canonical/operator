# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import os
import tempfile
import warnings
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from scenario import Context, State

from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import ActiveStatus

from ..helpers import trigger


class MyCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'my-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        foo = self.framework.charm_dir / 'src' / 'foo.bar'
        baz = self.framework.charm_dir / 'src' / 'baz' / 'qux.kaboodle'

        self.unit.status = ActiveStatus(f'{foo.read_text()} {baz.read_text()}')


@pytest.fixture
def charm_virtual_root() -> Generator[Path]:
    with tempfile.TemporaryDirectory() as mycharm_virtual_root:
        t = Path(mycharm_virtual_root)
        src = t / 'src'
        src.mkdir()
        foobar = src / 'foo.bar'
        foobar.write_text('hello')

        baz = src / 'baz'
        baz.mkdir(parents=True)
        quxcos = baz / 'qux.kaboodle'
        quxcos.write_text('world')

        yield t


def test_charm_virtual_root(charm_virtual_root: Path):
    out = trigger(
        State(),
        'start',
        charm_type=MyCharm,
        meta=dict(MyCharm.META),
        charm_root=charm_virtual_root,
    )
    assert out.unit_status == ActiveStatus('hello world')


class CwdCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'my-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        self.unit.status = ActiveStatus(os.getcwd())


def test_cwd_unchanged_by_default():
    cwd_before = os.getcwd()
    ctx = Context(CwdCharm, meta=dict(CwdCharm.META))
    with ctx(ctx.on.start(), State()) as mgr:
        mgr.run()
        # By default, Scenario leaves the test runner working directory in
        # place rather than chdir'ing to the charm root.
        assert mgr.charm.unit.status.message == cwd_before
    assert os.getcwd() == cwd_before


def test_cwd_is_charm_root_when_opted_in(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('SCENARIO_CHDIR_TO_CHARM_ROOT', '1')
    cwd_before = os.getcwd()
    ctx = Context(CwdCharm, meta=dict(CwdCharm.META))
    with ctx(ctx.on.start(), State()) as mgr:
        mgr.run()
        # With the opt-in env var, cwd matches charm_dir to match Juju.
        assert mgr.charm.unit.status.message == str(mgr.charm.framework.charm_dir)
    # The original working directory is restored after the event is handled.
    assert os.getcwd() == cwd_before


class RelativeOpenCharm(CharmBase):
    META: Mapping[str, Any] = {'name': 'my-charm'}
    REL_PATH = 'metadata.yaml'

    def __init__(self, framework: Framework):
        super().__init__(framework)
        try:
            with open(self.REL_PATH):
                pass
        except OSError:
            pass


def test_relative_path_open_emits_deprecation_warning(
    charm_virtual_root: Path, monkeypatch: pytest.MonkeyPatch
):
    # Ensure the env var is not set so we exercise the default (warn) path.
    monkeypatch.delenv('SCENARIO_CHDIR_TO_CHARM_ROOT', raising=False)
    # The relative path the charm opens exists at charm_root but not at the
    # test cwd, so behaviour would differ between current and future defaults.
    (charm_virtual_root / RelativeOpenCharm.REL_PATH).write_text('name: my-charm\n')
    ctx = Context(
        RelativeOpenCharm,
        meta=dict(RelativeOpenCharm.META),
        charm_root=charm_virtual_root,
    )
    with pytest.warns(DeprecationWarning, match='SCENARIO_CHDIR_TO_CHARM_ROOT'):
        ctx.run(ctx.on.start(), State())


def test_relative_path_open_no_warning_when_opted_in(
    charm_virtual_root: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv('SCENARIO_CHDIR_TO_CHARM_ROOT', '1')
    (charm_virtual_root / RelativeOpenCharm.REL_PATH).write_text('name: my-charm\n')
    ctx = Context(
        RelativeOpenCharm,
        meta=dict(RelativeOpenCharm.META),
        charm_root=charm_virtual_root,
    )
    with warnings.catch_warnings():
        warnings.simplefilter('error', DeprecationWarning)
        ctx.run(ctx.on.start(), State())


def test_charm_virtual_root_cleanup_if_exists(charm_virtual_root: Path):
    meta_file = charm_virtual_root / 'metadata.yaml'
    raw_ori_meta = yaml.safe_dump({'name': 'karl'})
    meta_file.write_text(raw_ori_meta)

    ctx = Context(MyCharm, meta=dict(MyCharm.META), charm_root=charm_virtual_root)
    with ctx(
        ctx.on.start(),
        State(),
    ) as mgr:
        assert meta_file.exists()
        assert meta_file.read_text() == yaml.safe_dump({'name': 'my-charm'})
        assert mgr.charm.meta.name == 'my-charm'  # not karl! Context.meta takes precedence
        mgr.run()
        assert meta_file.exists()

    # meta file was restored to its previous contents
    assert meta_file.read_text() == raw_ori_meta
    assert meta_file.exists()


def test_charm_virtual_root_cleanup_if_not_exists(charm_virtual_root: Path):
    meta_file = charm_virtual_root / 'metadata.yaml'

    assert not meta_file.exists()

    ctx = Context(MyCharm, meta=dict(MyCharm.META), charm_root=charm_virtual_root)
    with ctx(
        ctx.on.start(),
        State(),
    ) as mgr:
        assert meta_file.exists()
        assert meta_file.read_text() == yaml.safe_dump({'name': 'my-charm'})
        mgr.run()
        assert not meta_file.exists()

    assert not meta_file.exists()
