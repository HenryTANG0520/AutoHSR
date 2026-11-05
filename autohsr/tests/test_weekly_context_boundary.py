"""Final periodic-start checks after evidence writing; no Runner or OS IO."""
from datetime import datetime
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.models import AutomationError,RunReport,Scene,Stopped,Token
from autohsr.weekly_plan import CHINA,WeeklyGuard,weekly_slot


class WeeklyContextBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.at=datetime(2026,11,8,23,55,tzinfo=CHINA)
        self.settings=Settings(weekly_enabled=True,differential_universe_mode='periodic')
        self.slot=weekly_slot(self.settings,self.at)
        owner=self
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return owner.at.astimezone(tz) if tz else owner.at.replace(tzinfo=None)
        clock=patch('autohsr.weekly_plan.datetime',Clock);clock.start();self.addCleanup(clock.stop)
        self.guard=WeeklyGuard(self.root,self.settings,self.slot)
        self.target=Token('启动差分宇宙',.99,(.8,.85,.95,.92))
        self.scene=Scene([Token(text,.99,(.1,.1,.2,.15)) for text in ('差分宇宙','周期演算','难度V')]+[self.target],captured_at=time.monotonic())
        self.report=RunReport(operation='differential_universe')
        self.runner=SimpleNamespace(settings=self.settings,report=self.report,input_epoch=0,weekly_plan=self.guard,
                                   log=Mock(),stopped=False)
        self.window=Mock();self.context=Context(self.runner,self.window,Mock())
        self.context.last_scene=self.scene
        self.context.checkpoint=lambda:(_ for _ in ()).throw(Stopped('synthetic stop')) if self.runner.stopped else None
        self.context.evidence=Mock(return_value=self.root/'before.png')
        self.context.sleep=Mock();self.context._snapshot_after_du_input=Mock(return_value=self.scene)

    def test_evidence_crossing_week_cannot_send_and_marks_the_prepared_record_not_sent(self):
        requested=dict(intent='periodic_start',status='requested',before_evidence='original-intent.png')
        self.report.differential_universe['actions']=[dict(requested)]
        def write(*args):self.at=datetime(2026,11,9,4,1,tzinfo=CHINA);return self.root/'before.png'
        self.context.evidence.side_effect=write
        with self.assertRaisesRegex(AutomationError,'跨游戏周'):
            self.context.click(self.scene,self.target,du_intent='periodic_start')
        self.window.click.assert_not_called()
        self.assertEqual(self.report.differential_universe['actions'][0],requested)
        self.assertEqual(self.report.differential_universe['actions'][-1]['status'],'not_sent')
        self.assertEqual(self.guard.slot,self.slot)

    def test_evidence_epoch_stop_stale_or_replaced_scene_rejects_without_input(self):
        for change in ('epoch','stop','stale','scene'):
            with self.subTest(change=change):
                self.runner.input_epoch=0;self.runner.stopped=False
                self.context.last_scene=self.scene;self.scene.captured_at=time.monotonic()
                self.report.differential_universe={}
                def write(*args):
                    if change=='epoch':self.runner.input_epoch+=1
                    elif change=='stop':self.runner.stopped=True
                    elif change=='stale':self.scene.captured_at-=10
                    else:self.context.last_scene=None
                    return self.root/'before.png'
                self.context.evidence.side_effect=write
                with self.assertRaises(AutomationError):self.context.click(self.scene,self.target,du_intent='periodic_start')
                self.window.click.assert_not_called()
                self.assertEqual(self.report.differential_universe['actions'][0]['status'],'not_sent')

    def test_already_expired_guard_stops_before_evidence_and_independent_du_keeps_its_contract(self):
        self.at=datetime(2026,11,9,4,1,tzinfo=CHINA)
        with self.assertRaises(AutomationError):self.context.click(self.scene,self.target,du_intent='periodic_start')
        self.context.evidence.assert_not_called();self.window.click.assert_not_called()
        self.runner.weekly_plan=None
        self.context.click(self.scene,self.target,du_intent='periodic_start')
        self.window.click.assert_called_once()
