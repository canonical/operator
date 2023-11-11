import yaml
from ops import CharmBase
from ops.testing import Harness

from scenario.integrations.darkroom import Darkroom


class MyCharm(CharmBase):
    META = {"name": "joseph", "requires": {"foo": {"interface": "bar"}}}


def test_attach():
    h = Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))
    l = []
    d = Darkroom().attach(lambda e, s: l.append((e, s)))
    h.begin()
    h.add_relation("foo", "remote")

    assert len(l) == 1
    assert l[0][0].name == "foo_relation_created"
