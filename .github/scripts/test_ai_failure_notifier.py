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

"""Unit tests for ai_failure_notifier.py.

Run with: uv run .github/scripts/test_ai_failure_notifier.py
(or: python3 -m unittest .github.scripts.test_ai_failure_notifier -v)

No network calls and no `gh` calls happen in this file -- OpenRouter and gh
I/O are mocked. The fixture in testdata/run-28141163589.json is derived from
a real corpus run's extracted signature (see the file's own `_source` note),
used here as a self-test per step 5's task brief, not as new dedup-ladder
calibration (that's spike-step-3/FINDINGS.md's job).
"""

from __future__ import annotations

import json
import sys
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import ai_failure_notifier as afn

FIXTURE = json.loads((Path(__file__).parent / 'testdata' / 'run-28141163589.json').read_text())


class SignatureExtractionTests(unittest.TestCase):
    def test_strip_line_removes_timestamp_and_ansi(self):
        raw = '2026-06-25T01:40:15.8141713Z \x1b[36mhello\x1b[0m'
        self.assertEqual(
            afn.strip_line(raw),
            '\x1b[36mhello\x1b[0m'.replace('\x1b[36m', '').replace('\x1b[0m', ''),
        )

    def test_parse_job_log_pytest_failures_and_summary_bound(self):
        log = '\n'.join([
            '2026-06-25T01:40:15.0000000Z ============ short test summary info ============',
            '2026-06-25T01:40:15.0000000Z FAILED tests/unit/test_x.py::test_a - AssertionError: x',
            '2026-06-25T01:40:15.0000000Z ERROR tests/unit/test_x.py::test_b - PendingDeprecat...',
            '2026-06-25T01:40:15.0000000Z ============ 2 failed in 1.23s ============',
            '2026-06-25T01:40:15.0000000Z some trailing noise, not part of the summary',
        ])
        pytest_failures, go_failures, _tb, _tail = afn.parse_job_log(log)
        self.assertEqual(
            pytest_failures,
            [
                {
                    'kind': 'FAILED',
                    'test': 'tests/unit/test_x.py::test_a',
                    'error': 'AssertionError: x',
                },
                {
                    'kind': 'ERROR',
                    'test': 'tests/unit/test_x.py::test_b',
                    'error': 'PendingDeprecat...',
                },
            ],
        )
        self.assertEqual(go_failures, [])

    def test_parse_job_log_go_failures(self):
        log = '--- FAIL: TestFoo (0.03s)\n--- FAIL: TestBar (0.01s)\n'
        _pytest_failures, go_failures, _tb, _tail = afn.parse_job_log(log)
        self.assertEqual(go_failures, ['TestFoo', 'TestBar'])

    def test_parse_job_log_traceback_top_error_prefers_last_match(self):
        log = '\n'.join([
            'ValueError: first, ignored',
            'some other output',
            'AttributeError: the real one',
        ])
        _, _, tb, _ = afn.parse_job_log(log)
        self.assertEqual(tb, 'AttributeError: the real one')

    def test_parse_job_log_tail_excerpt_stops_before_first_error_marker(self):
        log = '\n'.join([
            'line before 1',
            'line before 2',
            '##[error]something broke',
            'line after (should not appear in tail)',
        ])
        _, _, _, tail = afn.parse_job_log(log)
        self.assertEqual(tail, ['line before 1', 'line before 2'])

    def test_build_run_signature_matches_fixture_shape(self):
        jobs = [
            afn.build_job_signature(j['job_id'], j['job_name'], j['failed_step'], '')
            for j in FIXTURE['signature']['jobs']
        ]
        sig = afn.build_run_signature(
            '28141163589', 'Broad Charm Compatibility Tests', 'url', '2026-06-25T01:40:15Z', jobs
        )
        self.assertEqual(sig['run_id'], '28141163589')
        self.assertEqual(len(sig['jobs']), 5)


