"""Independent reward transactions through real Context and synthetic IO."""
from copy import deepcopy
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.du_reward_store import preflight
from autohsr.du_reward_store import digest, encoded
from autohsr.du_rewards_only import RewardAction, RewardWorkflow, _gallery_rows, _kind, _steady_scope, run_rewards
from autohsr.models import AutomationError, EmptyCapture, RunReport, Scene, Stopped, Token, normalize
from autohsr.vision import save_scene


def token(text,x,y,w=.05):return Token(text,.99,(x-w/2,y-.012,x+w/2,y+.012))


def page(tokens):
    return Scene(tokens,np.full((720,1280,3),30,np.uint8),SimpleNamespace(width=1280,height=720))


def dot(scene,x,y):
    center=(round(x*1280),round(y*720))
    cv2.circle(scene.image,center,10,(35,35,230),-1)
    cv2.line(scene.image,(center[0],center[1]-5),(center[0],center[1]+2),(255,255,255),2)


def home(*marked,uid='100000000'):
    labels=('拟合等级','月下奇谭','稳态数组','可能性画廊')
    result=page([token('差分宇宙',.1,.05),token('乐园漫记',.1,.11),token('开始游戏',.85,.9),
        token('UID:'+uid,.07,.975)]+[token(name,.84,.28+index*.12) for index,name in enumerate(labels)])
    for name in marked:dot(result,.895,.27+labels.index(name)*.12)
    return result


def fit(*marked):
    result=page([token('差分宇宙',.1,.05),token('80',.5,.4),token('已满级',.5,.51),
        token('下次扩充',.85,.83),token('78',.4,.835),token('79',.55,.835),token('80',.70,.835)])
    for value in marked:dot(result,{79:.565,80:.715}[value],.742)
    return result


def overlay():return page([token('获得物品',.5,.15),token('×50',.5,.5),token('点击空白处关闭',.5,.8)])


def steady(status='领取',done=7):
    result=page([token('稳态数组',.1,.05),token('测试',.42,.115),token('难题',.58,.115),
        token('假面怪杰',.07,.198),token(str(done)+'/14',.055,.23),
        token('佩戴1次「两张」面具，并通关',.53,.25,w=.38),token(status,.92,.25)])
    result.image[round(.10*720):round(.13*720),round(.35*1280):round(.48*1280)]=230
    result.image[round(.178*720):round(.263*720),round(.02*1280):round(.21*1280)]=230
    return result


def gallery_home(marked=True):
    result=page([token('可能性画廊',.1,.05),token('奖励领取进度76%',.75,.06),token('收集进度58%',.9,.06),token('事件',.35,.6)])
    if marked:dot(result,.4,.59)
    return result


def gallery_category(marked=True):
    result=page([token('事件',.1,.05),token('奖励进度2/5',.16,.915)])
    if marked:dot(result,.21,.895)
    return result


def milestones(claimed=False):
    # The claimed threshold moves from the first row to the second.
    rows=[(90,'进行中'),(72,'已领取')] if claimed else [(72,'领取'),(90,'进行中')]
    values=[]
    for index,(threshold,status) in enumerate(rows):
        y=.3+index*.1
        values.extend([token('累计解锁数量达到',.29,y,w=.16),token(str(threshold),.26,y+.04),token(status,.74,y+.03)])
    return page(values)


def moon(balance=300,available=True):
    result=page([token('月下奇谭',.27,.17),token('道具一览',.2,.615),
        token('使用卡带获取下一道具' if available else '所有道具均已获得',.74,.685,w=.23),
        token(str(balance),.90,.06),token('×100',.70,.775),token('解锁',.785,.775)])
    if available:dot(result,.835,.765)
    return result


def unlocked():return page([token('技能提升',.5,.18),token('前往查看剧情',.5,.77)])
def story():return page([token('事件',.1,.05),token('差分宇宙',.22,.05),token('秘闻',.15,.83)])


