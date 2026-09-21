# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Draft the release notes for a release, via OpenRouter.

Called by the propose-release workflow once the changelog entry for the
release has been generated. The notes go in the version-bump pull request's
description, where a human edits them before the release is published.

The changelog is the reference and is generated deterministically; these
notes are the explanation, and a model writes the first draft of them. The
instructions the model gets are in `.github/release-notes-prompt.md`,
which is the team's prompt rather than one specific to this repository.

**No key means no notes, not a failed workflow.** Whenever the model cannot
be reached - no `OPENROUTER_API_KEY`, no `OPENROUTER_MODEL`, or a call that
fails - this writes a short placeholder telling the reviewer to write the
notes themselves, and exits successfully. The release must not be blocked by
the drafting of prose that a human is going to rewrite anyway.

Standard library only, so it runs on a runner with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'

# How long to wait for the draft. Generous: a slow draft is still cheaper
# than a human writing the notes from nothing, and the fallback is right
# there if the wait does not pay off.
TIMEOUT_SECONDS = 180

# The pull request description wraps the notes in these, so that workflow 2
# can lift them back out again. A model that emits one of them itself would
# truncate its own notes, so they are stripped from whatever comes back.
MARKERS = re.compile(r'<!--\s*release-notes:(?:start|end)\s*-->')

# A model told to emit Markdown and nothing else sometimes wraps the lot in
# a fence anyway.
WRAPPING_FENCE = re.compile(r'\A```(?:markdown|md)?\n(?P<body>.*)\n```\s*\Z', re.DOTALL)


def build_prompts(args: argparse.Namespace) -> tuple[str, str]:
    """Return the (system, user) pair for the call.

    The system prompt is the prompt file with the release
    filled in. The user message is everything about this particular
    release: the generated changelog, the range it covers, and the
    exemplar releases, if the workflow fetched any.
    """
    system = pathlib.Path(args.prompt).read_text()
    system = system.replace('<repo>', args.repo).replace('<version>', args.version)

    parts = [
        '# This release',
        '',
        f'Repository: {args.repo}',
        f'Version: {args.version}',
        f'Previous release: {args.previous}',
        f'Branch: {args.branch}',
        f'Commit range: {args.previous}..{args.branch}',
    ]
    if args.compare_url:
        parts.append(f'Compare: {args.compare_url}')
    parts += [
        '',
        '# The generated changelog for this release',
        '',
        pathlib.Path(args.changelog).read_text().strip(),
    ]
    if args.exemplars:
        exemplars = pathlib.Path(args.exemplars).read_text().strip()
        if exemplars:
            parts += ['', '# Exemplar releases', '', exemplars]
    return system, '\n'.join(parts) + '\n'


def call_openrouter(system: str, user: str, model: str, api_key: str) -> str:
    """POST the prompts to OpenRouter and return the Markdown it answers with.

    Uses urllib rather than requests so that this script has no third-party
    dependencies at all. Any failure is raised as a RuntimeError, which the
    caller turns into the placeholder body.
    """
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    }
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        # The URL is a literal https endpoint, not caller-controlled.
        opened = urllib.request.urlopen(  # ruff: ignore[suspicious-url-open-usage]
            request, timeout=TIMEOUT_SECONDS
        )
        with opened as response:
            body = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # `str(exc)` is only ever "HTTP Error 400: Bad Request", which says
        # nothing about which of the model, the key or the request OpenRouter
        # objected to. That is in the response body.
        raise RuntimeError(f'{exc} - {error_detail(exc)}') from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f'could not reach OpenRouter: {exc}') from exc
    try:
        return body['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f'unexpected response shape: {json.dumps(body)[:500]}') from exc


def error_detail(exc: urllib.error.HTTPError) -> str:
    """OpenRouter's own explanation of a non-2xx, as far as it can be read.

    Nothing here is allowed to raise: an unreadable explanation must not
    replace the status code that came with it.
    """
    try:
        raw = exc.read().decode(errors='replace').strip()
    except Exception:  # Any read failure means no detail, not a crash.
        return 'no response body'
    if not raw:
        return 'empty response body'
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw[:500]
    error = parsed.get('error') if isinstance(parsed, dict) else None
    if isinstance(error, dict) and error.get('message'):
        return str(error['message'])[:500]
    return raw[:500]


def tidy(notes: str) -> str:
    """Return the model's Markdown with the two things it gets wrong removed."""
    notes = notes.strip()
    fence = WRAPPING_FENCE.match(notes)
    if fence:
        notes = fence.group('body').strip()
    return MARKERS.sub('', notes).strip()


def placeholder(version: str, reason: str) -> str:
    """Return the body to use when there is no draft: a note asking for one."""
    return (
        f'_No release notes were drafted for {version}: {reason}._\n'
        '\n'
        'Write them here before merging. They become the body of the GitHub'
        ' release, above the changelog entry for this version.\n'
    )


def main(argv: list[str] | None = None) -> int:
    """Draft the notes, or write the placeholder, and always succeed."""
    parser = argparse.ArgumentParser(description='Draft release notes for a release.')
    parser.add_argument('--repo', required=True, metavar='OWNER/NAME')
    parser.add_argument('--version', required=True, metavar='X.Y.Z')
    parser.add_argument('--previous', required=True, metavar='X.Y.Z')
    parser.add_argument('--branch', required=True)
    parser.add_argument(
        '--prompt',
        default='.github/release-notes-prompt.md',
        help='The release-notes prompt.',
    )
    parser.add_argument(
        '--changelog',
        required=True,
        help='The generated changelog entry for this release.',
    )
    parser.add_argument(
        '--exemplars',
        default=None,
        help='Past release bodies to write in the register of. Optional.',
    )
    parser.add_argument('--compare-url', default=None, metavar='URL')
    parser.add_argument(
        '--output',
        required=True,
        help='Where to write the notes. Written whether or not a model was reached.',
    )
    args = parser.parse_args(argv)

    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    model = os.environ.get('OPENROUTER_MODEL', '')
    output = pathlib.Path(args.output)

    # Neither of these is an error. The environment that holds the key and
    # the variable is a repository setting, so a release cut before that
    # setting exists gets a placeholder and carries on.
    if not api_key:
        reason = 'no OPENROUTER_API_KEY is configured'
    elif not model:
        reason = 'no OPENROUTER_MODEL variable is set'
    else:
        reason = ''

    if reason:
        print(f'{reason}: writing the placeholder body.', file=sys.stderr)
        output.write_text(placeholder(args.version, reason))
        return 0

    system, user = build_prompts(args)
    try:
        notes = tidy(call_openrouter(system, user, model, api_key))
    except RuntimeError as exc:
        print(f'the draft failed ({exc}): writing the placeholder body.', file=sys.stderr)
        output.write_text(placeholder(args.version, f'the draft failed ({exc})'))
        return 0

    if not notes:
        print('the model answered with nothing: writing the placeholder body.', file=sys.stderr)
        output.write_text(placeholder(args.version, 'the model answered with nothing'))
        return 0

    output.write_text(notes + '\n')
    print(f'{output}: {len(notes)} characters, drafted by {model}.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