class MarkerTests(unittest.TestCase):
    def test_render_and_parse_notifier_marker(self):
        marker = afn.render_notifier_marker('123', 'new')
        enriched, origin_kind, origin_issue = afn.find_run_markers([(42, marker)], '123')
        self.assertIsNone(enriched)
        self.assertEqual(origin_kind, 'new')
        self.assertEqual(origin_issue, 42)

    def test_render_and_parse_enriched_marker_is_rung_zero(self):
        sig = FIXTURE['signature']
        marker = afn.render_enriched_marker('28141163589', sig)
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
        sig = FIXTURE['signature']
        h1 = afn.signature_hash(sig)
        h2 = afn.signature_hash(json.loads(json.dumps(sig)))  # round-tripped copy
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
            FIXTURE['open_candidates'], [], datetime.now(timezone.utc)
        )
        self.assertIn('#9010', block)
        self.assertIn('Broad Charm Compatibility Tests', block)
        self.assertNotIn('closed', block)

    def test_empty_candidates_block(self):
        block = afn.build_candidates_block([], [], datetime.now(timezone.utc))
        self.assertEqual(block, '(no open scheduled-failure issues found for this workflow)')

    def test_recently_closed_candidate_is_labelled_and_capped_at_medium(self):
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        closed = [
            {'number': 42, 'title': 'old thing', 'body': 'x', 'closedAt': '2026-06-20T00:00:00Z'}
        ]
        block = afn.build_candidates_block([], closed, now)
        self.assertIn('#42', block)
        self.assertIn('closed', block)
        self.assertIn('medium-confidence', block)

    def test_closed_candidate_outside_window_is_dropped(self):
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        closed = [
            {'number': 42, 'title': 'ancient', 'body': 'x', 'closedAt': '2026-01-01T00:00:00Z'}
        ]
        block = afn.build_candidates_block([], closed, now)
        self.assertEqual(block, '(no open scheduled-failure issues found for this workflow)')

    def test_candidates_capped_at_three(self):
        opens = [
            {'number': n, 'title': f'issue {n}', 'body': 'x', 'closedAt': None} for n in range(5)
        ]
        block = afn.build_candidates_block(opens, [], datetime.now(timezone.utc))
        self.assertEqual(block.count('- **#'), 3)


class SchemaValidationTests(unittest.TestCase):
    def test_valid_comment_envelope_from_fixture(self):
        errors = afn.validate_envelope(FIXTURE['expected_envelope'])
        self.assertEqual(errors, [])

    def test_valid_new_envelope(self):
        envelope = {
            'action': 'new',
            'title': 'Something failed',
            'body': 'details',
            'labels': ['scheduled-failure', 'flaky'],
            'issue_type': None,
            'dedup_reason': 'no match',
            'confidence': 'low',
        }
        self.assertEqual(afn.validate_envelope(envelope), [])

    def test_new_envelope_missing_scheduled_failure_label_is_invalid(self):
        errors = afn.validate_envelope(FIXTURE['invalid_envelope_missing_scheduled_failure_label'])
        self.assertTrue(any('scheduled-failure' in e for e in errors))

    def test_new_envelope_with_target_issue_is_invalid(self):
        envelope = {
            'action': 'new',
            'title': 't',
            'body': 'b',
            'labels': ['scheduled-failure'],
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

    def test_also_capped_at_two_entries(self):
        base = dict(FIXTURE['expected_envelope'])
        base['also'] = [dict(FIXTURE['expected_envelope']) for _ in range(3)]
        errors = afn.validate_envelope(base)
        self.assertTrue(any('also' in e for e in errors))

    def test_nested_also_is_invalid(self):
        base = dict(FIXTURE['expected_envelope'])
        inner = dict(FIXTURE['expected_envelope'])
        inner['also'] = [dict(FIXTURE['expected_envelope'])]
        base['also'] = [inner]
        errors = afn.validate_envelope(base)
        self.assertTrue(any('also' in e for e in errors))

    def test_also_entries_individually_validated(self):
        base = dict(FIXTURE['expected_envelope'])
        broken = {'action': 'comment'}  # missing body/dedup_reason/confidence/target_issue
        base['also'] = [broken]
        errors = afn.validate_envelope(base)
        self.assertTrue(any('also[0]' in e for e in errors))


class MainFlowTests(unittest.TestCase):
    """Exercises main()'s branching with gh and OpenRouter mocked out --
    per the task brief, no live gh/OpenRouter calls happen in this test.
    """

    def setUp(self):
        self.env = {
            'REPO': 'canonical/operator',
            'RUN_ID': '28141163589',
            'WORKFLOW_NAME': 'Broad Charm Compatibility Tests',
            'RUN_URL': 'https://github.com/canonical/operator/actions/runs/28141163589',
            'OPENROUTER_API_KEY': 'test-key',
        }

    def _patch_common(self, *, locate_return, gh_calls):
        patches = [
            mock.patch.object(afn, 'locate_run_markers', return_value=locate_return),
            mock.patch.object(afn, 'fetch_failed_jobs', return_value=[]),
            mock.patch.object(
                afn, 'fetch_run_meta', return_value={'createdAt': '2026-06-25T01:40:15Z'}
            ),
            mock.patch.object(
                afn, 'search_candidates', return_value=(FIXTURE['open_candidates'], [])
            ),
            mock.patch.object(afn, 'existing_labels', return_value={'scheduled-failure', 'flaky'}),
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
            ExitStack() as stack,
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
            'labels': ['scheduled-failure'],
            'issue_type': None,
            'dedup_reason': 'd',
            'confidence': 'medium',
        }
        with (
            mock.patch.dict('os.environ', self.env, clear=True),
            mock.patch.object(afn, 'call_openrouter', return_value=envelope),
            ExitStack() as stack,
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
            ExitStack() as stack,
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
            ExitStack() as stack,
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

    def _capture(self, stdout='[]'):
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
        states = []
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
        self.assertEqual(jobs, [{'id': 1, 'name': 'j', 'failed_step': 's'}])
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


if __name__ == '__main__':
    unittest.main()
