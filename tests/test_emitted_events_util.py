import pytest
from ops.charm import CharmEvents, CharmBase
from ops.framework import EventBase, EventSource

from scenario import State, Event
from scenario.utils import match_line, emitted_events


@pytest.mark.parametrize(
    'line, expected_source, expected_name',
    (
            ('Re-emitting <XX via foo/on/bar[1]>.', 'deferral', 'bar'),
            ('Re-emitting <XX via foo/on/foo[1]>.', 'deferral', 'foo'),
            ('Re-emitting deferred event <XX via foo/on/bar[1]>.', 'deferral', 'bar'),  # ops >= 2.1
            ('Re-emitting deferred event <XX via foo/on/foo[1]>.', 'deferral', 'foo'),  # ops >= 2.1
            ('Emitting custom event <XX via foo/on/bar[1]>.', 'custom', 'bar'),
            ('Emitting custom event <XX via foo/on/foo[1]>.', 'custom', 'foo'),
            ('Emitting Juju event foo.', 'juju', 'foo'),
            ('Emitting Juju event bar.', 'juju', 'bar'),
            ('Charm called itself via hooks/foo.', 'framework', 'foo'),
            ('Charm called itself via hooks/bar.', 'framework', 'bar'),
            ('Foobarbaz', None, None),
    )
)
def test_line_matcher(line, expected_source, expected_name):
    match = match_line(line)
    if expected_source is expected_name is None:
        assert not match
    else:
        assert match.raw == line
        assert match.source == expected_source
        assert match.name == expected_name


class Foo(EventBase):
    pass


class MyCharmEvents(CharmEvents):
    foo = EventSource(Foo)


class MyCharm(CharmBase):
    META = {"name": "mycharm"}
    on = MyCharmEvents()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.foo, self._on_foo)

    def _on_start(self, e):
        self.on.foo.emit()

    def _on_foo(self, e):
        pass


def test_collection_custom_as_juju_evt():
    out = State().trigger("foo", MyCharm, meta=MyCharm.META)
    emitted = emitted_events(out)

    assert len(emitted) == 1
    assert emitted[0].source == 'juju'
    assert emitted[0].name == 'foo'


def test_collection_juju_evt():
    out = State().trigger("start", MyCharm, meta=MyCharm.META)
    emitted = emitted_events(out)

    assert len(emitted) == 2
    assert emitted[0].source == 'juju'
    assert emitted[0].name == 'start'
    assert emitted[1].source == 'custom'
    assert emitted[1].name == 'foo'


def test_collection_deferred():
    # todo: this test should pass with ops < 2.1 as well
    out = State(deferred=[
        Event('foo').deferred(handler=MyCharm._on_foo)
    ]).trigger("start", MyCharm, meta=MyCharm.META)
    emitted = emitted_events(out)

    assert len(emitted) == 3
    assert emitted[0].source == 'deferral'
    assert emitted[0].name == 'foo'
    assert emitted[1].source == 'juju'
    assert emitted[1].name == 'start'
    assert emitted[2].source == 'custom'
    assert emitted[2].name == 'foo'
