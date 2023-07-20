import dataclasses
from typing import Dict, List

from scenario.state import _DCBase


@dataclasses.dataclass(frozen=True)
class Foo(_DCBase):
    a: int
    b: List[int]
    c: Dict[int, List[int]]


def test_base_case():
    l = [1, 2]
    l1 = [1, 2, 3]
    d = {1: l1}
    f = Foo(1, l, d)
    g = f.replace(a=2)

    assert g.a == 2
    assert g.b == l
    assert g.c == d
    assert g.c[1] == l1


def test_dedup_on_replace():
    l = [1, 2]
    l1 = [1, 2, 3]
    d = {1: l1}
    f = Foo(1, l, d)
    g = f.replace(a=2)

    l.append(3)
    l1.append(4)
    d[2] = "foobar"

    assert g.a == 2
    assert g.b == [1, 2]
    assert g.c == {1: [1, 2, 3]}
    assert g.c[1] == [1, 2, 3]
