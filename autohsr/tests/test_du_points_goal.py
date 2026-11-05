"""Public home replays and synthetic launch/return paths for the points target."""
from contextlib import contextmanager, redirect_stderr
from datetime import datetime
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time as wall_time
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.du_periodic_points import GuidePointsUnverified, read_home_points
from autohsr.models import AutomationError, EmptyCapture, Scene
from autohsr.tests.test_du_periodic_points import ACCOUNT, OTHER, replace, token, with_account
from autohsr.tests.test_du_team import fixture
from autohsr.weekly_plan import CHINA
from autohsr.windows import Geometry


WEEK = '2026-11-02'
NOW = datetime(2026,11,6,9,30,tzinfo=CHINA)
RESET = datetime(2026,11,9,4,tzinfo=CHINA)


class HomePointsTests(unittest.TestCase):
    def test_public_home_frames_at_two_layout_positions(self):
        scenes = (('fit_65_red_after_steady',datetime(2026,10,23,9,20,28,tzinfo=CHINA)),
                  ('rewards_home_intro',datetime(2026,10,23,22,28,1,tzinfo=CHINA)))
        for name,now in scenes:
            with self.subTest(name=name):
                points = read_home_points(fixture(name),now,'2026-10-19')
                self.assertEqual((points.current,points.cap,points.capped),(18000,18000,True))

    def test_home_accepts_split_time_and_score_but_rejects_partial_or_conflicting_rows(self):
        page = fixture('fit_65_red_after_steady')
        split = replace(page,'本期剩余时间：2天18小时',
                        token('本期剩余时间：',.035,.859,.117,.882),token('2天18小时',.123,.86,.167,.88))
        split = replace(split,'18000/18000',token('３，０００',.113,.905,.155,.945),
                        token('/',.157,.906,.164,.948),token('２０，０００',.167,.908,.221,.948))
        result = read_home_points(split,NOW,WEEK)
        self.assertEqual((result.current,result.cap,result.capped),(3000,20000,False))
        for invalid in (
            replace(page,'18000/18000'),
            replace(page,'18000/18000',token('奖励已由邮件发放',.087,.906,.19,.948)),
            replace(page,'18000/18000',token('18000/18000',.113,.905,.208,.947,.61)),
            replace(page,'本期剩余时间：2天18小时',token('本期剩余时间：1小时',.035,.86,.161,.882)),
            Scene([*page.tokens,token('账号验证',.43,.44,.55,.48)],page.image),
            Scene([*page.tokens,token('1/18000',.069,.91,.112,.944,.69)],page.image),
            replace(page,'更新内容'),
        ):
            with self.subTest(invalid=len(invalid.tokens)), self.assertRaises(GuidePointsUnverified):
                read_home_points(invalid,NOW,WEEK)


class PointsGoalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.page = fixture('fit_65_red_after_steady')
        height,width = self.page.image.shape[:2]
        self.page.geometry = Geometry(0,0,width,height)

    def home(self, points=18000, account=ACCOUNT):
        page = replace(self.page,'18000/18000',token(f'{points}/18000',.113,.904,.207,.947))
        return with_account(page,account) if account else page

    def setup_and_field(self):
        setup = with_account(fixture('periodic_setup'),ACCOUNT)
        setup.geometry = self.page.geometry
        field = Scene([token('(1/13)第一位面-战斗',.04,.028,.24,.05)],self.page.image,self.page.geometry)
        return setup,field

    @contextmanager
    def flow(self, pages, *, maximum=3):
        from autohsr import differential_universe as du
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        clock = {'now': NOW}
        with TemporaryDirectory(prefix='AutoHSR-du-points-goal-') as directory:
            with DuRuntimeTests().captured_du_flow(pages) as (baseline,window):
                du.time.time = wall_time
                context = baseline.ctx
                window.hwnd = 123
                context.report.run_dir = directory
                context.evidence = Context.evidence.__get__(context)
                flow = DifferentialUniverseWorkflow(context,maximum,until_points=True)
                flow.report['run_dir'] = directory
                sent = []

                def send(x,y,geometry,*,before_send=None):
                    if before_send is not None:
                        before_send()
                    sent.append((x,y))

                window.click.side_effect = send
                with patch('autohsr.du_periodic_points.time',du.time), \
                     patch('autohsr.du_periodic_points.local_now',lambda:clock['now']):
                    yield flow,window,clock,sent

    def seed_launch_and_win(self, flow):
        def launch(_page,_kind):
            setup = flow.ctx.snapshot()
            flow.report['difficulty_selection'] = dict(verified=True,requested_rank=5,displayed_rank_after=5)
            target = setup.find(('启动「差分宇宙」','启动差分宇宙'),(.72,.82,1,.98))
            return flow._click(setup,target,intent='periodic_start',label='periodic_run_started')

        def win(_page,_kind):
            return flow.ctx.snapshot(),'home',True

        flow._prepare_and_start = launch
        flow._progress_run = win

    def test_already_capped_records_zero_attempts_and_zero_input(self):
        with self.flow([self.home(),self.home()]) as (flow,window,_,sent):
            self.assertEqual(flow.run().status,'ok')
            self.assertFalse(sent)
            window.click.assert_not_called()
            self.assertEqual(flow.report['run_results'],[])
            self.assertEqual(flow.report['completed_runs'],0)
            goal = flow.report['periodic_points_goal']
            self.assertEqual(goal['status'],'capped')
            self.assertEqual(len(goal['observations'][0]['evidence']),2)
            ledger = json.loads(Path(flow.report['ledger_path']).read_text('utf-8'))
            self.assertEqual(ledger['periodic_points_goal'],goal)

    def test_black_frame_interrupts_a_reading_pair(self):
        pages = [self.home(),EmptyCapture('synthetic black frame'),self.home(),self.home()]
        with self.flow(pages) as (flow,window,_,sent):
            self.assertEqual(flow.run().status,'ok')
            self.assertEqual(window.capture.call_count,4)
            self.assertFalse(sent)

    def test_win_can_reach_cap_early_or_exhaust_explicit_maximum(self):
        for score,maximum,status,result in ((18000,3,'capped','ok'),(12000,1,'exhausted','partial')):
            pages = [self.home(8000),self.home(8000),*self.setup_and_field(),self.home(score),self.home(score)]
            with self.subTest(score=score), self.flow(pages,maximum=maximum) as (flow,_,_,sent):
                self.seed_launch_and_win(flow)
                self.assertEqual(flow.run().status,result)
                self.assertEqual(len(sent),1)
                self.assertEqual(flow.report['completed_runs'],1)
                goal = flow.report['periodic_points_goal']
                self.assertEqual(goal['status'],status)
                self.assertEqual([row['completed_runs'] for row in goal['observations']],[0,1])
                self.assertEqual([row['current'] for row in goal['observations']],[8000,score])

    def test_different_account_and_disagreeing_score_never_open_a_run(self):
        cases = ([self.home(),self.home(account=OTHER)],
                 [self.home(8000 if index % 2 else 9000) for index in range(6)])
        for pages in cases:
            with self.subTest(frames=len(pages)), self.flow(pages) as (flow,window,_,sent):
                with self.assertRaises(AutomationError):
                    flow.run()
                window.click.assert_not_called()
                self.assertFalse(sent)
                self.assertEqual(flow.report['run_results'],[])
                self.assertEqual(flow.report['periodic_points_goal']['status'],'unverified')

    def test_account_conflict_after_a_win_preserves_the_win_and_prevents_new_input(self):
        pages = [self.home(8000),self.home(8000),*self.setup_and_field(),self.home(account=OTHER)]
        with self.flow(pages) as (flow,_,_,sent):
            self.seed_launch_and_win(flow)
            with self.assertRaises(AutomationError):
                flow.run()
            self.assertEqual(len(sent),1)
            self.assertEqual(flow.report['completed_runs'],1)
            self.assertEqual(flow.report['run_results'][0]['status'],'completed')
            self.assertEqual(flow.report['periodic_points_goal']['status'],'unverified')

    def test_new_epoch_at_final_native_callback_blocks_old_start(self):
        pages = [self.home(8000),self.home(8000),self.setup_and_field()[0]]
        with self.flow(pages) as (flow,window,_,sent):
            self.seed_launch_and_win(flow)
            send = window.click.side_effect

            def interrupt(*args,**kwargs):
                flow.ctx.runner.input_epoch += 1
                return send(*args,**kwargs)

            window.click.side_effect = interrupt
            with self.assertRaises(AutomationError):
                flow.run()
            self.assertFalse(sent)
            self.assertEqual(flow.report['completed_runs'],0)
            self.assertEqual(flow.report['actions'][-1]['status'],'not_sent')

    def test_week_crossing_during_points_evidence_cannot_complete_the_goal(self):
        with self.flow([self.home(),self.home()]) as (flow,_,clock,sent):
            evidence = flow.ctx.evidence

            def crossing(scene,label):
                path = evidence(scene,label)
                if label.startswith('du_points_after_'):
                    clock['now'] = RESET
                return path

            flow.ctx.evidence = crossing
            with self.assertRaises(AutomationError):
                flow.run()
            self.assertFalse(sent)
            self.assertEqual(flow.report['periodic_points_goal']['status'],'unverified')

    def test_epoch_change_between_ledger_renames_keeps_only_an_unverified_goal(self):
        with self.flow([self.home(),self.home()]) as (flow,window,_,sent):
            original = Path.replace
            attempts = []

            def replace_ledger(temp,destination):
                if Path(destination).name == 'differential-universe-ledger.json':
                    state = json.loads(temp.read_text('utf-8'))['periodic_points_goal']['status']
                    if state != 'observing':
                        attempts.append(state)
                    if state == 'capped':
                        flow.ctx.runner.input_epoch += 1
                        raise PermissionError('synthetic sharing violation')
                return original(temp,destination)

            with patch.object(Path,'replace',replace_ledger), self.assertRaises(AutomationError):
                flow.run()
            self.assertEqual(attempts,['capped','unverified'])
            window.click.assert_not_called()
            self.assertFalse(sent)
            ledger = json.loads(Path(flow.report['ledger_path']).read_text('utf-8'))
            self.assertEqual(ledger['periodic_points_goal']['status'],'unverified')

    def test_cli_rejects_new_option_for_resume_normal_and_non_du_operations(self):
        from autohsr.__main__ import main

        for args in (('--run',),('--differential-universe',),('--differential-universe','--resume-active-du'),
                     ('--differential-universe','--du-mode','normal'),('--plan',)):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), patch('autohsr.app.Runner') as runner:
                self.assertEqual(main([*args,'--du-until-points']),2)
                runner.assert_not_called()
