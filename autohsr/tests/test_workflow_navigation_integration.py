"""Exercise the task-tree page adapter with a simulated Win32 foreground."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import ctypes
from hashlib import sha256
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
import numpy as np

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.daily_event_observe import read_event_installation
from autohsr.models import FocusLost, Scene, Token
from autohsr.selected_page_check import build_recipe
from autohsr.task_workflow_run import _bytes
from autohsr.tests.test_daily_event_navigation import activity_frame
from autohsr.tests.test_daily_event_pages import _odyssey
from autohsr.tests.test_daily_reward_observe import ACCOUNT, OTHER, _Window, phone, support_phone, visa_collection
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_redemption_pages import four_row_more_scene, variant_phone_scene
from autohsr.tests.test_task_workflow import condition, recipe, task
from autohsr.tests.test_workflow_navigation import badge, exact_guide_fixture, identified, world_hud
from autohsr.vision import Vision
from autohsr.windows import GameWindow, Geometry, INPUT
from autohsr.workflow_battlepass_tabs import small_battlepass_tab
from autohsr.workflow_navigation import WorkflowNavigation


def interrupted_page_report(runs_root):
    directory = runs_root / 'interrupted-page-check'
    directory.mkdir(parents=True)
    original = build_recipe(('mail', 'phone')).document
    raw = _bytes(original)
    (directory / 'workflow.json').write_bytes(raw)
    now = '2026-11-08T00:00:00+08:00'
    intent = dict(sequence=1, step='page_mail', type='task', task='workflow_open_page',
                  trail=[], status='running', started_at=now)
    result = dict(intent, status='failed', finished_at=now)
    events = (dict(event='intent', **intent), dict(event='result', **result))
    (directory / 'steps.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events), encoding='utf8')
    report = directory / 'report.json'
    report.write_bytes(_bytes(dict(operation='task_workflow', status='partial', report_saved=True,
        run_dir=str(directory), finished_at=now, workflow=dict(name=original['name'], selected_path=[],
        steps=[result], identity=dict(account_changed=False), definition_sha256=sha256(raw).hexdigest()))))
    return report


class WorkflowNavigationIntegrationTests(unittest.TestCase):
    def run_navigation(self, *, already_open=False, late_loss=False, target='mail', version='4.6.0',
                       start_in_list=False, late_version=False, from_odyssey=False, check_publication_lock=False,
                       lose_focus_on_installation_read=False, from_phone=False, battlepass_size=None,
                       lose_focus_after_geometry=0, duplicate_tab=False, first_escape_native_count=2,
                       upstream_screen=None, guide_overlay=None, overlay_on_target=False,
                       achievement_page_kind="overview", redemption_state="form", current_redemption_form=False,
                       visa_pages=None, expect_visa_stop=False, observe_only=False, resume=False):
        source = phone()
        mailbox = Scene([ACCOUNT, Token('邮箱', .99, (.03, .027, .072, .054)),
                         Token('暂无邮件', .99, (.28, .45, .34, .49))], source.image)
        guide_target = target in ('difficulty_guide', 'universe_guide', 'daily_training', 'survival_index')
        if target == 'messages':
            from autohsr.tests.test_daily_message_world import bright_sequence, world_pair

            pages = tuple(Scene(frame.tokens, cv2.resize(frame.image, (1920, 1080)))
                          for frame in (world_pair()[-1], bright_sequence()[-1]))
        elif target == 'redemption_form':
            from autohsr.tests.test_redemption_pages import (
                current_empty_form_scene, form_scene, four_row_more_scene, more_scene, result_scene, variant_phone_scene,
            )

            source, more = variant_phone_scene(), four_row_more_scene()
            form = current_empty_form_scene() if current_redemption_form else form_scene()
            more.image[:, :900] = 95
            if redemption_state == 'stale_phone':
                more = variant_phone_scene()
            elif redemption_state == 'unverified_more':
                source = more_scene()
                candidate = source.tokens[-1]
                source.tokens[-1] = Token(candidate.text, .78, candidate.box)
            elif redemption_state == 'purchase':
                form.tokens.append(Token('确认购买并支付', .79, (.40, .46, .60, .50)))
            elif redemption_state == 'result':
                form = result_scene()
            elif redemption_state == 'split_result':
                form.tokens.extend((Token('兑换', .86, (.43, .49, .47, .52)),
                                    Token('成功', .86, (.473, .49, .513, .52))))
            elif redemption_state == 'unknown_modal':
                form.tokens.append(Token('额外内容', .78, (.45, .55, .55, .58)))
            elif redemption_state == 'nonempty':
                form = form_scene('ExampleCode24', echo=False)
            for frame in (source, more, form):
                frame.tokens.append(ACCOUNT)
            pages = (source, more, form)
        elif target == 'achievement_overview':
            from autohsr.tests.test_achievement_pages import category_view
            from autohsr.tests.test_daily_reward_observe import achievement_page, destination

            achievement = achievement_page()
            if achievement_page_kind == 'title':
                achievement = destination()
            elif achievement_page_kind == 'category':
                achievement = Scene([ACCOUNT, *category_view()], achievement.image)
            elif achievement_page_kind == 'receipt_overlay':
                source = phone(Token('成就奖励', .78, (.473, .109, .527, .143)))
            elif achievement_page_kind == 'split_receipt_overlay':
                source = phone(Token('成就', .78, (.473, .109, .499, .143)),
                               Token('奖励', .78, (.501, .109, .527, .143)))
            pages = (source, achievement)
        elif target == 'visa_characters':
            pages = visa_pages or (visa_collection(), visa_collection('characters'))
        elif target == 'visa_collection':
            pages = visa_pages or (support_phone(), support_phone(menu=True), visa_collection())
        elif target == 'world':
            pages = (identified(fixture('mail_claimable')), identified(fixture('phone_mail_icon')), world_hud())
            if resume:
                pages = (world_hud() if already_open else source, source)
        elif guide_target:
            if target == 'universe_guide':
                pages = (exact_guide_fixture('difficulty_guide'), exact_guide_fixture('currency_guide'))
            else:
                path = Path(__file__).parent / 'fixtures' / 'du_runtime' / 'guide_universe_tab_clear.png'
                survival = identified(Vision(.65).read(cv2.imdecode(np.fromfile(path, np.uint8), 1)))
                if target == 'difficulty_guide':
                    pages = (survival, exact_guide_fixture('difficulty_guide'))
                else:
                    training = identified(fixture('daily_survival_badge'))
                    daily = Scene(training.tokens, cv2.resize(training.image, (1920, 1080)))
                    pages = (survival, daily) if target == 'daily_training' else (daily, survival)
            if guide_overlay is not None:
                source, destination = pages
                obscured = destination if overlay_on_target else source
                overlay = Scene([*obscured.tokens, guide_overlay], obscured.image)
                pages = (source, overlay) if overlay_on_target else (overlay, destination)
            if from_phone:
                pages = (identified(fixture('phone_mail_icon')), *pages)
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
        self.key_accepts = []
        first_release_rejected = False

        def frames():
            while True:
                yield pages[-1] if already_open and not resume else pages[min(completed_inputs + start_in_list, len(pages) - 1)]

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
            if plan_count == lose_focus_after_geometry:
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
            nonlocal completed_inputs, first_release_rejected
            events = ctypes.cast(events, ctypes.POINTER(INPUT))
            accepted = length
            if events[0].type == 1:
                self.assertEqual(length, 1)
                key = events[0].ki
                sent.append((key.dwFlags,))
                self.key_scans.append(key.wScan)
                if key.dwFlags == 0x08:
                    if not completed_inputs and first_escape_native_count == 0:
                        accepted = 0
                    else:
                        completed_inputs += 1
                elif completed_inputs == 1 and first_escape_native_count == 1 and not first_release_rejected:
                    first_release_rejected = True
                    accepted = 0
                self.key_accepts.append(accepted)
            else:
                sent.append(tuple(events[index].mi.dwFlags for index in range(length)))
                self.clicks.append((events[0].mi.dx / 65535, events[0].mi.dy / 65535))
                completed_inputs += 1
            return accepted

        def vision(confidence):
            engine = window.vision(confidence)
            if target == 'world' or guide_target:
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
            parameters = {'observe_only': True} if observe_only else {}
            document = recipe(task('page', 'workflow_open_page', target=target, **parameters),
                              dict(id='opened', type='if', condition=condition('page', 'page_verified', True),
                                   steps=[dict(id='verified', type='wait', seconds=0)]))
            if resume:
                workflow = interrupted_page_report(root / 'runs')
                original_report = workflow.read_bytes()
            elif upstream_screen is None:
                workflow.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
            else:
                source_yaml = root / 'source.yaml'
                source_yaml.write_text(f'name: 导航\nsteps: [{{type: switch_screen, target_screen: {upstream_screen}}}]\n',
                                       encoding='utf-8')
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as conversion_error:
                    self.assertEqual(main(['--task-workflow-convert-yaml', str(source_yaml),
                                           '--workflow-json-destination', str(workflow)]), 0, conversion_error.getvalue())
            user32 = SimpleNamespace(IsWindow=Mock(return_value=True), IsIconic=Mock(return_value=False),
                                     GetForegroundWindow=Mock(side_effect=lambda: foreground),
                                     GetAsyncKeyState=Mock(return_value=0), SendInput=Mock(side_effect=native_send),
                                     MapVirtualKeyW=Mock(side_effect=lambda key, _: key),
                                     GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: window.geometry.width,
                                                                        79: window.geometry.height}.__getitem__))
            for name, value in (
                ('autohsr.app.ROOT', root),
                ('autohsr.task_workflow_run.ROOT', root),
                ('autohsr.selected_page_check.ROOT', root),
                ('autohsr.windows.user32', user32),
                ('autohsr.windows.kernel32', SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())),
                ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.WorkflowNavigationQA.' + uuid4().hex),
            ):
                stack.enter_context(patch(name, value))
            if target != 'world' and not guide_target:
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
            command = '--screen-check-resume' if resume else '--task-workflow'
            code = main([command, str(workflow), '--config', str(config)])
            interrupted = (late_loss or late_version or lose_focus_on_installation_read
                           or lose_focus_after_geometry or version != '4.6.0'
                           or duplicate_tab or first_escape_native_count != 2 or guide_overlay is not None
                           or achievement_page_kind != 'overview' or redemption_state != 'form' or expect_visa_stop
                           or ((observe_only or resume) and not already_open))
            self.assertEqual(code, 1 if interrupted else 0, err.getvalue())
            if lose_focus_after_geometry:
                self.assertTrue(focus_changed)
            if check_publication_lock:
                self.assertEqual(installation_held, [True])
            self.assertEqual(config.read_bytes(), original)
            parent = json.loads(out.getvalue())
            if resume:
                self.assertEqual(workflow.read_bytes(), original_report)
                return sent, parent, None
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

    def test_redemption_yaml_stops_at_the_form_without_submit(self):
        for already_open, start_in_list, actions in (
                (False, False, ['open_redemption_more', 'open_redemption_form']),
                (False, True, ['open_redemption_form']), (True, False, [])):
            with self.subTest(start_in_list=start_in_list, already_open=already_open):
                sent, steps, native = self.run_navigation(target='redemption_form', upstream_screen='redemption',
                    already_open=already_open, start_in_list=start_in_list)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * len(actions))
                self.assertTrue(steps[0]['facts']['page_verified'])
                self.assertEqual([row['action'] for row in native['workflow_navigation']['actions']], actions)
                self.assertNotIn('redemption', steps[0]['facts'])

    def test_redemption_navigation_rejects_old_phone_payment_and_result_frames(self):
        for state, already_open, inputs in (
                ('stale_phone', False, 1), ('unverified_more', False, 0), ('purchase', False, 2),
                ('result', True, 0), ('split_result', True, 0)):
            with self.subTest(state=state):
                sent, steps, native = self.run_navigation(target='redemption_form', redemption_state=state,
                    already_open=already_open)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * inputs)
                self.assertNotIn('page_verified', steps[0]['facts'])
                self.assertFalse(native['workflow_navigation']['page_verified'])

    def test_current_empty_redemption_form_reaches_page_with_only_navigation_clicks(self):
        for already_open, actions in (
                (False, ['open_redemption_more', 'open_redemption_form']), (True, [])):
            with self.subTest(already_open=already_open):
                sent, steps, native = self.run_navigation(
                    target='redemption_form', current_redemption_form=True, already_open=already_open)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * len(actions))
                self.assertTrue(steps[0]['facts']['page_verified'])
                self.assertEqual([row['action'] for row in native['workflow_navigation']['actions']], actions)

    def test_redemption_form_rejects_unknown_modal_and_occupied_field(self):
        for state, already_open in (
                ('unknown_modal', False), ('purchase', True), ('split_result', True), ('nonempty', True)):
            with self.subTest(state=state):
                sent, steps, native = self.run_navigation(target='redemption_form', current_redemption_form=True,
                    redemption_state=state, already_open=already_open)
                self.assertEqual(sent, [] if already_open else [(0xC001, 0x0002, 0x0004)] * 2)
                self.assertNotIn('page_verified', steps[0]['facts'])
                record = native['workflow_navigation']
                self.assertFalse(record['page_verified'])
                if not already_open:
                    self.assertEqual([(row['input_status'], row['destination_status']) for row in record['actions']],
                                     [('sent', 'verified'), ('sent', 'unknown')])

    def test_achievement_yaml_navigation_only_opens_the_verified_overview(self):
        for already_open, inputs in ((False, 1), (True, 0)):
            with self.subTest(already_open=already_open):
                sent, steps, native = self.run_navigation(target='achievement_overview',
                    upstream_screen='achievement', already_open=already_open)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * inputs)
                self.assertTrue(steps[0]['facts']['page_verified'])
                record = native['workflow_navigation']
                self.assertEqual(len(record['actions']), inputs)
                if inputs:
                    self.assertEqual(record['actions'][0]['destination_page'], 'achievement_overview')

    def test_achievement_title_and_category_do_not_certify_arrival_or_retry(self):
        for kind, already_open, inputs in (('title', False, 1), ('category', True, 0),
                                            ('receipt_overlay', False, 0), ('split_receipt_overlay', False, 0)):
            with self.subTest(kind=kind):
                sent, steps, native = self.run_navigation(target='achievement_overview',
                    already_open=already_open, achievement_page_kind=kind)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * inputs)
                self.assertNotIn('page_verified', steps[0]['facts'])
                self.assertFalse(native['workflow_navigation']['page_verified'])

    def test_exact_guide_switches_imported_from_yaml_only_send_guide_controls(self):
        for upstream, target, from_phone, start, wanted in (
                ('guide4', 'difficulty_guide', True, 'survival_index', (.372, .201)),
                ('guide5', 'universe_guide', False, 'difficulty_guide', (.309, .190))):
            with self.subTest(target=target):
                sent, steps, native = self.run_navigation(target=target, from_phone=from_phone,
                                                          upstream_screen=upstream, check_publication_lock=True)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * (1 + from_phone))
                self.assertEqual(self.key_scans, [])
                self.assertTrue(steps[0]['facts']['page_verified'])
                rows = native['workflow_navigation']['actions']
                self.assertEqual(rows[-1]['source_page'], start)
                self.assertEqual(rows[-1]['destination_page'], target)
                self.assertAlmostEqual(self.clicks[-1][0], wanted[0], delta=.004)
                self.assertAlmostEqual(self.clicks[-1][1], wanted[1], delta=.004)

    def test_exact_guide_stops_on_route_blockers_before_the_tab_or_at_destination(self):
        for blocker in (badge('确认购买并支付', .50, .44), badge('跳过当前剧情', .50, .44),
                        badge('旅情事记', .09, .054)):
            for on_target in (False, True):
                with self.subTest(blocker=blocker.text, on_target=on_target):
                    sent, steps, native = self.run_navigation(target='universe_guide', from_phone=True,
                                                              guide_overlay=blocker, overlay_on_target=on_target)
                    self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * (1 + on_target))
                    self.assertEqual([step['step'] for step in steps], ['page'])
                    self.assertNotIn('page_verified', steps[0]['facts'])
                    record = native['workflow_navigation']
                    self.assertFalse(record['page_verified'])
                    self.assertEqual([(row['action'], row['input_status'], row['destination_status'])
                                      for row in record['actions']],
                                     ([('open_guide', 'sent', 'verified'), ('open_universe_guide', 'sent', 'unknown')]
                                      if on_target else [('open_guide', 'sent', 'unknown')]))

    def test_daily_guide_rejects_payment_and_story_overlays_on_the_route_or_current_page(self):
        for target in ('survival_index', 'daily_training'):
            sent, _, native = self.run_navigation(target=target, from_phone=True)
            self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * 2)
            self.assertTrue(native['workflow_navigation']['page_verified'])
            for blocker in (badge('确认购买并支付', .50, .44), badge('跳过当前剧情', .50, .44)):
                for current_page in (False, True):
                    with self.subTest(target=target, blocker=blocker.text, current_page=current_page):
                        sent, steps, native = self.run_navigation(target=target, from_phone=True,
                                                                  already_open=current_page, guide_overlay=blocker,
                                                                  overlay_on_target=current_page)
                        self.assertEqual(sent, [] if current_page else [(0xC001, 0x0002, 0x0004)])
                        self.assertEqual([step['step'] for step in steps], ['page'])
                        self.assertNotIn('page_verified', steps[0]['facts'])
                        record = native['workflow_navigation']
                        self.assertFalse(record['page_verified'])
                        self.assertEqual([(row['action'], row['input_status'], row['destination_status'])
                                          for row in record['actions']],
                                         [] if current_page else [('open_guide', 'sent', 'unknown')])

    def test_incoming_message_import_reaches_the_existing_notification_panel(self):
        sent, steps, native = self.run_navigation(target='messages', upstream_screen='incoming_message')
        self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)])
        self.assertEqual(self.key_scans, [])
        self.assertTrue(steps[0]['facts']['page_verified'])
        [row] = native['workflow_navigation']['actions']
        self.assertEqual((row['action'], row['destination_page']), ('open_messages', 'messages'))

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

    def test_world_observation_requires_already_open_world_and_sends_no_escape(self):
        for already_open in (False, True):
            with self.subTest(already_open=already_open):
                sent, steps, native = self.run_navigation(target='world', already_open=already_open, observe_only=True)
                self.assertEqual(sent, [])
                self.assertEqual(native['workflow_navigation']['actions'], [])
                self.assertIs(native['workflow_navigation']['page_verified'], already_open)
                self.assertEqual(steps[0]['status'], 'success' if already_open else 'failed')

    def test_cli_resumes_only_the_unstarted_page_after_the_world_check(self):
        sent, receipt, _ = self.run_navigation(target='world', already_open=True, resume=True)
        self.assertEqual(sent, [(0x08,), (0x0A,)])
        self.assertEqual(receipt, dict(status='success', pages=[
            dict(target='world', status='verified', actions_sent=0, actions_unconfirmed=0),
            dict(target='phone', status='verified', actions_sent=1, actions_unconfirmed=0),
        ]))
        sent, receipt, _ = self.run_navigation(target='world', resume=True)
        self.assertEqual(sent, [])
        self.assertEqual([(row['target'], row['status']) for row in receipt['pages']],
                         [('world', 'unknown'), ('phone', 'not_run')])

    def test_world_native_losing_focus_at_either_final_geometry_sends_no_new_escape(self):
        for plan_count, completed in ((2, 0), (4, 1)):
            with self.subTest(plan_count=plan_count):
                sent, steps, native = self.run_navigation(target='world', lose_focus_after_geometry=plan_count)
                self.assertEqual(sent, [(0x08,), (0x0A,)] * completed)
                self.assertNotIn('page_verified', steps[0]['facts'])
                record = native['workflow_navigation']
                self.assertFalse(record['page_verified'])
                self.assertEqual([row['destination_page'] for row in record['actions']], ['phone'][:completed])

    def test_world_native_requires_both_key_events_before_following_the_phone(self):
        for count, packets, accepts in ((0, [(0x08,)], [0]),
                                        (1, [(0x08,), (0x0A,), (0x0A,)], [1, 0, 1]),
                                        (2, [(0x08,), (0x0A,)] * 2, [1, 1, 1, 1])):
            with self.subTest(first_escape_events_accepted=count):
                sent, steps, native = self.run_navigation(target='world', first_escape_native_count=count)
                self.assertEqual((sent, self.key_accepts), (packets, accepts))
                self.assertEqual(self.key_scans, [0x1B] * len(packets))
                record = native['workflow_navigation']
                if count < 2:
                    self.assertNotIn('page_verified', steps[0]['facts'])
                    self.assertFalse(record['page_verified'])
                    [row] = record['actions']
                    self.assertEqual((row['source_page'], row['input_status'], row['destination_status']),
                                     ('mail', 'unconfirmed', 'unknown'))
                else:
                    self.assertTrue(record['page_verified'])
                    self.assertEqual([row['destination_page'] for row in record['actions']], ['phone', 'world'])

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

    def test_imported_visa_opens_collection_with_two_verified_clicks(self):
        sent, steps, native = self.run_navigation(target='visa_collection', upstream_screen='visa')
        self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * 2)
        self.assertAlmostEqual(self.clicks[0][0], .918, delta=.015)
        self.assertAlmostEqual(self.clicks[0][1], .107, delta=.015)
        visa = next(token for token in support_phone(menu=True).tokens if token.text == '漫游签证')
        self.assertAlmostEqual(self.clicks[1][0], visa.center[0], delta=.001)
        self.assertAlmostEqual(self.clicks[1][1], visa.center[1], delta=.001)
        self.assertTrue(steps[0]['facts']['page_verified'])
        result = native['workflow_navigation']
        self.assertEqual(result['target'], 'visa_collection')
        self.assertEqual(result['client_version'], '4.6.0')
        self.assertTrue(result['page_verified'])
        self.assertEqual(result['actions'], [
            dict(action='open_more', source_page='phone', expected_pages=['visa_more_menu'],
                 input_status='sent', destination_status='verified', destination_page='visa_more_menu'),
            dict(action='open_visa_collection', source_page='visa_more_menu', expected_pages=['visa_collection'],
                 input_status='sent', destination_status='verified', destination_page='visa_collection'),
        ])

    def test_visa_collection_already_open_is_zero_input(self):
        sent, steps, native = self.run_navigation(target='visa_collection', already_open=True)
        self.assertEqual(sent, [])
        self.assertTrue(steps[0]['facts']['page_verified'])
        self.assertEqual(native['workflow_navigation']['actions'], [])

    def test_visa_collection_accepts_the_four_row_menu_variant(self):
        closed, menu = variant_phone_scene(), four_row_more_scene()
        menu.image[100:380, 1490:1670] = 49
        for scene in (closed, menu):
            scene.tokens.append(ACCOUNT)
        sent, steps, native = self.run_navigation(target='visa_collection', visa_pages=(closed, menu, visa_collection()))
        self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * 2)
        self.assertTrue(steps[0]['facts']['page_verified'])
        self.assertAlmostEqual(self.clicks[0][0], 1753 / 1920, delta=.002)
        self.assertAlmostEqual(self.clicks[1][1], 140 / 1080, delta=.002)
        self.assertEqual([row['destination_page'] for row in native['workflow_navigation']['actions']],
                         ['visa_more_menu', 'visa_collection'])

    def test_visa_collection_rejects_unqualified_start_pages(self):
        for page in (support_phone(menu=True), visa_collection('characters'), world_hud()):
            with self.subTest(page=[token.text for token in page.tokens[:4]]):
                sent, steps, native = self.run_navigation(target='visa_collection', visa_pages=(page,),
                                                          expect_visa_stop=True)
                self.assertEqual(sent, [])
                self.assertNotIn('page_verified', steps[0]['facts'])
                self.assertEqual(native['workflow_navigation']['actions'], [])

    def test_visa_does_not_click_menu_entry_without_first_arrival(self):
        phone = support_phone()
        menu = support_phone(menu=True)
        claim = Token('支援奖励详情', .99, (.35, .25, .46, .30))
        loading = Token('正在加载', .99, (.35, .25, .46, .30))
        for pending in (phone, support_phone(menu=True, account=OTHER),
                        Scene([*menu.tokens, claim], menu.image), Scene([*menu.tokens, loading], menu.image)):
            with self.subTest(page=[token.text for token in pending.tokens[-2:]]):
                sent, steps, native = self.run_navigation(target='visa_collection', visa_pages=(phone, pending),
                                                          expect_visa_stop=True)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)])
                self.assertNotIn('page_verified', steps[0]['facts'])
                self.assertEqual(native['workflow_navigation']['actions'], [
                    dict(action='open_more', source_page='phone', expected_pages=['visa_more_menu'],
                         input_status='sent', destination_status='unknown')])

    def test_visa_does_not_count_character_showcase_or_popup_as_collection(self):
        collection = visa_collection()
        reconnect = Token('重新连接', .99, (.40, .25, .55, .30))
        for pending in (visa_collection('characters'), Scene([*collection.tokens, reconnect], collection.image)):
            with self.subTest(page=[token.text for token in pending.tokens[-2:]]):
                sent, steps, native = self.run_navigation(target='visa_collection',
                                                          visa_pages=(support_phone(), support_phone(menu=True), pending),
                                                          expect_visa_stop=True)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * 2)
                self.assertNotIn('page_verified', steps[0]['facts'])
                result = native['workflow_navigation']
                self.assertFalse(result['page_verified'])
                self.assertEqual([row['destination_status'] for row in result['actions']], ['verified', 'unknown'])
                self.assertEqual([row['input_status'] for row in result['actions']], ['sent', 'sent'])

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

    def test_opens_character_showcase_from_phone_without_an_extra_task(self):
        entry = (support_phone(), support_phone(menu=True))
        destination = visa_collection('characters')
        for pages, expected in (
            ((*entry, visa_collection(), destination), ['visa_more_menu', 'visa_collection', 'visa_characters']),
            ((*entry, destination), ['visa_more_menu', 'visa_characters']),
        ):
            with self.subTest(expected=expected):
                sent, steps, native = self.run_navigation(target='visa_characters', visa_pages=pages)
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * len(expected))
                self.assertTrue(steps[0]['facts']['page_verified'])
                actions = native['workflow_navigation']['actions']
                self.assertEqual([action['destination_page'] for action in actions], expected)
                self.assertTrue(all(action['destination_status'] == 'verified' for action in actions))

    def test_character_showcase_stops_on_unverified_visa_or_reward_overlay(self):
        collection = visa_collection()
        overlay = Token('支援奖励详情', .90, (.35, .25, .50, .30))
        for middle in (visa_collection('battle-record'), Scene([*collection.tokens, overlay], collection.image)):
            with self.subTest(tokens=[item.text for item in middle.tokens[-2:]]):
                sent, steps, native = self.run_navigation(target='visa_characters', expect_visa_stop=True,
                    visa_pages=(support_phone(), support_phone(menu=True), middle, visa_collection('characters')))
                self.assertEqual(sent, [(0xC001, 0x0002, 0x0004)] * 2)
                self.assertNotIn('page_verified', steps[0]['facts'])
                actions = native['workflow_navigation']['actions']
                self.assertEqual([action['destination_status'] for action in actions], ['verified', 'unknown'])

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
