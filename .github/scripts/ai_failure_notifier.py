#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
#
# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""ai-failure-notifications enrichment step.

Invoked by `.github/workflows/ai-failure-enrich.yaml` after
`.github/workflows/notify-scheduled-failure.yaml` (the notifier) has already
created or commented on a placeholder issue for a failed scheduled workflow
run. This script:

1. Finds the placeholder the notifier just touched (or, on a same-run
   re-fire, the issue an earlier run of this script already enriched).
2. Fetches and parses the failing job logs into a deterministic failure
   signature.
3. Builds a small candidate-issue pool (coarse title/body search).
4. Asks an LLM (via OpenRouter) to decide comment-vs-new and draft the text,
   validates the response against the envelope schema, and applies it via
   `gh`.
5. Falls back to a plain, generic issue/comment (still marker-stamped) if
   OpenRouter is unreachable, misconfigured, or returns invalid JSON.

Design reference (not shipped in this repo): the `ai-failure-notifications`
project folder in the `canonical-work-queue` staging repo — see PLAN.md,
SCHEMA.md and spike-step-3/FINDINGS.md, spike-step-4/prompt.md.

The functions above the `--- I/O ---` marker are pure and unit-tested in
`test_ai_failure_notifier.py`. Everything below it talks to `gh` or
OpenRouter and is exercised only by mocking in tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

