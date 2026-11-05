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

from autohsr.app import Context, Runner
from autohsr.differential_universe import DifferentialUniverseWorkflow, classify_page
from autohsr.du_periodic_points import GuidePointsUnverified, read_home_points, read_periodic_setup
from autohsr.models import AutomationError, EmptyCapture, FocusLost, Scene
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

    def test_periodic_setup_requires_its_own_complete_headings_and_start(self):
        page = fixture('periodic_setup')
        rank, start = read_periodic_setup(page, .85)
        self.assertEqual(rank, 5)
        self.assertIs(start, page.find('启动「差分宇宙」', exact=True))
        split = replace(page, '差分宇宙：乐园漫记丨难度V',
                        token('差分宇宙：乐园漫记', .572, .118, .696, .147),
                        token('难度Ⅹ', .700, .119, .75, .147))
        self.assertEqual(read_periodic_setup(split, .85)[0], 10)

        def with_extra(extra):
            return Scene([*page.tokens, extra], page.image, page.geometry)

        for kind, invalid in (
                ('weak_competing_mode', with_extra(token('常规演算', .62, .31, .75, .37, .70))),
                ('misplaced_mode', replace(page, '周期演算：不可亵玩', token('周期演算', .61, .32, .75, .36))),
                ('missing_boss', replace(page, '本周首领敌人')),
                ('competing_launch', with_extra(token('启动差分宇宙演算', .82, .91, .95, .94))),
                ('ambiguous_button', with_extra(token('开始演算', .82, .91, .95, .94)))):
            with self.subTest(kind=kind), self.assertRaises(GuidePointsUnverified):
                read_periodic_setup(invalid, .85)


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

    def mixed_setup(self):
        setup, _ = self.setup_and_field()
        return Scene([*setup.tokens, token('乐园漫记', .12, .04, .19, .08),
                      token('常规演算', .62, .31, .75, .37),
                      token('难度I', .06, .12, .11, .17)], setup.image, setup.geometry)

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

    def test_mixed_setup_stops_before_a_preset_or_after_its_return(self):
        for after_preset in (False, True):
            pages = [self.home(8000), self.home(8000)]
            if after_preset:
                pages.append(self.setup_and_field()[0])
            mixed = self.mixed_setup()
            self.assertEqual(classify_page(mixed), 'difficulty_setup')
            with self.subTest(after_preset=after_preset), self.flow([*pages, mixed]) as (flow, window, _, sent):
                prepare = flow._prepare_and_start

                def next_setup():
                    current = flow.ctx.snapshot()
                    return current, classify_page(current)

                flow._prepare_and_start = lambda _page, _kind: prepare(*next_setup())
                flow._select_preset_team = Mock(side_effect=lambda _page: next_setup())
                with self.assertRaisesRegex(AutomationError, '周期备战页'):
                    flow.run()
                self.assertEqual(flow._select_preset_team.call_count, int(after_preset))
                window.click.assert_not_called()
                self.assertFalse(sent)
                self.assertEqual(flow.report['mode'], '周期演算')
                ledger = json.loads(Path(flow.report['ledger_path']).read_text('utf-8'))
                self.assertEqual(ledger['periodic_points_goal']['status'], 'unverified')
                self.assertEqual(ledger['run_results'][-1]['status'], 'not_started')

    def test_context_rejects_launch_control_under_a_navigation_intent(self):
        setup = self.setup_and_field()[0]
        obscured = replace(replace(setup, '本周首领敌人'), '启动「差分宇宙」',
                           token('开始游戏', .826, .884, .920, .909))
        self.assertEqual(classify_page(obscured), 'home')
        for page in (setup, self.mixed_setup(), obscured):
            with self.flow([page]) as (flow, window, _, sent):
                current = flow.ctx.snapshot()
                observed = current.find(('启动「差分宇宙」', '开始游戏'), exact=True)
                for target in (observed, token('启动差分宇宙演算', *observed.box), token('开始演算', *observed.box)):
                    with self.subTest(label=target.text), self.assertRaisesRegex(AutomationError, '专用启动检查'):
                        flow.ctx.click(current, target)
                window.click.assert_not_called()
                self.assertFalse(sent)

    def test_final_native_block_preserves_the_request_as_not_sent_in_both_reports(self):
        for failure in ('epoch', 'week', 'focus'):
            pages = [self.home(8000), self.home(8000), self.setup_and_field()[0]]
            with self.subTest(failure=failure), self.flow(pages) as (flow, window, clock, sent):
                self.seed_launch_and_win(flow)
                send = window.click.side_effect

                def interrupt(*args, **kwargs):
                    if failure == 'epoch':
                        flow.ctx.runner.input_epoch += 1
                    elif failure == 'week':
                        clock['now'] = RESET
                    else:
                        window.guard.side_effect = FocusLost('synthetic foreground loss')
                    return send(*args, **kwargs)

                window.click.side_effect = interrupt
                with self.assertRaises(AutomationError):
                    flow.run()
                self.assertFalse(sent)
                ledger = json.loads(Path(flow.report['ledger_path']).read_text('utf-8'))
                for record in (flow.report, ledger):
                    self.assertEqual(record['requested_runs'], 3)
                    self.assertEqual(record['completed_runs'], 0)
                    self.assertEqual(record['periodic_points_goal']['status'], 'unverified')
                    self.assertEqual(record['run_results'][-1]['status'], 'not_started')
                    self.assertEqual(record['actions'][-1]['status'], 'not_sent')
                    request = next(a for a in record['actions'] if a.get('intent') == 'periodic_start')
                    self.assertEqual((request['run'], request['status']), (1, 'not_sent'))

    def test_report_retry_after_week_reset_preserves_the_verified_win_and_observations(self):
        pages = [self.home(8000), self.home(8000), *self.setup_and_field(), self.home(), self.home()]
        with self.flow(pages) as (flow, _, clock, sent):
            self.seed_launch_and_win(flow)
            report = flow.ctx.report
            report.results.append(flow.run())
            report.status = 'success'
            report.report_saved = True
            folder = Path(report.run_dir)
            original = Path.replace
            publication_attempts = []

            def replace_report(temp, destination):
                if Path(destination).name == 'report.json':
                    publication_attempts.append(json.loads(temp.read_text('utf-8'))['status'])
                    if len(publication_attempts) == 1:
                        clock['now'] = RESET
                        raise PermissionError('synthetic report sharing violation')
                return original(temp, destination)

            with patch.object(Path, 'replace', replace_report):
                Runner._save_run_report(flow.ctx.runner, folder, flow)

            self.assertEqual(publication_attempts, ['success', 'partial'])
            self.assertEqual(len(sent), 1)
            saved = json.loads((folder / 'report.json').read_text('utf-8'))
            self.assertEqual((saved['status'], saved['results'][-1]['status']), ('partial', 'partial'))
            ledger = json.loads(Path(flow.report['ledger_path']).read_text('utf-8'))
            for record in (saved['differential_universe'], ledger):
                self.assertEqual(record['completed_runs'], 1)
                self.assertEqual(record['run_results'][0]['status'], 'completed')
                goal = record['periodic_points_goal']
                self.assertEqual((goal['status'], goal['reason']), ('unverified', 'game_week_changed'))
                self.assertEqual([(row['current'], row['game_week']) for row in goal['observations']],
                                 [(8000, WEEK), (18000, WEEK)])

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
