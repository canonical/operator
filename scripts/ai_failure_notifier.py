#!/usr/bin/env python3
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

The functions above the `--- I/O ---` marker are pure and unit-tested in
`scripts/test/test_ai_failure_notifier.py`. Everything below it talks to `gh`
or OpenRouter and is exercised only by mocking in tests.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from typing import Any, Literal

MARKER_PREFIX = 'ai-failure-notifications'
DEFAULT_MODEL = 'deepseek/deepseek-chat'  # DeepSeek V3 on OpenRouter.
CLOSED_CANDIDATE_WINDOW_DAYS = 14
MAX_CANDIDATES = 3
# How many recently-updated issues to scan for the notifier's marker. The
# artefact we are looking for was touched minutes ago, so this only has to
# cover issue churn in that window; 50 is far more than `operator` sees.
RECENT_ISSUE_SCAN = 50

# Colour escapes, which Actions logs are full of. Two alternatives, because
# the logs contain both the real thing and a mangled form where the ESC byte
# has already been stripped, leaving a bare "[32m".
ANSI = re.compile(
    r"""
    \x1b\[ [0-9;]* [A-Za-z]   # a full escape: ESC [ params letter
    |
    \[ \d+ (?:;\d+)* m        # ESC already stripped: [32m, [1;33m
    """,
    re.VERBOSE,
)

# The timestamp Actions prefixes to every log line, for example
# "2026-07-21T16:17:04.8204062Z ". Stripped before anything else is matched.
TS = re.compile(
    r"""
    ^\d{4}-\d{2}-\d{2}        # date: 2026-07-21
    T\d{2}:\d{2}:\d{2}        # time: T16:17:04
    \.\d+Z[ ]                 # fractional seconds, zone, one trailing space
    """,
    re.VERBOSE,
)

# Actions' own annotation for a failing step.
ERROR_MARKER = re.compile(r'##\[error\]')

# The runner opens every step with "##[group]Run <script>", echoes the whole
# `run:` block a line at a time, dumps the step's env, and closes with
# "##[endgroup]". None of that is output: it is the step's own source. A
# multi-line `run:` therefore puts its every branch into the log, including
# the ones that did not execute, and parsing it produces failures the run
# never had.
#
# Colour is not a usable signal here -- the runner marks echoed lines cyan-
# bold, but ANSI above strips that before anything is matched -- so the
# group boundary is what separates a step's script from its output.
GROUP_RUN_START = re.compile(r'^##\[group\]Run ')
GROUP_END = re.compile(r'^##\[endgroup\]')

# A line from pytest's short summary, for example
# "FAILED tests/integration/test_charm.py::test_deploy - TimeoutError: ...".
PYTEST_SUMMARY = re.compile(
    r"""
    ^(FAILED|ERROR)[ ]         # which of the two pytest reports
    (\S+?)[ ]-[ ]              # the test id, up to the " - " separator
    (.+)$                      # the error message, to end of line
    """,
    re.VERBOSE,
)

# The end of pytest's summary section, for example
# "======== 3 failed, 41 passed, 2 warnings in 512.44s ========".
PYTEST_SUMMARY_END = re.compile(
    r"""
    ={3,}                      # the run of = that brackets the line
    .*(failed|passed|error)    # and one of pytest's outcome words
    """,
    re.VERBOSE,
)

# A failing Go test, for example "--- FAIL: TestFoo (0.01s)".
GO_FAIL = re.compile(r'^--- FAIL: (\S+)')

# The last line of a Python traceback: the exception type and its message,
# for example "KeyError: 'loki/0'". Deliberately narrow -- it must look like an
# exception class name -- so that arbitrary "word: text" log lines don't match.
TRACEBACK_END = re.compile(
    r"""
    ^([A-Z]                          # exception types start with a capital
      [A-Za-z_.]*                    # dotted path allowed: ops.pebble.APIError
      (?:Error|Exception|Warning))   # and conventionally end one of three ways
    :[ ](.*)$                        # then ": " and the message
    """,
    re.VERBOSE,
)

