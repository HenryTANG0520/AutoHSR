"""Supply quotas, complete columns, one input, candidate custody and delivery."""
from copy import deepcopy
from itertools import count
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import cv2

from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_rewards import active_action,_options
from autohsr.currency_wars_standard_supply_refresh import (ACTION,COUNTER,EXPECTED,MAX_REFRESHES,
    bind_choice,bind_intent,feedback,icon_ready,icon_template,refreshed,remaining,supplement_remaining,
    table,valid_receipt,valid_claim_chain)
from autohsr.currency_wars_supply_fields import CENTERS,rows,supplement_supply_fields
from autohsr.currency_wars_supply_policy import groups,preferred
from autohsr.models import AutomationError,InputInterrupted,Scene,Stopped,Token,normalize
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_trading as trading


UNWANTED=(('员工甲','光能电池'),('员工乙','量产型装甲'),('员工丙','以太钻头'),('员工丁','和平手枪'),('员工戊','生命之花'))


def quota(scene,value=2,score=.99):
    scene.tokens=[t for t in scene.tokens if not t.within(COUNTER)]
    if value is not None:scene.tokens.append(Token('剩余次数：'+str(value),score,(.700,.895,.775,.93)))


def options(scene,specs):
    result=Scene(list(scene.tokens),scene.image.copy(),field_reads=dict(scene.field_reads))
    result.tokens=[t for t in result.tokens if not t.within((.03,.50,.97,.55)) and not t.within((.03,.61,.97,.67))]
    for x,(name,item) in zip(CENTERS[len(specs)],specs):
        if name is not None:result.tokens.append(Token(name,.99,(x-.04,.505,x+.04,.54)))
        result.tokens.append(Token(item,.99,(x-.05,.62,x+.05,.66)))
    return result


def fixture(size=5,strategy='aglaea',count_left=2):
    before,page,session=rewards.supply_fixture(size,strategy)
    page=options(page,UNWANTED[:size]);quota(page,count_left)
    ref=icon_template();page.image[1276:1276+ref.shape[0],1718:1718+ref.shape[1]]=ref
    return before,page,session


def pending(session,page):
    choice=active_action(page,session)
    assert choice.intent==ACTION
    action=dict(id=len(session['actions']),action=ACTION,expected=EXPECTED,status='pending',input_epoch=0,
                target=list(choice.payload),before='refresh-before.png')
    session['actions'].append(action);bind_intent(session,choice,page)
    return choice


def record(session,page,after):
    choice=pending(session,page)
    assert feedback(choice,page,after,session)
    session['actions'][-1].update(status='verified',after='refresh-after.png')
    refreshed(session,choice,after)
    return choice


def complete_case(size,strategy,folder):
    before,page,session=fixture(size,strategy)
    middle=options(page,tuple(('中间'+name,item) for name,item in UNWANTED[:size]));quota(middle,1)
    target='阿格莱雅' if strategy=='aglaea' else '希儿'
    item='反重力皮靴' if strategy=='aglaea' else '光能电池'
    final=options(middle,((target,item),)+UNWANTED[1:size]);quota(final,0)
    preview=deepcopy(session);record(preview,page,middle);record(preview,middle,final)
    select,highlight=rewards.selected(final,preview)
    action=dict(id=len(preview['actions']),action=select.intent,expected=select.expected,status='pending',input_epoch=0,
        target=list(select.payload),before='selection-before.png')
    preview['actions'].append(action);bind_choice(preview,select,final)
    action.update(status='verified',after='selected.png');claim=active_action(highlight,preview)
    after=rewards.supply_board(before,claim)
    units=deepcopy(session['collection']['units'])
    for record_ in units.values():record_['unit']['equipment']=()
    units['bench:6']=dict(unit=dict(name=target,zone='bench',slot=6,star=1,tier=4,
        traits=('测试',),equipment=(),eligible_zones=('front','back')))
    frames=[page,middle,middle,final,final,highlight,highlight,after,after]
    for cell in sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
        frames.extend((rewards.node(equipment.panel(units[cell.zone+':'+str(cell.slot)]['unit'],()),'1-3'),after))
    c=exchange.StandardExchangeTests().context(folder,before,session,frames)
    def done():
        store=getattr(c,'currency_standard_session',None)
        if store and store.data.get('reward',{}).get('status')=='verified':raise Stopped('supply delivered')
    c.checkpoint=done
    with patch('autohsr.currency_wars_replay.save_sample'):
        try:run_standard(c)
        except Stopped:pass
        else:raise AssertionError(str(c.currency_standard_session.data.get('reason')))
    return c,StandardSession(c.currency_standard_session.path).data