def pair(*pages):return [value for item in pages for value in (item,item)]


class RewardsOnlyTests(unittest.TestCase):
    def context(self,folder,pages):
        directory=Path(folder)/str(len(list(Path(folder).iterdir())));directory.mkdir()
        runner=SimpleNamespace(settings=Settings(action_delay=0),report=RunReport(operation='du_rewards',run_dir=str(directory)),
            input_epoch=0,inactive_duration=0.,_stop=threading.Event(),_pause=threading.Event(),log=Mock())
        runner.checkpoint=lambda:(_ for _ in ()).throw(Stopped('synthetic stop')) if runner._stop.is_set() else None
        window=Mock(hwnd=123)
        c=Context(runner,window,Mock());c.sleep=Mock()
        source=iter(pages);serial=[0]
        def snapshot():
            try:item=next(source)
            except StopIteration:raise Stopped('synthetic sequence ended')
            if isinstance(item,Exception):raise item
            scene=deepcopy(item);scene.captured_at=time.monotonic();c.last_scene=scene;c.scene_epoch=runner.input_epoch
            return scene
        c.snapshot=snapshot
        def evidence(scene,label):
            serial[0]+=1
            return save_scene(scene,directory,str(serial[0])+'-'+label)
        c.evidence=evidence
        return c

    def test_no_free_red_dots_complete_without_touching_optional_moon(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.context(folder,pair(home('月下奇谭')))
            self.assertEqual(run_rewards(c).status,'ok')
            data=c.report.du_rewards
            self.assertTrue(data['rewards_verified']);self.assertFalse(data['all_notifications_cleared'])
            self.assertEqual(data['skipped_optional_categories'],['月下奇谭'])
            self.assertNotIn('月下奇谭',data['requested_categories'])
            self.assertEqual(preflight(folder),data)
            c.window.click.assert_not_called();c.window.key.assert_not_called()

    def test_fit_claim_has_overlay_and_return_proof_before_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.context(folder,pair(home('拟合等级'),fit(79),overlay(),fit(),home()))
            self.assertEqual(run_rewards(c).status,'ok')
            data=c.report.du_rewards;self.assertEqual(data['claims'][0]['status'],'verified')
            self.assertEqual(data['claims'][0]['identity']['tier'],79)
            self.assertEqual([row['request']['intent'] for row in data['actions']],
                ['du_reward_open','du_reward_dot','du_reward_dismiss','du_reward_back_home'])
            self.assertEqual(c.window.click.call_count,3);c.window.key.assert_called_once_with('esc')
            self.assertTrue(data['all_notifications_cleared']);preflight(folder)

    def test_gallery_reordered_threshold_and_steady_explicit_claimed_feedback(self):
        scenarios=[('可能性画廊',pair(home('可能性画廊'),gallery_home(),gallery_category(),milestones(),overlay(),
            milestones(True),gallery_category(False),gallery_home(False),home())),
            ('稳态数组',pair(home('稳态数组'),steady(),overlay(),steady('已领取'),home()))]
        for label,pages in scenarios:
            with self.subTest(label=label),tempfile.TemporaryDirectory() as folder:
                c=self.context(folder,pages)
                self.assertEqual(run_rewards(c).status,'ok')
                self.assertEqual(c.report.du_rewards['claims'][0]['source'],label)
                preflight(folder)

    def test_explicit_cassettes_freeze_and_verify_story_return_and_exact_debit(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.context(folder,pair(home('月下奇谭'),moon(),unlocked(),story(),moon(200,False),home()))
            self.assertEqual(run_rewards(c,use_cassettes=True).status,'ok')
            self.assertEqual(c.report.du_rewards['cassettes'],dict(initial_balance=300,limit=300,spent_verified=100))
            self.assertEqual(c.report.du_rewards['claims'][0]['balance_after'],200)
            self.assertIsNone(c.report.du_rewards['obligation']);preflight(folder)

    def test_unknown_claim_blocks_new_run_and_keeps_original_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.context(folder,pair(home('拟合等级'),fit(79)))
            with self.assertRaises(Stopped):run_rewards(c)
            self.assertEqual(c.report.du_rewards['actions'][-1]['status'],'unknown')
            original=(Path(folder)/'du-rewards-session.json').read_bytes()
            with self.assertRaises(AutomationError):preflight(folder)
            other=self.context(folder,pair(home()))
            with self.assertRaises(AutomationError):run_rewards(other)
            self.assertEqual((Path(folder)/'du-rewards-session.json').read_bytes(),original)
            other.window.click.assert_not_called()

    def test_steady_progress_growth_without_claimed_and_wrong_gallery_threshold_do_not_settle(self):
        for label,returned in [('稳态数组',steady('进行中',8)),('可能性画廊',milestones())]:
            with self.subTest(label=label),tempfile.TemporaryDirectory() as folder:
                sequence=pair(home(label),steady() if label=='稳态数组' else gallery_home())
                if label=='可能性画廊':sequence+=pair(gallery_category(),milestones())
                sequence+=pair(overlay(),returned)
                c=self.context(folder,sequence)
                with self.assertRaises(Stopped):run_rewards(c)
                self.assertFalse(c.report.du_rewards['rewards_verified'])
                self.assertNotEqual(c.report.du_rewards['claims'][0]['status'],'verified')
                with self.assertRaises(AutomationError):preflight(folder)

    def test_external_cassette_growth_does_not_expand_or_continue_frozen_budget(self):
        for changed in (400,100):
            with self.subTest(balance=changed),tempfile.TemporaryDirectory() as folder:
                c=self.context(folder,pair(home('月下奇谭'),moon(),unlocked(),story(),moon(200),moon(changed)))
                with self.assertRaisesRegex(AutomationError,'冻结余额'):run_rewards(c,use_cassettes=True)
                data=c.report.du_rewards
                self.assertEqual(data['cassettes'],dict(initial_balance=300,limit=300,spent_verified=100))
                self.assertEqual([claim['status'] for claim in data['claims']],['verified'])
                self.assertEqual(sum(row['request']['intent']=='du_reward_unlock' for row in data['actions']),1)
                self.assertEqual(c.window.click.call_count,3)

    def test_three_verified_cassette_debits_stop_at_original_ceiling_with_partial_home_return(self):
        with tempfile.TemporaryDirectory() as folder:
            sequence=pair(home('月下奇谭'),moon(300))
            for balance in (200,100,0):
                sequence+=pair(unlocked(),story(),moon(balance,available=balance>0))
                if balance:sequence+=pair(moon(balance))
            sequence+=pair(home('月下奇谭'))
            c=self.context(folder,sequence)
            self.assertEqual(run_rewards(c,use_cassettes=True).status,'partial')
            self.assertEqual(c.report.du_rewards['cassettes'],dict(initial_balance=300,limit=300,spent_verified=300))
            self.assertEqual(len(c.report.du_rewards['claims']),3)
            self.assertEqual(c.report.du_rewards['remaining_categories'],['月下奇谭'])
            self.assertFalse(c.report.du_rewards['rewards_verified']);preflight(folder)

    def test_final_context_epoch_or_png_change_and_intent_write_failure_never_click(self):
        for change in ('epoch','png','write'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                c=self.context(folder,pair(home('拟合等级')))
                if change=='write':
                    from autohsr import du_reward_store as store
                    original=store._write
                    def write(path,data):
                        if data['actions']:raise OSError('synthetic intent disk failure')
                        return original(path,data)
                    patcher=patch.object(store,'_write',side_effect=write)
                else:
                    def guard(*args):
                        if change=='epoch':c.runner.input_epoch+=1
                        else:
                            flow=c.du_rewards_workflow
                            Path(flow.data['observations'][flow.data['actions'][-1]['before']]['evidence']['path']).write_bytes(b'changed PNG')
                    c.window.guard.side_effect=guard
                    patcher=nullcontext()
                with patcher,self.assertRaises((AutomationError,OSError)):run_rewards(c)
                c.window.click.assert_not_called();c.window.key.assert_not_called()

    def test_unknown_frame_interrupts_pair_and_background_home_cannot_win_over_overlay(self):
        with tempfile.TemporaryDirectory() as folder:
            c=self.context(folder,[home(),EmptyCapture('synthetic black frame'),home()])
            with self.assertRaises(Stopped):run_rewards(c)
            c.window.click.assert_not_called();self.assertFalse(c.report.du_rewards['rewards_verified'])
        scene=home();scene.tokens+=overlay().tokens
        self.assertEqual(_kind(scene),'reward_overlay')

    def test_complete_moon_unlock_modal_wins_over_background_home(self):
        scene=home();scene.tokens+=unlocked().tokens
        self.assertEqual(_kind(scene),'moon_unlocked')
        # A partial obtained-items overlay still blocks the home behind it.
        scene=home();scene.tokens.append(token('获得物品',.5,.15))
        self.assertIsNone(_kind(scene))

    def test_static_purchase_condition_keeps_steady_page_and_explicit_claimed_receipt(self):
        root=Path(__file__).parent/'fixtures/du_runtime'
        rows=json.loads((root/'reward_pages.json').read_text(encoding='utf-8'))
        row=next(item for item in rows if item['kind']=='steady_rewards')
        observed=Scene([Token(item['text'],item['score'],tuple(item['box'])) for item in row['tokens']],cv2.imread(str(root/row['file'])))
        condition='在商店购买1件奇物，并通关'
        observed.tokens=[Token(condition,t.score,t.box) if t.text.startswith('佩戴1次') else t for t in observed.tokens]
        self.assertEqual(_kind(observed),'steady_rewards')
        before,after=steady(),steady('已领取')
        for scene in (before,after):
            scene.tokens=[Token(condition,t.score,t.box) if t.text.startswith('佩戴1次') else t for t in scene.tokens]
        with tempfile.TemporaryDirectory() as folder:
            c=self.context(folder,pair(home('稳态数组'),before,overlay(),after,home()))
            self.assertEqual(run_rewards(c).status,'ok')
            self.assertEqual(c.report.du_rewards['claims'][0]['identity']['condition'],normalize(condition))
            self.assertEqual(c.report.du_rewards['claims'][0]['status'],'verified')

    def test_centered_purchase_modal_blocks_background_home_and_reward_authorization(self):
        for positive in ('确认购买','确认','确定','确认支付','确认付款'):
            with self.subTest(positive=positive),tempfile.TemporaryDirectory() as folder:
                scene=home('拟合等级')
                scene.tokens += [token(positive,.62,.62),token('取消',.38,.62)]
                self.assertIsNone(_kind(scene))
                c=self.context(folder,[]);workflow=RewardWorkflow(c)
                target=next(t for t in scene.tokens if t.text=='拟合等级')
                self.assertFalse(workflow._derive(scene,RewardAction(0,'du_reward_open',target=target)))
                c.window.click.assert_not_called()

    def test_zero_input_abort_preserves_sources_and_can_start_another_explicit_run(self):
        for variant in ('stopped','missing_uid'):
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as folder:
                first=home()
                if variant=='missing_uid':first.tokens=[t for t in first.tokens if not t.text.startswith('UID:')]
                c=self.context(folder,[first])
                with self.assertRaises(Stopped):run_rewards(c)
                data=c.report.du_rewards
                self.assertEqual(data['status'],'abort_before_input');self.assertTrue(data['safe_to_restart'])
                self.assertFalse(data['rewards_verified']);self.assertEqual(data['actions'],[])
                original=Path(data['journal']).read_bytes();preflight(folder)
                other=self.context(folder,pair(home()))
                self.assertEqual(run_rewards(other).status,'ok')
                self.assertEqual(Path(data['journal']).read_bytes(),original)

    def test_home_uid_gap_requires_two_new_frames_and_explicit_other_uid_stops(self):
        missing=home();missing.tokens=[t for t in missing.tokens if not t.text.startswith('UID:')]
        for changed in (False,True):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as folder:
                end=home(uid='200000000') if changed else home()
                c=self.context(folder,pair(home('拟合等级'),fit(79),overlay(),fit())+[home(),missing]+pair(end))
                if changed:
                    with self.assertRaisesRegex(AutomationError,'账号改变'):run_rewards(c)
                    self.assertFalse(c.report.du_rewards['rewards_verified'])
                else:
                    self.assertEqual(run_rewards(c).status,'ok')
                    frames=c.report.du_rewards['final_home_frames']
                    self.assertEqual(frames[-1],frames[0]+1)
                    self.assertGreater(frames[0],c.report.du_rewards['actions'][-1]['before']+1)

    def test_old_return_or_initial_home_frames_cannot_replace_the_corresponding_action_proof(self):
        for change in ('return','home'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                c=self.context(folder,pair(home('拟合等级'),fit(79),overlay(),fit(),home()))
                run_rewards(c);data=json.loads(Path(c.report.du_rewards['journal']).read_text(encoding='utf-8'))
                if change=='return':data['claims'][0]['return_frames']=data['actions'][0]['after']
                else:data['final_home_frames']=data['home_frames']
                data['digest']=digest({key:value for key,value in data.items() if key!='digest'})
                for path in (Path(data['journal']),Path(folder)/'du-rewards-session.json'):path.write_bytes(encoded(data))
                with self.assertRaises(AutomationError):preflight(folder)

    def test_claim_receipts_cannot_be_dropped_or_duplicated_while_retaining_consumptive_actions(self):
        for source in ('free','cassettes'):
            with self.subTest(source=source),tempfile.TemporaryDirectory() as folder:
                sequence=pair(home('拟合等级'),fit(79),overlay(),fit(),home()) if source=='free' else pair(
                    home('月下奇谭'),moon(),unlocked(),story(),moon(200,False),home())
                c=self.context(folder,sequence);run_rewards(c,use_cassettes=source=='cassettes')
                original=json.loads(Path(c.report.du_rewards['journal']).read_text(encoding='utf-8'))
                for change in ('missing','duplicate','wrong_source'):
                    data=deepcopy(original)
                    if change=='missing':data['claims']=[];data['cassettes']['spent_verified']=0
                    elif change=='duplicate':data['claims'].append(deepcopy(data['claims'][0]));data['claims'][1]['id']=1
                    else:data['claims'][0]['source']='稳态数组'
                    data['digest']=digest({key:value for key,value in data.items() if key!='digest'})
                    for path in (Path(data['journal']),Path(folder)/'du-rewards-session.json'):path.write_bytes(encoded(data))
                    with self.subTest(change=change),self.assertRaises(AutomationError):preflight(folder)

    def test_real_public_layouts_support_selected_steady_scope_and_gallery_reordering(self):
        from autohsr.tests.test_du_team import fixture
        root=Path(__file__).parent/'fixtures/du_runtime'
        rows=json.loads((root/'reward_pages.json').read_text(encoding='utf-8'))
        row=next(item for item in rows if item['kind']=='steady_rewards')
        scene=Scene([Token(item['text'],item['score'],tuple(item['box'])) for item in row['tokens']],cv2.imread(str(root/row['file'])))
        self.assertEqual(_steady_scope(scene),dict(tab='测试',group='假面怪杰',done=7,total=14))
        before=_gallery_rows(fixture('gallery_event_milestones'));after=_gallery_rows(fixture('gallery_event_after_claim'))
        self.assertEqual(next(status.text for value,status in before if value==72),'领取')
        self.assertEqual(next(status.text for value,status in after if value==72),'已领取')
        self.assertNotEqual(before[0][0],after[0][0])
