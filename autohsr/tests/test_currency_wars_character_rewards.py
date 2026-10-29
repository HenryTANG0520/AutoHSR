"""Advisor/contract choice and real roster delivery are different facts."""
from copy import deepcopy
from dataclasses import asdict
from itertools import count
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import numpy as np

from autohsr.currency_wars import observe
from autohsr.currency_wars_character_rewards import choose,options,observe_shop
from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.currency_wars_match import read_match,supplement_numbers
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import StandardAction,next_action,run_standard,transition_ready
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_rewards import (active_action,basis,enter,feedback,open_bench_action,
    returned,valid_effect,verify_unit)
from autohsr.models import AutomationError,InputInterrupted,Scene,Stopped,Token,normalize
from autohsr.tests import test_currency_wars_standard_rewards as old
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange


def modal(before,kind='hiring_selection',names=('瓦尔特','阿格莱雅','风堇'),tier=3,cash=4):
    page=old.modal('expert_selection',before)
    page.tokens=[t for t in page.tokens if not t.within((.14,.25,.94,.41))]
    if kind=='hiring_selection':
        page.tokens=[t for t in page.tokens if normalize(t.text)!='专家邀请函' and not normalize(t.text).startswith('请选择1个专家顾问')]
        page.tokens.extend((Token((str(tier)+'费' if tier else '')+'聘用书',.99,(.46,.03,.62,.075)),
            Token('请选择1名角色',.99,(.4,.08,.68,.11))))
    centers={1:(.5,),2:(.35,.65),3:(.24,.5,.76),4:(.22,.40,.58,.76),5:(.22,.36,.50,.64,.78)}[len(names)]
    for x,name in zip(centers,names):
        if name=='现金为王':
            page.tokens.append(Token(name,.99,(x-.026,.34,x+.026,.37)))
            if cash is not None:page.tokens.append(Token(str(cash),.99,(x+.046,.26,x+.064,.29)))
        else:
            page.tokens.extend((Token(name,.99,(x-.03,.34,x+.03,.37)),Token('测试',.99,(x-.02,.27,x+.05,.30)),
                                Token('仙舟',.99,(x-.02,.307,x+.05,.332))))
    return page


def fixture(kind='hiring_selection',strategy='aglaea',names=None,tier=3,*,level=3,modify=None):
    before,session=trading.full_board_fixture(gold=25,level=level)
    if level==10:before.tokens=[t for t in before.tokens if not t.within((.13,.865,.18,.9))]
    if modify:modify(before,session)
    session['strategy']=strategy
    _crop(before.image,bench_face(3))[:]=np.random.default_rng(23).integers(0,256,_crop(before.image,bench_face(3)).shape,dtype=np.uint8)
    before.tokens.append(Token('开启',.99,(.344,.819,.371,.866)))
    opening=open_bench_action(before,session)
    session['actions'].append(dict(id=0,action=opening.intent,status='verified',input_epoch=0,target=list(opening.payload),
                                  before='before.png',after='modal.png',reward_basis=basis(before,session,opening.intent)))
    names=names or (('银狼','刃','青雀','停云','现金为王') if kind=='expert_selection' else ('瓦尔特','阿格莱雅','风堇'))
    page=modal(before,kind,names,tier)
    if level==10:
        trading.hud(page,level=10);page.tokens=[t for t in page.tokens if not t.within((.13,.865,.18,.9))]
    enter(session,opening,page)
    return before,page,session


def delivered(before,session,choice,*,tier=None,slot=6,star=1,merge=None,gear=()):
    after=Scene([t for t in before.tokens if normalize(t.text)!='开启'],before.image.copy(),captured_at=time.monotonic())
    _crop(after.image,bench_face(3))[:]=0
    units=deepcopy(session['collection']['units'])
    if merge:
        zone,slot=merge;unit=units[zone+':'+str(slot)]['unit'];unit.update(star=star,equipment=gear)
    else:
        zone='bench';_crop(after.image,bench_face(slot))[:]=np.random.default_rng(600+slot).integers(0,256,_crop(after.image,bench_face(slot)).shape,dtype=np.uint8)
        unit=dict(name=choice.payload[6],zone=zone,slot=slot,star=star,tier=tier or choice.payload[10] or 2,
                  traits=('测试',),equipment=gear,eligible_zones=('front','back'))
        units[zone+':'+str(slot)]=dict(unit=unit)
    return after,units


