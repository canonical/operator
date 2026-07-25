#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
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

"""Unit tests for .github/ai_failure_notifier.py.

Lives here, rather than beside the script, so `tox -e unit` collects it --
pytest skips dot-directories, so anything under .github/ never runs in CI.

No network calls and no `gh` calls happen in this file -- OpenRouter and gh
I/O are mocked. FIXTURE below is the extracted signature, candidate issue and
LLM envelope from a real failing scheduled run (28141163589, "Broad Charm
Compatibility Tests", 2026-06-25); the `tail_excerpt` arrays are trimmed for
size; `pytest_failures` and `traceback_top_error` are verbatim, since those are
what the dedup and schema logic actually exercise.
"""

from __future__ import annotations

import contextlib
import datetime
import email.message
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
from typing import Any
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / '.github'))

import ai_failure_notifier as afn

# The signature, candidate issue and envelope from a real failing scheduled run
# (28141163589, "Broad Charm Compatibility Tests", 2026-06-25). The tail_excerpt
# lists are trimmed for size; pytest_failures and traceback_top_error are
# verbatim, since those are what the dedup and schema logic exercise.
FIXTURE_SIGNATURE = afn.RunSignature(
    run_id='28141163589',
    workflow_name='Broad Charm Compatibility Tests',
    html_url='https://github.com/canonical/operator/actions/runs/28141163589',
    created_at='2026-06-25T01:40:15Z',
    jobs=[
        afn.JobSignature(
            job_id=83338922280,
            job_name='charm-tests (canonical/charm-ubuntu, .)',
            failed_step="Run the charm's unit tests",
            pytest_failures=[
                afn.PytestFailure(
                    kind='ERROR',
                    test='tests/unit/test_charm.py::TestCharm::test_charm_ready',
                    error='PendingDeprecat...',
                ),
                afn.PytestFailure(
                    kind='ERROR',
                    test='tests/unit/test_charm.py::TestCharm::test_hostname',
                    error='PendingDeprecation...',
                ),
                afn.PytestFailure(
                    kind='ERROR',
                    test='tests/unit/test_charm.py::TestCharm::test_version',
                    error='PendingDeprecationW...',
                ),
            ],
            go_failures=[],
            traceback_top_error=(
                'ResourceWarning: Implicitly cleaning up <TemporaryDirectory '
                "'/tmp/ops-harness-ruod78qd'>"
            ),
            tail_excerpt=[
                'pytest.PytestUnraisableExceptionWarning: Exception ignored in: <finalize object '
                'at 0x7f2f582dea60; dead>',
                'unit: FAIL code 1 (2.04=setup[1.23]+cmd[0.81] seconds)',
                'evaluation failed :( (2.07 seconds)',
            ],
        ),
        afn.JobSignature(
            job_id=83338922315,
            job_name='charm-tests (canonical/k8s-operator, charms/worker/k8s)',
            failed_step="Run the charm's static tests",
            pytest_failures=[],
            go_failures=[],
            traceback_top_error=None,
            tail_excerpt=[
                'Total issues (by severity):',
                'static: FAIL code 1 (16.01=setup[0.42]+cmd[15.59] seconds)',
                'evaluation failed :( (16.06 seconds)',
            ],
        ),
        afn.JobSignature(
            job_id=83338923301,
            job_name='charm-tests (canonical/seldon-core-operator, .)',
            failed_step="Run the charm's unit tests",
            pytest_failures=[
                afn.PytestFailure(
                    kind='FAILED',
                    test='tests/unit/test_operator.py::TestCharm::test_prometheus_data_set',
                    error=(
                        "AttributeError: module 'ops.testing' has no attribute "
                        "'_TestingModelBackend'"
                    ),
                ),
            ],
            go_failures=[],
            traceback_top_error=(
                "AttributeError: module 'ops.testing' has no attribute '_TestingModelBackend'"
            ),
            tail_excerpt=[
                'FAILED tests/unit/test_operator.py::TestCharm::test_prometheus_data_set - '
                "AttributeError: module 'ops.testing' has no attribute '_TestingModelBackend'",
                'unit: FAIL code 1 (8.95=setup[0.60]+cmd[8.35] seconds)',
            ],
        ),
        afn.JobSignature(
            job_id=83338923304,
            job_name='charm-tests (canonical/self-signed-certificates-operator, .)',
            failed_step="Run the charm's unit tests",
            pytest_failures=[],
            go_failures=[],
            traceback_top_error=None,
            tail_excerpt=[
                'ERROR tests/unit/test_charm_collect_status.py',
                '!!!!!!!!!!!!!!!!!!! Interrupted: 5 errors during collection !!!!!!!!!!!!!!!!!!!!',
                'unit: FAIL code 2 (3.43=setup[1.18]+cmd[0.06,0.02,2.16] seconds)',
            ],
        ),
        afn.JobSignature(
            job_id=83338923318,
            job_name='charm-tests (canonical/traefik-k8s-operator, .)',
            failed_step="Run the charm's unit tests",
            pytest_failures=[],
            go_failures=[],
            traceback_top_error=(
                "ImportError: cannot import name 'Event' from 'scenario' (/home/runner/work/operat"
                'or/operator/charm-repo/.tox/unit/lib/python3.12/site-packages/scenario/__init__.p'
                'y)'
            ),
            tail_excerpt=[
                (
                    "ImportError: cannot import name 'Event' from 'scenario' "
                    '(/home/runner/work/operator/operator/charm-repo/.tox/unit/lib/python3.12/site'
                    '-packages/scenario/__init__.py)'
                ),
                'unit: FAIL code 1 (6.43=setup[2.14]+cmd[0.06,0.02,4.21] seconds)',
            ],
        ),
    ],
)