# Matches markers stamped by either workflow:
#   notifier:  <!-- ai-failure-notifications:run=123:origin=new -->
#              <!-- ai-failure-notifications:run=123:origin=comment -->
#   enricher:  <!-- ai-failure-notifications:run=123:sig=abcdef0123456789 -->
MARKER_RE = re.compile(
    r'<!--\s*'
    + re.escape(MARKER_PREFIX)
    + r"""
    :run=(?P<run_id>\d+)
    (?::origin=(?P<origin>new|comment))?
    (?::sig=(?P<sig>[0-9a-f]+))?
    \s*-->
    """,
    re.VERBOSE,
)


# --- Structured shapes ---
#
# The signature is built here, serialised into the prompt, and hashed for the
# marker, so its shape is worth pinning down rather than passing dicts around.
# `dataclasses.asdict` preserves field declaration order, which is what the
# prompt's JSON ends up in.


@dataclasses.dataclass(frozen=True)
class PytestFailure:
    """One line of pytest's short summary."""

    kind: str  # "FAILED" or "ERROR" -- pytest reports both here.
    test: str
    error: str


@dataclasses.dataclass(frozen=True)
class JobSignature:
    """What the deterministic parser could extract from one failed job's log."""

    job_id: int
    job_name: str
    failed_step: str | None
    pytest_failures: list[PytestFailure]
    go_failures: list[str]
    traceback_top_error: str | None
    tail_excerpt: list[str]


@dataclasses.dataclass(frozen=True)
class RunSignature:
    """Every failed job of one run, plus the run's own identifying fields."""

    run_id: str
    workflow_name: str
    html_url: str
    created_at: str
    jobs: list[JobSignature]

    def as_json(self) -> str:
        """Render for the prompt, in field declaration order."""
        return json.dumps(dataclasses.asdict(self), indent=2)


@dataclasses.dataclass(frozen=True)
class FailedJob:
    """A failed job as listed by `gh run view`, before its log is fetched."""

    id: int
    name: str
    failed_step: str | None


@dataclasses.dataclass(frozen=True)
class CandidateIssue:
    """An existing issue that might already track this failure."""

    number: int
    title: str
    body: str | None
    closed_at: str | None

    @classmethod
    def from_gh(cls, data: dict[str, Any]) -> CandidateIssue:
        """Build from one element of `gh issue list --json ...` output."""
        return cls(
            number=data['number'],
            title=data['title'],
            body=data.get('body'),
            closed_at=data.get('closedAt'),
        )

    def excerpt(self) -> str:
        """The first line of the body, bounded, for the candidate block."""
        lines = (self.body or '').strip().splitlines()
        return lines[0][:300] if lines else '(no body)'


# --- Signature extraction ---


def strip_line(line: str) -> str:
    """Remove GHA timestamp and ANSI colours."""
    line = TS.sub('', line, count=1)
    line = ANSI.sub('', line)
    return line.rstrip('\r\n')


def strip_log(text: str) -> list[str]:
    """Split a raw job log into output lines, dropping each step's own script.

    Everything between "##[group]Run ..." and "##[endgroup]" is the runner
    echoing the step's `run:` block and env, not anything the step printed.
    See GROUP_RUN_START above for why that matters.
    """
    lines: list[str] = []
    in_step_header = False
    for raw in text.splitlines():
        line = strip_line(raw)
        if GROUP_RUN_START.match(line):
            in_step_header = True
            continue
        if in_step_header:
            in_step_header = not GROUP_END.match(line)
            continue
        lines.append(line)
    return lines


def parse_job_log(
    text: str,
) -> tuple[list[PytestFailure], list[str], str | None, list[str]]:
    """Parse one job's raw log text.

    Returns (pytest_failures, go_failures, traceback_top_error, tail_excerpt).
    """
    lines = strip_log(text)

    pytest_failures: list[PytestFailure] = []
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
                pytest_failures.append(PytestFailure(kind, test, err.strip()))
                continue
            if PYTEST_SUMMARY_END.match(line):
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
) -> JobSignature:
    """Parse one job's log into its signature."""
    pytest_failures, go_failures, traceback_top_error, tail = parse_job_log(log_text)
    return JobSignature(
        job_id=job_id,
        job_name=job_name,
        failed_step=failed_step,
        pytest_failures=pytest_failures,
        go_failures=go_failures,
        traceback_top_error=traceback_top_error,
        tail_excerpt=tail,
    )


