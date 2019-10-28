from juju.interface import InterfaceBase


class MySQLInterfaceRequires(InterfaceBase):
    @property
    def is_joined(self):
        return len(self.relations) > 0

    @property
    def is_single(self):
        return len(self.relations) == 1

    @property
    def is_ready(self):
        return self.is_single and self.database and self.host and self.username and self.password

    def _field(self, name):
        if not self.is_joined:
            return None
        rel = self.relations[0]
        return rel.data[rel.app].get(name)

    @property
    def database(self):
        return self._field('database')

    @property
    def host(self):
        return self._field('host')

    @property
    def username(self):
        return self._field('username')

    @property
    def password(self):
        return self._field('password')