def receipt(session,choice,after):
    action=dict(id=len(session['actions']),action=choice.intent,status='verified',expected=choice.expected,input_epoch=0,
                target=list(choice.payload),before='choice.png',after='delivered.png')
    session['actions'].append(action);returned(session,choice,after)
    return action


def collect(session,scene,units):
    cells=roster_cells(scene)
    collection=session['collection']
    collection.update(complete=True,units={})
    for cell in cells:
        if cell.state=='occupied':
            record=deepcopy(units[cell.zone+':'+str(cell.slot)])
            record.update(signature=cell.signature,node=cell.node,source='profile.png')
            collection['units'][cell.zone+':'+str(cell.slot)]=record


class CharacterRewardTests(unittest.TestCase):
    def test_crystal_can_open_a_contract_only_at_its_frozen_origin_node(self):
        before,page,session=fixture()
        source=session['actions'][0]
        source.update(action='collect_standard_loot',target=[.7,.34,.01])
        session.pop('reward')
        opening=StandardAction('collect_standard_loot','loot_collected',None,payload=(.7,.34,.01))
        self.assertTrue(transition_ready(opening,page,before=before,session=session))
        enter(session,opening,page);self.assertEqual(active_action(page,session).payload[6],'阿格莱雅')
        old.node(page,'1-2')
        self.assertFalse(transition_ready(opening,page,before=before,session=session))

    def test_hiring_one_to_five_cards_reads_tier_separately_from_selection_count(self):
        for total in range(1,6):
            names=('角色甲','角色乙','阿格莱雅','角色丁','角色戊')[:total]
            for tier in (1,2,3,4,5):
                _,page,session=fixture(names=names,tier=tier)
                candidates=options(page,'hiring_selection');choice=active_action(page,session)
                self.assertEqual(len(candidates),total)
                self.assertEqual(choice.payload[9:],(1,tier))
                self.assertEqual(choice.payload[6],'阿格莱雅' if total>=3 else '角色乙' if total==2 else '角色甲')

    def test_advisor_four_and_five_layouts_follow_named_policy_and_keep_default_cash(self):
        for names in (('银狼','刃','停云','现金为王'),('银狼','现金为王','青雀','停云','刃')):
            before,page,session=fixture('expert_selection',names=names)
            self.assertEqual(observe(page,.65).page_kind,'expert_selection')
            self.assertEqual(active_action(page,session).payload[6],'银狼')
            session['strategy']='default';cash=active_action(page,session)
            self.assertIsNone(cash.payload[6]);self.assertEqual(cash.payload[7],4);self.assertEqual(len(cash.payload),9)

    def test_seele_needs_core_or_missing_support_and_never_uses_a_first_card_fallback(self):
        _,page,session=fixture('expert_selection','seele',('刃','希儿','瓦尔特','现金为王'))
        self.assertEqual(active_action(page,session).payload[6],'希儿')
        session['reward']['basis']['snapshot']['roster'].append(dict(name='希儿',star=3,tier=3,equipment=[],traits=[]))
        self.assertEqual(active_action(page,session).payload[6],'瓦尔特')
        session['reward']['basis']['snapshot']['roster'].append(dict(name='瓦尔特',star=1,tier=5,equipment=[],traits=[]))
        self.assertIsNone(active_action(page,session).payload[6])

    def test_known_gear_and_complete_roster_are_required_before_irreversible_character_choice(self):
        for mutation in ('incomplete','star','tier','gear'):
            _,page,session=fixture()
            source=session['reward']['basis']['snapshot']
            if mutation=='incomplete':source['roster_complete']=False
            elif mutation=='gear':source['roster'][0]['equipment']=None
            else:source['roster'][0][mutation]=None
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):active_action(page,session)

    def test_disabled_missing_trait_duplicate_name_and_changed_header_do_not_authorize_a_choice(self):
        for mutation in ('disabled','trait','duplicate','count','tier'):
            _,page,session=fixture(names=('阿格莱雅',))
            if mutation=='disabled':page.tokens.append(Token('不可选择',.99,(.47,.39,.53,.42)))
            elif mutation=='trait':page.tokens=[t for t in page.tokens if not t.within((.4,.25,.6,.335))]
            elif mutation=='duplicate':page.tokens.append(Token('阿格莱雅',.99,(.7,.34,.76,.37)))
            elif mutation=='count':page.tokens=[Token(t.text.replace('请选择1名','请选择2名'),t.score,t.box) for t in page.tokens]
            else:page.tokens=[Token(t.text.replace('3费聘用书','6费聘用书'),t.score,t.box) for t in page.tokens]
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):active_action(page,session)

    def test_character_choice_ignores_unselected_cash_digits_without_inventing_a_cash_amount(self):
        _,page,session=fixture('expert_selection')
        page.tokens=[t for t in page.tokens if not (t.within((.8,.25,.9,.30)) and re.fullmatch('[0-9]+',t.text))]
        self.assertEqual(active_action(page,session).payload[6],'银狼')
        session['strategy']='default'
        with self.assertRaises(AutomationError):active_action(page,session)

    def test_cash_number_crop_tracks_the_actual_cash_card_and_preserves_conflicts(self):
        for names in (('银狼','刃','停云','现金为王'),('银狼','现金为王','青雀','停云','刃')):
            before,_,_=fixture('expert_selection')
            page=modal(before,'expert_selection',names,cash=None)
            reader=SimpleNamespace(read=lambda image:Scene([Token('12',.99,(.1,.1,.9,.9))]))
            revised=supplement_numbers(page,reader)
            from autohsr.currency_wars_standard_rewards import _options
            self.assertEqual(_options(revised,'expert_selection',.65)[0][4],12)
            number=next(t for t in revised.tokens if t.text=='12')
            revised.tokens.append(Token('4',.99,number.box))
            with self.assertRaises(AutomationError):_options(revised,'expert_selection',.65)

    def test_known_empty_roster_is_captured_only_for_reward_origin_without_deadlock(self):
        def empty(before,session):
            for cell in roster_cells(before):_crop(before.image,cell.roi)[:]=0
            trading.hud(before,deployment=(0,3));session['collection']['units']={};session['collection']['complete']=False
        before,page,session=fixture(strategy='default',modify=empty,names=('新角色',))
        self.assertTrue(session['reward']['basis']['snapshot']['roster_complete'])
        self.assertEqual(session['reward']['basis']['snapshot']['roster'],[])
        choice=active_action(page,session);after,units=delivered(before,session,choice,slot=3)
        self.assertTrue(feedback(choice,page,after,session));receipt(session,choice,after)
        session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        collect(session,after,units);self.assertIsNone(verify_unit(session,after,0))
        self.assertEqual(ledger_status(session['actions']),'clear')
        session.pop('reward');session['actions']=[];session['collection']['units']={};session['collection']['complete']=False
        self.assertEqual(next_action(before,session=session).intent,'open_standard_bench_reward')

    def test_return_board_is_pending_until_every_owned_identity_is_read(self):
        before,page,session=fixture();choice=active_action(page,session);after,units=delivered(before,session,choice)
        self.assertTrue(feedback(choice,page,after,session));action=receipt(session,choice,after)
        self.assertFalse(action['reward_verified']);self.assertEqual(ledger_status(session['actions']),'pending')
        session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        collect(session,after,units);self.assertIsNone(verify_unit(session,after,0))
        self.assertTrue(action['reward_verified']);self.assertEqual(action['reward_effect']['tiers_after'],[3])
        self.assertEqual(ledger_status(session['actions']),'clear')

    def test_actual_context_recollects_character_contract_and_advisor_gifts(self):
        for kind,strategy in (('hiring_selection','aglaea'),('expert_selection','aglaea')):
            before,page,session=fixture(kind,strategy)
            choice=active_action(page,session);after,units=delivered(before,session,choice)
            states=[page,after,after]
            for cell in sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
                unit=units[cell.zone+':'+str(cell.slot)]['unit']
                states.extend((equipment.panel(unit,unit['equipment']),after))
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,before,session,states)
                def stop_done():
                    store=getattr(c,'currency_standard_session',None)
                    if store and store.data.get('reward',{}).get('status')=='verified':raise Stopped('gift verified')
                c.checkpoint=stop_done
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(ledger_status(saved['actions']),'clear');self.assertFalse(saved['completion_verified'])
                self.assertEqual(saved['reward_history'][-1]['choice'][6],choice.payload[6])
                claim=saved['actions'][1];self.assertEqual(claim['reward_effect']['advisor_unlock_declared'],kind=='expert_selection')
                self.assertNotIn('advisor_shop_observations',saved)

    def test_cost_and_owned_gear_are_checked_after_a_merge_without_assuming_a_copy_recipe(self):
        def owned(before,session):session['collection']['units']['bench:4']['unit'].update(name='阿格莱雅',star=1,tier=3,equipment=('armor',))
        for gear,expected in ((('armor',),True),((),False)):
            before,page,session=fixture(names=('阿格莱雅',),modify=owned)
            choice=active_action(page,session);after,units=delivered(before,session,choice,star=2,merge=('bench',4),gear=gear)
            action=receipt(session,choice,after)
            session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
            collect(session,after,units);problem=verify_unit(session,after,0)
            self.assertEqual(problem is None,expected)
            self.assertEqual(action['reward_verified'],expected)

    def test_wrong_cost_missing_role_or_changed_other_unit_never_finishes_the_gift(self):
        for mutation in ('tier','missing','other'):
            before,page,session=fixture();choice=active_action(page,session);after,units=delivered(before,session,choice,tier=5)
            if mutation!='tier':units['bench:6']['unit']['tier']=3
            if mutation=='missing':_crop(after.image,bench_face(6))[:]=0;units.pop('bench:6')
            elif mutation=='other':units['bench:4']['unit']['star']=3
            action=receipt(session,choice,after)
            session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
            collect(session,after,units);self.assertIsNotNone(verify_unit(session,after,0))
            self.assertFalse(action['reward_verified']);self.assertEqual(ledger_status(session['actions']),'pending')

    def test_unknown_equipment_is_observation_pending_and_can_be_reinspected_without_claiming_again(self):
        before,page,session=fixture();choice=active_action(page,session);after,units=delivered(before,session,choice)
        action=receipt(session,choice,after);session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        unknown=deepcopy(units);unknown['bench:6']['unit']['equipment']=None
        collect(session,after,unknown);self.assertIsNone(verify_unit(session,after,0))
        self.assertIn('unit_observation_incomplete',session['reward']);self.assertFalse(action['reward_verified'])
        with self.assertRaises(AutomationError):next_action(after,session=session)
        collect(session,after,units);verify_unit(session,after,0)
        self.assertTrue(action['reward_verified']);self.assertEqual(ledger_status(session['actions']),'clear')

    def test_advisor_merge_preserves_observed_cost_even_without_a_declared_contract_tier(self):
        def owned(before,session):session['collection']['units']['bench:4']['unit'].update(name='银狼',star=1,tier=3,equipment=())
        before,page,session=fixture('expert_selection',modify=owned);choice=active_action(page,session)
        after,units=delivered(before,session,choice,star=2,merge=('bench',4))
        action=receipt(session,choice,after)
        session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        units['bench:4']['unit']['tier']=5
        collect(session,after,units);self.assertIsNotNone(verify_unit(session,after,0))
        self.assertFalse(action['reward_verified'])

    def test_tenth_level_can_receive_a_gift_without_inventing_an_experience_bar(self):
        before,page,session=fixture(level=10,names=('阿格莱雅',))
        self.assertIsNone(read_match(before).experience)
        choice=active_action(page,session);after,units=delivered(before,session,choice)
        self.assertTrue(feedback(choice,page,after,session));action=receipt(session,choice,after)
        session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        collect(session,after,units);self.assertIsNone(verify_unit(session,after,0));self.assertTrue(action['reward_verified'])

    def test_resource_node_or_unconsumed_box_changes_do_not_verify_a_return(self):
        before,page,session=fixture();choice=active_action(page,session)
        for mutation in ('node','gold','xp','box','inventory'):
            after,_=delivered(before,session,choice)
            if mutation=='node':old.node(after,'1-2')
            elif mutation=='gold':trading.hud(after,gold=26)
            elif mutation=='xp':trading.hud(after,xp=(1,6))
            elif mutation=='box':after.tokens.append(Token('开启',.99,(.344,.819,.371,.866)))
            else:equipment.place(after.image,'armor',(2460,330))
            with self.subTest(mutation=mutation):self.assertFalse(feedback(choice,page,after,session))

    def test_role_receipt_shape_tiers_and_original_stars_and_gear_cannot_be_forged(self):
        before,page,session=fixture();choice=active_action(page,session);after,units=delivered(before,session,choice)
        action=receipt(session,choice,after);session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        collect(session,after,units);verify_unit(session,after,0)
        self.assertTrue(valid_effect(action,session['actions']))
        for field,value in (('selection_count',3),('expected_tier',5),('tiers_after',[5]),('stars_before',[1]),('equipment_before',['armor'])):
            actions=deepcopy(session['actions']);actions[-1]['reward_effect'][field]=value
            with self.subTest(field=field):self.assertEqual(ledger_status(actions),'unknown')

    def test_advisor_shop_observation_needs_a_later_priced_quote_and_never_claims_purchase(self):
        before,page,session=fixture('expert_selection');choice=active_action(page,session);after,units=delivered(before,session,choice)
        action=receipt(session,choice,after);session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        collect(session,after,units);verify_unit(session,after,0)
        _,shop,_=trading.purchase_fixture();left=.192
        shop.tokens=[t for t in shop.tokens if not t.within((left,.265,left+.125,.305))]
        shop.tokens.extend((Token('银狼',.99,(left,.27,left+.09,.30)),Token('6',.99,(left+.109,.27,left+.125,.30))))
        observation=dict(id=2,action='open_standard_shop',status='verified',input_epoch=0,before='board.png',after='shop.png')
        session['actions'].append(observation);observe_shop(session,shop,observation);observe_shop(session,shop,observation)
        self.assertEqual(len(session['advisor_shop_observations']),1)
        self.assertEqual(session['advisor_shop_observations'][0]['price'],6)
        self.assertNotIn('purchase_verified',action['reward_effect'])
        self.assertFalse(any(a['action']=='buy_standard_offer' for a in session['actions']))

    def test_unverified_earlier_or_unpriced_advisor_quotes_do_not_prove_shop_availability(self):
        before,page,session=fixture('expert_selection');choice=active_action(page,session);after,units=delivered(before,session,choice)
        action=receipt(session,choice,after);session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        collect(session,after,units);verify_unit(session,after,0)
        _,shop,_=trading.purchase_fixture();left=.192
        shop.tokens=[t for t in shop.tokens if not t.within((left,.265,left+.125,.305))]
        shop.tokens.append(Token('银狼',.99,(left,.27,left+.09,.30)))
        for mutation in ('price','pending','earlier','unverified'):
            current=deepcopy(session)
            observation=dict(id=2,action='open_standard_shop',status='verified',after='shop.png')
            candidate=Scene(list(shop.tokens),shop.image.copy())
            if mutation!='price':candidate.tokens.append(Token('6',.99,(left+.109,.27,left+.125,.30)))
            if mutation=='pending':observation['status']='pending'
            elif mutation=='earlier':observation['id']=0
            elif mutation=='unverified':current['actions'][1]['reward_verified']=False
            observe_shop(current,candidate,observation)
            with self.subTest(mutation=mutation):self.assertNotIn('advisor_shop_observations',current)

    def test_contract_cannot_be_forged_into_a_gear_only_receipt(self):
        before,page,session=fixture();choice=active_action(page,session);after,units=delivered(before,session,choice)
        action=receipt(session,choice,after)
        action['target']=action['target'][:9]
        action['target'][4:8]=['量产型装甲','armor',None,0]
        action['reward_effect'].update(name='量产型装甲',item='armor',unit=None,unit_verified=True)
        action['reward_verified']=True
        self.assertFalse(valid_effect(action,session['actions']))

    def test_character_claim_pause_account_and_write_failures_keep_the_intent_unsettled(self):
        for case in ('write','pause','account','receipt'):
            before,page,session=fixture('expert_selection');choice=active_action(page,session);after,_=delivered(before,session,choice)
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,before,session,[page,after,after])
                if case=='pause':c.currency_standard_input.side_effect=InputInterrupted('pause')
                snapshot=c.snapshot
                def read():
                    current=snapshot()
                    if case=='account' and current is after:
                        current.tokens=[Token('UID:200000000',t.score,t.box) if normalize(t.text).startswith('uid') else t for t in current.tokens]
                    return current
                c.snapshot=read;persist=StandardSession.persist
                def save(store):
                    last=store.data['actions'][-1]
                    if last['action']=='choose_standard_reward':
                        if case=='write' or case=='receipt' and last['status']=='verified':raise OSError('claim write failed')
                    return persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',save),self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                if case=='write':self.assertEqual(len(saved['actions']),1)
                else:self.assertEqual(saved['actions'][-1]['status'],'pending')
                self.assertEqual(c.window.click.call_count,1 if case in ('account','receipt') else 0)
                self.assertFalse(saved.get('reward',{}).get('status')=='verified')

    def test_unknown_claim_is_kept_durable_and_never_repeated(self):
        before,page,session=fixture()
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,[page,page,page])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown');self.assertEqual(c.window.click.call_count,1)
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(c.window.click.call_count,1)


if __name__=='__main__':unittest.main()