def build_run_signature(
    run_id: str, workflow_name: str, html_url: str, created_at: str, jobs: list[JobSignature]
) -> RunSignature:
    """Combine per-job signatures into the full run signature."""
    return RunSignature(
        run_id=str(run_id),
        workflow_name=workflow_name,
        html_url=html_url,
        created_at=created_at,
        jobs=jobs,
    )


# --- Marker + signature hashing ---


def signature_hash(signature: RunSignature) -> str:
    """Deterministic short fingerprint of a run signature.

    Used only for the marker's :sig= suffix (not for dedup decisions --
    that's the LLM's job, guided by the candidate pool).
    """
    parts: list[str] = []
    for job in signature.jobs:
        parts.extend(failure.test for failure in job.pytest_failures)
        parts.extend(job.go_failures)
        if job.traceback_top_error:
            parts.append(job.traceback_top_error)
        if job.failed_step:
            parts.append(job.failed_step)
    canonical = '\n'.join(sorted(parts)) or signature.workflow_name
    return hashlib.sha1(canonical.encode('utf-8'), usedforsecurity=False).hexdigest()[:16]


# Which artefact the notifier touched: a fresh placeholder issue, or a comment
# on an issue that already existed. A Literal so a type checker rejects a bad
# value before it reaches a marker.
Origin = Literal['new', 'comment']


def render_notifier_marker(run_id: str, origin: Origin) -> str:
    """Render the marker the notifier stamps, telling the enricher what it touched."""
    return f'<!-- {MARKER_PREFIX}:run={run_id}:origin={origin} -->'


def render_enriched_marker(run_id: str, signature: RunSignature) -> str:
    """Render the marker this script stamps once it has fully processed a run.

    Presence of :sig= is what makes rung zero (find_run_markers) treat a later
    same-run-id trigger as "already enriched, just note the re-run".
    """
    return f'<!-- {MARKER_PREFIX}:run={run_id}:sig={signature_hash(signature)} -->'


