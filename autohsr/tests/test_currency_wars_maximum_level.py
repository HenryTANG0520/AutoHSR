"""Maximum-level preparation has no experience bar; absence needs a cap label."""
from copy import deepcopy
from itertools import chain,count
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.currency_wars_standard_hud import experience_observed
from autohsr.currency_wars_standard_ledger import ledger_status,valid_receipt
from autohsr.currency_wars_standard_sale import proposal as sale_proposal,active_action as sale_action,panel_feedback
from autohsr.currency_wars_standard_trading import experience_action,financial_feedback
from autohsr.currency_wars_standard_equipment import proposal as equip_proposal,inspectable,bind_intent,begin_verification,active_action as equip_action
from autohsr.models import AutomationError,Scene,Stopped,Token,normalize
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_standard_sale as sale
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange


def maximum(scene,*,level=10,marker=True):
    scene.tokens=[t for t in scene.tokens if not t.within((.13,.865,.18,.90)) and normalize(t.text) not in ('满级','已满级')]
    trading.hud(scene,level=level)
    if marker:scene.tokens.append(Token('已满级',.99,(.13,.78,.18,.81)))
    return scene


def board_fixture(*,selling=False,items=()):
    board,session=trading.full_board_fixture(gold=25 if selling else 0,level=10)
    maximum(board)
    units=session['collection']['units']
    candidate=units['bench:4']
    for i in (4,5):units.pop('bench:'+str(i));_crop(board.image,bench_face(i))[:]=0
    for record in units.values():
        unit=record['unit'];unit.update(star=3,tier=5,traits=('测试',),equipment=(),eligible_zones=(unit['zone'],))
    units['front:2']['unit']['name']='阿格莱雅'
    if selling:
        patch=_crop(board.image,bench_face(4));patch[:]=75;patch[::2]=180
        candidate['unit'].update(name='待售角色',zone='bench',slot=4,star=1,tier=1,traits=('测试',),equipment=(),eligible_zones=('back',))
        candidate['signature']=next(c.signature for c in roster_cells(board) if (c.zone,c.slot)==('bench',4))
        units['bench:4']=candidate
    for i,name in enumerate(items):equipment.place(board.image,name,(2460,(330,430,535)[i]))
    session.update(strategy='aglaea',shop_observed_nodes=['1-1'])
    return board,session


def pending_equipment(board,session):
    choice=equip_proposal(board,session)
    session['actions'].append(dict(id=0,action=choice.intent,status='pending',input_epoch=0,target=list(choice.payload),
                                  expected=choice.expected,before='before.png'))
    bind_intent(session,choice,board)
    session['actions'][0].update(status='verified',after='after.png')
    after=equipment.consumed(board,choice.payload[5])
    begin_verification(session,choice,board,after)
    return choice,after


def maximum_panel(unit,gear):
    return trading.hud(maximum(equipment.panel(unit,gear)),deployment=(10,10))


def sale_panel(board,session,refund=2):
    detail=sale.character(board,session,refund=refund)
    native=equipment.panel(session['collection']['units']['bench:4']['unit'])
    detail.image[1040:1130,2140:2480]=native.image[1040:1130,2140:2480]
    return detail


