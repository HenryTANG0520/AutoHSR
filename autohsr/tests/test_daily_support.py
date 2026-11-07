"""Replay support-training fields and exercise real Context with fake inputs."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import windows
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.currency_wars_identity import account_key
from autohsr.daily_support import ACTIVITY, Decision, observe, read_state
from autohsr.du_daily import CHINA
from autohsr.models import AutomationError, RunReport, Scene, Token, normalize
from autohsr.planar_team import entry as planar_preset_entry
from autohsr.recovery import BattleBudget
from autohsr.tests import test_core as core, test_power_plan as battles
from autohsr.tests.test_du_team import fixture as team_fixture
from autohsr.workflow_identity import account_scope
from autohsr.workflows import DailyWorkflow


FIXTURE = Path(__file__).parent/'fixtures/daily_support_cards.json'


def training(name='needed_400'):
    rows = json.loads(FIXTURE.read_text('utf8'))['scenes'][name]['tokens']
    return Scene([Token(text, score, tuple(box)) for text, score, box in rows])


class DailySupportReadingTests(unittest.TestCase):
    def test_observed_pending_and_activity_full_before_looking_at_the_card(self):
        self.assertEqual(read_state(training(), badge_verified=True), ('needed', 400))
        for name in ('full_pending', 'full_completed_third', 'full_completed_fourth'):
            with self.subTest(name=name):
                self.assertEqual(read_state(training(name)), ('activity_full', 500))
        self.assertEqual(read_state(training()), ('unknown', None))

    def test_same_column_completion_is_distinct_from_the_activity_cap(self):
        for name in ('full_completed_third', 'full_completed_fourth'):
            with self.subTest(name=name):
                page = training(name)
                page.tokens = [replace(token, text='400') if token.within(ACTIVITY) else
                               replace(token, text='领取') if token.text=='本日活跃度已满' else token
                               for token in page.tokens]
                self.assertEqual(read_state(page, badge_verified=True), ('completed', 400))

    def test_missing_conflicting_low_confidence_and_adjacent_card_fields_are_unknown(self):
        page = training()
        status = next(token for token in page.tokens if token.text=='进行中' and .33<token.center[0]<.45)
        part = next(token for token in page.tokens if token.text=='得战斗胜利1次')
        progress = next(token for token in page.tokens if token.text=='进度0/1' and .33<token.center[0]<.45)
        for old, new in ((status, None), (part, replace(part, score=.8)),
                         (status, replace(status, box=(.53,.747,.60,.78))),
                         (progress, replace(progress, text='进度1/1')),
                         (status, replace(status, text='本日活跃度已满'))):
            with self.subTest(token=old.text, value=new):
                changed = Scene([token for token in page.tokens if token is not old] + ([new] if new else []))
                self.assertEqual(read_state(changed, badge_verified=True)[0], 'unknown')

    def test_training_capture_is_bound_to_the_real_four_am_boundary(self):
        page = training()
        page.tokens.append(Token('UID:123456789', .99, (.01,.96,.22,.99)))
        ctx = SimpleNamespace(last_scene=page, scene_epoch=0, runner=SimpleNamespace(input_epoch=0),
                              report=RunReport(), checkpoint=Mock())
        workflow = SimpleNamespace(ctx=ctx, settings=Settings(), _open_guide=Mock(return_value=page),
                                   _icon=Mock(return_value=(.18,.29,.98)))
        with patch('autohsr.daily_support.datetime') as clock, patch('autohsr.daily_support.monotonic', return_value=10):
            clock.now.return_value = datetime(2026,11,5,4,0,0,100000,tzinfo=CHINA)
            page.captured_at = 9.8
            with self.assertRaisesRegex(AutomationError, '跨游戏日'):
                observe(workflow)
            self.assertEqual(ctx.report.support_selections, [])
            page.captured_at = 9.95
            self.assertEqual(observe(workflow).day, '2026-11-05')


class DailySupportNativeTests(unittest.TestCase):
    def test_last_window_check_preserves_scope_and_vetoes_stale_input(self):
        geometry = windows.Geometry(40, 30, 960, 540)
        for name, change in (('click', 'day'), ('click', 'epoch'), ('click', 'account'),
                             ('click', 'stop'), ('click', 'emergency'), ('click', 'focus'), ('esc', 'day'),
                             ('click', None), ('esc', None)):
            with self.subTest(action=name, change=change):
                target = Token('支援', .99, (.65, .84, .73, .89))
                scene = Scene([target, Token('队伍', .99, (.08, .04, .13, .08)),
                               Token('UID:123456789', .99, (.01, .96, .16, .99))],
                              geometry=geometry, captured_at=time.monotonic())
                day = '2026-11-06'
                decision = Decision('needed', day, account_key(scene), 0, .85)
                runner = SimpleNamespace(settings=Settings(), report=RunReport(operation='daily'),
                                         input_epoch=0, stop_requested=False, checkpoint=Mock(), log=Mock(),
                                         wait_for_focus=Mock())
                window = windows.GameWindow.__new__(windows.GameWindow)
                window.hwnd = 71
                native = Mock()
                native.IsWindow.return_value = 1
                native.IsIconic.return_value = 0
                native.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__
                native.GetAsyncKeyState.return_value = 0
                native.MapVirtualKeyW.return_value = 1
                native.SendInput.side_effect = lambda size, *_: size
                scope = SimpleNamespace(require=Mock())

                def foreground():
                    nonlocal day
                    if native.GetForegroundWindow.call_count == (1 if name == 'esc' else 2):
                        if change == 'day':
                            day = '2026-11-07'
                        elif change == 'epoch':
                            runner.input_epoch += 1
                        elif change == 'account':
                            scene.tokens.append(Token('UID:987654321', .74, (.01, .96, .17, .99)))
                        elif change == 'stop':
                            runner.stop_requested = True
                    if change == 'emergency' and native.GetForegroundWindow.call_count == 3:
                        native.GetAsyncKeyState.return_value = 0x8000
                    if change == 'focus' and native.GetForegroundWindow.call_count == 3:
                        return window.hwnd + 1
                    return window.hwnd

                native.GetForegroundWindow.side_effect = foreground
                with (account_scope(scope), patch.object(windows, 'user32', native),
                      patch.object(windows, 'geometry', return_value=geometry), patch('autohsr.windows.time.sleep'),
                      patch('autohsr.daily_support.game_day', side_effect=lambda _now: day)):
                    ctx = Context(runner, window, Mock())
                    outer = ctx.window
                    ctx.last_scene = scene
                    ctx.sleep = Mock()
                    with decision.inputs(ctx):
                        submit = (lambda: ctx.key('esc')) if name == 'esc' else (lambda: ctx.click(scene, target))
                        if change is not None:
                            with self.assertRaises(AutomationError):
                                submit()
                            native.SendInput.assert_not_called()
                        else:
                            submit()
                            sizes = [call.args[0] for call in native.SendInput.call_args_list]
                            self.assertEqual(sizes, [1, 1] if name == 'esc' else [3])
                    self.assertIs(ctx.window, outer)
                    scope.require.assert_called_once_with(ctx)


class World(battles.World):
    def __init__(self, card):
        super().__init__(stamina=80)
        self.card, self.borrowed, self.opened_guide = card, False, 0
        self.old_planar_support = self.conflicting_uid = False

    def scene(self, settings):
        if self.mode == 'training':
            page = training(self.card)
            if self.card=='needed_400' and getattr(self, 'unknown', False):
                page.tokens = [token for token in page.tokens if token.text != '得战斗胜利1次']
        elif self.mode in ('picker', 'selected'):
            page = core.support_picker(marker='green' if self.mode=='selected' else None)
        else:
            page = super().scene(settings)
            if self.mode=='team':
                page.tokens += [core.token('队伍', .10,.06),
                                core.token('解除支援' if self.old_planar_support else '支援', .70,.86)]
                if self.borrowed:
                    page = core.support_marker(page)
                if self.conflicting_uid:
                    page.tokens.append(Token('UID:987', .65, (.02,.94,.12,.96)))
            return page
        page.tokens.append(Token('UID:'+self.uid, .99, (.01,.96,.22,.99)))
        return page


class Screens(battles.Screens):
    _team_page = DailyWorkflow._team_page

    def _open_guide(self, name):
        if name != '每日实训':
            raise AssertionError(name)
        self.ctx.world.opened_guide += 1
        self.ctx.world.mode = 'training'
        return self.ctx.snapshot()


class PresetWorld(World):
    def __init__(self, card):
        super().__init__(card)
        self.prepare = team_fixture('planar_preparation')
        self.listing = team_fixture('planar_preset_list')
        self.enabled = team_fixture('planar_preset_enabled')
        self.preset_returned = False
        self.support_control_hidden = False
        self.old_planar_marker = False

    def scene(self, settings):
        if self.mode in ('preset_panel', 'preset_list', 'preset_enabled'):
            source = self.enabled if self.mode=='preset_enabled' else self.listing
            tokens = [token for token in source.tokens if not normalize(token.text).startswith('uid')]
            tokens.append(Token('UID:'+self.uid, .99, (.01,.96,.22,.99)))
            return Scene(tokens, source.image)
        page = super().scene(settings)
        if self.mode=='team':
            page.image = self.prepare.image
            if not self.old_planar_support and (not self.preset_returned or self.support_control_hidden):
                page.tokens = [token for token in page.tokens if token.text!='支援']
            if self.old_planar_marker:
                page.tokens.append(Token('支援', .99, (.375,.78,.395,.8)))
                page.image = page.image.copy()
                page.image[842:864,720:760] = (65,150,75)
        return page


class DailySupportContextTests(unittest.TestCase):
    def run_battle(self, *, card='needed_400', category='calyx_golden', event=None,
                   use_support=True, support_daily_only=True):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        planar = category=='planar'
        world = PresetWorld(card) if planar else World(card)
        world.unknown = event=='unknown'
        world.old_planar_support = event=='old_planar_support'
        world.conflicting_uid = event=='conflicting_uid'
        world.support_control_hidden = event=='planar_hidden_support_control'
        world.old_planar_marker = event=='old_planar_marker'
        if event=='changed_account_before_preset':
            world.on_open = lambda value: setattr(value, 'uid', '987654321')
        settings = Settings(dungeon_category=category, challenge_count=1, stamina_limit=80,
                            daily_synthesis=False, use_support=use_support, support_daily_only=support_daily_only)
        report = RunReport(operation='daily', run_dir=str(root/'attempt'))
        budget = BattleBudget(root, settings, report)
        budget.begin()
        day = '2026-11-04'
        click_labels = []

        def log(message, *args):
            nonlocal day
            if ((event=='day_at_support' and message=='点击：支援')
                    or (event=='day_in_preset' and message=='点击：预设编队')
                    or (event=='day_at_payment' and message=='点击：开始挑战')):
                day = '2026-11-05'

        runner = SimpleNamespace(settings=settings, report=report, input_epoch=0,
                                 checkpoint=Mock(), log=log)
        window = Mock()
        vision = SimpleNamespace(read=Mock(),
            template=lambda scene, path, roi, threshold: (.18,.29,.98) if path.stem=='daily_activity_badge' else None,
            planar_payment=lambda scene: battles.FakeContext.planar_payment(None, scene),
            refine_planar_support=Mock())
        ctx = Context(runner, window, vision)
        ctx.world, ctx.battle_budget = world, budget
        ctx.sleep = Mock()

        def evidence(scene, label):
            nonlocal day
            if event=='day_at_preset_close' and label=='planar_preset_team_verified':
                day = '2026-11-05'
            return 'fixture.png'

        ctx.evidence = Mock(side_effect=evidence)
        window.capture.side_effect = lambda: (world.scene(settings).image, None)
        vision.read.side_effect = lambda image, geometry: world.scene(settings)

        def click(x, y, geometry):
            scene = ctx.last_scene
            if planar and world.mode=='team' and (x,y)==planar_preset_entry(scene).center:
                click_labels.append('preset_open')
                world.mode = 'preset_panel'
                if event=='epoch_in_preset':
                    runner.input_epoch += 1
                return
            target = next(token for token in scene.tokens if abs(token.center[0]-x)<1e-6 and abs(token.center[1]-y)<1e-6)
            click_labels.append(target.text)
            if world.mode=='preset_panel' and target.text=='预设编队':
                world.mode = 'preset_list'
                if event=='changed_account_in_preset':
                    world.uid = '987654321'
            elif world.mode=='preset_list' and target.text==settings.differential_universe_team:
                world.mode = 'preset_enabled'
            elif world.mode=='team' and target.text=='支援':
                world.mode = 'picker'
            elif world.mode=='picker' and target.text=='好友':
                world.mode = 'selected'
            elif world.mode=='selected' and target.text=='确认':
                world.mode, world.borrowed = 'team', True
            else:
                driver = battles.FakeContext(world, settings, report, budget)
                driver.last_scene = scene
                driver.click(scene, target)
                if event=='changed_account' and target.text=='挑战':
                    world.uid = '987654321'

        def key(name):
            self.assertEqual((name, world.mode), ('esc', 'preset_enabled'))
            click_labels.append(name)
            world.mode, world.preset_returned = 'team', True

        window.click.side_effect = click
        window.key.side_effect = key
        flow = Screens(ctx)
        with patch('autohsr.daily_support.game_day', side_effect=lambda _now=None: day):
            if event:
                with self.assertRaises(AutomationError):
                    flow.battle()
            else:
                self.assertEqual(flow.battle().status, 'ok')
        self.assertIs(ctx.window, window)
        self.assertNotIn('UID', json.dumps(report.support_selections))
        self.assertNotIn(world.uid, json.dumps(report.support_selections))
        return world, report, click_labels

    def test_ordinary_only_borrows_when_the_current_card_requires_it(self):
        world, report, clicks = self.run_battle()
        self.assertEqual(clicks, ['挑战', '支援', '好友', '确认', '开始挑战'])
        self.assertEqual((report.battle_completed, report.stamina_spent), (1, 10))
        self.assertEqual(report.support_selections[0]['state'], 'needed')

    def test_planar_at_cap_skips_borrowing_but_checks_and_records_payment(self):
        world, report, clicks = self.run_battle(card='full_pending', category='planar')
        self.assertEqual(clicks, ['preset_open', '预设编队', '哈哈哈哈', 'esc', '开始挑战'])
        self.assertEqual((report.battle_completed, report.stamina_spent), (1, 40))
        self.assertEqual(report.support_selections[0]['state'], 'activity_full')
        self.assertTrue(report.team_selections[0]['verified'])

    def test_planar_without_daily_only_retains_original_preset_and_payment(self):
        world, report, clicks = self.run_battle(category='planar', use_support=False, support_daily_only=False)
        self.assertEqual(clicks, ['preset_open', '预设编队', '哈哈哈哈', 'esc', '开始挑战'])
        self.assertEqual((world.opened_guide, report.support_selections, report.stamina_spent), (0, [], 40))

    def test_main_support_switch_off_does_not_even_open_the_training_page(self):
        world, report, clicks = self.run_battle(use_support=False)
        self.assertEqual(world.opened_guide, 0)
        self.assertEqual(report.support_selections, [])
        self.assertEqual(clicks, ['挑战', '开始挑战'])

    def test_planar_at_cap_with_old_borrowed_role_does_not_clear_it_or_pay(self):
        for event in ('old_planar_support', 'old_planar_marker'):
            with self.subTest(event=event):
                world, report, clicks = self.run_battle(card='full_pending', category='planar', event=event)
                self.assertEqual((clicks, world.paid, report.stamina_pending, report.team_selections), ([], [], 0, []))

    def test_planar_identity_day_and_epoch_are_rechecked_at_each_preset_input(self):
        for event, expected in (('changed_account_before_preset', []),
                                ('changed_account_in_preset', ['preset_open', '预设编队']),
                                ('day_in_preset', ['preset_open']), ('epoch_in_preset', ['preset_open'])):
            with self.subTest(event=event):
                world, report, clicks = self.run_battle(card='full_pending', category='planar', event=event)
                self.assertEqual((clicks, world.paid, report.stamina_pending, report.team_selections),
                                 (expected, [], 0, []))

    def test_planar_day_change_at_close_preserves_verified_preset_without_sending_escape(self):
        world, report, clicks = self.run_battle(card='full_pending', category='planar', event='day_at_preset_close')
        self.assertEqual(clicks, ['preset_open', '预设编队', '哈哈哈哈'])
        self.assertTrue(report.team_selections[0]['verified'])
        self.assertEqual((world.paid, report.stamina_pending), ([], 0))

    def test_planar_missing_support_control_after_preset_does_not_authorize_payment(self):
        world, report, clicks = self.run_battle(card='full_pending', category='planar', event='planar_hidden_support_control')
        self.assertEqual(clicks, ['preset_open', '预设编队', '哈哈哈哈', 'esc'])
        self.assertEqual((world.paid, report.stamina_pending), ([], 0))

    def test_unknown_day_rollover_and_account_change_do_not_submit(self):
        for event, expected in (('unknown', []), ('changed_account', ['挑战']),
                                ('conflicting_uid', ['挑战']), ('day_at_support', ['挑战']),
                                ('day_at_payment', ['挑战', '支援', '好友', '确认'])):
            with self.subTest(event=event):
                world, report, clicks = self.run_battle(event=event)
                self.assertEqual(clicks, expected)
                self.assertEqual(world.paid, [])
                self.assertEqual((report.stamina_spent, report.stamina_pending), (0, 10 if event=='day_at_payment' else 0))


class DailySupportCLITests(unittest.TestCase):
    def test_flag_is_transient_and_respects_the_main_support_switch(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'settings.json'
            Settings(use_support=False).save(path)
            before = path.read_bytes()
            with patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()):
                runner.return_value.run.return_value = RunReport(status='success')
                self.assertEqual(main(['--run', '--support-daily-only', '--config', str(path)]), 0)
            selected = runner.call_args.args[0]
            self.assertIs(selected.support_daily_only, True)
            self.assertIs(selected.use_support, False)
            self.assertEqual(path.read_bytes(), before)
            self.assertIs(Settings.load(path).support_daily_only, False)

    def test_flag_reaches_the_plan_daily_settings_without_saving(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'settings.json'
            Settings().save(path)
            before = path.read_bytes()
            with patch('autohsr.plan_runner.PlanRunner') as runner, redirect_stdout(io.StringIO()):
                runner.return_value.run.return_value = RunReport(status='success')
                self.assertEqual(main(['--plan', '--support-daily-only', '--config', str(path)]), 0)
            self.assertIs(runner.call_args.args[0].support_daily_only, True)
            self.assertIs(runner.call_args.args[0].use_support, True)
            self.assertEqual(path.read_bytes(), before)

    def test_reward_only_and_independent_modes_reject_the_flag_before_runner(self):
        from autohsr.__main__ import main
        for args in (['--run','--reward-only'], ['--differential-universe'], ['--plan','--resume-weekly-currency']):
            with self.subTest(args=args), patch('autohsr.app.Runner') as runner, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    main([*args, '--support-daily-only'])
                self.assertEqual(error.exception.code, 2)
                runner.assert_not_called()
