"""Frozen DU week boundaries with synthetic contexts and temporary receipts."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.du_daily import account_key
from autohsr.models import AutomationError, RunReport, Scene, Token
from autohsr.tests.test_weekly_plan import du_report
from autohsr.weekly_plan import CHINA, WeeklyGuard, WeeklyReceipt, weekly_slot


class WeeklyBoundaryTests(unittest.TestCase):
    def setUp(self):
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)
        self.settings=Settings(weekly_enabled=True,differential_universe_mode='periodic')
        self.at=datetime(2026,11,8,23,55,tzinfo=CHINA)
        self.next_week=datetime(2026,11,9,4,5,tzinfo=CHINA)
        self.slot=weekly_slot(self.settings,self.at)
        owner=self
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):
                return owner.at.astimezone(tz) if tz else owner.at.replace(tzinfo=None)
        clock=patch('autohsr.weekly_plan.datetime',Clock)
        clock.start();self.addCleanup(clock.stop)
        self.guard=WeeklyGuard(self.root,self.settings,self.slot)
        self.scene=Scene([Token('UID:100000000',.99,(.01,.96,.1,.99))])

    def context(self,guard=True):
        return SimpleNamespace(settings=self.settings,report=RunReport(),
            runner=SimpleNamespace(weekly_plan=self.guard if guard else None,emit=Mock(),inactive_duration=0),
            checkpoint=Mock(),snapshot=Mock(return_value=self.scene),evidence=Mock(return_value='synthetic-proof.png'),
            click=Mock(),log=Mock())

    def test_expired_daily_to_weekly_gap_does_not_navigate_or_write_any_intent(self):
        self.at=self.next_week
        with patch('autohsr.workflows.DailyWorkflow') as daily:
            with self.assertRaisesRegex(AutomationError,'跨游戏周'):self.guard.prepare(self.context())
        daily.assert_not_called()
        self.assertEqual(list(self.root.rglob('*')),[])
        self.assertEqual(self.guard.slot,self.slot)

    def test_week_crossed_during_navigation_keeps_account_check_but_no_old_week_intent(self):
        context=self.context()
        with patch('autohsr.workflows.DailyWorkflow') as daily:
            daily.return_value.ensure_main.side_effect=lambda:setattr(self,'at',self.next_week)
            with self.assertRaisesRegex(AutomationError,'跨游戏周'):self.guard.prepare(context)
        context.snapshot.assert_called_once()
        self.assertEqual(list(self.root.rglob('*.json')),[])
        self.assertIsNone(self.guard.receipt)

    def test_intent_rechecks_after_existing_receipt_scan_and_preserves_original_files(self):
        previous=weekly_slot(self.settings,datetime(2026,10,28,12,tzinfo=CHINA))
        old=WeeklyReceipt(self.root,account_key(self.scene),previous)
        old.begin(self.settings, fixed_run_dir=self.root / 'child')
        old.complete(du_report(self.root, receipt=old))
        saved={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        original=WeeklyReceipt._report
        def read(receipt,data):
            result=original(receipt,data)
            self.at=self.next_week
            return result
        with patch('autohsr.workflows.DailyWorkflow'),patch.object(WeeklyReceipt,'_report',read):
            with self.assertRaisesRegex(AutomationError,'跨游戏周'):self.guard.prepare(self.context())
        self.assertEqual({p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()},saved)
        self.assertFalse(self.guard.receipt.path.exists())
        self.assertEqual(self.guard.slot.week,'2026-11-02')

    def test_current_week_completed_receipt_is_read_only_and_does_not_call_before_start(self):
        receipt=WeeklyReceipt(self.root,account_key(self.scene),self.slot)
        receipt.begin(self.settings, fixed_run_dir=self.root / 'child')
        receipt.complete(du_report(self.root, receipt=receipt))
        saved={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        callback=Mock(side_effect=AssertionError('no new intent'))
        self.assertFalse(WeeklyReceipt(self.root,account_key(self.scene),self.slot).begin(self.settings,before_start=callback))
        callback.assert_not_called()
        with patch('autohsr.workflows.DailyWorkflow'):
            self.assertFalse(self.guard.prepare(self.context()))
        self.assertTrue(self.guard.already_complete)
        self.assertEqual({p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()},saved)

    def test_not_due_frozen_goal_cannot_be_started_even_in_the_same_week(self):
        future=Settings(weekly_enabled=True,weekly_day=7,weekly_time='23:59')
        guard=WeeklyGuard(self.root,future,weekly_slot(future,self.at))
        with self.assertRaises(AutomationError):guard.require_current_week()
        self.assertFalse(list(self.root.rglob('*.json')))

    def test_new_attempt_and_preparation_entry_stop_before_any_navigation_after_reset(self):
        context=self.context();flow=DifferentialUniverseWorkflow(context,2)
        flow._snapshot=Mock(return_value=(self.scene,'home'))
        flow._open_differential_universe=Mock(return_value=(self.scene,'home'))
        flow._prepare_and_start=Mock(side_effect=AssertionError('must not prepare'))
        self.at=self.next_week
        with self.assertRaisesRegex(AutomationError,'跨游戏周'):flow.run()
        self.assertEqual(flow.report['run_results'],[])
        flow._prepare_and_start.assert_not_called()
        flow._open_differential_universe.assert_not_called()
        flow._open_differential_universe.reset_mock()
        with self.assertRaisesRegex(AutomationError,'跨游戏周'):
            DifferentialUniverseWorkflow._prepare_and_start(flow,self.scene,'home')
        flow._open_differential_universe.assert_not_called()
        context.click.assert_not_called()

    def test_long_preparation_crossing_reset_blocks_final_start_without_action_intent(self):
        context=self.context();flow=DifferentialUniverseWorkflow(context,1)
        page=Scene([Token('周期演算',.99,(.1,.1,.2,.2))])
        flow._open_differential_universe=Mock(return_value=(page,'periodic_setup'))
        def team(scene):
            self.at=self.next_week
            return page,'periodic_setup'
        flow._select_preset_team=Mock(side_effect=team)
        flow._displayed_difficulty_rank=Mock(return_value=5)
        flow._find=Mock(return_value=Token('启动差分宇宙',.99,(.8,.85,.95,.9)))
        with self.assertRaisesRegex(AutomationError,'跨游戏周'):flow._prepare_and_start(page,'periodic_setup')
        context.click.assert_not_called()
        self.assertEqual(flow.report['actions'],[])

    def test_intent_write_crossing_reset_preserves_requested_without_sending_or_retrying(self):
        context=self.context();context.report.run_dir=str(self.root)
        flow=DifferentialUniverseWorkflow(context,1)
        persist=flow._persist_ledger
        def save_then_cross():
            persist()
            self.at=self.next_week
        flow._persist_ledger=Mock(side_effect=save_then_cross)
        target=Token('启动差分宇宙',.99,(.8,.85,.95,.9))
        with self.assertRaisesRegex(AutomationError,'跨游戏周'):
            flow._click(self.scene,target,intent='periodic_start')
        context.click.assert_not_called()
        flow._persist_ledger.assert_called_once()
        saved=json.loads((self.root/'differential-universe-ledger.json').read_text('utf-8'))
        self.assertEqual(len(saved['actions']),1)
        self.assertEqual(saved['actions'][0]['status'],'requested')
        self.assertEqual(flow.report['actions'],saved['actions'])
        self.assertNotIn('after_evidence',saved['actions'][0])

    def test_completed_first_run_survives_reset_and_second_attempt_is_never_created(self):
        context=self.context();flow=DifferentialUniverseWorkflow(context,2)
        flow._snapshot=Mock(return_value=(self.scene,'home'))
        flow._open_differential_universe=Mock(return_value=(self.scene,'home'))
        def prepare(scene,kind):
            flow.report['difficulty_selection']=dict(requested_rank=5,displayed_rank_after=5,verified=True)
            return scene,'mask_choice'
        flow._prepare_and_start=Mock(side_effect=prepare)
        flow._progress_run=Mock(return_value=(self.scene,'home',True))
        def after(scene,kind,label):
            self.at=self.next_week
            return scene,kind
        flow._after_completed_run=Mock(side_effect=after)
        with self.assertRaisesRegex(AutomationError,'跨游戏周'):flow.run()
        self.assertEqual(flow.report['completed_runs'],1)
        self.assertEqual(len(flow.report['run_results']),1)
        self.assertEqual(flow.report['run_results'][0]['status'],'completed')
        self.assertTrue(flow.report['run_results'][0]['counted'])
        flow._prepare_and_start.assert_called_once()
        flow._progress_run.assert_called_once()

    def test_independent_du_has_no_weekly_guard_or_clock_requirement(self):
        flow=DifferentialUniverseWorkflow(self.context(guard=False),1)
        self.at=self.next_week
        before=deepcopy(flow.report)
        flow._weekly_boundary()
        self.assertEqual(flow.report,before)
