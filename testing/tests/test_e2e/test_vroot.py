import ast
import importlib
import inspect
import os
import sys
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest
import yaml
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import ActiveStatus

from scenario import Context, State
from ..helpers import trigger


class MyCharm(CharmBase):
    META = {'name': 'my-charm'}

    def __init__(self, framework: Framework):
        super().__init__(framework)
        foo = self.framework.charm_dir / 'src' / 'foo.bar'
        baz = self.framework.charm_dir / 'src' / 'baz' / 'qux.kaboodle'

        self.unit.status = ActiveStatus(f'{foo.read_text()} {baz.read_text()}')


@pytest.fixture
def charm_virtual_root():
    with tempfile.TemporaryDirectory() as mycharm_virtual_root:
        t = Path(mycharm_virtual_root)
        (t / "somefile.txt").write_text("foo")

        src = t / 'src'
        src.mkdir()
        foobar = src / 'foo.bar'
        foobar.write_text('hello')

        baz = src / 'baz'
        baz.mkdir(parents=True)
        quxcos = baz / 'qux.kaboodle'
        quxcos.write_text('world')

        yield t


def test_charm_virtual_root(charm_virtual_root):
    out = trigger(
        State(),
        'start',
        charm_type=MyCharm,
        meta=MyCharm.META,
        charm_root=charm_virtual_root,
    )
    assert out.unit_status == ActiveStatus('hello world')


def test_charm_virtual_root_cleanup_if_metadata_file_exists(charm_virtual_root):
    meta_file = charm_virtual_root / 'metadata.yaml'
    raw_ori_meta = yaml.safe_dump({'name': 'karl'})
    meta_file.write_text(raw_ori_meta)

    ctx = Context(MyCharm, meta=MyCharm.META, charm_root=charm_virtual_root)
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


def test_charm_virtual_root_cleanup_if_not_metadata_file_exists(charm_virtual_root):
    meta_file = charm_virtual_root / 'metadata.yaml'

    assert not meta_file.exists()

    ctx = Context(MyCharm, meta=MyCharm.META, charm_root=charm_virtual_root)
    with ctx(
        ctx.on.start(),
        State(),
    ) as mgr:
        assert meta_file.exists()
        assert meta_file.read_text() == yaml.safe_dump({'name': 'my-charm'})
        mgr.run()
        assert not meta_file.exists()

    assert not meta_file.exists()


def test_charm_virtual_root_autoload(charm_virtual_root):
    # given a "real charm root"
    meta_file = charm_virtual_root / 'metadata.yaml'
    raw_ori_meta = yaml.safe_dump({'name': 'marx'})
    meta_file.write_text(raw_ori_meta)
    imports = dedent("""
    from ops.charm import CharmBase
    from ops.framework import Framework
    from ops.model import ActiveStatus
    """)
    (charm_virtual_root/'src'/'charm.py').write_text(imports+inspect.getsource(MyCharm))

    # make the temporary charm root importable; avoid messing with sys.path as we have many
    # conflicting 'src' and 'charm' modules lying around here
    cwd = os.getcwd()
    os.chdir(str(charm_virtual_root))
    sys.path.append(str(charm_virtual_root))
    tmpmodule = importlib.import_module(".charm", "src")
    os.chdir(cwd)

    # now we import MyCharm from the temporary module
    ctx = Context(tmpmodule.MyCharm, charm_root=charm_virtual_root)
    with ctx(
        ctx.on.start(),
        State(),
    ) as mgr:
        # verify all of the tempdir's contents are in the vroot copy created by the runtime
        vroot_copy = mgr.charm.framework.charm_dir
        for file in (
            # IRL, charmcraft shreds charmcraft.yaml in metadata/config/actions.yaml while packing.
            vroot_copy / 'metadata.yaml',
            vroot_copy / 'config.yaml',
            vroot_copy / 'actions.yaml',
            vroot_copy / 'somefile.txt',
            vroot_copy / 'src'/'foo.bar',
            vroot_copy / 'src'/'baz'/'qux.kaboodle',
        ):
            assert file.exists()
        mgr.run()

