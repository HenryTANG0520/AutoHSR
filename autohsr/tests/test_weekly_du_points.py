"""Native CLI and weekly receipts with public DU fields and synthetic IO."""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import io
from itertools import count
import json
import os
from pathlib import Path
import tempfile
from time import time as wall_time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.du_daily import account_key
from autohsr.du_reward_store import NAME as REWARD_SESSION
from autohsr.du_rewards_only import RewardWorkflow
from autohsr.models import AutomationError, Scene, TaskResult
from autohsr.plan_runner import PlanRunner
from autohsr.tests.test_du_periodic_points import ACCOUNT, OTHER, token, with_account
from autohsr.tests.test_du_periodic_rewards import points_home, points_panel, twice
from autohsr.tests.test_du_rewards_only import overlay
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_weekly_plan import du_report
from autohsr.weekly_plan import CHINA, WeeklyGuard, WeeklyReceipt, weekly_slot
from autohsr.windows import Geometry


CLAIM_WEEKLY = '--du-claim-weekly-rewards'


class WeeklyDuPointsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.runs = self.root / 'runs'
        self.settings = Settings(weekly_enabled=True, weekly_runs=3, assignments=False, battle=False,
                                 daily=False, overlay_logs=False, differential_universe_runs=7)
        self.now = datetime(2026, 11, 6, 9, 30, tzinfo=CHINA)
        self.home_tokens = fixture('fit_65_red_after_steady').tokens
        self.image = np.zeros((180, 320, 3), dtype=np.uint8)
        self.geometry = Geometry(0, 0, 320, 180)

    def home(self, current=18000, account=ACCOUNT):
        fields = [t for t in self.home_tokens if t.text != '18000/18000']
        return Scene([*fields, token(f'{current}/18000', .113, .904, .207, .947), account],
                     self.image, self.geometry)

    def win_frames(self, current):
        setup = with_account(fixture('periodic_setup'), ACCOUNT)
        field = Scene([token('(1/13)第一位面-战斗', .04, .028, .24, .05)])
        return [self.home(8000)] * 5 + [setup, field, self.home(current), self.home(current)]

    @contextmanager
    def runtime(self, pages):
        owner = self

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return owner.now.astimezone(tz) if tz else owner.now.replace(tzinfo=None)

        window = Mock(hwnd=123)
        window.capture.return_value = self.image, self.geometry
        frames = iter(pages)
        ticks = count(100, .01)
        clock = SimpleNamespace(monotonic=lambda: next(ticks), time=wall_time)
        sent = []

        def read(image, geometry):
            page = next(frames, None)
            if page is None:
                raise AutomationError('synthetic capture sequence exhausted')
            return Scene(list(page.tokens), image if page.image is None else page.image, geometry)

        def click(x, y, geometry, *, before_send=None):
            if before_send is not None:
                before_send()
            sent.append((x, y))

        def launch(flow, _scene, _kind):
            scene = flow.ctx.snapshot()
            flow.report['difficulty_selection'] = dict(verified=True, requested_rank=5, displayed_rank_after=5)
            target = scene.find('启动「差分宇宙」', exact=True)
            return flow._click(scene, target, intent='periodic_start', label='periodic_run_started')

        def win(flow, scene, _kind):
            entry = flow.report['run_results'][-1]
            flow._record_completion_image(entry, scene, 'victory', f"du_{flow.report['current_run']:02d}_victory")
            return flow.ctx.snapshot(), 'home', True

        window.click.side_effect = click
        vision = Mock()
        vision.read.side_effect = read
        with ExitStack() as stack:
            stack.enter_context(patch('autohsr.app.ROOT', self.root))
            stack.enter_context(patch('autohsr.plan_runner.ROOT', self.root))
            stack.enter_context(patch('autohsr.weekly_plan.datetime', Clock))
            stack.enter_context(patch('autohsr.du_periodic_points.local_now', lambda: self.now))
            stack.enter_context(patch('autohsr.du_periodic_rewards.local_now', lambda: self.now))
            for module in ('app', 'differential_universe', 'du_periodic_points', 'du_periodic_rewards',
                           'du_rewards_only', 'workflow_identity'):
                stack.enter_context(patch(f'autohsr.{module}.time', clock))
            stack.enter_context(patch('autohsr.app.find_game', return_value=window))
            stack.enter_context(patch('autohsr.app.Vision', return_value=vision))
            stack.enter_context(patch('autohsr.app.is_elevated', return_value=False))
            stack.enter_context(patch('autohsr.app.threading.Thread'))
            stack.enter_context(patch('autohsr.app.C.get_last_error', return_value=0))
            stack.enter_context(patch('autohsr.windows.kernel32', Mock(CreateMutexW=Mock(return_value=1))))
            stack.enter_context(patch.object(Runner, '_arm_hotkeys'))
            stack.enter_context(patch.object(Context, 'sleep', lambda ctx, seconds: ctx.checkpoint()))
            stack.enter_context(patch('autohsr.workflows.DailyWorkflow.ensure_main'))
            stack.enter_context(patch.object(DifferentialUniverseWorkflow, '_prepare_and_start', launch))
            stack.enter_context(patch.object(DifferentialUniverseWorkflow, '_progress_run', win))
            yield window, sent

    def cli(self, *, points=True, extra=()):
        config = self.root / 'config.json'
        self.settings.save(config)
        original = config.read_bytes()
        output, logs = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(logs):
            args = ['--plan', '--config', str(config), *extra]
            code = main(args + ['--du-until-points'] if points else args)
        self.assertEqual(config.read_bytes(), original)
        return code, json.loads(output.getvalue() or logs.getvalue())

    def receipt(self):
        slot = weekly_slot(self.settings, self.now)
        return WeeklyReceipt(self.runs, account_key(self.home()), slot).path

    def reward_receipt(self):
        goal = self.receipt()
        return goal.parent / 'periodic-rewards' / goal.name

    def reward_frames(self, *, account=ACCOUNT):
        def page_in_week(scene):
            fields = [replace(value, text=value.text.replace('6天18小时', '2天18小时'))
                      for value in scene.tokens if not value.text.startswith('UID')]
            return Scene([*fields, account], scene.image)

        ready = page_in_week(points_home(True))
        return [ready, ready, *twice(ready), *twice(page_in_week(points_panel())), *twice(overlay()),
                *twice(page_in_week(points_panel(claimed=True))), *twice(page_in_week(points_home(False)))]

    @contextmanager
    def reward_runtime(self, frames, *, before_reward_send=lambda: None, native_submit=lambda: None):
        with self.runtime(frames) as (window, starts):
            raw = windows.GameWindow.__new__(windows.GameWindow)
            raw.guard = lambda _expected=None: self.geometry
            raw.emergency_pressed = lambda: False
            original_click = window.click.side_effect
            batches = []

            def send(size, *_):
                native_submit()
                batches.append(size)
                return size

            def click(x, y, geometry, *, before_send=None, before_submit=None):
                if before_submit is None:
                    return original_click(x, y, geometry, before_send=before_send)
                # The last F10 query follows authorization and the foreground
                # guard, and precedes the final capture/week checks.
                window.emergency_pressed.side_effect = before_reward_send
                return raw.click(x, y, geometry, before_submit=before_submit)

            native = SimpleNamespace(SendInput=send, MapVirtualKeyW=lambda *_: 1,
                                     GetSystemMetrics=lambda i: {76:0, 77:0, 78:320, 79:180}[i])
            window.click.side_effect = click
            window.key.side_effect = raw.key
            with patch.object(windows, 'user32', native):
                yield starts, batches

    def test_opt_in_zero_run_claim_and_read_only_same_week_reuse(self):
        self.settings = replace(self.settings, differential_universe_station_custom=True,
                                differential_universe_station_reroll=True)
        with self.reward_runtime([self.home()] * 5 + self.reward_frames()) as (starts, sends):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual(code, 0, report.get('error'))
        self.assertEqual((starts, sends), ([], [3, 3, 3, 1, 1]))
        summary = report['weekly_plan']
        self.assertTrue(summary['points_capped'])
        self.assertEqual(summary['goal_receipt_state'], 'complete')
        self.assertTrue(summary['score_rewards_verified'])
        self.assertTrue(summary['score_rewards_delivery_verified'])
        self.assertTrue(summary['score_rewards_home_verified'])
        self.assertEqual(summary['score_rewards_receipt_state'], 'complete')
        self.assertEqual(summary['completed_runs'], 0)
        paths = (self.receipt(), self.reward_receipt(), self.runs / REWARD_SESSION)
        originals = [path.read_bytes() for path in paths]
        reward = json.loads(originals[1])
        self.assertEqual(reward['source']['receipt_sha256'], hashlib.sha256(originals[0]).hexdigest())
        self.assertEqual(reward['journal_sha256'], hashlib.sha256(originals[2]).hexdigest())

        # A later standalone native run may replace the canonical pointer.
        # The weekly receipt references the original journal, not that pointer.
        (self.runs / REWARD_SESSION).unlink()
        with self.reward_runtime([self.home()] * 3) as (starts, sends):
            code, replay = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual(code, 0, replay.get('error'))
        self.assertEqual((starts, sends), ([], []))
        self.assertEqual(replay['weekly_plan']['score_rewards_receipt_state'], 'reused')
        self.assertEqual([path.read_bytes() for path in paths[:2]], originals[:2])

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing locks')
    def test_win_then_claim_holds_all_original_goal_sources_at_native_send(self):
        goal = self.receipt()
        sources = []
        denied = []

        def try_write_at_send():
            if sources:
                return
            original = json.loads(goal.read_bytes())
            sources.extend([goal, Path(original['report']), Path(original['ledger']['path']),
                            *map(Path, original['evidence'])])
            for path in sources:
                try:
                    with path.open('r+b'):
                        pass
                except PermissionError:
                    denied.append(path)

        with self.reward_runtime(self.win_frames(18000) + self.reward_frames(),
                                 native_submit=try_write_at_send) as (starts, sends):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual(code, 0, report.get('error'))
        self.assertEqual((len(starts), sends), (1, [3, 3, 3, 1, 1]))
        self.assertEqual(denied, sources)
        self.assertTrue(sources)
        self.assertEqual(report['weekly_plan']['completed_runs'], 1)

    def test_old_points_only_receipt_does_not_start_a_reward_child(self):
        with self.runtime([self.home()] * 5):
            code, _ = self.cli()
        self.assertEqual(code, 0)
        raw = self.receipt().read_bytes()
        with self.reward_runtime([self.home()] * 3) as (starts, sends):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], []))
        self.assertEqual(self.receipt().read_bytes(), raw)
        self.assertTrue(report['weekly_plan']['points_capped'])
        self.assertEqual(len(report['weekly_plan']['children']), 1)
        self.assertFalse(self.reward_receipt().exists())

    def test_two_different_uid_candidates_cannot_relabel_a_weekly_reward_receipt(self):
        with self.reward_runtime([self.home()] * 5 + self.reward_frames()):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual(code, 0, report.get('error'))
        receipt = self.reward_receipt()
        original = receipt.read_bytes()
        # The strict reader can see OTHER below y=.94, while the legacy
        # reader would read ACCOUNT farther right and below y=.95.
        mixed = self.home(account=replace(OTHER, box=(.02, .942, .13, .952)))
        mixed.tokens.append(replace(ACCOUNT, box=(.25, .959, .32, .983)))
        with self.reward_runtime([self.home(account=OTHER)] * 2 + [mixed]) as (starts, sends):
            code, rejected = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], []))
        self.assertFalse(rejected['weekly_plan']['score_rewards_verified'])
        self.assertEqual(receipt.read_bytes(), original)

    def test_account_change_at_reward_child_cannot_open_panel(self):
        with self.reward_runtime([self.home()] * 5 + self.reward_frames(account=OTHER)) as (starts, sends):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], []))
        self.assertTrue(report['weekly_plan']['points_capped'])
        self.assertFalse(report['weekly_plan']['score_rewards_verified'])
        self.assertTrue(report['execution_identity']['account_changed'])
        self.assertFalse(self.reward_receipt().exists())

    def test_goal_image_changed_after_receipt_blocks_reward_before_child(self):
        complete = WeeklyGuard.complete

        def change(guard, report, **kwargs):
            result = complete(guard, report, **kwargs)
            source = next(iter(guard.receipt.data['evidence']))
            Path(source).write_bytes(b'synthetic source replacement')
            return result

        with (self.reward_runtime([self.home()] * 5) as (starts, sends),
              patch.object(WeeklyGuard, 'complete', change)):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], []))
        self.assertEqual(len(report['weekly_plan']['children']), 1)
        self.assertEqual(json.loads(self.receipt().read_bytes())['state'], 'complete')
        self.assertFalse((self.runs / REWARD_SESSION).exists())

    def test_original_week_checked_after_last_f10_query_before_send(self):
        original = self.receipt()

        def cross_week():
            self.now = datetime(2026, 11, 9, 4, tzinfo=CHINA)
            return False

        with self.reward_runtime([self.home()] * 5 + self.reward_frames(),
                                 before_reward_send=cross_week) as (starts, sends):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], []))
        self.assertTrue(report['weekly_plan']['points_capped'])
        self.assertFalse(report['weekly_plan']['score_rewards_delivery_verified'])
        self.assertEqual(json.loads(original.read_bytes())['state'], 'complete')
        self.assertFalse(self.receipt().exists())

    def test_late_f10_stops_the_weekly_claim_packet(self):
        checks = 0

        def f10():
            nonlocal checks
            checks += 1
            return checks == 2

        with self.reward_runtime([self.home()] * 5 + self.reward_frames(),
                                 before_reward_send=f10) as (starts, sends):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends, checks), (1, [], [3], 2))
        self.assertEqual(report['status'], 'stopped')
        summary = report['weekly_plan']
        self.assertTrue(summary['points_capped'])
        self.assertFalse(summary['score_rewards_delivery_verified'])
        self.assertFalse(self.reward_receipt().exists())
        native = json.loads((self.runs / REWARD_SESSION).read_bytes())
        self.assertEqual([step['status'] for step in native['actions']], ['verified', 'unknown'])
        self.assertEqual(native['actions'][-1]['request']['intent'], 'du_reward_periodic_claim')

    def test_stop_after_delivery_preserves_original_goal_and_blocks_replay(self):
        back = RewardWorkflow._back

        def stop(flow, scene, destination, check=None):
            if flow.data.get('periodic_rewards_verified') is True:
                flow.c.runner.stop()
            return back(flow, scene, destination, check)

        with (self.reward_runtime([self.home()] * 5 + self.reward_frames()) as (starts, sends),
              patch.object(RewardWorkflow, '_back', stop)):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], [3, 3, 3]))
        self.assertEqual(report['status'], 'stopped')
        summary = report['weekly_plan']
        self.assertTrue(summary['points_capped'])
        self.assertTrue(summary['score_rewards_delivery_verified'])
        self.assertFalse(summary['score_rewards_home_verified'])
        self.assertEqual(summary['score_rewards_receipt_state'], 'stopped')
        self.assertFalse(self.reward_receipt().exists())
        goal, native = self.receipt(), self.runs / REWARD_SESSION
        original = goal.read_bytes(), native.read_bytes()
        with self.reward_runtime([]) as (starts, sends):
            code, retry = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], []))
        self.assertIn('待核对', retry['error'])
        self.assertEqual((goal.read_bytes(), native.read_bytes()), original)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing retry')
    def test_reward_week_receipt_rename_retry_preserves_delivery_and_home(self):
        goal, receipt = self.receipt(), self.reward_receipt()
        rename_path = Path.rename
        attempted = []

        def cross(source, destination):
            if Path(destination) == receipt:
                attempted.append(destination)
                self.now = datetime(2026, 11, 9, 4, tzinfo=CHINA)
                raise PermissionError('synthetic sharing violation')
            return rename_path(source, destination)

        with (self.reward_runtime([self.home()] * 5 + self.reward_frames()) as (starts, sends),
              patch.object(Path, 'rename', cross)):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], [3, 3, 3, 1, 1]))
        self.assertEqual(attempted, [receipt])
        summary = report['weekly_plan']
        self.assertTrue(summary['points_capped'])
        self.assertTrue(summary['score_rewards_delivery_verified'])
        self.assertTrue(summary['score_rewards_home_verified'])
        self.assertFalse(summary['score_rewards_verified'])
        self.assertEqual(json.loads(goal.read_bytes())['state'], 'complete')
        self.assertFalse(receipt.exists())

    def test_native_receipt_retry_crossing_week_preserves_verified_home_but_blocks_replay(self):
        self.assert_native_receipt_rollover(sharing_conflict=True)

    def test_native_receipt_rename_return_after_reset_also_keeps_original_result_unknown(self):
        self.assert_native_receipt_rollover(sharing_conflict=False)

    def assert_native_receipt_rollover(self, *, sharing_conflict):
        goal, weekly_receipt = self.receipt(), self.reward_receipt()
        canonical = self.runs / REWARD_SESSION
        replace_path = Path.replace
        attempted = []

        def cross(source, destination):
            if Path(destination) == canonical and json.loads(source.read_bytes())['status'] == 'complete':
                attempted.append(destination)
                if not sharing_conflict:
                    published = replace_path(source, destination)
                self.now = datetime(2026, 11, 9, 4, tzinfo=CHINA)
                if sharing_conflict:
                    raise PermissionError('synthetic sharing violation on canonical receipt')
                return published
            return replace_path(source, destination)

        with (self.reward_runtime([self.home()] * 5 + self.reward_frames()) as (starts, sends),
              patch.object(Path, 'replace', cross)):
            code, report = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], [3, 3, 3, 1, 1]))
        self.assertEqual(attempted, [canonical])
        self.assertEqual(report['status'], 'partial')
        summary = report['weekly_plan']
        self.assertTrue(summary['points_capped'])
        self.assertTrue(summary['score_rewards_delivery_verified'])
        self.assertTrue(summary['score_rewards_home_verified'])
        self.assertFalse(summary['score_rewards_verified'])
        self.assertFalse(weekly_receipt.exists())
        goal_bytes, reward_bytes = goal.read_bytes(), canonical.read_bytes()
        self.assertEqual(json.loads(goal_bytes)['state'], 'complete')
        record = json.loads(reward_bytes)
        self.assertEqual(record['status'], 'unknown')
        self.assertEqual(record['game_week'], '2026-11-02')
        self.assertFalse(record['safe_to_restart'])
        self.assertEqual(Path(record['journal']).read_bytes(), reward_bytes)
        self.assertEqual(record['actions'][-1]['after'], record['final_home_frames'])
        with self.reward_runtime([]) as (starts, sends):
            code, retry = self.cli(extra=(CLAIM_WEEKLY,))
        self.assertEqual((code, starts, sends), (1, [], []))
        self.assertIn('待核对', retry['error'])
        self.assertEqual((goal.read_bytes(), canonical.read_bytes()), (goal_bytes, reward_bytes))

    def test_full_points_uses_two_captures_zero_starts_and_same_week_dedupe(self):
        with self.runtime([self.home()] * 5) as (window, sent):
            code, report = self.cli()
        self.assertEqual(code, 0, report.get('error'))
        self.assertEqual(sent, [])
        window.click.assert_not_called()
        window.key.assert_not_called()
        summary = report['weekly_plan']
        self.assertEqual((summary['status'], summary['objective'], summary['completed_runs'], summary['maximum_runs']),
                         ('complete', 'points', 0, 3))
        self.assertTrue(summary['points_capped'])
        self.assertFalse(summary['score_rewards_verified'])
        self.assertEqual(report['differential_universe']['run_results'], [])
        row, = report['differential_universe']['periodic_points_goal']['observations']
        self.assertEqual((row['current'], row['game_week']), (18000, summary['week']))
        path = self.receipt()
        original = path.read_bytes()
        receipt = json.loads(original)
        self.assertEqual(receipt['evidence'], {ref['path']: ref['sha256'] for ref in row['evidence']})
        self.assertEqual(len(receipt['evidence']), 2)
        child = report['differential_universe']
        ledger = Path(child['ledger_path']).read_bytes()
        self.assertEqual(receipt['ledger'], dict(path=child['ledger_path'], sha256=hashlib.sha256(ledger).hexdigest()))
        self.assertEqual(json.loads(ledger)['weekly_points_scope'], child['weekly_points_scope'])
        self.assertEqual(child['weekly_points_scope']['account_key'], account_key(self.home()))

        self.settings = replace(self.settings, weekly_runs=8, weekly_time='08:00')
        with self.runtime([self.home(0)] * 3) as (_, sent):
            code, replay = self.cli(points=False)
        self.assertEqual(code, 0, replay.get('error'))
        summary = replay['weekly_plan']
        self.assertEqual((summary['status'], summary['objective'], summary['maximum_runs'], summary['new_completed_runs']),
                         ('already_complete', 'points', 3, 0))
        self.assertTrue(summary['reused_result'])
        self.assertEqual(summary['original_run_dir'], report['weekly_plan']['children'][-1]['run_dir'])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(sent, [])

        Path(row['evidence'][0]['path']).write_bytes(b'changed synthetic proof')
        with self.runtime([self.home()] * 3) as (_, sent):
            code, rejected = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(rejected['weekly_plan']['status'], 'needs_review')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(sent, [])

    def test_bound_fixed_receipt_is_reused_without_claiming_points(self):
        self.runs.mkdir()
        slot = weekly_slot(self.settings, self.now)
        receipt = WeeklyReceipt(self.runs, account_key(self.home()), slot)
        receipt.begin(self.settings, fixed_run_dir=self.runs / 'child')
        receipt.complete(du_report(self.runs, self.settings.weekly_runs, receipt=receipt))
        original = receipt.path.read_bytes()
        self.assertEqual(json.loads(original)['objective'], 'fixed_runs')
        with self.runtime([self.home()] * 3) as (_, sent):
            code, report = self.cli()
        self.assertEqual(code, 0, report.get('error'))
        summary = report['weekly_plan']
        self.assertEqual((summary['status'], summary['objective'], summary['completed_runs'], summary['new_completed_runs']),
                         ('already_complete', 'fixed_runs', 3, 0))
        self.assertIsNone(summary['points_capped'])
        self.assertFalse(summary['score_rewards_verified'])
        self.assertEqual(receipt.path.read_bytes(), original)
        self.assertEqual(sent, [])

    def test_native_start_counts_one_win_and_stops_below_frozen_opening_limit(self):
        with self.runtime(self.win_frames(18000)) as (_, sent):
            code, report = self.cli()
        self.assertEqual(code, 0, report.get('error'))
        self.assertEqual(len(sent), 1)
        summary = report['weekly_plan']
        self.assertEqual((summary['maximum_runs'], summary['completed_runs'], summary['status']), (3, 1, 'complete'))
        self.assertTrue(summary['points_capped'])
        self.assertFalse(summary['score_rewards_verified'])
        child = report['differential_universe']
        self.assertEqual([(r['completed_runs'], r['current']) for r in child['periodic_points_goal']['observations']],
                         [(0, 8000), (1, 18000)])
        self.assertEqual(len(json.loads(self.receipt().read_bytes())['evidence']), 7)

    def test_exhausted_receipt_keeps_partial_and_prevents_another_same_week_budget(self):
        self.settings = replace(self.settings, weekly_runs=1)
        with self.runtime(self.win_frames(12000)) as (_, sent):
            code, report = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual((report['status'], report['weekly_plan']['status']), ('partial', 'exhausted'))
        self.assertFalse(report['weekly_plan']['points_capped'])
        path = self.receipt()
        original = path.read_bytes()
        self.assertEqual(json.loads(original)['state'], 'exhausted')

        self.settings = replace(self.settings, weekly_runs=9)
        with self.runtime([self.home()] * 3) as (_, sent):
            code, replay = self.cli(points=False)
        self.assertEqual(code, 1)
        summary = replay['weekly_plan']
        self.assertEqual((replay['status'], summary['status'], summary['maximum_runs'], summary['completed_runs'],
                          summary['new_completed_runs']), ('partial', 'exhausted', 1, 1, 0))
        self.assertEqual(sent, [])
        self.assertEqual(path.read_bytes(), original)

        self.now += timedelta(days=7)
        with self.runtime([self.home()] * 5):
            code, next_week = self.cli()
        self.assertEqual(code, 0, next_week.get('error'))
        self.assertEqual(next_week['weekly_plan']['maximum_runs'], 9)
        self.assertEqual(path.read_bytes(), original)

    def test_account_swap_between_receipt_and_home_stops_native_points(self):
        guard = WeeklyGuard(self.runs, self.settings, weekly_slot(self.settings, self.now), until_points=True)
        pages = [self.home(), self.home(account=OTHER), self.home(account=OTHER)]
        with self.runtime(pages) as (_, sent):
            runner = Runner(self.settings, operation='differential_universe', du_runs=3, weekly_plan=guard,
                            du_until_points=True)
            report = runner.run()
        self.assertEqual(report.status, 'failed')
        goal = report.differential_universe['periodic_points_goal']
        self.assertEqual((goal['status'], goal['reason']), ('unverified', 'weekly_account_unverified'))
        self.assertEqual(json.loads(self.receipt().read_bytes())['state'], 'started')
        self.assertEqual(sent, [])

    def test_stop_during_points_preserves_daily_and_blocks_mode_switch(self):
        self.settings = replace(self.settings, daily=True)
        original_evidence = Context.evidence

        def daily(runner, *_):
            runner.report.daily_verified = True
            runner.report.results.append(TaskResult('daily', 'ok', 'fixture daily'))
            runner.report.status = 'success'

        def stop(ctx, scene, label):
            path = original_evidence(ctx, scene, label)
            if label.startswith('du_points_after_'):
                ctx.runner.stop()
            return path

        with (self.runtime([self.home()] * 8) as (_, sent), patch.object(Runner, '_run_tasks', daily),
              patch.object(Context, 'evidence', stop)):
            code, report = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(report['status'], 'stopped')
        self.assertTrue(report['daily_verified'])
        path = self.receipt()
        original = path.read_bytes()
        self.assertEqual(json.loads(original)['state'], 'started')
        self.assertEqual(sent, [])

        self.settings = replace(self.settings, daily=False, weekly_runs=7)
        with self.runtime([self.home()] * 3) as (_, sent):
            code, replay = self.cli(points=False)
        self.assertEqual(code, 1)
        self.assertEqual(replay['weekly_plan']['status'], 'needs_review')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(sent, [])

    def test_disagreeing_home_frames_after_win_leave_points_and_receipt_unverified(self):
        frames = self.win_frames(18000)[:-2] + [self.home(), self.home(12000)] * 3
        with self.runtime(frames) as (_, sent):
            code, report = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(len(sent), 1)
        summary = report['weekly_plan']
        self.assertEqual((summary['status'], summary['completed_runs'], summary['points_capped']),
                         ('needs_review', 1, None))
        self.assertFalse(summary['score_rewards_verified'])
        goal = report['differential_universe']['periodic_points_goal']
        self.assertEqual(goal['status'], 'unverified')
        self.assertEqual([row['current'] for row in goal['observations']], [8000])
        self.assertEqual(json.loads(self.receipt().read_bytes())['state'], 'started')

    def test_receipt_retry_across_week_keeps_child_win_and_original_intent(self):
        path = self.receipt()
        original_replace = Path.replace
        failed_renames = []

        def cross(source, destination):
            if Path(destination) == path:
                failed_renames.append(destination)
                self.now = datetime(2026, 11, 9, 4, tzinfo=CHINA)
                raise PermissionError('synthetic sharing violation')
            return original_replace(source, destination)

        with self.runtime(self.win_frames(18000)) as (_, sent), patch.object(Path, 'replace', cross):
            code, report = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(len(failed_renames), 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(report['weekly_plan']['status'], 'needs_review')
        self.assertIsNone(report['weekly_plan']['points_capped'])
        self.assertEqual(report['differential_universe']['completed_runs'], 1)
        self.assertEqual(json.loads(path.read_bytes())['state'], 'started')

    def test_changed_native_report_or_ledger_blocks_publication_and_reuse(self):
        original = PlanRunner._run
        for field in ('report_bytes', 'ledger_bytes', 'reuse_without_ledger'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                self.root = Path(folder)
                self.runs = self.root / 'runs'
                path = self.receipt()
                if field == 'reuse_without_ledger':
                    with self.runtime(self.win_frames(18000)):
                        code, report = self.cli()
                    self.assertEqual(code, 0, report.get('error'))
                    original_receipt = path.read_bytes()
                    Path(report['differential_universe']['ledger_path']).unlink()
                    with self.runtime([self.home()] * 3) as (_, sent):
                        code, report = self.cli(points=False)
                    self.assertEqual(path.read_bytes(), original_receipt)
                    self.assertEqual(sent, [])
                else:
                    changed = []

                    def after_native(plan, settings, *, phase, **options):
                        child = original(plan, settings, phase=phase, **options)
                        if phase == 'weekly':
                            source = (Path(child['run_dir']) / 'report.json' if field == 'report_bytes'
                                      else Path(child['differential_universe']['ledger_path']))
                            changed.append(path.read_bytes())
                            source.write_bytes(source.read_bytes() + b'\n')
                        return child

                    with (self.runtime(self.win_frames(18000)) as (_, sent),
                          patch.object(PlanRunner, '_run', after_native)):
                        code, report = self.cli()
                    self.assertEqual([path.read_bytes()], changed)
                    self.assertEqual(len(sent), 1)
                    self.assertEqual(report['weekly_plan']['completed_runs'], 1)
                self.assertEqual((code, report['weekly_plan']['status']), (1, 'needs_review'))
                self.assertIsNone(report['weekly_plan']['points_capped'])

    def test_receipt_retry_rechecks_native_report_and_points_images(self):
        original_replace = Path.replace
        for field in ('report', 'points_image'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                self.root = Path(folder)
                self.runs = self.root / 'runs'
                path = self.receipt()
                pending = []
                sources = []

                def locked(source, destination):
                    if Path(destination) == path:
                        pending.append(path.read_bytes())
                        if len(pending) == 1:
                            child = Path(json.loads(source.read_bytes())['report'])
                            if field == 'points_image':
                                goal = json.loads(child.read_bytes())['differential_universe']['periodic_points_goal']
                                child = Path(goal['observations'][-1]['evidence'][1]['path'])
                            sources.append(child)
                            raise PermissionError('synthetic sharing violation')
                    return original_replace(source, destination)

                def change_between_attempts(_delay):
                    child, = sources
                    child.write_bytes(child.read_bytes() + b'\n')

                with (self.runtime(self.win_frames(18000)) as (_, sent),
                      patch.object(Path, 'replace', locked),
                      patch('autohsr.storage.time.sleep', change_between_attempts)):
                    code, report = self.cli()
                self.assertEqual(pending, [path.read_bytes()])
                self.assertEqual(len(sent), 1)
                self.assertEqual((code, report['weekly_plan']['status'], report['weekly_plan']['completed_runs']),
                                 (1, 'needs_review', 1))
                self.assertIsNone(report['weekly_plan']['points_capped'])

    @unittest.skipUnless(os.name == 'nt', 'Windows read sharing')
    def test_receipt_retry_holds_verified_sources_through_replace(self):
        path = self.receipt()
        original_open, original_replace = Path.open, Path.replace
        attempts, sources, denied = [], [], []

        def replace(source, destination):
            if Path(destination) == path:
                attempts.append(destination)
                if len(attempts) == 1:
                    candidate = json.loads(source.read_bytes())
                    report = Path(candidate['report'])
                    goal = json.loads(report.read_bytes())['differential_universe']['periodic_points_goal']
                    images = [Path(ref['path']) for row in goal['observations'] for ref in row['evidence']]
                    sources.extend([report, Path(candidate['ledger']['path']), *images])
                    raise PermissionError('synthetic sharing violation')
                for proof in sources:
                    with self.assertRaises(PermissionError), proof.open('r+b'):
                        pass
            return original_replace(source, destination)

        def open_file(file, mode='r', *args, **kwargs):
            if sources and file == path.with_suffix('.tmp') and mode == 'rb' and len(attempts) == 1 and not denied:
                with self.assertRaises(PermissionError):
                    sources[-1].unlink()
                denied.append(sources[-1])
            return original_open(file, mode, *args, **kwargs)

        with (self.runtime(self.win_frames(18000)) as (_, sent),
              patch.object(Path, 'open', open_file), patch.object(Path, 'replace', replace)):
            code, report = self.cli()
        self.assertEqual(denied, sources[-1:])
        self.assertEqual(attempts, [path, path])
        self.assertEqual((code, len(sent), report['weekly_plan']['status']), (0, 1, 'complete'), report.get('error'))
        self.assertEqual(json.loads(path.read_bytes())['state'], 'complete')
        for proof in sources:
            with proof.open('r+b'):
                pass

    def test_lost_ledger_after_first_win_is_preserved_without_opening_again(self):
        original = DifferentialUniverseWorkflow._verify_periodic_goal
        lost = []

        def lose(flow, scene, kind):
            result = original(flow, scene, kind)
            if flow.report['completed_runs'] == 1:
                ledger = Path(flow.report['ledger_path'])
                ledger.unlink()
                lost.append(ledger)
            return result

        with (self.runtime(self.win_frames(12000)) as (_, sent),
              patch.object(DifferentialUniverseWorkflow, '_verify_periodic_goal', lose)):
            code, report = self.cli()
        ledger, = lost
        self.assertFalse(ledger.exists())
        self.assertEqual(len(sent), 1)
        self.assertEqual((code, report['weekly_plan']['status'], report['weekly_plan']['completed_runs']),
                         (1, 'needs_review', 1))
        self.assertEqual(json.loads(self.receipt().read_bytes())['state'], 'started')

    def test_last_window_guard_rechecks_points_sources_before_extra_opening(self):
        original = DifferentialUniverseWorkflow._verify_periodic_goal
        evidence = []

        def observe(flow, scene, kind):
            result = original(flow, scene, kind)
            if flow.report['completed_runs'] == 1:
                evidence.extend(flow.points_goal.result['observations'][-1]['evidence'])
            return result

        pages = self.win_frames(12000) + self.win_frames(18000)[5:]
        changed = []
        with (self.runtime(pages) as (window, sent),
              patch.object(DifferentialUniverseWorkflow, '_verify_periodic_goal', observe)):
            send = window.click.side_effect

            def click(x, y, geometry, *, before_send=None):
                if len(sent) == 1:
                    calls = []

                    def guard(expected=None):
                        if expected == geometry:
                            calls.append(expected)
                            if len(calls) == 2:
                                path = Path(evidence[0]['path'])
                                path.unlink()
                                changed.append(path)

                    window.guard.side_effect = guard
                return send(x, y, geometry, before_send=before_send)

            window.click.side_effect = click
            code, report = self.cli()
        self.assertEqual(len(changed), 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual((code, report['weekly_plan']['status'], report['weekly_plan']['completed_runs']),
                         (1, 'needs_review', 1))
        self.assertIsNone(report['weekly_plan']['points_capped'])
        action = [row for row in report['differential_universe']['actions'] if row.get('intent') == 'periodic_start'][-1]
        self.assertEqual(action['status'], 'not_sent')

    @unittest.skipUnless(os.name == 'nt', 'Windows read sharing')
    def test_final_native_send_holds_ledger_and_both_points_frames(self):
        self.geometry = Geometry(37, 19, 960, 540)
        self.image = np.zeros((540, 960, 3), dtype=np.uint8)
        raw = object.__new__(windows.GameWindow)
        raw.hwnd = 123
        fake = Mock(IsWindow=Mock(return_value=True), IsIconic=Mock(return_value=False),
                    GetForegroundWindow=Mock(return_value=raw.hwnd), GetAsyncKeyState=Mock(return_value=0),
                    GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__))
        original_observe = DifferentialUniverseWorkflow._verify_periodic_goal
        original_open = Path.open
        proofs, denied, batches = [], [], []
        in_click = False

        def observe(flow, scene, kind):
            result = original_observe(flow, scene, kind)
            if flow.report['completed_runs'] == 1:
                images = flow.points_goal.result['observations'][-1]['evidence']
                proofs.extend([Path(flow.report['ledger_path']), *(Path(ref['path']) for ref in images)])
            return result

        def open_file(file, mode='r', *args, **kwargs):
            if in_click and len(batches) == 1 and proofs and file == proofs[-1] and mode == 'rb' and not denied:
                for proof in proofs[:-1]:
                    with self.assertRaises(PermissionError):
                        proof.unlink()
                    denied.append(proof)
            return original_open(file, mode, *args, **kwargs)

        def send(size, items, _item_size):
            if len(batches) == 1:
                for proof in proofs:
                    with self.assertRaises(PermissionError), proof.open('r+b'):
                        pass
            batches.append([item.mi.dwFlags for item in items])
            return size

        def click(*args, **kwargs):
            nonlocal in_click
            in_click = True
            try:
                raw.click(*args, **kwargs)
            finally:
                in_click = False

        fake.SendInput.side_effect = send
        pages = self.win_frames(12000) + self.win_frames(18000)[5:]
        with (self.runtime(pages) as (window, _),
              patch.object(DifferentialUniverseWorkflow, '_verify_periodic_goal', observe),
              patch.object(Path, 'open', open_file), patch.object(windows, 'user32', fake),
              patch.object(windows, 'geometry', return_value=self.geometry)):
            window.click.side_effect = click
            window.guard.side_effect = raw.guard
            window.emergency_pressed.side_effect = raw.emergency_pressed
            code, report = self.cli()
        self.assertEqual(denied, proofs[:2])
        self.assertEqual(batches, [[0xC001, 2, 4]] * 2)
        self.assertEqual((code, report['weekly_plan']['status'], report['weekly_plan']['completed_runs']),
                         (0, 'complete', 2))
        for proof in proofs:
            with proof.open('r+b'):
                pass

    def test_context_ledger_writes_preserve_the_weekly_binding(self):
        with self.runtime(self.win_frames(18000)) as (_, sent):
            win = DifferentialUniverseWorkflow._progress_run

            def record_field_input(flow, scene, kind):
                flow.ctx._persist_du_ledger()
                return win(flow, scene, kind)

            with patch.object(DifferentialUniverseWorkflow, '_progress_run', record_field_input):
                code, report = self.cli()
        self.assertEqual(code, 0, report.get('error'))
        self.assertEqual(len(sent), 1)
        self.assertEqual(report['weekly_plan']['status'], 'complete')

    def test_other_account_cannot_reuse_a_misfiled_points_receipt(self):
        with self.runtime([self.home()] * 5):
            code, report = self.cli()
        self.assertEqual(code, 0, report.get('error'))
        original = self.receipt().read_bytes()
        slot = weekly_slot(self.settings, self.now)
        other = WeeklyReceipt(self.runs, account_key(self.home(account=OTHER)), slot)
        other.folder.mkdir(parents=True)
        for relabel in (False, True):
            with self.subTest(relabel=relabel):
                row = json.loads(original)
                if relabel:
                    row['account_key'] = other.account
                payload = json.dumps(row).encode('utf-8')
                other.path.write_bytes(payload)
                with self.runtime([self.home(account=OTHER)] * 3) as (_, sent):
                    code, report = self.cli()
                self.assertEqual((code, report['weekly_plan']['status']), (1, 'needs_review'))
                self.assertEqual(other.path.read_bytes(), payload)
                self.assertEqual(self.receipt().read_bytes(), original)
                self.assertEqual(sent, [])

    def test_points_option_rejects_other_plans_and_cli_budget_override(self):
        for enabled, mode, extra in ((False, 'differential_universe', ()), (True, 'currency_wars', ()),
                                     (True, 'differential_universe', ('--du-runs', '2'))):
            with self.subTest(enabled=enabled, mode=mode, extra=extra), patch('autohsr.plan_runner.PlanRunner') as native:
                self.settings = replace(self.settings, weekly_enabled=enabled, weekly_mode=mode)
                code, error = self.cli(extra=extra)
                self.assertEqual(code, 2)
                self.assertIn('error', error)
                native.assert_not_called()

    def test_claim_flag_requires_explicit_du_points_plan(self):
        with patch('autohsr.plan_runner.PlanRunner') as native:
            self.assertEqual(self.cli(points=False, extra=(CLAIM_WEEKLY,))[0], 2)
            self.settings = replace(self.settings, weekly_mode='currency_wars')
            self.assertEqual(self.cli(extra=(CLAIM_WEEKLY,))[0], 2)
            native.assert_not_called()
