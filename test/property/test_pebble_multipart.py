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

"""Hypothesis property-based tests for Pebble's multipart handling.

``Client.pull`` reads a multipart body in chunks, and ``_MultipartParser``
has to find boundaries that may be split across those chunks, while writing
file data out as it goes. ``Client.push`` builds its multipart body by hand.
Both are streaming code with a wide input space and a simple invariant: what
goes in comes back out.
"""

from __future__ import annotations

import email.parser
import itertools
import json
import string
from email.message import Message
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ops import pebble

# ── strategies ──────────────────────────────────────────────────────────────

# RFC 2046 boundary characters, 1 to 70 of them, not ending in a space.
_BCHARS = string.ascii_letters + string.digits + "'()+_,-./:=? "
_boundaries = st.text(alphabet=_BCHARS, min_size=1, max_size=70).filter(
    lambda b: not b.endswith(' ')
)

# Linear whitespace is allowed between a boundary and its CRLF (RFC 2046).
_lwsp = st.text(alphabet=' \t', max_size=3)

# Absolute file paths. Control characters are left out: a CR or LF in a
# path would need header folding, which neither side does.
_paths = st.text(
    alphabet=st.characters(blacklist_categories=['Cs', 'Cc']),
    min_size=1,
    max_size=50,
).map(lambda p: '/' + p)

# Known problems these tests found, kept out of the general strategies so
# that the properties stay green; each has its own xfail test below.
#
# - pull: _FilesParser reads the filename with the stdlib email parser, which
#   decodes header bytes as ASCII (non-ASCII bytes become surrogate escapes)
#   and strips trailing whitespace. Either way the name doesn't match the
#   requested path, and Client.pull raises ProtocolError('path not expected').
# - push: _encode_multipart escapes '"' but not '\', and Go's
#   mime.ParseMediaType (which Pebble uses) treats '\' before a tspecial as an
#   escape, so '\\' arrives as '\', '\/' as '/', and a trailing '\' makes the
#   header unparsable.
_TSPECIALS = '()<>@,;:\\"/[]?='


def _pull_safe(path: str) -> bool:
    return path.isascii() and path == path.rstrip(' \t')


def _push_safe(path: str) -> bool:
    # The closing quote follows the path, so a trailing backslash escapes it.
    return not any(a == '\\' and b in _TSPECIALS for a, b in itertools.pairwise(path + '"'))


def _go_escape(value: str) -> str:
    """Escape a parameter value the way Go's multipart.Writer does."""
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _go_param(header: str, name: str) -> str | None:
    """Read a quoted parameter the way Go's mime.ParseMediaType does.

    Inside quotes, a backslash escapes the next character only if that
    character is a tspecial; otherwise the backslash is kept. Returns None if
    the quoted string is unterminated, where Go fails to parse the header.
    """
    marker = f'{name}="'
    start = header.find(marker)
    assert start != -1
    out: list[str] = []
    i = start + len(marker)
    while i < len(header):
        c = header[i]
        if c == '"':
            return ''.join(out)
        if c == '\\' and i + 1 < len(header) and header[i + 1] in _TSPECIALS:
            out.append(header[i + 1])
            i += 2
            continue
        out.append(c)
        i += 1
    return None


_json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(), children, max_size=3)
    ),
    max_leaves=10,
)


def _chunked(data: bytes, cuts: list[int]) -> list[bytes]:
    """Split data at the given offsets (taken modulo the length)."""
    if not data:
        return [data]
    points = sorted({c % len(data) for c in cuts} | {0, len(data)})
    return [data[a:b] for a, b in itertools.pairwise(points)]


# ── pull: _FilesParser ──────────────────────────────────────────────────────


def _pull_files_part(path: str, content: bytes) -> bytes:
    """The files part as Pebble writes it, with Go's escaping of the filename."""
    return b''.join([
        b'Content-Disposition: form-data; name="files"; filename="',
        _go_escape(path).encode(),
        b'"\r\nContent-Type: application/octet-stream\r\n\r\n',
        content,
    ])


@st.composite
def _pull_bodies(draw: st.DrawFn) -> tuple[str, bytes, str, bytes, dict[str, Any]]:
    boundary = draw(_boundaries)
    delimiter = b'\r\n--' + boundary.encode()
    # The delimiter must not appear in the content (RFC 2046), and Pebble
    # picks a random boundary to make sure it doesn't.
    content = draw(st.binary(max_size=2000).filter(lambda c: delimiter not in c))
    path = draw(_paths.filter(_pull_safe))
    response = {
        'type': 'sync',
        'status-code': 200,
        'status': 'OK',
        'result': [{'path': path}],
        'extra': draw(_json_values),
    }
    files_part = _pull_files_part(path, content)
    response_part = b''.join([
        b'Content-Disposition: form-data; name="response"\r\n\r\n',
        json.dumps(response).encode(),
    ])
    parts = [files_part, response_part]
    if draw(st.booleans()):
        parts.reverse()
    # requests strips the CRLF before the first boundary, and _FilesParser
    # primes its buffer with it, so the body starts at the first "--".
    body = b''
    for part in parts:
        body += b'--' + boundary.encode() + draw(_lwsp).encode() + b'\r\n' + part + b'\r\n'
    body += b'--' + boundary.encode() + b'--' + draw(_lwsp).encode() + b'\r\n'
    return boundary, body, path, content, response


