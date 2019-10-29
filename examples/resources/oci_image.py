import json
from pathlib import Path

from juju.framework import Object, StoredState


class OCIImageResource(Object):
    _state = StoredState()

    def __init__(self, resource):
        self._resource = resource
        self._state.is_fetched = False
        self._state.registry_path = None
        self._state.username = None
        self._state.password = None

    def fetch(self):
        resource_file = self._resource.fetch()
        if not resource_file:
            return False
        resource_text = Path(resource_file).read_text()
        if not resource_text:
            return False
        try:
            resource_data = json.loads(resource_text)
        except json.JSONDecodeError:
            # TODO: This should be surfaced.
            return False
        else:
            self._state.is_fetched = True
            self._state.registry_path = resource_data['registrypath']
            self._state.username = resource_data['username']
            self._state.password = resource_data['password']
            return True

    @property
    def is_fetched(self):
        return self._state.is_fetched

    @property
    def registry_path(self):
        return self._state.registry_path

    @property
    def username(self):
        return self._state.username

    @property
    def password(self):
        return self._state.password