FIXTURE_CANDIDATES = [
    afn.CandidateIssue(
        number=9010,
        title='Broad Charm Compatibility Tests: 4 downstream charms failing, independent causes',
        body=(
            'canonical/k8s-operator: bandit exit 1 (Medium: 24, High: 591). '
            "canonical/seldon-core-operator: AttributeError: module 'ops.testing' has no attribute"
            " '_TestingModelBackend'. canonical/self-signed-certificates-operator: 5 collection "
            "errors. canonical/traefik-k8s-operator: ImportError: cannot import name 'Event' from "
            "'scenario'."
        ),
        closed_at=None,
    ),
]

FIXTURE_ENVELOPE: dict[str, Any] = {
    'action': 'comment',
    'target_issue': 9010,
    'body': 'Another occurrence: '
    'https://github.com/canonical/operator/actions/runs/28141163589\n'
    '\n'
    '4 of the 5 failing charms match #9010 unchanged. New this run: '
    'canonical/charm-ubuntu is now also failing its unit tests.',
    'dedup_reason': "4 of 5 failing charms match #9010's signature; charm-ubuntu is a "
    'new failure not present in #9010',
    'confidence': 'medium',
}


class SignatureExtractionTests(unittest.TestCase):
    def test_strip_line_removes_timestamp_and_ansi(self):
        raw = '2026-06-25T01:40:15.8141713Z \x1b[36mhello\x1b[0m'
        self.assertEqual(
            afn.strip_line(raw),
            '\x1b[36mhello\x1b[0m'.replace('\x1b[36m', '').replace('\x1b[0m', ''),
        )

    def test_parse_job_log_pytest_failures_and_summary_bound(self):
        ts = '2026-06-25T01:40:15.0000000Z '
        log = '\n'.join(
            [
                f'{ts}============ short test summary info ============',
                f'{ts}FAILED tests/unit/test_x.py::test_a - AssertionError: x',
                f'{ts}ERROR tests/unit/test_x.py::test_b - PendingDeprecat...',
                f'{ts}============ 2 failed in 1.23s ============',
                f'{ts}some trailing noise, not part of the summary',
            ]
        )
        pytest_failures, go_failures, _tb, _tail = afn.parse_job_log(log)
        self.assertEqual(
            pytest_failures,
            [
                afn.PytestFailure('FAILED', 'tests/unit/test_x.py::test_a', 'AssertionError: x'),
                afn.PytestFailure('ERROR', 'tests/unit/test_x.py::test_b', 'PendingDeprecat...'),
            ],
        )
        self.assertEqual(go_failures, [])

    def test_parse_job_log_go_failures(self):
        log = '--- FAIL: TestFoo (0.03s)\n--- FAIL: TestBar (0.01s)\n'
        _pytest_failures, go_failures, _tb, _tail = afn.parse_job_log(log)
        self.assertEqual(go_failures, ['TestFoo', 'TestBar'])

    def test_parse_job_log_traceback_top_error_prefers_last_match(self):
        log = '\n'.join(
            [
                'ValueError: first, ignored',
                'some other output',
                'AttributeError: the real one',
            ]
        )
        _, _, tb, _ = afn.parse_job_log(log)
        self.assertEqual(tb, 'AttributeError: the real one')

    def test_parse_job_log_tail_excerpt_stops_before_first_error_marker(self):
        log = '\n'.join(
            [
                'line before 1',
                'line before 2',
                '##[error]something broke',
                'line after (should not appear in tail)',
            ]
        )
        _, _, _, tail = afn.parse_job_log(log)
        self.assertEqual(tail, ['line before 1', 'line before 2'])

    def test_build_run_signature_matches_fixture_shape(self):
        jobs = [
            afn.build_job_signature(j.job_id, j.job_name, j.failed_step, '')
            for j in FIXTURE_SIGNATURE.jobs
        ]
        sig = afn.build_run_signature(
            '28141163589', 'Broad Charm Compatibility Tests', 'url', '2026-06-25T01:40:15Z', jobs
        )
        self.assertEqual(sig.run_id, '28141163589')
        self.assertEqual(len(sig.jobs), 5)
        # as_json is what reaches the prompt; field order is declaration order.
        self.assertEqual(
            list(json.loads(sig.as_json())),
            ['run_id', 'workflow_name', 'html_url', 'created_at', 'jobs'],
        )


class MarkerTests(unittest.TestCase):
    def test_render_and_parse_notifier_marker(self):
        marker = afn.render_notifier_marker('123', 'new')
        enriched, origin_kind, origin_issue = afn.find_run_markers([(42, marker)], '123')
        self.assertIsNone(enriched)
        self.assertEqual(origin_kind, 'new')
        self.assertEqual(origin_issue, 42)

    def test_render_and_parse_enriched_marker_is_rung_zero(self):
        marker = afn.render_enriched_marker('28141163589', FIXTURE_SIGNATURE)
        run_id = '28141163589'
        enriched, origin_kind, _origin_issue = afn.find_run_markers([(9010, marker)], run_id)
        self.assertEqual(enriched, 9010)
        self.assertIsNone(origin_kind)

    def test_marker_for_different_run_id_does_not_match(self):
        marker = afn.render_notifier_marker('999', 'comment')
        enriched, origin_kind, origin_issue = afn.find_run_markers([(1, marker)], '123')
        self.assertIsNone(enriched)
        self.assertIsNone(origin_kind)
        self.assertIsNone(origin_issue)

    def test_signature_hash_is_deterministic_and_order_independent_of_call(self):
        h1 = afn.signature_hash(FIXTURE_SIGNATURE)
        h2 = afn.signature_hash(FIXTURE_SIGNATURE)  # independently constructed
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_no_marker_present_returns_all_none(self):
        enriched, origin_kind, origin_issue = afn.find_run_markers(
            [(1, 'just a normal comment, no marker')], '123'
        )
        self.assertIsNone(enriched)
        self.assertIsNone(origin_kind)
        self.assertIsNone(origin_issue)


