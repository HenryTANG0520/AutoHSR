"""Investment provenance, typed gifts and refresh experience, without game IO."""
from copy import deepcopy
from dataclasses import asdict
from itertools import count
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import numpy as np

from autohsr.currency_wars_collector import collected_snapshot
from autohsr.currency_wars_deployment import _BENCH_CENTERS, _crop, bench_face
from autohsr.currency_wars_investment_policy import (choose, options, parse_effect, selected_slot)
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action,run_standard,transition_ready
from autohsr.currency_wars_standard_investment import (SELECT,CONFIRM,active_action,bind_reward,confirmed,
    enter,feedback,refresh_bonus,reward_completed,reward_scope,valid_effect,verified_names)
from autohsr.currency_wars_standard_ledger import ledger_status,valid_receipt
from autohsr.currency_wars_standard_refresh import experience_gain,refresh_action
from autohsr.currency_wars_standard_trading import financial_feedback,record_financial_feedback,shop_return_values
from autohsr.currency_wars_standard_rewards import bind_source,enter as reward_enter,returned
from autohsr.models import AutomationError,InputInterrupted,Scene,Stopped,Token,normalize
from autohsr.tests import test_currency_wars_choices as old_choices
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_refresh as refresh
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange


EXECUTE='我方小队攻击敌方目标后，若其生命值百分比少于16%，将其【斩杀】。'
CASH_XP='你每次消耗金币刷新商店，都会获得2经验值。'
DEFENSE='我方小队获得8%伤害减免。进入战斗时，生命上限最低的角色额外获得12%伤害减免。获得一件【进阶武装箱】。'


def page(cards=None, selected=None):
    scene=old_choices.investment()
    if cards is not None:
        scene.tokens=[t for t in scene.tokens if not t.within((.1,.43,.9,.85))]
        centers={1:(.5,),2:(.37,.63),3:(.24,.5,.76)}[len(cards)]
        for x,(name,effect) in zip(centers,cards):
            scene.tokens.extend((Token(name,.99,(x-.04,.44,x+.04,.47)),
                Token(effect,.99,(x-.1,.49,x+.1,.55)),Token('刷新次数1',.99,(x-.04,.78,x+.04,.81))))
    if selected is not None:
        choices=options(scene);x=choices[selected].name.center[0]
        _crop(scene.image,(x-.106,.198,x-.103,.722))[:]=240
        _crop(scene.image,(.43,.892,.57,.925))[:]=240
    return scene


def fixture(cards=None,strategy='default'):
    board,session=trading.full_board_fixture(gold=30)
    rewards.node(board,'2-1')
    for record in session['collection']['units'].values():record['node']='2-1'
    session.update(strategy=strategy,expected_board='2-1',actions=[
        dict(id=0,action='start_standard_node',status='verified',input_epoch=0,target=['1-6',30,100,3],before='start.png',after='battle.png'),
        dict(id=1,action='continue_standard_node',status='verified',input_epoch=0,target=['1-6',0],before='victory.png',after='map.png',feedback=dict(page_kind='plane_map',node='2-1')),
        dict(id=2,action='advance_standard_next_plane',status='verified',input_epoch=0,target=['1-6',0,'2-1'],before='map.png',after='choices.png')])
    session['node_attempt']=dict(node='1-6',start_action_id=0,status='advanced',node_verified=True,result='victory.png',result_kind='node_result')
    scene=page(cards);enter(session,scene)
    return board,scene,session


def append(session,choice,status='verified',epoch=0):
    action=dict(id=len(session['actions']),action=choice.intent,expected=choice.expected,status=status,
                input_epoch=epoch,target=list(choice.payload),before='before.png',after='after.png')
    if choice.intent==CONFIRM:
        action['selection_proof']=dict(source_action_id=len(session['actions'])-1,input_epoch=epoch,
            run_dir=session['account_verified_run'],options=choice.payload[6])
    session['actions'].append(action)
    return action