MARKER_PREFIX = 'ai-failure-notifications'
DEFAULT_MODEL = 'deepseek/deepseek-chat'  # DeepSeek V3 on OpenRouter (PLAN.md Approach §6).
CLOSED_CANDIDATE_WINDOW_DAYS = 14
MAX_CANDIDATES = 3

ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\[\d+(?:;\d+)*m')
TS = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z ')
ERROR_MARKER = re.compile(r'##\[error\]')
PYTEST_SUMMARY = re.compile(r'^(FAILED|ERROR) (\S+?) - (.+)$')
GO_FAIL = re.compile(r'^--- FAIL: (\S+)')
TRACEBACK_END = re.compile(r'^([A-Z][A-Za-z_.]*(?:Error|Exception|Warning)): (.*)$')

# Matches markers stamped by either stage:
#   notifier (stage 1):  <!-- ai-failure-notifications:run=123:origin=new -->
#                         <!-- ai-failure-notifications:run=123:origin=comment -->
#   enricher (stage 2):   <!-- ai-failure-notifications:run=123:sig=abcdef0123456789 -->
MARKER_RE = re.compile(
    r'<!--\s*'
    + re.escape(MARKER_PREFIX)
    + r':run=(\d+)(?::origin=(new|comment))?(?::sig=([0-9a-f]+))?\s*-->'
)


# --- Signature extraction (ported from canonical-work-queue's
# non-roadmap/ai-failure-notifications/spike-step-2/extract_signature.py) ---


def strip_line(line: str) -> str:
    """Remove GHA timestamp and ANSI colours."""
    line = TS.sub('', line, count=1)
    line = ANSI.sub('', line)
    return line.rstrip('\r\n')


def parse_job_log(text: str) -> tuple[list[dict], list[str], str | None, list[str]]:
    """Parse one job's raw log text.

    Returns (pytest_failures, go_failures, traceback_top_error, tail_excerpt).
    """
    lines = [strip_line(line) for line in text.splitlines()]

    pytest_failures: list[dict] = []
    go_failures: list[str] = []
    in_summary = False

    for line in lines:
        if 'short test summary info' in line:
            in_summary = True
            continue
        if in_summary:
            m = PYTEST_SUMMARY.match(line)
            if m:
                kind, test, err = m.groups()
                pytest_failures.append({'kind': kind, 'test': test, 'error': err.strip()})
                continue
            if re.match(r'={3,}.*(failed|passed|error)', line):
                in_summary = False
        m = GO_FAIL.match(line)
        if m:
            go_failures.append(m.group(1))

    traceback_top_error: str | None = None
    for line in reversed(lines):
        m = TRACEBACK_END.match(line)
        if m:
            traceback_top_error = f'{m.group(1)}: {m.group(2).strip()}'
            break

    error_idx = None
    for i, line in enumerate(lines):
        if ERROR_MARKER.search(line):
            error_idx = i
            break
    tail: list[str] = []
    if error_idx is not None:
        for line in reversed(lines[:error_idx]):
            if not line.strip():
                continue
            if line.startswith('##[group]') or line.startswith('##[endgroup]'):
                continue
            tail.append(line)
            if len(tail) >= 40:
                break
        tail.reverse()

    return pytest_failures, go_failures, traceback_top_error, tail


def build_job_signature(
    job_id: int, job_name: str, failed_step: str | None, log_text: str
) -> dict:
    """Parse one job's log into the signature dict shape used throughout."""
    pytest_failures, go_failures, traceback_top_error, tail = parse_job_log(log_text)
    return {
        'job_id': job_id,
        'job_name': job_name,
        'failed_step': failed_step,
        'pytest_failures': pytest_failures,
        'go_failures': go_failures,
        'traceback_top_error': traceback_top_error,
        'tail_excerpt': tail,
    }


def build_run_signature(
    run_id: str, workflow_name: str, html_url: str, created_at: str, jobs: list[dict]
) -> dict:
    """Combine per-job signatures into the full run signature dict."""
    return {
        'run_id': str(run_id),
        'workflow_name': workflow_name,
        'html_url': html_url,
        'created_at': created_at,
        'jobs': jobs,
    }


# --- Marker + signature hashing ---


def signature_hash(signature: dict) -> str:
    """Deterministic short fingerprint of a run signature.

    Used only for the marker's :sig= suffix (not for dedup decisions --
    that's the LLM's job, guided by the candidate pool).
    """
    parts: list[str] = []
    for job in signature['jobs']:
        for f in job['pytest_failures']:
            parts.append(f['test'])
        parts.extend(job['go_failures'])
        if job['traceback_top_error']:
            parts.append(job['traceback_top_error'])
        if job['failed_step']:
            parts.append(job['failed_step'])
    canonical = '\n'.join(sorted(parts)) or signature['workflow_name']
    return hashlib.sha1(canonical.encode('utf-8'), usedforsecurity=False).hexdigest()[:16]


def render_notifier_marker(run_id: str, origin: str) -> str:
    """Render the marker stage 1 (the notifier) stamps.

    `origin` is "new" or "comment", telling stage 2 which artefact it
    touched.
    """
    assert origin in ('new', 'comment')
    return f'<!-- {MARKER_PREFIX}:run={run_id}:origin={origin} -->'


def render_enriched_marker(run_id: str, signature: dict) -> str:
    """Render the marker stage 2 (this script) stamps once fully processed.

    Presence of :sig= is what makes rung 0 (find_run_markers) treat a later
    same-run-id trigger as "already enriched, just note the re-run".
    """
    return f'<!-- {MARKER_PREFIX}:run={run_id}:sig={signature_hash(signature)} -->'


def find_run_markers(
    texts: list[tuple[int, str]], run_id: str
) -> tuple[int | None, str | None, int | None]:
    """Scan (issue_number, text) pairs for markers belonging to `run_id`.

    Returns (enriched_issue, origin_kind, origin_issue):
    - enriched_issue: an issue number carrying a :sig= marker for this run
      (rung 0 -- this run was already fully enriched once), else None.
    - origin_kind / origin_issue: the "new"/"comment" marker the notifier
      stamped for this run (identifies which artefact to upgrade), else
      (None, None).
    """
    run_id = str(run_id)
    enriched_issue = None
    origin_kind = None
    origin_issue = None
    for number, text in texts:
        if not text:
            continue
        for m in MARKER_RE.finditer(text):
            if m.group(1) != run_id:
                continue
            if m.group(3):  # :sig=
                enriched_issue = number
            elif m.group(2):  # :origin=
                origin_kind = m.group(2)
                origin_issue = number
    return enriched_issue, origin_kind, origin_issue


# --- Candidate pool ---


def within_window(iso_timestamp: str, now: datetime, days: int) -> bool:
    """Return whether `iso_timestamp` falls within `days` of `now`."""
    ts = datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
    return now - ts <= timedelta(days=days)


def build_candidates_block(
    open_issues: list[dict], closed_issues: list[dict], now: datetime
) -> str:
    """Render the {{CANDIDATES_BLOCK}} the step-4 prompt expects.

    Up to MAX_CANDIDATES entries: open issues first, recently-closed issues
    (<=14 days, spike-step-3/FINDINGS.md "medium-max" rule) filling any
    remaining slots and explicitly labelled as closed so the LLM never
    auto-treats one as a strong match.
    """
    entries: list[str] = []
    for issue in open_issues:
        if len(entries) >= MAX_CANDIDATES:
            break
        excerpt = (issue.get('body') or '').strip().splitlines()
        excerpt_text = excerpt[0][:300] if excerpt else '(no body)'
        entries.append(f'- **#{issue["number"]} — {issue["title"]}** (open)\n  > {excerpt_text}')

    recent_closed = [
        i
        for i in closed_issues
        if i.get('closedAt') and within_window(i['closedAt'], now, CLOSED_CANDIDATE_WINDOW_DAYS)
    ]
    for issue in recent_closed:
        if len(entries) >= MAX_CANDIDATES:
            break
        excerpt = (issue.get('body') or '').strip().splitlines()
        excerpt_text = excerpt[0][:300] if excerpt else '(no body)'
        entries.append(
            f'- **#{issue["number"]} — {issue["title"]}** (closed {issue["closedAt"]} -- '
            f'recently closed; treat as at most a medium-confidence match)\n  > {excerpt_text}'
        )

    if not entries:
        return '(no open scheduled-failure issues found for this workflow)'
    return '\n'.join(entries)


# --- Prompt building (ported from spike-step-4/prompt.md) ---

SYSTEM_PROMPT = """\
You are the enrichment step of an internal CI failure-triage bot for the
Canonical Charm Tech team. A scheduled GitHub Actions workflow just failed.
A separate deterministic parser has already extracted a structured failure
signature from the run's logs -- you do not have repository access, log
access, or internet access beyond what is given to you in this message.
Work only from the signature JSON and candidate issues you're given.

Your job: decide whether this failure is a new occurrence of an
already-tracked problem (comment on the existing issue) or something not
currently tracked (open a new issue), and draft the text for whichever
artefact you choose. Output ONLY the JSON envelope described below -- no
prose before or after it, no markdown code fences around it.

## Reading the signature

The signature has one entry per failed job in `jobs[]`. Each entry may
carry, in decreasing order of how much you should trust it:

1. `pytest_failures[]` -- `{kind, test, error}` triples parsed from
   pytest's "short test summary info" block. `test` is a real pytest node
   id; `error` is the tail of that summary line and CAN BE TRUNCATED by
   pytest itself (it cuts long messages short, e.g.
   "PendingDeprecat..."). If an `error` string ends in `...`, treat it
   as unreliable for anything beyond "this test failed" -- do not quote it
   as the root cause, do not put the truncated fragment in a title. Look
   at `traceback_top_error` and `tail_excerpt` for that job instead; if
   they don't resolve it either, describe the failure by test name only
   and say the specific assertion text is unavailable.
2. `traceback_top_error` -- the last `<ErrorClass>: <message>` line found
   anywhere in the job's log. Usually the real exception, but it is a
   last-line heuristic: on jobs where cleanup code raises its own warning
   after the real failure (a `ResourceWarning` from tempfile cleanup is
   the known example), this field can point at the cleanup noise instead
   of the actual cause. If `traceback_top_error` names a `Warning` class
   while `pytest_failures[]` for the same job names an `Error` class,
   trust the `pytest_failures[]` entry for what actually failed and treat
   `traceback_top_error` as noise.
3. `tail_excerpt[]` -- the last ~40 non-empty log lines before the job's
   first `##[error]` marker. This is what's left when neither of the
   above fired. Sometimes it contains an unambiguous plain-text failure
   (e.g. a Go `panic:`, a shell command's final non-zero-exit message, an
   infra tool's own `level=ERROR msg="..."` line) -- if so, use it. Other
   times it shows the *shape* of a timeout or an in-progress hook without
   ever stating what actually broke. Do not guess a specific root cause
   from an inconclusive `tail_excerpt`. It is fine, and preferred, to say
   plainly that the cause isn't visible in the available log excerpt.

A job with no `pytest_failures`, no `traceback_top_error`, and a
`tail_excerpt` that never names an exception, an error code, or an
explicit failure message (only status-transition noise) is very likely an
**infrastructural** failure (bootstrap, provisioning, network) rather than
a test regression, PROVIDED the excerpt at least shows a concrete
infra-level error. Say so explicitly -- title and body should make clear
this is "infrastructure failing before tests could run" language, not
"test X failed" language, and do not name a specific test as the culprit.

If even that infra-level signal is missing or the excerpt is genuinely
inconclusive, do not invent a specific-sounding title. Use a plain, honest
title that names the workflow and says the cause is unclear from the log
excerpt, set "confidence": "low", and say in `dedup_reason` what
information would be needed to do better. Never fabricate a
plausible-sounding cause to fill the gap.

A run can have multiple failed jobs with different signatures. Handle this
as follows:

- If all failed jobs share essentially the same signature, treat it as one
  failure and write one title/body for it, noting how many jobs it hit.
- If failed jobs split into distinct signatures, decide whether one is
  clearly the dominant, actionable story, with others being a smaller
  number of already-familiar, separately-tracked issues riding along. If
  so, make the dominant one the subject of `title`/`action`, and mention
  the others in `body` as a secondary note plus in `dedup_reason`.
- If failed jobs are multiple genuinely distinct, comparably-important
  problems with no dominant one, use a title naming the workflow and the
  count/spread of distinct causes and list each in `body` as its own
  bullet. Don't pick one arbitrarily and bury the rest.

## Handling multiple independent failures (`also`)

When a run has a dominant story plus one or two secondary failures that
have distinct signatures from the dominant one AND would either match a
different existing tracked issue or themselves be dominant enough to
warrant their own artefact if seen alone, emit an `also` array on the
envelope with one entry per secondary. Each `also[i]` is a self-contained
decision (its own `action`, its own `target_issue`/`title`, its own
`confidence`, its own `dedup_reason`).

Do not use `also` to split a single failure across two entries; do not
nest `also` inside an `also` entry; cap: 2 `also` entries per envelope.

## Body structure (for `action: "new"`)

Use this shape, adapting to how many distinct failures you're describing:

```
## Summary
<one or two sentences: what broke, at what scope>

## Failures
- **<job name>**: <headline error, or "infrastructure failure -- <what>",
  or "cause unclear from the available log excerpt">
  (omit this section entirely if there's exactly one failing job)

## Likely root cause
<ONLY include this section if the signature actually supports a specific
hypothesis. Omit it entirely otherwise -- expected on roughly half the
signatures you'll see.>
```

For `action: "comment"`, keep the comment short: what matches the existing
issue (or what's new/different), and nothing else.

## Deciding comment vs new

You are given up to 3 candidate existing issues (title + excerpt), already
pre-filtered to the same workflow by a coarser deterministic search. Some
candidates may be marked "(closed ...)" -- these are recently-closed
issues included for context only; never target a closed issue with
`action: "comment"`, and never let a closed candidate alone justify
`confidence: "high"`.

- **Strong** -- at least one `pytest_failures[].test` (or, for
  infra/tail-only failures, the same `failed_step` plus the same concrete
  error text) matches an OPEN candidate, AND the top error class matches
  too -> `action: "comment"`, `confidence: "high"`.
- **Medium** -- same workflow and same `failed_step`, or same top error
  class, but the specific test/error text has drifted, OR the only match
  is a recently-closed candidate -> `action: "comment"` (target the open
  issue only; if the only match is closed, use `action: "new"` instead and
  mention the closed issue in `dedup_reason`), `confidence: "medium"`, and
  say the drift explicitly in `body` and `dedup_reason`.
- **Weak** -- only the workflow name matches, or only a vague thematic
  overlap -- this is not a dedup match. `action: "new"`.

Do not comment on a candidate just because one exists for the same
workflow -- check whether the *signature* actually matches.

## Labels and issue type

- Every `action: "new"` issue MUST include "scheduled-failure" in
  `labels` -- it's the marker label the dedup search itself depends on.
- Add other labels only from concepts the signature actually supports:
  `flaky`, `regression`, `infra`, `upstream`. Don't add a label you can't
  justify from the signature.
- `issue_type` is "bug" when you're reasonably sure this is a defect. Use
  `null` when genuinely unsure -- this is normal and expected for
  low-confidence signatures, not an edge case.

## Never

- Never invent a root cause, a PR number, a file/line, or a "likely fix"
  that isn't directly supported by the signature JSON you were given.
- Never output anything except the single JSON envelope object.
"""

USER_PROMPT_TEMPLATE = """\
Workflow: {workflow_name}
Run: {run_url}

## Extracted failure signature (deterministic parser output, JSON)

{signature_json}

## Candidate existing open issues (same workflow, pre-filtered by title;
## may include recently-closed issues explicitly marked as such; may be
## empty)

{candidates_block}

Produce the JSON envelope now.
"""


def build_prompt(
    workflow_name: str, run_url: str, signature: dict, candidates_block: str
) -> tuple[str, str]:
    """Render the (system, user) prompt pair for the OpenRouter call."""
    user = USER_PROMPT_TEMPLATE.format(
        workflow_name=workflow_name,
        run_url=run_url,
        signature_json=json.dumps(signature, indent=2),
        candidates_block=candidates_block,
    )
    return SYSTEM_PROMPT, user


# --- Envelope schema validation (hand-rolled -- deliberately not the
# `jsonschema` package, to keep the script's only third-party dependency as
# `requests`; see SCHEMA.md for the source-of-truth JSON Schema this mirrors) ---

_ENTRY_COMMON_REQUIRED = ('action', 'body', 'dedup_reason', 'confidence')
_ENTRY_KNOWN_KEYS = {
    'action',
    'body',
    'dedup_reason',
    'confidence',
    'title',
    'labels',
    'issue_type',
    'target_issue',
}


def validate_entry(entry: Any, *, path: str) -> list[str]:
    """Validate one envelope entry (top-level or an `also[i]`) against the schema."""
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f'{path}: expected an object, got {type(entry).__name__}']

    for field in _ENTRY_COMMON_REQUIRED:
        if field not in entry:
            errors.append(f"{path}: missing required field '{field}'")

    unknown = set(entry) - _ENTRY_KNOWN_KEYS
    if unknown:
        errors.append(f'{path}: unknown field(s) {sorted(unknown)}')

    action = entry.get('action')
    if action not in ('comment', 'new'):
        errors.append(f"{path}.action: must be 'comment' or 'new', got {action!r}")
        return errors  # can't check action-conditional fields without a valid action

    if not isinstance(entry.get('body'), str) or not entry.get('body'):
        errors.append(f'{path}.body: must be a non-empty string')
    if not isinstance(entry.get('dedup_reason'), str) or not entry.get('dedup_reason'):
        errors.append(f'{path}.dedup_reason: must be a non-empty string')
    if entry.get('confidence') not in ('high', 'medium', 'low'):
        errors.append(
            f'{path}.confidence: must be one of high/medium/low, got {entry.get("confidence")!r}'
        )

    if action == 'new':
        for field in ('title', 'labels', 'issue_type'):
            if field not in entry:
                errors.append(f"{path}: action='new' requires '{field}'")
        if 'target_issue' in entry:
            errors.append(f"{path}: action='new' must not include 'target_issue'")
        labels = entry.get('labels')
        if labels is not None:
            if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
                errors.append(f'{path}.labels: must be an array of strings')
            elif 'scheduled-failure' not in labels:
                errors.append(f"{path}.labels: must contain 'scheduled-failure'")
        if 'issue_type' in entry and not (
            entry['issue_type'] is None or isinstance(entry['issue_type'], str)
        ):
            errors.append(f'{path}.issue_type: must be a string or null')
    else:  # comment
        if 'target_issue' not in entry:
            errors.append(f"{path}: action='comment' requires 'target_issue'")
        elif not isinstance(entry['target_issue'], int) or entry['target_issue'] < 1:
            errors.append(f'{path}.target_issue: must be a positive integer')
        for field in ('title', 'labels', 'issue_type'):
            if field in entry:
                errors.append(f"{path}: action='comment' must not include '{field}'")

    return errors


