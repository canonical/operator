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
import pathlib
import sys
from typing import (
    Any,
    Literal,
    Mapping,
    cast,
    overload,
)

from ._types import CloudSpec, GoalState, GoalStateDict, Network
from ._utils import run


def app_version_set(version: str):
    """Specify which version of the application is deployed.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/application-version-set/

    Args:
        version: the version of the application software the unit is running.
            This could be a package version number or some other useful identifier,
            such as a Git hash, that indicates the version of the deployed software.
            It shouldn't be confused with the charm revision.
    """
    run('application-version-set', version)


# config-get has an `--all` option, which we do not offer here. When `--all` is
# specified, Juju returns all config options, including those that are unset and
# have no default value. We do not currently have a use-case for `--all` and
# excluding it simplifies the method signature.
@overload
def config_get(key: str) -> bool | int | float | str: ...
@overload
def config_get(key: None = None) -> Mapping[str, bool | int | float | str]: ...
def config_get(
    key: str | None = None,
) -> Mapping[str, bool | int | float | str] | bool | int | float | str:
    """Retrieve application configuration.

    Note that 'secret' type options are returned as string secret IDs.

    If called without arguments, returns a dictionary containing all config
    settings that are either explicitly set, or which have a non-nil default
    value. If called with a key, it returns the value of that config option.
    Missing config keys are reported as nulls, and do not return an error.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/config-get/

    Args:
        key: The configuration option to retrieve.
    """
    args = ['--format=json']
    if key:
        args.append(key)
    stdout = run('config-get', *args)
    if key:
        result = cast('bool | int | float | str', json.loads(stdout))
    else:
        result = cast('dict[str, bool | int | float | str]', json.loads(stdout))
    return result


def credential_get() -> CloudSpec:
    """Access cloud credentials.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/credential-get/
    """
    stdout = run('credential-get', '--format=json')
    result = cast('dict[str, Any]', json.loads(stdout))
    return CloudSpec.from_dict(result)


def goal_state() -> GoalState:
    """Print the status of the charm's peers and related units.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/goal-state/
    """
    stdout = run('goal-state', '--format=json')
    result = cast('GoalStateDict', json.loads(stdout))
    return GoalState._from_dict(result)


def is_leader() -> bool:
    """Obtain the current leadership status for the unit the charm code is executing on.

    The value is not cached. It is accurate for 30s from the time the method is
    successfully called.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/is-leader/
    """
    stdout = run('is-leader', '--format=json')
    result = cast('bool', json.loads(stdout))
    return result


def juju_log(
    message: str, *, level: Literal['TRACE', 'DEBUG', 'INFO', 'WARNING', 'ERROR'] = 'INFO'
):
    """Write a message to the juju log.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/juju-log/

    Args:
        message: The message to log.
        level: Send the message at the given level.
    """
    run('juju-log', '--log-level', level, message)


def juju_reboot(*, now: bool = False):
    """Reboot the host machine.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/juju-reboot/

    Args:
        now: Reboot immediately, killing the invoking process.
    """
    if now:
        run('juju-reboot', '--now')
        # Juju will kill this process, but to avoid races we force that to be the case.
        sys.exit()
        return  # Make it simpler to mock out sys.exit() in tests.
    run('juju-reboot')


# model.py has this comment:
# > fields marked as network addresses need not be IPs; they could be
# > hostnames that juju failed to resolve.
# Is this still true? It doesn't seem to make sense, because if they could be a
# hostname, then why don't we have a str possibility where they do resolve.
# If it is true, we perhaps should wrap all the conversions to ipaddr.
# unit-get: https://github.com/juju/juju/blob/4488fbb57735c2ec74f9f07e85ac5241bd3f52df/internal/worker/uniter/runner/jujuc/unit-get.go#L81
# network-get: https://github.com/juju/juju/blob/4488fbb57735c2ec74f9f07e85ac5241bd3f52df/internal/worker/uniter/runner/jujuc/network-get.go#L119


# We could have bind_address: bool=True, egress_subnets: bool=True,
# --ingress-address: bool=True, and could even return just that data if only one
# is specified. However, it seems like it's unlikely there would be a lot of data
# here, and that it's unlikely to be much faster to only get one, so the API is
# a lot simpler if we only support getting all at once (which is the behaviour
# when none of those arguments are specified).
def network_get(binding_name: str, *, relation_id: int | None = None) -> Network:
    """Get network config.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/network-get/

    Args:
        binding_name: A name of a binding (relation name or extra-binding name).
        relation_id: An optional relation id to get network info for.
    """
    args: list[str] = []
    if relation_id is not None:
        args.extend(['-r', str(relation_id)])
    args.append(binding_name)
    stdout = run('network-get', *args, '--format=json')
    result = cast('dict[str, Any]', json.loads(stdout))
    return Network._from_dict(result)


def resource_get(name: str) -> pathlib.Path:
    """Get the path to the locally cached resource file.

    For more details, see:
    https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/resource-get/

    Args:
        name: The name of the resource.
    """
    stdout = run('resource-get', name)
    # Note that this does not have a `--format=json` flag
    return pathlib.Path(stdout.strip())