class SupplyRefreshTests(unittest.TestCase):
    def test_independent_remaining_counter_accepts_whole_and_split_fields(self):
        _,page,_=fixture()
        for value in (0,1,2,3,12,99):
            quota(page,value);self.assertEqual(remaining(page)[0],value)
        quota(page,None)
        page.tokens.extend((Token('剩余次数：',.99,(.700,.895,.75,.93)),Token('3',.99,(.755,.895,.775,.93))))
        self.assertEqual(remaining(page)[0],3)
        for value in ('-1','100','1/2'):
            quota(page,value)
            with self.subTest(value=value),self.assertRaises(AutomationError):remaining(page)
        quota(page,1,.5)
        with self.assertRaises(AutomationError):remaining(page)
        quota(page,1);page.tokens.append(Token('2',.99,(.755,.895,.775,.93)))
        with self.assertRaises(AutomationError):remaining(page)

    def test_local_counter_readings_must_agree_and_never_hide_global_conflicts(self):
        _,page,_=fixture();quota(page,None)
        for texts,accepted in ((('剩余次数2','剩余次数2'),True),(('剩余次数1','剩余次数2'),False),(('剩余次数2',None),False)):
            reader=SimpleNamespace(read=Mock(side_effect=[Scene([Token(t,.99,(0,0,1,1))] if t else []) for t in texts]))
            refined=supplement_remaining(page,reader)
            if accepted:self.assertEqual(remaining(refined)[0],2)
            else:
                with self.assertRaises(AutomationError):remaining(refined)
        quota(page,'-1')
        reader=SimpleNamespace(read=Mock(return_value=Scene([Token('剩余次数2',.99,(0,0,1,1))])))
        with self.assertRaises(AutomationError):remaining(supplement_remaining(page,reader))
        quota(page,None)
        page.field_reads={k:(Token('剩余次数2',.99,(.1,.1,.2,.2)),) for k in ('currency_supply_refresh_raw','currency_supply_refresh_binary')}
        with self.assertRaises(AutomationError):remaining(page)

    def test_four_and_five_complete_layouts_do_not_convert_missing_columns(self):
        for size in (4,5):
            _,page,_=fixture(size);self.assertEqual(len(rows(page)),size)
        _,page,_=fixture(5)
        page.tokens=[t for t in page.tokens if not t.within((.04,.50,.22,.55))]
        known=_options(page,'supply_selection',.65)
        self.assertEqual(len(known),5);self.assertTrue(known[0][1].startswith('unknown:'));self.assertIsNone(known[0][3])
        page.tokens=[t for t in page.tokens if not t.within((.04,.61,.22,.67))]
        with self.assertRaises(AutomationError):rows(page)

    def test_unreadable_unselected_role_keeps_its_image_identity_and_cannot_be_chosen(self):
        _,page,session=fixture(count_left=0)
        page=options(page,((None,'反重力皮靴'),('可读员工','轮滑鞋'))+UNWANTED[2:])
        old=table(page);self.assertTrue(old[0]['name'].startswith('unknown:'))
        choice=active_action(page,session)
        self.assertEqual((choice.payload[3],choice.payload[6]),(1,'可读员工'))
        x=CENTERS[5][0];_crop(page.image,(x-.09,.50,x+.09,.55))[:]=7
        self.assertNotEqual(old[0]['name'],table(page)[0]['name'])

    def test_missing_role_requires_both_local_sources_to_become_known(self):
        _,page,_=fixture()
        page.tokens=[t for t in page.tokens if not t.within((.04,.50,.22,.55))]
        for names,known in ((('藿藿','藿藿'),True),(('藿藿','霍霍'),False),(('藿藿',None),False)):
            reader=SimpleNamespace(read=Mock(side_effect=[Scene([Token(t,.99,(.1,.1,.5,.8))] if t else []) for t in names]))
            result=supplement_supply_fields(page,reader)
            name=rows(result)[0][1].text
            self.assertEqual(name=='藿藿',known)
            self.assertEqual(name.startswith('unknown:'),not known)

    def test_strategy_prefers_aglaea_speed_before_core_and_seele_missing_recipe_part(self):
        _,page,session=fixture()
        page=options(page,(('阿格莱雅','量产型装甲'),('忘归人','反重力皮靴'))+UNWANTED[2:])
        choice=active_action(page,session)
        self.assertEqual((choice.intent,choice.payload[5],choice.payload[6]),('select_standard_supply','boots','忘归人'))
        _,page,session=fixture(strategy='seele')
        data=deepcopy(session['reward']);data['basis']['inventory']['shoe']=1
        candidates=_options(options(page,(('希儿','光能电池'),('忘归人','折叠小刀'))+UNWANTED[2:]),'supply_selection',.65)
        self.assertEqual(groups(data,'seele')[0],('item',('knife',)))
        self.assertEqual(preferred(candidates,data,'seele')[3],'忘归人')

    def test_current_counter_and_visible_control_are_required_only_for_a_needed_refresh(self):
        _,page,session=fixture()
        self.assertEqual(next_action(page,session=session).intent,ACTION)
        page.image[1260:1365,1680:1810]=0
        with self.assertRaises(AutomationError):active_action(page,session)
        quota(page,0);self.assertEqual(active_action(page,session).intent,'select_standard_supply')
        session['strategy']='default';quota(page,None)
        self.assertEqual(active_action(page,session).intent,'select_standard_supply')
        _,page,session=fixture()
        session['reward']['basis']['inventory']=None;session['actions'][0]['reward_basis']['inventory']=None
        with self.assertRaises(AutomationError):active_action(page,session)

    def test_refresh_control_and_count_support_resized_frames(self):
        _,page,_=fixture()
        for width,height in ((2560,1440),(1920,1080),(1280,720)):
            scaled=Scene(list(page.tokens),cv2.resize(page.image,(width,height)))
            with self.subTest(width=width):self.assertTrue(icon_ready(scaled));self.assertEqual(remaining(scaled)[0],2)
        page.image[1276:1347,1718:1790]//=2
        self.assertFalse(icon_ready(page))

    def test_same_candidates_with_one_spent_quota_are_recorded_without_replaying_the_click(self):
        before,page,session=fixture(count_left=1);after=deepcopy(page);quota(after,0)
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,[page,after,after])
            def done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data['actions'][-1]['action']==ACTION and store.data['actions'][-1]['status']=='verified':raise Stopped('quota verified')
            c.checkpoint=done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertFalse(saved['actions'][-1]['supply_refresh_receipt']['candidates_changed'])
            self.assertEqual(saved['reward']['status'],'awaiting');self.assertEqual(ledger_status(saved['actions']),'clear')
            c.window.click.assert_called_once();self.assertFalse(saved['completion_verified'])

    def test_formal_context_refreshes_twice_selects_confirms_and_verifies_actual_delivery(self):
        for size,strategy in ((4,'aglaea'),(5,'seele')):
            with self.subTest(size=size,strategy=strategy),tempfile.TemporaryDirectory() as folder:
                c,saved=complete_case(size,strategy,folder)
                actions=saved['actions'];claims=[a for a in actions if a['action']=='confirm_standard_supply']
                self.assertEqual(sum(a['action']==ACTION for a in actions),2);self.assertEqual(len(claims),1)
                self.assertEqual(saved['reward']['supply_refresh_ids'],[2,3]);self.assertTrue(claims[0]['reward_verified'])
                self.assertTrue(claims[0]['reward_effect']['unit_verified']);self.assertTrue(valid_claim_chain(claims[0],actions))
                self.assertEqual(ledger_status(actions),'clear');self.assertFalse(saved['completion_verified']);c.window.drag.assert_not_called()
                for mutation in ('quota','basis','table','hud','chain','binding','selected_table','foreign'):
                    wrong=deepcopy(actions);first=wrong[2];claim=wrong[claims[0]['id']]
                    if mutation=='quota':first['supply_refresh_receipt']['remaining_after']=2
                    elif mutation=='basis':first['supply_refresh_origin']['basis']['inventory']['boots']=1
                    elif mutation=='table':first['supply_refresh_receipt']['candidates_after'][0]['item_name']='未知装备'
                    elif mutation=='hud':first['supply_refresh_receipt']['hud_after']['gold']=24
                    elif mutation=='chain':wrong[3]['supply_refresh_receipt']['remaining_before']=2
                    elif mutation=='binding':claim['supply_refresh_binding']['refresh_action_id']=2
                    elif mutation=='selected_table':wrong[claim['id']-1].pop('supply_refresh_binding')
                    else:first['target'][1]=0
                    with self.subTest(mutation=mutation):self.assertEqual(ledger_status(wrong),'unknown')

    def test_extra_resource_changes_missing_images_and_bad_quota_cannot_settle_a_refresh(self):
        _,page,session=fixture();choice=pending(session,page)
        hidden=deepcopy(page);quota(hidden,1);trading.hud(hidden,gold=24)
        # The modal covers this HUD field. Its OCR must remain unknown rather
        # than becoming a fabricated balance or a zero-cost gold receipt.
        self.assertIsNone(session['actions'][-1]['supply_refresh_origin']['before_hud']['gold'])
        self.assertTrue(feedback(choice,page,hidden,session));self.assertEqual(session['reward']['basis']['gold'],25)
        for mutation in ('unchanged','twice','hp','xp','layout','image'):
            after=deepcopy(page);quota(after,1)
            if mutation=='unchanged':quota(after,2)
            elif mutation=='twice':quota(after,0)
            elif mutation in ('hp','xp'):
                trading.hud(after,xp=(1,6) if mutation=='xp' else (0,6))
                if mutation=='hp':
                    after.tokens=[t for t in after.tokens if not t.within((.735,.05,.78,.095))]
                    after.tokens.append(Token('99',.99,(.735,.05,.78,.095)))
            elif mutation=='layout':after.tokens=[t for t in after.tokens if not t.within((.04,.61,.22,.67))]
            else:after.image=None
            with self.subTest(mutation=mutation):self.assertFalse(feedback(choice,page,after,session))

    def test_candidate_and_unknown_role_changes_after_verified_refresh_cannot_authorize_selection(self):
        _,page,session=fixture(count_left=1)
        final=options(page,((None,'量产型装甲'),('阿格莱雅','反重力皮靴'))+UNWANTED[2:]);quota(final,0)
        record(session,page,final)
        final.image[720:792,102:563]=13
        with self.assertRaises(AutomationError):active_action(final,session)

    def test_per_arrival_cap_and_receipt_chain_cannot_be_bypassed_by_a_sixth_record(self):
        _,page,session=fixture(count_left=99)
        for left in range(98,98-MAX_REFRESHES,-1):
            after=deepcopy(page);quota(after,left);record(session,page,after);page=after
        self.assertEqual(active_action(page,session).intent,'select_standard_supply')
        extra=deepcopy(session['actions'][-1]);extra['id']=len(session['actions'])
        extra['target'][2]-=1;extra['supply_refresh_receipt']['remaining_before']-=1;extra['supply_refresh_receipt']['remaining_after']-=1
        session['actions'].append(extra)
        self.assertTrue(valid_receipt(extra,session['actions']));self.assertEqual(ledger_status(session['actions']),'unknown')

    def test_unknown_feedback_is_durable_and_cannot_replay_the_refresh(self):
        before,page,session=fixture()
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,[page,page,page])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown');c.window.click.assert_called_once()
            with self.assertRaises(AutomationError):run_standard(c)
            c.window.click.assert_called_once()

    def test_write_pause_and_account_changes_never_replay_the_refresh(self):
        for case in ('write_before','write_after','pause','account'):
            before,page,session=fixture();after=deepcopy(page);quota(after,1)
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,before,session,[page,after,after])
                submit=c.currency_standard_input.side_effect
                def apply(scene,choice):
                    if case=='pause':raise InputInterrupted('pause before refresh')
                    return submit(scene,choice)
                c.currency_standard_input.side_effect=apply;take=c.snapshot
                def snapshot():
                    current=take()
                    if case=='account' and current is after:current.tokens=[Token('UID:200000000',t.score,t.box) if t.text.startswith('UID:') else t for t in current.tokens]
                    return current
                c.snapshot=snapshot;original=StandardSession.persist
                def persist(store):
                    if store.data['actions'][-1]['action']==ACTION and (case=='write_before' or case=='write_after' and store.data['actions'][-1]['status']=='verified'):
                        raise OSError('refresh journal write failed')
                    return original(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',persist),self.assertRaises((AutomationError,OSError)):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                if case=='write_before':self.assertEqual(len(saved['actions']),2)
                else:
                    self.assertEqual(saved['actions'][-1]['status'],'pending')
                    with self.assertRaises(AutomationError):run_standard(c)
                self.assertEqual(c.window.click.call_count,1 if case in ('write_after','account') else 0)


if __name__=='__main__':unittest.main()
