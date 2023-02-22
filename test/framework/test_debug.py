# Copyright 2023 Canonical Ltd.
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

import inspect
import io
import os
import sys
from test.test_helpers import BaseTestCase, fake_script
from unittest.mock import patch

import logassert

from ops import charm
from ops.framework import (
    _BREAKPOINT_WELCOME_MESSAGE,
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
)


class GenericObserver(Object):
    """Generic observer for the tests."""

    def __init__(self, parent, key):
        super().__init__(parent, key)
        self.called = False

    def callback_method(self, event):
        """Set the instance .called to True."""
        self.called = True


@patch('sys.stderr', new_callable=io.StringIO)
class BreakpointTests(BaseTestCase):

    def setUp(self):
        super().setUp()
        logassert.setup(self, 'ops')

    def test_ignored(self, fake_stderr):
        # It doesn't do anything really unless proper environment is there.
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            framework = self.create_framework()

        with patch('pdb.Pdb.set_trace') as mock:
            framework.breakpoint()
        self.assertEqual(mock.call_count, 0)
        self.assertEqual(fake_stderr.getvalue(), "")
        self.assertNotLoggedWarning("Breakpoint", "skipped")

    def test_pdb_properly_called(self, fake_stderr):
        # The debugger needs to leave the user in the frame where the breakpoint is executed,
        # which for the test is the frame we're calling it here in the test :).
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()

        with patch('pdb.Pdb.set_trace') as mock:
            this_frame = inspect.currentframe()
            framework.breakpoint()

        self.assertEqual(mock.call_count, 1)
        self.assertEqual(mock.call_args, ((this_frame,), {}))

    def test_welcome_message(self, fake_stderr):
        # Check that an initial message is shown to the user when code is interrupted.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace'):
            framework.breakpoint()
        self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_welcome_message_not_multiple(self, fake_stderr):
        # Check that an initial message is NOT shown twice if the breakpoint is exercised
        # twice in the same run.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace'):
            framework.breakpoint()
            self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
            framework.breakpoint()
            self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_breakpoint_builtin_sanity(self, fake_stderr):
        # this just checks that calling breakpoint() works as expected
        # nothing really framework-dependent
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            self.create_framework()

        with patch('pdb.Pdb.set_trace') as mock:
            this_frame = inspect.currentframe()
            breakpoint()

        self.assertEqual(mock.call_count, 1)
        self.assertEqual(mock.call_args, ((this_frame,), {}))

    def test_builtin_breakpoint_hooked(self, fake_stderr):
        # Verify that the proper hook is set.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()
        old_breakpointhook = framework.set_breakpointhook()
        self.addCleanup(setattr, sys, 'breakpointhook', old_breakpointhook)
        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()
        self.assertEqual(mock.call_count, 1)

    def test_breakpoint_builtin_unset(self, fake_stderr):
        # if no JUJU_DEBUG_AT, no call to pdb is done
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            framework = self.create_framework()
        old_breakpointhook = framework.set_breakpointhook()
        self.addCleanup(setattr, sys, 'breakpointhook', old_breakpointhook)

        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()

        self.assertEqual(mock.call_count, 0)

    def test_breakpoint_names(self, fake_stderr):
        framework = self.create_framework()

        # Name rules:
        # - must start and end with lowercase alphanumeric characters
        # - only contain lowercase alphanumeric characters, or the hyphen "-"
        good_names = [
            'foobar',
            'foo-bar-baz',
            'foo-------bar',
            'foo123',
            '778',
            '77-xx',
            'a-b',
            'ab',
            'x',
        ]
        for name in good_names:
            with self.subTest(name=name):
                framework.breakpoint(name)

        bad_names = [
            '',
            '.',
            '-',
            '...foo',
            'foo.bar',
            'bar--'
            'FOO',
            'FooBar',
            'foo bar',
            'foo_bar',
            '/foobar',
            'break-here-☚',
        ]
        msg = 'breakpoint names must look like "foo" or "foo-bar"'
        for name in bad_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as cm:
                    framework.breakpoint(name)
                self.assertEqual(str(cm.exception), msg)

        reserved_names = [
            'all',
            'hook',
        ]
        msg = 'breakpoint names "all" and "hook" are reserved'
        for name in reserved_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as cm:
                    framework.breakpoint(name)
                self.assertEqual(str(cm.exception), msg)

        not_really_names = [
            123,
            1.1,
            False,
        ]
        for name in not_really_names:
            with self.subTest(name=name):
                with self.assertRaises(TypeError) as cm:
                    framework.breakpoint(name)
                self.assertEqual(str(cm.exception), 'breakpoint names must be strings')

    def check_trace_set(self, envvar_value, breakpoint_name, call_count):
        """Helper to check the diverse combinations of situations."""
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': envvar_value}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace') as mock:
            framework.breakpoint(breakpoint_name)
        self.assertEqual(mock.call_count, call_count)

    def test_unnamed_indicated_all(self, fake_stderr):
        # If 'all' is indicated, unnamed breakpoints will always activate.
        self.check_trace_set('all', None, 1)

    def test_unnamed_indicated_hook(self, fake_stderr):
        # Special value 'hook' was indicated, nothing to do with any call.
        self.check_trace_set('hook', None, 0)

    def test_named_indicated_specifically(self, fake_stderr):
        # Some breakpoint was indicated, and the framework call used exactly that name.
        self.check_trace_set('mybreak', 'mybreak', 1)

    def test_named_indicated_unnamed(self, fake_stderr):
        # Some breakpoint was indicated, but the framework call was unnamed
        self.check_trace_set('some-breakpoint', None, 0)
        self.assertLoggedWarning(
            "Breakpoint None skipped",
            "not found in the requested breakpoints: {'some-breakpoint'}")

    def test_named_indicated_somethingelse(self, fake_stderr):
        # Some breakpoint was indicated, but the framework call was with a different name
        self.check_trace_set('some-breakpoint', 'other-name', 0)
        self.assertLoggedWarning(
            "Breakpoint 'other-name' skipped",
            "not found in the requested breakpoints: {'some-breakpoint'}")

    def test_named_indicated_ingroup(self, fake_stderr):
        # A multiple breakpoint was indicated, and the framework call used a name among those.
        self.check_trace_set('some,mybreak,foobar', 'mybreak', 1)

    def test_named_indicated_all(self, fake_stderr):
        # The framework indicated 'all', which includes any named breakpoint set.
        self.check_trace_set('all', 'mybreak', 1)

    def test_named_indicated_hook(self, fake_stderr):
        # The framework indicated the special value 'hook', nothing to do with any named call.
        self.check_trace_set('hook', 'mybreak', 0)