def select_and_confirm(board,scene,session):
    selection=active_action(scene,session);append(session,selection)
    highlighted=page([(o.name.text,o.effect) for o in options(scene)],selected=selection.payload[2])
    # Preserve the original layout and tokens, changing only the selection pixels.
    highlighted.tokens=list(scene.tokens)
    choice=active_action(highlighted,session);append(session,choice)
    confirmed(session,choice,board)
    session.setdefault('collection',dict(run_dir=session['account_verified_run'],input_epoch=session['account_verified_epoch'],units={},complete=False))
    return choice,highlighted


def gift_board(board,number=1):
    result=Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
    for slot in range(6,6+number):
        _crop(result.image,bench_face(slot))[:]=np.random.default_rng(300+slot).integers(0,256,_crop(result.image,bench_face(slot)).shape,dtype=np.uint8)
        x=_BENCH_CENTERS[slot-1]
        result.tokens.append(Token('开启',.99,(x-.015,.82,x+.015,.87)))
    return result


def deliver_box(before,opening,choice,index=0):
    result=Scene([t for t in before.tokens if not (normalize(t.text)=='开启' and abs(t.center[0]-_BENCH_CENTERS[opening.payload[1]-1])<.02)],
                 before.image.copy(),captured_at=time.monotonic())
    _crop(result.image,bench_face(opening.payload[1]))[:]=0
    equipment.place(result.image,choice.payload[5],(2460,330+100*index))
    return result


def modifier_fixture(gain=2,price=2,xp=(0,6)):
    source,scene,old=fixture([('淘金客',CASH_XP.replace('2经验',str(gain)+'经验'))])
    select_and_confirm(source,scene,old)
    board,shop,session=refresh.fixture(price=price)
    rewards.node(board,'2-1');rewards.node(shop,'2-1')
    trading.hud(board,xp=xp);trading.hud(shop,xp=xp)
    for record in session['collection']['units'].values():record['node']='2-1'
    opening=session['actions'][0];opening['id']=len(old['actions'])
    session['actions']=deepcopy(old['actions'])+[opening]
    session['investment']=deepcopy(old['investment'])
    session['pre_shop_snapshot']=asdict(collected_snapshot(board,session,0,'fresh_opening'))
    return board,shop,session


