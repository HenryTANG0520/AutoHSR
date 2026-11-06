"""Exercise the task-tree page adapter with a simulated Win32 foreground."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2

from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.models import FocusLost, Scene, Token
from autohsr.tests.test_daily_event_navigation import activity_frame
from autohsr.tests.test_daily_event_pages import _odyssey
from autohsr.tests.test_daily_reward_observe import ACCOUNT, _Window, phone
from autohsr.tests.test_task_workflow import condition, recipe, task


class WorkflowNavigationIntegrationTests(unittest.TestCase):
    def run_navigation(self, *, already_open=False, late_loss=False, target='mail', version='4.6.0',
                       start_in_list=False, late_version=False, from_odyssey=False, check_publication_lock=False):
        source = phone()
        mailbox = Scene([ACCOUNT, Token('邮箱', .99, (.03, .027, .072, .054)),
                         Token('暂无邮件', .99, (.28, .45, .34, .49))], source.image)
        if target in ('odyssey', 'reward_guide'):
            banner = activity_frame()
            banner.tokens.append(ACCOUNT)
            event = _odyssey()
            odyssey = Scene([ACCOUNT, *event.tokens], cv2.resize(event.image, (1920, 1080)))
            if target == 'reward_guide':
                from autohsr.tests.test_daily_reward_guide_pages import guide_scene

                destination = guide_scene(width=1920)
                destination.tokens.append(ACCOUNT)
                odyssey.image[:120] = banner.image[:120]
                odyssey.image[:, 45:246] = banner.image[:, 45:246]
                pages = (source, odyssey if from_odyssey else banner, destination)
            else:
                pages = (source, banner, odyssey)
        else:
            pages = (source, mailbox)
        sent = []
        self.clicks = []

        def frames():
            while True:
                yield pages[-1] if already_open else pages[min(len(sent) + start_in_list, len(pages) - 1)]

        window = _Window(frames())
        previous = Runner._save_run_report
        native_replace = Path.replace
        installation_held = []

        def replace_while_held(temporary, destination):
            if os.name == 'nt':
                with self.assertRaises(PermissionError), (game / 'config.ini').open('ab'):
                    pass
            installation_held.append(True)
            return native_replace(temporary, destination)

        def save(runner, *args, **kwargs):
            if late_loss:
                window.guard.side_effect = FocusLost('fake late focus loss')
            if late_version:
                (game / 'config.ini').write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
            if check_publication_lock and kwargs.get('workflow_navigation') is not None:
                with patch.object(Path, 'replace', new=replace_while_held):
                    return previous(runner, *args, **kwargs)
            return previous(runner, *args, **kwargs)

        def native_send(length, events, _size):
            sent.append(tuple(events[index].mi.dwFlags for index in range(length)))
            self.clicks.append((events[0].mi.dx / 65535, events[0].mi.dy / 65535))
            return length

        out, err = io.StringIO(), io.StringIO()
        with TemporaryDirectory() as tmp, ExitStack() as stack:
            root = Path(tmp).resolve()
            game = root / 'game'
            game.mkdir()
            executable = game / 'StarRail.exe'
            executable.touch()
            (game / 'config.ini').write_text(f'[General]\ngame_version={version}\n', encoding='utf8')
            window.current_executable = Mock(return_value=str(executable))
            config = root / 'config.json'
            Settings(overlay_logs=True, auto_launch=True, ocr_confidence=.91).save(config)
            original = config.read_bytes()
            workflow = root / 'recipe.json'
            document = recipe(task('page', 'workflow_open_page', target=target),
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
            self.assertEqual(code, 1 if late_loss or late_version or version != '4.6.0' else 0, err.getvalue())
            if check_publication_lock:
                self.assertEqual(installation_held, [True])
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

    def test_opens_odyssey_from_phone_using_only_the_left_activity_banner(self):
        sent, steps, native = self.run_navigation(target='odyssey')
        self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * 2)
        phone, banner = self.clicks
        self.assertTrue(.670 <= phone[0] <= .729 and .476 <= phone[1] <= .520)
        self.assertTrue(.035 <= banner[0] <= .118 and .27 <= banner[1] <= .32)
        result = native['workflow_navigation']
        self.assertEqual(result['client_version'], '4.6.0')
        self.assertEqual([row['action'] for row in result['actions']], ['open_journey_events', 'open_odyssey'])
        self.assertEqual([row['destination_page'] for row in result['actions']], ['activity_list', 'odyssey'])
        self.assertTrue(steps[0]['facts']['page_verified'])

    def test_odyssey_already_open_or_unsupported_version_never_sends_input(self):
        for version in ('4.6.0', '4.7.0'):
            with self.subTest(version=version):
                sent, _, native = self.run_navigation(already_open=True, target='odyssey', version=version)
                self.assertEqual(sent, [])
                self.assertEqual(native['workflow_navigation']['page_verified'], version == '4.6.0')

    def test_from_current_activity_list_late_installation_change_keeps_only_the_sent_action(self):
        sent, steps, native = self.run_navigation(target='odyssey', start_in_list=True, late_version=True)
        self.assertEqual(len(sent), 1)
        self.assertNotIn('page_verified', steps[0]['facts'])
        result = native['workflow_navigation']
        self.assertFalse(result['page_verified'])
        self.assertEqual(result['actions'][0]['action'], 'open_odyssey')
        self.assertEqual(result['actions'][0]['input_status'], 'sent')

    def test_reward_guide_opens_from_phone_or_odyssey_without_using_a_reward_row(self):
        for start in ('phone', 'odyssey'):
            with self.subTest(start=start):
                sent, steps, native = self.run_navigation(target='reward_guide', start_in_list=start == 'odyssey',
                                                           from_odyssey=start == 'odyssey')
                clicks = 2 if start == 'phone' else 1
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * clicks)
                x, y = self.clicks[-1]
                self.assertTrue(.20 <= x <= .28 and .037 <= y <= .09)
                result = native['workflow_navigation']
                self.assertEqual(result['actions'][-1]['action'], 'open_reward_guide')
                self.assertEqual(result['actions'][-1]['source_page'],
                                 'activity_list' if start == 'phone' else 'odyssey')
                self.assertEqual(result['actions'][-1]['destination_page'], 'reward_guide')
                self.assertTrue(steps[0]['facts']['page_verified'])

    def test_already_open_reward_guide_is_verified_with_no_input(self):
        sent, steps, native = self.run_navigation(target='reward_guide', already_open=True, check_publication_lock=True)
        self.assertEqual(sent, [])
        self.assertEqual(native['workflow_navigation']['actions'], [])
        self.assertTrue(steps[0]['facts']['page_verified'])
