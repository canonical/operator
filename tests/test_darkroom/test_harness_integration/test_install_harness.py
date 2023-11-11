def test_install():
    from scenario.integrations.darkroom import Darkroom

    l = []

    def register_trace(t):
        l.append(t)

    Darkroom.install(register_trace)

    import yaml
    from ops import CharmBase
    from ops.testing import Harness

    class MyCharm(CharmBase):
        META = {"name": "joseph", "requires": {"foo": {"interface": "bar"}}}

    h = Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))
    h.begin_with_initial_hooks()

    h = Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))
    h.begin_with_initial_hooks()
    h.add_relation("foo", "remote")

    h = Harness(MyCharm, meta=yaml.safe_dump(MyCharm.META))
    h.begin_with_initial_hooks()
    h.add_relation("foo", "remote2")

    assert len(l) == 3
    assert [len(x) for x in l] == [4, 5, 5]
    assert l[0][1][0].name == "leader_settings_changed"
    assert l[1][-1][0].name == "foo_relation_created"
    assert l[2][-1][0].name == "foo_relation_created"
