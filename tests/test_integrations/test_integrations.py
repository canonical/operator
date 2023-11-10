import pytest
from ops import CharmBase
from ops.testing import Harness


class MyCharm(CharmBase):
    META = {"name": "joseph"}


@pytest.fixture
def harness():
    return Harness(MyCharm, meta=MyCharm.META)


def test_base(harness):
    harness.begin()
