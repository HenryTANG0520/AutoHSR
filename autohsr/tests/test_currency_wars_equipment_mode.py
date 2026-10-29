"""Generic boss-only equipment never suppresses independently verified cores."""
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
from dataclasses import asdict,replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from autohsr.app import Context,Runner
from autohsr.config import Settings,SettingsError
from autohsr.currency_wars_collector import collected_snapshot
from autohsr.currency_wars_equipment_mode import (FAST_FIELD,generic_allowed,resolve_fast_mode,stored_fast_mode)
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_equipment import proposal
from autohsr.currency_wars_standard_flow import next_action,run_standard
from autohsr.models import AutomationError,Stopped,Token
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_flow as flow
from autohsr.tests import test_currency_wars_standard_rewards as rewards


def at_node(board,session,node):
    rewards.node(board,node);session['shop_observed_nodes']=[node]
    for record in session['collection']['units'].values():record['node']=node
    return board,session


class EquipmentModeTests(unittest.TestCase):
    def test_settings_default_legacy_roundtrip_and_boolean_validation(self):
        self.assertIs(Settings().currency_fast_mode,False)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings(currency_fast_mode=True).save(path)
            self.assertIs(Settings.load(path).currency_fast_mode,True)
            old=asdict(Settings());old.pop('currency_fast_mode');path.write_text(json.dumps(old),encoding='utf-8')
            self.assertIs(Settings.load(path).currency_fast_mode,False)
        for value in (0,1,'true',None,[]):
            with self.subTest(value=value),self.assertRaises(SettingsError) as caught:
                Settings(currency_fast_mode=value).validate('currency_wars')
            self.assertEqual(caught.exception.field,'currency_fast_mode')

    def test_runner_override_is_standard_only_and_does_not_mutate_settings(self):
        settings=Settings(currency_fast_mode=True)
        for value in (False,True):
            with self.assertRaises(ValueError):Runner(settings,currency_fast_mode=value)
            runner=Runner(settings,operation='currency_wars_standard',currency_fast_mode=value)
            self.assertIs(runner.currency_fast_mode,value);self.assertIs(settings.currency_fast_mode,True)
        for value in (0,1,'true'):
            with self.assertRaises(ValueError):Runner(settings,operation='currency_wars_standard',currency_fast_mode=value)

    def test_new_session_freezes_settings_and_legacy_resume_stays_false(self):
        settings=Settings(currency_fast_mode=True)
        self.assertIs(resolve_fast_mode(settings),True);self.assertIs(resolve_fast_mode(settings,False),False)
        self.assertIs(resolve_fast_mode(settings,session={},resume=True),False)
        self.assertIs(resolve_fast_mode(settings,session={FAST_FIELD:False},resume=True),False)
        settings.currency_fast_mode=False
        self.assertIs(resolve_fast_mode(settings,session={FAST_FIELD:True},resume=True),True)
        self.assertIs(resolve_fast_mode(settings,True,{FAST_FIELD:True},resume=True),True)
        for stored,requested in (({},True),({FAST_FIELD:True},False),({FAST_FIELD:False},True)):
            with self.assertRaises(AutomationError):resolve_fast_mode(settings,requested,stored,resume=True)
        for value in (0,1,'false',None):
            with self.assertRaises(AutomationError):stored_fast_mode({FAST_FIELD:value})

    def test_both_cli_directions_are_scoped_and_never_save_configuration(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings(currency_fast_mode=False).save(path);original=path.read_bytes()
            for flag,value in (('--currency-fast-mode',True),('--no-currency-fast-mode',False)):
                with patch('autohsr.app.Runner') as runner,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                    runner.return_value.run.return_value=dict(status='partial')
                    main(['--currency-wars-standard',flag,'--config',str(path)])
                    self.assertIs(runner.call_args.kwargs['currency_fast_mode'],value)
                self.assertEqual(path.read_bytes(),original)
                with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(['--check',flag])

    def test_resume_conflict_precedes_snapshot_and_preserves_the_original_journal(self):
        for original_mode in (None,False,True):
            with self.subTest(original_mode=original_mode),tempfile.TemporaryDirectory() as folder:
                board,session=equipment.fixture()
                if original_mode is not None:session[FAST_FIELD]=original_mode
                c=exchange.StandardExchangeTests().context(folder,board,session,[board])
                c.runner.currency_fast_mode=not bool(original_mode);c.snapshot=Mock()
                path=Path(folder)/'currency-standard-session.json';original=path.read_bytes()
                with self.assertRaises(AutomationError):run_standard(c)
                self.assertEqual(path.read_bytes(),original);c.snapshot.assert_not_called();c.currency_standard_input.assert_not_called()

    def test_new_game_mode_is_durable_before_first_input_without_saving_settings(self):
        for saved,explicit,expected in ((True,None,True),(False,True,True),(True,False,False)):
            with self.subTest(saved=saved,explicit=explicit),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'config.json';Settings(currency_fast_mode=saved).save(path);before=path.read_bytes()
                c=flow.StandardFlowTests().context(folder,[flow.ready()]);c.settings=Settings.load(path);c.runner.currency_fast_mode=explicit
                original=c.currency_standard_input.side_effect
                def stop_before_dispatch(scene,choice):
                    original(scene,choice)
                    self.assertIs(StandardSession(c.currency_standard_session.path).data[FAST_FIELD],expected)
                    raise Stopped('frozen before first input')
                c.currency_standard_input.side_effect=stop_before_dispatch
                with patch('autohsr.currency_wars_standard_flow.locate',flow.StandardFlowTests().locate), \
                     patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                self.assertEqual(path.read_bytes(),before);c.currency_standard_input.assert_called_once()

    def test_runner_preflight_rejects_conflict_or_invalid_access_before_game_start(self):
        for case in ('mode','missing','existing','unknown'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);path=root/'runs'/'currency-standard-session.json'
                if case!='missing':
                    store=StandardSession(path);store.begin(root/'old',dict(rank_verified=True));store.data.update(status='active',start_verified=True)
                    store.data[FAST_FIELD]=False
                    if case=='unknown':store.data['actions']=[dict(id=0,action='stage_standard_equipment',status='unknown',input_epoch=0)]
                    store.persist()
                runner=Runner(Settings(),operation='currency_wars_standard',currency_resume=case!='existing',
                              currency_fast_mode=True if case=='mode' else None)
                with patch('autohsr.app.ROOT',root),patch('autohsr.windows.kernel32') as kernel, \
                     patch('autohsr.app.C.get_last_error',return_value=0),patch.object(runner,'_prepare_daily_game') as prepare, \
                     patch.object(runner,'_arm_hotkeys') as hotkeys,patch('autohsr.app.find_game') as find:
                    kernel.CreateMutexW.return_value=1;report=runner.run()
                self.assertEqual(report.status,'failed');prepare.assert_not_called();find.assert_not_called();hotkeys.assert_not_called()
                self.assertIn(dict(mode='速通装备',missing='没有',existing='记录',unknown='核实')[case],report.error)

    def test_durable_mode_changes_or_nonbooleans_never_grant_input(self):
        with tempfile.TemporaryDirectory() as folder:
            store=flow.StandardFlowTests().store(folder);store.data[FAST_FIELD]=True;store.pending('observe',0,'before.png','seen')
            for value in (False,0,1,'true'):
                data=deepcopy(store.data);data[FAST_FIELD]=value;store.path.write_text(json.dumps(data),encoding='utf-8')
                with self.subTest(value=value),self.assertRaises(AutomationError):store.require_pending('observe',0)

    def test_only_current_supported_standard_boss_nodes_allow_generic_fast_equipment(self):
        board,session=equipment.fixture('default',('armor',));snapshot=collected_snapshot(board,session,0,'fast_nodes')
        for label in ('1-9','2-7','3-7'):
            self.assertTrue(generic_allowed(replace(snapshot,node=label),True))
        for label in ('1-1','1-8','2-6','3-6','3-8',None):
            self.assertFalse(generic_allowed(replace(snapshot,node=label),True))
            self.assertTrue(generic_allowed(replace(snapshot,node=label),False))
        for changed in (replace(snapshot,node='1-9',game_version='4.7'),replace(snapshot,node='1-9',rules_version=None),
                        replace(snapshot,node='1-9',mode='overclock')):
            self.assertFalse(generic_allowed(changed,True))

    def test_nonboss_generic_is_skipped_and_a_previous_drag_cannot_bypass_the_mode(self):
        board,session=equipment.fixture('default',('armor',));old=proposal(board,session);self.assertIsNotNone(old)
        session[FAST_FIELD]=True;self.assertIsNone(proposal(board,session));self.assertEqual(next_action(board,session=session).intent,'start_standard_node')
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,[board]);c.snapshot()
            store=StandardSession(Path(folder)/'currency-standard-session.json');c.currency_standard_session=store
            item=store.pending(old.intent,0,'before.png',old.expected);item['target']=list(old.payload);store.persist()
            with self.assertRaises(AutomationError):c.currency_standard_input(board,old)
            c.window.drag.assert_not_called();c.window.click.assert_not_called()

    def test_named_core_direct_wear_still_uses_formal_context_at_a_nonboss_node(self):
        for strategy,item in (('aglaea','boots'),('seele','firestorm')):
            with self.subTest(strategy=strategy),tempfile.TemporaryDirectory() as folder:
                board,session=equipment.fixture(strategy,(item,));session[FAST_FIELD]=True
                choice=proposal(board,session);self.assertIsNotNone(choice)
                role=session['collection']['units']['front:2']['unit'];after=equipment.consumed(board,choice.payload[5])
                c=exchange.StandardExchangeTests().context(folder,board,session,[board,after,after,equipment.panel(role,(item,)),after])
                def stop_done():
                    store=getattr(c,'currency_standard_session',None)
                    if store and len(store.data.get('equipment_history',[]))==1:raise Stopped('named core verified')
                c.checkpoint=stop_done
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                self.assertTrue(c.currency_standard_session.data['actions'][0]['equipment_verified']);c.window.drag.assert_called_once()
                self.assertIs(c.currency_standard_session.data[FAST_FIELD],True)

    def test_complete_named_cores_do_not_enable_nonboss_generic_fallback_in_fast_mode(self):
        for strategy,worn in (('aglaea',('boots','boots','propeller')),('seele',('firestorm','firestorm','chainsaw'))):
            board,session=equipment.fixture(strategy,('battery',),worn)
            for record in session['collection']['units'].values():record['recommendations']=['battery']
            self.assertIsNotNone(proposal(board,session));session[FAST_FIELD]=True;self.assertIsNone(proposal(board,session))
            at_node(board,session,'2-7');self.assertIsNotNone(proposal(board,session))

    def test_boss_generic_recipe_keeps_two_independent_consumption_and_worn_receipts(self):
        board,session=equipment.fixture('default',('armor','armor'));at_node(board,session,'1-9');session[FAST_FIELD]=True
        for record in session['collection']['units'].values():
            record.update(recommendations=['hard_armor'],equipment_recipes=[dict(product='hard_armor',components=['armor','armor'])])
        choice=proposal(board,session);key=choice.payload[6]+':'+str(choice.payload[7]);role=session['collection']['units'][key]['unit']
        first=equipment.consumed(board,6);second=equipment.consumed(first,7)
        a=equipment.panel(role,('armor',));b=equipment.panel(role,('hard_armor',));rewards.node(a,'1-9');rewards.node(b,'1-9')
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,[board,first,first,a,first,second,second,b,second])
            def stop_done():
                store=getattr(c,'currency_standard_session',None)
                if store and len(store.data.get('equipment_history',[]))==2:raise Stopped('boss craft verified')
            c.checkpoint=stop_done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            data=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(data['collection']['units'][key]['unit']['equipment'],['hard_armor'])
            self.assertEqual(c.window.drag.call_count,2);self.assertFalse(data['completion_verified'])

    def test_fast_mode_never_relaxes_account_epoch_version_or_transaction_provenance(self):
        board,session=equipment.fixture('default',('armor',));at_node(board,session,'1-9');session[FAST_FIELD]=True
        for change in ('epoch','version','ledger','roster'):
            data=deepcopy(session)
            if change=='epoch':data['account_verified_epoch']=1
            elif change=='version':data['client']['version']='4.7'
            elif change=='ledger':data['actions']=[dict(action='buy_standard_offer',status='unknown')]
            else:data['collection']['complete']=False
            with self.subTest(change=change),self.assertRaises(AutomationError):proposal(board,data)
        with tempfile.TemporaryDirectory() as folder:
            choice=proposal(board,session);c=exchange.StandardExchangeTests().context(folder,board,session,[board]);c.snapshot()
            store=StandardSession(Path(folder)/'currency-standard-session.json');c.currency_standard_session=store
            item=store.pending(choice.intent,0,'before.png',choice.expected);item['target']=list(choice.payload);store.persist()
            board.tokens=[Token('UID:200000000',t.score,t.box) if t.text=='UID:100000000' else t for t in board.tokens]
            with self.assertRaises(AutomationError) as caught:c.currency_standard_input(board,choice)
            self.assertIn('账号',str(caught.exception))
            c.window.drag.assert_not_called();c.window.click.assert_not_called()


if __name__=='__main__':unittest.main()