def find_run_markers(
    texts: list[tuple[int, str]], run_id: str
) -> tuple[int | None, str | None, int | None]:
    """Scan (issue_number, text) pairs for markers belonging to `run_id`.

    Returns (enriched_issue, origin_kind, origin_issue):
    - enriched_issue: an issue number carrying a :sig= marker for this run
      (rung zero -- this run was already fully enriched once), else None.
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
        for match in MARKER_RE.finditer(text):
            if match['run_id'] != run_id:
                continue
            if match['sig']:
                enriched_issue = number
            elif match['origin']:
                origin_kind = match['origin']
                origin_issue = number
    return enriched_issue, origin_kind, origin_issue


# --- Candidate pool ---


def within_window(iso_timestamp: str, now: datetime.datetime, days: int) -> bool:
    """Return whether `iso_timestamp` falls within `days` of `now`."""
    ts = datetime.datetime.fromisoformat(iso_timestamp.replace('Z', '+00:00'))
    return now - ts <= datetime.timedelta(days=days)


def build_candidates_block(
    open_issues: list[CandidateIssue],
    closed_issues: list[CandidateIssue],
    now: datetime.datetime,
) -> str:
    """Render the {{CANDIDATES_BLOCK}} the prompt expects.

    Up to MAX_CANDIDATES entries: open issues first, then recently-closed
    issues (<=14 days) filling any remaining slots, explicitly labelled as
    closed so the LLM never auto-treats one as a strong match. Calibration on
    past scheduled failures found a closed issue can corroborate a match but
    should never be enough to dedupe against on its own.
    """
    entries: list[str] = []
    for issue in open_issues:
        if len(entries) >= MAX_CANDIDATES:
            break
        entries.append(f'- **#{issue.number} — {issue.title}** (open)\n  > {issue.excerpt()}')

    recent_closed = [
        i
        for i in closed_issues
        if i.closed_at and within_window(i.closed_at, now, CLOSED_CANDIDATE_WINDOW_DAYS)
    ]
    for issue in recent_closed:
        if len(entries) >= MAX_CANDIDATES:
            break
        entries.append(
            f'- **#{issue.number} — {issue.title}** (closed {issue.closed_at} -- '
            f'recently closed; treat as at most a medium-confidence match)\n  > {issue.excerpt()}'
        )

    if not entries:
        return '(no open issues found for this workflow)'
    return '\n'.join(entries)


# --- Prompt building ---

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

You are reporting, not fixing. Never propose a fix, a patch, a diff, a
workaround, a configuration change, a retry, a next step, or anything else
that tells a reader what to do about the failure -- not as a section, not
as a sentence, not as an aside, however confident you are and however
obvious it looks. Deciding what to do about a failure is someone else's
job, and a wrong suggestion from you is worse than none, because it
anchors whoever picks the issue up. Describe what failed and, where the
signature genuinely supports it, why. Then stop.

## Reading the signature

The signature has one entry per failed job in `jobs[]`. Each entry may
carry, in decreasing order of how much you should trust it:

1. `pytest_failures[]` -- `{kind, test, error}` triples parsed from
   pytest's "short test summary info" block. `test` is a real pytest node
   id; `error` is the tail of that summary line and CAN BE TRUNCATED by
   pytest itself (it cuts long messages short, for example
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
   (for example a Go `panic:`, a shell command's final non-zero-exit message, an
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
signatures you'll see. Describe the cause only; do not carry on into what
should be done about it.>
```

Do not add sections beyond these. In particular there is no "suggested
fix", "next steps", "workaround" or "recommendation" section, and none may
be added.

For `action: "comment"`, keep the comment short: what matches the existing
issue (or what's new/different), and nothing else.

## Deciding comment vs new

You are given up to three candidate existing issues (title + excerpt), already
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

The repository has a fixed, centrally-managed label set. You may only use
labels from this list, and a label that does not exist in the repository is
dropped before the issue is created, so inventing one achieves nothing:

- `tests` -- the failure is in the tests or the test harness. This is the
  common case for a failing integration or unit workflow.
- `docs` -- the failure is in documentation building, linting or link
  checking, or in a workflow that maintains a doc.
- `performance` -- only where the failure *is* a performance result, such
  as a benchmark regression or a timing threshold. Not for an ordinary
  timeout, which is usually a hang or an infrastructure problem.
- `small item` -- only where the signature makes it obvious the work is
  trivial. Prefer omitting it: you cannot see the code, so you are usually
  not in a position to judge size.

An empty `labels` list is a perfectly good answer. Use it whenever none of
the above clearly applies, rather than reaching for the nearest one.

`issue_type` is "bug" when you're reasonably sure this is a defect. Use
`null` when genuinely unsure -- this is normal and expected for
low-confidence signatures, not an edge case.

## Never

- Never suggest a fix or a remedy of any kind. See "You are reporting, not
  fixing" above; this is the constraint most easily broken by accident,
  usually as a closing sentence offering a next step.
- Never invent a root cause, a PR number, or a file/line that isn't
  directly supported by the signature JSON you were given.
- Never use a label that isn't in the list above.
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
    workflow_name: str, run_url: str, signature: RunSignature, candidates_block: str
) -> tuple[str, str]:
    """Render the (system, user) prompt pair for the OpenRouter call."""
    user = USER_PROMPT_TEMPLATE.format(
        workflow_name=workflow_name,
        run_url=run_url,
        signature_json=signature.as_json(),
        candidates_block=candidates_block,
    )
    return SYSTEM_PROMPT, user


# --- Envelope schema validation (hand-rolled -- deliberately not the
# `jsonschema` package, so the script keeps needing nothing outside the stdlib.
# Mirrors ENVELOPE_JSON_SCHEMA below, which is what OpenRouter is asked to
# conform to; this re-checks it on the applier side.) ---

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


def validate_entry(entry: Any, *, path: str, allow_also: bool = False) -> list[str]:
    """Validate one envelope entry (top-level or an `also[i]`) against the schema.

    `also` is only legal on the top-level envelope, so the caller says whether
    this is that. Without it the top-level check rejected every envelope that
    carried `also` -- which the model emits routinely, since the schema it is
    given declares the field.
    """
    errors: list[str] = []
    if not isinstance(entry, dict):
        return [f'{path}: expected an object, got {type(entry).__name__}']

    for field in _ENTRY_COMMON_REQUIRED:
        if field not in entry:
            errors.append(f"{path}: missing required field '{field}'")

    known = _ENTRY_KNOWN_KEYS | {'also'} if allow_also else _ENTRY_KNOWN_KEYS
    unknown = set(entry) - known
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

    # A field present but null counts as absent. The schema sent to OpenRouter
    # is `strict`, so models routinely return every declared property and use
    # null for the ones that do not apply to the action they chose; rejecting on
    # mere presence threw away otherwise good output.
    if action == 'new':
        for field in ('title', 'labels', 'issue_type'):
            if field not in entry:
                errors.append(f"{path}: action='new' requires '{field}'")
        if entry.get('target_issue') is not None:
            errors.append(f"{path}: action='new' must not include 'target_issue'")
        labels = entry.get('labels')
        if labels is not None and (
            not isinstance(labels, list) or not all(isinstance(x, str) for x in labels)
        ):
            errors.append(f'{path}.labels: must be an array of strings')
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
            if entry.get(field) is not None:
                errors.append(f"{path}: action='comment' must not include '{field}'")

    return errors


# Fields that only mean something for one of the two actions. The model is
# given a `strict` schema, so it tends to return every declared property and
# fill in the ones that do not apply to the action it chose. Those are dropped
# rather than treated as an error: we would not act on them either way, and
# rejecting the envelope threw away a usable body and fell back to the plain
# notice.
_ACTION_ONLY_FIELDS = {
    'comment': ('title', 'labels', 'issue_type'),
    'new': ('target_issue',),
}


def drop_inapplicable_fields(entry: Any) -> tuple[Any, list[str]]:
    """Strip fields that do not apply to `entry`'s action; report what went."""
    if not isinstance(entry, dict):
        return entry, []
    fields = _ACTION_ONLY_FIELDS.get(entry.get('action'))
    if not fields:
        return entry, []
    dropped = [f for f in fields if f in entry]
    if not dropped:
        return entry, []
    return {k: v for k, v in entry.items() if k not in dropped}, dropped


