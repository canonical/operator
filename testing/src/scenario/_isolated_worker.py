# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""The worker process that ``scenario._isolation`` starts to run one charm.

``python -m scenario._isolated_worker`` reads messages from stdin (see
``_worker_protocol``) and writes a response to stdout for each one. The first
message describes the charm. The worker imports it and responds with ``{}``,
or with ``{"error": <traceback>}`` and exits. Each later message is an event
and a ``State`` to run it on, and gets ``{"state": ...}`` or
``{"error": <traceback>}`` back.
"""

from __future__ import annotations

import importlib
import os
import pathlib
import sys
import traceback
from typing import Any

import ops

from . import _state_json
from ._worker_protocol import read_message, write_message
from .context import Context


def load_charm_type(charm_source: pathlib.Path) -> type[ops.CharmBase]:
    """Import ``src/charm.py`` from ``charm_source`` and return its charm class."""
    for directory in ('lib', 'src'):
        path = str(charm_source / directory)
        if path not in sys.path:
            sys.path.insert(0, path)
    module = importlib.import_module('charm')
    # Only classes defined in charm.py, so an imported base class doesn't count.
    charm_types = [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, ops.CharmBase)
        and value.__module__ == module.__name__
    ]
    if len(charm_types) != 1:
        names = [t.__name__ for t in charm_types]
        raise RuntimeError(
            f'Expected one CharmBase subclass in {charm_source}/src/charm.py, found {names}.'
        )
    return charm_types[0]


def run(
    charm_type: type[ops.CharmBase], setup: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Run one request's event, and return the response."""
    ctx = Context(
        charm_type,
        meta=setup['meta'],
        config=setup['config'],
        actions=setup['actions'],
        app_name=setup['app_name'],
        unit_id=request['unit_id'],
        juju_version=setup['juju_version'],
        app_trusted=setup['app_trusted'],
    )
    event = _state_json.decode_event(request['event'])
    state_in = _state_json.decode_state(request['state'])
    state_out = ctx.run(event, state_in)
    return {'state': _state_json.encode_state(state_out)}


def main() -> int:
    """Serve requests until stdin closes."""
    # Charms write to fd 1 directly, through subprocesses or C extensions, as
    # well as through sys.stdout. Responses go to a private copy of fd 1, and
    # fd 1 itself goes to stderr, which the test process reads separately.
    responses = os.fdopen(os.dup(1), 'wb')
    os.dup2(2, 1)
    requests = sys.stdin.buffer

    setup = read_message(requests)
    if setup is None:
        return 0
    # Ahead of the environment's own packages, so these win for the charm.
    sys.path[:0] = [entry for entry in setup['extra_sys_path'] if entry not in sys.path]
    try:
        charm_type = load_charm_type(pathlib.Path(setup['charm_source']))
    except (Exception, SystemExit):
        write_message({'error': traceback.format_exc()}, to=responses)
        return 1
    write_message({}, to=responses)
    while (request := read_message(requests)) is not None:
        try:
            response = run(charm_type, setup, request)
        except (Exception, SystemExit):
            # SystemExit too, so a charm calling sys.exit doesn't end the worker.
            response = {'error': traceback.format_exc()}
        write_message(response, to=responses)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