class CandidateBlockTests(unittest.TestCase):
    def test_open_candidate_rendered(self):
        block = afn.build_candidates_block(
            FIXTURE_CANDIDATES, [], datetime.datetime.now(datetime.timezone.utc)
        )
        self.assertIn('#9010', block)
        self.assertIn('Broad Charm Compatibility Tests', block)
        self.assertNotIn('closed', block)

    def test_empty_candidates_block(self):
        block = afn.build_candidates_block([], [], datetime.datetime.now(datetime.timezone.utc))
        self.assertEqual(block, '(no open issues found for this workflow)')

    def test_recently_closed_candidate_is_labelled_and_capped_at_medium(self):
        now = datetime.datetime(2026, 6, 25, tzinfo=datetime.timezone.utc)
        closed = [
            afn.CandidateIssue.from_gh(
                {
                    'number': 42,
                    'title': 'old thing',
                    'body': 'x',
                    'closedAt': '2026-06-20T00:00:00Z',
                }
            )
        ]
        block = afn.build_candidates_block([], closed, now)
        self.assertIn('#42', block)
        self.assertIn('closed', block)
        self.assertIn('medium-confidence', block)

    def test_closed_candidate_outside_window_is_dropped(self):
        now = datetime.datetime(2026, 6, 25, tzinfo=datetime.timezone.utc)
        closed = [
            afn.CandidateIssue.from_gh(
                {
                    'number': 42,
                    'title': 'ancient',
                    'body': 'x',
                    'closedAt': '2026-01-01T00:00:00Z',
                }
            )
        ]
        block = afn.build_candidates_block([], closed, now)
        self.assertEqual(block, '(no open issues found for this workflow)')

    def test_candidates_capped_at_three(self):
        opens = [
            afn.CandidateIssue.from_gh(
                {
                    'number': n,
                    'title': f'issue {n}',
                    'body': 'x',
                    'closedAt': None,
                }
            )
            for n in range(5)
        ]
        block = afn.build_candidates_block(opens, [], datetime.datetime.now(datetime.timezone.utc))
        self.assertEqual(block.count('- **#'), 3)


class SchemaValidationTests(unittest.TestCase):
    def test_valid_comment_envelope_from_fixture(self):
        errors = afn.validate_envelope(FIXTURE_ENVELOPE)
        self.assertEqual(errors, [])

    def test_valid_new_envelope(self):
        envelope: dict[str, Any] = {
            'action': 'new',
            'title': 'Something failed',
            'body': 'details',
            'labels': ['tests'],
            'issue_type': None,
            'dedup_reason': 'no match',
            'confidence': 'low',
        }
        self.assertEqual(afn.validate_envelope(envelope), [])

    def test_new_envelope_with_no_labels_is_valid(self):
        # No label is mandatory: the repo's label set is centrally managed, and
        # an empty list is the right answer when none of it applies.
        envelope: dict[str, Any] = {
            'action': 'new',
            'title': 'Something failed',
            'body': 'details',
            'labels': [],
            'issue_type': None,
            'dedup_reason': 'no match',
            'confidence': 'low',
        }
        self.assertEqual(afn.validate_envelope(envelope), [])

    def test_new_envelope_with_non_string_labels_is_invalid(self):
        envelope: dict[str, Any] = {
            'action': 'new',
            'title': 'Something failed',
            'body': 'details',
            'labels': ['tests', 7],
            'issue_type': None,
            'dedup_reason': 'no match',
            'confidence': 'low',
        }
        self.assertTrue(any('labels' in e for e in afn.validate_envelope(envelope)))

    def test_new_envelope_with_target_issue_is_invalid(self):
        envelope = {
            'action': 'new',
            'title': 't',
            'body': 'b',
            'labels': ['tests'],
            'issue_type': None,
            'dedup_reason': 'd',
            'confidence': 'low',
            'target_issue': 5,
        }
        errors = afn.validate_envelope(envelope)
        self.assertTrue(any('target_issue' in e for e in errors))

    def test_comment_envelope_with_title_is_invalid(self):
        envelope = {
            'action': 'comment',
            'target_issue': 5,
            'title': 'should not be here',
            'body': 'b',
            'dedup_reason': 'd',
            'confidence': 'high',
        }
        errors = afn.validate_envelope(envelope)
        self.assertTrue(any('title' in e for e in errors))

    def test_bad_action_value_is_invalid(self):
        envelope = {'action': 'delete', 'body': 'b', 'dedup_reason': 'd', 'confidence': 'high'}
        errors = afn.validate_envelope(envelope)
        self.assertTrue(any('action' in e for e in errors))

    def test_envelope_with_also_is_valid(self):
        # Regression: `also` is legal on the top-level envelope, and the model
        # emits it routinely because the schema it is given declares it. The
        # top-level unknown-field check used to reject every envelope carrying
        # it, so the LLM path always fell back to the plain body. The three
        # tests below did not catch it: they assert invalidity and match on the
        # substring "also", which the spurious error also contained.
        base = dict(FIXTURE_ENVELOPE)
        base['also'] = [dict(FIXTURE_ENVELOPE)]
        self.assertEqual(afn.validate_envelope(base), [])

    def test_envelope_with_empty_also_is_valid(self):
        base = dict(FIXTURE_ENVELOPE)
        base['also'] = []
        self.assertEqual(afn.validate_envelope(base), [])

    def test_genuinely_unknown_top_level_field_is_still_invalid(self):
        base = dict(FIXTURE_ENVELOPE)
        base['nonsense'] = 1
        self.assertTrue(any('nonsense' in e for e in afn.validate_envelope(base)))

    def test_new_envelope_with_null_target_issue_is_valid(self):
        # The schema sent to OpenRouter is `strict`, so models return every
        # declared property and null the inapplicable ones. Rejecting on mere
        # presence discarded good output; only a real value is a conflict.
        envelope: dict[str, Any] = {
            'action': 'new',
            'title': 't',
            'body': 'b',
            'labels': ['tests'],
            'issue_type': None,
            'target_issue': None,
            'dedup_reason': 'd',
            'confidence': 'low',
        }
        self.assertEqual(afn.validate_envelope(envelope), [])

    def test_new_envelope_with_a_real_target_issue_is_still_invalid(self):
        envelope: dict[str, Any] = {
            'action': 'new',
            'title': 't',
            'body': 'b',
            'labels': [],
            'issue_type': None,
            'target_issue': 7,
            'dedup_reason': 'd',
            'confidence': 'low',
        }
        self.assertTrue(
            any('target_issue' in e for e in afn.validate_envelope(envelope)),
        )

    def test_comment_envelope_with_null_new_only_fields_is_valid(self):
        envelope: dict[str, Any] = {
            'action': 'comment',
            'target_issue': 7,
            'body': 'b',
            'title': None,
            'labels': None,
            'issue_type': None,
            'dedup_reason': 'd',
            'confidence': 'high',
        }
        self.assertEqual(afn.validate_envelope(envelope), [])

    def test_comment_envelope_with_a_real_title_is_still_invalid(self):
        envelope: dict[str, Any] = {
            'action': 'comment',
            'target_issue': 7,
            'body': 'b',
            'title': 'nope',
            'dedup_reason': 'd',
            'confidence': 'high',
        }
        self.assertTrue(any('title' in e for e in afn.validate_envelope(envelope)))

    def test_also_capped_at_two_entries(self):
        base = dict(FIXTURE_ENVELOPE)
        base['also'] = [dict(FIXTURE_ENVELOPE) for _ in range(3)]
        errors = afn.validate_envelope(base)
        self.assertTrue(any('at most two entries' in e for e in errors), errors)

    def test_nested_also_is_invalid(self):
        base = dict(FIXTURE_ENVELOPE)
        inner = dict(FIXTURE_ENVELOPE)
        inner['also'] = [dict(FIXTURE_ENVELOPE)]
        base['also'] = [inner]
        errors = afn.validate_envelope(base)
        self.assertTrue(any("nested 'also'" in e for e in errors), errors)

    def test_also_entries_individually_validated(self):
        base = dict(FIXTURE_ENVELOPE)
        broken = {'action': 'comment'}  # missing body/dedup_reason/confidence/target_issue
        base['also'] = [broken]
        errors = afn.validate_envelope(base)
        self.assertTrue(any('also[0]' in e for e in errors))


