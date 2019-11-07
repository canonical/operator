from juju.framework import Object


class InterfaceBase(Object):
    @property
    def charm(self):
        return self.parent

    @property
    def name(self):
        return self.handle.key

    @property
    def relations(self):
        return self.framework.model.relations[self.name]
