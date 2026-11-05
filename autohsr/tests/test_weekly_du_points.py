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
from autohsr.models import AutomationError, Scene, TaskResult
from autohsr.plan_runner import PlanRunner
from autohsr.tests.test_du_periodic_points import ACCOUNT, OTHER, token, with_account
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_weekly_plan import du_report
from autohsr.weekly_plan import CHINA, WeeklyGuard, WeeklyReceipt, weekly_slot
from autohsr.windows import Geometry


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
            return Scene(list(page.tokens), image, geometry)

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
            for module in ('app', 'differential_universe', 'du_periodic_points', 'workflow_identity'):
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

    def test_legacy_fixed_receipt_is_reused_without_claiming_points(self):
        self.runs.mkdir()
        slot = weekly_slot(self.settings, self.now)
        receipt = WeeklyReceipt(self.runs, account_key(self.home()), slot)
        receipt.begin(self.settings)
        receipt.complete(du_report(self.runs, self.settings.weekly_runs))
        original = receipt.path.read_bytes()
        self.assertNotIn('objective', json.loads(original))
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