def validate_envelope(envelope: Any) -> list[str]:
    """Validate a top-level envelope (may carry `also`).

    Returns a list of human-readable errors; empty list means valid.
    """
    if not isinstance(envelope, dict):
        return ['envelope: expected a JSON object']

    errors = validate_entry(envelope, path='envelope')

    also = envelope.get('also')
    if also is not None:
        if not isinstance(also, list) or len(also) > 2:
            errors.append('envelope.also: must be an array of at most 2 entries')
        else:
            for i, entry in enumerate(also):
                if isinstance(entry, dict) and 'also' in entry:
                    errors.append(f"envelope.also[{i}]: nested 'also' is not allowed")
                errors.extend(validate_entry(entry, path=f'envelope.also[{i}]'))

    unknown_top = set(envelope) - _ENTRY_KNOWN_KEYS - {'also'}
    if unknown_top:
        errors.append(f'envelope: unknown field(s) {sorted(unknown_top)}')

    return errors


ENVELOPE_JSON_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'ai-failure-notifications envelope',
    'type': 'object',
    'required': ['action', 'body', 'dedup_reason', 'confidence'],
    'properties': {
        'action': {'enum': ['comment', 'new']},
        'body': {'type': 'string', 'minLength': 1},
        'dedup_reason': {'type': 'string', 'minLength': 1},
        'confidence': {'enum': ['high', 'medium', 'low']},
        'title': {'type': 'string', 'minLength': 1},
        'labels': {'type': 'array', 'items': {'type': 'string'}},
        'issue_type': {'type': ['string', 'null']},
        'target_issue': {'type': 'integer', 'minimum': 1},
        'also': {'type': 'array', 'maxItems': 2, 'items': {'$ref': '#/$defs/envelopeEntry'}},
    },
    'additionalProperties': False,
    'allOf': [{'$ref': '#/$defs/actionConditionals'}],
    '$defs': {
        'actionConditionals': {
            'allOf': [
                {
                    'if': {'properties': {'action': {'const': 'new'}}},
                    'then': {
                        'required': ['title', 'labels', 'issue_type'],
                        'not': {'required': ['target_issue']},
                        'properties': {
                            'labels': {
                                'type': 'array',
                                'items': {'type': 'string'},
                                'contains': {'const': 'scheduled-failure'},
                            }
                        },
                    },
                },
                {
                    'if': {'properties': {'action': {'const': 'comment'}}},
                    'then': {
                        'required': ['target_issue'],
                        'not': {
                            'anyOf': [
                                {'required': ['title']},
                                {'required': ['labels']},
                                {'required': ['issue_type']},
                            ]
                        },
                    },
                },
            ]
        },
        'envelopeEntry': {
            'type': 'object',
            'required': ['action', 'body', 'dedup_reason', 'confidence'],
            'properties': {
                'action': {'enum': ['comment', 'new']},
                'body': {'type': 'string', 'minLength': 1},
                'dedup_reason': {'type': 'string', 'minLength': 1},
                'confidence': {'enum': ['high', 'medium', 'low']},
                'title': {'type': 'string', 'minLength': 1},
                'labels': {'type': 'array', 'items': {'type': 'string'}},
                'issue_type': {'type': ['string', 'null']},
                'target_issue': {'type': 'integer', 'minimum': 1},
            },
            'additionalProperties': False,
            'allOf': [{'$ref': '#/$defs/actionConditionals'}],
        },
    },
}


