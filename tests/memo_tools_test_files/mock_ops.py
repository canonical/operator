import random

from recorder import memo


class _ModelBackend:
    def _private_method(self):
        pass

    def other_method(self):
        pass

    @memo
    def action_set(self, *args, **kwargs):
        return str(random.random())

    @memo
    def action_get(self, *args, **kwargs):
        return str(random.random())
