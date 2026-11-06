"""Exercise the task-tree page adapter with a simulated Win32 foreground."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import ctypes
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

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.daily_event_observe import read_event_installation
from autohsr.models import FocusLost, Scene, Token
from autohsr.tests.test_daily_event_navigation import activity_frame
from autohsr.tests.test_daily_event_pages import _odyssey
from autohsr.tests.test_daily_reward_observe import ACCOUNT, _Window, phone, visa_collection
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_task_workflow import condition, recipe, task
from autohsr.tests.test_workflow_navigation import identified, world_hud
from autohsr.vision import Vision
from autohsr.windows import GameWindow, Geometry, INPUT
from autohsr.workflow_battlepass_tabs import small_battlepass_tab
from autohsr.workflow_navigation import WorkflowNavigation


class WorkflowNavigationIntegrationTests(unittest.TestCase):
    def run_navigation(self, *, already_open=False, late_loss=False, target='mail', version='4.6.0',
                       start_in_list=False, late_version=False, from_odyssey=False, check_publication_lock=False,
                       lose_focus_on_installation_read=False, from_phone=False, battlepass_size=None,
                       lose_focus_after_geometry=False, duplicate_tab=False):
        source = phone()
        mailbox = Scene([ACCOUNT, Token('邮箱', .99, (.03, .027, .072, .054)),
                         Token('暂无邮件', .99, (.28, .45, .34, .49))], source.image)
        if target == 'messages':
            from autohsr.tests.test_daily_message_world import bright_sequence, world_pair

            pages = tuple(Scene(frame.tokens, cv2.resize(frame.image, (1920, 1080)))
                          for frame in (world_pair()[-1], bright_sequence()[-1]))
        elif target == 'visa_characters':
            pages = (visa_collection(), visa_collection('characters'))
        elif target == 'world':
            pages = (identified(fixture('mail_claimable')), identified(fixture('phone_mail_icon')), world_hud())
        elif target in ('battlepass_rewards', 'battlepass_tasks'):
            rewards = identified(fixture('bp_rewards_claimable'))
            tasks = identified(fixture('bp_tasks_claimable'))
            pages = (tasks, rewards) if target == 'battlepass_rewards' else (rewards, tasks)
            if duplicate_tab:
                from autohsr.tests.test_workflow_navigation import duplicate_battlepass_tab

                pages = (duplicate_battlepass_tab(pages[0], target.removeprefix('battlepass_')), pages[1])
            if from_phone:
                pages = (identified(fixture('phone_mail_icon')), *pages)
            if battlepass_size is not None:
                vision = Vision(.65)
                pages = tuple(identified(vision.read(cv2.resize(page.image, battlepass_size, interpolation=cv2.INTER_AREA)))
                              for page in pages)
        elif target in ('odyssey', 'reward_guide'):
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
        completed_inputs = 0
        self.clicks = []
        self.key_scans = []

        def frames():
            while True:
                yield pages[-1] if already_open else pages[min(completed_inputs + start_in_list, len(pages) - 1)]

        window = _Window(frames())
        if target == 'world':
            window.key = GameWindow.key.__get__(window)
        if battlepass_size is not None:
            window.geometry = Geometry(0, 0, *battlepass_size)
            window.guard.return_value = window.geometry
        window.require_foreground = windows.GameWindow.require_foreground.__get__(window)
        foreground = window.hwnd
        plan_count = 0
        focus_changed = False
        original_plan = WorkflowNavigation._planned
        if lose_focus_after_geometry:
            window.guard = windows.GameWindow.guard.__get__(window)

        def plan(navigation, pair):
            nonlocal plan_count
            action = original_plan(navigation, pair)
            plan_count += 1
            return action

        def geometry(_hwnd):
            nonlocal foreground, focus_changed
            if plan_count == 2:
                foreground = window.hwnd + 1
                focus_changed = True
            return window.geometry

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
            if lose_focus_on_installation_read and kwargs.get('workflow_navigation') is not None:
                def read_then_lose_focus(game_window):
                    installation = read_event_installation(game_window)
                    game_window.guard.side_effect = FocusLost('focus lost at the end of the installation read')
                    return installation

                with patch('autohsr.workflow_navigation.read_event_installation', side_effect=read_then_lose_focus):
                    return previous(runner, *args, **kwargs)
            if check_publication_lock and kwargs.get('workflow_navigation') is not None:
                with patch.object(Path, 'replace', new=replace_while_held):
                    return previous(runner, *args, **kwargs)
            return previous(runner, *args, **kwargs)

        def native_send(length, events, _size):
            nonlocal completed_inputs
            events = ctypes.cast(events, ctypes.POINTER(INPUT))
            if events[0].type == 1:
                self.assertEqual(length, 1)
                key = events[0].ki
                sent.append((key.dwFlags,))
                self.key_scans.append(key.wScan)
                if key.dwFlags == 0x08:
                    completed_inputs += 1
            else:
                sent.append(tuple(events[index].mi.dwFlags for index in range(length)))
                self.clicks.append((events[0].mi.dx / 65535, events[0].mi.dy / 65535))
                completed_inputs += 1
            return length

        def vision(confidence):
            engine = window.vision(confidence)
            if target == 'world':
                engine.template = Vision.__new__(Vision).template
            return engine

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
            user32 = SimpleNamespace(IsWindow=Mock(return_value=True), IsIconic=Mock(return_value=False),
                                     GetForegroundWindow=Mock(side_effect=lambda: foreground),
                                     GetAsyncKeyState=Mock(return_value=0), SendInput=Mock(side_effect=native_send),
                                     MapVirtualKeyW=Mock(side_effect=lambda key, _: key),
                                     GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: window.geometry.width,
                                                                        79: window.geometry.height}.__getitem__))
            for name, value in (
                ('autohsr.app.ROOT', root),
                ('autohsr.task_workflow_run.ROOT', root),
                ('autohsr.windows.user32', user32),
                ('autohsr.windows.kernel32', SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())),
                ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.WorkflowNavigationQA.' + uuid4().hex),
            ):
                stack.enter_context(patch(name, value))
            if target != 'world':
                stack.enter_context(patch('autohsr.app.Context.template', return_value=None))
            for name, kwargs in (
                ('autohsr.app.C.get_last_error', dict(return_value=0)),
                ('autohsr.app.find_game', dict(return_value=window)),
                ('autohsr.app.is_elevated', dict(return_value=False)),
                ('autohsr.app.Vision', dict(side_effect=vision)),
                ('autohsr.app.Runner._arm_hotkeys', {}),
                ('autohsr.app.Runner._hotkeys', {}),
                ('autohsr.task_workflow_run.TaskWorkflowRunner._hotkeys', {}),
                ('autohsr.app.Runner._save_run_report', dict(new=save)),
                ('autohsr.app.Runner._prepare_daily_game', dict(side_effect=AssertionError('no launch or login'))),
                ('autohsr.overlay.OverlayService', dict(side_effect=AssertionError('no overlay'))),
            ):
                stack.enter_context(patch(name, **kwargs))
            if lose_focus_after_geometry:
                stack.enter_context(patch.object(WorkflowNavigation, '_planned', new=plan))
                stack.enter_context(patch.object(windows, 'geometry', side_effect=geometry))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            code = main(['--task-workflow', str(workflow), '--config', str(config)])
            interrupted = (late_loss or late_version or lose_focus_on_installation_read
                           or lose_focus_after_geometry or version != '4.6.0' or duplicate_tab)
            self.assertEqual(code, 1 if interrupted else 0, err.getvalue())
            if lose_focus_after_geometry:
                self.assertTrue(focus_changed)
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

    def test_world_native_workflow_uses_only_existing_escape_from_verified_sources(self):
        for start, already_open, count in ((0, False, 2), (1, False, 1), (0, True, 0)):
            with self.subTest(start=start, already_open=already_open):
                sent, steps, native = self.run_navigation(target='world', start_in_list=start,
                                                          already_open=already_open, check_publication_lock=True)
                self.assertEqual(sent, [(0x08,), (0x0A,)] * count)
                self.assertEqual(self.key_scans, [0x1B] * 2 * count)
                self.assertEqual(self.clicks, [])
                self.assertTrue(steps[0]['facts']['page_verified'])
                record = native['workflow_navigation']
                self.assertEqual(record['target'], 'world')
                self.assertTrue(record['page_verified'])
                self.assertEqual([row['destination_page'] for row in record['actions']], ['phone', 'world'][2-count:])

    def test_world_native_late_focus_loss_preserves_the_escape_receipt(self):
        sent, steps, native = self.run_navigation(target='world', start_in_list=True, late_loss=True)
        self.assertEqual(sent, [(0x08,), (0x0A,)])
        self.assertNotIn('page_verified', steps[0]['facts'])
        record = native['workflow_navigation']
        self.assertFalse(record['page_verified'])
        [row] = record['actions']
        self.assertEqual((row['input_status'], row['destination_page']), ('sent', 'world'))

    def test_battlepass_exact_targets_click_only_opposite_tab_and_verify_current_page(self):
        for source, target, center_x in (('battlepass_tasks', 'battlepass_rewards', .45),
                                         ('battlepass_rewards', 'battlepass_tasks', .50)):
            for already_open in (False, True):
                with self.subTest(target=target, already_open=already_open):
                    sent, steps, native = self.run_navigation(target=target, already_open=already_open)
                    self.assertTrue(steps[0]['facts']['page_verified'])
                    record = native['workflow_navigation']
                    self.assertEqual(record['target'], target)
                    self.assertEqual(record['client_version'], '4.6.0')
                    if already_open:
                        self.assertEqual((sent, record['actions']), ([], []))
                    else:
                        self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)])
                        x, y = self.clicks[0]
                        self.assertAlmostEqual(x, center_x, delta=.004)
                        self.assertAlmostEqual(y, .059, delta=.004)
                        self.assertEqual(record['actions'], [dict(action='open_' + target, source_page=source,
                            expected_pages=[target], input_status='sent', destination_status='verified',
                            destination_page=target)])

    def test_battlepass_from_phone_waits_for_the_actual_first_tab_before_switching(self):
        sent, steps, native = self.run_navigation(target='battlepass_tasks', from_phone=True,
                                                  check_publication_lock=True)
        self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * 2)
        actions = native['workflow_navigation']['actions']
        self.assertEqual([(row['action'], row['destination_page']) for row in actions],
                         [('open_battlepass', 'battlepass_rewards'), ('open_battlepass_tasks', 'battlepass_tasks')])
        self.assertTrue(steps[0]['facts']['page_verified'])
        for (x, y), (want_x, want_y) in zip(self.clicks, ((.766, .618), (.50, .059))):
            self.assertAlmostEqual(x, want_x, delta=.004)
            self.assertAlmostEqual(y, want_y, delta=.004)

    def test_battlepass_wrong_client_sends_nothing(self):
        sent, steps, native = self.run_navigation(target='battlepass_rewards', version='4.7.0')
        self.assertEqual(sent, [])
        self.assertEqual(native['workflow_navigation']['actions'], [])
        self.assertFalse(native['workflow_navigation']['page_verified'])
        self.assertNotIn('page_verified', steps[0]['facts'])

    def test_small_battlepass_formal_workflow_switches_when_the_primary_template_misses(self):
        for size, target, expected_x in (((960, 540), 'battlepass_tasks', .50),
                                          ((1280, 720), 'battlepass_rewards', .45)):
            with self.subTest(size=size, target=target), patch('autohsr.workflow_battlepass_tabs.small_battlepass_tab',
                                                             wraps=small_battlepass_tab) as fallback:
                sent, steps, native = self.run_navigation(target=target, battlepass_size=size,
                                                          check_publication_lock=True)
                fallback.assert_called()
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)])
                self.assertAlmostEqual(self.clicks[0][0], expected_x, delta=.004)
                self.assertAlmostEqual(self.clicks[0][1], .059, delta=.004)
                self.assertTrue(steps[0]['facts']['page_verified'])
                [action] = native['workflow_navigation']['actions']
                self.assertEqual((action['input_status'], action['destination_page']), ('sent', target))

    def test_battlepass_losing_foreground_during_final_geometry_sends_nothing(self):
        sent, steps, native = self.run_navigation(target='battlepass_rewards', lose_focus_after_geometry=True)
        self.assertEqual(sent, [])
        self.assertEqual(native['workflow_navigation']['actions'], [])
        self.assertFalse(native['workflow_navigation']['page_verified'])
        self.assertNotIn('page_verified', steps[0]['facts'])

    def test_exact_battlepass_duplicate_standard_peaks_stop_before_native_input(self):
        for target in ('battlepass_tasks', 'battlepass_rewards'):
            with self.subTest(target=target), patch('autohsr.workflow_battlepass_tabs.small_battlepass_tab') as fallback:
                sent, steps, native = self.run_navigation(target=target, duplicate_tab=True)
                self.assertEqual(sent, [])
                self.assertIn('多个匹配位置', native['error'])
                self.assertEqual(native['workflow_navigation']['actions'], [])
                self.assertNotIn('page_verified', steps[0]['facts'])
                fallback.assert_not_called()

    def test_messages_uses_one_world_input_and_no_input_when_already_open(self):
        for already_open, actions in ((False, 1), (True, 0)):
            with self.subTest(already_open=already_open):
                sent, steps, native = self.run_navigation(
                    target='messages', already_open=already_open, check_publication_lock=True)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * actions)
                self.assertTrue(steps[0]['facts']['page_verified'])
                record = native['workflow_navigation']
                self.assertEqual((record['target'], record['client_version'], len(record['actions'])),
                                 ('messages', '4.6.0', actions))
                if actions:
                    self.assertEqual(record['actions'][0]['action'], 'open_messages')
                    self.assertEqual(record['actions'][0]['destination_page'], 'messages')

    def test_messages_late_loss_keeps_the_sent_input_and_revokes_arrival(self):
        sent, steps, native = self.run_navigation(target='messages', lose_focus_on_installation_read=True)
        self.assertEqual(len(sent), 1)
        self.assertNotIn('page_verified', steps[0]['facts'])
        result = native['workflow_navigation']
        self.assertFalse(result['page_verified'])
        self.assertEqual(result['actions'][0]['input_status'], 'sent')

    def test_opens_character_showcase_with_one_explicit_task_and_no_other_input(self):
        sent, steps, native = self.run_navigation(target='visa_characters', check_publication_lock=True)
        self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)])
        tab = next(token for token in visa_collection().tokens if token.text == '角色展示')
        self.assertAlmostEqual(self.clicks[0][0], tab.center[0], delta=.001)
        self.assertAlmostEqual(self.clicks[0][1], tab.center[1], delta=.001)
        result = native['workflow_navigation']
        self.assertEqual(result['client_version'], '4.6.0')
        self.assertTrue(result['page_verified'])
        self.assertTrue(steps[0]['facts']['page_verified'])
        self.assertEqual(result['actions'], [
            dict(action='open_visa_characters', source_page='visa_collection', expected_pages=['visa_characters'],
                 input_status='sent', destination_status='verified', destination_page='visa_characters')])

    def test_character_switch_already_open_is_zero_input_and_wrong_version_stops(self):
        for version, verified in (('4.6.0', True), ('4.7.0', False)):
            with self.subTest(version=version):
                sent, steps, native = self.run_navigation(target='visa_characters', already_open=True, version=version)
                self.assertEqual(sent, [])
                self.assertEqual(native['workflow_navigation']['actions'], [])
                self.assertIs(native['workflow_navigation']['page_verified'], verified)
                self.assertIs(steps[0]['facts'].get('page_verified', False), verified)

    def test_character_switch_preserves_only_the_sent_action_on_late_focus_or_version_change(self):
        for overrides in (dict(late_loss=True), dict(late_version=True)):
            with self.subTest(overrides=overrides):
                sent, steps, native = self.run_navigation(target='visa_characters', **overrides)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)])
                result = native['workflow_navigation']
                self.assertFalse(result['page_verified'])
                self.assertNotIn('page_verified', steps[0]['facts'])
                self.assertEqual([action['input_status'] for action in result['actions']], ['sent'])

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

    def test_reward_guide_publication_requires_foreground_after_the_last_installation_read(self):
        sent, steps, native = self.run_navigation(target='reward_guide', lose_focus_on_installation_read=True)
        self.assertEqual(len(sent), 2)
        self.assertFalse(native['workflow_navigation']['page_verified'])
        self.assertNotIn('page_verified', steps[0]['facts'])