# --- I/O ---


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a `gh` subcommand, returning the completed process."""
    return subprocess.run(['gh', *args], text=True, capture_output=True, check=check)


def gh_json(*args: str) -> Any:
    """Run a `gh ... --json ...` subcommand and parse its stdout as JSON."""
    result = gh(*args)
    return json.loads(result.stdout) if result.stdout.strip() else None


def fetch_failed_jobs(repo: str, run_id: str) -> list[dict]:
    """List the failed jobs of a run, each with its id, name, and failed step."""
    data = gh_json('run', 'view', str(run_id), '--repo', repo, '--json', 'jobs') or {}
    failed = []
    for job in data.get('jobs', []):
        if job.get('conclusion') != 'failure':
            continue
        failed_step = None
        for step in job.get('steps') or []:
            if step.get('conclusion') == 'failure':
                failed_step = step.get('name')
                break
        failed.append({'id': job['databaseId'], 'name': job['name'], 'failed_step': failed_step})
    return failed


def fetch_job_log(repo: str, run_id: str, job_id: int) -> str:
    """Fetch one job's full log text."""
    return gh(
        'run', 'view', str(run_id), '--repo', repo, '--job', str(job_id), '--log', check=False
    ).stdout


def fetch_run_meta(repo: str, run_id: str) -> dict:
    """Fetch a run's display metadata (title, workflow name, url, createdAt)."""
    return (
        gh_json(
            'run',
            'view',
            str(run_id),
            '--repo',
            repo,
            '--json',
            'displayTitle,workflowName,url,createdAt',
        )
        or {}
    )


