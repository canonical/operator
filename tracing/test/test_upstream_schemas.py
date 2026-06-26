# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pin our de-pydantic'd dataclasses against the upstream charmlibs schemas.

This is an "opt-in" test: it requires network access to fetch the upstream
schemas at canonical/charmlibs HEAD, and it requires pydantic to instantiate
them. It is not part of the default ``unit`` tox env; run it via::

    tox -e upstream-schemas

The intent is to detect drift: if the canonical schemas under
``interfaces/{tracing,certificate_transfer}/`` change shape, this test should
fail and force a conscious decision about whether to follow upstream.
"""

from __future__ import annotations

import contextlib
import dataclasses
import enum
import json
import sys
import types
import typing
import urllib.request

import pytest

pydantic = pytest.importorskip('pydantic')

from ops_tracing import _tracing_models  # noqa: E402

TRACING_SCHEMA_URL = (
    'https://raw.githubusercontent.com/canonical/charmlibs/main/'
    'interfaces/tracing/interface/v2/schema.py'
)
CERT_TRANSFER_SCHEMA_URL = (
    'https://raw.githubusercontent.com/canonical/charmlibs/main/'
    'interfaces/certificate_transfer/interface/v1/schema.py'
)


def _fetch(url: str) -> str:
    assert url.startswith('https://'), url
    with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
        return resp.read().decode('utf-8')


def _load_upstream(url: str) -> dict[str, typing.Any]:
    """Exec an upstream schema.py in an isolated namespace.

    The upstream files import ``interface_tester.schema_base.DataBagSchema``,
    which is a tiny pydantic ``BaseModel`` subclass. Stub it so we don't have
    to install ``pytest-interface-tester``.
    """
    stub = types.ModuleType('interface_tester.schema_base')

    class DataBagSchema(pydantic.BaseModel):
        pass

    stub.DataBagSchema = DataBagSchema  # pyright: ignore[reportAttributeAccessIssue]
    parent = types.ModuleType('interface_tester')
    parent.schema_base = stub  # pyright: ignore[reportAttributeAccessIssue]
    sys.modules.setdefault('interface_tester', parent)
    sys.modules['interface_tester.schema_base'] = stub

    ns: dict[str, typing.Any] = {'__name__': f'upstream_{url.rsplit("/", 3)[-3]}'}
    exec(compile(_fetch(url), url, 'exec'), ns)  # noqa: S102
    # ``Json[T]`` annotations are stored as ForwardRefs at class-construction
    # time; resolve them now so ``model_fields`` and ``__init__`` work.
    for value in list(ns.values()):
        if isinstance(value, type) and issubclass(value, pydantic.BaseModel):
            with contextlib.suppress(Exception):
                value.model_rebuild(_types_namespace=ns)
    return ns


# Represent the upstream pydantic model and our dataclass as normalised
# (field-name -> type-token) maps. Token equality is what we compare.

_PRIMITIVE_TOKENS = {
    str: 'str',
    int: 'int',
    float: 'float',
    bool: 'bool',
}


def _token(tp: object) -> object:
    """Normalise a typing annotation into a comparable token.

    - Strip pydantic ``Json[T]`` (it's a wire-format wrapper; our dataclasses
      json-decode at the databag layer, so the inner type is what counts).
    - Treat ``Literal[*strs]`` as ``str`` (we narrow ``ReceiverProtocol`` to a
      Literal of the supported set; upstream leaves it open as ``str``).
    - Recurse into containers and into nested BaseModel/dataclass classes.
    """
    if tp in _PRIMITIVE_TOKENS:
        return _PRIMITIVE_TOKENS[tp]

    origin = typing.get_origin(tp)
    args = typing.get_args(tp)

    if origin is typing.Literal:
        if all(isinstance(a, str) for a in args):
            return 'str'
        return ('literal', args)

    if origin in (list, set, frozenset, tuple):
        container = {list: 'list', set: 'set', frozenset: 'set', tuple: 'tuple'}[origin]
        return (container, _token(args[0]))

    # pydantic's ``Json[T]`` is ``Annotated[T, ...]``; unwrap.
    if origin is not None and args and 'Json' in str(tp):
        return _token(args[0])

    if isinstance(tp, type):
        if issubclass(tp, pydantic.BaseModel):
            return _model_signature(tp)
        if dataclasses.is_dataclass(tp):
            return _dataclass_signature(tp)
        if issubclass(tp, enum.Enum):
            return ('enum', tuple(sorted((m.name, m.value) for m in tp)))

    return ('unknown', repr(tp))


def _model_signature(model: type) -> dict[str, typing.Any]:
    return {name: _token(f.annotation) for name, f in model.model_fields.items()}


def _dataclass_signature(cls: type) -> dict[str, typing.Any]:
    hints = typing.get_type_hints(cls)
    return {f.name: _token(hints[f.name]) for f in dataclasses.fields(cls)}


# ---- tracing v2 ----------------------------------------------------------


@pytest.fixture(scope='module')
def tracing_upstream() -> dict[str, typing.Any]:
    return _load_upstream(TRACING_SCHEMA_URL)


def test_tracing_provider_shape(tracing_upstream: dict[str, typing.Any]):
    upstream = _model_signature(tracing_upstream['TracingProviderData'])
    ours = _dataclass_signature(_tracing_models.TracingProviderAppData)
    assert upstream == ours, (
        f'TracingProviderData drift\n  upstream: {upstream}\n  ours:     {ours}'
    )


def test_tracing_requirer_shape(tracing_upstream: dict[str, typing.Any]):
    upstream = _model_signature(tracing_upstream['TracingRequirerData'])
    ours = _dataclass_signature(_tracing_models.TracingRequirerAppData)
    assert upstream == ours, (
        f'TracingRequirerData drift\n  upstream: {upstream}\n  ours:     {ours}'
    )


def test_tracing_provider_roundtrip(tracing_upstream: dict[str, typing.Any]):
    """A valid upstream payload must deserialise identically through our loader."""
    upstream_cls = tracing_upstream['TracingProviderData']
    payload = {
        'receivers': json.dumps([
            {'protocol': {'name': 'otlp_http', 'type': 'http'}, 'url': 'http://example:4318'},
            {'protocol': {'name': 'otlp_grpc', 'type': 'grpc'}, 'url': 'example:4317'},
        ])
    }
    upstream_obj = upstream_cls(**payload)
    ours = _tracing_models.TracingProviderAppData.load(payload)

    upstream_receivers = [
        {'name': r.protocol.name, 'type': r.protocol.type, 'url': r.url}
        for r in upstream_obj.receivers
    ]
    ours_receivers = [
        {'name': r.protocol.name, 'type': r.protocol.type.value, 'url': r.url}
        for r in ours.receivers
    ]
    assert upstream_receivers == ours_receivers


def test_tracing_requirer_roundtrip(tracing_upstream: dict[str, typing.Any]):
    upstream_cls = tracing_upstream['TracingRequirerData']
    payload = {'receivers': json.dumps(['otlp_http', 'otlp_grpc'])}
    upstream_obj = upstream_cls(**payload)
    ours = _tracing_models.TracingRequirerAppData(receivers=['otlp_http', 'otlp_grpc'])
    assert list(upstream_obj.receivers) == list(ours.receivers)


# ---- certificate_transfer v1 ---------------------------------------------

# We don't model certificate_transfer as a dataclass — the provider-side
# ``certificates`` key is JSON-decoded directly by ``_read_certificates`` in
# ``ops_tracing/_api.py``. So instead of a structural match, we pin the key
# names and the wire format that ``_read_certificates`` expects.


@pytest.fixture(scope='module')
def cert_transfer_upstream() -> dict[str, typing.Any]:
    return _load_upstream(CERT_TRANSFER_SCHEMA_URL)


def test_cert_transfer_provider_keys(cert_transfer_upstream: dict[str, typing.Any]):
    upstream = _model_signature(cert_transfer_upstream['CertificateTransferProviderAppData'])
    # The only field we read is ``certificates`` (a set/list of PEM strings).
    # If upstream renames it, our ``_read_certificates`` would silently return
    # an empty set — this test guards against that drift.
    assert 'certificates' in upstream, f'upstream lost `certificates`: {upstream}'
    assert upstream['certificates'] in (
        ('set', 'str'),
        ('list', 'str'),
    ), f'upstream `certificates` shape changed: {upstream["certificates"]!r}'
    # ``version`` is upstream-optional metadata; we deliberately ignore it.
    # If a NEW required field appears, fail loudly so we can decide whether to
    # adopt it.
    upstream_cls = cert_transfer_upstream['CertificateTransferProviderAppData']
    required = {name for name, f in upstream_cls.model_fields.items() if f.is_required()}
    assert required <= {'certificates'}, (
        f'upstream added required field(s): {required - {"certificates"}}'
    )


def test_cert_transfer_wire_format_roundtrip(cert_transfer_upstream: dict[str, typing.Any]):
    """A databag value built by the upstream model must parse with our reader."""
    upstream_cls = cert_transfer_upstream['CertificateTransferProviderAppData']
    obj = upstream_cls(certificates={'pem-a', 'pem-b'})
    # ``model_dump_json`` produces what an upstream provider would write to
    # the app databag under the ``certificates`` key; we just need the list
    # serialisation matching our ``json.loads(...)`` of the raw value.
    dumped = obj.model_dump(mode='json')
    raw = json.dumps(dumped['certificates'])
    parsed = set(json.loads(raw))
    assert parsed == {'pem-a', 'pem-b'}
