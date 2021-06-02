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
from typing import List, Tuple


logger = logging.getLogger(__name__)


# prevents ops calls register_cloud_event more than once during each hook runs.
_KEY_REGISTERED = "registered_cloud_events"
# prevents ops calls register_cloud_event again after the charm has called event.unregister_cloud_event.
_KEY_UNREGISTERED = "unregistered_cloud_events"

CloudEventIds = List[str]


def _get_registered(emitter) -> CloudEventIds:
    return emitter.framework._stored[_KEY_REGISTERED] or []


def _set_registered(emitter, items: CloudEventIds):
    emitter.framework._stored[_KEY_REGISTERED] = items


def _get_unregistered(emitter) -> CloudEventIds:
    return emitter.framework._stored[_KEY_UNREGISTERED] or []


def _set_unregistered(emitter, items: CloudEventIds):
    emitter.framework._stored[_KEY_UNREGISTERED] = items


def _validate_cloud_event_id(emitter, cloud_event_id: str) -> Tuple[CloudEventIds, CloudEventIds]:
    registered = _get_registered(emitter)
    unregistered = _get_unregistered(emitter)

    if cloud_event_id in registered and cloud_event_id in unregistered:
        raise RuntimeError("stale state for {}".format(cloud_event_id))
    return registered, unregistered


def _cache_registered(emitter, cloud_event_id: str):
    registered, unregistered = _validate_cloud_event_id(emitter, cloud_event_id)
    if cloud_event_id in registered:
        return

    registered.append(cloud_event_id)
    _set_registered(emitter, registered)
    _uncache_unregistered(emitter, cloud_event_id, unregistered)


def _cache_unregistered(emitter, cloud_event_id: str):
    registered, unregistered = _validate_cloud_event_id(emitter, cloud_event_id)
    if cloud_event_id in unregistered:
        return

    unregistered.append(cloud_event_id)
    _set_unregistered(emitter, unregistered)
    _uncache_registered(emitter, cloud_event_id, registered)


def _uncache_registered(emitter, cloud_event_id: str, registered: CloudEventIds):
    try:
        registered.remove(cloud_event_id)
        _set_registered(emitter, registered)
    except ValueError:
        pass


def _uncache_unregistered(emitter, cloud_event_id: str, unregistered: CloudEventIds):
    try:
        unregistered.remove(cloud_event_id)
        _set_unregistered(emitter, unregistered)
    except ValueError:
        pass


def register_cloud_event(emitter, cloud_event_id, resource_type, resource_name, force=False):
    if cloud_event_id in _get_registered(emitter):
        logger.debug('cloud event %s has already been registered', cloud_event_id)
        return
    if cloud_event_id in _get_unregistered(emitter) and not force:
        logger.debug(
            'cloud event %s has already been registered, can not register again without force',
            cloud_event_id,
        )
        return
    # only call register_cloud_event for the first time.
    emitter.framework.model._backend.register_cloud_event(
        cloud_event_id, resource_type, resource_name,
    )
    _cache_registered(emitter, cloud_event_id)


def unregister_cloud_event(emitter, cloud_event_id):
    if cloud_event_id in _get_unregistered(emitter):
        logger.debug('cloud event %s has already been unregistered', cloud_event_id)
        return
    emitter.framework.model._backend.unregister_cloud_event(cloud_event_id)
    _cache_unregistered(emitter, cloud_event_id)