def normalise_envelope(envelope: Any) -> tuple[Any, list[str]]:
    """Drop inapplicable fields from the envelope and each `also` entry."""
    if not isinstance(envelope, dict):
        return envelope, []
    cleaned, dropped = drop_inapplicable_fields(envelope)
    notes = [f'envelope: {f}' for f in dropped]
    also = cleaned.get('also')
    if isinstance(also, list):
        entries: list[Any] = []
        for i, entry in enumerate(also):
            entry, entry_dropped = drop_inapplicable_fields(entry)
            notes += [f'envelope.also[{i}]: {f}' for f in entry_dropped]
            entries.append(entry)
        cleaned = {**cleaned, 'also': entries}
    return cleaned, notes


def validate_envelope(envelope: Any) -> list[str]:
    """Validate a top-level envelope (may carry `also`).

    Returns a list of human-readable errors; empty list means valid.
    """
    if not isinstance(envelope, dict):
        return ['envelope: expected a JSON object']

    errors = validate_entry(envelope, path='envelope', allow_also=True)

    also = envelope.get('also')
    if also is not None:
        if not isinstance(also, list) or len(also) > 2:
            errors.append('envelope.also: must be an array of at most two entries')
        else:
            for i, entry in enumerate(also):
                if isinstance(entry, dict) and 'also' in entry:
                    errors.append(f"envelope.also[{i}]: nested 'also' is not allowed")
                errors.extend(validate_entry(entry, path=f'envelope.also[{i}]'))

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
                        'properties': {'labels': {'type': 'array', 'items': {'type': 'string'}}},
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
    # S607: `gh` is deliberately called by name, resolved from the runner's PATH.
    return subprocess.run(['gh', *args], text=True, capture_output=True, check=check)  # noqa: S607


def gh_json(*args: str) -> Any:
    """Run a `gh ... --json ...` subcommand and parse its stdout as JSON."""
    result = gh(*args)
    return json.loads(result.stdout) if result.stdout.strip() else None


def fetch_failed_jobs(repo: str, run_id: str) -> list[FailedJob]:
    """List the failed jobs of a run, each with its id, name, and failed step."""
    data = gh_json('run', 'view', str(run_id), '--repo', repo, '--json', 'jobs') or {}
    failed: list[FailedJob] = []
    for job in data.get('jobs', []):
        if job.get('conclusion') != 'failure':
            continue
        failed_step = None
        for step in job.get('steps') or []:
            if step.get('conclusion') == 'failure':
                failed_step = step.get('name')
                break
        failed.append(FailedJob(id=job['databaseId'], name=job['name'], failed_step=failed_step))
    return failed


