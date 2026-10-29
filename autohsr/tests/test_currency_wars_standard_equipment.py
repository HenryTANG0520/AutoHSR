"""Observed recipes, material consumption and actual worn-result proofs."""
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import count
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2

from autohsr.currency_wars_collector import collected_snapshot, owned_profile
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_equipment import equipment_template
from autohsr.currency_wars_equipment_catalog import (inventory, inventory_counts, recommendation_facts,
    slots, template)
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_equipment import (choose_equipment, inspectable, proposal,
    resulting_gear, recipe_book, bind_intent, begin_verification, active_action, record_profile, after_close)
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.models import AutomationError, InputInterrupted, Scene, Stopped, Token
from autohsr.tests import test_currency_wars_standard_exchange as exchange_helpers
from autohsr.tests import test_currency_wars_standard_trading as trading_helpers


def place(image, name, point, scale=1.):
    ref = cv2.resize(template(name),None,fx=scale,fy=scale)
    x,y = point
    h,w = ref.shape[:2]
    image[round(y-h/2):round(y-h/2)+h,round(x-w/2):round(x-w/2)+w] = ref


def fixture(strategy='seele', items=('shoe','knife'), worn=()):
    board,session = trading_helpers.full_board_fixture(gold=0)
    units = session['collection']['units']
    for slot in (4,5):
        units.pop('bench:'+str(slot),None);_crop(board.image,bench_face(slot))[:] = 0
    units['front:2']['unit'].update(name='希儿' if strategy=='seele' else '阿格莱雅' if strategy=='aglaea' else '主力角色',
                                   traits=('测试',),equipment=worn)
    if strategy=='seele':
        units['front:1']['unit']['name']='符玄'
        units['back:1']['unit']['name']='瓦尔特'
    for i,name in enumerate(items):
        place(board.image,name,(2460,(330,430,535,640,745,845)[i]))
    session['strategy'] = strategy
    return board,session


