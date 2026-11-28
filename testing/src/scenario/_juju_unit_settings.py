# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""The relation unit databag keys that Juju manages itself.

When a unit enters a relation's scope, Juju writes the unit's addresses to its
databag for that relation. Which keys Juju writes, and whether the charm can
change them, depends on the Juju version. All of those rules are in this
module, so that when Juju changes them there's one place to update.
"""

from __future__ import annotations

from collections.abc import Iterable

from ops import JujuVersion

from .state import Network, PeerRelation, RelationBase, State, SubordinateRelation

INGRESS_ADDRESS = 'ingress-address'
EGRESS_SUBNETS = 'egress-subnets'
PRIVATE_ADDRESS = 'private-address'

JUJU_MANAGED_KEYS = frozenset({INGRESS_ADDRESS, EGRESS_SUBNETS, PRIVATE_ADDRESS})
"""Every key that any supported Juju version writes to a unit databag."""

# Documentation address ranges (RFC 5737), distinct from the default Network's
# 192.0.2.0, so that a charm building a list of units gets distinct members.
_REMOTE_UNIT_NETWORK = '203.0.113'
_PEER_UNIT_NETWORK = '198.51.100'


def juju_managed_keys(
    juju_version: str,
    *,
    ingress_addresses: Iterable[str],
    egress_subnets: Iterable[str],
) -> dict[str, str]:
    """The keys and values that Juju writes to a unit databag on entering scope.

    On Juju 3, ``private-address`` and ``ingress-address`` are both the first
    ingress address. Juju 4 only writes ``ingress-address``. ``egress-subnets``
    is the comma-separated list of egress subnets. A key is left out when
    there's nothing to fill it from.
    """
    ingress = list(ingress_addresses)
    egress = list(egress_subnets)
    keys: dict[str, str] = {}
    if egress:
        keys[EGRESS_SUBNETS] = ','.join(egress)
    if ingress:
        keys[INGRESS_ADDRESS] = ingress[0]
        if JujuVersion(juju_version).major < 4:
            keys[PRIVATE_ADDRESS] = ingress[0]
    return keys


def charm_can_write(key: str, juju_version: str) -> bool:
    """Whether Juju keeps a charm's write (or delete) of a key in its own unit databag.

    Juju 4 silently drops the charm's changes to ``ingress-address`` and
    ``egress-subnets`` when it commits the hook. On Juju 3, the charm's changes
    are kept (until the next ``config-changed`` hook, which Scenario doesn't
    model).
    """
    if JujuVersion(juju_version).major >= 4:
        return key not in (INGRESS_ADDRESS, EGRESS_SUBNETS)
    return True


def local_unit_network(state: State, endpoint: str) -> Network:
    """The network that Juju uses for this unit's addresses on an endpoint."""
    try:
        return state.get_network(endpoint)
    except KeyError:
        return Network(endpoint)


def local_unit_keys(state: State, endpoint: str, juju_version: str) -> dict[str, str]:
    """The Juju-managed keys for this unit's databag in a relation on ``endpoint``."""
    network = local_unit_network(state, endpoint)
    return juju_managed_keys(
        juju_version,
        ingress_addresses=network.ingress_addresses,
        egress_subnets=network.egress_subnets,
    )


def remote_unit_keys(
    state: State,
    relation: RelationBase,
    unit_id: int,
    juju_version: str,
) -> dict[str, str]:
    """The Juju-managed keys for another unit's databag in ``relation``.

    The principal unit of a subordinate is on the same machine, so it has the
    same addresses as this unit. Other units get an address made up from the
    unit ID, from one documentation range for peers and another for remote
    units. The unit ID wraps at 256.
    """
    if isinstance(relation, SubordinateRelation):
        return local_unit_keys(state, relation.endpoint, juju_version)
    network = _PEER_UNIT_NETWORK if isinstance(relation, PeerRelation) else _REMOTE_UNIT_NETWORK
    address = f'{network}.{unit_id % 256}'
    return juju_managed_keys(
        juju_version, ingress_addresses=[address], egress_subnets=[f'{address}/32']
    )