class MainFlowTests(unittest.TestCase):
    """Exercises main()'s branching with gh and OpenRouter mocked out --
    No live gh or OpenRouter calls happen in this test.
    """

    def setUp(self):
        self.env = {
            'REPO': 'canonical/operator',
            'RUN_ID': '28141163589',
            'WORKFLOW_NAME': 'Broad Charm Compatibility Tests',
            'RUN_URL': 'https://github.com/canonical/operator/actions/runs/28141163589',
            'OPENROUTER_API_KEY': 'test-key',
        }

    def _patch_common(
        self,
        *,
        locate_return: tuple[int | None, str | None, int | None],
        gh_calls: mock.Mock,
    ) -> list[Any]:
        patches = [
            mock.patch.object(afn, 'locate_run_markers', return_value=locate_return),
            mock.patch.object(afn, 'fetch_failed_jobs', return_value=[]),
            mock.patch.object(
                afn, 'fetch_run_meta', return_value={'createdAt': '2026-06-25T01:40:15Z'}
            ),
            mock.patch.object(afn, 'search_candidates', return_value=(FIXTURE_CANDIDATES, [])),
            mock.patch.object(afn, 'existing_labels', return_value={'tests', 'docs'}),
            mock.patch.object(afn, 'gh', side_effect=gh_calls),
            mock.patch.object(afn, 'write_step_summary'),
            mock.patch.object(afn, 'set_output'),
        ]
        return patches

    def test_rung_zero_comments_and_skips_llm(self):
        gh_calls = mock.Mock(return_value=mock.Mock(returncode=0, stdout='', stderr=''))
        patches = self._patch_common(locate_return=(9010, None, None), gh_calls=gh_calls)
        with (
            mock.patch.dict('os.environ', self.env, clear=True),
            mock.patch.object(afn, 'call_openrouter') as call_openrouter,
            contextlib.ExitStack() as stack,
        ):
            for p in patches:
                stack.enter_context(p)
            rc = afn.main()
        self.assertEqual(rc, 0)
        call_openrouter.assert_not_called()
        gh_calls.assert_called_once()
        self.assertEqual(gh_calls.call_args.args[:3], ('issue', 'comment', '9010'))

    def test_valid_llm_response_upgrades_placeholder_in_place(self):
        gh_calls = mock.Mock(return_value=mock.Mock(returncode=0, stdout='', stderr=''))
        patches = self._patch_common(locate_return=(None, 'new', 4242), gh_calls=gh_calls)
        envelope = {
            'action': 'new',
            'title': 'x',
            'body': 'y',
            'labels': ['tests'],
            'issue_type': None,
            'dedup_reason': 'd',
            'confidence': 'medium',
        }
        with (
            mock.patch.dict('os.environ', self.env, clear=True),
            mock.patch.object(afn, 'call_openrouter', return_value=envelope),
            contextlib.ExitStack() as stack,
        ):
            for p in patches:
                stack.enter_context(p)
            rc = afn.main()
        self.assertEqual(rc, 0)
        edit_calls = [c for c in gh_calls.call_args_list if c.args[:2] == ('issue', 'edit')]
        self.assertEqual(len(edit_calls), 1)
        self.assertEqual(edit_calls[0].args[2], '4242')

    def test_invalid_llm_response_falls_back_to_plain_comment(self):
        gh_calls = mock.Mock(return_value=mock.Mock(returncode=0, stdout='', stderr=''))
        patches = self._patch_common(locate_return=(None, 'comment', 4242), gh_calls=gh_calls)
        with (
            mock.patch.dict('os.environ', self.env, clear=True),
            mock.patch.object(
                afn, 'call_openrouter', return_value={'action': 'not-a-real-action'}
            ),
            contextlib.ExitStack() as stack,
        ):
            for p in patches:
                stack.enter_context(p)
            rc = afn.main()
        self.assertEqual(rc, 0)
        comment_calls = [c for c in gh_calls.call_args_list if c.args[:2] == ('issue', 'comment')]
        self.assertEqual(len(comment_calls), 1)
        self.assertEqual(comment_calls[0].args[2], '4242')

    def test_no_api_key_uses_plain_fallback_without_calling_llm(self):
        gh_calls = mock.Mock(return_value=mock.Mock(returncode=0, stdout='', stderr=''))
        patches = self._patch_common(locate_return=(None, 'new', 4242), gh_calls=gh_calls)
        env = dict(self.env)
        env.pop('OPENROUTER_API_KEY')
        with (
            mock.patch.dict('os.environ', env, clear=True),
            mock.patch.object(afn, 'call_openrouter') as call_openrouter,
            contextlib.ExitStack() as stack,
        ):
            for p in patches:
                stack.enter_context(p)
            rc = afn.main()
        self.assertEqual(rc, 0)
        call_openrouter.assert_not_called()


