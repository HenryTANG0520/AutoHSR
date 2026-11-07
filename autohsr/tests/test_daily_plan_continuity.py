"""Formal CLI with a fake window, real shared budget and training decision."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import ctypes as C
from dataclasses import replace
from datetime import datetime, timedelta
import io
from itertools import count
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.currency_wars_identity import UID_COUNTEREVIDENCE, UID_VETO_FLOOR
from autohsr.daily_support import ACTIVITY, FULL
from autohsr.models import Token
from autohsr.power_plan_store import read, read_ref
from autohsr.recovery import BattleBudget
from autohsr.tests import test_daily_support as support
from autohsr.tests.test_power_plan import FakeContext, row
from autohsr.tests.test_power_plan_entry import runtime as fake_runtime
from autohsr.weekly_plan import CHINA


NOW = datetime(2026, 11, 6, 12, tzinfo=CHINA)
ECHO = '毁灭的开端'
FIRST = '回忆之蕾'
FILL = '藏珍之蕾'
CAVERN = '侵蚀隧洞'
CALYX = '以太之蕾'
PLANAR = '浴火钢心'
CRIMSON = '欢愉之蕾'
FIFTY_POINT = Path(__file__).parent / 'fixtures/daily_support_fifty_point_settings.json'
runtime = fake_runtime


class BalanceWorld(support.World):
    def __init__(self, target, boundary):
        super().__init__('full_pending')
        self.target, self.boundary = target, boundary
        self.stamina, self.weekly_left = 110, 1
        self.on_open = self.lower_balance

    def lower_balance(self, world):
        opens = world.opened.count(self.target)
        if world.settings.target_name == self.target and (
                opens == 1 and self.boundary in ('missing_uid', 'known_low', 'low_balance_uid_conflict')
                or opens == 2 and self.boundary == 'known_low_reopen'):
            world.stamina = 20

    def scene(self, settings):
        target_team = settings.target_name == self.target and self.mode == 'team'
        if target_team and self.boundary in ('known_low_team', 'partial_team_balance'):
            self.stamina = 20
        page = super().scene(settings)
        if target_team and self.boundary == 'missing_team_balance':
            page.tokens = [token for token in page.tokens if token.text != f'{self.stamina}/300']
        elif target_team and self.boundary == 'conflicting_team_balance':
            page.tokens.append(Token('20/300', .99, (.84, .02, .92, .06)))
        elif target_team and self.boundary == 'mixed_team_balance':
            page.tokens.append(Token('2O/300', .94, (.84, .02, .92, .06)))
        elif target_team and self.boundary in ('partial_team_balance', 'blank_team_numerator',
                                               'isolated_team_digits', 'label_without_balance'):
            fragment = {'partial_team_balance': '2O/300', 'blank_team_numerator': '/300', 'isolated_team_digits': '20',
                        'label_without_balance': '当前开拓力'}[self.boundary]
            page.tokens = [replace(token, text=fragment) if token.text == f'{self.stamina}/300' else token
                           for token in page.tokens]
        if settings.target_name == self.target and self.mode == 'entry':
            opens = self.opened.count(self.target)
            if self.boundary == 'missing_uid' and opens == 1:
                page.tokens = [field for field in page.tokens if not field.text.startswith('UID:')]
            elif self.boundary == 'low_balance_uid_conflict' and opens == 1:
                page.tokens.append(Token('UID:987654321', .74, (.014, .956, .21, .979)))
            if opens == 2 and (self.boundary == 'reopen' or self.boundary == 'count_adjustment' and self.count == 2):
                page.tokens = [field for field in page.tokens if field.text != f'{self.stamina}/300']
        return page


class NativeTrainingScreens(support.Screens):
    def ensure_main(self):
        return self.ctx.snapshot()

    def _icon(self, scene, name, roi, threshold=.88):
        return None


class FiftyPointWorld(support.World):
    def __init__(self, boundary):
        super().__init__('needed_400')
        self.stamina, self.weekly_left = 50, 1
        self.boundary = boundary
        self.support_clicks = []
        self.after_payment = self.settle_support
        badge = FIFTY_POINT.parent / 'dungeons' / 'planar_support_badge.png'
        self.badge = cv2.imdecode(np.frombuffer(badge.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)

    @staticmethod
    def settle_support(world):
        if world.settings.target_name == ECHO:
            assert world.borrowed
            world.borrowed = False
            world.card = 'full_completed_third'

    def scene(self, settings):
        if self.mode in ('picker', 'selected'):
            rows = [('离线相近甲', .203, True)]
            if self.boundary != 'friend_missing':
                rows.append(('离线指定甲', .332, True))
            page = support.core.support_picker(rows, marker='green' if self.mode == 'selected' else None)
            page.tokens.append(Token('UID:' + self.uid, .99, (.01, .96, .22, .99)))
        else:
            page = super().scene(settings)
        if self.mode in ('picker', 'selected') and page.image is None:
            page.image = np.full((540, 960, 3), 80, dtype=np.uint8)
        if self.mode == 'selected' or self.mode == 'team' and self.borrowed:
            mark = page.find('支援', (.80, .48, .95, .60), exact=True)
            height, width = page.image.shape[:2]
            x1, y1, x2, y2 = (round(value * size) for value, size in zip(mark.box, (width, height) * 2))
            page.image[y1:y2, x1:x2] = cv2.resize(self.badge, (x2-x1, y2-y1))
        if self.mode == 'training' and self.card == 'full_completed_third':
            # Keep the historical card fields, with synthetic sub-cap activity.
            page.tokens = [replace(token, text='400') if token.within(ACTIVITY) else
                           replace(token, text='领取') if token.text == FULL else token
                           for token in page.tokens]
        return page

    def click_support(self, target):
        if target.text not in ('支援', '好友', '确认'):
            return False
        assert self.settings.target_name == ECHO
        self.support_clicks.append(target.text)
        if target.text == '支援':
            assert self.mode == 'team'
            self.mode = 'picker'
        elif target.text == '好友':
            assert self.mode == 'picker' and abs(target.center[1] - .332) < .001
            self.mode = 'selected'
        else:
            assert self.mode == 'selected'
            self.mode, self.borrowed = 'team', True
        return True


class FiftyPointScreens(NativeTrainingScreens):
    def _icon(self, scene, name, roi, threshold=.88):
        return (.18, .29, .98) if self.ctx.world.mode == 'training' and name == 'daily_activity_badge' else None


@contextmanager
def native_payment_window(root, settings, world, starts, vetoes, *, payment_target=CAVERN, on_click=None):
    """Keep the actual Win32 guard, key query, callback and packet assembly."""
    with fake_runtime(root, settings, world) as (screen, find):
        geometry = windows.Geometry(8, 12, 960, 540)
        screen.geometry = geometry
        window = windows.GameWindow.__new__(windows.GameWindow)
        window.hwnd, window.path, window.world, window.contexts = 71, '', world, screen.contexts
        window.capture, window.focus = screen.capture, window.guard
        user32 = Mock()
        user32.IsWindow.return_value = 1
        user32.IsIconic.return_value = 0
        user32.GetForegroundWindow.return_value = 71
        user32.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__
        active = None

        def click(x, y, geometry, **kwargs):
            nonlocal active
            active = next(token for token in screen.scene.tokens
                          if abs(token.center[0]-x) < 1e-6 and abs(token.center[1]-y) < 1e-6)
            try:
                return windows.GameWindow.click(window, x, y, geometry, **kwargs)
            finally:
                active = None

        def is_later_payment():
            return active is not None and active.text == '开始挑战' and world.settings.target_name == payment_target

        def key_state(_):
            if is_later_payment() and world.boundary == 'late_epoch' and not vetoes:
                window.owner.input_epoch += 1
                vetoes.append('epoch')
            return 0

        def send(count, payload, _):
            if count == 1:
                release = C.cast(payload, C.POINTER(windows.INPUT)).contents
                assert is_later_payment() and world.boundary == 'partial_send' and release.mi.dwFlags == 4
                return count
            assert count == 3 and [item.mi.dwFlags for item in payload] == [0xC001, 2, 4]
            driver = FakeContext(world, world.settings, window.owner.report, window.owner.battle_budget)
            driver.last_scene = screen.scene
            if active.text == '开始挑战':
                starts.append((world.settings.target_name, window.owner.report.stamina_pending))
            if on_click is None or not on_click(active):
                driver.click(screen.scene, active)
            return count - 1 if is_later_payment() and world.boundary == 'partial_send' else count

        window.click = click
        user32.GetAsyncKeyState.side_effect = key_state
        user32.SendInput.side_effect = send
        find.return_value = window
        with patch.object(windows, 'user32', user32), patch.object(windows, 'geometry', return_value=geometry):
            yield window, find
        user32.SetForegroundWindow.assert_not_called()


class DailyPlanContinuityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        stamps = count()

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                current = NOW + timedelta(microseconds=next(stamps))
                return current.astimezone(tz) if tz else current.replace(tzinfo=None)

        for target, value in (('autohsr.app.datetime', Clock), ('autohsr.daily_support.datetime', Clock),
                              ('autohsr.echo_weekly.local_now', lambda: NOW)):
            mocked = patch(target, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def cli(self, folder, world, later, *, mode, extra=(), screens=NativeTrainingScreens):
        folder.mkdir(exist_ok=True)
        config = folder / 'config.json'
        if not config.exists():
            settings = Settings(assignments=False, daily=False, daily_synthesis=False, use_support=True,
                                overlay_logs=False, stamina_limit=110, rounds=2, challenge_count=1,
                                target_name=FILL, power_plan=[row(count=1), later],
                                echo_of_war_enabled=True, power_plan_fill=True)
            settings.save(config)
        else:
            settings = Settings.load(config)
        saved = config.read_bytes()
        output = io.StringIO()
        with runtime(folder, settings, world) as (window, find):
            def native(settings, *args, **kwargs):
                child = Runner(settings, *args, **kwargs)
                window.owner = child
                return child

            with (patch('autohsr.app.Runner', side_effect=native), patch('autohsr.plan_runner.ROOT', folder),
                  patch('autohsr.workflows.DailyWorkflow', screens), redirect_stdout(output),
                  redirect_stderr(io.StringIO())):
                code = main([mode, '--config', str(config), '--power-plan', '--support-daily-only', *extra])
        self.assertEqual(config.read_bytes(), saved)
        return code, json.loads(output.getvalue()), find.call_count

    def assert_stopped_with_prior_proof(self, folder, world, code, report):
        self.assertEqual(world.paid, [(ECHO, 1, 30), (FIRST, 1, 10)], report.get('error'))
        self.assertNotIn(FILL, world.opened)
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'partial')
        if report['operation'] == 'plan':
            self.assertEqual(report['weekly_plan']['status'], 'not_started')
        self.assertEqual((report['battle_completed'], report['stamina_spent'], report['stamina_pending']), (2, 40, 0))
        self.assertEqual(report['power_plan']['done'], [1, 0])
        self.assertEqual(report['power_plan']['weekly_echo']['completed'], 1)
        self.assertEqual([selection['state'] for selection in report['support_selections']], ['activity_full'] * world.opened_guide)
        self.assertGreaterEqual(world.opened_guide, 2)
        journal = read(folder / 'runs' / 'battle-session.json')
        self.assertEqual((journal['completed'], journal['spent'], journal['pending']), (2, 40, 0))
        self.assertEqual(journal['power_plan']['done'], [1, 0])

    def test_fifty_point_combination_and_same_day_recovery(self):
        for mode in ('--run', '--plan'):
            for boundary in (None, 'friend_missing', 'late_epoch', 'partial_send'):
                with self.subTest(mode=mode, boundary=boundary):
                    folder = self.root / f'{mode}-{boundary}'
                    folder.mkdir()
                    (folder / 'config.json').write_bytes(FIFTY_POINT.read_bytes())
                    world = FiftyPointWorld(boundary)
                    starts, vetoes = [], []

                    def native(root, settings, value):
                        return native_payment_window(root, settings, value, starts, vetoes,
                                                     payment_target=CRIMSON, on_click=world.click_support)

                    def run(*extra):
                        with patch(__name__ + '.runtime', native):
                            return self.cli(folder, world, None, mode=mode, extra=extra, screens=FiftyPointScreens)

                    code, report, _ = run()
                    journal = folder / 'runs' / 'battle-session.json'
                    first = read(journal)
                    states = [record['state'] for record in report['support_selections']]
                    if boundary == 'friend_missing':
                        self.assertEqual((code, states, starts, world.support_clicks),
                                         (1, ['needed', 'unverified'], [], ['支援']))
                        self.assertEqual((first['spent'], first['pending']), (0, 0))
                        world.boundary = None
                        code, report, _ = run()
                    else:
                        self.assertEqual(states, ['needed', 'borrowed', 'completed', 'completed'], report['error'])
                        self.assertEqual(world.support_clicks, ['支援', '好友', '确认'])
                        training = [item for item in report['support_selections'] if item['mode'] == 'daily_training']
                        self.assertEqual([item['activity'] for item in training], [400, 400, 400])
                        self.assertEqual({item['game_day'] for item in training}, {NOW.date().isoformat()})
                    if boundary in ('late_epoch', 'partial_send'):
                        self.assertEqual((code, first['spent'], report['power_plan']['done']), (1, 40, [1, 0]))
                        self.assertEqual([charge['row'] for charge in first['power_plan']['charges']], [-2, 0])
                        if boundary == 'partial_send':
                            self.assertEqual(first['pending'], 10)
                            original = journal.read_bytes()
                            blocked, _, finds = run('--new-battle-run')
                            self.assertEqual((blocked, finds), (1, 0))
                            self.assertEqual(journal.read_bytes(), original)
                            continue
                        self.assertEqual((first['pending'], vetoes), (0, ['epoch']))
                        self.assertEqual(starts, [(ECHO, 30), (FIRST, 10)])
                        world.boundary = None
                        code, report, _ = run('--new-battle-run')
                        self.assertEqual(report['power_plan']['before'], [1, 0])
                    self.assertEqual(code, 0, report['error'])
                    self.assertEqual(starts, [(ECHO, 30), (FIRST, 10), (CRIMSON, 10)])
                    self.assertEqual((world.stamina, report['stamina_pending']), (0, 0))
                    self.assertEqual([entry[:3] for entry in world.payments],
                                     [(ECHO, 1, 30), (FIRST, 1, 10), (CRIMSON, 1, 10)])
                    settled = read(journal)
                    if boundary != 'late_epoch':
                        self.assertEqual((settled['limit'], settled['spent'], report['power_plan']['done']),
                                         (50, 50, [1, 1]))
                        self.assertEqual([charge['row'] for charge in settled['power_plan']['charges']], [-2, 0, 1])
                        self.assertEqual(settled['power_plan']['weekly_echo']['completed'], 1)
                        borrowed, = [item for item in report['support_selections'] if item['state'] == 'borrowed']
                        self.assertEqual((borrowed['selected']['friend'], borrowed['attempts']), ('离线指定甲', 1))

    def test_mixed_plan_with_support_and_weak_account_conflict(self):
        class MixedWorld(FiftyPointWorld):
            def scene(self, settings):
                page = super().scene(settings)
                if settings.target_name == PLANAR and self.opened_guide == 3 and self.mode == self.boundary:
                    page.field_reads[UID_COUNTEREVIDENCE] = (Token('UID:987654321', .75, (.02, .95, .21, .98)),)
                return page

        for mode in ('--run', '--plan'):
            for boundary in (None, 'team', 'success'):
                with self.subTest(mode=mode, boundary=boundary):
                    folder = self.root / f'{mode}-{boundary}'
                    folder.mkdir()
                    settings = replace(Settings.load(FIFTY_POINT), ocr_confidence=.85, stamina_limit=80, rounds=2,
                                       power_plan=[row(count=1), row('planar', 2, PLANAR, '永恒圣城')])
                    settings.save(folder / 'config.json')
                    world = MixedWorld(boundary)
                    world.stamina, world.tokens = 80, 1
                    starts, readers = [], []

                    @contextmanager
                    def native(root, settings, value):
                        with native_payment_window(root, settings, value, starts, [], payment_target=PLANAR,
                                                   on_click=world.click_support) as (window, find):
                            yield window, find
                            readers.extend(ctx.vision for ctx in window.contexts)

                    def run(*extra):
                        with patch(__name__ + '.runtime', native):
                            return self.cli(folder, world, None, mode=mode, extra=extra, screens=FiftyPointScreens)

                    code, report, _ = run()
                    ledger = folder / 'runs' / 'battle-session.json'
                    saved = read(ledger)
                    self.assertEqual(world.support_clicks, ['支援', '好友', '确认'])
                    self.assertEqual([record['state'] for record in report['support_selections']],
                                     ['needed', 'borrowed', 'completed', 'completed'])
                    expected = [(ECHO, 30), (FIRST, 10)]
                    if boundary != 'team':
                        expected.append((PLANAR, 40))
                    self.assertEqual(starts, expected)
                    if boundary == 'success':
                        self.assertEqual((code, saved['spent'], saved['pending'], saved['immersifiers_pending']),
                                         (1, 40, 40, 1))
                        self.assertIn('账号未核实', report['error'])
                        self.assertEqual(saved['power_plan']['done'], [1, 0])
                        original = ledger.read_bytes()
                        blocked, _, finds = run('--new-battle-run')
                        self.assertEqual((blocked, finds), (1, 0))
                        self.assertEqual(ledger.read_bytes(), original)
                    elif boundary == 'team':
                        self.assertEqual((code, saved['spent'], saved['pending'], saved['immersifiers_pending']),
                                         (1, 40, 0, 0))
                        self.assertIn('账号未核实', report['error'])
                    else:
                        self.assertEqual((code, saved['completed'], saved['spent'], saved['immersifiers_spent'],
                                          saved['pending'], saved['immersifiers_pending']), (0, 4, 80, 1, 0, 0))
                        self.assertEqual(world.payments[-1], (PLANAR, 2, 40, 1))
                        charges = saved['power_plan']['charges']
                        self.assertEqual([(c['row'], c['count'], c['stamina'], c['immersifiers']) for c in charges],
                                         [(-2, 1, 30, 0), (0, 1, 10, 0), (1, 2, 40, 1)])
                        original_report = Path(saved['run_dir']) / 'report.json'
                        original = original_report.read_bytes()
                        world.stamina, world.tokens = 80, 1
                        code, resumed, _ = run()
                        self.assertEqual((code, resumed['battle_completed'], resumed['stamina_spent']), (0, 0, 0))
                        self.assertEqual(resumed['power_plan']['before'], [1, 2])
                        self.assertEqual(starts, expected)
                        self.assertEqual(original_report.read_bytes(), original)
                    self.assertTrue(readers)
                    self.assertTrue(all(getattr(reader, 'uid_counterevidence_floor', None) == UID_VETO_FLOOR
                                        for reader in readers))

    def test_low_balance_without_a_unique_account_cannot_defer_to_default_fill(self):
        later = row('cavern', 1, CAVERN, '残响回廊')
        for mode in ('--run', '--plan'):
            for boundary in ('missing_uid', 'low_balance_uid_conflict'):
                with self.subTest(mode=mode, boundary=boundary):
                    folder = self.root / (boundary + mode)
                    world = BalanceWorld(CAVERN, boundary)
                    code, report, _ = self.cli(folder, world, later, mode=mode)
                    self.assert_stopped_with_prior_proof(folder, world, code, report)

    def test_unread_balance_after_training_or_round_adjustment_cannot_pay(self):
        for boundary in ('reopen', 'count_adjustment'):
            for mode in ('--run', '--plan'):
                with self.subTest(boundary=boundary, mode=mode):
                    folder = self.root / (boundary + mode)
                    world = BalanceWorld(CALYX, boundary)
                    later = row(count=2, target=CALYX)
                    code, report, _ = self.cli(folder, world, later, mode=mode)
                    self.assert_stopped_with_prior_proof(folder, world, code, report)

    def test_verified_low_balance_still_allows_cheaper_default_fill(self):
        later = row('cavern', 1, CAVERN, '残响回廊')
        for mode in ('--run', '--plan'):
            for boundary in ('known_low', 'known_low_reopen'):
                with self.subTest(mode=mode, boundary=boundary):
                    world = BalanceWorld(CAVERN, boundary)
                    code, report, _ = self.cli(self.root / (boundary + mode), world, later, mode=mode)
                    self.assertEqual(code, 0, report.get('error'))
                    self.assertEqual(world.paid, [(ECHO, 1, 30), (FIRST, 1, 10), (FILL, 1, 10)])
                    plan = report['power_plan']
                    self.assertEqual(plan['done'], [1, 0])
                    self.assertEqual([charge['row'] for charge in plan['charges']], [-2, 0, -1])
                    skipped, = [result for result in plan['results'] if result['row'] == 1]
                    self.assertEqual((skipped['status'], skipped['reason']), ('deferred', 'insufficient_stamina'))

    def test_new_team_balance_blocks_payment_and_hidden_balance_keeps_original_chain(self):
        later = row('cavern', 1, CAVERN, '残响回廊')
        for mode in ('--run', '--plan'):
            for boundary in ('known_low_team', 'conflicting_team_balance', 'partial_team_balance',
                             'blank_team_numerator', 'isolated_team_digits', 'label_without_balance', 'mixed_team_balance',
                             'missing_team_balance'):
                with self.subTest(mode=mode, boundary=boundary):
                    folder = self.root / (boundary + mode)
                    world = BalanceWorld(CAVERN, boundary)
                    code, report, _ = self.cli(folder, world, later, mode=mode)
                    if boundary == 'missing_team_balance':
                        self.assertEqual(code, 0, report.get('error'))
                        self.assertEqual(world.paid, [(ECHO, 1, 30), (FIRST, 1, 10), (CAVERN, 1, 40), (FILL, 1, 10)])
                        self.assertEqual((report['stamina_spent'], report['stamina_pending']), (90, 0))
                    else:
                        self.assert_stopped_with_prior_proof(folder, world, code, report)

    def test_native_payment_distinguishes_epoch_veto_from_partial_windows_submission(self):
        later = row('cavern', 1, CAVERN, '残响回廊')
        for mode in ('--run', '--plan'):
            for boundary in ('late_epoch', 'partial_send'):
                with self.subTest(mode=mode, boundary=boundary):
                    folder = self.root / (boundary + mode)
                    world = BalanceWorld(CAVERN, boundary)
                    starts, vetoes = [], []

                    def native(root, settings, value):
                        return native_payment_window(root, settings, value, starts, vetoes)

                    with patch(__name__ + '.runtime', native):
                        code, report, _ = self.cli(folder, world, later, mode=mode)
                        journal = folder / 'runs' / 'battle-session.json'
                        saved = read(journal)
                        if boundary == 'late_epoch':
                            self.assert_stopped_with_prior_proof(folder, world, code, report)
                            self.assertEqual(vetoes, ['epoch'])
                            self.assertEqual(starts, [(ECHO, 30), (FIRST, 10)])
                            self.assertIsNone(saved['power_plan']['intent'])
                            self.assertEqual(saved['power_plan']['run_status'], 'partial')
                            unsent, = [result for result in saved['power_plan']['results']
                                       if result.get('reason') == 'payment_not_sent']
                            self.assertEqual((unsent['row'], unsent['requested'], unsent['completed']), (1, 1, 0))
                            self.assertTrue(read_ref(folder / 'runs', unsent['evidence']).is_file())
                            original = journal.read_bytes()
                            code, blocked, finds = self.cli(folder, world, later, mode=mode)
                            self.assertEqual((code, finds), (1, 0))
                            self.assertIn('明确确认新增预算', blocked['error'])
                            self.assertEqual(journal.read_bytes(), original)
                            world.boundary = None
                            code, resumed, _ = self.cli(folder, world, later, mode=mode, extra=('--new-battle-run',))
                            self.assertEqual(code, 0, resumed['error'])
                            self.assertEqual(resumed['power_plan']['before'], [1, 0])
                            self.assertEqual(starts, [(ECHO, 30), (FIRST, 10), (CAVERN, 40), (FILL, 10)])
                        else:
                            self.assertEqual((code, report['status']), (1, 'partial'))
                            self.assertEqual((report['stamina_spent'], report['stamina_pending'],
                                              report['battle_completed']), (40, 40, 2))
                            self.assertEqual(report['power_plan']['done'], [1, 0])
                            self.assertIn('已尝试提交，支付待核对', report['error'])
                            self.assertEqual(starts, [(ECHO, 30), (FIRST, 10), (CAVERN, 40)])
                            self.assertNotIn(FILL, world.opened)
                            self.assertEqual(saved['power_plan']['intent']['stamina'], 40)
                            original = journal.read_bytes()
                            code, blocked, finds = self.cli(folder, world, later, mode=mode, extra=('--new-battle-run',))
                            self.assertEqual((code, finds), (1, 0))
                            self.assertIn('待核对', blocked['error'])
                            self.assertEqual(journal.read_bytes(), original)

    def test_unsent_receipt_write_failure_keeps_the_original_pending_intent(self):
        write = BattleBudget._write

        def fail_unsent(budget, *args, **kwargs):
            if any(result.get('reason') == 'payment_not_sent' for result in budget.report.power_plan.get('results', [])):
                raise OSError('fixture unsent receipt write failed')
            return write(budget, *args, **kwargs)

        for later, tokens in ((row('cavern', 1, CAVERN, '残响回廊'), 0),
                              (row('planar', 2, PLANAR, '永恒圣城'), 1)):
            with self.subTest(category=later['category']):
                folder = self.root / later['category']
                world = BalanceWorld(later['target'], 'late_epoch')
                world.tokens = tokens
                starts, vetoes = [], []

                def native(root, settings, value):
                    return native_payment_window(root, settings, value, starts, vetoes, payment_target=later['target'])

                with patch(__name__ + '.runtime', native), patch.object(BattleBudget, '_write', fail_unsent):
                    code, report, _ = self.cli(folder, world, later, mode='--run')
                self.assertEqual((code, vetoes, starts), (1, ['epoch'], [(ECHO, 30), (FIRST, 10)]))
                self.assertEqual((report['stamina_spent'], report['stamina_pending'],
                                  report['immersifiers_pending']), (40, 40, tokens))
                saved = read(folder / 'runs' / 'battle-session.json')
                intent = saved['power_plan']['intent']
                self.assertEqual((intent['stamina'], intent['immersifiers']), (40, tokens))
                self.assertEqual(saved['power_plan']['done'], [1, 0])

    def test_followup_week_veto_after_payment_callback_is_recorded_as_unsent(self):
        from autohsr import du_periodic_points
        from autohsr.du_points_followup import FollowupWeek, followup_week_scope

        week = du_periodic_points.game_week(NOW)
        permission = FollowupWeek(week)
        clock = NOW
        world = BalanceWorld(CAVERN, None)
        starts, vetoes = [], []
        require_week = windows.require_followup_week

        @contextmanager
        def native(root, settings, value):
            with native_payment_window(root, settings, value, starts, vetoes) as (window, find):
                def late_week_check():
                    nonlocal clock
                    if world.settings.target_name == CAVERN and window.owner.report.stamina_pending == 40:
                        clock = NOW + timedelta(days=7)
                    require_week()

                with patch.object(windows, 'require_followup_week', late_week_check):
                    yield window, find

        with (patch(__name__ + '.runtime', native), patch.object(du_periodic_points, 'local_now', lambda: clock),
              followup_week_scope(permission)):
            code, report, _ = self.cli(self.root, world, row('cavern', 1, CAVERN, '残响回廊'), mode='--run')
        self.assert_stopped_with_prior_proof(self.root, world, code, report)
        self.assertTrue(permission.expired)
        self.assertEqual(starts, [(ECHO, 30), (FIRST, 10)])
        journal = read(self.root / 'runs' / 'battle-session.json')
        self.assertIsNone(journal['power_plan']['intent'])
        unsent, = [result for result in journal['power_plan']['results'] if result.get('reason') == 'payment_not_sent']
        self.assertTrue(read_ref(self.root / 'runs', unsent['evidence']).is_file())

    def test_support_day_rollover_after_payment_callback_retires_only_the_unsent_intent(self):
        later = row('cavern', 1, CAVERN, '残响回廊')
        for mode in ('--run', '--plan'):
            with self.subTest(mode=mode):
                folder = self.root / mode
                world = BalanceWorld(CAVERN, None)
                starts, vetoes = [], []
                day = NOW.date().isoformat()
                require_week = windows.require_followup_week

                @contextmanager
                def native(root, settings, value):
                    with native_payment_window(root, settings, value, starts, vetoes) as (window, find):
                        def after_payment_check():
                            nonlocal day
                            require_week()
                            if world.settings.target_name == CAVERN and window.owner.report.stamina_pending == 40:
                                day = (NOW + timedelta(days=1)).date().isoformat()
                                vetoes.append('day')

                        with (patch.object(windows, 'require_followup_week', after_payment_check),
                              patch('autohsr.daily_support.game_day', side_effect=lambda _now: day)):
                            yield window, find

                with patch(__name__ + '.runtime', native):
                    code, report, _ = self.cli(folder, world, later, mode=mode)
                self.assert_stopped_with_prior_proof(folder, world, code, report)
                self.assertEqual((starts, vetoes), ([(ECHO, 30), (FIRST, 10)], ['day']))
                self.assertIn('开始挑战未发送', report['error'])
                journal = read(folder / 'runs' / 'battle-session.json')
                self.assertIsNone(journal['power_plan']['intent'])
                unsent, = [result for result in journal['power_plan']['results'] if result.get('reason') == 'payment_not_sent']
                self.assertEqual((unsent['row'], unsent['requested'], unsent['completed']), (1, 1, 0))
                self.assertTrue(read_ref(folder / 'runs', unsent['evidence']).is_file())

    def test_planar_support_day_rollover_retires_both_unsent_resources(self):
        for mode, count, pending_stamina in (('--run', 1, 0), ('--plan', 2, 40)):
            with self.subTest(mode=mode, count=count):
                folder = self.root / mode
                world = BalanceWorld(PLANAR, None)
                world.tokens = 1
                starts, vetoes = [], []
                day = NOW.date().isoformat()
                require_week = windows.require_followup_week

                @contextmanager
                def native(root, settings, value):
                    with native_payment_window(root, settings, value, starts, vetoes,
                                               payment_target=PLANAR) as (window, find):
                        def cross_day_at_planar_payment():
                            nonlocal day
                            require_week()
                            report = window.owner.report
                            if world.settings.target_name == PLANAR and report.immersifiers_pending == 1:
                                self.assertEqual(report.stamina_pending, pending_stamina)
                                day = (NOW + timedelta(days=1)).date().isoformat()
                                vetoes.append('day')

                        with (patch.object(windows, 'require_followup_week', cross_day_at_planar_payment),
                              patch('autohsr.daily_support.game_day', side_effect=lambda _now: day)):
                            yield window, find

                later = row('planar', count, PLANAR, '永恒圣城')
                with patch(__name__ + '.runtime', native):
                    code, report, _ = self.cli(folder, world, later, mode=mode)
                self.assert_stopped_with_prior_proof(folder, world, code, report)
                self.assertEqual((starts, vetoes), ([(ECHO, 30), (FIRST, 10)], ['day']))
                self.assertEqual((report['immersifiers_spent'], report['immersifiers_pending']), (0, 0))
                journal = read(folder / 'runs' / 'battle-session.json')
                self.assertIsNone(journal['power_plan']['intent'])
                unsent, = [result for result in journal['power_plan']['results'] if result.get('reason') == 'payment_not_sent']
                self.assertEqual((unsent['row'], unsent['requested'], unsent['completed']), (1, count, 0))
                self.assertTrue(read_ref(folder / 'runs', unsent['evidence']).is_file())
                original_report = Path(journal['run_dir']) / 'report.json'
                original = original_report.read_bytes()
                code, resumed, _ = self.cli(folder, world, later, mode=mode, extra=('--new-battle-run',))
                self.assertEqual(code, 0, resumed['error'])
                self.assertEqual(resumed['power_plan']['before'], [1, 0])
                self.assertEqual(world.payments.count((PLANAR, count, pending_stamina, 1)), 1)
                self.assertEqual(original_report.read_bytes(), original)

    def test_planar_short_submission_keeps_mixed_payment_pending(self):
        world = BalanceWorld(PLANAR, 'partial_send')
        world.tokens = 1
        starts, vetoes = [], []
        later = row('planar', 2, PLANAR, '永恒圣城')

        def native(root, settings, value):
            return native_payment_window(root, settings, value, starts, vetoes, payment_target=PLANAR)

        with patch(__name__ + '.runtime', native):
            code, report, _ = self.cli(self.root, world, later, mode='--run')
        self.assertEqual((code, report['status']), (1, 'partial'))
        self.assertEqual((report['stamina_spent'], report['stamina_pending'], report['immersifiers_pending']), (40, 40, 1))
        self.assertEqual(report['power_plan']['done'], [1, 0])
        self.assertEqual(starts, [(ECHO, 30), (FIRST, 10), (PLANAR, 40)])
        self.assertNotIn(FILL, world.opened)
        journal = self.root / 'runs' / 'battle-session.json'
        original = journal.read_bytes()
        intent = read(journal)['power_plan']['intent']
        self.assertEqual((intent['count'], intent['stamina'], intent['immersifiers']), (2, 40, 1))
        code, _, finds = self.cli(self.root, world, later, mode='--run', extra=('--new-battle-run',))
        self.assertEqual((code, finds), (1, 0))
        self.assertEqual(journal.read_bytes(), original)

    def test_single_round_conflicting_result_keeps_intent_and_stops_before_fill(self):
        class WaveWorld(BalanceWorld):
            def __init__(self, observed):
                super().__init__(CALYX, None)
                self.observed = observed

            def scene(self, settings):
                page = super().scene(settings)
                if self.mode == 'success' and settings.target_name in (ECHO, CALYX):
                    page.tokens = [t for t in page.tokens if not t.text.startswith('本次挑战波次')]
                    page.tokens.append(Token('退出关卡', .99, (.32, .88, .42, .93)))
                    if settings.target_name == CALYX and self.observed is not None:
                        page.tokens.append(Token(f'上轮挑战波次：{self.observed}', .99, (.575, .793, .67, .826)))
                return page

        later = row(count=1, target=CALYX)
        for mode in ('--run', '--plan'):
            for observed in (None, 1, 2, 18, 24):
                with self.subTest(mode=mode, observed=observed):
                    folder = self.root / f'{mode}-{observed}'
                    world = WaveWorld(observed)
                    starts = []
                    with patch(__name__ + '.runtime', side_effect=lambda root, settings, value:
                               native_payment_window(root, settings, value, starts, [])):
                        code, report, _ = self.cli(folder, world, later, mode=mode)
                    expected_starts = [(ECHO, 30), (FIRST, 10), (CALYX, 10)]
                    if observed in (None, 1):
                        self.assertEqual((code, report['status']), (0, 'success'))
                        self.assertEqual(starts, [*expected_starts, (FILL, 10)])
                        self.assertEqual((report['stamina_spent'], report['stamina_pending']), (60, 0))
                        continue
                    self.assertEqual((code, report['status']), (1, 'partial'))
                    self.assertIn('波次', report['error'])
                    self.assertEqual(starts, expected_starts)
                    self.assertEqual(world.mode, 'success')
                    self.assertNotIn(FILL, world.opened)
                    path = folder / 'runs' / 'battle-session.json'
                    saved = read(path)
                    self.assertEqual((saved['spent'], saved['pending'], saved['completed']), (40, 10, 2))
                    plan = saved['power_plan']
                    self.assertEqual(plan['done'], [1, 0])
                    self.assertEqual([charge['row'] for charge in plan['charges']], [-2, 0])
                    self.assertEqual((plan['intent']['row'], plan['intent']['count']), (1, 1))
                    original = path.read_bytes()
                    code, blocked, finds = self.cli(folder, world, later, mode=mode, extra=('--new-battle-run',))
                    self.assertEqual((code, finds), (1, 0))
                    self.assertIn('待核对', blocked['error'])
                    self.assertEqual(path.read_bytes(), original)

    def test_explicit_next_budget_uses_original_confirmed_counts(self):
        folder = self.root / 'resume'
        world = BalanceWorld(CAVERN, 'missing_uid')
        later = row('cavern', 1, CAVERN, '残响回廊')
        code, original, _ = self.cli(folder, world, later, mode='--plan')
        self.assert_stopped_with_prior_proof(folder, world, code, original)
        runs = folder / 'runs'
        ledger = runs / 'battle-session.json'
        original_ledger = ledger.read_bytes()
        child = Path(original['weekly_plan']['children'][0]['run_dir']) / 'report.json'
        original_report = child.read_bytes()

        world.boundary, world.stamina = None, 90
        code, blocked, finds = self.cli(folder, world, later, mode='--run')
        self.assertEqual((code, finds), (1, 0))
        self.assertIn('明确确认新增预算', blocked['error'])
        self.assertEqual(ledger.read_bytes(), original_ledger)

        code, resumed, _ = self.cli(folder, world, later, mode='--plan', extra=('--new-battle-run',))
        self.assertEqual(code, 0, resumed.get('error'))
        self.assertEqual(world.paid, [(ECHO, 1, 30), (FIRST, 1, 10), (CAVERN, 1, 40), (FILL, 1, 10)])
        self.assertEqual((resumed['battle_completed'], resumed['stamina_spent']), (2, 50))
        self.assertEqual(resumed['power_plan']['before'], [1, 0])
        self.assertEqual(resumed['power_plan']['done'], [0, 1])
        self.assertEqual(resumed['power_plan']['weekly_echo']['completed'], 0)
        self.assertTrue(resumed['power_plan']['goal_complete'])
        self.assertEqual(child.read_bytes(), original_report)
        archive, = (runs / 'power-plans').rglob(original['power_plan']['run'] + '.json')
        self.assertEqual(read(archive), json.loads(original_ledger))
