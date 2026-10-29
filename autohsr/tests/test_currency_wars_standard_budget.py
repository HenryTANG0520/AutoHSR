"""Full-match technical bounds are separate from game-resource authority."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_session import StandardSession,MAX_ACTIONS,read_session
from autohsr.currency_wars_standard_budget import StandardBudget,PHASE_ACTIONS
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.models import AutomationError,Stopped
from autohsr.tests import test_currency_wars_standard_flow as flow
from autohsr.tests import test_currency_wars_standard_progress as progress
from autohsr.tests.test_currency_wars_node import screen


def action(data,name='inspect_standard_unit',**extra):
    item=dict(id=len(data['actions']),action=name,status='verified',input_epoch=0,before='before.png',after='after.png')
    item.update(extra);data['actions'].append(item)
    return item


def continued(data,node='1-1',kind='preparation'):
    start=action(data,'start_standard_node',expected='standard_node_entered',target=[node,20,100,3])
    plane,number=map(int,node.split('-'));after=f'{plane+1}-1' if kind=='plane_map' else f'{plane}-{number+1}'
    end=action(data,'continue_standard_node',expected='standard_node_advanced',target=[node,start['id']],feedback=dict(page_kind=kind,node=after))
    data.setdefault('node_history',[]).append(dict(node=node,start_action_id=start['id'],continue_action_id=end['id'],status='advanced',node_verified=True,result='victory.png'))
    return start,end


class StandardBudgetTests(unittest.TestCase):
    def test_verified_forward_progress_can_cross_the_old_whole_run_limit(self):
        data=dict(actions=[]);budget=StandardBudget(data)
        for node in ('1-1','1-2','1-3'):
            for _ in range(300):action(data)
            self.assertIsNone(budget.check(data))
            continued(data,node)
            self.assertIsNone(budget.check(data));self.assertEqual(data['execution_window']['phase_actions'],0)
        self.assertGreater(len(data['actions']),512);self.assertEqual(data['execution_window']['phase_node'],'1-4')

    def test_current_phase_stops_at_512_and_ocr_or_same_node_gifts_do_not_reset_it(self):
        data=dict(actions=[]);budget=StandardBudget(data)
        for _ in range(PHASE_ACTIONS-1):action(data)
        self.assertIsNone(budget.check(data))
        action(data,'choose_standard_reward',reward_verified=True,reward_effect=dict(node='1-1',node_after='1-1'))
        data.update(observed_node='2-1',page_kind='preparation',action_status='transition_verified')
        self.assertIn('512',budget.check(data));self.assertEqual(data['execution_window']['phase_start'],0)
        self.assertFalse(data.get('completion_verified',False))

    def test_only_a_complete_continue_receipt_can_change_the_phase(self):
        for kind in ('preparation','shop','supply_selection','plane_map'):
            data=dict(actions=[]);budget=StandardBudget(data);continued(data,kind=kind)
            self.assertIsNone(budget.check(data));self.assertEqual(data['execution_window']['phase_start'],2)
        baseline=dict(actions=[]);continued(baseline)
        for change in ('start','end','status','result','observed','node','destination','expected','plane','target','source','epoch'):
            data=deepcopy(baseline);budget=StandardBudget(dict(actions=[]))
            entry=data['node_history'][-1]
            if change=='start':entry['start_action_id']=True
            elif change=='end':entry['continue_action_id']=False
            elif change=='status':data['actions'][1]['status']='unknown'
            elif change=='result':entry['result']=''
            elif change=='observed':entry['node_verified']=False
            elif change=='node':entry['node']='2-2'
            elif change=='destination':data['actions'][1]['feedback']['node']='1-4'
            elif change=='expected':data['actions'][0]['expected']='character'
            elif change=='target':data['actions'][1]['target'][1]=False
            elif change=='source':data['actions'][0]['after']=True
            elif change=='epoch':data['actions'][1]['input_epoch']=False
            else:data['actions'][1]['feedback']['page_kind']='unknown'
            with self.subTest(change=change),self.assertRaises(AutomationError):budget.check(data)

    def test_unknown_reward_delivery_cannot_renew_a_phase(self):
        data=dict(actions=[]);budget=StandardBudget(data)
        action(data,'confirm_standard_supply',reward_verified=False,reward_effect=dict(node='1-2',node_after='1-3'))
        self.assertEqual(budget.window(data)['phase_start'],0)
        data['actions'][0]['reward_verified']=True
        with self.assertRaises(AutomationError):budget.check(data)

    def test_supply_phase_changes_only_after_formal_delivery_and_actual_unit_readback(self):
        from autohsr.currency_wars_collector import roster_cells
        from autohsr.tests import test_currency_wars_standard_rewards as rewards
        from autohsr.tests import test_currency_wars_standard_equipment as equipment
        from autohsr.tests import test_currency_wars_standard_trading as trading
        for count_options in (4,5):
            before,page,session=rewards.supply_fixture(count_options);budget=StandardBudget(session)
            choice,highlight=rewards.selected(page,session);after=rewards.supply_board(before,choice)
            units=deepcopy(session['collection']['units'])
            units['bench:6']=dict(unit=dict(name=choice.payload[6],zone='bench',slot=6,star=1,tier=1,
                traits=('测试',),equipment=(),eligible_zones=('front','back')))
            states=[page,highlight,highlight,after,after]
            for cell in sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
                detail=equipment.panel(units[cell.zone+':'+str(cell.slot)]['unit'])
                rewards.node(detail,'1-3');states += [detail,after]
            with self.subTest(cards=count_options),tempfile.TemporaryDirectory() as folder:
                c=trading.StandardTradingTests().context(folder,before,session,states);pending=[]
                def checkpoint():
                    store=getattr(c,'currency_standard_session',None)
                    if not store:return
                    if store.data.get('reward',{}).get('status')=='unit_verifying':pending.append(budget.window(store.data))
                    if store.data.get('reward',{}).get('status')=='verified':raise Stopped('supply readback completed')
                c.checkpoint=checkpoint
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                data=c.currency_standard_session.data;window=budget.window(data)
                claim=next(a for a in data['actions'] if a['action']=='confirm_standard_supply')
                self.assertTrue(pending);self.assertTrue(all(w['phase_start']==2 for w in pending))
                self.assertEqual(window['phase_start'],claim['id']+1);self.assertEqual(window['phase_node'],'1-3')
                self.assertEqual(window['boundary_kind'],'verified_supply_delivery')
                for bad in ('jump','unit','inventory'):
                    changed=deepcopy(data);effect=changed['actions'][claim['id']]['reward_effect']
                    if bad=='jump':effect['node_after']='1-4'
                    elif bad=='unit':effect['unit_verified']=False
                    else:effect['inventory_checked']=False
                    with self.assertRaises(AutomationError):budget.check(changed)

    def test_explicit_new_invocation_does_not_erase_the_match_action_bound(self):
        data=dict(actions=[])
        for _ in range(600):action(data)
        budget=StandardBudget(data);self.assertEqual(budget.window(data)['phase_actions'],0)
        for _ in range(MAX_ACTIONS-600):action(data)
        self.assertIn('4096',budget.check(data));self.assertEqual(len(data['actions']),MAX_ACTIONS)
        self.assertIn('4096',StandardBudget(data).check(data))

    def test_shortening_or_corrupting_the_progress_record_never_refreshes_limits(self):
        data=dict(actions=[]);action(data);budget=StandardBudget(data);data['actions'].clear()
        with self.assertRaises(AutomationError):budget.check(data)
        for bad in (None,{},'1-2'):
            with self.subTest(history=bad),self.assertRaises(AutomationError):StandardBudget(dict(actions=[])).check(dict(actions=[],node_history=bad))

    def test_native_flow_stops_before_dispatch_when_the_total_journal_is_full(self):
        with tempfile.TemporaryDirectory() as folder:
            store=progress.StandardProgressTests().store(folder)
            for _ in range(MAX_ACTIONS-len(store.data['actions'])):action(store.data)
            store.persist();c=flow.StandardFlowTests().context(folder,[progress.current('node_result')],resume=True)
            with patch('autohsr.currency_wars_replay.save_sample'):result=run_standard(c)
            self.assertEqual(result.status,'partial');c.currency_standard_input.assert_not_called()
            self.assertEqual(len(c.currency_standard_session.data['actions']),MAX_ACTIONS)
            self.assertEqual(c.report.currency_wars['action_status'],'step_limit')
            self.assertFalse(c.report.currency_wars['completion_verified'])

    def test_phase_stop_preserves_final_victory_but_never_invents_settlement(self):
        with tempfile.TemporaryDirectory() as folder:
            progress.StandardProgressTests().store(folder,'3-5',observed=False)
            states=[screen(k) for k in ('final_victory','match_rating','match_summary','match_statistics','lobby')]
            c=flow.StandardFlowTests().context(folder,states,resume=True)
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_budget.PHASE_ACTIONS',2):
                result=run_standard(c)
            self.assertEqual(result.status,'partial');self.assertEqual(c.currency_standard_input.call_count,2)
            self.assertTrue(c.report.currency_wars['match_victory_observed']);self.assertFalse(c.report.currency_wars['completion_verified'])
            self.assertEqual(c.report.currency_wars['action_status'],'step_limit')


class StandardJournalSizeTests(unittest.TestCase):
    def test_real_context_can_read_a_journal_larger_than_the_old_four_mib_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            store=flow.StandardFlowTests().store(folder);store.data.update(status='active',start_verified=True)
            # Repeated bounded appearance-like fields model retained evidence;
            # this test exercises IO size, not a claim about game progression.
            store.data['size_fixture']=['a'*2048 for _ in range(2200)];store.persist()
            self.assertGreater(store.path.stat().st_size,4*1024*1024)
            restored=StandardSession(store.path);self.assertEqual(restored.data['match_id'],store.data['match_id'])
            scene=screen('boss_preview');scene.tokens += [flow.Token('UID:100000000',.99,(.01,.96,.1,.99))]
            from autohsr.currency_wars_identity import account_key
            restored.data['account_key']=account_key(scene);restored.persist()
            choice=next_action(scene,session=restored.data);restored.pending(choice.intent,0,'before.png',choice.expected)
            c=Context(Runner(Settings(),operation='currency_wars_standard'),Mock(),Mock())
            c.last_scene=scene;c.currency_standard_session=restored;c.checkpoint=Mock();c.sleep=Mock()
            c.currency_standard_input(scene,choice);c.window.click.assert_called_once()

    def test_over_size_persist_keeps_original_bytes_and_sends_no_input(self):
        with tempfile.TemporaryDirectory() as folder:
            store=flow.StandardFlowTests().store(folder);before=store.path.read_bytes();digest=hashlib.sha256(before).hexdigest()
            store.data['size_fixture']='文'*3000
            with patch('autohsr.currency_wars_session.MAX_SESSION_BYTES',2048),self.assertRaises(AutomationError):store.persist()
            self.assertEqual(hashlib.sha256(store.path.read_bytes()).hexdigest(),digest)
            self.assertFalse(store.path.with_suffix('.tmp').exists())
            store.path.write_bytes(b' '*2049)
            with patch('autohsr.currency_wars_session.MAX_SESSION_BYTES',2048):
                with self.assertRaises(ValueError):read_session(store.path)
                with self.assertRaises(AutomationError):StandardSession(store.path)
                with self.assertRaises(AutomationError):store.require_pending('advance_standard_preview',0)

    def test_pending_cannot_append_past_the_shared_action_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            store=flow.StandardFlowTests().store(folder)
            for _ in range(MAX_ACTIONS):action(store.data)
            store.persist();before=store.path.read_bytes()
            with self.assertRaises(AutomationError):store.pending('advance_standard_preview',0,'before.png','plane_map')
            self.assertEqual(len(store.data['actions']),MAX_ACTIONS);self.assertEqual(store.path.read_bytes(),before)


if __name__=='__main__':unittest.main()