class GhCallShapeTests(unittest.TestCase):
    """Pins the argv of each read-only gh call.

    These mock only the `gh` subprocess boundary, not the functions under
    test, so a wrong flag or a mis-quoted positional is visible here. The
    MainFlowTests above patch out `locate_run_markers` and `search_candidates`
    wholesale, which is why both shipped with argv bugs that 29 green tests
    did not catch -- see the 2026-07-25 dev-box run against canonical/operator.
    """

    def _capture(self, stdout: str = '[]') -> mock.Mock:
        return mock.Mock(return_value=mock.Mock(returncode=0, stdout=stdout, stderr=''))

    def test_search_issue_numbers_passes_repo_as_a_flag(self):
        gh_calls = self._capture('[{"number": 2658}]')
        with mock.patch.object(afn, 'gh', side_effect=gh_calls):
            numbers = afn.search_issue_numbers('canonical/operator', 'Example Charm Tests')
        self.assertEqual(numbers, [2658])
        args = gh_calls.call_args.args
        self.assertEqual(args[:2], ('search', 'issues'))
        self.assertIn('--repo', args)
        self.assertEqual(args[args.index('--repo') + 1], 'canonical/operator')
        # The query is a bare positional -- no `repo:` prefix, no added quotes.
        # `gh search issues` quotes each positional as one keyword, so folding
        # the repo in produces `repo:"canonical/operator \"text\""`, which
        # GitHub rejects with "Invalid search query".
        self.assertIn('Example Charm Tests', args)
        for arg in args:
            self.assertNotIn('repo:canonical/operator', arg)

    def test_search_candidates_passes_state_and_search_flags(self):
        gh_calls = self._capture('[]')
        with mock.patch.object(afn, 'gh', side_effect=gh_calls):
            afn.search_candidates('canonical/operator', 'Example Charm Tests')
        states: list[str] = []
        for call in gh_calls.call_args_list:
            args = call.args
            self.assertEqual(args[:2], ('issue', 'list'))
            self.assertEqual(args[args.index('--repo') + 1], 'canonical/operator')
            self.assertEqual(args[args.index('--search') + 1], '"Example Charm Tests"')
            states.append(args[args.index('--state') + 1])
        self.assertEqual(states, ['open', 'closed'])

    def test_fetch_job_log_uses_the_rest_logs_endpoint(self):
        gh_calls = self._capture('2026-07-21T16:17:04Z some log line\n')
        with mock.patch.object(afn, 'gh', side_effect=gh_calls):
            log = afn.fetch_job_log('canonical/operator', '29847889218', 88693036489)
        self.assertIn('some log line', log)
        self.assertEqual(
            gh_calls.call_args.args,
            ('api', 'repos/canonical/operator/actions/jobs/88693036489/logs'),
        )

    def test_fetch_job_log_reports_an_empty_log_instead_of_swallowing_it(self):
        gh_calls = self._capture('')
        with (
            mock.patch.object(afn, 'gh', side_effect=gh_calls),
            mock.patch.object(afn, 'write_step_summary') as summary,
        ):
            log = afn.fetch_job_log('canonical/operator', '29847889218', 88693036489)
        self.assertEqual(log, '')
        summary.assert_called_once()
        self.assertIn('no log text', summary.call_args.args[0])

    def test_fetch_failed_jobs_requests_the_jobs_field(self):
        gh_calls = self._capture(
            '{"jobs": [{"databaseId": 1, "name": "j", "conclusion": "failure",'
            ' "steps": [{"name": "s", "conclusion": "failure"}]}]}'
        )
        with mock.patch.object(afn, 'gh', side_effect=gh_calls):
            jobs = afn.fetch_failed_jobs('canonical/operator', '29847889218')
        self.assertEqual(jobs, [afn.FailedJob(id=1, name='j', failed_step='s')])
        args = gh_calls.call_args.args
        self.assertEqual(args[:3], ('run', 'view', '29847889218'))
        self.assertEqual(args[args.index('--json') + 1], 'jobs')

    def test_existing_labels_requests_the_name_field(self):
        gh_calls = self._capture('[{"name": "tests"}, {"name": "docs"}]')
        with mock.patch.object(afn, 'gh', side_effect=gh_calls):
            labels = afn.existing_labels('canonical/operator')
        self.assertEqual(labels, {'tests', 'docs'})
        args = gh_calls.call_args.args
        self.assertEqual(args[:2], ('label', 'list'))
        self.assertEqual(args[args.index('--json') + 1], 'name')


