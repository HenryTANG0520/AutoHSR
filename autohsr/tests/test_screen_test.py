"""Current-page observation with scrubbed fixtures and a noninteractive window."""

from contextlib import ExitStack
from itertools import count
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
from unittest import TestCase, skipUnless
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PIL import Image

from autohsr import screen_test
from autohsr.models import AutomationError, EmptyCapture, FocusLost, RunReport, Scene, Stopped
from autohsr.screenshot_tool import selection
from autohsr.storage import hold_read_sources, replace_file
from autohsr.tests.test_achievement_pages import category_view, gold_controls, label, overview, receipt_rows
from autohsr.tests.test_daily_reward_observe import ACCOUNT, OTHER, phone
from autohsr.tests.test_daily_reward_guide_pages import guide_scene
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_workflow_navigation import Context, badge, battlepass, identified, world
from autohsr.vision import Vision


_GUIDE_VIEWPORT = dict(visible_section='ongoing', content_box=[378, 342, 1404, 945], frame_size=[1920, 1080])


def achievement_frame(tokens, *buttons):
    image = gold_controls(*buttons)
    image[230:360, 430:720] = 145
    return Scene([ACCOUNT, *tokens, *buttons], image)


class ReadOnlyContext(Context):
    def __init__(self, frames):
        super().__init__('phone', frames)
        self.report = RunReport(operation=screen_test.OPERATION)
        self.vision.confidence = .65
        self.runner.stop = Mock(side_effect=lambda: setattr(self.runner, 'stop_requested', True))
        self.window.emergency_pressed = Mock(return_value=False)
        self.input_methods = []
        for owner, names in ((self.window, ('focus', 'send', 'click', 'key')),
                             (self, ('workflow_navigation_input', 'evidence'))):
            for name in names:
                blocked = Mock(side_effect=AssertionError('no game input or evidence export'))
                self.input_methods.append(blocked)
                setattr(owner, name, blocked)
        self.snapshot = Mock(wraps=self.snapshot)


