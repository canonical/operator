#!/usr/bin/env python3

import os
import sys
from pathlib import Path

import yaml

import ops.charm
import ops.framework
import ops.model

CHARM_STATE_FILE = '.unit-state.db'


def debugf(format, *args, **kwargs):
    pass


def _get_charm_dir():
    charm_dir = os.environ.get("JUJU_CHARM_DIR")
    if charm_dir is None:
        # Assume $JUJU_CHARM_DIR/lib/op/main.py structure.
        charm_dir = Path(f'{__file__}/../../..').resolve()
    else:
        charm_dir = Path(charm_dir).resolve()
    return charm_dir


def _load_metadata(charm_dir):
    with open(charm_dir / 'metadata.yaml') as f:
        metadata = yaml.load(f, Loader=yaml.SafeLoader)
    return metadata


def _create_event_link(charm_dir, event_dir, target_path, bound_event):
    """Create a symlink for a particular event.

    charm_dir -- A root directory of the charm
    bound_event -- An event for which to create a symlink.
    """
    # TODO: Handle function/action events here.
    if not issubclass(bound_event.event_type, ops.charm.HookEvent):
        raise RuntimeError(f'cannot create a symlink: unsupported event type {bound_event.event_type}')

    if not event_dir.exists():
        raise RuntimeError(f'cannot create event symlink: {event_dir} directory does not exist')

    event_path = event_dir / bound_event.event_kind.replace('_', '-')
    if not event_path.exists():
        # Ignore the non-symlink files or directories assuming the charm author knows what they are doing.
        debugf(f'Creating a new relative symlink at {event_path} pointing to {target_path}')
        event_path.symlink_to(target_path)


def _setup_event_links(charm_dir, charm):
    """Set up links for supported events that originate from Juju.

    Whether a charm can handle an event or not can be determined by
    introspecting which events are defined on it.

    Hooks or functions are created as symlinks to the charm code file which is determined by inspecting
    symlinks provided by the charm author at hooks/install or hooks/start.

    charm_dir -- A root directory of the charm.
    charm -- An instance of the Charm class.
    """
    # CPython has different implementations for populating sys.argv[0] for Linux and Windows. For Windows
    # it is always an absolute path (any symlinks are resolved) while for Linux it can be a relative path.
    charm_exec_path = os.path.relpath(os.path.realpath(sys.argv[0]), charm_dir / 'hooks')
    for bound_event in charm.on.events().values():
        # Only events that originate from Juju need symlinks.
        # TODO: handle function/action events here.
        if issubclass(bound_event.event_type, ops.charm.HookEvent):
            event_dir = charm_dir / 'hooks'
            _create_event_link(charm_dir, event_dir, charm_exec_path, bound_event)


def _emit_charm_event(charm, event_name):
    """Emits a charm event based on a Juju event name.

    charm -- A charm instance to emit an event from.
    event_name -- A Juju event name to emit on a charm.
    """
    formatted_event_name = event_name.replace('-', '_')
    event_to_emit = None
    try:
        event_to_emit = getattr(charm.on, formatted_event_name)
    except AttributeError:
        debugf(f"event {formatted_event_name} not defined for {charm}")

    # If the event is not supported by the charm implementation, do
    # not error out or try to emit it. This is to support rollbacks.
    if event_to_emit is not None:
        args, kwargs = _get_event_args(charm, event_to_emit)
        debugf(f'Emitting Juju event {event_name}')
        event_to_emit.emit(*args, **kwargs)


def _get_event_args(charm, bound_event):
    event_type = bound_event.event_type
    model = charm.framework.model

    if issubclass(event_type, ops.charm.RelationEvent):
        relation_name = os.environ['JUJU_RELATION']
        relation_id = int(os.environ['JUJU_RELATION_ID'].split(':')[-1])
        relation = model.get_relation(relation_name, relation_id)
    else:
        relation = None

    remote_app_name = os.environ.get('JUJU_REMOTE_APP', '')
    remote_unit_name = os.environ.get('JUJU_REMOTE_UNIT', '')
    if remote_app_name or remote_unit_name:
        if not remote_app_name:
            if '/' not in remote_unit_name:
                raise RuntimeError(f'invalid remote unit name: {remote_unit_name}')
            remote_app_name = remote_unit_name.split('/')[0]
        args = [relation, model.get_app(remote_app_name)]
        if remote_unit_name:
            args.append(model.get_unit(remote_unit_name))
        return args, {}
    elif relation:
        return [relation], {}
    return [], {}


def main(charm_class):
    """Setup the charm and dispatch the observed event.

    The event name is based on the way this executable was called (argv[0]).
    """

    charm_dir = _get_charm_dir()

    # Process the Juju event relevant to the current hook execution
    # JUJU_HOOK_NAME or JUJU_ACTION_NAME are not used to support simulation
    # of events from debugging sessions.
    # TODO: For Windows, when symlinks are used, this is not a valid method of getting an event name (see LP: #1854505).
    juju_event_name = Path(sys.argv[0]).name

    meta = ops.charm.CharmMeta(_load_metadata(charm_dir))
    unit_name = os.environ['JUJU_UNIT_NAME']
    model = ops.model.Model(unit_name, meta, ops.model.ModelBackend())

    # TODO: If Juju unit agent crashes after exit(0) from the charm code
    # the framework will commit the snapshot but Juju will not commit its
    # operation.
    charm_state_path = charm_dir / CHARM_STATE_FILE
    framework = ops.framework.Framework(charm_state_path, charm_dir, meta, model)
    try:
        charm = charm_class(framework, None)

        # When a charm is force-upgraded and a unit is in an error state Juju does not run upgrade-charm and
        # instead runs the failed hook followed by config-changed. Given the nature of force-upgrading
        # the hook setup code is not triggered on config-changed.
        # 'start' event is included as Juju does not fire the install event for K8s charms (see LP: #1854635).
        if juju_event_name in ('install', 'start', 'upgrade-charm') or juju_event_name.endswith('-storage-attached'):
            _setup_event_links(charm_dir, charm)

        framework.reemit()

        _emit_charm_event(charm, juju_event_name)

        framework.commit()
    finally:
        framework.close()
