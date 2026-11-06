"""Formal achievements observation CLI with a synthetic foreground and Win32 sender."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import ctypes as C
from hashlib import sha256
import io
from itertools import count
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
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.daily_reward_observe import OPERATION, phone_achievement_target
from autohsr.desktop_daily_observe import observation_result
from autohsr.models import AutomationError, EmptyCapture, FocusLost, RunReport, Scene, Token
from autohsr.policy import guard_click
from autohsr.storage import hold_read_sources
from autohsr.tests.test_achievement_pages import gold_controls, label as achievement_label, overview
from autohsr.tests.test_daily_visa_pages import replay as replay_visa
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_redemption_pages import (form_scene, four_row_more_scene, more_scene, phone_scene,
                                               stamp, token, variant_phone_scene)
from autohsr.windows import GameWindow, Geometry, INPUT


ACCOUNT = Token('UID:135792468', .99, (.018, .957, .106, .985))
OTHER = Token('UID:246813579', .99, (.018, .957, .106, .985))


def phone(*extra, account=ACCOUNT):
    scene = fixture('phone_mail_icon')
    scene.tokens.extend((account, *extra))
    return scene


def destination(*extra, account=ACCOUNT):
    return Scene([account, Token('成就', .99, (.027, .032, .052, .058)), *extra], phone().image)


def achievement_page(*, account=ACCOUNT):
    return Scene([account, *overview()], phone().image)


def support_phone(*, menu=False, account=ACCOUNT):
    scene = more_scene() if menu else phone_scene()
    scene.image[95:125, 1775:1840] = 70
    stamp(scene.image, 'more', 1728, 100)
    if menu:
        scene.image[170:395, 1440:1720] = 49
    scene.tokens.append(account)
    return scene


def visa_page(*extra, account=ACCOUNT):
    return Scene([account, token('漫游签证', (50, 40, 155, 74)), *extra], phone_scene().image)


def visa_collection(name='collection', *, account=ACCOUNT):
    scene = replay_visa(name)
    return Scene([account, *scene.tokens], cv2.resize(scene.image, (1920, 1080)))


class _Window:
    hwnd = 1
    geometry = Geometry(0, 0, 1920, 1080)
    click = GameWindow.click
    send = GameWindow.send
    emergency_pressed = staticmethod(GameWindow.emergency_pressed)

    def __init__(self, frames):
        self.frames = iter(frames)
        self.frame = None
        self.guard = Mock(return_value=self.geometry)
        self.current_window_key = Mock(return_value='synthetic-window')
        self.focus = Mock(side_effect=AssertionError('must not focus a window'))
        for name in ('move', 'key', 'scroll', 'drag'):
            setattr(self, name, Mock(side_effect=AssertionError('no generic input')))

    def capture(self):
        self.frame = next(self.frames, EmptyCapture('blank test frame'))
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.frame.image.copy(), self.geometry

    def vision(self, confidence):
        def read(image, geometry):
            return Scene([token for token in self.frame.tokens if token.score >= confidence], image, geometry)

        return SimpleNamespace(read=read)


class DailyRewardObserveTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.config = self.root / 'config.json'
        Settings(overlay_logs=True, auto_launch=True, ocr_confidence=.93).save(self.config)
        self.original = self.config.read_bytes()

    def run_cli(self, frames, *, mode='achievements', entry_hook=None, before_native=None, short_at=None,
                foreground=True, exit_code=1, publication_hook=None):
        self.window = window = _Window(frames)
        if not foreground:
            window.guard.side_effect = FocusLost('synthetic window is not foreground')
        self.context = None
        self.events = []
        key_checks = []
        original_entry = Context.daily_reward_entry_input
        original_publish = Runner._save_run_report

        def entry(context, scene):
            self.context = context
            if entry_hook is not None:
                entry_hook(context, scene)
            return original_entry(context, scene)

        def key_state(_):
            key_checks.append(True)
            return before_native(len(key_checks)) if before_native else 0

        def publish(runner, directory, *args, **kwargs):
            return publication_hook(runner, directory, lambda: original_publish(runner, directory, *args, **kwargs))

        def submit(length, items, _size):
            events = C.cast(items, C.POINTER(INPUT))
            self.events.append(tuple((events[i].mi.dwFlags, events[i].mi.dx, events[i].mi.dy)
                                     for i in range(length)))
            return length - 1 if len(self.events) == short_at else length

        user32 = SimpleNamespace(GetAsyncKeyState=Mock(side_effect=key_state),
                                 GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__),
                                 SendInput=Mock(side_effect=submit))
        kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        ticks = count(100., .01)
        clock = SimpleNamespace(monotonic=lambda: next(ticks))
        output, logs = io.StringIO(), io.StringIO()
        with ExitStack() as stack:
            for target, value in (('autohsr.app.ROOT', self.root), ('autohsr.app.time', clock),
                                  ('autohsr.daily_reward_observe.time', clock), ('autohsr.redemption_pages.time', clock),
                                  ('autohsr.windows.user32', user32),
                                  ('autohsr.windows.kernel32', kernel),
                                  ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.DailyRewardQA.' + uuid4().hex)):
                stack.enter_context(patch(target, value))
            for target, kwargs in (
                    ('autohsr.app.C.get_last_error', dict(return_value=0)),
                    ('autohsr.app.threading.Thread', {}),
                    ('autohsr.app.is_elevated', dict(return_value=False)),
                    ('autohsr.app.find_game', dict(return_value=window)),
                    ('autohsr.app.Vision', dict(side_effect=window.vision)),
                    ('autohsr.notify_runtime.hooks', dict(side_effect=AssertionError('no notifications'))),
                    ('autohsr.overlay.OverlayService', dict(side_effect=AssertionError('no overlay'))),
                    ('autohsr.app.Runner._arm_hotkeys', {}),
                    ('autohsr.app.Runner._prepare_daily_game', dict(side_effect=AssertionError('no startup')))):
                stack.enter_context(patch(target, **kwargs))
            stack.enter_context(patch.object(Context, 'sleep', lambda ctx, _seconds: ctx.checkpoint()))
            stack.enter_context(patch.object(Context, 'daily_reward_entry_input', entry))
            if publication_hook is not None:
                stack.enter_context(patch.object(Runner, '_save_run_report', publish))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(logs))
            self.assertEqual(main(['--daily-reward-observe', mode, '--config', str(self.config)]), exit_code)
        report = json.loads(output.getvalue())
        self.assertEqual(report['operation'], OPERATION)
        self.assertEqual((report['stamina_spent'], report['stamina_pending'], report['battle_completed']), (0, 0, 0))
        self.assertEqual(report['daily_reward_observe']['page_verified'], exit_code == 0)
        self.assertEqual(json.loads((Path(report['run_dir']) / 'report.json').read_text('utf8')), report)
        self.assertEqual(self.config.read_bytes(), self.original)
        window.focus.assert_not_called()
        for name in ('move', 'key', 'scroll', 'drag'):
            getattr(window, name).assert_not_called()
        for value in (ACCOUNT.text[4:], OTHER.text[4:]):
            self.assertNotIn(value, output.getvalue() + logs.getvalue())
        return report

    def test_real_phone_fixture_submits_one_native_batch_and_saves_unverified_arrival(self):
        report = self.run_cli([phone(), phone(), phone(), destination(), destination()])
        self.assertEqual(report['status'], 'partial', report['error'])
        result = report['daily_reward_observe']
        self.assertEqual((result['entry_input'], result['destination_status']), ('sent', 'achievement_title_only'))
        self.assertEqual(len(self.events), 1)
        self.assertEqual([item[0] for item in self.events[0]], [0xC001, 0x0002, 0x0004])
        x, y = result['entry_point']
        self.assertAlmostEqual(x, .9018, places=4)
        self.assertAlmostEqual(y, .4981, places=4)
        self.assertEqual(result['submission_capture_sequence'], 3)
        frames = [*result['before_frames'], *result['after_frames']]
        self.assertEqual([row['capture_sequence'] for row in frames], [1, 2, 4, 5])
        directory = Path(report['run_dir'])
        for row in frames:
            self.assertEqual(sha256((directory / row['screenshot']).read_bytes()).hexdigest(), row['sha256'])
        intent = (directory / result['intent']).read_text('utf8')
        self.assertEqual(json.loads(intent)['sources'], result['before_frames'])
        self.assertNotIn(ACCOUNT.text[4:], intent)

    def test_achievement_overview_requires_independent_same_account_frames(self):
        report = self.run_cli([phone(), phone(), phone(), achievement_page(), achievement_page()], exit_code=0)
        result = report['daily_reward_observe']
        self.assertEqual((report['status'], result['entry_input'], result['destination_status']),
                         ('success', 'sent', 'achievement_overview'))
        self.assertEqual([row['capture_sequence'] for row in result['after_frames']], [4, 5])
        self.assertEqual(len(self.events), 1)

        for later in ([achievement_page(), destination()], [achievement_page(), achievement_page(account=OTHER)],
                      [achievement_page(), EmptyCapture('gap'), achievement_page()]):
            with self.subTest(later=len(later)):
                report = self.run_cli([phone(), phone(), phone(), *later])
                self.assertEqual(report['status'], 'partial')
                self.assertEqual(report['daily_reward_observe']['entry_input'], 'sent')
                self.assertEqual(len(self.events), 1)

    def test_stop_at_achievement_overview_publication_withdraws_success(self):
        report = self.run_cli([phone(), phone(), phone(), achievement_page(), achievement_page()],
                              before_native=lambda count: count == 3)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(report['daily_reward_observe']['entry_input'], 'sent')
        self.assertEqual(report['daily_reward_observe']['destination_status'], 'unknown')
        self.assertEqual(len(self.events), 1)

    def test_achievement_arrival_exposes_only_agreed_visible_bulk_control(self):
        button = achievement_label('一键领取奖励', .824, .897)
        pixels = cv2.resize(gold_controls(button), (1920, 1080))
        with_button = Scene([ACCOUNT, *overview(), button], pixels)
        before = [phone(), phone(), phone()]
        for ending, expected in (([with_button, with_button], True), ([with_button, achievement_page()], False)):
            with self.subTest(expected=expected):
                report = self.run_cli([*before, *ending], exit_code=0)
                result = report['daily_reward_observe']
                self.assertEqual(result.get('bulk_claim_visible', False), expected)
                self.assertEqual(len(self.events), 1)

    @unittest.skipUnless(os.name == 'nt', 'requires Windows file sharing')
    def test_achievement_report_sharing_retry_rechecks_after_frames(self):
        retries = []

        def publication(runner, directory, save):
            report_path = directory / 'report.json'
            report_path.write_text('{}', encoding='utf8')
            row = runner.report.daily_reward_observe['after_frames'][0]
            source = directory / row['screenshot']
            with ExitStack() as blocker:
                blocker.enter_context(hold_read_sources([report_path]))

                def on_retry(delay):
                    retries.append(delay)
                    blocker.close()
                    source.write_bytes(source.read_bytes() + b'replaced during sharing retry')

                with patch('autohsr.storage.time', SimpleNamespace(sleep=on_retry)):
                    return save()

        report = self.run_cli([phone(), phone(), phone(), achievement_page(), achievement_page()],
                              publication_hook=publication)
        self.assertEqual(len(retries), 1)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['daily_reward_observe']['entry_input'], 'sent')
        self.assertEqual(report['daily_reward_observe']['destination_status'], 'unknown')
        self.assertIn('证据在报告提交前已变化', report['error'])
        self.assertEqual(len(self.events), 1)

    def test_wrong_page_modal_duplicate_weak_account_or_gap_cannot_send(self):
        duplicate = Token('成就', .72, (.31, .32, .34, .35))
        modal = Token('确认', .73, (.43, .42, .48, .45))
        split = (Token('确', .88, (.43, .42, .45, .45)), Token('认', .89, (.456, .42, .477, .45)))
        weak_other = Token(OTHER.text, .68, OTHER.box)
        for frames in ([destination(), destination()], [phone(duplicate), phone(duplicate)],
                       [phone(modal), phone(modal)], [phone(*split), phone(*split)], [phone(weak_other), phone(weak_other)],
                       [phone(), EmptyCapture('gap'), phone()], [phone(), phone(account=OTHER)]):
            with self.subTest(frames=len(frames)):
                report = self.run_cli(frames)
                result = report['daily_reward_observe']
                self.assertEqual(result['entry_input'], 'not_sent')
                self.assertEqual(self.events, [])
                self.assertNotIn('intent', result)

    def test_third_capture_cannot_reuse_the_saved_intent_after_view_or_account_change(self):
        for changed in (destination(), phone(account=OTHER), phone(Token('切换账号', .99, (.43, .42, .52, .46)))):
            with self.subTest(changed=len(changed.tokens)):
                report = self.run_cli([phone(), phone(), changed])
                result = report['daily_reward_observe']
                self.assertEqual(result['entry_input'], 'not_sent')
                self.assertIn('intent', result)
                self.assertEqual(self.events, [])

    def test_background_window_and_last_native_stop_do_not_send(self):
        background = self.run_cli([phone(), phone(), phone()], foreground=False)
        self.assertEqual(background['daily_reward_observe']['entry_input'], 'not_sent')
        self.assertEqual(self.events, [])
        stopped = self.run_cli([phone(), phone(), phone()], before_native=lambda count: count == 2)
        self.assertEqual(stopped['status'], 'stopped')
        self.assertEqual(stopped['daily_reward_observe']['entry_input'], 'not_sent')
        self.assertEqual(self.events, [])

    def test_input_epoch_change_at_native_stop_check_cannot_submit(self):
        def pause(count):
            if count == 2:
                self.context.runner.toggle_pause()
            return 0

        report = self.run_cli([phone(), phone(), phone()], before_native=pause)
        self.assertEqual(report['daily_reward_observe']['entry_input'], 'not_sent')
        self.assertIn('输入代次已改变', report['error'])
        self.assertEqual(self.events, [])

    def test_evidence_swap_before_native_lock_stops_submission(self):
        def replace(context, _scene):
            reader = context.daily_reward_reader
            file = reader.directory / reader.record['before_frames'][0]['screenshot']
            file.write_bytes(file.read_bytes() + b'different bytes')

        report = self.run_cli([phone(), phone(), phone()], entry_hook=replace)
        self.assertEqual(report['daily_reward_observe']['entry_input'], 'not_sent')
        self.assertIn('截图在发送前已变化', report['error'])
        self.assertEqual(self.events, [])

    @unittest.skipUnless(os.name == 'nt', 'requires Windows file sharing')
    def test_real_ntfs_sources_are_locked_at_native_submit(self):
        blocked = []

        def try_replace(count):
            if count == 2:
                reader = self.context.daily_reward_reader
                for name in (reader.intent.name, *(row['screenshot'] for row in reader.record['before_frames'])):
                    replacement = reader.directory / 'replacement.tmp'
                    replacement.write_bytes(b'changed')
                    with self.assertRaises(PermissionError):
                        os.replace(replacement, reader.directory / name)
                    blocked.append(name)
            return 0

        report = self.run_cli([phone(), phone(), phone(), destination(), destination()], before_native=try_replace)
        self.assertEqual(len(blocked), 3)
        self.assertEqual(report['daily_reward_observe']['entry_input'], 'sent')
        self.assertEqual(len(self.events), 1)

    def test_existing_run_ledger_preflights_can_block_navigation(self):
        for target in ('autohsr.du_reward_store.preflight', 'autohsr.du_archive_store.preflight',
                       'autohsr.currency_wars_weekly_reward_store.RewardStore.preflight',
                       'autohsr.currency_wars_weekly.native_gate'):
            with (self.subTest(target=target), patch(target, side_effect=AutomationError('synthetic ledger block'))):
                report = self.run_cli([phone(), phone(), phone()])
                self.assertEqual(report['daily_reward_observe']['entry_input'], 'not_sent')
                self.assertEqual(report['error'], 'synthetic ledger block')
                self.assertIsNone(self.window.frame)
                self.assertEqual(self.events, [])

    def test_short_send_or_account_change_after_click_never_retry(self):
        short = self.run_cli([phone(), phone(), phone()], short_at=1)
        self.assertEqual(short['daily_reward_observe']['entry_input'], 'unconfirmed')
        self.assertEqual([len(batch) for batch in self.events], [3, 1])
        self.assertEqual(self.events[-1], ((4, 0, 0),))
        changed = self.run_cli([phone(), phone(), phone(), destination(account=OTHER)])
        self.assertEqual(changed['status'], 'partial')
        self.assertEqual(changed['daily_reward_observe']['entry_input'], 'sent')
        self.assertEqual(changed['daily_reward_observe']['after_frames'], [])
        self.assertEqual(len(self.events), 1)
        unchanged = self.run_cli([phone() for _ in range(9)])
        self.assertEqual(unchanged['daily_reward_observe']['destination_status'], 'phone_still_visible')
        self.assertEqual(len(self.events), 1)

    def test_support_route_reuses_verified_more_feedback_and_never_clicks_redemption(self):
        menu = [support_phone(menu=True) for _ in range(3)]
        frames = [support_phone() for _ in range(3)] + menu + [visa_page(), visa_page()]
        report = self.run_cli(frames, mode='support')
        self.assertEqual(report['status'], 'partial', report['error'])
        result = report['daily_reward_observe']
        self.assertEqual((result['mode'], result['entry_input'], result['destination_status']),
                         ('support', 'sent', 'support_title_only'))
        more, visa = (result['steps'][step] for step in ('open_more', 'open_support'))
        self.assertEqual((more['entry_input'], more['destination_status'], visa['entry_input']),
                         ('sent', 'more_menu_verified', 'sent'))
        self.assertEqual(len(self.events), 2)
        self.assertEqual([[item[0] for item in batch] for batch in self.events], [[0xC001, 0x0002, 0x0004]] * 2)
        self.assertAlmostEqual(more['entry_point'][0], .9091, places=4)
        self.assertEqual(visa['entry_point'], list(next(t.center for t in menu[0].tokens if t.text == '漫游签证')))
        self.assertEqual(more['after_frames'], visa['before_frames'])
        self.assertEqual([row['capture_sequence'] for row in more['after_frames']], [4, 5])
        self.assertEqual([more['submission_capture_sequence'], visa['submission_capture_sequence']], [3, 6])
        self.assertEqual([row['capture_sequence'] for row in visa['after_frames']], [7, 8])
        directory = Path(report['run_dir'])
        first_intent = (directory / more['intent']).read_bytes()
        final_intent = json.loads((directory / visa['intent']).read_bytes())
        self.assertEqual(final_intent['previous_intent'], dict(name=more['intent'], sha256=sha256(first_intent).hexdigest()))
        self.assertEqual(final_intent['sources'], more['after_frames'])

    def test_support_four_row_more_submits_only_the_visa_label(self):
        menu = four_row_more_scene()
        menu.tokens.append(ACCOUNT)
        frames = [support_phone() for _ in range(3)] + [menu] * 3 + [visa_page()] * 2
        report = self.run_cli(frames, mode='support')
        result = report['daily_reward_observe']
        self.assertEqual(result['steps']['open_more']['destination_status'], 'more_menu_verified')
        self.assertEqual(result['steps']['open_support']['entry_input'], 'sent')
        visa = next(token for token in menu.tokens if token.text == '漫游签证')
        self.assertEqual(result['steps']['open_support']['entry_point'], list(visa.center))
        self.assertEqual(len(self.events), 2)

    def test_support_collection_verifies_only_two_current_account_overview_frames(self):
        before = [support_phone() for _ in range(3)] + [support_phone(menu=True) for _ in range(3)]
        collection = visa_collection()
        report = self.run_cli([*before, collection, collection], mode='support', exit_code=0)
        result = report['daily_reward_observe']
        final_step = result['steps']['open_support']
        self.assertEqual(result['destination_status'], 'support_collection_overview')
        self.assertEqual(final_step['destination_status'], result['destination_status'])
        self.assertEqual([row['capture_sequence'] for row in final_step['after_frames']], [7, 8])
        self.assertEqual(len(self.events), 2)

        for ending in ([collection, visa_collection(account=OTHER)],
                       [collection, visa_collection('characters')],
                       [visa_collection('battle-record')] * 2):
            with self.subTest(ending=ending[1].tokens):
                report = self.run_cli([*before, *ending], mode='support')
                self.assertEqual(report['status'], 'partial')
                self.assertEqual(len(self.events), 2)

    def test_open_visa_read_keeps_the_two_navigation_steps_idle(self):
        for name, hint, section in (
                ('collection', 'support_collection_overview', 'unknown'),
                ('characters', 'support_character_overview', 'visible')):
            with self.subTest(name=name):
                report = self.run_cli([visa_collection(name)] * 2, mode='support', exit_code=0)
                result = report['daily_reward_observe']
                self.assertEqual(result['destination_status'], hint)
                self.assertEqual((result['entry_input'], result['support_section'], result['claimable_state'],
                                  result['claim_receipt_status']), ('not_sent', section, 'unknown', 'not_observed'))
                after = result['after_frames']
                self.assertEqual([(row['capture_sequence'], row['hint']) for row in after], [(1, hint), (2, hint)])
                self.assertNotEqual(after[0]['screenshot'], after[1]['screenshot'])
                for step in result['steps'].values():
                    self.assertEqual(step, dict(entry_input='not_sent', destination_status='unknown',
                                                before_frames=[], after_frames=[]))
                self.assertFalse(list(Path(report['run_dir']).glob('*intent.json')))
                self.assertEqual(self.events, [])
                title, detail = observation_result('support', report)
                if name == 'characters':
                    self.assertEqual((title, detail), ('漫游签证支援区已核实', '可领取状态待核对。到账状态待核对。'))
                else:
                    self.assertEqual(title, '漫游签证收集展示已核实')

    def test_phone_route_can_verify_the_support_section_without_changing_tabs(self):
        before = [support_phone() for _ in range(3)] + [support_phone(menu=True) for _ in range(3)]
        roles = [visa_collection('characters')] * 2
        report = self.run_cli(before + roles, mode='support', exit_code=0)
        result = report['daily_reward_observe']
        self.assertEqual(result['support_section'], 'visible')
        self.assertEqual(result['claimable_state'], 'unknown')
        self.assertEqual(result['claim_receipt_status'], 'not_observed')
        self.assertEqual(result['after_frames'], [])
        more, visa = (result['steps'][step] for step in ('open_more', 'open_support'))
        self.assertEqual(more['after_frames'], visa['before_frames'])
        self.assertEqual([row['capture_sequence'] for row in visa['after_frames']], [7, 8])
        self.assertEqual(len(self.events), 2)
        self.assertEqual(observation_result('support', report)[0], '漫游签证支援区已核实')

    def test_open_support_needs_adjacent_clean_same_account_frames_without_falling_back_to_navigation(self):
        role = visa_collection('characters')
        modal = visa_collection('characters')
        modal.tokens.append(Token('获得物品', .99, (.44, .28, .54, .33)))
        cases = ([role, visa_collection('characters', account=OTHER)],
                 [role, EmptyCapture('transition'), role],
                 [role, visa_collection('battle-record')],
                 [role] + [support_phone()] * 5,
                 [modal, modal])
        for frames in cases:
            with self.subTest(frames=[type(frame).__name__ for frame in frames]):
                report = self.run_cli(frames, mode='support')
                result = report['daily_reward_observe']
                self.assertEqual((result['entry_input'], result['support_section'], result['claimable_state'],
                                  result['claim_receipt_status']), ('not_sent', 'unknown', 'unknown', 'not_observed'))
                self.assertEqual(self.events, [])

    def test_open_support_publication_withdraws_on_stop_focus_or_changed_evidence(self):
        def lose_focus(_runner, _directory, save):
            self.window.guard.side_effect = FocusLost('synthetic focus loss at publication')
            return save()

        def change_evidence(runner, directory, save):
            first = runner.report.daily_reward_observe['after_frames'][0]
            path = directory / first['screenshot']
            path.write_bytes(path.read_bytes() + b'changed')
            return save()

        def change_fields(runner, _directory, save):
            runner.report.daily_reward_observe['claimable_state'] = 'available'
            return save()

        def stop_at_final_guard(runner, _directory, save):
            checks = count(1)

            def guard(_geometry):
                if next(checks) == 2:
                    runner.stop()
                return self.window.geometry

            self.window.guard.side_effect = guard
            return save()

        def change_epoch_at_final_guard(runner, _directory, save):
            checks = count(1)

            def guard(_geometry):
                if next(checks) == 2:
                    runner.input_epoch += 1
                return self.window.geometry

            self.window.guard.side_effect = guard
            return save()

        checks = (('stopped', dict(before_native=lambda count: count == 1)),
                  ('partial', dict(publication_hook=lose_focus)),
                  ('partial', dict(publication_hook=change_evidence)),
                  ('partial', dict(publication_hook=change_fields)),
                  ('stopped', dict(publication_hook=stop_at_final_guard)),
                  ('partial', dict(publication_hook=change_epoch_at_final_guard)))
        for status, options in checks:
            with self.subTest(options=options):
                report = self.run_cli([visa_collection('characters')] * 2, mode='support', **options)
                self.assertEqual(report['status'], status)
                result = report['daily_reward_observe']
                self.assertEqual((result['entry_input'], result['destination_status'], result['support_section'],
                                  result['claimable_state'], result['claim_receipt_status']),
                                 ('not_sent', 'unknown', 'unknown', 'unknown', 'not_observed'))
                self.assertEqual(self.events, [])
                self.assertNotIn('入口已发送', report['results'][-1]['detail'])

    def test_stop_at_visa_collection_publication_preserves_both_inputs(self):
        before = [support_phone() for _ in range(3)] + [support_phone(menu=True) for _ in range(3)]
        report = self.run_cli([*before, visa_collection(), visa_collection()], mode='support',
                              before_native=lambda count: count == 5)
        result = report['daily_reward_observe']
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(result['destination_status'], 'unknown')
        self.assertEqual(result['steps']['open_support']['destination_status'], 'unknown')
        self.assertEqual([step['entry_input'] for step in result['steps'].values()], ['sent', 'sent'])
        self.assertEqual(len(self.events), 2)

    def test_support_accepts_closed_more_variant_then_current_four_row_menu(self):
        closed, expanded = variant_phone_scene(), four_row_more_scene()
        closed.tokens.append(ACCOUNT)
        expanded.tokens.append(ACCOUNT)
        report = self.run_cli([closed] * 3 + [expanded] * 3 + [visa_page()] * 2, mode='support')
        result = report['daily_reward_observe']
        self.assertEqual(result['steps']['open_more']['destination_status'], 'more_menu_verified')
        self.assertEqual(result['steps']['open_support']['entry_input'], 'sent')
        self.assertAlmostEqual(result['steps']['open_more']['entry_point'][0], .913, places=3)
        self.assertEqual(len(self.events), 2)

    def test_support_does_not_retoggle_an_existing_or_ambiguous_more_menu(self):
        partial = support_phone()
        partial.tokens.append(token('漫游签证', (1510, 215, 1660, 250), score=.70))
        duplicate = support_phone()
        stamp(duplicate.image, 'more', 1660, 100)
        form = form_scene()
        form.tokens.append(ACCOUNT)
        for tag, scene in (('menu', support_phone(menu=True)), ('partial', partial), ('duplicate', duplicate), ('form', form)):
            with self.subTest(tag=tag):
                report = self.run_cli([scene] * 6, mode='support')
                result = report['daily_reward_observe']
                self.assertEqual(result['entry_input'], 'not_sent')
                self.assertEqual(self.events, [])
                self.assertNotIn('intent', result['steps']['open_more'])

    def test_support_stops_at_incomplete_conflicting_or_stale_more_feedback(self):
        absent = support_phone(menu=True)
        absent.tokens = [t for t in absent.tokens if t.text != '漫游签证']
        duplicate = support_phone(menu=True)
        duplicate.tokens.append(token('漫游签证', (1310, 215, 1460, 250), score=.68))
        wrong_column = support_phone(menu=True)
        wrong_column.tokens = [t for t in wrong_column.tokens if t.text != '兑换码']
        wrong_column.tokens.append(token('兑换码', (1275, 305, 1395, 340)))
        conflict = support_phone(menu=True)
        conflict.tokens.append(token('确认', (880, 640, 990, 676), score=.74))
        valid = support_phone(menu=True)
        changed = support_phone(menu=True, account=OTHER)
        for later in ([absent] * 6, [duplicate] * 6, [wrong_column] * 6, [conflict] * 6,
                      [valid, EmptyCapture('gap'), valid],
                      [changed], [valid, valid, support_phone()]):
            with self.subTest(observed_frames=len(later)):
                report = self.run_cli([support_phone() for _ in range(3)] + later, mode='support')
                result = report['daily_reward_observe']
                self.assertEqual(report['status'], 'partial', report['error'])
                self.assertEqual(result['steps']['open_more']['entry_input'], 'sent')
                self.assertEqual(result['steps']['open_support']['entry_input'], 'not_sent')
                self.assertEqual(len(self.events), 1)

    def test_support_short_send_distinguishes_the_two_steps(self):
        phone_frames = [support_phone() for _ in range(3)]
        menu_frames = [support_phone(menu=True) for _ in range(3)]
        for send in (1, 2):
            with self.subTest(send=send):
                report = self.run_cli(phone_frames + menu_frames, mode='support', short_at=send)
                result = report['daily_reward_observe']
                expected = ('unconfirmed', 'not_sent') if send == 1 else ('sent', 'unconfirmed')
                self.assertEqual(report['status'], 'partial')
                self.assertEqual(result['entry_input'], 'unconfirmed')
                self.assertEqual(tuple(step['entry_input'] for step in result['steps'].values()), expected)
                self.assertEqual([len(batch) for batch in self.events], [3] * send + [1])
                self.assertEqual(self.events[-1], ((4, 0, 0),))

    def test_support_previous_intent_cannot_change_before_second_input(self):
        def replace(context, _scene):
            reader = context.daily_reward_reader
            if reader.action == 'open_support':
                previous, _ = reader.more_intent
                previous.write_bytes(b'other intent')

        frames = [support_phone() for _ in range(3)] + [support_phone(menu=True) for _ in range(3)]
        report = self.run_cli(frames, mode='support', entry_hook=replace)
        self.assertEqual(report['daily_reward_observe']['steps']['open_support']['entry_input'], 'not_sent')
        self.assertIn('意图在发送前已变化', report['error'])
        self.assertEqual(len(self.events), 1)

    def test_support_stop_or_new_epoch_immediately_before_second_input_preserves_more(self):
        def pause(count):
            if count == 4:
                self.context.runner.toggle_pause()
            return 0

        frames = [support_phone() for _ in range(3)] + [support_phone(menu=True) for _ in range(3)]
        for gate, status in ((lambda count: count == 4, 'stopped'), (pause, 'partial')):
            with self.subTest(status=status):
                report = self.run_cli(frames, mode='support', before_native=gate)
                result = report['daily_reward_observe']
                self.assertEqual(report['status'], status)
                self.assertEqual(result['steps']['open_more']['destination_status'], 'more_menu_verified')
                self.assertEqual(result['steps']['open_support']['entry_input'], 'not_sent')
                self.assertEqual(len(self.events), 1)

    @unittest.skipUnless(os.name == 'nt', 'requires Windows file sharing')
    def test_support_native_second_submit_holds_both_intents_and_all_four_frames(self):
        blocked = []

        def try_replace(count):
            if count == 4:
                reader = self.context.daily_reward_reader
                for path, raw in reader._intents():
                    names = (path.name, *(row['screenshot'] for row in json.loads(raw)['sources']))
                    for name in names:
                        replacement = reader.directory / 'other.tmp'
                        replacement.write_bytes(b'other evidence')
                        with self.assertRaises(PermissionError):
                            os.replace(replacement, reader.directory / name)
                        blocked.append(name)
            return 0

        frames = [support_phone() for _ in range(3)] + [support_phone(menu=True) for _ in range(3)] + [visa_page()] * 2
        report = self.run_cli(frames, mode='support', before_native=try_replace)
        self.assertEqual(len(set(blocked)), 6)
        self.assertEqual(report['daily_reward_observe']['steps']['open_support']['entry_input'], 'sent')
        self.assertEqual(len(self.events), 2)

    def test_generic_input_and_incompatible_cli_options_stay_out_of_scope(self):
        scene = phone()
        target = phone_achievement_target(scene, .85)
        self.assertIsNotNone(target)
        with self.assertRaises(AutomationError):
            guard_click(scene, target)
        window = _Window(())
        context = Context(Runner(Settings(), operation=OPERATION), window, None)
        for action, args in ((context.click, (scene, target)), (context.key, ('esc',)),
                             (context.scroll, (1,)), (context.move, (scene, target.center)),
                             (context.drag, (scene, (.2, .3), (.4, .5))),
                             (context.daily_reward_entry_input, (scene,))):
            with self.assertRaises(AutomationError):
                action(*args)
        with self.assertRaises(ValueError):
            Runner(Settings(), operation=OPERATION, new_battle_run=True)
        with self.assertRaises(ValueError):
            Runner(Settings(), operation=OPERATION, daily_reward_mode='redemption')
        with self.assertRaises(ValueError):
            Runner(Settings(), daily_reward_mode='support')
        self.assertNotIn('daily_reward_observe', RunReport().to_dict())
        for option in ('--run', '--reward-only', '--new-battle-run', '--with-redemption'):
            with (self.subTest(option=option), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error,
                  patch.object(Settings, 'load', side_effect=AssertionError('invalid CLI must not load config'))):
                main(['--daily-reward-observe', 'achievements', option])
            self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