class InvestmentTests(unittest.TestCase):
    def test_full_semantic_fields_and_numeric_variants_are_parsed_independently(self):
        for amount in (1,2,3,16,99,100):
            kind,parameters,_=parse_effect(EXECUTE.replace('16%',str(amount)+'%'))
            self.assertEqual((kind,dict(parameters)['threshold']),('execution',amount))
        for effect,kind,params in (
            ('在战斗开始50行动值后，我方小队伤害增幅提高80%。','delayed_damage',dict(delay=50,damage=80)),
            (DEFENSE,'reduction',dict(reduction=8,extra_reduction=12,boxes=1,box_tier=2)),
            (DEFENSE.replace('一件','2个').replace('进阶','简易'),'reduction',dict(reduction=8,extra_reduction=12,boxes=2,box_tier=1)),
            ('战斗开始时：1个随机的1费角色在这场战斗中升为4星，并获得5%前/后台强度。','temporary_upgrade',dict(count=1,tier=1,star=4,strength=5)),
            (CASH_XP.replace('2经验','3经验'),'refresh_experience',dict(experience=3))):
            parsed,parameters,_=parse_effect(effect)
            self.assertEqual((parsed,dict(parameters)),(kind,params))
            self.assertIsNone(parse_effect(effect+'但出售所有角色')[0])
        for effect in (EXECUTE.replace('16%','0%'),EXECUTE.replace('16%','101%'),CASH_XP.replace('2经验','-2经验')):
            self.assertIsNone(parse_effect(effect)[0])

    def test_one_two_three_layouts_use_effects_and_named_preferences_not_slot(self):
        for cards in ([('爆仓',EXECUTE)],[('未知策略','未知效果'),('爆仓',EXECUTE)],
                      [('延迟收益','在战斗开始100行动值后我方小队伤害增幅提高40%'),('爆仓',EXECUTE),('未知','未知')]):
            choices=options(page(cards))
            self.assertEqual(len(choices),len(cards));self.assertEqual(choose(choices,'default').name.text,'爆仓')
        choices=options(page([('爆仓',EXECUTE),('淘金客',CASH_XP)]))
        self.assertEqual(choose(choices,'aglaea').name.text,'淘金客')
        self.assertEqual(choose(choices,'default').name.text,'爆仓')

    def test_unknown_penalty_and_upstream_blacklist_never_become_a_fallback(self):
        for name,effect in (('未知','未知效果'),('现金为王',EXECUTE),('爆仓',EXECUTE+'消耗全部金币')):
            with self.subTest(name=name),self.assertRaises(AutomationError):choose(options(page([(name,effect)])),'default')
        for y in (.70,.82):
            scene=page([('爆仓',EXECUTE)])
            scene.tokens.append(Token('并出售全部角色',.99,(.43,y,.57,y+.02)))
            with self.assertRaises(AutomationError):choose(options(scene),'default')

    def test_origin_account_version_and_ledger_must_match_before_selecting(self):
        for mutation in ('missing','map','node','start','version','epoch','unknown'):
            _,scene,session=fixture()
            if mutation=='missing':session.pop('investment')
            elif mutation=='map':session['actions'][1]['feedback']['node']='3-1'
            elif mutation=='node':session['investment']['expected_node']='2-2'
            elif mutation=='start':session['actions'][0]['status']='unknown'
            elif mutation=='version':session['client']['version']='4.7'
            elif mutation=='epoch':session['account_verified_epoch']=1
            else:session['actions'][-1]['status']='unknown'
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):active_action(scene,session)

    def test_confirm_requires_our_selection_same_candidates_and_unique_highlight(self):
        board,scene,session=fixture([('爆仓',EXECUTE),('未知','未知效果')])
        selected=page([('爆仓',EXECUTE),('未知','未知效果')],selected=0)
        with self.assertRaises(AutomationError):active_action(selected,session)
        choice=active_action(scene,session);append(session,choice)
        self.assertTrue(feedback(choice,selected,session))
        confirm=active_action(selected,session);self.assertEqual(confirm.intent,CONFIRM)
        wrong=page([('爆仓',EXECUTE),('未知','未知效果')],selected=1)
        self.assertFalse(feedback(choice,wrong,session))
        changed=page([('爆仓',EXECUTE.replace('16%','20%')),('未知','未知效果')],selected=0)
        self.assertFalse(feedback(choice,changed,session))
        with self.assertRaises(AutomationError):active_action(changed,session)
        append(session,confirm,'pending');self.assertEqual(next_action(selected,session=session),confirm)

    def test_formal_context_selects_and_confirms_once_with_two_frame_feedback(self):
        board,scene,session=fixture([('爆仓',EXECUTE)])
        marked=page([('爆仓',EXECUTE)],selected=0)
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[scene,marked,marked,board,board])
            c.checkpoint=lambda:(_ for _ in ()).throw(Stopped('investment complete')) if getattr(c,'currency_standard_session',None) and c.currency_standard_session.data.get('investment',{}).get('status')=='verified' else None
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual([a['action'] for a in saved['actions'][-2:]],[SELECT,CONFIRM])
            self.assertEqual(c.window.click.call_count,2);self.assertEqual(ledger_status(saved['actions']),'clear')
            self.assertEqual(verified_names(saved),('爆仓',));self.assertFalse(saved['completion_verified'])

    def test_pause_after_a_verified_selection_uses_fresh_selected_proof_before_confirming(self):
        board,scene,session=fixture([('爆仓',EXECUTE)]);selection=active_action(scene,session);append(session,selection)
        marked=page([('爆仓',EXECUTE)],selected=0)
        session['account_verified_epoch']=1;session['collection']['input_epoch']=1;session['client']['input_epoch']=1
        choice=active_action(marked,session);claim=append(session,choice,epoch=1);confirmed(session,choice,board)
        self.assertTrue(valid_effect(claim,session['actions']))
        claim['selection_proof']['input_epoch']=0;self.assertEqual(ledger_status(session['actions']),'unknown')

    def test_receipts_reject_wrong_effect_stale_selection_and_forged_completion(self):
        board,scene,session=fixture([('爆仓',EXECUTE)]);select_and_confirm(board,scene,session)
        self.assertTrue(valid_effect(session['actions'][-1],session['actions']))
        for mutation in ('name','kind','parameters','board','select','epoch','origin'):
            actions=deepcopy(session['actions']);claim=actions[-1]
            if mutation=='select':actions[-2]['target'][2]=2
            elif mutation=='epoch':claim['input_epoch']=1
            elif mutation=='origin':actions[1]['feedback']['node']='3-1'
            elif mutation=='board':claim['investment_effect']['board'][0]='2-2'
            elif mutation=='parameters':claim['investment_effect']['parameters']['threshold']=80
            else:claim['investment_effect'][mutation]='未知'
            with self.subTest(mutation=mutation):self.assertEqual(ledger_status(actions),'unknown')

    def test_declared_box_is_a_pending_obligation_until_typed_inventory_delivery(self):
        for boxes in (1,2):
            board,scene,session=fixture([('保守派',DEFENSE.replace('一件',str(boxes)+'个'))])
            original=deepcopy(session['collection']);board=gift_board(board,boxes)
            select_and_confirm(board,scene,session)
            self.assertEqual(ledger_status(session['actions']),'pending')
            self.assertFalse(session['actions'][-1]['investment_verified'])
            for index in range(boxes):
                session['collection']=deepcopy(original)
                opening=next_action(board,session=session);append(session,opening,'pending')
                bind_source(session,opening,board);bind_reward(session,opening)
                session['actions'][-1]['status']='verified'
                modal=rewards.modal('advanced_equipment_selection',board,gold=30,destination='2-1')
                reward_enter(session,opening,modal)
                claim=next_action(modal,session=session);after=deliver_box(board,opening,claim,index)
                self.assertTrue(transition_ready(claim,after,before=modal,session=session))
                append(session,claim);returned(session,claim,after);reward_completed(session);board=after
                self.assertEqual(ledger_status(session['actions']),'clear' if index==boxes-1 else 'pending')
            claim=session['actions'][session['investment']['claim_action_id']]
            self.assertTrue(claim['investment_verified']);self.assertEqual(len(claim['investment_effect']['reward_actions']),boxes)
            forged=deepcopy(session['actions']);forged[4]['investment_effect']['reward_actions']=[]
            self.assertEqual(ledger_status(forged),'unknown')

    def test_wrong_box_type_or_foreign_pending_trade_cannot_borrow_gift_scope(self):
        board,scene,session=fixture([('保守派',DEFENSE)]);board=gift_board(board)
        select_and_confirm(board,scene,session)
        opening=next_action(board,session=session);append(session,opening,'pending');bind_source(session,opening,board);bind_reward(session,opening)
        session['actions'][-1]['status']='verified'
        modal=rewards.modal('equipment_selection',board,gold=30,destination='2-1');reward_enter(session,opening,modal)
        with self.assertRaises(AutomationError):next_action(modal,session=session)
        session['actions'].append(dict(id=6,action='buy_standard_offer',status='unknown',input_epoch=0))
        with self.assertRaises(AutomationError):reward_scope(session,'choose_standard_reward')
        with self.assertRaises(AutomationError):reward_scope(session,'buy_standard_experience')

    def test_formal_gift_context_stays_pending_until_actual_box_and_gear_are_observed(self):
        board,scene,session=fixture([('保守派',DEFENSE)]);board=gift_board(board)
        marked=page([('保守派',DEFENSE)],selected=0)
        preview=deepcopy(session);select_and_confirm(board,scene,preview)
        opening=next_action(board,session=preview);append(preview,opening,'pending');bind_source(preview,opening,board);bind_reward(preview,opening)
        preview['actions'][-1]['status']='verified'
        modal=rewards.modal('advanced_equipment_selection',board,gold=30,destination='2-1');reward_enter(preview,opening,modal)
        claim=next_action(modal,session=preview);after=deliver_box(board,opening,claim)
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,[scene,marked,marked,board,board,modal,after,after])
            c.checkpoint=lambda:(_ for _ in ()).throw(Stopped('gift complete')) if getattr(c,'currency_standard_session',None) and c.currency_standard_session.data.get('investment',{}).get('status')=='verified' else None
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(ledger_status(saved['actions']),'clear');c.window.click_held.assert_called_once()
            self.assertEqual(c.window.click.call_count,3)
            self.assertTrue(saved['actions'][4]['investment_verified']);self.assertTrue(saved['actions'][-1]['reward_verified'])

    def test_paid_refresh_records_observed_bonus_and_closes_before_replanning(self):
        for gain,xp in ((2,(0,6)),(3,(0,6)),(2,(5,6))):
            board,shop,session=modifier_fixture(gain=gain,xp=xp)
            choice=refresh_action(shop,session);self.assertEqual(len(choice.payload),11);self.assertEqual(choice.payload[7],gain)
            after=refresh.refreshed(shop,choice)
            total=xp[0]+gain;level=3+(total>=xp[1]);newxp=(total-xp[1],10) if level==4 else (total,xp[1])
            trading.hud(after,level=level,xp=newxp)
            receipt=financial_feedback(choice,shop,after,session=session);self.assertIsNotNone(receipt)
            action=append(session,choice);record_financial_feedback(session,choice,receipt)
            self.assertTrue(valid_receipt(action));self.assertEqual(ledger_status(session['actions']),'clear')
            close=next_action(after,session=session)
            self.assertEqual(close.intent,'close_standard_shop');self.assertEqual(close.payload[-2:],newxp)
            returned_board=Scene(list(board.tokens),board.image.copy());trading.hud(returned_board,gold=28,level=level,xp=newxp)
            self.assertTrue(transition_ready(close,returned_board))
            append(session,close,'pending');self.assertEqual(next_action(after,session=session),close)
            wrong=Scene(list(after.tokens),after.image.copy());trading.hud(wrong,xp=(newxp[0]+1,newxp[1]))
            self.assertIsNone(financial_feedback(choice,shop,wrong,session=dict(session,actions=session['actions'][:-2])))

    def test_free_refresh_does_not_receive_paid_only_experience(self):
        _,shop,session=modifier_fixture(price=0)
        choice=refresh_action(shop,session);self.assertEqual(len(choice.payload),7)
        after=refresh.refreshed(shop,choice)
        self.assertIsNotNone(financial_feedback(choice,shop,after,session=session))
        trading.hud(after,xp=(2,6));self.assertIsNone(financial_feedback(choice,shop,after,session=session))

    def test_formal_bonus_refresh_closes_and_recollects_the_new_level_before_another_trade(self):
        board,shop,session=modifier_fixture(xp=(5,6));session['shop_observed_nodes']=['2-1']
        choice=refresh_action(shop,session);after=refresh.refreshed(shop,choice)
        trading.hud(after,level=4,xp=(1,10))
        closed=Scene(list(board.tokens),board.image.copy());trading.hud(closed,gold=28,level=4,xp=(1,10),deployment=(3,4))
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[shop,after,after,closed])
            def stop_closed():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data['actions'][-1]['action']=='close_standard_shop' and store.data['actions'][-1]['status']=='verified':
                    raise Stopped('bonus recollection boundary')
            c.checkpoint=stop_closed
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(c.window.click.call_count,2)
            self.assertEqual(saved['actions'][-2]['receipt']['experience_after'],[1,10])
            self.assertNotIn('2-1',saved['shop_observed_nodes']);self.assertEqual(ledger_status(saved['actions']),'clear')

    def test_refresh_bonus_receipt_cannot_hide_wrong_xp_or_drop_its_source(self):
        _,shop,session=modifier_fixture();choice=refresh_action(shop,session);after=refresh.refreshed(shop,choice)
        trading.hud(after,xp=(2,6));receipt=financial_feedback(choice,shop,after,session=session)
        action=append(session,choice);action['receipt']=receipt
        for mutation in ('xp','source','digest','missing','claimed','shape'):
            actions=deepcopy(session['actions'])
            if mutation=='source':actions[-1]['receipt']['bonus_sources']=[0]
            elif mutation=='digest':actions[-1]['target'][10]='f'*64
            elif mutation=='missing':actions[-1]['target']=actions[-1]['target'][:7]
            elif mutation=='claimed':actions[4]['investment_verified']=False
            elif mutation=='shape':actions[-1]['receipt']['experience_after']=99
            else:actions[-1]['receipt']['experience_after']=[3,6]
            with self.subTest(mutation=mutation):self.assertIn(ledger_status(actions),('pending','unknown'))

    def test_xp_bonus_checks_remainder_and_max_level_without_inventing_intermediate_costs(self):
        for before,after,gain,expected in (((3,(5,6)),(4,(1,10)),2,True),((3,(5,6)),(4,(2,10)),2,False),
            ((3,(5,6)),(5,(1,20)),2,False),((9,(59,60)),(10,None),2,True),((10,None),(10,None),2,True),
            ((3,(0,6)),(3,(0,6)),0,True),((3,(0,6)),(3,(2,6)),3,False)):
            self.assertEqual(experience_gain(*before,*after,gain),expected)

    def test_only_verified_sources_authorize_bonus_and_duplicate_rules_need_their_own_contract(self):
        board,scene,first=fixture([('淘金客',CASH_XP)]);select_and_confirm(board,scene,first)
        self.assertEqual(refresh_bonus(first)[0:2],(2,[4]))
        self.assertEqual(refresh_bonus(dict(actions=[],investment_history=first['investment_history']))[0],0)
        board,scene,second=fixture([('淘金客',CASH_XP.replace('2经验','3经验'))]);select_and_confirm(board,scene,second)
        following=deepcopy(second['actions'])
        for action in following:
            original=action['id'];action['id']+=5
            if original==0:action['target'][0]='2-6'
            elif original==1:
                action['target']=['2-6',5];action['feedback']['node']='3-1'
            elif original==2:action['target']=['2-6',5,'3-1']
            else:
                action['target'][0]='3-1';action['target'][1]=7
                if original==4:
                    effect=action['investment_effect'];effect.update(node='3-1',origin_action_id=7);effect['board'][0]='3-1'
                    action['selection_proof']['source_action_id']=8
        combined=deepcopy(first['actions'])+following
        self.assertEqual(ledger_status(combined),'clear')
        with self.assertRaises(AutomationError):refresh_bonus(dict(actions=combined))
        second['actions']=combined[:-2];second['investment']=dict(status='awaiting',origin_action_id=7,expected_node='3-1')
        second['expected_board']='3-1'
        with self.assertRaises(AutomationError):active_action(scene,second)
        with self.assertRaises(AutomationError):refresh_bonus(first,node='1-1')

    def test_unknown_confirmation_is_durable_and_never_replayed(self):
        board,scene,session=fixture([('爆仓',EXECUTE)]);marked=page([('爆仓',EXECUTE)],selected=0)
        wrong=Scene(list(board.tokens),board.image.copy());rewards.node(wrong,'2-2')
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[scene,marked,marked,wrong,wrong])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown');self.assertEqual(c.window.click.call_count,2)
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(c.window.click.call_count,2)

    def test_pause_account_and_write_failure_keep_the_original_confirmation_unsettled(self):
        for case in ('pause','account','write','receipt'):
            board,scene,session=fixture([('爆仓',EXECUTE)]);marked=page([('爆仓',EXECUTE)],selected=0)
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=trading.StandardTradingTests().context(folder,board,session,[scene,marked,marked,board,board])
                original_input=c.currency_standard_input.side_effect
                def dispatch(current,choice):
                    if case=='pause' and choice.intent==CONFIRM:raise InputInterrupted('paused')
                    return original_input(current,choice)
                c.currency_standard_input.side_effect=dispatch
                snapshot=c.snapshot
                def read():
                    current=snapshot()
                    if case=='account' and current is board:
                        current.tokens=[Token('UID:200000000',t.score,t.box) if normalize(t.text).startswith('uid') else t for t in current.tokens]
                    return current
                c.snapshot=read;persist=StandardSession.persist
                def save(store):
                    last=store.data['actions'][-1]
                    if case=='write' and last['action']==CONFIRM:raise OSError('confirmation write failed')
                    if case=='receipt' and last['action']==CONFIRM and last['status']=='verified':raise OSError('receipt write failed')
                    return persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',save),self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                if case=='write':self.assertEqual(saved['actions'][-1]['action'],SELECT)
                else:self.assertEqual(saved['actions'][-1]['status'],'pending')
                self.assertEqual(c.window.click.call_count,1 if case in ('write','pause') else 2)


if __name__=='__main__':unittest.main()