def fetch_job_log(repo: str, run_id: str, job_id: int) -> str:
    """Fetch one job's full log text.

    Uses the REST logs endpoint rather than `gh run view --log`: the latter
    exits 0 with empty stdout on some `gh` builds (reproduced on 2.45.0), which
    silently degrades the extracted signature to nothing. An empty log here is
    reported rather than swallowed.

    `--allow-escape-sequences` is not optional. From gh 2.9x, `gh api` refuses
    to write a response containing terminal escapes -- "the response contains
    terminal escape sequences; pass --allow-escape-sequences to output it
    anyway" -- and returns nothing at all. Actions logs are full of them; ANSI
    above exists to strip them. Runners carry a gh new enough to refuse (2.97.0
    when this was measured, in fork run 32673538357), so without the flag every
    fetch comes back empty and the signature degrades to the job name.

    Older builds have no such check and no such flag, and reject it as unknown
    rather than ignoring it, so those retry without.
    """
    endpoint = f'repos/{repo}/actions/jobs/{job_id}/logs'
    result = gh('api', endpoint, '--allow-escape-sequences', check=False)
    if 'unknown flag' in (result.stderr or ''):
        result = gh('api', endpoint, check=False)
    if not result.stdout.strip():
        # `gh` puts the status on stderr ("gh: Not Found (HTTP 404)"), and the
        # exit code alone is 1 for all of them. Without the status there is no
        # telling a log that is not ready yet from a token that has lost
        # `actions: read`, and the two want opposite fixes.
        detail = ' '.join((result.stderr or '').split())[:200] or 'no stderr'
        write_step_summary(
            f'Warning: no log text for job {job_id} of run {run_id} '
            f'(gh exit {result.returncode}: {detail}); '
            f'signature will be based on the job name alone.'
        )
    return result.stdout


def fetch_run_meta(repo: str, run_id: str) -> dict[str, str]:
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
    # The repo must be passed as `--repo`, not folded into the positional query.
    # `gh search issues` quotes each positional argument as a single search
    # keyword, so `repo:owner/name "text"` becomes the literal keyword
    # `repo:"owner/name \"text\""` and GitHub rejects it as an invalid query.
    data = (
        gh_json(
            'search', 'issues', '--repo', repo, '--limit', '10', '--json', 'number', query_text
        )
        or []
    )
    return [item['number'] for item in data]


def fetch_issue_texts(repo: str, number: int) -> list[str]:
    """Fetch an issue's body plus all comment bodies, for marker scanning."""
    data = gh_json('issue', 'view', str(number), '--repo', repo, '--json', 'body,comments') or {}
    texts = [data.get('body') or '']
    for c in data.get('comments') or []:
        texts.append(c.get('body') or '')
    return texts


def recent_issue_texts(repo: str, limit: int = RECENT_ISSUE_SCAN) -> list[tuple[int, str]]:
    """Return (number, text) pairs for the `limit` most recently updated issues.

    Bodies and comment bodies both, since a notifier marker with
    `origin=comment` lives in a comment rather than the body.
    """
    data = (
        gh_json(
            'issue',
            'list',
            '--repo',
            repo,
            '--state',
            'all',
            '--limit',
            str(limit),
            '--json',
            'number,body,comments',
        )
        or []
    )
    texts: list[tuple[int, str]] = []
    for issue in data:
        number = issue['number']
        texts.append((number, issue.get('body') or ''))
        for comment in issue.get('comments') or []:
            texts.append((number, comment.get('body') or ''))
    return texts