class MarkerLookupConsistencyTests(unittest.TestCase):
    """The notifier's marker must be found without depending on the search index.

    `gh search issues` is not read-your-writes: the notifier stamps its marker
    seconds before the enricher runs, and an unindexed marker reads as "no
    notifier marker found", which makes main() open a *second* issue for a run
    that already has one. The issue list endpoint has no such lag, so it is
    consulted first and search is only a fallback.
    """

    def _gh(self, responses: list[str]) -> mock.Mock:
        return mock.Mock(
            side_effect=[mock.Mock(returncode=0, stdout=out, stderr='') for out in responses]
        )

    def test_marker_in_a_body_is_found_without_any_search_call(self):
        listing = json.dumps(
            [
                {'number': 2700, 'body': 'unrelated', 'comments': []},
                {
                    'number': 2658,
                    'body': 'placeholder\n\n<!-- ai-failure-notifications:run=999:origin=new -->',
                    'comments': [],
                },
            ]
        )
        gh_calls = self._gh([listing])
        with mock.patch.object(afn, 'gh', side_effect=gh_calls):
            enriched, kind, number = afn.locate_run_markers('canonical/operator', '999')
        self.assertEqual((enriched, kind, number), (None, 'new', 2658))
        # Exactly one call, and it is the list endpoint -- not search.
        self.assertEqual(gh_calls.call_count, 1)
        args = gh_calls.call_args.args
        self.assertEqual(args[:2], ('issue', 'list'))
        self.assertEqual(args[args.index('--repo') + 1], 'canonical/operator')
        self.assertEqual(args[args.index('--state') + 1], 'all')
        self.assertEqual(args[args.index('--json') + 1], 'number,body,comments')

    def test_marker_in_a_comment_is_found_too(self):
        comment = 'failed again\n\n<!-- ai-failure-notifications:run=999:origin=comment -->'
        listing = json.dumps(
            [
                {
                    'number': 2601,
                    'body': 'an older failure thread',
                    'comments': [{'body': comment}],
                }
            ]
        )
        with mock.patch.object(afn, 'gh', side_effect=self._gh([listing])):
            enriched, kind, number = afn.locate_run_markers('canonical/operator', '999')
        self.assertEqual((enriched, kind, number), (None, 'comment', 2601))

    def test_search_is_a_fallback_when_the_listing_misses(self):
        listing = json.dumps([{'number': 2700, 'body': 'unrelated', 'comments': []}])
        search = json.dumps([{'number': 2658}])
        view = json.dumps(
            {
                'body': 'placeholder\n\n<!-- ai-failure-notifications:run=999:origin=new -->',
                'comments': [],
            }
        )
        gh_calls = self._gh([listing, search, view])
        with mock.patch.object(afn, 'gh', side_effect=gh_calls):
            enriched, kind, number = afn.locate_run_markers('canonical/operator', '999')
        self.assertEqual((enriched, kind, number), (None, 'new', 2658))
        self.assertEqual(gh_calls.call_args_list[1].args[:2], ('search', 'issues'))

    def test_an_unindexed_marker_still_resolves(self):
        """The regression this change exists for.

        Search returns nothing (the marker is not indexed yet) but the issue is
        right there in the listing. Before the fix this returned all-None and
        main() opened a duplicate issue.
        """
        listing = json.dumps(
            [
                {
                    'number': 2658,
                    'body': 'placeholder\n\n<!-- ai-failure-notifications:run=999:origin=new -->',
                    'comments': [],
                }
            ]
        )
        with mock.patch.object(afn, 'gh', side_effect=self._gh([listing, '[]'])):
            enriched, kind, number = afn.locate_run_markers('canonical/operator', '999')
        self.assertEqual((enriched, kind, number), (None, 'new', 2658))

    def test_rung_zero_sig_marker_is_found_in_the_listing(self):
        listing = json.dumps(
            [
                {
                    'number': 2658,
                    'body': 'enriched\n\n<!-- ai-failure-notifications:run=999:sig=abc123 -->',
                    'comments': [],
                }
            ]
        )
        with mock.patch.object(afn, 'gh', side_effect=self._gh([listing])):
            enriched, _, _ = afn.locate_run_markers('canonical/operator', '999')
        self.assertEqual(enriched, 2658)


class NormalisationTests(unittest.TestCase):
    """Fields that do not apply to the chosen action are dropped, not fatal.

    Found by dogfooding: the model is given a `strict` schema, so it returns
    every declared property and fills the ones irrelevant to the action it
    chose. Treating those as validation errors discarded a perfectly good
    comment body and fell back to the plain notice.
    """

    def test_comment_loses_new_only_fields(self):
        envelope: dict[str, Any] = {
            'action': 'comment',
            'target_issue': 9010,
            'body': 'Another occurrence.',
            'title': 'a title it should not have',
            'labels': ['tests'],
            'issue_type': 'bug',
            'dedup_reason': 'd',
            'confidence': 'high',
        }
        cleaned, dropped = afn.normalise_envelope(envelope)
        self.assertEqual(
            sorted(dropped), ['envelope: issue_type', 'envelope: labels', 'envelope: title']
        )
        self.assertNotIn('title', cleaned)
        self.assertEqual(cleaned['body'], 'Another occurrence.')
        self.assertEqual(afn.validate_envelope(cleaned), [])

    def test_new_loses_target_issue(self):
        envelope: dict[str, Any] = {
            'action': 'new',
            'title': 't',
            'body': 'b',
            'labels': [],
            'issue_type': None,
            'target_issue': 7,
            'dedup_reason': 'd',
            'confidence': 'low',
        }
        cleaned, dropped = afn.normalise_envelope(envelope)
        self.assertEqual(dropped, ['envelope: target_issue'])
        self.assertEqual(afn.validate_envelope(cleaned), [])

    def test_also_entries_are_normalised_too(self):
        inner: dict[str, Any] = {
            'action': 'comment',
            'target_issue': 1,
            'body': 'b',
            'title': 'nope',
            'dedup_reason': 'd',
            'confidence': 'low',
        }
        envelope: dict[str, Any] = {
            'action': 'new',
            'title': 't',
            'body': 'b',
            'labels': [],
            'issue_type': None,
            'dedup_reason': 'd',
            'confidence': 'low',
            'also': [inner],
        }
        cleaned, dropped = afn.normalise_envelope(envelope)
        self.assertEqual(dropped, ['envelope.also[0]: title'])
        self.assertEqual(afn.validate_envelope(cleaned), [])

    def test_nothing_dropped_leaves_the_envelope_alone(self):
        cleaned, dropped = afn.normalise_envelope(FIXTURE_ENVELOPE)
        self.assertEqual(dropped, [])
        self.assertIs(cleaned, FIXTURE_ENVELOPE)