def search_issue_numbers(repo: str, query_text: str) -> list[int]:
    """Search issues (any state) in `repo` for `query_text`, return issue numbers."""
    query = f'repo:{repo} "{query_text}"'
    data = gh_json('search', 'issues', '--limit', '10', '--json', 'number', query) or []
    return [item['number'] for item in data]


def fetch_issue_texts(repo: str, number: int) -> list[str]:
    """Fetch an issue's body plus all comment bodies, for marker scanning."""
    data = gh_json('issue', 'view', str(number), '--repo', repo, '--json', 'body,comments') or {}
    texts = [data.get('body') or '']
    for c in data.get('comments') or []:
        texts.append(c.get('body') or '')
    return texts


def locate_run_markers(repo: str, run_id: str) -> tuple[int | None, str | None, int | None]:
    """Search `repo` for markers belonging to `run_id` and classify them."""
    hits = search_issue_numbers(repo, f'{MARKER_PREFIX}:run={run_id}')
    texts = [(n, t) for n in hits for t in fetch_issue_texts(repo, n)]
    return find_run_markers(texts, run_id)


def search_candidates(repo: str, workflow_name: str) -> tuple[list[dict], list[dict]]:
    """Coarse candidate search: open and closed issues matching the workflow name."""
    fields = 'number,title,body,createdAt,closedAt'
    open_issues = (
        gh_json(
            'issue',
            'list',
            '--repo',
            repo,
            '--state',
            'open',
            '--search',
            f'"{workflow_name}"',
            '--json',
            fields,
            '--limit',
            '20',
        )
        or []
    )
    closed_issues = (
        gh_json(
            'issue',
            'list',
            '--repo',
            repo,
            '--state',
            'closed',
            '--search',
            f'"{workflow_name}"',
            '--json',
            fields,
            '--limit',
            '20',
        )
        or []
    )
    return open_issues, closed_issues


