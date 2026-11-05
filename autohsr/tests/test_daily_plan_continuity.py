"""Formal CLI with a fake window, real shared budget and training decision."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
import io
from itertools import count
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
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


@contextmanager
def native_payment_window(root, settings, world, starts, vetoes):
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
            return active is not None and active.text == '开始挑战' and world.settings.target_name == CAVERN

        def key_state(_):
            if is_later_payment() and world.boundary == 'late_epoch' and not vetoes:
                window.owner.input_epoch += 1
                vetoes.append('epoch')
            return 0

        def send(count, payload, _):
            assert count == 3 and [item.mi.dwFlags for item in payload] == [0xC001, 2, 4]
            driver = FakeContext(world, world.settings, window.owner.report, window.owner.battle_budget)
            driver.last_scene = screen.scene
            if active.text == '开始挑战':
                starts.append((world.settings.target_name, window.owner.report.stamina_pending))
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

    def cli(self, folder, world, later, *, mode, extra=()):
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
                  patch('autohsr.workflows.DailyWorkflow', NativeTrainingScreens), redirect_stdout(output),
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
        later = row('cavern', 1, CAVERN, '残响回廊')
        world = BalanceWorld(CAVERN, 'late_epoch')
        starts, vetoes = [], []
        write = BattleBudget._write

        def fail_unsent(budget, *args, **kwargs):
            if any(result.get('reason') == 'payment_not_sent' for result in budget.report.power_plan.get('results', [])):
                raise OSError('fixture unsent receipt write failed')
            return write(budget, *args, **kwargs)

        def native(root, settings, value):
            return native_payment_window(root, settings, value, starts, vetoes)

        with patch(__name__ + '.runtime', native), patch.object(BattleBudget, '_write', fail_unsent):
            code, report, _ = self.cli(self.root, world, later, mode='--run')
        self.assertEqual((code, vetoes, starts), (1, ['epoch'], [(ECHO, 30), (FIRST, 10)]))
        self.assertEqual((report['stamina_spent'], report['stamina_pending']), (40, 40))
        saved = read(self.root / 'runs' / 'battle-session.json')
        self.assertEqual(saved['power_plan']['intent']['stamina'], 40)
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
