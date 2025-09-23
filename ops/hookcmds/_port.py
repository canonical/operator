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
from typing import (
    Iterable,
    cast,
    overload,
)

from ._types import Port
from ._utils import run


@overload
def close_port(
    protocol: str,
    port: int | None = None,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str],
) -> None: ...
@overload
def close_port(
    protocol: str | None,
    port: int,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str],
) -> None: ...
def close_port(
    protocol: str | None = None,
    port: int | None = None,
    *,
    to_port: int | None = None,
    endpoints: str | Iterable[str],
):
    """Register a request to close a port or port range."""
    args = ['close-port']
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
    run(*args)


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

    Args:
        protocol: Open the port(s) for the specified protocol.
        port: If ``to_port`` is not specified, open only this port.
        to_port: Open a range of ports from ``port`` to ``to_port``.
        endpoints: If not provided, ports will be opened for all defined
            application endpoints. To constrain the open request to specific
            endpoints, provide one or more endpoint names.
    """
    args = ['open-port']
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
    run(*args)


def opened_ports(*, endpoints: bool = False) -> list[Port]:
    """List all ports or port ranges opened by the unit.

    Args:
        endpoints: If ``True``, each entry in the port list will be augmented
            with a list of endpoints that the port applies to. If a port applies
            to all endpoints, this will be indicated by an endpoint of ``*``.
    """
    args = ['opened-ports']
    if endpoints:
        args.append('--endpoints')
    output = cast('list[str]', json.loads(run(*args, '--format=json')))
    ports: list[Port] = []
    # Each port from Juju will look like one of these:
    # 'icmp'
    # '80/tcp' or '42/udp' (where the port could be any port number)
    # '80' (where this could be any port number)
    # '8000-8999/tcp' or '8000-8999/udp' (where the two numbers can be any ports)
    # '8000-8999' (where these could be any port number)
    # If ``--endpoints`` is used, then each port will be followed by a
    # (possibly empty) tuple of endpoints.
    for port in output:
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
            port = int(port)
        if protocol not in ('tcp', 'udp', 'icmp'):
            raise ValueError(f'Unexpected protocol from Juju: {protocol}')
        ports.append(Port(protocol=protocol, port=port, to_port=to_port, endpoints=port_endpoints))
    return ports