class CandidatePoolTests(unittest.TestCase):
    """The issue the notifier commented on stays in the candidate pool.

    Found by dogfooding. The origin issue was excluded unconditionally. When
    the notifier had commented on a pre-existing issue -- the case for every
    recurrence after the first -- that issue is the most likely duplicate, and
    removing it left the model with an empty candidate list. It answered "new",
    and a duplicate issue was opened: the exact outcome this path exists to
    prevent.
    """

    def _run_main(self, *, origin_kind: str, candidates: list[afn.CandidateIssue]) -> str:
        captured: dict[str, str] = {}

        def fake_build_prompt(
            workflow_name: str, run_url: str, signature: Any, candidates_block: str
        ) -> tuple[str, str]:
            captured['block'] = candidates_block
            return 'sys', 'user'

        env = {
            'REPO': 'canonical/operator',
            'RUN_ID': '28141163589',
            'WORKFLOW_NAME': 'Broad Charm Compatibility Tests',
            'RUN_URL': 'https://example.invalid/run',
            'OPENROUTER_API_KEY': 'test-key',
        }
        with (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(afn, 'locate_run_markers', return_value=(None, origin_kind, 9010)),
            mock.patch.object(afn, 'fetch_failed_jobs', return_value=[]),
            mock.patch.object(afn, 'fetch_run_meta', return_value={'createdAt': ''}),
            mock.patch.object(afn, 'search_candidates', return_value=(candidates, [])),
            mock.patch.object(afn, 'existing_labels', return_value=set()),
            mock.patch.object(afn, 'build_prompt', side_effect=fake_build_prompt),
            mock.patch.object(afn, 'call_openrouter', return_value={'action': 'bogus'}),
            mock.patch.object(afn, 'gh'),
            mock.patch.object(afn, 'write_step_summary'),
            mock.patch.object(afn, 'set_output'),
        ):
            afn.main()
        return captured['block']

    def test_commented_origin_issue_is_offered_as_a_candidate(self):
        candidate = afn.CandidateIssue(
            number=9010, title='the tracked one', body='x', closed_at=None
        )
        block = self._run_main(origin_kind='comment', candidates=[candidate])
        self.assertIn('#9010', block)

    def test_freshly_created_placeholder_is_not_offered_as_a_candidate(self):
        candidate = afn.CandidateIssue(
            number=9010, title='the placeholder', body='x', closed_at=None
        )
        block = self._run_main(origin_kind='new', candidates=[candidate])
        self.assertNotIn('#9010', block)


class BodyFooterTests(unittest.TestCase):
    """Every body carries the footer the notifier's coarse search matches on.

    Found by dogfooding: the footer was described in the design and in the
    notifier's own comment, but only ever existed in the prompt template, so
    enriched issues went out without it. The coarse search then depended on
    the model happening to leave the workflow name in the title.
    """

    def test_render_body_has_footer_and_marker(self):
        body = afn.render_body('Some detail.', 'Example Charm Tests', '<!-- m -->')
        self.assertEqual(body, 'Some detail.\n\nWorkflow: Example Charm Tests\n\n<!-- m -->')

    def test_applied_comment_body_has_the_footer(self):
        gh_calls = mock.Mock(return_value=mock.Mock(returncode=0, stdout='', stderr=''))
        entry: dict[str, Any] = {'action': 'comment', 'body': 'Another occurrence.'}
        with mock.patch.object(afn, 'gh', side_effect=gh_calls):
            afn.apply_entry(
                'canonical/operator', entry, '<!-- m -->', 'ops Smoke Tests', default_target=7
            )
        args = gh_calls.call_args.args
        self.assertEqual(args[:3], ('issue', 'comment', '7'))
        self.assertIn('Workflow: ops Smoke Tests', args[args.index('--body') + 1])

    def test_applied_new_issue_body_has_the_footer(self):
        gh_calls = mock.Mock(
            return_value=mock.Mock(returncode=0, stdout='https://x/issues/9', stderr='')
        )
        entry: dict[str, Any] = {
            'action': 'new',
            'title': 't',
            'body': 'Detail.',
            'labels': [],
            'issue_type': None,
        }
        with (
            mock.patch.object(afn, 'gh', side_effect=gh_calls),
            mock.patch.object(afn, 'existing_labels', return_value=set()),
        ):
            afn.apply_entry('canonical/operator', entry, '<!-- m -->', 'ops Smoke Tests')
        args = gh_calls.call_args.args
        self.assertIn('Workflow: ops Smoke Tests', args[args.index('--body') + 1])


class StepSummaryTests(unittest.TestCase):
    """Fallback reporting reaches the job log, not only the step summary."""

    def test_message_goes_to_stderr_even_with_a_summary_file(self):
        with tempfile.NamedTemporaryFile('w+', suffix='.md', delete=False) as handle:
            summary_path = handle.name
        self.addCleanup(os.unlink, summary_path)
        stderr = io.StringIO()
        with (
            mock.patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': summary_path}, clear=True),
            contextlib.redirect_stderr(stderr),
        ):
            afn.write_step_summary('OpenRouter call failed (boom)')
        self.assertIn('OpenRouter call failed (boom)', stderr.getvalue())
        with open(summary_path, encoding='utf-8') as handle:
            self.assertIn('OpenRouter call failed (boom)', handle.read())


