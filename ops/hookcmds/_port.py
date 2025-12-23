# Copyright 2025 Canonical Ltd.
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

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import overload

from ._types import Port
from ._utils import run


@overload
def close_port(
    protocol: str,
    port: int | None = None,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str] | None = None,
) -> None: ...
@overload
def close_port(
    protocol: str | None,
    port: int,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str] | None = None,
) -> None: ...
def close_port(
    protocol: str | None = None,
    port: int | None = None,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str] | None = None,
):
    """Register a request to close a port or port range.

    For more details, see:
    `Juju | Hook commands | close-port <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/close-port/>`_
    """
    args: list[str] = []
    if endpoints:
        if isinstance(endpoints, str):
            endpoints = [endpoints]
        args.extend(['--endpoints', ','.join(endpoints)])
    if port is None:
        if protocol is None:
            raise TypeError('You must provide a port or protocol.')
        args.append(protocol)
    else:
        port_arg = f'{port}-{to_port}' if to_port is not None else str(port)
        if protocol is not None:
            port_arg = f'{port_arg}/{protocol}'
        args.append(port_arg)
    run('close-port', *args)


@overload
def open_port(
    protocol: str,
    port: int | None = None,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str] | None = None,
) -> None: ...
@overload
def open_port(
    protocol: str | None,
    port: int,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str] | None = None,
) -> None: ...
def open_port(
    protocol: str | None = None,
    port: int | None = None,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str] | None = None,
):
    """Register a request to open a port or port range.

    For more details, see:
    `Juju | Hook commands | open-port <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/open-port/>`_

    Args:
        protocol: Open the port(s) for the specified protocol.
        port: If ``to_port`` is not specified, open only this port.
        to_port: Open a range of ports from ``port`` to ``to_port``.
        endpoints: If not provided, ports will be opened for all defined
            application endpoints. To constrain the open request to specific
            endpoints, provide one or more endpoint names.
    """
    args: list[str] = []
    if endpoints:
        if isinstance(endpoints, str):
            endpoints = [endpoints]
        args.extend(['--endpoints', ','.join(endpoints)])
    if protocol is None and port is None:
        raise TypeError('Either protocol or port must be specified')
    if port is None:
        if protocol is None:
            raise TypeError('You must provide a port or protocol.')
        args.append(protocol)
    else:
        port_arg = f'{port}-{to_port}' if to_port is not None else str(port)
        if protocol is not None:
            port_arg = f'{port_arg}/{protocol}'
        args.append(port_arg)
    run('open-port', *args)


def opened_ports(*, endpoints: bool = False) -> list[Port]:
    """List all ports or port ranges opened by the unit.

    For more details, see:
    `Juju | Hook commands | opened-ports <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/opened-ports/>`_

    Args:
        endpoints: If ``True``, each entry in the port list will be augmented
            with a list of endpoints that the port applies to. If a port applies
            to all endpoints, this will be indicated by an endpoint of ``*``.
    """
    args: list[str] = []
    if endpoints:
        args.append('--endpoints')
    stdout = run('opened-ports', *args, '--format=json')
    result: list[str] = json.loads(stdout)
    ports: list[Port] = []
    # Each port from Juju will look like one of these:
    # 'icmp'
    # '80/tcp' or '42/udp' (where the port could be any port number)
    # '80' (where this could be any port number)
    # '8000-8999/tcp' or '8000-8999/udp' (where the two numbers can be any ports)
    # '8000-8999' (where these could be any port number)
    # If ``--endpoints`` is used, then each port will be followed by a
    # (possibly empty) tuple of endpoints.
    for port in result:
        if endpoints:
            port, port_endpoints = port.rsplit(' ', 1)
            port_endpoints = [e.strip() for e in port_endpoints.strip('()').split(',')]
        else:
            port_endpoints = None
        if '/' in port:
            port, protocol = port.split('/', 1)
        else:
            protocol = None
        if '-' in port:
            port, to_port = port.split('-')
            to_port = int(to_port)
        else:
            to_port = None
        if port == 'icmp':
            protocol = port
            port = None
        else:
            protocol = protocol or 'tcp'
            port = int(port)
        # The type: ignore is required because we know that protocol will be tcp, udp, or icmp
        # but we can't raise if not, because model.py only emits a warning in that case, and
        # we need to maintain backwards compatibility.
        port = Port(
            protocol=protocol,  # type: ignore
            port=port,
            to_port=to_port,
            endpoints=port_endpoints,
        )
        ports.append(port)
    return ports