def consumed(board, item_slot):
    result = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
    x = (2350,2460)[item_slot//6];y = (330,430,535,640,745,845)[item_slot%6]
    result.image[y-44:y+44,x-44:x+44] = 0
    return result


def panel(unit, gear=()):
    result = exchange_helpers.panel(unit)
    for i,x in enumerate((2195,2310,2420)):
        result.image[1040:1130,x-45:x+45] = 0
        if i<len(gear):
            place(result.image,gear[i],(x,1085))
        else:
            ref = equipment_template('empty_equipment')
            h,w = ref.shape[:2]
            result.image[1085-h//2:1085-h//2+h,x-w//2:x-w//2+w] = ref
    return result


def recommend(detail, product='hard_armor', ingredients=('armor','armor')):
    result = Scene(list(detail.tokens),detail.image.copy(),captured_at=time.monotonic())
    result.tokens += [Token('推荐装备',.99,(.505,.532,.557,.561)),Token('次选装备',.99,(.505,.708,.557,.737))]
    place(result.image,product,(.529*2560,.61*1440))
    for name,y in zip(ingredients,(.590,.626)):
        place(result.image,name,((.529+.029)*2560,y*1440),.65)
    return result


class NativeEquipmentTests(unittest.TestCase):
    def test_pinned_reference_icons_recognize_inventory_and_all_worn_gear(self):
        for item in ('shoe','knife','star','life_flower','pistol','battery','drill','armor','boots','firestorm',
                     'chainsaw','propeller','hard_armor','energy_sail'):
            board,session = fixture(items=(item,))
            self.assertEqual([cell.name for cell in inventory(board) if cell.name],[item],item)
            role = session['collection']['units']['front:2']['unit']
            detail = panel(role,(item,))
            self.assertEqual(slots(detail),(item,'empty','empty'),item)
            actual = owned_profile(detail,dict(zone='front',slot=2,node='1-1'))
            self.assertEqual(actual.equipment,(item,),item)

    def test_current_recommendation_pairs_keep_two_identical_materials(self):
        board,session = fixture()
        detail = panel(session['collection']['units']['front:2']['unit'])
        names,recipes = recommendation_facts(recommend(detail))
        self.assertEqual(names,('hard_armor',))
        self.assertEqual(recipes,({'product':'hard_armor','components':['armor','armor']},))
        self.assertEqual(resulting_gear(('armor',),'armor',recipes),('hard_armor',))
        self.assertIsNone(resulting_gear(('armor',),'armor'))
        with self.assertRaises(AutomationError):recipe_book([dict(product='boots',components=['shoe','knife'])])

    def test_core_goals_reserve_materials_and_unknown_gear_is_not_overwritten(self):
        for strategy,items,old,expected in (('aglaea',('boots',),(),('boots',)),
                ('aglaea',('propeller',),('boots','boots'),('boots','boots','propeller')),
                ('seele',('knife',),('shoe',),('firestorm',)),
                ('seele',('knife',),('star',),('chainsaw',)),
                ('seele',('firestorm',),('firestorm',),('firestorm','firestorm'))):
            board,session = fixture(strategy,items,old)
            choice = proposal(board,session)
            self.assertEqual(choice.details[2],expected)
        board,session = fixture(items=('shoe',))
        self.assertIsNone(proposal(board,session))  # Do not strand half a known pair.
        board,session = fixture(items=('knife',),worn=None)
        self.assertIsNone(proposal(board,session))
        self.assertIsNone(resulting_gear(('boots','boots','propeller'),'knife'))
        self.assertIsNone(resulting_gear(('shoe',),'shoe'))  # Needs observed double-shoe recipe.
        board,session = fixture('aglaea',('boots',),('boots','shoe'))
        self.assertIsNone(proposal(board,session))  # Preserve the propeller slot; do not overshoot 3 -> 5.

    def test_generic_strategy_uses_observed_recipe_and_requires_both_materials(self):
        formula = [dict(product='hard_armor',components=['armor','armor'])]
        for items,allowed in ((('armor',),False),(('armor','armor'),True)):
            board,session = fixture('default',items)
            snapshot = collected_snapshot(board,session,0,'gear_test')
            recs = {unit.zone+':'+str(unit.slot):['hard_armor'] for unit in snapshot.roster}
            recipes = {key:formula for key in recs}
            choice = choose_equipment(snapshot,inventory(board),'default',recs,recipes)
            self.assertEqual(choice is not None,allowed)
        self.assertEqual(resulting_gear(('armor',),'armor',formula),('hard_armor',))
        board,session = fixture('default',('star',),('knife',))
        snapshot = collected_snapshot(board,session,0,'unwanted_combination')
        # A recommended basic cannot authorize an automatic combination into
        # a different item which the current role did not recommend.
        self.assertIsNone(choose_equipment(snapshot,inventory(board),'default',{'front:2':['star']}))

    def test_catalog_conflicts_or_missing_frame_do_not_become_input_targets(self):
        board,session = fixture('aglaea',('boots',))
        for mutation in ('epoch','version','ledger','roster'):
            bad = deepcopy(session)
            if mutation=='epoch':bad['account_verified_epoch']=1
            elif mutation=='version':bad['client']['version']='4.7'
            elif mutation=='ledger':bad['actions']=[dict(action='buy_standard_offer',status='unknown')]
            else:bad['collection']['complete']=False
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):proposal(board,bad)
        board.image = None
        with self.assertRaises(AutomationError):inventory(board)

    def test_one_material_consumption_is_only_inspectable_until_actual_worn_result_is_read(self):
        board,session = fixture('aglaea',('boots',))
        choice = proposal(board,session)
        after = consumed(board,choice.payload[5])
        self.assertTrue(inspectable(choice,board,after))
        role = session['collection']['units']['front:2']['unit']
        for wrong in ((),('shoe',),('boots','propeller')):
            with self.subTest(wrong=wrong),tempfile.TemporaryDirectory() as folder:
                c = exchange_helpers.StandardExchangeTests().context(folder,board,session,[board,after,after,panel(role,wrong)])
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(AutomationError):run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['equipment']['status'],'equipment_mismatch')
                self.assertFalse(saved['actions'][0]['equipment_verified'])
                c.window.drag.assert_called_once()
                c.window.click.assert_called_once()
                with self.assertRaises(AutomationError):run_standard(c)
                c.window.drag.assert_called_once()

    def test_known_core_direct_wear_and_pair_craft_use_real_context_once_per_material(self):
        for variant in ('direct','pair','learned_pair'):
            board,session = fixture('aglaea' if variant=='direct' else 'seele' if variant=='pair' else 'default',
                                    ('boots',) if variant=='direct' else ('shoe','knife') if variant=='pair' else ('armor','armor'))
            key = 'front:1' if variant=='learned_pair' else 'front:2'
            if variant=='learned_pair':
                for record in session['collection']['units'].values():
                    record.update(recommendations=['hard_armor'],equipment_recipes=[dict(product='hard_armor',components=['armor','armor'])])
            role = session['collection']['units'][key]['unit']
            first = consumed(board,6)
            states = [board,first,first,panel(role,('boots',) if variant=='direct' else ('shoe',) if variant=='pair' else ('armor',)),first]
            if variant!='direct':
                second = consumed(first,7)
                states += [second,second,panel(role,('firestorm',) if variant=='pair' else ('hard_armor',)),second]
            expected = 1 if variant=='direct' else 2
            with self.subTest(variant=variant),tempfile.TemporaryDirectory() as folder:
                c = exchange_helpers.StandardExchangeTests().context(folder,board,session,states)
                def stop_completed():
                    store = getattr(c,'currency_standard_session',None)
                    if store and len(store.data.get('equipment_history',[]))==expected:
                        raise Stopped('equipment fixture complete')
                c.checkpoint = stop_completed
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                self.assertEqual(len(saved['equipment_history']),expected)
                self.assertTrue(saved['actions'][0]['equipment_verified'])
                self.assertEqual(saved['collection']['units'][key]['unit']['equipment'],
                                 ['boots'] if variant=='direct' else ['firestorm'] if variant=='pair' else ['hard_armor'])
                self.assertEqual(ledger_status(saved['actions']),'clear')
                self.assertEqual(c.window.drag.call_count,expected)
                self.assertEqual(c.window.click.call_count,expected*2)
                self.assertFalse(saved['completion_verified'])

    def test_other_money_roster_xp_or_inventory_changes_cannot_settle_a_drag(self):
        for mutation in ('unchanged','gold','xp','level','bench','other_item'):
            board,session = fixture('aglaea',('boots','battery'))
            choice = proposal(board,session);bad = consumed(board,6)
            if mutation=='unchanged':bad = board
            elif mutation=='gold':trading_helpers.hud(bad,gold=1)
            elif mutation=='xp':trading_helpers.hud(bad,xp=(2,6))
            elif mutation=='level':trading_helpers.hud(bad,level=4)
            elif mutation=='bench':place(bad.image,'star',(585,1210))
            else:bad = consumed(bad,7)
            with self.subTest(mutation=mutation):self.assertFalse(inspectable(choice,board,bad))

    def test_recommendation_open_is_read_only_and_keeps_the_record_after_reobservation(self):
        board,session = fixture('default',())
        role = session['collection']['units']['front:2']['unit']
        detail = panel(role);opened = recommend(detail)
        session['collection']['units'].pop('front:2')
        session['actions'] = []
        with tempfile.TemporaryDirectory() as folder:
            c = trading_helpers.StandardTradingTests().context(folder,board,session,[board,detail,opened,board,board])
            def stop_closed():
                store = getattr(c,'currency_standard_session',None)
                if store and store.data['actions'] and store.data['actions'][-1]['action']=='close_standard_unit' and store.data['actions'][-1]['status']=='verified':
                    raise Stopped('recommendation fixture complete')
            c.checkpoint = stop_closed
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['collection']['units']['front:2']['recommendations'],['hard_armor'])
            self.assertEqual(saved['collection']['units']['front:2']['equipment_recipes'],[dict(product='hard_armor',components=['armor','armor'])])
            self.assertEqual(c.window.click.call_count,3)

    def test_unknown_drag_feedback_is_retained_and_never_replayed(self):
        board,session = fixture('aglaea',('boots',))
        with tempfile.TemporaryDirectory() as folder:
            c = exchange_helpers.StandardExchangeTests().context(folder,board,session,[board,board,board])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',
                    SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                self.assertEqual(run_standard(c).status,'partial')
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown')
            with self.assertRaises(AutomationError):run_standard(c)
            c.window.drag.assert_called_once()
            c.window.click.assert_not_called()

    def test_pause_and_cross_run_panel_proofs_are_discarded_without_another_drag(self):
        for mutation in ('epoch','run'):
            board,session = fixture('aglaea',('boots',))
            choice = proposal(board,session);after = consumed(board,6)
            action = dict(id=0,action=choice.intent,status='pending',input_epoch=0,before='before.png',target=list(choice.payload))
            session['actions'].append(action);bind_intent(session,choice,board)
            action.update(status='verified',after='after.png');begin_verification(session,choice,board,after)
            inspect = active_action(after,session)
            session['inspecting'] = dict(zone=inspect.payload[0],slot=inspect.payload[1],node=inspect.payload[2],
                signature=inspect.payload[3],equipment_id=0,input_epoch=0,run_dir='run')
            role = session['equipment']['expected']['unit'];detail = panel(role,('boots',))
            profile = owned_profile(detail,session['inspecting'])
            session['collection']['units']['front:2'] = dict(unit=asdict(profile),signature=inspect.payload[3],node='1-1')
            self.assertIsNone(record_profile(session,profile,session['inspecting'],'profile.png',0))
            session['account_verified_epoch' if mutation=='epoch' else 'account_verified_run'] = 1 if mutation=='epoch' else 'new-run'
            close = active_action(detail,session)
            self.assertEqual(close.intent,'close_standard_equipment_stale_panel')
            after_close(session,close,after)
            self.assertIsNone(session['equipment']['proof'])
            self.assertFalse(session['actions'][0]['equipment_verified'])
            self.assertEqual(active_action(after,session).intent,'inspect_standard_equipment_unit')

    def test_write_pause_and_account_failures_never_replay_equipment_consumption(self):
        for case in ('write_before','write_after','pause','account'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                board,session = fixture('aglaea',('boots',));after = consumed(board,6)
                c = exchange_helpers.StandardExchangeTests().context(folder,board,session,[board,after,after])
                original_input = c.currency_standard_input.side_effect
                def submit(scene,choice):
                    if case=='pause':raise InputInterrupted('pause before drag')
                    return original_input(scene,choice)
                c.currency_standard_input.side_effect = submit
                snapshot = c.snapshot
                def changed_account():
                    scene = snapshot()
                    if case=='account' and scene is after:
                        scene.tokens = [Token('UID:200000000',t.score,t.box) if t.text.startswith('UID:') else t for t in scene.tokens]
                    return scene
                c.snapshot = changed_account
                original = StandardSession.persist
                def persist(store):
                    if store.data['actions'] and store.data['actions'][-1]['action']=='stage_standard_equipment':
                        status = store.data['actions'][-1]['status']
                        if case=='write_before' or case=='write_after' and status=='verified':
                            raise OSError('equipment journal write failed')
                    return original(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',persist), \
                        self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                if case=='write_before':
                    self.assertEqual(saved['actions'],[])
                else:
                    self.assertEqual(saved['actions'][-1]['status'],'pending')
                    with self.assertRaises(AutomationError):run_standard(c)
                self.assertEqual(c.window.drag.call_count,1 if case in ('write_after','account') else 0)
                c.window.click.assert_not_called()


if __name__=='__main__':
    unittest.main()
