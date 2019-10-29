from juju.charm import Charm
from juju.framework import StoredState
from juju.interface import Endpoint
from juju.model import Active, Blocked, Waiting, Maintenance

from interfaces.http import HTTPInterfaceProvides
from interfaces.mysql import MySQLInterfaceRequires
from resources.oci_image import OCIImageResource


class GitLabK8sCharm(Charm):
    state = StoredState()

    website = Endpoint(HTTPInterfaceProvides)
    mysql = Endpoint(MySQLInterfaceRequires)

    def __init__(self, framework, key):
        super().__init__(framework, key)

        for event in (self.on.start,
                      self.on.upgrade_charm,
                      self.on.config_changed,
                      self.mysql.on.changed):
            self.framework.observe(event, self.on_start)
        self.framework.observe(self.website.on.joined, self.on_website_joined)

        # TODO: Resources are not implemented in the model.
        self.image_resource = OCIImageResource(self.framework.model.resources['gitlab_image'])

    def on_install(self, event):
        self.state.is_started = False

    def on_start(self, event):
        unit = self.framework.model.unit
        if not self.image_resource.fetch():
            unit.status = Blocked('Missing or invalid image resource')
            return
        if not self.mysql.is_joined:
            unit.status = Blocked('Missing database')
        if not self.mysql.is_single:
            unit.status = Blocked('Too many databases')
        if not self.db.is_ready:
            unit.status = Waiting('Waiting for database')
            return
        unit.status = Maintenance('Configuring container')
        self.framework.model.pod_spec = {
            'name': self.framework.model.app.name,
            'docker_image_path': self.image_info.registry_path,
            'docker_image_username': self.image_info.username,
            'docker_image_password': self.image_info.password,
            'port': self.framework.model.config['http_port'],
            'config': '; '.join([
                f"postgresql['enable'] = false",  # disable built-in DB
                f"gitlab_rails['db_adapter'] = 'mysql'",
                f"gitlab_rails['db_encoding'] = 'utf8'",
                f"gitlab_rails['db_database'] = '{self.mysql.database}'",
                f"gitlab_rails['db_host'] = '{self.mysql.host}'",
                f"gitlab_rails['db_port'] = '{self.mysql.port}'",
                f"gitlab_rails['db_username'] = '{self.mysql.username}'",
                f"gitlab_rails['db_password'] = '{self.mysql.password}'",
            ]),
        }
        self.state.is_started = True
        # Final active status (ready) will be set by Juju.
        unit.status = Active('Starting container')

    def on_website_joined(self, event):
        if not self.state.is_started:
            event.defer()
            return

        self.config = self.framework.model.config
        for client in self.website.clients:
            client.serve(hosts=[client.ingress_address],
                         port=self.config['http_port'])
