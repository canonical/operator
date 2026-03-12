# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml
from scenario import Context, Relation, State
from scenario.errors import ContextSetupError, MetadataNotFoundError
from scenario.state import _CharmSpec

from ops import CharmBase

CHARM = """
from ops import CharmBase

class MyCharm(CharmBase): pass
"""


@contextmanager
def import_name(name: str, source: Path) -> Iterator[type[CharmBase]]:
    pkg_path = str(source.parent)
    sys.path.append(pkg_path)
    charm = importlib.import_module('mycharm')
    obj = getattr(charm, name)
    sys.path.remove(pkg_path)
    yield obj
    del sys.modules['mycharm']


@contextmanager
def create_tempcharm(
    root: Path,
    charm: str = CHARM,
    meta: dict[str, Any] | None = None,
    actions: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    name: str = 'MyCharm',
    legacy: bool = False,
) -> Iterator[type[CharmBase]]:
    src = root / 'src'
    src.mkdir(parents=True)
    charmpy = src / 'mycharm.py'
    charmpy.write_text(charm)

    # we add a charmcraft.yaml file to verify that _CharmSpec._load_metadata
    # is able to tell that the presence of charmcraft.yaml ALONE is not enough
    # to make this a valid charm
    charmcraft = {'builds-on': "literally anywhere! isn't that awesome?"}
    (root / 'charmcraft.yaml').write_text(yaml.safe_dump(charmcraft))

    if legacy:
        if meta is not None:
            (root / 'metadata.yaml').write_text(yaml.safe_dump(meta))

        if actions is not None:
            (root / 'actions.yaml').write_text(yaml.safe_dump(actions))

        if config is not None:
            (root / 'config.yaml').write_text(yaml.safe_dump(config))
    else:
        unified_meta = meta or {}

        if actions:
            unified_meta['actions'] = actions
        if config:
            unified_meta['config'] = config
        if unified_meta:
            (root / 'charmcraft.yaml').write_text(yaml.safe_dump(unified_meta))

    with import_name(name, charmpy) as charm_class:
        yield charm_class


def test_autoload_no_meta_fails(tmp_path: Path):
    with create_tempcharm(tmp_path) as charm:
        with pytest.raises(MetadataNotFoundError):
            _CharmSpec.autoload(charm)


def test_autoload_no_type_fails(tmp_path: Path):
    with create_tempcharm(tmp_path, meta={'name': 'foo'}) as charm:
        with pytest.raises(MetadataNotFoundError):
            _CharmSpec.autoload(charm)


def test_autoload_legacy_no_meta_fails(tmp_path: Path):
    with create_tempcharm(tmp_path, legacy=True) as charm:
        with pytest.raises(MetadataNotFoundError):
            _CharmSpec.autoload(charm)


def test_autoload_legacy_no_type_passes(tmp_path: Path):
    with create_tempcharm(tmp_path, legacy=True, meta={'name': 'foo'}) as charm:
        _CharmSpec.autoload(charm)


@pytest.mark.parametrize('config_type', ('charm', 'foo'))
def test_autoload_legacy_type_passes(tmp_path: Path, config_type: str):
    with create_tempcharm(
        tmp_path, legacy=True, meta={'type': config_type, 'name': 'foo'}
    ) as charm:
        _CharmSpec.autoload(charm)


@pytest.mark.parametrize('legacy', (True, False))
def test_meta_autoload(tmp_path: Path, legacy: bool):
    with create_tempcharm(
        tmp_path,
        legacy=legacy,
        meta={'type': 'charm', 'name': 'foo', 'summary': 'foo', 'description': 'foo'},
    ) as charm:
        ctx = Context(charm)
        ctx.run(ctx.on.start(), State())


@pytest.mark.parametrize('legacy', (True, False))
def test_no_meta_raises(tmp_path: Path, legacy: bool):
    with create_tempcharm(
        tmp_path,
        legacy=legacy,
    ) as charm:
        # metadata not found:
        with pytest.raises(ContextSetupError):
            Context(charm)


@pytest.mark.parametrize('legacy', (True, False))
def test_relations_ok(tmp_path: Path, legacy: bool):
    with create_tempcharm(
        tmp_path,
        legacy=legacy,
        meta={
            'type': 'charm',
            'summary': 'foo',
            'description': 'foo',
            'name': 'josh',
            'requires': {'cuddles': {'interface': 'arms'}},
        },
    ) as charm:
        # this would fail if there were no 'cuddles' relation defined in meta
        ctx = Context(charm)
        ctx.run(ctx.on.start(), State(relations={Relation('cuddles')}))


@pytest.mark.parametrize('legacy', (True, False))
def test_config_defaults(tmp_path: Path, legacy: bool):
    with create_tempcharm(
        tmp_path,
        legacy=legacy,
        meta={
            'type': 'charm',
            'name': 'josh',
            'summary': 'foo',
            'description': 'foo',
        },
        config={'options': {'foo': {'type': 'bool', 'default': True}}},
    ) as charm:
        # this would fail if there were no 'cuddles' relation defined in meta
        ctx = Context(charm)
        with ctx(ctx.on.start(), State()) as mgr:
            mgr.run()
            assert mgr.charm.config['foo'] is True


