"""Movement custody, independently selected cards and actual returned identities."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import numpy as np

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_collector import roster_cells,collected_snapshot
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_popup import (SELECT,CONFIRM,INSPECT,CLOSE,CENTERS,active_action,arrival,appearance,same_appearance,
    bind_move,bind_intent,candidates,digest,opened,returned,selected,table,valid_child,valid_parent)
from autohsr.currency_wars_standard_exchange import record_intent
from autohsr.models import AutomationError,InputInterrupted,Scene,Stopped,Token,normalize
from autohsr.tests import test_currency_wars_standard_deployment as deployment
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_star as old


def popup(board,slot=None,names=None):
    scene=old.star(False);scene.image=board.image.copy()
    state=read_match(board);rewards.node(scene,state.node)
    trading.hud(scene,gold=state.gold,level=state.level,xp=state.experience,deployment=state.deployment)
    if names:
        scene.tokens=[t for t in scene.tokens if not t.within((.17,.30,.94,.40))]
        for i,name in enumerate(names):
            x=.545+.1237*(i-(len(names)-1)/2)
            scene.tokens.extend((Token('盛会之星一'+name+'女士',.99,(x-.05,.305,x+.05,.33)),Token('详情',.99,(x-.015,.355,x+.015,.38))))
    if slot is not None:
        title=candidates(scene)[slot][2];x=title.center[0]
        scene.tokens.append(Token('已选择',.99,(x-.02,.15,x+.02,.18)))
        _crop(scene.image,(x-.059,.16,x-.056,.33))[:]=240
        cx=title.center[0]
        _crop(scene.image,(cx+.043,.18,cx+.053,.285))[:]=(100,190,240)
        control=next(t for t in scene.tokens if t.text=='确认选择');b=control.box
        _crop(scene.image,(b[0]-.01,b[1]-.01,b[2]+.01,b[3]+.01))[:]=240
    scene.captured_at=time.monotonic()
    return scene


def fixture(exchange_move=False):
    if exchange_move:
        before,after,session,_=exchange.fixture()
        unit=session['collection']['units']['bench:4']['unit'];unit.update(star=3)
        names=iter(('知更鸟','花火','大丽花','星期日','黑天鹅'))
        for record in session['collection']['units'].values():record['unit'].update(name=next(names),traits=('盛会之星',))
        extra=_crop(before.image,bench_face(6));extra[:]=np.random.default_rng(155).integers(0,256,extra.shape,dtype=np.uint8)
        _crop(after.image,bench_face(6))[:]=extra
        cell=next(c for c in roster_cells(before) if (c.zone,c.slot)==('bench',6))
        session['collection']['units']['bench:6']=dict(unit=dict(name='加拉赫',zone='bench',slot=6,star=1,tier=2,traits=('盛会之星',),
            equipment=(),eligible_zones=('front','back')),signature=cell.signature,node=cell.node,source='extra.png')
        choice=next_action(before,session=session)
        assert choice.intent=='stage_standard_exchange'
        # The native exchange protocol inspects both actual identities; these
        # two textures only simulate that a movement was accepted.
        cells={c.zone+':'+str(c.slot):c for c in roster_cells(before)}
        for i,key in enumerate((choice.payload[4]+':'+str(choice.payload[5]),choice.payload[6]+':'+str(choice.payload[7]))):
            patch=_crop(after.image,cells[key].roi);patch[:]=np.random.default_rng(810+i).integers(0,256,patch.shape,dtype=np.uint8)
    else:
        before,session=deployment.frame_and_session();session['strategy']='default'
        for record,name in zip(session['collection']['units'].values(),('知更鸟','花火','大丽花','星期日','黑天鹅')):
            record['unit'].update(name=name,traits=('盛会之星',))
        extra=_crop(before.image,bench_face(6));extra[:]=np.random.default_rng(155).integers(0,256,extra.shape,dtype=np.uint8)
        cell=next(c for c in roster_cells(before) if (c.zone,c.slot)==('bench',6))
        session['collection']['units']['bench:6']=dict(unit=dict(name='加拉赫',zone='bench',slot=6,star=1,tier=2,traits=('盛会之星',),
            equipment=(),eligible_zones=('front','back')),signature=cell.signature,node=cell.node,source='extra.png')
        choice=next_action(before,session=session);assert choice.intent=='deploy_standard_owned'
        after=Scene(list(before.tokens),before.image.copy(),captured_at=time.monotonic())
        face=_crop(before.image,bench_face(choice.target.source_slot));h,w=face.shape[:2]
        x=round(choice.target.end[0]*2560)-w//2
        after.image[480:480+h,x:x+w]=face
        _crop(after.image,bench_face(choice.target.source_slot))[:]=(80,35,25)
        trading.hud(after,deployment=(1,3))
    return before,after,session,choice


def accept(before,page,session,choice):
    action=dict(id=len(session['actions']),action=choice.intent,expected=choice.expected,status='pending',
        target=list(choice.payload),input_epoch=0,before='move-before.png')
    session['actions'].append(action)
    if choice.intent=='stage_standard_exchange':record_intent(session,choice)
    bind_move(session,choice,before)
    action.update(status='verified',after='popup.png');opened(session,choice,page)
    return action


def complete(folder,exchange_move=False,preselected=False,wrong=None,stop_before_return=False,names=None,noise=False):
    before,after,session,movement=fixture(exchange_move)
    index=names.index('花火') if names else 1
    page=popup(before,index if preselected else None,names);highlight=popup(before,index,names)
    preview=deepcopy(session);parent=accept(before,page,preview,movement)
    from autohsr.currency_wars_standard_popup import _expected
    units=_expected(parent)[0]
    cells=sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot))
    frames=[before,page,page]
    if not preselected:frames += [highlight,highlight]
    if noise:
        after=deepcopy(after)
        for cell in roster_cells(after):
            if cell.state=='occupied':
                cell_patch=_crop(after.image,cell.roi)
                cell_patch[::11,::13]=np.maximum(0,cell_patch[::11,::13].astype(int)-1).astype(np.uint8)
    frames += [after,after]
    for cell in cells:
        unit=units[cell.zone+':'+str(cell.slot)]
        if wrong and cell.zone+':'+str(cell.slot)==next(iter(units)):
            unit=dict(unit,**wrong)
        frames += [rewards.node(equipment.panel(unit,unit['equipment']),read_match(after).node),after,after]
    if noise:
        final=deepcopy(after);area=_crop(final.image,cells[0].roi)
        area[:]=np.minimum(255,area.astype(int)+1).astype(np.uint8)
        frames[-1]=final
    c=exchange.StandardExchangeTests().context(folder,before,session,frames)
    reads=0;snapshot=c.snapshot
    def bounded():
        nonlocal reads
        reads+=1
        if reads>140:raise AssertionError('popup fixture exhausted: '+repr([(a['action'],a['status']) for a in c.currency_standard_session.data['actions']]))
        return snapshot()
    c.snapshot=bounded
    def done():
        store=getattr(c,'currency_standard_session',None)
        if store and store.data.get('movement_popup',{}).get('status')=='verified':raise Stopped('popup movement verified')
        if stop_before_return and store and store.data.get('movement_popup',{}).get('status')=='verifying':raise Stopped('popup acknowledged')
    c.checkpoint=done
    with patch('autohsr.currency_wars_replay.save_sample'):
        try:run_standard(c)
        except Stopped:pass
        except AutomationError:
            if not wrong:raise
    return c,StandardSession(c.currency_standard_session.path).data


class StandardPopupTests(unittest.TestCase):
    def test_complete_three_cards_and_unique_selected_feedback_are_separate(self):
        before,_,_,_=fixture();page=popup(before)
        self.assertEqual([c[1] for c in candidates(page)],['大丽花','花火','知更鸟'])
        self.assertIsNone(selected(page));self.assertEqual(selected(popup(before,1)),1)
        for failure in ('missing','duplicate','low','title','border','marker','cost'):
            page=popup(before,1)
            if failure=='missing':page.tokens=[t for t in page.tokens if '知更鸟女士' not in t.text]
            elif failure=='duplicate':page.tokens=[replace(t,text='盛会之星一花火女士') if '知更鸟女士' in t.text else t for t in page.tokens]
            elif failure=='low':page.tokens=[replace(t,score=.5) if '知更鸟女士' in t.text else t for t in page.tokens]
            elif failure=='title':page.tokens=[t for t in page.tokens if t.text!='请选择1名角色成为巨星']
            elif failure=='border':
                _crop(page.image,(CENTERS[0]-.059,.16,CENTERS[0]-.056,.33))[:]=240
                title=next(t for t in page.tokens if '大丽花女士' in t.text);cx=title.center[0]
                _crop(page.image,(cx+.043,.18,cx+.053,.285))[:]=(100,190,240)
            elif failure=='marker':page.tokens.append(Token('已选择',.99,(.40,.15,.44,.18)))
            else:page.tokens.append(Token('消耗4金币',.99,(.5,.4,.6,.43)))
            with self.subTest(failure=failure),self.assertRaises(AutomationError):selected(page)

    def test_orphan_popup_unknown_move_and_changed_money_cannot_grant_input(self):
        before,_,session,movement=fixture();page=popup(before)
        self.assertIsNone(active_action(page,session))
        parent=accept(before,page,session,movement)
        self.assertEqual(ledger_status(session['actions']),'pending')
        self.assertFalse(parent['movement_verified']);self.assertFalse(parent['popup_verified'])
        changed=deepcopy(session);changed['actions'][0]['status']='unknown'
        with self.assertRaises(AutomationError):active_action(page,changed)
        trading.hud(page,gold=read_match(before).gold+1)
        with self.assertRaises(AutomationError):active_action(page,session)
        before,_,session,movement=fixture();session['collection']['units']['bench:1']['unit'].update(name='砂金',traits=())
        movement=next_action(before,session=session)
        with self.assertRaises(AutomationError):accept(before,popup(before),session,movement)

    def test_reordering_chooses_the_actual_sparkle_and_changed_candidates_do_not_confirm(self):
        before,_,session,movement=fixture();page=popup(before)
        page.tokens=[replace(t,text=t.text.replace('花火','临时').replace('大丽花','花火').replace('临时','大丽花')) for t in page.tokens]
        accept(before,page,session,movement)
        choice=active_action(page,session)
        self.assertEqual(choice.payload[3:],(0,'花火'))
        changed=deepcopy(page);changed.tokens=[replace(t,text=t.text.replace('知更鸟','星期日')) for t in changed.tokens]
        with self.assertRaises(AutomationError):active_action(changed,session)

    def test_formal_deployment_and_exchange_each_resume_their_actual_move(self):
        for exchange_move in (False,True):
            with self.subTest(exchange=exchange_move),tempfile.TemporaryDirectory() as folder:
                c,saved=complete(folder,exchange_move)
                parent=saved['actions'][0]
                self.assertTrue(parent['popup_verified']);self.assertTrue(parent['movement_verified'])
                self.assertTrue(valid_parent(parent,saved['actions']));self.assertEqual(ledger_status(saved['actions']),'clear')
                self.assertTrue(saved['collection']['complete']);self.assertFalse(saved['completion_verified'])
                self.assertEqual(c.window.drag.call_count,1)
                self.assertEqual([a['action'] for a in saved['actions'][1:3]],[SELECT,CONFIRM])
                self.assertEqual(len(parent['popup_receipt']['proofs']),len(saved['collection']['units']))
                self.assertTrue(collected_snapshot(c.last_scene,saved,0,'returned').roster_complete)

    def test_existing_preferred_selection_is_observed_without_toggling_and_not_a_movement_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            c,saved=complete(folder,preselected=True,stop_before_return=True)
            self.assertNotIn(SELECT,[a['action'] for a in saved['actions']])
            self.assertEqual(saved['actions'][1]['action'],CONFIRM)
            self.assertFalse(saved['actions'][0]['movement_verified'])
            self.assertEqual(ledger_status(saved['actions']),'pending')
            self.assertEqual(c.window.click.call_count,1)

    def test_wrong_identity_or_gear_cannot_complete_or_replay_the_movement(self):
        for wrong in (dict(name='错误角色'),dict(star=4),dict(tier=5),dict(traits=('变化',))):
            with self.subTest(wrong=wrong),tempfile.TemporaryDirectory() as folder:
                c,saved=complete(folder,wrong=wrong)
                self.assertFalse(saved['actions'][0]['movement_verified'])
                self.assertNotEqual(ledger_status(saved['actions']),'clear')
                self.assertEqual(c.window.drag.call_count,1)

    def test_corrupted_child_proof_or_origin_never_clears_the_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            _,saved=complete(folder)
            for field in ('origin','selection','profile','close','receipt','unrelated','epoch','run','unknown'):
                changed=deepcopy(saved);parent=changed['actions'][0];proof=next(iter(parent['popup_receipt']['proofs'].values()))
                if field=='origin':parent['popup_basis']['gold']+=1
                elif field=='selection':changed['actions'][2]['popup_selection_proof']['options']='x'*64
                elif field=='profile':proof['inspection_action_id']=1
                elif field=='close':changed['actions'][proof['close_action_id']]['target'][3]='x'*64
                elif field=='receipt':parent['popup_receipt']['cells'].pop('bench:9')
                elif field=='epoch':parent['popup_receipt']['input_epoch']+=1
                elif field=='run':parent['popup_receipt']['verified_run']='another-run'
                elif field=='unknown':changed['actions'][proof['inspection_action_id']]['status']='unknown'
                else:changed['actions'][1]['action']='open_standard_shop'
                with self.subTest(field=field):self.assertNotEqual(ledger_status(changed['actions']),'clear')

    def test_confirm_feedback_rejects_changed_bank_resources_or_unrelated_cells(self):
        before,after,session,movement=fixture();page=popup(before,1)
        accept(before,page,session,movement);choice=active_action(page,session)
        from autohsr.currency_wars_standard_popup import feedback
        self.assertTrue(feedback(choice,after,session))
        for mutation in ('gold','node','life','level','roster','bank'):
            changed=deepcopy(after)
            if mutation=='gold':trading.hud(changed,gold=100)
            elif mutation=='node':rewards.node(changed,'1-2')
            elif mutation=='life':changed.tokens=[replace(t,text='10') if t.within((.735,.05,.78,.095)) else t for t in changed.tokens]
            elif mutation=='level':trading.hud(changed,level=9)
            elif mutation=='roster':_crop(changed.image,bench_face(2))[:]=0
            else:changed.image[300:360,2420:2480]=np.random.default_rng(11).integers(0,256,(60,60,3),dtype=np.uint8)
            with self.subTest(mutation=mutation):self.assertFalse(feedback(choice,changed,session))

    def test_partial_animation_can_be_reobserved_without_accepting_a_partial_table(self):
        before,_,session,movement=fixture();page=popup(before)
        parent=dict(id=0,action=movement.intent,expected=movement.expected,status='pending',target=list(movement.payload),input_epoch=0,before='before.png')
        session['actions'].append(parent);bind_move(session,movement,before)
        missing=deepcopy(page);missing.tokens=[t for t in missing.tokens if '花火女士' not in t.text]
        self.assertIsNone(arrival(movement,missing,session))
        self.assertEqual(arrival(movement,page,session),digest(table(page)))
        self.assertEqual(parent['status'],'pending')

    def test_pause_write_and_account_failures_keep_the_pending_selection_and_send_no_click(self):
        for failure in ('pause','write','account'):
            before,_,session,movement=fixture();page=popup(before)
            accept(before,page,session,movement)
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,before,session,[page])
                original=c.currency_standard_input.side_effect
                if failure=='pause':c.currency_standard_input.side_effect=InputInterrupted('fixture paused')
                elif failure=='account':
                    def changed(scene,choice):
                        scene.tokens=[Token('UID:200000000',t.score,t.box) if normalize(t.text).startswith('uid') else t for t in scene.tokens]
                        original(scene,choice)
                    c.currency_standard_input.side_effect=changed
                persist=StandardSession.persist
                def fail_write(store):
                    if store.data['actions'][-1].get('action')==SELECT:raise OSError('fixture disk full')
                    return persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',fail_write if failure=='write' else persist),self.assertRaises((InputInterrupted,AutomationError,OSError)):
                    run_standard(c)
                saved=StandardSession(Path(folder)/'currency-standard-session.json').data
                self.assertFalse(saved['actions'][0]['movement_verified'])
                c.window.click.assert_not_called();c.window.drag.assert_not_called()
                if failure!='write':self.assertEqual(saved['actions'][-1]['status'],'pending')

    def test_unknown_confirmation_is_not_replayed_by_explicit_resume(self):
        before,_,session,movement=fixture();page=popup(before,1)
        accept(before,page,session,movement)
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,[page,page])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',
                    SimpleNamespace(monotonic=Mock(side_effect=[0,61]))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown')
            self.assertFalse(saved['actions'][0]['popup_verified'])
            c.window.click.assert_called_once()
            with self.assertRaises(AutomationError):run_standard(c)
            c.window.click.assert_called_once();c.window.drag.assert_not_called()

    def test_old_selected_proof_is_not_reused_after_pause_or_a_new_run(self):
        before,_,session,movement=fixture();page=popup(before,1)
        accept(before,page,session,movement)
        choice=active_action(page,session)
        action=dict(id=1,action=choice.intent,expected=choice.expected,status='pending',input_epoch=0,target=list(choice.payload),before='confirm.png')
        session['actions'].append(action);bind_intent(session,choice,page)
        self.assertEqual(next_action(page,session=session),choice)
        action['popup_selection_proof']['run_dir']='old-run'
        with self.assertRaises(AutomationError):next_action(page,session=session)

    def test_readonly_or_daily_contexts_never_accept_standard_popup_input(self):
        before,_,session,movement=fixture();page=popup(before)
        accept(before,page,session,movement);choice=active_action(page,session)
        for operation in ('daily','currency_wars','currency_wars_flow_test'):
            c=Context(Runner(Settings(),operation=operation),Mock(),Mock())
            c.last_scene=page
            with self.assertRaises(AutomationError):c.currency_standard_input(page,choice)
            c.window.click.assert_not_called()

    def test_one_to_six_layouts_match_independent_details_and_never_shrink_missing_names(self):
        before,_,_,_=fixture()
        names=('大丽花','知更鸟','星期日','黑天鹅','加拉赫')
        for total in range(1,7):
            roles=names[:total-1]+('花火',)
            page=popup(before,total-1,roles)
            self.assertEqual(len(candidates(page)),total)
            self.assertEqual(selected(page),total-1)
            missing=deepcopy(page);missing.tokens=[t for t in missing.tokens if '花火女士' not in t.text]
            with self.subTest(total=total),self.assertRaises(AutomationError):candidates(missing)
        fixture_data=json.loads((Path(__file__).parent/'fixtures/currency_wars_star_two.json').read_text(encoding='utf-8'))
        for case in fixture_data['cases']:
            page=Scene([Token(**t) for t in case['tokens']],np.zeros((1440,2560,3),dtype=np.uint8))
            self.assertEqual([r[1] for r in candidates(page)],['大丽花','花火'])

    def test_hover_border_alone_cannot_replace_the_selected_gold_card(self):
        before,_,_,_=fixture();page=popup(before,1)
        _crop(page.image,(CENTERS[0]-.059,.16,CENTERS[0]-.056,.33))[:]=240
        self.assertEqual(selected(page),1)
        no_label=deepcopy(page);no_label.tokens=[t for t in no_label.tokens if t.text!='已选择']
        self.assertEqual(selected(no_label),1)
        control=next(t for t in no_label.tokens if t.text=='确认选择');b=control.box
        _crop(no_label.image,(b[0]-.01,b[1]-.01,b[2]+.01,b[3]+.01))[:]=0
        with self.assertRaises(AutomationError):selected(no_label)

    def test_two_and_six_cards_finish_through_the_formal_context_at_the_actual_edge_slot(self):
        for names in (('花火','知更鸟'),('大丽花','知更鸟','星期日','黑天鹅','加拉赫','花火')):
            with self.subTest(total=len(names)),tempfile.TemporaryDirectory() as folder:
                c,saved=complete(folder,names=names)
                parent=saved['actions'][0]
                self.assertEqual(len(parent['movement_popup']['options']),len(names))
                self.assertEqual(saved['actions'][1]['target'][3],names.index('花火'))
                self.assertEqual(ledger_status(saved['actions']),'clear')
                self.assertEqual(c.window.drag.call_count,1)

    def test_new_run_closes_an_old_panel_and_recollects_every_identity(self):
        before,after,session,movement=fixture();page=popup(before,1)
        parent=accept(before,page,session,movement);choice=active_action(page,session)
        claim=dict(id=1,action=CONFIRM,expected=choice.expected,status='pending',input_epoch=0,target=list(choice.payload),before='confirm.png')
        session['actions'].append(claim);bind_intent(session,choice,page);claim.update(status='verified',after='board.png');returned(session,choice,after)
        inspection=active_action(after,session)
        action=dict(id=2,action=INSPECT,expected='character',status='pending',input_epoch=0,target=list(inspection.payload),before='board.png')
        session['actions'].append(action);bind_intent(session,inspection,after);action.update(status='verified',after='old-panel.png',inspection_run_dir='run')
        session['inspecting']=dict(zone=inspection.payload[0],slot=inspection.payload[1],node=inspection.payload[2],signature=inspection.payload[3],
            input_epoch=0,run_dir='run',before='board.png',after='old-panel.png',inspection_action_id=2)
        from autohsr.currency_wars_standard_popup import _expected
        units=_expected(parent)[0];old_unit=dict(next(iter(units.values())),name='旧界面角色')
        frames=[exchange.panel(old_unit),after,after]
        for cell in sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
            unit=units[cell.zone+':'+str(cell.slot)]
            frames += [equipment.panel(unit,unit['equipment']),after,after]
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,frames)
            def done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data.get('movement_popup',{}).get('status')=='verified':raise Stopped('new run proof complete')
            c.checkpoint=done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][3]['action'],'close_standard_popup_stale_panel')
            self.assertTrue(all(p['run_dir']==c.report.run_dir for p in saved['actions'][0]['popup_receipt']['proofs'].values()))
            self.assertEqual(ledger_status(saved['actions']),'clear');c.window.drag.assert_not_called()
            self.assertNotIn('旧界面角色',[r['unit']['name'] for r in saved['collection']['units'].values()])

    def test_failed_write_after_confirmation_keeps_disk_pending_and_cannot_repeat(self):
        before,after,session,movement=fixture();page=popup(before,1);accept(before,page,session,movement)
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,[page,after,after])
            persist=StandardSession.persist
            def fail(store):
                if store.data.get('movement_popup',{}).get('status')=='verifying':raise OSError('fixture final write')
                return persist(store)
            with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',fail),self.assertRaises(OSError):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'pending')
            self.assertFalse(saved['actions'][0]['movement_verified']);c.window.click.assert_called_once()
            with self.assertRaises(AutomationError):run_standard(c)
            c.window.click.assert_called_once()

    def test_current_panel_account_is_checked_before_publishing_any_new_identity(self):
        before,_,session,movement=fixture();page=popup(before);accept(before,page,session,movement)
        from autohsr.currency_wars_standard_popup import require_panel_account
        panel=exchange.panel(session['collection']['units']['bench:2']['unit'])
        panel.tokens.append(Token('UID:200000000',.99,(.01,.96,.10,.99)))
        original=deepcopy(session)
        with self.assertRaises(AutomationError):require_panel_account(panel,session)
        self.assertEqual(session,original)

    def test_boolean_or_float_targets_do_not_equal_frozen_integer_choices(self):
        before,_,session,movement=fixture();page=popup(before,1);accept(before,page,session,movement)
        choice=active_action(page,session)
        for fake in (True,1.0):
            changed=deepcopy(session);target=list(choice.payload);target[3]=fake
            action=dict(id=1,action=CONFIRM,expected=choice.expected,status='pending',input_epoch=0,target=target,before='confirm.png')
            changed['actions'].append(action);bind_intent(changed,choice,page)
            with self.subTest(fake=fake),self.assertRaises(AutomationError):next_action(page,session=changed)

    def test_a_verified_selection_that_later_changes_is_not_automatically_reselected(self):
        before,_,session,movement=fixture();page=popup(before);accept(before,page,session,movement)
        choice=active_action(page,session)
        session['actions'].append(dict(id=1,action=SELECT,expected=choice.expected,status='verified',input_epoch=0,
            target=list(choice.payload),popup_parent_action_id=0,before='unselected.png',after='selected.png'))
        with self.assertRaises(AutomationError):active_action(page,session)

    def test_tiny_pixel_changes_preserve_visual_identity_but_different_portraits_do_not(self):
        before,_,_,_=fixture();cell=next(c for c in roster_cells(before) if (c.zone,c.slot)==('bench',2))
        original=appearance(before,cell.roi);same=deepcopy(before)
        patch=_crop(same.image,cell.roi);patch[::11,::13]=np.maximum(0,patch[::11,::13].astype(int)-1).astype(np.uint8)
        self.assertTrue(same_appearance(original,appearance(same,cell.roi)))
        brighter=deepcopy(before);area=_crop(brighter.image,cell.roi)
        area[:]=np.minimum(255,area.astype(int)+1).astype(np.uint8)
        self.assertNotEqual(original,appearance(brighter,cell.roi))
        self.assertTrue(same_appearance(original,appearance(brighter,cell.roi)))
        wrong=deepcopy(before);patch=_crop(wrong.image,cell.roi)
        patch[:]=np.random.default_rng(891).integers(0,256,patch.shape,dtype=np.uint8)
        self.assertFalse(same_appearance(original,appearance(wrong,cell.roi)))
        with tempfile.TemporaryDirectory() as folder:
            c,saved=complete(folder,noise=True)
            self.assertEqual(ledger_status(saved['actions']),'clear')
            self.assertTrue(collected_snapshot(c.last_scene,saved,0,'final appearance').roster_complete)
            self.assertNotEqual(saved['collection']['units']['bench:2']['signature'],saved['collection']['units']['bench:2']['inspection_signature'])


if __name__=='__main__':unittest.main()