def existing_labels(repo: str) -> set[str]:
    """Return the set of label names that already exist in `repo`."""
    data = gh_json('label', 'list', '--repo', repo, '--json', 'name', '--limit', '100') or []
    return {item['name'] for item in data}


def filter_labels(labels: list[str], available: set[str]) -> list[str]:
    """Drop labels that don't already exist in the repo (never auto-create)."""
    return [label for label in labels if label in available]


def call_openrouter(system_prompt: str, user_prompt: str, model: str, api_key: str) -> dict:
    """POST the prompt to OpenRouter with the envelope schema, return the parsed JSON."""
    import requests

    response = requests.post(
        'https://openrouter.ai/api/v1/chat/completions',
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        json={
            'model': model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'response_format': {
                'type': 'json_schema',
                'json_schema': {
                    'name': 'ai_failure_notification',
                    'strict': True,
                    'schema': ENVELOPE_JSON_SCHEMA,
                },
            },
        },
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()['choices'][0]['message']['content']
    return json.loads(content)


def write_step_summary(message: str) -> None:
    """Append a line to the job's step summary (or stderr, outside Actions)."""
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if not path:
        print(message, file=sys.stderr)
        return
    with open(path, 'a', encoding='utf-8') as f:
        f.write(message + '\n')


def set_output(name: str, value: str) -> None:
    """Write a `name=value` line to $GITHUB_OUTPUT, if set."""
    path = os.environ.get('GITHUB_OUTPUT')
    if not path:
        return
    with open(path, 'a', encoding='utf-8') as f:
        f.write(f'{name}={value}\n')


def plain_fallback_body(workflow_name: str, run_url: str) -> str:
    """The original notifier's plain, generic body text."""
    return f"Scheduled workflow '{workflow_name}' failed: {run_url}"


def apply_entry(repo: str, entry: dict, marker: str, *, default_target: int | None = None) -> str:
    """Create or comment on an issue per one envelope entry, stamping `marker`."""
    body = entry['body'].rstrip() + f'\n\n{marker}'
    if entry['action'] == 'new':
        available = existing_labels(repo)
        labels = filter_labels(entry.get('labels') or [], available)
        if 'scheduled-failure' not in available:
            write_step_summary(
                '`scheduled-failure` label does not exist in this repo yet -- created issue '
                'without it (see PLAN.md Open Questions: labels land via a separate '
                'canonical-repo-automation PR).'
            )
        args = ['issue', 'create', '--repo', repo, '--title', entry['title'], '--body', body]
        for label in labels:
            args += ['--label', label]
        issue_type = entry.get('issue_type')
        result = None
        if issue_type:
            result = gh(*args, '--type', issue_type, check=False)
            if result.returncode != 0:
                write_step_summary(
                    f'`gh issue create --type {issue_type}` failed ({result.stderr.strip()}); '
                    'retrying without --type.'
                )
                result = None
        if result is None:
            result = gh(*args)
        return result.stdout.strip()
    else:
        target = entry.get('target_issue', default_target)
        gh('issue', 'comment', str(target), '--repo', repo, '--body', body)
        return f'commented on #{target}'


def main() -> int:
    """Entry point: locate the run's marker, enrich or fall back, apply, and exit."""
    repo = os.environ['REPO']
    run_id = str(os.environ['RUN_ID'])
    workflow_name = os.environ['WORKFLOW_NAME']
    run_url = os.environ['RUN_URL']
    api_key = os.environ.get('OPENROUTER_API_KEY', '')
    model = os.environ.get('OPENROUTER_MODEL') or DEFAULT_MODEL

    enriched_issue, origin_kind, origin_issue = locate_run_markers(repo, run_id)

    if enriched_issue is not None:
        # Rung 0 (spike-step-3/FINDINGS.md): this run id was already fully
        # enriched once -- a re-run of the same failing jobs re-triggered us.
        # Comment, don't skip and don't redo the full LLM pass.
        gh(
            'issue',
            'comment',
            str(enriched_issue),
            '--repo',
            repo,
            '--body',
            f'Re-run attempt still failing: {run_url}\n\n<!-- {MARKER_PREFIX}:run={run_id} -->',
        )
        write_step_summary(
            f'Rung 0: run {run_id} already enriched on #{enriched_issue}; commented re-run note.'
        )
        set_output('handled', 'true')
        return 0

    if origin_issue is None:
        # Shouldn't happen -- the notifier always stamps a marker -- but
        # don't lose the notification if it does.
        write_step_summary(
            'No notifier marker found for this run id; falling back to a plain issue.'
        )
        result = gh(
            'issue',
            'create',
            '--repo',
            repo,
            '--title',
            f"Scheduled workflow '{workflow_name}' failed",
            '--body',
            plain_fallback_body(workflow_name, run_url)
            + f'\n\n<!-- {MARKER_PREFIX}:run={run_id}:origin=new -->',
        )
        origin_issue = int(result.stdout.strip().rstrip('/').rsplit('/', 1)[-1])
        origin_kind = 'new'

    failed_jobs = fetch_failed_jobs(repo, run_id)
    jobs_sig = [
        build_job_signature(
            job['id'], job['name'], job['failed_step'], fetch_job_log(repo, run_id, job['id'])
        )
        for job in failed_jobs
    ]
    meta = fetch_run_meta(repo, run_id)
    signature = build_run_signature(
        run_id, workflow_name, run_url, meta.get('createdAt', ''), jobs_sig
    )
    enriched_marker = render_enriched_marker(run_id, signature)

    if not api_key:
        write_step_summary('No OPENROUTER_API_KEY configured -- using the plain fallback body.')
        apply_entry(
            repo,
            {
                'action': 'comment' if origin_kind == 'comment' else 'new',
                'body': plain_fallback_body(workflow_name, run_url),
                'title': f"Scheduled workflow '{workflow_name}' failed",
                'labels': ['scheduled-failure'],
                'issue_type': None,
            }
            if origin_kind != 'comment'
            else {
                'action': 'comment',
                'body': plain_fallback_body(workflow_name, run_url),
                'target_issue': origin_issue,
            },
            enriched_marker,
            default_target=origin_issue,
        )
        set_output('handled', 'true')
        return 0

    open_candidates, closed_candidates = search_candidates(repo, workflow_name)
    open_candidates = [c for c in open_candidates if c['number'] != origin_issue]
    from datetime import datetime as _dt

    candidates_block = build_candidates_block(
        open_candidates, closed_candidates, _dt.now(timezone.utc)
    )
    system_prompt, user_prompt = build_prompt(workflow_name, run_url, signature, candidates_block)

    try:
        envelope = call_openrouter(system_prompt, user_prompt, model, api_key)
    except Exception as exc:  # network error, non-2xx, bad JSON, etc.
        write_step_summary(f'OpenRouter call failed ({exc}); using the plain fallback body.')
        apply_entry(
            repo,
            {
                'action': 'new',
                'body': plain_fallback_body(workflow_name, run_url),
                'title': f"Scheduled workflow '{workflow_name}' failed",
                'labels': ['scheduled-failure'],
                'issue_type': None,
            }
            if origin_kind != 'comment'
            else {
                'action': 'comment',
                'body': plain_fallback_body(workflow_name, run_url),
                'target_issue': origin_issue,
            },
            enriched_marker,
            default_target=origin_issue,
        )
        set_output('handled', 'true')
        return 0

    errors = validate_envelope(envelope)
    if errors:
        write_step_summary(
            'LLM output failed schema validation:\n' + '\n'.join(f'- {e}' for e in errors)
        )
        apply_entry(
            repo,
            {
                'action': 'new',
                'body': plain_fallback_body(workflow_name, run_url),
                'title': f"Scheduled workflow '{workflow_name}' failed",
                'labels': ['scheduled-failure'],
                'issue_type': None,
            }
            if origin_kind != 'comment'
            else {
                'action': 'comment',
                'body': plain_fallback_body(workflow_name, run_url),
                'target_issue': origin_issue,
            },
            enriched_marker,
            default_target=origin_issue,
        )
        set_output('handled', 'true')
        return 0

    if envelope['action'] == 'new' and origin_kind == 'new':
        # Upgrade the placeholder in place rather than creating a duplicate.
        available = existing_labels(repo)
        labels = filter_labels(envelope.get('labels') or [], available)
        edit_args = [
            'issue',
            'edit',
            str(origin_issue),
            '--repo',
            repo,
            '--title',
            envelope['title'],
            '--body',
            envelope['body'].rstrip() + f'\n\n{enriched_marker}',
        ]
        for label in labels:
            edit_args += ['--add-label', label]
        gh(*edit_args)
    elif envelope['action'] == 'comment' and envelope.get('target_issue') == origin_issue:
        apply_entry(repo, envelope, enriched_marker, default_target=origin_issue)
    elif envelope['action'] == 'comment':
        # LLM picked a different candidate than the notifier's coarse match.
        apply_entry(repo, envelope, enriched_marker)
        if origin_kind == 'comment':
            gh(
                'issue',
                'comment',
                str(origin_issue),
                '--repo',
                repo,
                '--body',
                f'This looks like a distinct issue -- see #{envelope["target_issue"]}.\n\n'
                f'{enriched_marker}',
            )
    else:
        # action == "new" but origin_kind == "comment": the coarse title
        # match landed on an unrelated older issue; this is genuinely new.
        apply_entry(repo, envelope, enriched_marker)
        gh(
            'issue',
            'comment',
            str(origin_issue),
            '--repo',
            repo,
            '--body',
            f'This looks like a distinct issue from this one -- opened separately.\n\n'
            f'{enriched_marker}',
        )

    for also_entry in envelope.get('also') or []:
        apply_entry(repo, also_entry, enriched_marker)

    set_output('handled', 'true')
    return 0


if __name__ == '__main__':
    sys.exit(main())