def locate_run_markers(repo: str, run_id: str) -> tuple[int | None, str | None, int | None]:
    """Find the markers belonging to `run_id` and classify them.

    Scans the most recently updated issues first, and only falls back to
    `gh search issues` if that finds nothing.

    The ordering matters, and is the whole point of doing it this way. The
    notifier stamps its marker moments before this workflow runs, and GitHub's
    issue *search* index is not read-your-writes -- a marker that has not been
    indexed yet reads as "no notifier marker found", and main() responds by
    opening a *second* issue for a run that already has one. The issue *list*
    endpoint has no such lag, and the artefact the notifier just touched is by
    construction among the most recently updated issues in the repo.

    Search remains as a fallback for the one case the list cannot cover: a repo
    busy enough that more than `RECENT_ISSUE_SCAN` issues were updated in
    between, where a stale index still beats no lookup at all.
    """
    markers = find_run_markers(recent_issue_texts(repo), run_id)
    if markers != (None, None, None):
        return markers

    hits = search_issue_numbers(repo, f'{MARKER_PREFIX}:run={run_id}')
    texts: list[tuple[int, str]] = []
    for number in hits:
        for text in fetch_issue_texts(repo, number):
            texts.append((number, text))
    return find_run_markers(texts, run_id)


def search_candidates(
    repo: str, workflow_name: str
) -> tuple[list[CandidateIssue], list[CandidateIssue]]:
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
    return (
        [CandidateIssue.from_gh(i) for i in open_issues],
        [CandidateIssue.from_gh(i) for i in closed_issues],
    )


def existing_labels(repo: str) -> set[str]:
    """Return the set of label names that already exist in `repo`."""
    data = gh_json('label', 'list', '--repo', repo, '--json', 'name', '--limit', '100') or []
    return {item['name'] for item in data}


def filter_labels(labels: list[str], available: set[str]) -> list[str]:
    """Drop labels that don't already exist in the repo (never auto-create)."""
    return [label for label in labels if label in available]


def call_openrouter(
    system_prompt: str, user_prompt: str, model: str, api_key: str
) -> dict[str, Any]:
    """POST the prompt to OpenRouter with the envelope schema, return the parsed JSON.

    Uses urllib rather than requests so the script has no third-party
    dependencies at all. urlopen raises HTTPError (a subclass of OSError) on a
    non-2xx response, which main() treats the same as any other OpenRouter
    failure: fall back to the plain body.
    """
    payload = {
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
    }
    request = urllib.request.Request(
        'https://openrouter.ai/api/v1/chat/completions',
        data=json.dumps(payload).encode(),
        headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
        method='POST',
    )
    # S310: the URL is a literal https endpoint, not caller-controlled.
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        body = json.loads(response.read().decode())
    content = body['choices'][0]['message']['content']
    return json.loads(content)


def write_step_summary(message: str) -> None:
    """Report a line to the job's step summary and to the log.

    Always goes to stderr as well as the summary: every fallback path in this
    script reports through here, and a fallback that only shows up in the
    summary is invisible to anyone reading the job log or the API.
    """
    print(message, file=sys.stderr)
    path = os.environ.get('GITHUB_STEP_SUMMARY')
    if path:
        with open(path, 'a', encoding='utf-8') as f:
            f.write(message + '\n')


def plain_fallback_body(workflow_name: str, run_url: str) -> str:
    """The plain, generic body text used whenever enrichment is unavailable."""
    return f"Scheduled workflow '{workflow_name}' failed: {run_url}"


def render_body(body: str, workflow_name: str, marker: str) -> str:
    """Assemble an issue or comment body, footer and marker included.

    The `Workflow: <name>` footer is what keeps the notifier's coarse search
    working after enrichment has rewritten the title and body: the search
    matches on the workflow name, and without the footer it would depend on
    the model happening to leave the name in the title.
    """
    return f'{body.rstrip()}\n\nWorkflow: {workflow_name}\n\n{marker}'


