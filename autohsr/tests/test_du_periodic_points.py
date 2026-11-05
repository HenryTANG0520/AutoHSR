"""Public guide replay plus synthetic current-account and clock variants."""
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time as wall_time
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context
from autohsr.differential_universe import classify_page
from autohsr.du_periodic_points import GuidePointsUnverified, PANEL, is_current_game_week, read_guide_points
from autohsr.models import AutomationError, Scene, Token
from autohsr.tests.test_du_team import fixture
from autohsr.weekly_plan import CHINA
from autohsr.windows import Geometry


NOW = datetime(2026,11,7,6,30,tzinfo=CHINA)
BEFORE_RESET = datetime(2026,11,9,3,59,tzinfo=CHINA)
AFTER_RESET = datetime(2026,11,9,4,0,tzinfo=CHINA)
ACCOUNT = Token('UID: 000000011',.99,(.02,.959,.13,.983))
OTHER = Token('UID: 000000012',.99,ACCOUNT.box)
MALFORMED = Token('UID?',.85,ACCOUNT.box)


def replace(page, old, *tokens):
    return Scene([token for token in page.tokens if token.text != old]+list(tokens),page.image,page.geometry)


def with_account(page, *accounts):
    return Scene([*page.tokens,*accounts],page.image,page.geometry)


def token(text,left,top,right,bottom,confidence=.99):
    return Token(text,confidence,(left,top,right,bottom))


def score(text, *, left=.240, top=.816, right=.333, bottom=.844, confidence=.99):
    return token(text,left,top,right,bottom,confidence)


class GuidePointsParserTests(unittest.TestCase):
    def setUp(self):
        self.page = fixture('guide_du_capped')

    def test_public_full_guide_distinguishes_periodic_points_from_other_numbers(self):
        points = read_guide_points(self.page)
        self.assertEqual((points.current,points.cap,points.capped),(18000,18000,True))
        self.assertEqual([part.text for part in points.tokens],['周期积分','18000/18000'])

    def test_zero_partial_variable_cap_and_compact_or_slash_split_readings(self):
        cases = (
            ((score('0/18000'),),0,18000),
            ((score('１２，３４５ ／ ２０，０００'),),12345,20000),
            ((score('10000',right=.281),score('/18000',left=.286)),10000,18000),
            ((score('5000/',right=.282),score('18000',left=.287)),5000,18000),
            ((score('3500',right=.278),score('/',left=.283,right=.290),score('20000',left=.295)),3500,20000),
        )
        for fragments,current,cap in cases:
            with self.subTest(current=current,cap=cap):
                reading = read_guide_points(replace(self.page,'18000/18000',*fragments))
                self.assertEqual((reading.current,reading.cap,reading.capped),(current,cap,False))

    def test_missing_ambiguous_and_out_of_bounds_score_rows(self):
        cases = (
            (), (score('18000'),), (score('18000/0'),), (score('18001/18000'),),
            (score('1.800/18000'),), (score('18,00/18000'),),
            (score('18000/18000',left=.31,right=.39),),
            (score('18000/18000',top=.77,bottom=.798),),
            (score('18000/18000'),score('900/18000',left=.242,right=.331,confidence=.55)),
            (score('18000/18000'),score('900/18000',left=.133,right=.202)),
            (score('100',right=.275),score('00/18000',left=.281)),
            (score('10000',right=.30),score('/18000',left=.279)),
            (score('1000',right=.28),score('/18000',left=.304)),
        )
        for fragments in cases:
            with self.subTest(parts=len(fragments),text=[value.text for value in fragments]):
                with self.assertRaises(GuidePointsUnverified):
                    read_guide_points(replace(self.page,'18000/18000',*fragments))

    def test_other_rows_and_duplicate_or_wrong_page_labels(self):
        unrelated = score('100/300',left=.66,right=.73)
        self.assertEqual(read_guide_points(Scene([*self.page.tokens,unrelated])).current,18000)
        for bad in (replace(self.page,'前往参与'),replace(self.page,'乐园漫记'),
                    replace(self.page,'周期积分',token('周期积分',.145,.72,.194,.75)),
                    Scene([*self.page.tokens,token('周期积分',.51,.7,.58,.73,.62)])):
            with self.assertRaises(GuidePointsUnverified):
                read_guide_points(bad)


class GuidePointsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.guide = fixture('guide_du_capped')
        height,width = self.guide.image.shape[:2]
        self.guide.geometry = Geometry(0,0,width,height)
        self.home = Scene([token('差分宇宙',.05,.03,.12,.06),token('乐园漫记',.78,.35,.85,.39),
                           token('开始游戏',.78,.84,.89,.87)],self.guide.image,self.guide.geometry)

    @contextmanager
    def flow(self, detail, *, origin=None, middle=None, loading=(), now=NOW, destination=None, trailing=()):
        from autohsr import differential_universe as du
        from autohsr.tests.test_du_runtime import DuRuntimeTests

        if origin is None:
            origin = with_account(replace(self.guide,'18000/18000'),ACCOUNT)
        if middle is None:
            middle = with_account(replace(self.guide,'18000/18000',score('9000/18000')),ACCOUNT)
        pages = [origin,middle,*loading,detail,self.home if destination is None else destination,*trailing]
        clock = {'now':now}
        with TemporaryDirectory(prefix='AutoHSR-du-points-test-') as folder:
            with DuRuntimeTests().captured_du_flow(pages) as (flow,window):
                du.time.time = wall_time
                flow.ctx.report.run_dir = flow.report['run_dir'] = folder
                flow.ctx.evidence = Context.evidence.__get__(flow.ctx)
                window.hwnd = 123
                with patch('autohsr.du_periodic_points.time',du.time), \
                     patch('autohsr.du_periodic_points.local_now',lambda:clock['now']):
                    yield flow,window,clock

    def guide_entry(self, flow, window, *, loading_frames=0):
        initial = flow.ctx.snapshot()
        self.assertEqual(classify_page(initial),'guide')
        self.assertEqual(flow._open_differential_universe(initial,'guide'),(self.home,'home'))
        self.assertEqual([row['intent'] for row in flow.report['actions'] if 'intent' in row],
                         ['du_guide_select','du_guide_enter'])
        self.assertEqual(window.click.call_count,2)
        self.assertEqual(flow.ctx.vision.read.call_count,4+loading_frames)
        self.assertFalse(flow.report['stamina_budget_used'])
        self.assertEqual(flow.report['completed_runs'],0)
        self.assertNotIn('reward_collection',flow.report)
        flow._finish_periodic_points()
        return flow.report['periodic_points']

    def test_normal_guide_navigation_records_frozen_current_frame_after_legacy_input(self):
        import cv2
        import numpy as np

        detail = with_account(Scene(list(self.guide.tokens),self.guide.image.copy(),self.guide.geometry),ACCOUNT)
        height,width = detail.image.shape[:2]
        x1,y1,x2,y2 = (round(value*size) for value,size in zip(PANEL,(width,height,width,height)))
        expected = detail.image[y1:y2,x1:x2].copy()
        with self.flow(detail) as (flow,window,_):
            save = flow.ctx.evidence

            def after_input(scene,label):
                if label == 'du_periodic_points':
                    self.assertEqual(window.click.call_count,2)
                return save(scene,label)

            def change_old_scene(*_):
                if window.click.call_count == 2:
                    detail.image[:] = 250
                    detail.tokens.clear()

            flow.ctx.evidence = after_input
            window.click.side_effect = change_old_scene
            observed = self.guide_entry(flow,window)
            self.assertTrue(observed['verified'])
            self.assertEqual((observed['current'],observed['cap'],observed['capped']),(18000,18000,True))
            self.assertEqual((observed['game_week'],observed['input_epoch']),('2026-11-02',0))
            self.assertEqual(observed['source'],'guide_details')
            path = Path(observed['evidence']['path'])
            stored = cv2.imdecode(np.frombuffer(path.read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            self.assertTrue(np.array_equal(stored,expected))
            self.assertEqual(path.with_suffix('.txt').read_text(encoding='utf8').splitlines(),
                             ['剩余时间','①1天21小时','周期积分','18000/18000'])
            ledger = json.loads(Path(flow.ctx.report.run_dir,'differential-universe-ledger.json').read_text('utf8'))
            self.assertEqual(ledger['periodic_points'],observed)

    def test_formal_run_preserves_launch_and_result_before_recording_points(self):
        setup = fixture('periodic_setup')
        setup.geometry = self.guide.geometry
        field = Scene([token('(1/13)第一位面-战斗',.04,.028,.24,.05)],setup.image,setup.geometry)
        self.assertEqual(classify_page(setup),'periodic_setup')
        self.assertEqual(classify_page(field),'field_combat')
        for completed in (False,True):
            with self.subTest(completed=completed), self.flow(with_account(self.guide,ACCOUNT),
                    destination=setup,trailing=(field,)) as (flow,window,_):
                flow._select_preset_team = Mock(return_value=(setup,'periodic_setup'))
                timeline = []

                def progress(scene,kind):
                    self.assertIs(scene,field)
                    self.assertEqual(kind,'field_combat')
                    self.assertEqual(window.click.call_count,3)
                    timeline.append('gameplay_outcome')
                    if not completed:
                        raise AutomationError('synthetic run failure')
                    return self.home,'home',True

                evidence = flow.ctx.evidence

                def after_run(scene,label):
                    if label == 'du_periodic_points':
                        self.assertEqual(flow.report['completed_runs'],int(completed))
                        self.assertEqual(window.click.call_count,3)
                        timeline.append('points_evidence')
                    return evidence(scene,label)

                flow._progress_run = progress
                flow.ctx.evidence = after_run
                if completed:
                    self.assertEqual(flow.run().status,'ok')
                else:
                    with self.assertRaisesRegex(AutomationError,'synthetic run failure'):
                        flow.run()
                self.assertEqual(timeline,['gameplay_outcome','points_evidence'])
                self.assertEqual(flow.report['completed_runs'],int(completed))
                self.assertTrue(flow.report['periodic_points']['capped'])

    def test_missing_malformed_or_changed_identity_never_becomes_current_points(self):
        for accounts,reason in (((),'account_unverified'),((MALFORMED,),'account_unverified'),
                                ((ACCOUNT,OTHER),'account_unverified'),((OTHER,),'account_changed')):
            with self.subTest(reason=reason,count=len(accounts)):
                with self.flow(with_account(self.guide,*accounts)) as (flow,window,_):
                    observed = self.guide_entry(flow,window)
                    self.assertFalse(observed['verified'])
                    self.assertIsNone(observed['current'])
                    self.assertEqual(observed['reason'],reason)

    def test_category_return_also_binds_the_account_chain(self):
        cases = (((),(ACCOUNT,),(OTHER,),'account_changed'),
                 ((ACCOUNT,),(OTHER,),(ACCOUNT,),'account_changed'),
                 ((),(MALFORMED,),(ACCOUNT,),'account_unverified'),
                 ((ACCOUNT,),(),(ACCOUNT,),None),
                 ((),(ACCOUNT,),(ACCOUNT,),None))
        for origin,middle,detail,reason in cases:
            with self.subTest(reason=reason,origin_has_account=bool(origin)):
                page = with_account(self.guide,*detail)
                with self.flow(page,origin=with_account(self.guide,*origin),
                               middle=with_account(self.guide,*middle)) as (flow,window,_):
                    observed = self.guide_entry(flow,window)
                    self.assertEqual(observed['reason'],reason)
                    self.assertEqual(observed['verified'],reason is None)
                    self.assertEqual(observed['current'],18000 if reason is None else None)

    def test_replayed_category_return_is_not_a_fresh_details_frame(self):
        reused = with_account(self.guide,ACCOUNT)
        with self.flow(reused,middle=reused) as (flow,window,_):
            observed = self.guide_entry(flow,window)
            self.assertEqual(observed['reason'],'capture_not_fresh')
            self.assertFalse(observed['verified'])

    def test_account_conflict_during_existing_detail_wait_remains_unverified(self):
        loading = with_account(replace(self.guide,'乐园漫记'),OTHER)
        with self.flow(with_account(self.guide,ACCOUNT),loading=(loading,)) as (flow,window,_):
            observed = self.guide_entry(flow,window,loading_frames=1)
            self.assertEqual(observed['reason'],'account_changed')
            self.assertFalse(observed['verified'])

    def test_second_guide_missing_target_never_publishes_the_first_read(self):
        destination = with_account(replace(self.guide,'差分宇宙'),OTHER)
        with self.flow(with_account(self.guide,ACCOUNT),destination=destination) as (flow,window,_):
            with self.assertRaisesRegex(AutomationError,'未识别到差分宇宙分类'):
                flow.run()
            self.assertEqual(window.click.call_count,2)
            self.assertEqual(flow.report['completed_runs'],0)
            observed = flow.report['periodic_points']
            self.assertEqual(observed['reason'],'guide_entry_incomplete')
            self.assertFalse(observed['verified'])
            self.assertIsNone(observed['evidence'])
            ledger = json.loads(Path(flow.ctx.report.run_dir,'differential-universe-ledger.json').read_text('utf8'))
            self.assertEqual(ledger['periodic_points'],observed)

    def test_ambiguous_or_conflicting_countdown_does_not_affect_guide_entry(self):
        cases = ((replace(self.guide,'剩余时间'),'week_countdown_unverified'),
                 (replace(self.guide,'①1天21小时',token('5天',.255,.782,.317,.807)),'week_countdown_conflict'),
                 (replace(self.guide,'18000/18000',score('满分')),'score_row_unverified'))
        for page,reason in cases:
            with self.subTest(reason=reason), self.flow(with_account(page,ACCOUNT)) as (flow,window,_):
                observed = self.guide_entry(flow,window)
                self.assertEqual(observed['reason'],reason)
                self.assertIsNone(observed['capped'])
                self.assertTrue(Path(observed['evidence']['path']).is_file())

    def test_replayed_capture_new_epoch_and_week_rollover_leave_score_unverified(self):
        for scenario,reason in (('replayed','capture_not_fresh'),('new_epoch','capture_scope_changed'),
                                ('new_week','game_week_changed')):
            detail = with_account(self.guide,ACCOUNT)
            with self.subTest(scenario=scenario), self.flow(detail,now=BEFORE_RESET) as (flow,window,clock):
                wait = flow.ctx.wait

                def changed(*args,**kwargs):
                    page = wait(*args,**kwargs)
                    if scenario == 'replayed':
                        page.captured_at = 10.
                    elif scenario == 'new_epoch':
                        flow.ctx.runner.input_epoch = flow.ctx.scene_epoch = 1
                    else:
                        clock['now'] = AFTER_RESET
                    return page

                flow.ctx.wait = changed
                observed = self.guide_entry(flow,window)
                self.assertEqual(observed['reason'],reason)
                self.assertIsNone(observed['current'])

    def test_crossing_week_while_saving_or_write_failure_only_affects_observation(self):
        timer = token('1分钟',.255,.782,.310,.807)
        detail = with_account(replace(self.guide,'①1天21小时',timer),ACCOUNT)
        for fail_write in (False,True):
            with self.subTest(fail_write=fail_write), self.flow(detail,now=BEFORE_RESET) as (flow,window,clock):
                evidence = flow.ctx.evidence

                def changed(scene,label):
                    if label == 'du_periodic_points':
                        self.assertEqual(window.click.call_count,2)
                        if fail_write:
                            raise OSError('synthetic evidence write failure')
                        clock['now'] = AFTER_RESET
                    return evidence(scene,label)

                flow.ctx.evidence = changed
                observed = self.guide_entry(flow,window)
                self.assertFalse(observed['verified'])
                self.assertIsNone(observed['current'])
                self.assertEqual(observed['reason'],'evidence_unverified' if fail_write else 'game_week_changed')
                self.assertEqual(observed['game_week'],'2026-11-02')
                self.assertEqual(observed['evidence'] is None,fail_write)

    def test_crossing_week_during_ledger_replace_downgrades_even_if_rewrite_fails(self):
        from autohsr import differential_universe as du

        timer = token('1分钟',.255,.782,.310,.807)
        detail = with_account(replace(self.guide,'①1天21小时',timer),ACCOUNT)
        for fail_rewrite in (False,True):
            with self.subTest(fail_rewrite=fail_rewrite), self.flow(detail,now=BEFORE_RESET) as (flow,window,clock):
                replace_file = du.replace_file
                attempts = []

                def rollover(source,target):
                    pending = json.loads(source.read_text('utf8'))['periodic_points']
                    if pending['verified']:
                        self.assertTrue(is_current_game_week(pending,BEFORE_RESET))
                        attempts.append('publish')
                        clock['now'] = AFTER_RESET
                    elif pending['reason'] == 'game_week_changed':
                        attempts.append('downgrade')
                        if fail_rewrite:
                            raise OSError('synthetic downgrade rewrite failure')
                    return replace_file(source,target)

                with patch.object(du,'replace_file',rollover):
                    observed = self.guide_entry(flow,window)
                self.assertEqual(attempts,['publish','downgrade'])
                self.assertEqual(observed['reason'],'game_week_changed')
                self.assertFalse(observed['verified'])
                self.assertEqual([observed[key] for key in ('current','cap','capped')],[None,None,None])
                self.assertTrue(Path(observed['evidence']['path']).is_file())
                ledger = json.loads(Path(flow.ctx.report.run_dir,'differential-universe-ledger.json').read_text('utf8'))
                saved = ledger['periodic_points']
                self.assertEqual(saved['game_week'],'2026-11-02')
                self.assertFalse(is_current_game_week(saved,AFTER_RESET))
                if fail_rewrite:
                    self.assertTrue(saved['verified'])
                    relabeled = dict(saved,game_week='2026-11-09')
                    self.assertFalse(is_current_game_week(relabeled,AFTER_RESET))
                else:
                    self.assertEqual(saved,observed)

    def test_home_entry_does_not_create_extra_navigation_or_score(self):
        with self.flow(with_account(self.guide,ACCOUNT)) as (flow,window,_):
            flow.ctx.snapshot = Mock(return_value=self.home)
            self.assertEqual(flow._open_differential_universe(self.home,'home'),(self.home,'home'))
            self.assertEqual(flow.report['periodic_points']['reason'],'guide_not_observed')
            window.click.assert_not_called()
