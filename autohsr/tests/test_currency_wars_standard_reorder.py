"""Whole-roster goals, local optima and fresh custody of empty-slot moves."""
from copy import deepcopy
from dataclasses import replace
from itertools import combinations, product
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from autohsr.currency_wars_collector import collected_snapshot,roster_cells
from autohsr.currency_wars_deployment import _crop
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_deployment import team_score
from autohsr.currency_wars_standard_exchange import choose_exchange,inspectable,record_intent,begin_verification
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_reorder import (POLICY,advance,choose_step,distance,identity,optimize,proposal)
from autohsr.currency_wars_state import UnitState
from autohsr.models import AutomationError,InputInterrupted,Scene,Stopped,Token
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_equipment as equipment


def fixture(local_optimum=False,star=False):
    board,session=trading.full_board_fixture()
    units=session['collection']['units']
    units['front:1']['unit'].update(name='核心',star=4,tier=5,traits=('核心羁绊',),eligible_zones=('front',))
    units['front:2']['unit'].update(name='优选角色',tier=5,traits=('前排',),eligible_zones=('front','back'))
    units['back:1']['unit'].update(name='后台角色',tier=3,traits=('后援',),eligible_zones=('back',))
    units['bench:4']['unit']['traits']=('备战甲',)
    units['bench:5']['unit']['traits']=('备战乙',)
    if local_optimum:
        units['front:2']['unit'].update(tier=3)
        for key,name in (('bench:4','组合甲'),('bench:5','组合乙')):
            units[key]['unit'].update(name=name,traits=('共鸣','协作','追击','强袭'),eligible_zones=('front','back'))
    if star:units['front:2']['unit'].update(name='花火',traits=('盛会之星',))
    for record in units.values():
        if record['unit']['zone']!='bench':record['recommendations']=[]
    return board,session


def moved(snapshot,step):
    source,target,zone,slot,*_=step
    return replace(snapshot,roster=tuple(replace(source,zone=zone,slot=slot) if u==source else
        replace(target,zone=source.zone,slot=source.slot) if target is not None and u==target else u for u in snapshot.roster))


def moved_board(board,step,index=0):
    source,target,zone,slot,*_=step
    after=Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
    cells={(c.zone,c.slot):c for c in roster_cells(board)}
    for i,position in enumerate(((source.zone,source.slot),(zone,slot))):
        area=_crop(after.image,cells[position].roi)
        area[:]=np.random.default_rng(9300+index*2+i).integers(0,256,area.shape,dtype=np.uint8)
        if i==0 and target is None:area[:]=0
    return after


def frames(board,session):
    snapshot=collected_snapshot(board,session,0,'reorder_fixture');goal,score=optimize(snapshot,session['strategy'])
    states=[board];steps=[]
    while distance(snapshot.roster,goal):
        step=choose_step(snapshot,goal,session['strategy']);after=moved_board(board,step,len(steps))
        source,target,zone,slot,*_=step
        states += [after,after]
        expected=[replace(source,zone=zone,slot=slot)]
        if target is not None:expected.append(replace(target,zone=source.zone,slot=source.slot))
        for unit in expected:states += [equipment.panel(unit.__dict__,unit.equipment),after]
        for unit in sorted((u for u in expected if u.zone!='bench'),key=lambda u:(u.zone,u.slot)):
            detail=equipment.panel(unit.__dict__,unit.equipment)
            states += [detail,equipment.recommend(detail),after,after]
        steps.append(step);snapshot=moved(snapshot,step);board=after
    return states,steps,score