def apply_entry(
    repo: str,
    entry: dict[str, Any],
    marker: str,
    workflow_name: str,
    *,
    default_target: int | None = None,
) -> str:
    """Create or comment on an issue per one envelope entry, stamping `marker`."""
    body = render_body(entry['body'], workflow_name, marker)
    if entry['action'] == 'new':
        # The repo's label set is centrally managed, so anything the model
        # asked for that doesn't exist is dropped rather than created.
        labels = filter_labels(entry.get('labels') or [], existing_labels(repo))
        dropped = set(entry.get('labels') or []) - set(labels)
        if dropped:
            write_step_summary(
                f'Dropped labels that do not exist in this repo: {", ".join(sorted(dropped))}.'
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

    try:
        enriched_issue, origin_kind, origin_issue = locate_run_markers(repo, run_id)
    except Exception as exc:  # search API rejection, rate limit, transient 5xx.
        # The marker lookup is the first thing main() does, so an uncaught
        # failure here takes out the whole enrich job and hands every run to
        # the workflow-level plain-fallback -- losing enrichment silently
        # rather than degrading through the script's own fallback path.
        write_step_summary(f'Marker lookup failed ({exc}); treating this run as un-marked.')
        enriched_issue, origin_kind, origin_issue = None, None, None

    if enriched_issue is not None:
        # Rung zero: this run id was already fully enriched once -- a re-run of
        # the same failing jobs re-triggered us. Comment, don't skip and don't
        # redo the full LLM pass. On a corpus of past scheduled failures this
        # rung accounted for half the real duplicate pairs, making it the
        # highest-value one.
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
            f'Rung zero: run {run_id} already enriched on #{enriched_issue}; '
            'commented re-run note.'
        )
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
        build_job_signature(job.id, job.name, job.failed_step, fetch_job_log(repo, run_id, job.id))
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
                'labels': [],
                'issue_type': None,
            }
            if origin_kind != 'comment'
            else {
                'action': 'comment',
                'body': plain_fallback_body(workflow_name, run_url),
                'target_issue': origin_issue,
            },
            enriched_marker,
            workflow_name,
            default_target=origin_issue,
        )
        return 0

    try:
        open_candidates, closed_candidates = search_candidates(repo, workflow_name)
    except Exception as exc:  # as above: degrade to "no candidates", don't crash.
        write_step_summary(f'Candidate search failed ({exc}); proceeding with no candidates.')
        open_candidates, closed_candidates = [], []
    if origin_kind == 'new':
        # The placeholder this run just created is not a candidate to dedupe
        # against. An issue the notifier *commented* on is a different matter:
        # it already existed, the coarse search matched it, and it is the most
        # likely duplicate -- dropping it left the model blind to the very
        # issue it should have been comparing against, so it answered "new"
        # and produced the duplicate this whole path exists to avoid.
        open_candidates = [c for c in open_candidates if c.number != origin_issue]
    candidates_block = build_candidates_block(
        open_candidates, closed_candidates, datetime.datetime.now(datetime.timezone.utc)
    )
    system_prompt, user_prompt = build_prompt(workflow_name, run_url, signature, candidates_block)

    try:
        envelope = call_openrouter(system_prompt, user_prompt, model, api_key)
    except Exception as exc:  # network error, non-2xx, bad JSON, and so on.
        write_step_summary(f'OpenRouter call failed ({exc}); using the plain fallback body.')
        apply_entry(
            repo,
            {
                'action': 'new',
                'body': plain_fallback_body(workflow_name, run_url),
                'title': f"Scheduled workflow '{workflow_name}' failed",
                'labels': [],
                'issue_type': None,
            }
            if origin_kind != 'comment'
            else {
                'action': 'comment',
                'body': plain_fallback_body(workflow_name, run_url),
                'target_issue': origin_issue,
            },
            enriched_marker,
            workflow_name,
            default_target=origin_issue,
        )
        return 0

    envelope, dropped_fields = normalise_envelope(envelope)
    if dropped_fields:
        write_step_summary(
            'Ignored fields that do not apply to the chosen action: '
            + ', '.join(dropped_fields)
            + '.'
        )

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
                'labels': [],
                'issue_type': None,
            }
            if origin_kind != 'comment'
            else {
                'action': 'comment',
                'body': plain_fallback_body(workflow_name, run_url),
                'target_issue': origin_issue,
            },
            enriched_marker,
            workflow_name,
            default_target=origin_issue,
        )
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
            render_body(envelope['body'], workflow_name, enriched_marker),
        ]
        for label in labels:
            edit_args += ['--add-label', label]
        gh(*edit_args)
    elif envelope['action'] == 'comment' and envelope.get('target_issue') == origin_issue:
        apply_entry(repo, envelope, enriched_marker, workflow_name, default_target=origin_issue)
    elif envelope['action'] == 'comment':
        # LLM picked a different candidate than the notifier's coarse match.
        apply_entry(repo, envelope, enriched_marker, workflow_name)
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
        apply_entry(repo, envelope, enriched_marker, workflow_name)
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
        apply_entry(repo, also_entry, enriched_marker, workflow_name)

    return 0


if __name__ == '__main__':
    sys.exit(main())