class MaximumLevelTests(unittest.TestCase):
    def test_maximum_needs_level_ten_a_current_label_and_no_conflicting_bar(self):
        board,_=board_fixture()
        self.assertTrue(experience_observed(board,read_match(board)))
        for mutation in ('missing','low','outside','bar','conflict','level9','level11'):
            current=Scene(list(board.tokens),board.image.copy())
            if mutation=='missing':current.tokens=[t for t in current.tokens if normalize(t.text)!='已满级']
            elif mutation=='low':current.tokens=[Token(t.text,.4,t.box) if normalize(t.text)=='已满级' else t for t in current.tokens]
            elif mutation=='outside':current.tokens=[Token(t.text,t.score,(.5,.78,.6,.81)) if normalize(t.text)=='已满级' else t for t in current.tokens]
            elif mutation in ('bar','conflict'):
                trading.hud(current,xp=(0,20))
                if mutation=='conflict':current.tokens.append(Token('2/20',.99,(.13,.865,.18,.9)))
            else:trading.hud(current,level=9 if mutation=='level9' else 11)
            with self.subTest(mutation=mutation):self.assertFalse(experience_observed(current,read_match(current)))
        for level in (1,5,9):
            current=maximum(Scene(list(board.tokens),board.image.copy()),level=level,marker=False)
            self.assertFalse(experience_observed(current,read_match(current)))
            trading.hud(current,xp=(0,20));self.assertTrue(experience_observed(current,read_match(current)))

    def test_full_native_preparation_reaches_start_without_purchasing_experience(self):
        board,session=board_fixture()
        self.assertIsNone(experience_action(board,session))
        self.assertIsNone(sale_proposal(board,session));self.assertIsNone(equip_proposal(board,session))
        self.assertEqual(next_action(board,session=session).intent,'start_standard_node')
        current=maximum(Scene(list(board.tokens),board.image.copy()),marker=False)
        with self.assertRaises(AutomationError):next_action(current,session=session)

    def test_formal_maximum_sale_keeps_null_experience_and_positive_refund_receipt(self):
        board,session=board_fixture(selling=True)
        choice=sale_proposal(board,session);detail=sale_panel(board,session,refund=6)
        after=sale.sold(board,choice.__class__('sell_standard_owned','standard_owned_sold',None,payload=choice.payload+(6,0)))
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,[board,detail,detail,after,after])
            def done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data.get('sale',{}).get('status')=='verified':raise Stopped('sold')
            c.checkpoint=done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            receipt=saved['actions'][-1]['receipt']
            self.assertEqual(receipt['gold_after'],31);self.assertTrue(receipt['max_level_verified'])
            self.assertIsNone(receipt['experience_before']);self.assertIsNone(receipt['experience_after'])
            self.assertIsNone(saved['sale']['snapshot']['experience']);self.assertTrue(valid_receipt(saved['actions'][-1]))
            self.assertEqual(c.window.click.call_count,2);self.assertEqual(ledger_status(saved['actions']),'clear')
            self.assertFalse(saved['completion_verified'])

    def test_maximum_sale_view_and_return_need_the_label_and_unchanged_level(self):
        board,session=board_fixture(selling=True);choice=sale.inspected(board,session)
        detail=sale_panel(board,session);claim=sale_action(detail,session);after=sale.sold(board,claim)
        self.assertTrue(panel_feedback(choice,board,detail))
        self.assertIsNotNone(financial_feedback(claim,detail,after,session=session))
        for mutation in ('missing','bar','level'):
            bad=Scene(list(detail.tokens),detail.image.copy())
            if mutation=='missing':maximum(bad,marker=False)
            elif mutation=='bar':trading.hud(bad,xp=(0,20))
            else:trading.hud(bad,level=9)
            with self.subTest(mutation=mutation):
                self.assertFalse(panel_feedback(choice,board,bad))
                with self.assertRaises(AutomationError):sale_action(bad,session)
            returned=Scene(list(after.tokens),after.image.copy());maximum(returned,marker=False)
            self.assertIsNone(financial_feedback(claim,detail,returned,session=session))

    def test_maximum_refund_receipt_requires_the_cap_proof_and_null_fields(self):
        board,session=board_fixture(selling=True);sale.inspected(board,session)
        detail=sale_panel(board,session);choice=sale_action(detail,session);after=sale.sold(board,choice)
        receipt=financial_feedback(choice,detail,after,session=session)
        action=dict(action=choice.intent,status='verified',target=list(choice.payload),receipt=receipt,before='before.png',after='after.png')
        self.assertTrue(valid_receipt(action))
        for field,value in (('max_level_verified',False),('experience_before',[]),('experience_after',[0,20])):
            wrong=deepcopy(action);wrong['receipt'][field]=value
            with self.subTest(field=field):self.assertFalse(valid_receipt(wrong))
        wrong=deepcopy(action);wrong['receipt'].pop('experience_before');self.assertFalse(valid_receipt(wrong))
        wrong=deepcopy(action);wrong['target'][3]=9;wrong['receipt']['level_after']=9
        self.assertFalse(valid_receipt(wrong))

    def test_formal_maximum_equipment_direct_and_recipe_preserve_null_lock(self):
        for items,expected in ((('boots',),['boots']),(('shoe','shoe'),['boots'])):
            board,session=board_fixture(items=items)
            if len(items)==2:
                session['collection']['units']['front:2']['equipment_recipes']=[dict(product='boots',components=['shoe','shoe'])]
            role=session['collection']['units']['front:2']['unit']
            first=equipment.consumed(board,6)
            states=[board,first,first,maximum_panel(role,('boots',) if len(items)==1 else ('shoe',)),first]
            if len(items)==2:
                second=equipment.consumed(first,7)
                states.extend((second,second,maximum_panel(role,('boots',)),second))
            with self.subTest(items=items),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,board,session,states)
                def done():
                    store=getattr(c,'currency_standard_session',None)
                    if store and len(store.data.get('equipment_history',[]))==len(items):raise Stopped('equipped')
                c.checkpoint=done
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                for action in saved['actions']:
                    if action['action']=='stage_standard_equipment':
                        self.assertIsNone(action['equipment_expected']['board'][5]);self.assertTrue(action['equipment_expected']['max_level_verified'])
                        self.assertTrue(action['equipment_verified'])
                self.assertEqual(saved['collection']['units']['front:2']['unit']['equipment'],expected)
                self.assertEqual(c.window.drag.call_count,len(items));self.assertEqual(ledger_status(saved['actions']),'clear')
                self.assertFalse(any(a['action']=='buy_standard_experience' for a in saved['actions']))

    def test_maximum_equipment_before_and_after_need_current_cap_evidence(self):
        board,session=board_fixture(items=('boots',));choice=equip_proposal(board,session)
        after=equipment.consumed(board,choice.payload[5]);self.assertTrue(inspectable(choice,board,after))
        for mutation in ('missing','bar','level'):
            bad=Scene(list(after.tokens),after.image.copy())
            if mutation=='missing':maximum(bad,marker=False)
            elif mutation=='bar':trading.hud(bad,xp=(0,20))
            else:trading.hud(bad,level=9)
            with self.subTest(mutation=mutation):self.assertFalse(inspectable(choice,board,bad))
        no_label=maximum(Scene(list(board.tokens),board.image.copy()),marker=False)
        with self.assertRaises(AutomationError):equip_proposal(no_label,session)
        with self.assertRaises(AutomationError):sale_proposal(no_label,session)

    def test_equipment_maximum_lock_cannot_turn_null_into_zero_or_drop_cap_proof(self):
        board,session=board_fixture(items=('boots',));choice,after=pending_equipment(board,session)
        self.assertEqual(equip_action(after,session).intent,'inspect_standard_equipment_unit')
        for mutation in ('null','flag','label'):
            current=deepcopy(session);view=Scene(list(after.tokens),after.image.copy())
            if mutation=='null':current['equipment']['expected']['board'][5]=[]
            elif mutation=='flag':current['equipment']['expected'].pop('max_level_verified')
            else:maximum(view,marker=False)
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):equip_action(view,current)

    def test_normal_level_missing_bar_never_uses_the_maximum_exception(self):
        for level in (1,5,9):
            board,session=board_fixture(items=('boots',))
            maximum(board,level=level,marker=False)
            with self.subTest(level=level):
                with self.assertRaises(AutomationError):equip_proposal(board,session)
                with self.assertRaises(AutomationError):sale_proposal(board,session)

    def test_cap_lost_after_consumption_is_durable_unknown_and_never_replayed(self):
        for kind in ('sale','equipment'):
            board,session=board_fixture(selling=kind=='sale',items=('boots',) if kind=='equipment' else ())
            if kind=='sale':
                original=sale_proposal(board,session)
                claim=original.__class__('sell_standard_owned','standard_owned_sold',None,payload=original.payload+(2,0))
                detail=sale_panel(board,session)
                after=maximum(sale.sold(board,claim),marker=False)
                states=[board,detail,detail,after,after]
            else:
                after=maximum(equipment.consumed(board,6),marker=False)
                states=[board,after,after]
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,board,session,states)
                timer=SimpleNamespace(monotonic=Mock(side_effect=chain((0,.1,.2,.3),count(31,31))))
                with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',timer):
                    self.assertEqual(run_standard(c).status,'partial')
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['actions'][-1]['status'],'unknown')
                self.assertEqual(saved['actions'][-1]['action'],'sell_standard_owned' if kind=='sale' else 'stage_standard_equipment')
                calls=(c.window.click.call_count,c.window.drag.call_count)
                self.assertEqual(calls,(2,0) if kind=='sale' else (0,1))
                with self.assertRaises(AutomationError):run_standard(c)
                self.assertEqual((c.window.click.call_count,c.window.drag.call_count),calls)


if __name__=='__main__':unittest.main()
