from typing import List

from ops.testing import Harness

from scenario import Container, Model, Network, Port, Relation, Secret, State


class Darkroom:
    """Wrap a harness and capture its state."""

    def __init__(self, harness: Harness):
        self._harness = harness

    def capture(self) -> State:
        h = self._harness
        c = h.charm

        if not c:
            raise RuntimeError("cannot capture: uninitialized harness.")

        state = State(
            config=dict(c.config),
            relations=self._get_relations(),
            containers=self._get_containers(),
            networks=self._get_networks(),
            secrets=self._get_secrets(),
            opened_ports=self._get_opened_ports(),
            leader=c.unit.is_leader(),
            unit_id=int(c.unit.name.split("/")[1]),
            app_status=c.app.status,
            unit_status=c.unit.status,
            workload_version=h.get_workload_version(),
            model=Model(
                # todo: model = kubernetes or lxd?
                uuid=h.model.uuid,
                name=h.model.name,
            ),
        )
        return state

    def _get_opened_ports(self) -> List[Port]:
        return [Port(p.protocol, p.port) for p in self._harness._backend.opened_ports()]

    def _get_relations(self) -> List[Relation]:
        relations = []
        b = self._harness._backend

        def get_interface_name(endpoint: str):
            return b._meta.relations[endpoint].interface_name

        local_unit_name = b.unit_name
        local_app_name = b.unit_name.split("/")[0]

        for endpoint, ids in b._relation_ids_map.items():
            for r_id in ids:
                # todo switch between peer and sub
                rel_data = b._relation_data_raw[r_id]
                remote_app_name = b._relation
                app_and_units = b._relation_app_and_units[r_id]
                relations.append(
                    Relation(
                        endpoint=endpoint,
                        interface=get_interface_name(endpoint),
                        relation_id=r_id,
                        local_app_data=rel_data[local_app_name],
                        local_unit_data=rel_data[local_unit_name],
                        remote_app_data=rel_data[remote_app_name],
                        remote_units_data={
                            int(remote_unit_id.split("/")[1]): rel_data[remote_unit_id]
                            for remote_unit_id in app_and_units["units"]
                        },
                        remote_app_name=app_and_units["app"],
                    ),
                )
        return relations

    def _get_containers(self) -> List[Container]:
        containers = []
        b = self._harness._backend
        for name, c in b._meta.containers.items():
            containers.append(Container(name=name, mounts=c.mounts))
        return containers

    def _get_networks(self) -> List[Network]:
        networks = [
            Network(name=nw_name, **nw)
            for nw_name, nw in self._harness._backend._networks.items()
        ]
        return networks

    def _get_secrets(self) -> List[Secret]:
        secrets = []
        h = self._harness
        b = h._backend

        for s in b._secrets:
            owner_app = s.owner_name.split("/")[0]
            relation_id = b._relation_id_to(owner_app)
            grants = s.grants.get(relation_id, set())

            remote_grants = set()
            granted = False
            for grant in grants:
                if grant in (h.charm.unit.name, h.charm.app.name):
                    granted = grant
                else:
                    remote_grants.add(grant)

            secrets.append(
                Secret(
                    id=s.id,
                    label=s.label,
                    contents=b.secret_get(s.id),
                    granted=granted,
                    remote_grants={relation_id: remote_grants},
                    description=s.description,
                    owner=s.owner_name,
                    rotate=s.rotate_policy,
                    expire=s.expire_time,
                ),
            )
        return secrets