class TestExtensions:
    """Tests for charmcraft extension autoloading."""

    def test_extension_adds_metadata(self, tmp_path):
        """An extension injects its metadata (containers, requires, etc.)."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            assert 'flask-app' in spec.meta.get('containers', {})
            assert 'ingress' in spec.meta.get('requires', {})
            assert 'secret-storage' in spec.meta.get('peers', {})
            assert 'metrics-endpoint' in spec.meta.get('provides', {})
            assert 'flask-app-image' in spec.meta.get('resources', {})
            assert 'k8s-api' in spec.meta.get('assumes', [])

    def test_extension_adds_config(self, tmp_path):
        """An extension injects its config options."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            assert spec.config is not None
            options = spec.config.get('options', {})
            assert 'flask-debug' in options
            assert 'webserver-workers' in options

    def test_extension_adds_actions(self, tmp_path):
        """An extension injects its actions."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            assert spec.actions is not None
            assert 'rotate-secret-key' in spec.actions

    def test_local_meta_overlaps_extension_errors(self, tmp_path):
        """Overlapping metadata keys with extension cause an error."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
                'requires': {
                    'ingress': {'interface': 'custom-ingress', 'limit': 5},
                },
            },
        ) as charm:
            with pytest.raises(ValueError, match=r'overlapping keys.*requires.*flask-framework'):
                _CharmSpec.autoload(charm)

    def test_local_meta_no_overlap_with_extension(self, tmp_path):
        """Non-overlapping local metadata keys merge with extension."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
                'requires': {
                    'my-custom-relation': {'interface': 'custom'},
                },
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            # Local-only entry is present.
            assert 'my-custom-relation' in spec.meta['requires']
            # Extension entries are still present.
            assert 'ingress' in spec.meta['requires']
            assert 'logging' in spec.meta['requires']

    def test_local_config_overlaps_extension_errors(self, tmp_path):
        """Overlapping config options with extension cause an error."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
            config={
                'options': {
                    'flask-debug': {'type': 'boolean', 'default': True},
                    'my-custom-option': {'type': 'string'},
                },
            },
        ) as charm:
            with pytest.raises(
                ValueError, match=r'overlapping keys.*config\.options.*flask-framework'
            ):
                _CharmSpec.autoload(charm)

    def test_local_config_no_overlap_with_extension(self, tmp_path):
        """Non-overlapping local config options merge with extension."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
            config={
                'options': {
                    'my-custom-option': {'type': 'string'},
                },
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            options = spec.config['options']
            # Local-only option is present.
            assert 'my-custom-option' in options
            # Extension-only options are still present.
            assert 'flask-debug' in options
            assert 'webserver-workers' in options

    def test_local_actions_overlap_extension_errors(self, tmp_path):
        """Overlapping actions with extension cause an error."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
            actions={
                'rotate-secret-key': {'description': 'custom rotate'},
                'my-action': {'description': 'custom action'},
            },
        ) as charm:
            with pytest.raises(ValueError, match=r'overlapping keys.*actions.*flask-framework'):
                _CharmSpec.autoload(charm)

    def test_local_actions_no_overlap_with_extension(self, tmp_path):
        """Non-overlapping local actions merge with extension."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
            actions={
                'my-action': {'description': 'custom action'},
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            # Local-only action is present.
            assert 'my-action' in spec.actions
            # Extension action is still present.
            assert 'rotate-secret-key' in spec.actions

    def test_local_assumes_merged_with_extension(self, tmp_path):
        """Local assumes list is merged with extension assumes."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
                'assumes': ['juju >= 3.1'],
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            assumes = spec.meta['assumes']
            assert 'k8s-api' in assumes
            assert 'juju >= 3.1' in assumes

    def test_django_extension_has_create_superuser(self, tmp_path):
        """Django extension adds the create-superuser action."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-django',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['django-framework'],
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            assert 'create-superuser' in spec.actions
            assert 'rotate-secret-key' in spec.actions

    def test_unknown_extension_warns(self, tmp_path):
        """An unknown extension name emits a warning and is skipped."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-app',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['nonexistent-extension'],
            },
        ) as charm:
            with pytest.warns(UserWarning, match='Unknown charmcraft extension'):
                spec = _CharmSpec.autoload(charm)
            # No extension data merged, but the charm still loads.
            assert spec.meta['name'] == 'my-app'

    def test_extension_stripped_from_meta(self, tmp_path):
        """The 'extensions' key should not remain in the loaded meta."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
        ) as charm:
            spec = _CharmSpec.autoload(charm)
            assert 'extensions' not in spec.meta

    def test_extension_with_relations_in_context(self, tmp_path):
        """Relations from an extension can be used in a Context run."""
        with create_tempcharm(
            tmp_path,
            meta={
                'type': 'charm',
                'name': 'my-flask',
                'summary': 'foo',
                'description': 'foo',
                'extensions': ['flask-framework'],
            },
        ) as charm:
            ctx = Context(charm)
            ctx.run(
                ctx.on.start(),
                State(relations={Relation('ingress')}),
            )
