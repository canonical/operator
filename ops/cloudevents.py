# Copyright 2021 Canonical Ltd.
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

"""Interface to interact with cloud events system."""

import logging
import typing
from typing import Dict

from ops.framework import Object


logger = logging.getLogger(__name__)


# The state key for storing the registered cloud event identifiers.
_STATE_KEY = 'registered_cloud_events'

CloudEventIds = Dict[str, bool]


def _get_state(emitter: Object) -> CloudEventIds:
    data = emitter.framework._stored[_STATE_KEY]
    if data is None:
        emitter.framework._stored[_STATE_KEY] = {}
    return emitter.framework._stored[_STATE_KEY]


def _set_state(emitter: Object, data: CloudEventIds):
    emitter.framework._stored[_STATE_KEY] = data


def _set_registered(emitter: Object, cloud_event_id: str):
    data = _get_state(emitter)
    data[cloud_event_id] = True
    _set_state(emitter, data)


def _set_unregistered(emitter: Object, cloud_event_id: str):
    data = _get_state(emitter)
    data[cloud_event_id] = False
    _set_state(emitter, data)


def _is_registered(emitter: Object, cloud_event_id: str) -> typing.Optional[bool]:
    return _get_state(emitter).get(cloud_event_id)


def register_cloud_event(
    emitter: Object, cloud_event_id: str,
    resource_type: str, resource_name: str,
    force: bool = False,
):
    """Register a resource to watch for cloud events.

    Args:
        emitter: An instance of Object which has Framework accessible.
        cloud_event_id: The cloud event identifier.
        resource_type: The resource type.
        resource_name: The resource name.
        force: Always call 'register-cloud-event' command if force is True.
    """
    is_registered = _is_registered(emitter, cloud_event_id)
    if is_registered:
        logger.debug('cloud event %s has already been watched', cloud_event_id)
        return
    if is_registered is None or force:
        # call register_cloud_event for the first time or with force == True.
        logger.debug('cloud event %s is being watched now', cloud_event_id)
        emitter.framework.model._backend.register_cloud_event(
            cloud_event_id, resource_type, resource_name,
        )
        _set_registered(emitter, cloud_event_id)
        return
    # no ops for an unregistered id.


def unregister_cloud_event(emitter: Object, cloud_event_id: str):
    """Unregister a watched resource for cloud events.

    Args:
        emitter: An instance of Object which has Framework accessible.
        cloud_event_id: The cloud event identifier.
    """
    if _is_registered(emitter, cloud_event_id):
        emitter.framework.model._backend.unregister_cloud_event(cloud_event_id)
        _set_unregistered(emitter, cloud_event_id)
