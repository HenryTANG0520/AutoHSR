from contextlib import nullcontext
from pathlib import Path
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import windows_background as background
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, EmptyCapture, InputInterrupted
from autohsr.task_workflow import PAGE_TASK, WorkflowError, _params, task_spec
from autohsr.task_workflow_run import TaskWorkflowRunner
from autohsr.windows import Geometry


class BackgroundNavigationTests(TestCase):
    def test_scope_is_an_explicit_workflow_step_option(self):
        task = dict(task=PAGE_TASK, params=dict(target='daily_training', background=True))
        _, options = task_spec(Settings(), task, Path.cwd())
        self.assertIs(options['workflow_page_background'], True)
        for target in ('mail', 'battlepass', 'redemption_form', 'world'):
            with self.subTest(target=target), self.assertRaises(WorkflowError):
                _params(PAGE_TASK, dict(target=target, background=True))
        with self.assertRaises(AutomationError):
            Runner(Settings(), operation='daily', workflow_page_background=True)

    def test_background_step_does_not_consume_initial_foreground_wait(self):
        first = dict(id='guide', type='task', task=PAGE_TASK, params=dict(target='guide', background=True))
        next_step = dict(id='mail', type='task', task=PAGE_TASK, params=dict(target='mail'))
        factory = Mock()
        runner = TaskWorkflowRunner(Settings(), dict(version=1, name='fixture', steps=[first, next_step]),
                                    runner_factory=factory, wait_for_foreground=True)
        runner._make_child(first)
        runner._make_child(next_step)
        background_options, foreground_options = [call.kwargs for call in factory.call_args_list]
        self.assertIs(background_options['workflow_page_background'], True)
        self.assertNotIn('observation_wait_for_foreground', background_options)
        self.assertIs(foreground_options['observation_wait_for_foreground'], True)

    def window(self):
        window = background.BackgroundGameWindow.__new__(background.BackgroundGameWindow)
        window.hwnd = 100
        window._thread = (41, 50)
        window._post = Mock(return_value=True)
        window._checkpoint = Mock()
        window.emergency_pressed = Mock(return_value=False)
        window.current_window_key = Mock(return_value='private window key')
        window.guard = Mock()
        return window

    def test_guarded_mouse_sends_client_messages_and_releases_after_interruption(self):
        target = self.window()
        expected = Geometry(400, 200, 960, 540)
        still = Mock(side_effect=[None, None, InputInterrupted('pointer moved')])
        with patch.object(background, '_window_thread', return_value=target._thread), \
                patch.object(background, '_borrow_cursor', return_value=nullcontext(still)) as cursor, \
                patch.object(background.time, 'sleep'):
            with self.assertRaises(AutomationError):
                target.click(.5, .5, expected)
            target._post.assert_not_called()
            with self.assertRaises(InputInterrupted):
                target.click(.5, .5, expected, before_submit=lambda: None)
        cursor.assert_called_once_with((880, 470))
        self.assertEqual([call.args[1] for call in target._post.call_args_list], [0x200, 0x201, 0x202])
        self.assertEqual(target._post.call_args.args[-1], 480 | (270 << 16))

    def test_key_release_is_never_sent_to_a_replacement_window(self):
        target = self.window()
        expected = Geometry(400, 200, 960, 540)
        with patch.object(background, '_window_thread', side_effect=[target._thread, (42, 51)]), \
                patch.object(background.time, 'sleep'):
            with self.assertRaises(AutomationError):
                target.key('esc', expected=expected, before_submit=lambda: None)
        target._post.assert_called_once()
        self.assertEqual(target._post.call_args.args[:3], (100, 0x100, 0x1b))

    def test_cursor_restores_after_failure_but_never_over_user_movement(self):
        for user_moved in (False, True):
            with self.subTest(user_moved=user_moved):
                original, target, moved = (1, 1), (20, 20), (45, 50)
                read = [original, original, target, moved if user_moved else target]
                with patch.object(background, '_bind', return_value=Mock(return_value=True)) as bind, \
                        patch.object(background, '_cursor', side_effect=read), \
                        patch.object(background.user32, 'GetAsyncKeyState', return_value=0), \
                        patch.object(background.time, 'sleep'):
                    with self.assertRaises(AutomationError), background._borrow_cursor(target):
                        raise AutomationError('fixture interrupted')
                expected = [target] if user_moved else [target, original]
                self.assertEqual([call.args for call in bind.return_value.call_args_list], expected)

    def test_capture_timeout_does_not_start_a_second_worker(self):
        started, release = Event(), Event()

        def blocked(*args):
            started.set()
            release.wait(2)

        with patch.object(background, '_print_client', side_effect=blocked) as render, \
                patch.object(background, '_CAPTURE_TIMEOUT', .06):
            try:
                with self.assertRaises(EmptyCapture):
                    background._bounded_capture(100, (960, 540), lambda: None)
                self.assertTrue(started.is_set())
                with self.assertRaises(EmptyCapture):
                    background._bounded_capture(100, (960, 540), lambda: None)
                render.assert_called_once()
            finally:
                release.set()
                self.assertTrue(background._capture_gate.acquire(timeout=2))
                background._capture_gate.release()
