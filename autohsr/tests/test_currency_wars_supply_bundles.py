"""Synthetic complete item fields and actual stock/roster delivery contracts.

These tests do not calibrate a double-equipment game layout. No native runner
or game IO is used; only the already bounded text band and fake Context run.
"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_equipment_catalog import NAMES
from autohsr.currency_wars_reward_items import item_ids, item_payload, items_from_names
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_rewards import active_action, feedback, returned, verify_unit, _options
from autohsr.currency_wars_standard_supply_refresh import table, bind_choice, valid_claim_chain, valid_receipt
from autohsr.currency_wars_supply_policy import matches
from autohsr.models import AutomationError, Scene, Stopped, Token
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_supply_refresh as refresh


def fixture(items=('armor','battery'), size=5, strategy='default'):
    before,page,session=rewards.supply_fixture(size,strategy)
    specs=(('新增角色','、'.join(NAMES[item] if item in NAMES else item for item in items)),)+refresh.UNWANTED[1:size]
    return before,refresh.options(page,specs),session


def board(before, stock=()):
    after=Scene(list(before.tokens),before.image.copy(),captured_at=time.monotonic())
    rewards.node(after,'1-3')
    patch_=_crop(after.image,bench_face(6))
    patch_[:]=np.random.default_rng(55).integers(0,256,patch_.shape,dtype=np.uint8)
    for index,item in enumerate(stock):equipment.place(after.image,item,(2460,(330,430,535,640)[index]))
    return after


def append_action(session, choice, before='choice.png', after='after.png'):
    entry=dict(id=len(session['actions']),action=choice.intent,expected=choice.expected,status='verified',input_epoch=0,
               target=deepcopy(list(choice.payload)),before=before,after=after)
    session['actions'].append(entry)
    return entry


def claim(page,session,after):
    select,highlight=rewards.selected(page,session)
    append_action(session,select);bind_choice(session,select,page)
    choice=active_action(highlight,session)
    append_action(session,choice);bind_choice(session,choice,highlight)
    assert feedback(choice,highlight,after,session)
    returned(session,choice,after)
    return choice


def units_after(session, gear=()):
    units=deepcopy(session['reward']['basis']['snapshot']['roster'])
    units.append(dict(name=session['reward']['choice'][6],zone='bench',slot=6,star=1,tier=1,
                      traits=['测试'],equipment=list(gear),eligible_zones=['front','back']))
    return units


def recollect(session,after,units):
    by_slot={unit['zone']+':'+str(unit['slot']):unit for unit in units}
    session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,complete=True,
        units={cell.zone+':'+str(cell.slot):dict(unit=deepcopy(by_slot[cell.zone+':'+str(cell.slot)]),
            node=cell.node,signature=cell.signature,source='synthetic-profile.png')
            for cell in roster_cells(after) if cell.state=='occupied'})


class SupplyBundleTests(unittest.TestCase):
    def test_normalization_preserves_duplicates_and_rejects_partial_or_unbounded_payloads(self):
        self.assertEqual(item_ids('armor'),('armor',))
        self.assertEqual(item_payload(('armor','armor')),['armor','armor'])
        self.assertEqual(item_ids(['armor','battery']),('armor','battery'))
        self.assertIsNone(items_from_names(('量产型装甲','未知装备')))
        for value in ([],['armor'],['armor','battery','shoe'],['armor',None],['armor','unknown'],True,1,('armor','battery')):
            with self.subTest(value=value),self.assertRaises(AutomationError):item_ids(value)

    def test_complete_pair_is_in_options_policy_target_and_json_without_collapsing_quantity(self):
        for size in (4,5):
            for items in (('armor','battery'),('armor','armor')):
                with self.subTest(size=size,items=items):
                    _,page,session=fixture(items,size)
                    options=_options(page,'supply_selection',.65)
                    choice=active_action(page,session)
                    self.assertEqual(options[0][2],list(items))
                    self.assertEqual(choice.payload[5],list(items))
                    self.assertEqual(matches(options,('item',('armor',)))[0],options[0])
                    self.assertEqual(json.loads(json.dumps(list(choice.payload)))[5],list(items))
                    self.assertEqual(next_action(page,session=session),choice)

    def test_unknown_part_never_authorizes_known_subset(self):
        _,page,session=fixture(('armor','未知装备'))
        self.assertIsNone(_options(page,'supply_selection',.65)[0][2])
        self.assertNotEqual(active_action(page,session).payload[3],0)
        self.assertIsNone(table(page)[0]['item'])
        self.assertEqual(table(page)[0]['item_name'],['量产型装甲','未知装备'])

    def test_selection_and_candidate_digest_freeze_both_items_and_their_order(self):
        _,page,session=fixture()
        select,highlight=rewards.selected(page,session)
        self.assertTrue(feedback(select,page,highlight,session))
        append_action(session,select)
        self.assertEqual(active_action(highlight,session).payload,select.payload)
        for text in ('量产型装甲','量产型装甲、量产型装甲','光能电池、量产型装甲'):
            changed=deepcopy(highlight)
            changed.tokens=[Token(text,t.score,t.box) if t.text=='量产型装甲、光能电池' else t for t in changed.tokens]
            with self.subTest(text=text):
                self.assertFalse(feedback(select,page,changed,session))
                with self.assertRaises(AutomationError):active_action(changed,session)

    def test_unselected_unknown_equipment_names_remain_in_the_frozen_candidate_table(self):
        _,page,session=fixture()
        # The last column is not selected, yet its complete visible unknown
        # name is part of the same frozen table and cannot silently change.
        last=max((t for t in page.tokens if t.within((.03,.61,.97,.67))),key=lambda t:t.center[0])
        page.tokens=[Token('未知装备甲',t.score,t.box) if t is last else t for t in page.tokens]
        select,highlight=rewards.selected(page,session)
        append_action(session,select);bind_choice(session,select,page)
        changed=deepcopy(highlight)
        changed.tokens=[Token('未知装备乙',t.score,t.box) if t.text=='未知装备甲' else t for t in changed.tokens]
        self.assertFalse(feedback(select,page,changed,session))
        with self.assertRaises(AutomationError):active_action(changed,session)
        choice=active_action(highlight,session)
        append_action(session,choice);bind_choice(session,choice,highlight)
        self.assertTrue(valid_claim_chain(session['actions'][-1],session['actions']))
        bad=deepcopy(session['actions'])
        bad[-1]['supply_candidate_table'][-1]['item_name']='未知装备乙'
        self.assertFalse(valid_claim_chain(bad[-1],bad))

    def test_refresh_before_after_and_claim_binding_keep_the_full_list(self):
        _,page,session=refresh.fixture(count_left=1)
        final=refresh.options(page,(('阿格莱雅','反重力皮靴、反重力皮靴'),)+refresh.UNWANTED[1:])
        refresh.quota(final,0)
        refresh.record(session,page,final)
        record=session['actions'][-1]
        self.assertTrue(valid_receipt(record,session['actions']))
        self.assertEqual(record['supply_refresh_receipt']['candidates_after'][0]['item'],['boots','boots'])
        select,highlight=rewards.selected(final,session)
        append_action(session,select);bind_choice(session,select,final)
        choice=active_action(highlight,session)
        entry=append_action(session,choice);bind_choice(session,choice,highlight)
        self.assertTrue(valid_claim_chain(entry,session['actions']))
        for field,value in (('item',['boots','armor']),('item_name',['反重力皮靴','量产型装甲'])):
            bad=deepcopy(session['actions']);bad[2]['supply_refresh_receipt']['candidates_after'][0][field]=value
            with self.subTest(field=field):self.assertFalse(valid_claim_chain(bad[-1],bad))

    def test_all_stock_split_or_all_worn_need_complete_recollection_before_clearing(self):
        for items in (('armor','battery'),('armor','armor')):
            for stock_count in (0,1,2):
                with self.subTest(items=items,stock_count=stock_count):
                    before,page,session=fixture(items)
                    after=board(before,items[:stock_count])
                    claim(page,session,after)
                    self.assertEqual(ledger_status(session['actions']),'pending')
                    self.assertFalse(session['actions'][-1]['reward_verified'])
                    self.assertEqual(session['reward']['status'],'unit_verifying')
                    units=units_after(session,items[stock_count:])
                    recollect(session,after,units)
                    self.assertIsNone(verify_unit(session,after,0))
                    self.assertEqual(session['reward']['status'],'verified')
                    self.assertEqual(ledger_status(session['actions']),'clear')
                    effect=session['actions'][-1]['reward_effect']
                    self.assertEqual(effect['items'],list(items))
                    self.assertEqual(Counter(effect['inventory_after'])+Counter(effect['equipment_after']),Counter(items))

    def test_missing_extra_wrong_or_unknown_worn_gear_keeps_original_pending_claim(self):
        for gear in ((),('armor',),('armor','star'),('armor','battery','battery'),None):
            with self.subTest(gear=gear):
                before,page,session=fixture()
                after=board(before)
                claim(page,session,after)
                units=units_after(session)
                units[-1]['equipment']=gear
                recollect(session,after,units)
                verify_unit(session,after,0)
                self.assertNotEqual(session['reward']['status'],'verified')
                self.assertFalse(session['actions'][-1]['reward_verified'])
                self.assertEqual(ledger_status(session['actions']),'pending')

    def test_extra_or_wrong_stock_is_rejected_before_unit_recollection(self):
        before,page,session=fixture()
        select,highlight=rewards.selected(page,session);append_action(session,select)
        choice=active_action(highlight,session)
        for stock in (('star',),('armor','battery','battery')):
            with self.subTest(stock=stock):self.assertFalse(feedback(choice,highlight,board(before,stock),session))

    def test_receipt_cannot_drop_part_or_rewrite_stock_roster_or_original_source(self):
        before,page,session=fixture(('armor','armor'))
        after=board(before,('armor',));claim(page,session,after)
        recollect(session,after,units_after(session,('armor',)));verify_unit(session,after,0)
        self.assertEqual(ledger_status(session['actions']),'clear')
        mutations=(('items',['armor']),('inventory_after',{}),('equipment_after',[]),('equipment_delivery_schema',True),('roster_after',[]))
        for field,value in mutations:
            bad=deepcopy(session['actions']);bad[-1]['reward_effect'][field]=value
            with self.subTest(field=field):self.assertEqual(ledger_status(bad),'unknown')
        bad=deepcopy(session['actions']);bad[-1]['reward_effect'].pop('equipment_delivery_schema')
        self.assertEqual(ledger_status(bad),'unknown')
        bad=deepcopy(session['actions']);bad[0]['reward_basis']['inventory']={'armor':1}
        self.assertEqual(ledger_status(bad),'unknown')
        bad=deepcopy(session['actions']);bad[-1]['target'][5]=['armor','battery']
        self.assertEqual(ledger_status(bad),'unknown')

    def test_self_consistent_four_star_receipt_cannot_expand_the_supported_copy_delivery(self):
        before,page,session=fixture(('armor','armor'))
        after=board(before,('armor',));claim(page,session,after)
        recollect(session,after,units_after(session,('armor',)));verify_unit(session,after,0)
        bad=deepcopy(session['actions']);effect=bad[-1]['reward_effect']
        effect['stars_after']=[4]
        next(unit for unit in effect['roster_after'] if unit['name']=='新增角色')['star']=4
        self.assertEqual(ledger_status(bad),'unknown')

    def test_single_basic_copy_and_three_to_one_merge_are_the_new_receipt_capability_bound(self):
        for existing,observed,verified in ((False,1,True),(False,2,False),(False,4,False),
                                           (True,1,False),(True,2,True),(True,3,False)):
            with self.subTest(existing=existing,observed=observed):
                before,page,session=fixture(('armor','armor'))
                if existing:
                    # Two explicitly held base copies at separate observed
                    # slots; a supply copy may complete their three-to-one merge.
                    for snapshot in (session['actions'][0]['reward_basis']['snapshot'],session['reward']['basis']['snapshot']):
                        for unit in snapshot['roster']:
                            if unit['zone']=='bench' and unit['slot'] in (4,5):
                                unit.update(name='新增角色',star=1,tier=1,equipment=[])
                after=board(before,('armor','armor'))
                if existing:
                    for slot in (4,5):_crop(after.image,bench_face(slot))[:]=0
                claim(page,session,after)
                units=units_after(session)
                if existing:units=[unit for unit in units if unit['zone']!='bench' or unit['slot'] not in (4,5)]
                units[-1]['star']=observed
                recollect(session,after,units);verify_unit(session,after,0)
                self.assertEqual(session['reward']['status']=='verified',verified)
                self.assertEqual(ledger_status(session['actions']),'clear' if verified else 'pending')

    def test_single_item_new_receipt_and_legacy_receipt_still_work(self):
        before,page,session=fixture(('armor',))
        after=board(before,('armor',));claim(page,session,after)
        recollect(session,after,units_after(session));verify_unit(session,after,0)
        self.assertIsInstance(session['actions'][-1]['target'][5],str)
        self.assertEqual(ledger_status(session['actions']),'clear')
        effect=session['actions'][-1]['reward_effect']
        for field in ('equipment_delivery_schema','items','inventory_before','inventory_after','equipment_before','equipment_after','roster_after'):
            effect.pop(field)
        self.assertEqual(ledger_status(session['actions']),'clear')

    def test_fake_context_selects_confirms_inspects_and_persists_duplicate_pair_once(self):
        before,page,session=fixture(('armor','armor'))
        preview=deepcopy(session)
        select,highlight=rewards.selected(page,preview)
        after=board(before,('armor','armor'))
        claim(page,preview,after)
        units=units_after(preview)
        by_slot={unit['zone']+':'+str(unit['slot']):unit for unit in units}
        frames=[page,highlight,highlight,after,after]
        for cell in sorted((cell for cell in roster_cells(after) if cell.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
            unit=by_slot[cell.zone+':'+str(cell.slot)]
            frames.extend((rewards.node(equipment.panel(unit,unit['equipment']),'1-3'),after))
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,frames)
            def done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data.get('reward',{}).get('status')=='verified':raise Stopped('synthetic pair verified')
            c.checkpoint=done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            claims=[action for action in saved['actions'] if action['action']=='confirm_standard_supply']
            self.assertEqual(len(claims),1)
            self.assertEqual(claims[0]['target'][5],['armor','armor'])
            self.assertEqual(claims[0]['reward_effect']['items'],['armor','armor'])
            self.assertTrue(claims[0]['reward_verified'])
            self.assertEqual(ledger_status(saved['actions']),'clear')
            self.assertFalse(saved.get('completion_verified',False))