class DebugHookTests(BaseTestCase):

    def test_envvar_parsing_missing(self):
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, set())

    def test_envvar_parsing_empty(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': ''}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, set())

    def test_envvar_parsing_simple(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'hook'}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, {'hook'})

    def test_envvar_parsing_multiple(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'foo,bar,all'}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, {'foo', 'bar', 'all'})

    def test_basic_interruption_enabled(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'hook'}

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO) as fake_stderr:
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        # Check that the pdb module was used correctly and that the callback method was NOT
        # called (as we intercepted the normal pdb behaviour! this is to check that the
        # framework didn't call the callback directly)
        self.assertEqual(mock.call_count, 1)
        expected_callback, expected_event = mock.call_args[0]
        self.assertEqual(expected_callback, observer.callback_method)
        self.assertIsInstance(expected_event, EventBase)
        self.assertFalse(observer.called)

        # Verify proper message was given to the user.
        self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_interruption_enabled_with_all(self):
        test_model = self.create_model()
        framework = self.create_framework(model=test_model)
        framework._juju_debug_at = {'all'}

        class CustomEvents(ObjectEvents):
            foobar_action = EventSource(charm.ActionEvent)

        publisher = CustomEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.foobar_action, observer.callback_method)
        fake_script(self, 'action-get', "echo {}")

        with patch('sys.stderr', new_callable=io.StringIO):
            with patch('pdb.runcall') as mock:
                with patch.dict(os.environ, {'JUJU_ACTION_NAME': 'foobar'}):
                    publisher.foobar_action.emit()

        self.assertEqual(mock.call_count, 1)
        self.assertFalse(observer.called)

    def test_actions_are_interrupted(self):
        test_model = self.create_model()
        framework = self.create_framework(model=test_model)
        framework._juju_debug_at = {'hook'}

        class CustomEvents(ObjectEvents):
            foobar_action = EventSource(charm.ActionEvent)

        publisher = CustomEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.foobar_action, observer.callback_method)
        fake_script(self, 'action-get', "echo {}")

        with patch('sys.stderr', new_callable=io.StringIO):
            with patch('pdb.runcall') as mock:
                with patch.dict(os.environ, {'JUJU_ACTION_NAME': 'foobar'}):
                    publisher.foobar_action.emit()

        self.assertEqual(mock.call_count, 1)
        self.assertFalse(observer.called)

    def test_internal_events_not_interrupted(self):
        class MyNotifier(Object):
            """Generic notifier for the tests."""
            bar = EventSource(EventBase)

        framework = self.create_framework()
        framework._juju_debug_at = {'hook'}

        publisher = MyNotifier(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.bar, observer.callback_method)

        with patch('pdb.runcall') as mock:
            publisher.bar.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_envvar_mixed(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'foo', 'hook', 'all', 'whatever'}

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO):
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        self.assertEqual(mock.call_count, 1)
        self.assertFalse(observer.called)

    def test_no_registered_method(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'hook'}

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")

        with patch('pdb.runcall') as mock:
            publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertFalse(observer.called)

    def test_envvar_nohook(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'something-else'}

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'something-else'}):
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_envvar_missing(self):
        framework = self.create_framework()
        framework._juju_debug_at = set()

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('pdb.runcall') as mock:
            publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_welcome_message_not_multiple(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'hook'}

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO) as fake_stderr:
            with patch('pdb.runcall') as mock:
                publisher.install.emit()
                self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
                publisher.install.emit()
                self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
        self.assertEqual(mock.call_count, 2)
