import json
from collections import namedtuple

from juju.interface import InterfaceBase


class HTTPInterfaceProvides(InterfaceBase):
    """Provides side for the 'http' interface protocol.

    Example usage:

        class MyCharm(CharmBase):
            website = Endpoint(HTTPInterfaceProvides)

            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.framework.observe(self.website.on.joined, self.on_website_joined)

        def on_website_joined(self, event):
            self.config = self.framework.model.config
            for client in self.website.clients:
                client.serve(hosts=[client.ingress_address],
                             port=self.config['http_port'])
    """
    @property
    def clients(self):
        return [HTTPInterfaceClient(self.framework, relation) for relation in self.relations]


class HTTPInterfaceRequires(InterfaceBase):
    @property
    def servers(self):
        return [HTTPInterfaceServer(relation) for relation in self.relations]


class HTTPInterfaceClient:
    def __init__(self, framework, relation):
        self._framework = framework
        self._relation = relation

    @property
    # TODO: Should this be binding_address?
    def ingress_address(self):
        binding = self._framework.model.network_bindings[self._relation.name]
        return binding.ingress_address

    def serve(self, hosts, port):
        local_unit = self._framework.model.unit
        hosts = list(hosts)
        first_host = hosts.pop(0)
        self._relation.data[local_unit]['hostname'] = first_host
        self._relation.data[local_unit]['port'] = port
        extra_hosts = [{'hostname': host, 'port': port} for host in hosts]
        self._relation.data[local_unit]['extended_data'] = json.dumps(extra_hosts)


HTTPInterfaceHost = namedtuple('HTTPInterfaceHost', ['host', 'port'])


class HTTPInterfaceServer:
    def __init__(self, relation):
        self._relation = relation

    @property
    def app(self):
        return self.relation.app

    @property
    def hosts(self):
        hosts_set = set()
        for unit in self._relation.units:
            data = self._relation.data[unit]
            host = data.get('hostname', data.get('private-address'))
            port = data.get('port')
            if host and port:
                hosts_set.add(HTTPInterfaceHost(host, port))
            extended_data = data.get('extended_data')
            if extended_data:
                for extra_host in json.loads(extended_data):
                    host = data.get('hostname', data.get('private-address'))
                    port = data.get('port')
                    hosts_set.add(HTTPInterfaceHost(host, port))
        return hosts_set