class MainDegradationTests(unittest.TestCase):
    """main() degrades through its own fallbacks when a gh search fails.

    Without these, a search failure raises out of main(), kills the enrich
    job, and hands every run to the workflow-level plain-fallback -- so
    enrichment silently never happens and the job still looks healthy.
    """

    def setUp(self):
        self.env = {
            'REPO': 'canonical/operator',
            'RUN_ID': '28141163589',
            'WORKFLOW_NAME': 'Broad Charm Compatibility Tests',
            'RUN_URL': 'https://github.com/canonical/operator/actions/runs/28141163589',
        }

    def test_marker_lookup_failure_does_not_crash_main(self):
        gh_calls = mock.Mock(
            return_value=mock.Mock(
                returncode=0, stdout='https://github.com/canonical/operator/issues/9999', stderr=''
            )
        )
        with (
            mock.patch.dict('os.environ', self.env, clear=True),
            mock.patch.object(afn, 'locate_run_markers', side_effect=RuntimeError('boom')),
            mock.patch.object(afn, 'fetch_failed_jobs', return_value=[]),
            mock.patch.object(afn, 'fetch_run_meta', return_value={'createdAt': ''}),
            mock.patch.object(afn, 'existing_labels', return_value=set()),
            mock.patch.object(afn, 'gh', side_effect=gh_calls),
            mock.patch.object(afn, 'write_step_summary') as summary,
            mock.patch.object(afn, 'set_output') as set_output,
        ):
            rc = afn.main()
        self.assertEqual(rc, 0)
        set_output.assert_called_with('handled', 'true')
        self.assertTrue(
            any('Marker lookup failed' in c.args[0] for c in summary.call_args_list),
            'the failure should be reported in the step summary',
        )

    def test_candidate_search_failure_proceeds_with_no_candidates(self):
        gh_calls = mock.Mock(return_value=mock.Mock(returncode=0, stdout='', stderr=''))
        env = dict(self.env, OPENROUTER_API_KEY='test-key')
        with (
            mock.patch.dict('os.environ', env, clear=True),
            mock.patch.object(afn, 'locate_run_markers', return_value=(None, 'new', 4242)),
            mock.patch.object(afn, 'fetch_failed_jobs', return_value=[]),
            mock.patch.object(afn, 'fetch_run_meta', return_value={'createdAt': ''}),
            mock.patch.object(afn, 'search_candidates', side_effect=RuntimeError('boom')),
            mock.patch.object(afn, 'existing_labels', return_value=set()),
            mock.patch.object(
                afn, 'call_openrouter', return_value={'action': 'not-a-real-action'}
            ),
            mock.patch.object(afn, 'gh', side_effect=gh_calls),
            mock.patch.object(afn, 'write_step_summary') as summary,
            mock.patch.object(afn, 'set_output'),
        ):
            rc = afn.main()
        self.assertEqual(rc, 0)
        self.assertTrue(
            any('Candidate search failed' in c.args[0] for c in summary.call_args_list),
            'the failure should be reported in the step summary',
        )


class OpenRouterCallTests(unittest.TestCase):
    """The OpenRouter call is built with urllib, so it has no third-party deps.

    Previously this function was only ever mocked, so nothing checked the
    request it actually builds.
    """

    def _response(self, content: str) -> mock.MagicMock:
        payload = json.dumps({'choices': [{'message': {'content': content}}]}).encode()
        response = mock.MagicMock()
        response.read.return_value = payload
        response.__enter__.return_value = response
        return response

    def test_posts_json_with_auth_and_schema(self):
        envelope = {'action': 'new', 'body': 'b'}
        with mock.patch.object(
            afn.urllib.request, 'urlopen', return_value=self._response(json.dumps(envelope))
        ) as urlopen:
            result = afn.call_openrouter('sys', 'user', 'some/model', 'secret-key')

        self.assertEqual(result, envelope)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.method, 'POST')
        self.assertEqual(request.full_url, 'https://openrouter.ai/api/v1/chat/completions')
        # urllib title-cases header keys, so compare case-insensitively.
        headers = {k.lower(): v for k, v in request.headers.items()}
        self.assertEqual(headers['Authorization'.lower()], 'Bearer secret-key')
        self.assertEqual(headers['Content-type'.lower()], 'application/json')
        self.assertEqual(urlopen.call_args.kwargs['timeout'], 60)

        sent = json.loads(request.data.decode())
        self.assertEqual(sent['model'], 'some/model')
        self.assertEqual([m['role'] for m in sent['messages']], ['system', 'user'])
        self.assertEqual(sent['messages'][0]['content'], 'sys')
        self.assertEqual(sent['messages'][1]['content'], 'user')
        self.assertEqual(sent['response_format']['type'], 'json_schema')
        self.assertEqual(
            sent['response_format']['json_schema']['schema'], afn.ENVELOPE_JSON_SCHEMA
        )
        self.assertTrue(sent['response_format']['json_schema']['strict'])

    def test_http_error_propagates_so_main_can_fall_back(self):
        # HTTPError holds a file object and warns on implicit cleanup, which
        # the unit env's -W error turns into a failure. Give it a real `fp`
        # (it fabricates a tempfile when passed None) and close it explicitly.
        error = urllib.error.HTTPError(
            'https://openrouter.ai/api/v1/chat/completions',
            500,
            'boom',
            email.message.Message(),
            io.BytesIO(b''),
        )
        self.addCleanup(error.close)
        with mock.patch.object(afn.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                afn.call_openrouter('sys', 'user', 'm', 'k')


if __name__ == '__main__':
    unittest.main()
