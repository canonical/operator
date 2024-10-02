import pytest
from ops import CharmBase, ModelError

from scenario import Context, State, Storage


class MyCharmWithStorage(CharmBase):
    META = {"name": "charlene", "storage": {"foo": {"type": "filesystem"}}}


class MyCharmWithoutStorage(CharmBase):
    META = {"name": "patrick"}


@pytest.fixture
def storage_ctx():
    return Context(MyCharmWithStorage, meta=MyCharmWithStorage.META)


@pytest.fixture
def no_storage_ctx():
    return Context(MyCharmWithoutStorage, meta=MyCharmWithoutStorage.META)


def test_storage_get_null(no_storage_ctx):
    with no_storage_ctx(no_storage_ctx.on.update_status(), State()) as mgr:
        storages = mgr.charm.model.storages
        assert not len(storages)


def test_storage_get_unknown_name(storage_ctx):
    with storage_ctx(storage_ctx.on.update_status(), State()) as mgr:
        storages = mgr.charm.model.storages
        # not in metadata
        with pytest.raises(KeyError):
            storages["bar"]


def test_storage_request_unknown_name(storage_ctx):
    with storage_ctx(storage_ctx.on.update_status(), State()) as mgr:
        storages = mgr.charm.model.storages
        # not in metadata
        with pytest.raises(ModelError):
            storages.request("bar")


def test_storage_get_some(storage_ctx):
    with storage_ctx(storage_ctx.on.update_status(), State()) as mgr:
        storages = mgr.charm.model.storages
        # known but none attached
        assert storages["foo"] == []


@pytest.mark.parametrize("n", (1, 3, 5))
def test_storage_add(storage_ctx, n):
    with storage_ctx(storage_ctx.on.update_status(), State()) as mgr:
        storages = mgr.charm.model.storages
        storages.request("foo", n)

    assert storage_ctx.requested_storages["foo"] == n


def test_storage_usage(storage_ctx):
    storage = Storage("foo")
    # setup storage with some content
    (storage.get_filesystem(storage_ctx) / "myfile.txt").write_text("helloworld")

    with storage_ctx(storage_ctx.on.update_status(), State(storages={storage})) as mgr:
        foo = mgr.charm.model.storages["foo"][0]
        loc = foo.location
        path = loc / "myfile.txt"
        assert path.exists()
        assert path.read_text() == "helloworld"

        myfile = loc / "path.py"
        myfile.write_text("helloworlds")

    # post-mortem: inspect fs contents.
    assert (
        storage.get_filesystem(storage_ctx) / "path.py"
    ).read_text() == "helloworlds"


def test_storage_attached_event(storage_ctx):
    storage = Storage("foo")
    storage_ctx.run(storage_ctx.on.storage_attached(storage), State(storages={storage}))


def test_storage_detaching_event(storage_ctx):
    storage = Storage("foo")
    storage_ctx.run(
        storage_ctx.on.storage_detaching(storage), State(storages={storage})
    )