class StandardReorderTests(unittest.TestCase):
    def test_exhaustive_small_oracle_scores_unique_teams_and_all_legal_zones(self):
        board,session=fixture();snapshot=collected_snapshot(board,session,0,'oracle')
        for strategy in ('default','aglaea','seele'):
            sample=replace(snapshot,roster=tuple(replace(u,name='希儿' if i==1 else '风堇' if i==3 else u.name)
                                                   for i,u in enumerate(snapshot.roster)))
            best=-1
            for team in combinations(sample.roster,sample.capacity):
                if len({u.name for u in team})!=len(team):continue
                for zones in product(*(u.eligible_zones for u in team)):
                    if not 1<=zones.count('front')<=4 or zones.count('back')>6:continue
                    best=max(best,team_score(team,strategy,zones=zones))
            self.assertEqual(optimize(sample,strategy)[1],best)

    def test_local_optimum_can_require_a_negative_step_without_greedy_reversal(self):
        board,session=fixture(True);snapshot=collected_snapshot(board,session,0,'local_optimum')
        self.assertIsNone(choose_exchange(snapshot))
        goal,score=optimize(snapshot);initial=team_score(tuple(u for u in snapshot.roster if u.zone!='bench'))
        self.assertGreater(score,initial);seen=set();gains=[]
        for _ in range(2*snapshot.capacity):
            if not distance(snapshot.roster,goal):break
            stamp=tuple(sorted((identity(u),u.zone,u.slot) for u in snapshot.roster));self.assertNotIn(stamp,seen);seen.add(stamp)
            step=choose_step(snapshot,goal);gains.append(step[4]);before=distance(snapshot.roster,goal)
            snapshot=moved(snapshot,step)
            self.assertLess(distance(snapshot.roster,goal),before)
            self.assertEqual(optimize(snapshot),(goal,score))
        self.assertLess(gains[0],0);self.assertEqual(distance(snapshot.roster,goal),0)
        self.assertEqual(team_score(tuple(u for u in snapshot.roster if u.zone!='bench')),score)

    def test_randomized_valid_boards_reach_the_same_goal_within_twice_capacity(self):
        board,session=fixture();base=collected_snapshot(board,session,0,'varied');rng=random.Random(1128)
        for index in range(80):
            roster=[]
            for j,u in enumerate(base.roster):
                zones=(u.zone,) if u.zone!='bench' and rng.randrange(2) else ('front','back')
                roster.append(replace(u,star=rng.randrange(1,5),tier=rng.randrange(1,6),eligible_zones=zones,
                                      traits=tuple(str(x) for x in range(4) if rng.randrange(2))))
            snapshot=replace(base,roster=tuple(roster));goal,score=optimize(snapshot)
            for _ in range(2*snapshot.capacity):
                if distance(snapshot.roster,goal)==0:break
                snapshot=moved(snapshot,choose_step(snapshot,goal))
            self.assertEqual(distance(snapshot.roster,goal),0,index)
            self.assertEqual(team_score(tuple(u for u in snapshot.roster if u.zone!='bench')),score)

    def test_one_to_ten_capacity_including_all_nineteen_slots_and_duplicate_copies(self):
        board,session=fixture();base=collected_snapshot(board,session,0,'capacity');rng=random.Random(1030)
        for capacity in range(1,11):
            front=max(1,capacity-6,capacity//3);roster=[]
            positions=[('front',i) for i in range(1,front+1)]+[('back',i) for i in range(1,capacity-front+1)]
            positions += [('bench',i) for i in range(1,10)]
            for i,(zone,slot) in enumerate(positions):
                roster.append(UnitState('角色'+str(i),zone,slot,rng.randrange(1,5),rng.randrange(1,6),
                    ('共同',) if i%2 else ('其他',),(),('front','back')))
            roster[-1]=replace(roster[-1],name=roster[0].name,star=1 if roster[0].star!=1 else 4)
            snapshot=replace(base,capacity=capacity,level=capacity,roster=tuple(roster),bench_occupied=9)
            goal,score=optimize(snapshot)
            for _ in range(2*capacity):
                if distance(snapshot.roster,goal)==0:break
                snapshot=moved(snapshot,choose_step(snapshot,goal))
            self.assertEqual(distance(snapshot.roster,goal),0,capacity)
            field=tuple(u for u in snapshot.roster if u.zone!='bench')
            self.assertEqual(len({u.name for u in field}),capacity);self.assertEqual(team_score(field),score)

    def test_empty_relocation_is_not_a_deployment_or_a_same_zone_shuffle(self):
        board,session=fixture();choice=next_action(board,session=session)
        self.assertEqual(choice.intent,'stage_standard_relocate');self.assertEqual(choice.payload[4:8],('front',2,'back',2))
        self.assertEqual(choice.payload[12:],('',0));self.assertEqual(choice.details[3],POLICY)
        snapshot=collected_snapshot(board,session,0,'relocate');step=choose_step(snapshot,optimize(snapshot)[0])
        self.assertFalse(inspectable(choice,board,board));self.assertTrue(inspectable(choice,board,moved_board(board,step)))

    def test_full_context_reaches_a_frozen_goal_and_independently_reads_each_move(self):
        for local in (False,True):
            with self.subTest(local=local),tempfile.TemporaryDirectory() as folder:
                board,session=fixture(local);states,steps,score=frames(board,session)
                c=exchange.StandardExchangeTests().context(folder,board,session,states)
                def stop_done():
                    data=getattr(c,'currency_standard_session',None)
                    if data and data.data.get('reorder',{}).get('status')=='verified':raise Stopped('whole roster verified')
                c.checkpoint=stop_done
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['reorder']['status'],'verified');self.assertEqual(c.window.drag.call_count,len(steps))
                self.assertEqual(len(saved['reorder']['steps']),len(steps));self.assertFalse(saved['completion_verified'])
                for index in saved['reorder']['steps']:
                    action=saved['actions'][index];self.assertTrue(action['movement_verified']);self.assertTrue(action['reorder_verified'])
                self.assertEqual(saved['reorder']['basis']['score'],score)
                self.assertTrue(all('recommendations' in r and 'equipment_recipes' in r for r in saved['collection']['units'].values()
                                    if r['unit']['zone']!='bench' and r['unit']['name'] in ('优选角色','组合甲','组合乙')))
                if local:
                    from autohsr.currency_wars_standard_collection import retained
                    parent=next(a for a in saved['actions'] if a.get('reorder_preserved'))
                    name=next(iter(parent['reorder_preserved']));cell=next(c for c in roster_cells(states[-1]) if c.zone+':'+str(c.slot)==name)
                    record=saved['collection']['units'][name]
                    self.assertTrue(retained(states[-1],cell,record,saved))
                    for bad in ('name','close','source','after','appearance','move'):
                        changed=deepcopy(saved);action=changed['actions'][parent['id']];proof=action['reorder_preserved'][name]
                        if bad=='name':proof['unit']['name']='不同角色'
                        elif bad=='close':proof['close_action_id']=True
                        elif bad=='source':proof['source_signature']='0'*64
                        elif bad=='after':proof['after_source']='other.png'
                        elif bad=='appearance':proof['after']='invalid'
                        else:action['movement_verified']=False
                        self.assertFalse(retained(states[-1],cell,changed['collection']['units'][name],changed),bad)

    def test_changed_hud_or_unrelated_occupancy_cannot_acknowledge_relocation(self):
        board,session=fixture();choice=next_action(board,session=session)
        snapshot=collected_snapshot(board,session,0,'guard');after=moved_board(board,choose_step(snapshot,optimize(snapshot)[0]))
        for changes in (dict(gold=24),dict(level=4),dict(xp=(1,6)),dict(deployment=(2,3))):
            changed=deepcopy(after);trading.hud(changed,**changes);self.assertFalse(inspectable(choice,board,changed))
        cell=next(c for c in roster_cells(after) if (c.zone,c.slot)==('front',1))
        _crop(after.image,cell.roi)[:]=0;self.assertFalse(inspectable(choice,board,after))

    def test_original_plan_targets_and_remaining_counts_are_independently_validated(self):
        board,session=fixture();choice=next_action(board,session=session)
        snapshot=collected_snapshot(board,session,0,'bind');step=choose_step(snapshot,optimize(snapshot)[0]);after=moved_board(board,step)
        item=dict(id=0,action=choice.intent,status='pending',before='before.png',input_epoch=0,expected=choice.expected,
                  target=list(choice.payload),decision=dict(source=choice.details[0],target=choice.details[1],improvement=choice.details[2],policy=POLICY))
        session['actions'].append(item);record_intent(session,choice);item.update(status='verified',after='after.png')
        begin_verification(session,choice,board,after)
        self.assertEqual(ledger_status(session['actions']),'pending')
        for change in ('goal','count','source','props','expected','credit','root','mode','epoch'):
            mutated=deepcopy(session)
            if change=='goal':mutated['reorder']['basis']['goal'][0][1]='front'
            elif change=='count':mutated['actions'][0]['reorder_step']['after']=1
            elif change=='source':mutated['actions'][0]['target'][4]='bench'
            elif change=='props':mutated['actions'][0]['exchange_expected']['back:2']['star']=4
            elif change=='expected':mutated['actions'][0]['expected']='standard_owned_deployed'
            elif change=='credit':mutated['actions'][0]['decision']['improvement']=400
            elif change=='mode':mutated['actions'][0]['reorder_basis']['snapshot']['mode']='overclock'
            elif change=='epoch':mutated['actions'][0]['input_epoch']=True
            else:mutated['actions'][0]['reorder_root']=True
            if change=='goal':
                with self.assertRaises(AutomationError):proposal(board,mutated)
            else:self.assertEqual(ledger_status(mutated['actions']),'unknown',change)

    def test_pause_discards_the_old_relocation_profile_and_rechecks_the_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            board,session=fixture();states,_,_=frames(board,session);choice=next_action(board,session=session);after=states[1]
            c=exchange.StandardExchangeTests().context(folder,board,session,[board])
            store=StandardSession(Path(c.report.run_dir).parent/'currency-standard-session.json')
            action=store.pending(choice.intent,0,'move.png',choice.expected)
            action.update(target=list(choice.payload),decision=dict(source=choice.details[0],target=choice.details[1],improvement=choice.details[2],policy=POLICY))
            record_intent(store.data,choice);action.update(status='verified',after='after.png');begin_verification(store.data,choice,board,after)
            inspect=next_action(after,session=store.data)
            store.data['inspecting']=dict(zone='back',slot=2,node='1-1',signature=inspect.payload[3],exchange_id=0,input_epoch=0,run_dir='old')
            store.data['account_verified_epoch']=1
            unit=store.data['exchange']['expected']['back:2'];panel=equipment.panel(unit,unit['equipment'])
            stale=next_action(panel,session=store.data);self.assertEqual(stale.intent,'close_standard_exchange_stale_panel')
            from autohsr.currency_wars_standard_exchange import after_close
            after_close(store.data,stale,after)
            self.assertEqual(next_action(after,session=store.data).intent,'inspect_standard_exchange_unit')
            self.assertFalse(action['movement_verified']);self.assertEqual(len(store.data['reorder']['steps']),1)

    def test_empty_relocation_star_popup_returns_to_the_same_global_goal(self):
        from autohsr.tests import test_currency_wars_standard_popup as popup
        from dataclasses import asdict
        board,session=fixture(star=True)
        session['collection']['units']['front:1']['unit']['name']='知更鸟'
        session['collection']['units']['back:1']['unit']['name']='大丽花'
        snapshot=collected_snapshot(board,session,0,'star_relocate');step=choose_step(snapshot,optimize(snapshot)[0])
        self.assertIsNone(step[1]);after=moved_board(board,step);actual=moved(snapshot,step)
        states=[board,popup.popup(board),popup.popup(board),popup.popup(board,1),popup.popup(board,1),after,after]
        for unit in sorted(actual.roster,key=lambda u:(u.zone!='bench',u.zone,u.slot)):
            states += [equipment.panel(asdict(unit),unit.equipment),after,after]
        for unit in sorted((u for u in actual.roster if u.zone!='bench'),key=lambda u:(u.zone!='front',u.slot)):
            detail=equipment.panel(asdict(unit),unit.equipment)
            states += [detail,equipment.recommend(detail),after,after]
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,states)
            def stop_done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data.get('reorder',{}).get('status')=='verified':raise Stopped('star relocation completed')
            c.checkpoint=stop_done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=c.currency_standard_session.data;parent=saved['actions'][0]
            self.assertTrue(parent['popup_verified']);self.assertTrue(parent['movement_verified']);self.assertTrue(parent['reorder_verified'])
            self.assertEqual(saved['movement_popup']['status'],'verified')
            self.assertEqual(ledger_status(saved['actions']),'clear');c.window.drag.assert_called_once()

    def test_closed_relocation_keeps_original_hash_and_accepts_only_bounded_portrait_changes(self):
        for changed_identity in (False,True):
            with self.subTest(changed_identity=changed_identity),tempfile.TemporaryDirectory() as folder:
                board,session=fixture();states,_,_=frames(board,session);returned=deepcopy(states[-1])
                cell=next(c for c in roster_cells(returned) if (c.zone,c.slot)==('back',2));area=_crop(returned.image,cell.roi)
                if changed_identity:area[:]=np.random.default_rng(775).integers(0,256,area.shape,dtype=np.uint8)
                else:area[::11,::13]=np.minimum(255,area[::11,::13].astype(int)+1).astype(np.uint8)
                for i in range(4,len(states)):
                    if states[i] is states[1]:states[i]=returned
                c=exchange.StandardExchangeTests().context(folder,board,session,states)
                def stop_done():
                    store=getattr(c,'currency_standard_session',None)
                    if not store:return
                    data=store.data
                    if data.get('reorder',{}).get('status')=='verified' or (changed_identity and data['actions'] and
                            data['actions'][-1].get('action')=='close_standard_exchange_unit' and data['actions'][-1].get('status')=='verified'):
                        raise Stopped('checked relocation close')
                c.checkpoint=stop_done
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                data=c.currency_standard_session.data;proof=data['exchange']['proofs']['back:2'];parent=data['actions'][0]
                self.assertEqual(parent['movement_verified'],not changed_identity);c.window.drag.assert_called_once()
                if not changed_identity:
                    record=data['collection']['units']['back:2']
                    self.assertNotEqual(proof['signature'],proof['returned_signature'])
                    self.assertEqual(record['signature'],proof['returned_signature']);self.assertEqual(record['exchange_inspection_signature'],proof['signature'])
                else:self.assertEqual(ledger_status(data['actions']),'pending')

    def test_completion_receipt_write_failure_recovers_readonly_without_repeating_the_move(self):
        with tempfile.TemporaryDirectory() as folder:
            board,session=fixture();states,_,_=frames(board,session)
            c=exchange.StandardExchangeTests().context(folder,board,session,states);original=StandardSession.persist;failed=False
            def once(store):
                nonlocal failed
                if not failed and store.data.get('reorder',{}).get('status')=='verified':
                    failed=True;raise OSError('completion receipt disk failure')
                return original(store)
            with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',once),self.assertRaises(OSError):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['reorder']['status'],'active');self.assertTrue(saved['actions'][0]['movement_verified'])
            def stop_done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data.get('reorder',{}).get('status')=='verified':raise Stopped('reconciled readonly')
            c.checkpoint=stop_done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            c.window.drag.assert_called_once();self.assertEqual(c.currency_standard_session.data['reorder']['status'],'verified')

    def test_changed_properties_stop_before_another_drag(self):
        for field,value in (('name','错误角色'),('star',3),('tier',1),('traits',('错误羁绊',)),('equipment',('shoe',))):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as folder:
                board,session=fixture();states,_,_=frames(board,session)
                expected=dict(session['collection']['units']['front:2']['unit'],zone='back',slot=2,**{field:value})
                states[3]=equipment.panel(expected,expected['equipment'])
                c=exchange.StandardExchangeTests().context(folder,board,session,states)
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(AutomationError):run_standard(c)
                saved=c.currency_standard_session.data
                self.assertEqual(saved['exchange']['status'],'identity_mismatch');self.assertEqual(c.window.drag.call_count,1)
                self.assertFalse(saved['actions'][0]['movement_verified'])

    def test_unknown_move_is_never_replayed_and_account_changes_block_input(self):
        for scenario in ('unknown','account','source_write'):
            with self.subTest(scenario=scenario),tempfile.TemporaryDirectory() as folder:
                board,session=fixture();states,_,_=frames(board,session)
                c=exchange.StandardExchangeTests().context(folder,board,session,states)
                original=c.currency_standard_input.side_effect
                if scenario=='unknown':
                    def interrupted(scene,choice):
                        original(scene,choice);raise InputInterrupted('interrupted after drag')
                    c.currency_standard_input.side_effect=interrupted
                elif scenario=='account':
                    def wrong_account(scene,choice):
                        scene.tokens=[Token('UID:200000000',t.score,t.box) if t.text=='UID:100000000' else t for t in scene.tokens]
                        original(scene,choice)
                    c.currency_standard_input.side_effect=wrong_account
                else:
                    original_persist=StandardSession.persist
                    def fail_source(store):
                        if store.data.get('reorder'):raise OSError('source disk failure')
                        return original_persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'):
                    if scenario=='source_write':
                        with patch.object(StandardSession,'persist',fail_source),self.assertRaises(OSError):run_standard(c)
                    else:
                        with self.assertRaises((InputInterrupted,AutomationError)):run_standard(c)
                self.assertEqual(c.window.drag.call_count,1 if scenario=='unknown' else 0)
                if scenario=='unknown':
                    with self.assertRaises(AutomationError):run_standard(c)
                    self.assertEqual(c.window.drag.call_count,1)


if __name__=='__main__':unittest.main()