class ScreenTestTests(TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / 'fixtures' / 'du_runtime' / 'guide_universe_tab_clear.png'
        cls.survival = identified(Vision(.65).read(cv2.imdecode(np.fromfile(path, np.uint8), 1)))

    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.path = self.directory / 'report.json'
        ticks = count(100_000)
        self.enterContext(patch('autohsr.workflow_screen.time.monotonic', side_effect=lambda: next(ticks) / 1000.))

    def observer(self, frames):
        context = ReadOnlyContext(frames)
        for method in context.input_methods:
            self.addCleanup(method.assert_not_called)
        return screen_test.ScreenTestObserver(context)

    def observe(self, observer):
        result = observer.run()
        self.assertEqual(result.task, screen_test.OPERATION)
        report = observer.context.report
        self.assertIs(report.screen_test, observer.record)
        report.results.append(result)
        report.status = 'success' if result.status == 'ok' else result.status
        return result

    def save(self, observer):
        temporary = self.directory / 'report.tmp'
        report = observer.context.report

        def write():
            value = report.to_dict()
            value['screen_test'] = report.screen_test
            payload = json.dumps(value, ensure_ascii=False, indent=2)
            temporary.write_text(payload, encoding='utf8')
            return payload

        observer.save_verified_report(temporary, write)
        raw = self.path.read_text(encoding='utf8')
        for field in (ACCOUNT.text, OTHER.text, 'synthetic-game-window', 'private-test-marker'):
            self.assertNotIn(field, raw)
        return json.loads(raw)

    def test_same_account_pair_accepts_each_existing_page_without_input(self):
        for page, label, frame in (
                ('phone', '手机', phone()), ('guide', '星际和平指南', identified(fixture('guide_du_capped'))),
                ('daily_training', '每日实训', identified(fixture('daily_survival_badge'))),
                ('survival_index', '生存索引', self.survival),
                ('assignments', '委托', identified(fixture('assignments_after_claim'))),
                ('mail', '邮件', identified(fixture('mail_claimable'))), ('battlepass', '无名勋礼', battlepass())):
            with self.subTest(page=page):
                observer = self.observer([frame, frame])
                self.assertEqual(self.observe(observer).status, 'ok')
                observer.guard_publication()
                self.assertEqual(observer.context.snapshot.call_count, 2)
                expected = dict(schema=1, page=page, page_verified=True, account_verified=True, input_sent=False)
                self.assertEqual(observer.record, expected)
                self.assertEqual(screen_test.desktop_result(expected, 'success')[0], '当前页面已核实 · ' + label)
                if page == 'phone':
                    saved = self.save(observer)
                    self.assertEqual(saved['screen_test'], expected)
                    self.assertEqual(saved['status'], 'success')

    def test_weak_title_ordinary_world_overlay_and_page_change_leave_unknown(self):
        source = phone()
        title_only = Scene([ACCOUNT, badge('委托', .08, .05)], source.image)
        for frames in ([title_only, title_only], [world(), world()], [source, title_only],
                       [source, identified(fixture('mail_claimable'))],
                       [source, phone(badge('确认', .50, .54, score=.72))],
                       [source, phone(badge('战斗失败', .50, .45))],
                       [source, phone(badge('加载中', .50, .45, score=.70))]):
            observer = self.observer(frames)
            self.assertEqual(self.observe(observer).status, 'partial')
            self.assertEqual(observer.record, screen_test.initial_record())

    def test_achievement_pages_publish_only_fixed_states_and_whitelisted_category(self):
        bulk = label('一键领取奖励', .824, .897)
        single = label('领取', .924, .286)
        row = label('东山再起', .176, .258)
        detail = [label('成就奖励', .50, .114), label('与你同行的回忆', .127, .193),
                  row, label('5', .83, .258),
                  label('总计获得', .467, .838), label('确认', .502, .926)]
        for page, category, claim, frame in (
                ('achievement_overview', None, 'bulk', achievement_frame(overview(), bulk)),
                ('achievement_list', '与你同行的回忆', 'single', achievement_frame(category_view(), single)),
                ('achievement_receipt', None, None, Scene([ACCOUNT, *detail], receipt_rows(row)))):
            with self.subTest(page=page):
                observer = self.observer([frame, frame])
                self.assertEqual(self.observe(observer).status, 'ok')
                saved = self.save(observer)['screen_test']
                self.assertEqual(saved['page'], page)
                self.assertEqual(saved['achievement'], dict(category=category, visible_claim=claim))
                self.assertNotIn('东山再起', json.dumps(saved, ensure_ascii=False))
                self.assertTrue(screen_test.desktop_result(saved, 'success')[0].startswith('当前页面已核实'))

    def test_reward_guide_requires_actual_installation_and_rechecks_it_before_publication(self):
        first, second = (guide_scene(name, width=1920) for name in ('viewport-7014.png', 'viewport-7026.png'))
        for frame in (first, second):
            frame.tokens.append(ACCOUNT)
        executable = self.directory / 'StarRail.exe'
        executable.touch()
        config = self.directory / 'config.ini'
        for version, expected in (('4.7.0', 'partial'), ('4.6.0', 'ok')):
            with self.subTest(version=version):
                config.write_text(f'[General]\ngame_version={version}\n', encoding='utf8')
                observer = self.observer([first, second])
                observer.context.window.current_executable = Mock(return_value=str(executable))
                self.assertEqual(self.observe(observer).status, expected)
                if expected == 'ok':
                    self.assertEqual(observer.record['page'], 'reward_guide')
                    self.assertEqual(observer.record['reward_guide'], _GUIDE_VIEWPORT)
                    native_replace = Path.replace
                    locks = []

                    def replace_while_held(temporary, destination):
                        if os.name == 'nt':
                            with self.assertRaises(PermissionError), config.open('ab'):
                                pass
                        locks.append(True)
                        return native_replace(temporary, destination)

                    with patch.object(Path, 'replace', new=replace_while_held):
                        saved = self.save(observer)['screen_test']
                    self.assertEqual(saved, observer.record)
                    self.assertEqual(locks, [True])
                    title, detail = screen_test.desktop_result(saved, 'success')
                    self.assertEqual(title, '当前页面已核实 · 奖励指南')
                    self.assertIn('进行中', detail)
                    self.assertIn('(378, 342)–(1404, 945)', detail)
                    self.assertEqual(selection(Image.fromarray(first.image[:, :, ::-1]),
                                               saved['reward_guide']['content_box']).size, (1026, 603))
                    config.write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
                    self.assertEqual(self.save(observer)['screen_test'], screen_test.initial_record())

    def test_reward_guide_crop_requires_both_frames_and_same_account(self):
        executable = self.directory / 'StarRail.exe'
        executable.touch()
        executable.with_name('config.ini').write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        guide, viewport = guide_scene(), guide_scene('viewport-7014.png')
        for frame in (guide, viewport):
            frame.tokens.append(ACCOUNT)
        legacy = dict(screen_test.initial_record(), page='reward_guide', page_verified=True, account_verified=True)
        for missing, frames in (('both', (guide, guide)), ('first', (guide, viewport)),
                                ('second', (viewport, guide))):
            with self.subTest(missing=missing):
                observer = self.observer(frames)
                observer.context.window.current_executable = Mock(return_value=executable)
                self.assertEqual(self.observe(observer).status, 'ok')
                self.assertEqual(self.save(observer)['screen_test'], legacy)
        self.assertEqual(screen_test.desktop_result(legacy, 'success'),
                         ('当前页面已核实 · 奖励指南', '同一账号的连续两帧一致。'))

        changed = guide_scene('viewport-7026.png')
        changed.tokens.append(OTHER)
        observer = self.observer((viewport, changed))
        observer.context.window.current_executable = Mock(return_value=executable)
        self.assertEqual(self.observe(observer).status, 'partial')
        self.assertEqual(observer.record, screen_test.initial_record())

    def test_reward_guide_desktop_projection_rejects_unverified_crop_fields(self):
        valid = dict(screen_test.initial_record(), page='reward_guide', page_verified=True, account_verified=True,
                     reward_guide=_GUIDE_VIEWPORT)
        for changes in (dict(visible_section='private-test-marker'), dict(content_box=[0, 0, 1000, 1000]),
                        dict(frame_size=[1920, True]), dict(frame_size=[1280, 720]), dict(path='private-test-marker')):
            with self.subTest(changes=changes):
                malformed = dict(valid, reward_guide=_GUIDE_VIEWPORT | changes)
                self.assertEqual(screen_test.desktop_result(malformed, 'success')[0], '当前页面待核对')
        self.assertEqual(screen_test.desktop_result(dict(valid, page='phone'), 'success')[0], '当前页面待核对')

    def test_reward_guide_final_version_read_cannot_outlive_foreground_epoch_or_stop(self):
        source = guide_scene('viewport-7014.png', width=1920)
        source.tokens.append(ACCOUNT)
        executable = self.directory / 'StarRail.exe'
        executable.touch()
        executable.with_name('config.ini').write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        native = screen_test.read_event_installation
        for change in ('foreground', 'epoch', 'stop'):
            with self.subTest(change=change):
                observer = self.observer([source, source])
                context = observer.context
                context.window.current_executable = Mock(return_value=str(executable))
                self.assertEqual(self.observe(observer).status, 'ok')
                self.assertEqual(observer.record['reward_guide'], _GUIDE_VIEWPORT)
                reads = count(1)

                def drift(window):
                    installation = native(window)
                    if next(reads) == 3:
                        if change == 'foreground':
                            window.guard.side_effect = FocusLost('lost during the final installation read')
                        elif change == 'epoch':
                            context.runner.input_epoch += 1
                        else:
                            window.emergency_pressed.return_value = True
                    return installation

                with patch.object(screen_test, 'read_event_installation', side_effect=drift):
                    saved = self.save(observer)
                self.assertEqual(saved['screen_test'], screen_test.initial_record())
                self.assertEqual(saved['status'], 'stopped' if change == 'stop' else 'partial')

    def test_achievement_button_disagreement_stays_unknown_and_conflicting_pages_are_rejected(self):
        bulk = label('一键领取奖励', .824, .897)
        seen = achievement_frame(overview(), bulk)
        observer = self.observer([seen, achievement_frame(overview())])
        self.assertEqual(self.observe(observer).status, 'ok')
        self.assertIsNone(observer.record['achievement']['visible_claim'])
        observer.record['achievement']['visible_claim'] = 'bulk'
        self.assertEqual(self.save(observer)['screen_test'], screen_test.initial_record())

        mail = fixture('mail_claimable')
        conflicting = achievement_frame([*overview(), *mail.tokens], bulk)
        wrong_category = achievement_frame(category_view('众秘探奇'))
        opening = achievement_frame([*overview(), label('成就奖励', .50, .114, score=.71)], bulk)
        for frames in ([conflicting, conflicting], [achievement_frame(category_view()), wrong_category],
                       [opening, opening]):
            observer = self.observer(frames)
            self.assertEqual(self.observe(observer).status, 'partial')
            self.assertEqual(observer.record, screen_test.initial_record())

    def test_account_change_empty_frame_stale_capture_and_background_fail_closed(self):
        source = phone()
        for second in (phone(account=OTHER), EmptyCapture('synthetic missing frame')):
            observer = self.observer([source, second])
            self.assertEqual(self.observe(observer).status, 'partial')
            self.assertFalse(observer.record['account_verified'])

        observer = self.observer([source, source])
        context = observer.context
        context.snapshot.side_effect = lambda: context.last_scene or Context.snapshot(context)
        self.assertEqual(self.observe(observer).status, 'partial')
        self.assertEqual(observer.record, screen_test.initial_record())

        observer = self.observer([source, source])
        observer.context.window.guard.side_effect = FocusLost('synthetic foreground loss')
        self.assertEqual(self.observe(observer).status, 'partial')
        observer.context.snapshot.assert_not_called()

    def test_dedicated_operation_low_collection_floor_and_one_shot_are_required(self):
        source = phone()
        for changes in ('operation', 'background-mode', 'floor'):
            with self.subTest(changes=changes):
                observer = self.observer([source, source])
                context = observer.context
                if changes == 'operation':
                    context.report.operation = 'daily'
                elif changes == 'background-mode':
                    context.runner._foreground_only = False
                else:
                    context.vision.confidence = .91
                with self.assertRaises(AutomationError):
                    observer.run()
                context.snapshot.assert_not_called()
        observer = self.observer([source, source])
        self.assertEqual(self.observe(observer).status, 'ok')
        with self.assertRaises(AutomationError):
            screen_test.ScreenTestObserver(observer.context).run()
        self.assertEqual(observer.context.snapshot.call_count, 2)

    def test_late_stop_window_epoch_pixel_or_semantic_change_clears_publication(self):
        source = phone()
        for failure in ('stop', 'focus', 'window', 'epoch', 'pixels', 'tokens', 'expired', 'record', 'status'):
            with self.subTest(failure=failure):
                observer = self.observer([source, source])
                self.assertEqual(self.observe(observer).status, 'ok')
                context = observer.context
                if failure == 'stop':
                    context.window.emergency_pressed.return_value = True
                elif failure == 'focus':
                    context.window.guard.side_effect = FocusLost('synthetic focus loss')
                elif failure == 'window':
                    context.window.current_window_key.return_value = 'synthetic-different-window'
                elif failure == 'epoch':
                    context.runner.input_epoch += 1
                elif failure == 'pixels':
                    context.last_scene.image[100, 100] ^= 1
                elif failure == 'tokens':
                    context.last_scene.tokens = [ACCOUNT]
                elif failure == 'record':
                    context.report.screen_test = {'unsupported': 'private-test-marker'}
                elif failure == 'status':
                    context.report.status = 'partial'
                with ExitStack() as patches:
                    if failure == 'expired':
                        patches.enter_context(patch('autohsr.workflow_screen.time.monotonic',
                                                    return_value=time.monotonic() + 9))
                    saved = self.save(observer)
                status = 'stopped' if failure == 'stop' else 'partial'
                self.assertEqual((saved['status'], saved['results'][-1]['status']), (status, status))
                self.assertEqual(saved['screen_test'], screen_test.initial_record())
                if failure == 'stop':
                    context.runner.stop.assert_called_once()

    @skipUnless(os.name == 'nt', 'requires native Windows sharing')
    def test_real_destination_sharing_retry_rechecks_before_final_replace(self):
        source = phone()
        observer = self.observer([source, source])
        self.assertEqual(self.observe(observer).status, 'ok')
        self.path.write_text('{}', encoding='utf8')
        waits = []
        with ExitStack() as blocker:
            blocker.enter_context(hold_read_sources((self.path,)))

            def delayed(seconds):
                waits.append(seconds)
                blocker.close()
                observer.context.runner.input_epoch += 1

            with patch('autohsr.storage.time', SimpleNamespace(sleep=delayed)):
                saved = self.save(observer)
        self.assertEqual(len(waits), 1)
        self.assertEqual(saved['screen_test'], screen_test.initial_record())
        self.assertEqual(saved['status'], 'partial')

    def test_staged_bytes_and_desktop_report_flags_cannot_assert_positive(self):
        source = phone()
        observer = self.observer([source, source])
        self.assertEqual(self.observe(observer).status, 'ok')
        record = dict(observer.record)
        for change in (dict(account_verified=1), dict(page='world'), dict(page_verified=False), dict(input_sent=0)):
            self.assertEqual(screen_test.desktop_result(record | change, 'success')[0], '当前页面待核对')
        self.assertEqual(screen_test.desktop_result(record, 'partial')[0], '当前页面待核对')

        def tamper(temporary, destination, **options):
            if 'attempt_scope' in options:
                temporary.write_bytes(b'\xff private-test-marker')
            return replace_file(temporary, destination, **options)

        with patch('autohsr.screen_test.replace_file', side_effect=tamper):
            saved = self.save(observer)
        self.assertEqual(saved['screen_test'], screen_test.initial_record())
        self.assertEqual(saved['status'], 'partial')

    def test_stop_during_observation_never_leaves_verified_record(self):
        source = phone()
        observer = self.observer([source, source])
        with patch.object(observer.context, 'sleep', side_effect=Stopped('internal synthetic reason')):
            with self.assertRaisesRegex(Stopped, '当前页面核对已停止'):
                observer.run()
        self.assertEqual(observer.record, screen_test.initial_record())
