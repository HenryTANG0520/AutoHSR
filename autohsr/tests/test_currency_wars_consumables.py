"""Tool identity, independent quantities, one input and actual delivery evidence."""
from copy import deepcopy
from dataclasses import asdict
from itertools import count
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import cv2
import numpy as np

from autohsr.currency_wars import observe
from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_consumables import stock,counts,supplement_counts,infinity,TOOLS
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_consumables import proposal,active_action,valid_effect,bind_intent,applied,panel_stale,STAGE,SELECT
from autohsr.models import AutomationError,InputInterrupted,Scene,Stopped,Token,normalize
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_trading as trading


def infinity_symbol(area):
    h,w=area.shape[:2]
    for x in (.3,.7):
        cv2.ellipse(area,(round(w*x),h//2),(round(w*.24),round(h*.21)),0,0,360,(255,255,255),-1)
    for x in (.3,.7):
        cv2.ellipse(area,(round(w*x),h//2),(round(w*.12),round(h*.1)),0,0,360,(0,0,0),-1)


def place_tool(scene,name,quantity=1,slot=12):
    point=(2350,210) if slot==12 else (2460,210) if slot==13 else ((2350,2460)[slot//6],(330,430,535,640,745,845)[slot%6])
    equipment.place(scene.image,name,point)
    cell=next(c for c in stock(scene) if c.slot==slot)
    update_quantity(scene,cell,quantity)
    return cell


def update_quantity(scene,cell,quantity):
    scene.tokens=[t for t in scene.tokens if not t.within(cell.count_roi)]
    x1,y1,x2,y2=cell.count_roi;h,w=scene.image.shape[:2]
    if quantity=='infinite':
        infinity_symbol(scene.image[round(y1*h):round(y2*h),round(x1*w):round(x2*w)])
    elif quantity is not None:
        scene.tokens.append(Token(str(quantity),.99,cell.count_roi))


def fixture(name='projector',quantity=1,*,strategy='aglaea',worn=(),duplicate=False):
    board,session=trading.full_board_fixture(gold=0)
    records=session['collection']['units']
    for i in (4,5):records.pop('bench:'+str(i));_crop(board.image,bench_face(i))[:]=0
    for record in records.values():
        unit=record['unit'];unit.update(traits=('测试',),equipment=(),eligible_zones=(unit['zone'],))
    core=records['front:2']['unit'];core.update(name='希儿' if strategy=='seele' else '阿格莱雅',star=1,tier=4,equipment=worn)
    if duplicate:
        patch=_crop(board.image,bench_face(4));patch[:]=np.random.default_rng(44).integers(0,256,patch.shape,dtype=np.uint8)
        cell=next(c for c in roster_cells(board) if (c.zone,c.slot)==('bench',4))
        records['bench:4']=dict(unit=dict(core,zone='bench',slot=4,equipment=()),signature=cell.signature,node=cell.node,source='earlier.png')
    session.update(strategy=strategy,shop_observed_nodes=['1-1'])
    place_tool(board,name,quantity,13 if name=='wrench2' else 12)
    if name in ('wrench','wrench2'):equipment.place(board.image,'boots',(2460,640))
    if name=='stove':equipment.place(board.image,'armor',(2460,330))
    return board,session


def result(board,session,name,*,merge=False,item=None,mutation=None):
    item=item or ('shoe' if name=='stove' else 'boots')
    after=Scene(list(board.tokens),board.image.copy())
    units=deepcopy(session['collection']['units'])
    source=next(c for c in stock(board) if c.name==name)
    if source.quantity_source=='single_cell':
        height,width=equipment.template(name).shape[:2]
        x,y=round(source.point[0]*2560),round(source.point[1]*1440)
        left,top=round(x-width/2),round(y-height/2)
        after.image[top:top+height,left:left+width]=board.image[y-44,x-44]
    elif source.quantity!='infinite':update_quantity(after,source,source.quantity-1)
    if name in ('projector','projector2'):
        if merge:
            _crop(after.image,bench_face(4))[:]=0;units.pop('bench:4');units['front:2']['unit']['star']=2
        else:
            patch=_crop(after.image,bench_face(4));patch[:]=np.random.default_rng(44).integers(0,256,patch.shape,dtype=np.uint8)
            units['bench:4']=dict(unit=dict(units['front:2']['unit'],zone='bench',slot=4,equipment=()))
    elif name in ('wrench','wrench2'):
        old=units['front:2']['unit']['equipment'];units['front:2']['unit']['equipment']=()
        for i,gear in enumerate(old):equipment.place(after.image,gear,(2460,(330,430,535)[i]))
    elif name=='stove':
        after=equipment.consumed(after,6);equipment.place(after.image,item,(2460,330))
    else:equipment.place(after.image,item,(2460,330))
    if mutation=='missing_copy':
        _crop(after.image,bench_face(4))[:]=0;units.pop('bench:4')
    elif mutation=='wrong_role':units['bench:4']['unit']['name']='其他角色'
    elif mutation=='worn':units['front:2']['unit']['equipment']=('armor',)*3
    elif mutation=='other_role':units['front:1']['unit']['star']=4
    return after,units


def token_page(board,names=('反重力皮靴','高周波电锯','光速螺旋桨','很硬的甲')):
    page=rewards.modal('advanced_equipment_selection',board,gold=0)
    page.tokens=[Token('好运令牌' if t.text=='进阶武装箱' else t.text,t.score,t.box) for t in page.tokens]
    page.tokens=[t for t in page.tokens if not t.within((.25,.22,.90,.30))]
    for x,name in zip((.346,.497,.647,.799),names):page.tokens.append(Token(name,.99,(x-.06,.25,x+.06,.28)))
    return page


def states(board,after,units,*,name):
    output=[board]
    if name=='token':
        page=token_page(board);output.extend((page,page))
    output.extend((after,after))
    for cell in sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
        unit=units[cell.zone+':'+str(cell.slot)]['unit'];detail=equipment.panel(unit,unit['equipment'])
        output.append(detail)
        if cell.zone!='bench':output.append(equipment.recommend(detail))
        output.extend((after,after))
    return output


def run_case(folder,board,session,after,units,name,*,complete=True):
    c=exchange.StandardExchangeTests().context(folder,board,session,states(board,after,units,name=name))
    if complete:
        def done():
            store=getattr(c,'currency_standard_session',None)
            if store and store.data.get('consumable',{}).get('status')=='verified':raise Stopped('tool verified')
        c.checkpoint=done
    with patch('autohsr.currency_wars_replay.save_sample'):
        if complete:
            with unittest.TestCase().assertRaises(Stopped):run_standard(c)
        else:run_standard(c)
    return c,StandardSession(c.currency_standard_session.path).data


class ConsumableTests(unittest.TestCase):
    def test_stock_recognizes_all_tool_icons_with_independent_quantity_fields(self):
        for name in TOOLS:
            board,_=fixture(name,2,worn=('armor',)*3)
            found=next(c for c in stock(board) if c.name==name)
            self.assertEqual(found.quantity,2,name)
        board,_=fixture('projector')
        source=next(c for c in stock(board) if c.name=='projector')
        for quantity in (0,1,2,3,8,12,99):
            update_quantity(board,source,quantity)
            self.assertEqual(next(c.quantity for c in stock(board) if c.name=='projector'),quantity)

    def test_infinity_cannot_be_a_vertical_eight_or_two_separate_zeros(self):
        area=np.zeros((34,50,3),np.uint8);infinity_symbol(area);self.assertTrue(infinity(area))
        for text in ('8','00','2'):
            fake=np.zeros_like(area);cv2.putText(fake,text,(3,28),cv2.FONT_HERSHEY_SIMPLEX,.8,(255,255,255),2)
            self.assertFalse(infinity(fake),text)
        board,_=fixture('wrench2','infinite',worn=('armor',)*3)
        self.assertEqual(next(c.quantity for c in stock(board) if c.name=='wrench2'),'infinite')
        cell=next(c for c in stock(board) if c.name=='wrench2')
        board.tokens.append(Token('8',.4,cell.count_roi))
        self.assertIsNone(next(c.quantity for c in stock(board) if c.name=='wrench2'))

    def test_field_refinement_requires_two_readings_and_preserves_conflicts(self):
        board,_=fixture('projector',None);cell=next(c for c in stock(board) if c.name=='projector')
        for values,expected in ((('2','2'),2),(('1','2'),None),(('2',None),None)):
            reader=SimpleNamespace(read_number=Mock(side_effect=[Token(t,.99,(0,0,1,1)) if t else None for t in values]))
            refined=supplement_counts(board,reader)
            self.assertEqual(next(c.quantity for c in stock(refined) if c.name=='projector'),expected)
        board.tokens.append(Token('-2',.99,cell.count_roi))
        reader=SimpleNamespace(read_number=Mock(return_value=Token('2',.99,(0,0,1,1))))
        self.assertIsNone(next(c.quantity for c in stock(supplement_counts(board,reader)) if c.name=='projector'))

    def test_unknown_zero_conflicting_or_low_quality_counts_do_not_authorize_use(self):
        for value in (None,0,'-2','1/2'):
            board,session=fixture('projector',value)
            with self.subTest(value=value):self.assertIsNone(proposal(board,session))
        board,session=fixture('projector',1);cell=next(c for c in stock(board) if c.name=='projector')
        board.tokens.append(Token('2',.99,cell.count_roi));self.assertIsNone(proposal(board,session))

    def test_default_strategy_leaves_named_core_tools_untouched(self):
        board,session=fixture('projector');session['strategy']='default'
        self.assertIsNone(proposal(board,session))

    def test_single_lower_inventory_card_is_distinct_from_an_unreadable_numeric_badge(self):
        board,session=fixture('projector',0)
        original=next(c for c in stock(board) if c.name=='projector')
        board.image[140:280,2295:2410]=0;board.tokens=[t for t in board.tokens if not t.within(original.count_roi)]
        place_tool(board,'projector',None,6)
        cell=next(c for c in stock(board) if c.name=='projector')
        self.assertEqual((cell.quantity,cell.quantity_source),(1,'single_cell'))
        self.assertEqual(proposal(board,session).payload[5:7],(6,1))
        after,units=result(board,session,'projector')
        with tempfile.TemporaryDirectory() as folder:
            c,saved=run_case(folder,board,session,after,units,'projector')
            self.assertEqual(saved['actions'][0]['consumable_origin']['count_mode'],'single_cell')
            self.assertEqual(ledger_status(saved['actions']),'clear');c.window.drag.assert_called_once()
        x1,y1,x2,y2=cell.count_roi
        cv2.putText(board.image,'2',(round(x1*2560)+7,round(y2*1440)-6),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),2)
        self.assertIsNone(next(c.quantity for c in stock(board) if c.name=='projector'))
        self.assertIsNone(proposal(board,session))

    def test_formal_context_verifies_all_six_tool_variants_and_actual_stock(self):
        for name in ('projector','projector2','wrench','wrench2','stove','token'):
            quantity='infinite' if name=='wrench2' else 2
            worn=('armor',)*3 if name in ('wrench','wrench2') else ()
            board,session=fixture(name,quantity,worn=worn);after,units=result(board,session,name)
            self.assertEqual(next_action(board,session=session).intent,STAGE,name)
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                c,saved=run_case(folder,board,session,after,units,name)
                action=saved['actions'][0]
                self.assertTrue(action['consumable_verified']);self.assertTrue(valid_effect(action,saved['actions']))
                self.assertEqual(ledger_status(saved['actions']),'clear');c.window.drag.assert_called_once()
                self.assertEqual(sum(a['action']==STAGE for a in saved['actions']),1)
                self.assertEqual(sum(a['action']==SELECT for a in saved['actions']),1 if name=='token' else 0)
                self.assertEqual(action['consumable_effect']['stock_after'],dict(counts(stock(after))))
                self.assertEqual(len(action['consumable_effect']['profile_proofs']),len(units))
                self.assertFalse(saved['completion_verified'])
                if name=='token':
                    selection=next(a for a in saved['actions'] if a['action']==SELECT)
                    orphan=[dict(deepcopy(selection),id=0)]
                    self.assertEqual(ledger_status(orphan),'unknown')
                    for mutation in ('digest','duplicate','item'):
                        wrong=deepcopy(saved['actions']);claim=wrong[selection['id']]
                        if mutation=='digest':claim['target'][3]='0'*64
                        elif mutation=='item':claim['target'][2]='firestorm'
                        else:wrong.append(dict(deepcopy(claim),id=len(wrong)))
                        with self.subTest(selection_mutation=mutation):self.assertEqual(ledger_status(wrong),'unknown')

    def test_copy_can_merge_two_existing_one_star_units_without_losing_other_roles(self):
        for merge in (False,True):
            board,session=fixture('projector',1,duplicate=merge,worn=('boots',))
            after,units=result(board,session,'projector',merge=merge)
            with self.subTest(merge=merge),tempfile.TemporaryDirectory() as folder:
                c,saved=run_case(folder,board,session,after,units,'projector')
                core=saved['collection']['units']['front:2']['unit']
                self.assertEqual(core['star'],2 if merge else 1);self.assertEqual(core['equipment'],['boots'])
                if merge:self.assertNotIn('bench:4',saved['collection']['units'])
                else:self.assertEqual(saved['collection']['units']['bench:4']['unit']['equipment'],[])
                c.window.drag.assert_called_once()

    def test_token_unknown_unselected_names_do_not_block_the_known_strategy_item(self):
        board,session=fixture('token',1)
        after,units=result(board,session,'token');frames=states(board,after,units,name='token')
        page=token_page(board,('反重力皮靴','未知进阶装甲','光速螺旋桨','很硬的甲'))
        frames[1:3]=[page,page]
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,frames)
            def done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data.get('consumable',{}).get('status')=='verified':raise Stopped('token verified')
            c.checkpoint=done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            self.assertEqual(c.currency_standard_session.data['consumable']['selected_item'],'boots')

    def test_changed_or_missing_role_after_copy_remains_unsettled(self):
        for mutation in ('missing_copy','wrong_role','other_role'):
            board,session=fixture('projector',1);after,units=result(board,session,'projector',mutation=mutation)
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(AutomationError):run_case(folder,board,session,after,units,'projector',complete=False)
                saved=StandardSession(Path(folder)/'currency-standard-session.json').data
                self.assertFalse(saved['actions'][0]['consumable_verified']);self.assertEqual(ledger_status(saved['actions']),'pending')

    def test_missing_tool_feedback_is_unknown_and_never_replayed(self):
        board,session=fixture('projector',1)
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,[board,board,board])
            timer=SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',timer):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][0]['status'],'unknown');c.window.drag.assert_called_once()
            with self.assertRaises(AutomationError):run_standard(c)
            c.window.drag.assert_called_once()

    def test_write_pause_and_account_failures_cannot_replay_a_tool(self):
        for case in ('write_before','write_after','pause','account'):
            board,session=fixture('projector',1);after,_=result(board,session,'projector')
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,board,session,[board,after,after])
                original_input=c.currency_standard_input.side_effect
                def submit(scene,choice):
                    if case=='pause':raise InputInterrupted('pause before tool use')
                    return original_input(scene,choice)
                c.currency_standard_input.side_effect=submit
                snapshot=c.snapshot
                def changed_account():
                    scene=snapshot()
                    if case=='account' and scene is after:
                        scene.tokens=[Token('UID:200000000',t.score,t.box) if t.text.startswith('UID:') else t for t in scene.tokens]
                    return scene
                c.snapshot=changed_account
                original=StandardSession.persist
                def persist(store):
                    if store.data['actions'] and store.data['actions'][-1]['action']==STAGE:
                        if case=='write_before' or case=='write_after' and store.data['actions'][-1]['status']=='verified':
                            raise OSError('tool journal write failed')
                    return original(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',persist),self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                if case=='write_before':self.assertEqual(saved['actions'],[])
                else:
                    self.assertEqual(saved['actions'][-1]['status'],'pending')
                    with self.assertRaises(AutomationError):run_standard(c)
                self.assertEqual(c.window.drag.call_count,1 if case in ('write_after','account') else 0)
                c.window.click.assert_not_called()

    def test_consumable_inspection_must_belong_to_the_current_run_and_own_namespace(self):
        board,session=fixture('projector',1);after,units=result(board,session,'projector')
        choice=proposal(board,session)
        action=dict(id=0,action=STAGE,status='pending',input_epoch=0,target=list(choice.payload),before='before.png',expected=choice.expected)
        session['actions'].append(action);bind_intent(session,choice,board)
        action.update(status='verified',after='after.png');applied(session,choice,after)
        inspect=active_action(after,session);zone,slot,node,signature,origin_id=inspect.payload
        run=session['account_verified_run']
        session['actions'].append(dict(id=1,action=inspect.intent,status='verified',input_epoch=0,
            target=list(inspect.payload),before='board.png',after='panel.png',inspection_run_dir=run))
        session['inspecting']=dict(zone=zone,slot=slot,node=node,signature=signature,consumable_id=origin_id,
            inspection_action_id=1,input_epoch=0,run_dir=run,before='board.png',after='panel.png')
        detail=equipment.panel(units[zone+':'+str(slot)]['unit'],())
        self.assertFalse(panel_stale(session))
        for mutation in ('epoch','run','namespace','source'):
            wrong=deepcopy(session)
            if mutation=='epoch':wrong['account_verified_epoch']=1
            elif mutation=='run':wrong['account_verified_run']='another-run'
            elif mutation=='namespace':wrong['inspecting']['consumable_id']=5
            else:wrong['inspecting']['after']='unrelated.png'
            with self.subTest(mutation=mutation):
                self.assertTrue(panel_stale(wrong))
                self.assertEqual(active_action(detail,wrong).intent,'close_standard_consumable_stale_panel')
                self.assertFalse(wrong['actions'][0]['consumable_verified'])

    def test_token_missing_changed_or_unwanted_candidates_never_default_to_a_card(self):
        for case in ('missing','changed','unwanted'):
            board,session=fixture('token',1);choice=proposal(board,session)
            action=dict(id=0,action=STAGE,status='pending',input_epoch=0,target=list(choice.payload),before='before.png',expected=choice.expected)
            session['actions'].append(action);bind_intent(session,choice,board);action.update(status='verified',after='selection.png')
            page=token_page(board,('很硬的甲','蓄能帆','火力风暴潮','高周波电锯')) if case=='unwanted' else token_page(board)
            applied(session,choice,page)
            if case=='missing':page.tokens=[t for t in page.tokens if normalize(t.text)!='反重力皮靴']
            elif case=='changed':page=token_page(board,('高周波电锯','反重力皮靴','光速螺旋桨','很硬的甲'))
            with self.subTest(case=case),self.assertRaises(AutomationError):active_action(page,session)
            self.assertEqual(len(session['actions']),1);self.assertFalse(action['consumable_verified'])

    def test_corrupt_bank_roster_counter_or_profile_source_cannot_settle_the_tool(self):
        board,session=fixture('projector',1);after,units=result(board,session,'projector')
        with tempfile.TemporaryDirectory() as folder:
            c,saved=run_case(folder,board,session,after,units,'projector')
            for mutation in ('counter','stock','roster','source','end','star','target','extra_gear','traits','zones'):
                wrong=deepcopy(saved['actions']);action=wrong[0]
                if mutation=='counter':action['target'][6]=0
                elif mutation=='stock':action['consumable_effect']['stock_after']['projector']=1
                elif mutation=='roster':action['consumable_effect']['roster_after'][0]['tier']=5
                elif mutation=='source':action['consumable_effect']['profile_proofs'][0]['inspection_action_id']=0
                elif mutation=='end':action['consumable_effect']['verification_action_id']=0
                elif mutation=='star':next(u for u in action['consumable_effect']['roster_after'] if u['zone']=='bench')['star']=2
                elif mutation=='target':
                    action['target'][9]=4;action['consumable_origin']['target'][9]=4
                else:
                    copied=next(u for u in action['consumable_effect']['roster_after'] if u['zone']=='bench')
                    if mutation=='extra_gear':copied['equipment']=['boots']
                    elif mutation=='traits':copied['traits']=['changed']
                    else:copied['eligible_zones']=['front','back']
                with self.subTest(mutation=mutation):self.assertEqual(ledger_status(wrong),'unknown')


if __name__=='__main__':unittest.main()