@given(_pull_bodies(), st.lists(st.integers(min_value=0), max_size=20))
def test_pull_parser_reassembles_any_chunking(
    pull_body: tuple[str, bytes, str, bytes, dict[str, Any]], cuts: list[int]
):
    """However the body is chunked, the parser returns the same file and response."""
    boundary, body, path, content, response = pull_body
    parser = pebble._FilesParser(boundary)
    try:
        for chunk in _chunked(body, cuts):
            parser.feed(chunk)
        assert parser.get_response() == response
        assert parser.filenames() == [path]
        with parser.get_file(path, encoding=None) as f:
            assert f.read() == content
    finally:
        parser.remove_files()


# ── push: Client._encode_multipart ──────────────────────────────────────────


def _parse_encoded(body: bytes, boundary: str) -> list[tuple[Message, bytes, str]]:
    """Parse a push body with _MultipartParser.

    Returns (headers, body, raw header text) per part. Pebble reads header
    bytes as UTF-8, so the raw text is what the filename should come from.
    """
    parts: list[tuple[Message, bytes, str]] = []
    current: dict[str, Any] = {}

    def handle_header(data: bytearray):
        p = email.parser.BytesFeedParser()
        p.feed(bytes(data))
        current['headers'] = p.close()
        current['raw'] = bytes(data).decode('utf-8')
        current['body'] = bytearray()

    def handle_body(data: bytearray, done: bool = False):
        current['body'].extend(data)
        if done:
            parts.append((current['headers'], bytes(current['body']), current['raw']))

    parser = pebble._MultipartParser(boundary.encode(), handle_header, handle_body)
    parser.feed(b'\r\n' + body)
    return parts


def _encode_push(
    metadata: dict[str, Any], path: str, content: bytes, chunk_size: int = 8192
) -> tuple[list[tuple[Message, bytes, str]], str | None]:
    """Encode a push body, then parse it back; also return the filename as Pebble reads it."""
    client = pebble.Client(socket_path='/nonexistent')
    client._chunk_size = chunk_size
    generator, content_type = client._encode_multipart(metadata, path, content, 'utf-8')
    body = b''.join(generator)
    boundary = content_type.split('boundary="', 1)[1].rstrip('"')
    parts = _parse_encoded(body, boundary)
    disposition = next(
        line for line in parts[-1][2].splitlines() if line.startswith('Content-Disposition:')
    )
    return parts, _go_param(disposition, 'filename')


@given(
    metadata=st.dictionaries(st.text(), _json_values, max_size=4),
    path=_paths.filter(_push_safe),
    content=st.binary(max_size=2000),
    chunk_size=st.integers(min_value=1, max_value=64),
)
def test_push_encoding_round_trips(
    metadata: dict[str, Any], path: str, content: bytes, chunk_size: int
):
    """What push encodes, Pebble decodes to the same request, path and file."""
    parts, filename = _encode_push(metadata, path, content, chunk_size)

    assert len(parts) == 2
    (request_headers, request_body, _), (files_headers, files_body, _) = parts
    assert request_headers.get_param('name', header='content-disposition') == 'request'
    assert json.loads(request_body) == metadata
    assert files_headers.get_param('name', header='content-disposition') == 'files'
    assert filename == path
    assert files_body == content


# ── what the properties found ───────────────────────────────────────────────


@pytest.mark.xfail(strict=True, reason='the email parser mangles the filename')
@pytest.mark.parametrize('path', ['/srv/café', '/srv/file ', '/srv/file\t'])
def test_pull_path_non_ascii_or_trailing_whitespace(path: str):
    boundary = 'b0undary'
    body = b''.join([
        b'--b0undary\r\n',
        _pull_files_part(path, b'data'),
        b'\r\n--b0undary\r\n',
        b'Content-Disposition: form-data; name="response"\r\n\r\n',
        json.dumps({'type': 'sync', 'status-code': 200, 'result': [{'path': path}]}).encode(),
        b'\r\n--b0undary--\r\n',
    ])
    parser = pebble._FilesParser(boundary)
    try:
        parser.feed(body)
        assert parser.filenames() == [path]
    finally:
        parser.remove_files()


@pytest.mark.xfail(strict=True, reason="_encode_multipart doesn't escape '\\'")
@pytest.mark.parametrize('path', ['/srv/a\\\\b', '/srv/a\\/b', '/srv/a\\'])
def test_push_path_with_backslash_before_tspecial(path: str):
    _, filename = _encode_push({}, path, b'data')
    assert filename == path
