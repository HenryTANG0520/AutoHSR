"""Exercise the task-tree page adapter with a simulated Win32 foreground."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.models import FocusLost, Scene, Token
from autohsr.tests.test_daily_reward_observe import ACCOUNT, _Window, phone
from autohsr.tests.test_task_workflow import condition, recipe, task


class WorkflowNavigationIntegrationTests(unittest.TestCase):
    def run_navigation(self, *, already_open=False, late_loss=False):
        source = phone()
        mailbox = Scene([ACCOUNT, Token('邮箱', .99, (.03, .027, .072, .054)),
                         Token('暂无邮件', .99, (.28, .45, .34, .49))], source.image)
        sent = []

        def frames():
            while True:
                yield mailbox if already_open or sent else source

        window = _Window(frames())
        previous = Runner._save_run_report

        def save(runner, *args, **kwargs):
            if late_loss:
                window.guard.side_effect = FocusLost('fake late focus loss')
            return previous(runner, *args, **kwargs)

        def native_send(length, events, _size):
            sent.append(tuple(events[index].mi.dwFlags for index in range(length)))
            return length

        out, err = io.StringIO(), io.StringIO()
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp).resolve()
            config = root / 'config.json'
            Settings(overlay_logs=True, auto_launch=True, ocr_confidence=.91).save(config)
            original = config.read_bytes()
            workflow = root / 'recipe.json'
            document = recipe(task('page', 'workflow_open_page', target='mail'),
                              dict(id='opened', type='if', condition=condition('page', 'page_verified', True),
                                   steps=[dict(id='verified', type='wait', seconds=0)]))
            workflow.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
            user32 = SimpleNamespace(GetAsyncKeyState=Mock(return_value=0), SendInput=Mock(side_effect=native_send),
                                     GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__))
            for name, value in (
                ('autohsr.app.ROOT', root),
                ('autohsr.task_workflow_run.ROOT', root),
                ('autohsr.windows.user32', user32),
                ('autohsr.windows.kernel32', SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())),
                ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.WorkflowNavigationQA.' + uuid4().hex),
            ):
                stack.enter_context(patch(name, value))
            for name, kwargs in (
                ('autohsr.app.C.get_last_error', dict(return_value=0)),
                ('autohsr.app.find_game', dict(return_value=window)),
                ('autohsr.app.is_elevated', dict(return_value=False)),
                ('autohsr.app.Vision', dict(side_effect=window.vision)),
                ('autohsr.app.Context.template', dict(return_value=None)),
                ('autohsr.app.Runner._arm_hotkeys', {}),
                ('autohsr.app.Runner._hotkeys', {}),
                ('autohsr.task_workflow_run.TaskWorkflowRunner._hotkeys', {}),
                ('autohsr.app.Runner._save_run_report', dict(new=save)),
                ('autohsr.app.Runner._prepare_daily_game', dict(side_effect=AssertionError('no launch or login'))),
                ('autohsr.overlay.OverlayService', dict(side_effect=AssertionError('no overlay'))),
            ):
                stack.enter_context(patch(name, **kwargs))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            code = main(['--task-workflow', str(workflow), '--config', str(config)])
            self.assertEqual(code, 1 if late_loss else 0, err.getvalue())
            self.assertEqual(config.read_bytes(), original)
            parent = json.loads(out.getvalue())
            entry = parent['workflow']['steps'][0]
            native_path = Path(entry['source']['path'])
            native = json.loads(native_path.read_text(encoding='utf-8'))
            self.assertNotIn('135792468', json.dumps(native))
            self.assertEqual((native['stamina_spent'], native['stamina_pending']), (0, 0))
            return sent, parent['workflow']['steps'], native

    def test_live_adapter_opens_mail_once_and_branches(self):
        sent, steps, native = self.run_navigation()
        self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)])
        self.assertEqual([step['step'] for step in steps], ['page', 'opened', 'verified'])
        self.assertTrue(steps[0]['facts']['page_verified'])
        self.assertTrue(native['workflow_navigation']['page_verified'])

    def test_current_mail_page_needs_no_input(self):
        sent, steps, native = self.run_navigation(already_open=True)
        self.assertEqual(sent, [])
        self.assertEqual(native['workflow_navigation']['actions'], [])
        self.assertTrue(steps[0]['facts']['page_verified'])

    def test_publication_focus_loss_preserves_sent_action_without_a_page_fact(self):
        sent, steps, native = self.run_navigation(late_loss=True)
        self.assertEqual(len(sent), 1)
        self.assertEqual([step['step'] for step in steps], ['page'])
        self.assertNotIn('page_verified', steps[0]['facts'])
        self.assertFalse(native['workflow_navigation']['page_verified'])
        self.assertEqual(len(native['workflow_navigation']['actions']), 1)
