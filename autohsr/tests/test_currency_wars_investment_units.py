"""Role grants need observed identities, quantities and native read/close proof."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.currency_wars_investment_policy import parse_effect
from autohsr.currency_wars_investment_units import _gains,baseline,board_ready,eligible,verify
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.currency_wars_standard_investment import valid_effect,verified_names,reward_scope
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_rewards import basis
from autohsr.models import AutomationError,Scene,Stopped,normalize
from autohsr.tests import test_currency_wars_standard_investment as investments
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_rewards as rewards


RANDOM='获得2个随机1星2费角色。'
NAMED='敌方目标被消灭后，【借力球】的伤害分摊比例永久提高0.15%。获得【黑塔】和【缇宝】。'


def fixture(effect=RANDOM):
    board,scene,session=investments.fixture([('赠送策略',effect)])
    for record in session['collection']['units'].values():
        if not record['unit'].get('traits'):record['unit']['traits']=('测试',)
    prior=deepcopy(session);before=Scene(list(board.tokens),board.image.copy());rewards.node(before,'1-6')
    for record in prior['collection']['units'].values():record['node']='1-6'
    source=basis(before,prior,'start_standard_node')
    session['actions'][0]['reward_basis']=source
    return board,scene,session


def delivered(board,session,*,names=('赠送甲','赠送乙'),stars=(1,1),tiers=(2,2)):
    after=Scene(list(board.tokens),board.image.copy());units=deepcopy(session['collection']['units'])
    base=dict(next(iter(units.values()))['unit'])
    for slot,name,star,tier in zip((6,7),names,stars,tiers):
        crop=_crop(after.image,bench_face(slot));crop[:]=np.random.default_rng(990+slot).integers(0,256,crop.shape,dtype=np.uint8)
        units['bench:'+str(slot)]=dict(unit=dict(base,zone='bench',slot=slot,name=name,star=star,tier=tier,
            traits=('测试',),equipment=(),eligible_zones=('front',)),node='2-1')
    return after,units


def states(scene,after,units):
    marked=investments.page([('赠送策略',investments.options(scene)[0].effect)],selected=0)
    output=[scene,marked,marked,after,after]
    for cell in sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
        unit=units[cell.zone+':'+str(cell.slot)]['unit'];detail=equipment.panel(unit,unit['equipment']);rewards.node(detail,'2-1')
        output.append(detail)
        if cell.zone!='bench':output.append(equipment.recommend(detail))
        output.extend((after,after))
    return output


def run_case(folder,effect=RANDOM,*,names=('赠送甲','赠送乙'),stars=(1,1),tiers=(2,2),expect=Stopped):
    board,scene,session=fixture(effect);after,units=delivered(board,session,names=names,stars=stars,tiers=tiers)
    c=exchange.StandardExchangeTests().context(folder,board,session,states(scene,after,units))
    def done():
        store=getattr(c,'currency_standard_session',None)
        if store and store.data.get('investment',{}).get('status') in ('verified','unit_mismatch'):raise Stopped('role grant checked')
    c.checkpoint=done
    with patch('autohsr.currency_wars_replay.save_sample'),unittest.TestCase().assertRaises(expect):run_standard(c)
    return c,StandardSession(c.currency_standard_session.path).data


class UnitGrantTests(unittest.TestCase):
    def test_explicit_count_star_tier_and_named_unknown_star_are_separate(self):
        for count in (1,2,3,9):
            for star,tier in ((1,2),(2,5),(4,1)):
                kind,params,score=parse_effect(f'获得{count}个随机{star}星{tier}费角色。')
                self.assertEqual(kind,'unit_gift');self.assertEqual(dict(params)['count'],count)
                self.assertEqual((dict(params)['star'],dict(params)['tier']),(star,tier))
        kind,params,_=parse_effect(NAMED)
        self.assertEqual((kind,dict(params)['names']),('unit_gift','黑塔|缇宝'))
        self.assertEqual((dict(params)['star'],dict(params)['spillover_basis_points']),(0,15))
        self.assertEqual(dict(parse_effect('获得3个2星4费【希儿】角色。')[1])['names'],'希儿')
        for effect in ('获得2个随机1星2费角色并出售全部角色','获得0个随机1星2费角色',
                       '获得2个随机1星2费角色消耗8金币',NAMED+'并获得其他装备',NAMED.replace('0.15','0')):
            self.assertIsNone(parse_effect(effect)[0])

    def test_original_start_roster_must_have_continuous_origin_and_enough_space(self):
        board,scene,session=fixture();choice=next_action(scene,session=session)
        self.assertEqual(len(choice.payload),9)
        for mutation in ('snapshot','node','epoch','inventory','intervening','space'):
            changed=deepcopy(session);source=changed['actions'][0]['reward_basis']
            if mutation=='snapshot':source['snapshot']['roster_complete']=False
            elif mutation=='node':source['node']='1-5'
            elif mutation=='epoch':source['input_epoch']=2
            elif mutation=='inventory':source['inventory']['armor']=-1
            elif mutation=='intervening':changed['actions'][2]['target'][1]=1
            else:
                for key,row in source['cells'].items():
                    if key.startswith('bench:') and row[0]=='empty':row[0]='occupied'
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):next_action(scene,session=changed)

    def test_confirmation_opens_pending_identity_obligation_instead_of_reporting_delivered(self):
        board,scene,session=fixture();after,_=delivered(board,session)
        investments.select_and_confirm(after,scene,session)
        self.assertEqual(session['investment']['status'],'unit_verifying')
        self.assertEqual(ledger_status(session['actions']),'pending')
        self.assertEqual(verified_names(session),())
        claim=session['actions'][-1];self.assertTrue(valid_effect(claim,session['actions']))
        fake=deepcopy(session['actions']);fake[-1]['investment_verified']=True
        self.assertEqual(ledger_status(fake),'unknown')

    def test_formal_context_recollects_all_roles_then_publishes_exact_delivery(self):
        with tempfile.TemporaryDirectory() as folder:c,saved=run_case(folder)
        self.assertEqual(saved['investment']['status'],'verified')
        claim=saved['actions'][saved['investment']['claim_action_id']]
        self.assertTrue(claim['investment_verified']);self.assertEqual(ledger_status(saved['actions']),'clear')
        self.assertEqual(claim['investment_effect']['unit_delivery']['base_copy_gains'],{'赠送甲':1,'赠送乙':1})
        self.assertEqual(c.window.click.call_count,len(saved['actions'])-3)
        self.assertEqual(verified_names(saved),('赠送策略',))
        self.assertFalse(saved['completion_verified'])
        for mutation in ('baseline','cost','copies','bank','proof','close','unit','epoch','node','duplicate','mixed_run'):
            changed=deepcopy(saved['actions']);grant=changed[claim['id']];data=grant['investment_effect']['unit_delivery']
            if mutation=='baseline':data['origin']['basis']['snapshot']['roster'][0]['star']=4
            elif mutation=='cost':data['roster_after'][2]['tier']=5
            elif mutation=='copies':data['base_copy_gains']['赠送甲']=3
            elif mutation=='bank':data['inventory_after']['shoe']=1
            elif mutation=='proof':data['profiles'][0]['inspection_action_id']=0
            elif mutation=='duplicate':data['profiles'][0]=deepcopy(data['profiles'][1])
            elif mutation=='mixed_run':data['profiles'][0]['run_dir']='another-run'
            else:
                p=data['profiles'][0];close=changed[p['close_action_id']];inspection=changed[p['inspection_action_id']]
                if mutation=='close':close['target'][-1]=0
                elif mutation=='unit':close['collection_read']['unit']['star']=4
                elif mutation=='epoch':inspection['input_epoch']+=1
                else:inspection['collection_basis']['node']='3-1';close['collection_receipt']['basis']['node']='3-1'
            with self.subTest(mutation=mutation):self.assertEqual(ledger_status(changed),'unknown')

    def test_named_grant_records_actual_delta_without_inventing_gift_star(self):
        with tempfile.TemporaryDirectory() as folder:_,saved=run_case(folder,NAMED,names=('黑塔','缇宝'),stars=(2,1))
        claim=saved['actions'][saved['investment']['claim_action_id']]
        self.assertEqual(claim['investment_effect']['parameters']['star'],0)
        self.assertEqual(claim['investment_effect']['unit_delivery']['base_copy_gains'],{'黑塔':3,'缇宝':1})
        self.assertEqual(ledger_status(saved['actions']),'clear')

    def test_random_quantity_wrong_tier_missing_role_or_changed_other_identity_never_settles(self):
        board,scene,session=fixture();before=baseline(session)['basis']['snapshot']['roster']
        original=[dict(u) for u in before]
        role=dict(original[0],zone='bench',slot=6,name='新角色',star=1,tier=2,equipment=[])
        self.assertEqual(_gains(original,original+[role],dict(count=1,star=1,tier=2,names=''),{},{}),{'新角色':1})
        for change in ('count','tier','missing','other'):
            new=deepcopy(original)+[deepcopy(role)];params=dict(count=1,star=1,tier=2,names='')
            if change=='count':params['count']=2
            elif change=='tier':new[-1]['tier']=3
            elif change=='missing':new=new[:-1]
            else:new[0]['star']=4
            with self.subTest(change=change):self.assertIsNone(_gains(original,new,params,{},{}))

    def test_explicit_star_grants_merge_by_base_copies_and_preserve_equipment(self):
        base=dict(name='希儿',zone='front',slot=1,star=1,tier=2,traits=['测试'],equipment=['armor'],eligible_zones=['front'])
        old=[base,dict(base,zone='bench',slot=1,equipment=['shoe'])]
        after=[dict(base,star=2)]
        params=dict(count=1,star=1,tier=2,names='希儿')
        self.assertEqual(_gains(old,after,params,{},dict(shoe=1)),{'希儿':1})
        self.assertIsNone(_gains(old,after,params,{},{}))
        self.assertIsNone(_gains(old,[dict(base,star=2,equipment=[])],params,{},dict(shoe=1,armor=1)))
        self.assertIsNone(_gains(old,[dict(base,star=2,traits=['错误'])],params,{},dict(shoe=1)))

    def test_four_star_is_a_direct_grant_and_not_an_inferred_merge(self):
        u=dict(name='希儿',zone='bench',slot=1,star=4,tier=2,traits=['测试'],equipment=[],eligible_zones=['front'])
        params=dict(count=1,star=4,tier=2,names='')
        self.assertEqual(_gains([], [u], params,{},{}),{'希儿':27})
        self.assertIsNone(_gains([dict(u,star=3)], [u], dict(params,count=2,star=3),{},{}))
        self.assertIsNone(_gains([], [u],dict(params,star=0,names='希儿'),{},{}))

    def test_role_card_position_does_not_replace_complete_effect_or_origin(self):
        _,_,session=fixture()
        for cards in ([('赠送策略',RANDOM)],[('未知','不支持的效果'),('赠送策略',RANDOM)],
                      [('未知甲','未知'),('未知乙','未知'),('赠送策略',RANDOM)]):
            scene=investments.page(cards);choice=next_action(scene,session=session)
            self.assertEqual(choice.payload[2],len(cards)-1)
            self.assertEqual(choice.payload[4],'unit_gift')

    def test_existing_anonymized_card_ocr_reads_named_roles_and_decimal_bonus(self):
        choices=investments.options(investments.page())
        option=next(o for o in choices if o.name.text=='借力打力')
        self.assertEqual(option.kind,'unit_gift')
        self.assertEqual(dict(option.parameters),dict(count=2,star=0,tier=0,names='黑塔|缇宝',spillover_basis_points=15))

    def test_pause_discards_old_panel_source_without_reclaim_or_general_trade_scope(self):
        board,scene,session=fixture();after,units=delivered(board,session)
        investments.select_and_confirm(after,scene,session)
        session['collection']=dict(run_dir='resumed-run',input_epoch=1,units={},complete=False)
        session['account_verified_run']='resumed-run';session['account_verified_epoch']=1
        session['client'].update(verified_run='resumed-run',input_epoch=1)
        session['inspecting']=dict(run_dir='old-run',input_epoch=0,zone='bench',slot=6,node='2-1')
        detail=equipment.panel(units['bench:6']['unit'],());rewards.node(detail,'2-1')
        detail.tokens.extend(t for t in board.tokens if normalize(t.text).startswith('uid'))
        choice=next_action(detail,session=session)
        self.assertEqual(choice.intent,'close_standard_stale_unit')
        self.assertEqual(ledger_status(session['actions']),'pending')
        for intent in ('buy_standard_offer','choose_standard_reward','start_standard_node'):
            with self.subTest(intent=intent),self.assertRaises(AutomationError):reward_scope(session,intent)

    def test_unknown_confirmation_is_not_replayed_and_other_pending_action_blocks_reads(self):
        board,scene,session=fixture();after,_=delivered(board,session)
        investments.select_and_confirm(after,scene,session)
        for status in ('unknown','pending'):
            changed=deepcopy(session);changed['actions'][-1]['status']=status
            with self.subTest(status=status),self.assertRaises(AutomationError):next_action(after,session=changed)
        session['actions'].append(dict(id=5,action='buy_standard_offer',status='unknown'))
        with self.assertRaises(AutomationError):next_action(after,session=session)

    def test_confirm_intent_write_failure_sends_no_second_click(self):
        board,scene,session=fixture();after,units=delivered(board,session)
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,states(scene,after,units));original=StandardSession.persist
            def failed(store):
                if store.data['actions'][-1]['action']=='confirm_standard_investment':raise OSError('fixture intent disk failure')
                return original(store)
            with patch.object(StandardSession,'persist',failed),patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(OSError):run_standard(c)
            self.assertEqual(c.window.click.call_count,1)

    def test_actual_wrong_tier_stops_with_original_confirm_and_no_trade(self):
        with tempfile.TemporaryDirectory() as folder:c,saved=run_case(folder,tiers=(2,3),expect=AutomationError)
        self.assertEqual(saved['investment']['status'],'unit_mismatch')
        self.assertEqual(ledger_status(saved['actions']),'pending')
        self.assertEqual(sum(a['action']=='confirm_standard_investment' for a in saved['actions']),1)
        self.assertFalse(any(a['action'] in ('open_standard_shop','start_standard_node') for a in saved['actions'][3:]))


if __name__=='__main__':unittest.main()
