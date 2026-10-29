"""Configured names influence preferences, never invent observed identities/costs."""
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
from dataclasses import asdict,replace
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from autohsr.app import Runner
from autohsr.config import Settings,SettingsError
from autohsr.currency_wars_character_rewards import choose,options
from autohsr.currency_wars_collector import roster_cells,collected_snapshot
from autohsr.currency_wars_match import read_match,supplement_shop_fields,unit_name
from autohsr.currency_wars_names import (PUBLIC_NAME,configured_name,resolve_name,
    supplement_configured_names,validate_name,with_name)
from autohsr.currency_wars_prepare import trusted
from autohsr.currency_wars_roster import read_character
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_deployment import choose_deployment
from autohsr.currency_wars_standard_exchange import choose_exchange
from autohsr.currency_wars_standard_flow import run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_policy import rank_standard_offers
from autohsr.currency_wars_standard_rewards import active_action
from autohsr.currency_wars_standard_sale import choose_sale
from autohsr.currency_wars_standard_supply_refresh import _valid_table
from autohsr.currency_wars_standard_trading import purchase_action
from autohsr.currency_wars_state import FactEvidence,ShopOffer,StrategySnapshot,UnitState
from autohsr.models import AutomationError,Scene,Stopped,Token
from autohsr.tests import test_currency_wars_character_rewards as characters
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_policy as policy
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_supply_refresh as refresh


def literal_worker(input_path,output_path,confidence,configured_name):
    """Actual bundled recognition in a child, without a game or desktop API."""
    import numpy as np
    from autohsr.vision import Vision
    image=np.load(input_path,allow_pickle=False);reader=Vision(confidence)
    result=reader.read_configured_unit_name(image,configured_name)
    assert reader.read_configured_unit_name(image,'different-name') is None
    assert result is not None
    Path(output_path).write_text(json.dumps(dict(status='ok',tokens=[asdict(result)])),encoding='utf-8')


def approved(scene,name):
    reader=Mock();reader.read_configured_unit_name.return_value=None
    return supplement_configured_names(scene,reader,name)


def freeze(session,name):
    session['remembrance_name']=unit_name(name)
    if session.get('pre_shop_snapshot'):session['pre_shop_snapshot']['private_names']=[unit_name(name)]
    if session.get('reward'):
        data=session['reward'];data['basis']['snapshot']['private_names']=[unit_name(name)]
        for source in session['actions']:
            if source.get('reward_basis'):source['reward_basis']['snapshot']['private_names']=[unit_name(name)]


def named_shop(name,price=1):
    board,shop,session=trading.purchase_fixture(100,price)
    roi=(.332,.265,.432,.305)
    shop.tokens=[t for t in shop.tokens if not t.within(roi)]
    shop.tokens.append(Token(name,.99,(.34,.275,.40,.295)))
    session['strategy']='seele'
    freeze(session,name)
    return board,approved(shop,name),session


def bounded(c):
    snapshot=c.snapshot;reads=0
    def read():
        nonlocal reads
        reads+=1
        if reads>100:
            actions=c.currency_standard_session.data['actions']
            raise AssertionError('offline fixture exhausted: '+repr([(a['action'],a['status']) for a in actions]))
        return snapshot()
    c.snapshot=read
    return c


class ConfiguredNameTests(unittest.TestCase):
    def test_validation_and_settings_roundtrip(self):
        for raw,expected in ((' 星 · 穹 ','星穹'),('Captain-7','captain-7'),('777','777'),('★小灰★','★小灰★'),('','')):
            with self.subTest(raw=raw):self.assertEqual(validate_name(raw),expected)
        for value in (None,1,'a'*41,'a\nb','a\tb','!!!','\u200b'):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_name(value)
        with self.assertRaises(SettingsError) as caught:Settings(currency_remembrance_name='a\nb').validate('currency_wars')
        self.assertEqual(caught.exception.field,'currency_remembrance_name')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            Settings(currency_remembrance_name='Captain-7').save(path)
            self.assertEqual(Settings.load(path).currency_remembrance_name,'Captain-7')
        self.assertEqual(Settings().currency_remembrance_name,'')

    def test_resume_freezes_the_original_name_including_old_unconfigured_sessions(self):
        settings=Settings(currency_remembrance_name='改名后')
        self.assertEqual(resolve_name(settings),'改名后')
        self.assertEqual(resolve_name(settings,'Captain-7'),'captain-7')
        self.assertEqual(resolve_name(settings,session={'remembrance_name':'旧名'},resume=True),'旧名')
        self.assertEqual(resolve_name(settings,session={},resume=True),'')
        self.assertEqual(resolve_name(settings,'旧 名',{'remembrance_name':'旧名'},resume=True),'旧名')
        for session in ({},{'remembrance_name':'旧名'}):
            with self.subTest(session=session),self.assertRaises(AutomationError):
                resolve_name(settings,'新名',session,resume=True)

    def test_preferences_keep_native_order_and_default_behavior(self):
        original=('希儿','瓦尔特','刻律德菈','符玄')
        self.assertEqual(with_name(original,'seele','小灰'),original[:3]+('小灰',)+original[3:])
        self.assertEqual(with_name(original,'seele','瓦尔特'),original)
        self.assertEqual(with_name(original,'default','小灰'),original)

    def test_header_requires_observation_for_unusual_literal_names(self):
        unit=dict(name='中文角色',zone='bench',slot=1,star=1,tier=2,traits=(),equipment=(),eligible_zones=('front','back'))
        for name in ('小灰','Captain-7','777','★小灰★'):
            page=exchange.panel(dict(unit,name=name),'1-1')
            page=approved(page,name)
            self.assertEqual(read_character(page).name,unit_name(name))
            # A configured string by itself cannot create any OCR identity.
            empty=Scene([t for t in page.tokens if not t.within((.775,.19,.91,.235))],page.image)
            absent=approved(empty,name)
            self.assertIsNone(configured_name(absent,(.775,.19,.91,.235)))
            with self.assertRaises(AutomationError):read_character(absent)

    def test_local_literal_reads_need_two_agreeing_sources_and_preserve_conflicts(self):
        _,page,session=named_shop('Captain-7')
        roi=(.332,.265,.432,.305)
        page.tokens=[t for t in page.tokens if not t.within(roi)]
        page.field_reads={}
        for pair,accepted in (((('Captain-7',.99),('captain-7',.99)),True),
                              ((('Captain-7',.99),('Captain-7',.89)),False),
                              ((('Captain-7',.99),('other',.99)),False),
                              ((('other',.99),('other',.99)),False)):
            reader=Mock();reader.read_configured_unit_name.side_effect=[Token(text,score,(0,0,1,1)) for text,score in pair]
            # Other four fields already have ordinary names, so only this ROI is read.
            result=supplement_configured_names(page,reader,'Captain-7')
            self.assertEqual(configured_name(result,roi) is not None,accepted,pair)
        conflict=Scene(page.tokens+[Token('相反角色',.99,roi)],page.image)
        reader=Mock();reader.read_configured_unit_name.return_value=Token('Captain-7',.99,(0,0,1,1))
        self.assertIsNone(configured_name(supplement_configured_names(conflict,reader,'Captain-7'),roi))

    def test_low_confidence_pending_name_is_not_replaced_by_generic_shop_guess(self):
        _,page,_=named_shop('Captain-7')
        page.tokens=[replace(t,score=.8) if unit_name(t.text)=='captain-7' else t for t in page.tokens]
        page.field_reads={}
        reader=Mock();reader.read_configured_unit_name.return_value=None
        pending=supplement_configured_names(page,reader,'Captain-7')
        reader.read_unit_name.return_value=Token('阿格莱雅',.99,(0,0,1,1))
        result=supplement_shop_fields(pending,reader)
        self.assertNotIn(1,[o.slot for o in read_match(result).offers])
        self.assertEqual(trusted(result,.65).field_reads,pending.field_reads)

    def test_pending_chinese_and_numeric_names_cannot_bypass_literal_proof(self):
        for name in ('小灰','Captain-7','777','★小灰★'):
            _,page,_=named_shop(name)
            page.tokens=[replace(t,score=.8) if unit_name(t.text)==unit_name(name) else t for t in page.tokens]
            page.field_reads={};page=approved(page,name)
            self.assertNotIn(1,[o.slot for o in read_match(page).offers])
            _,hiring,session=characters.fixture(names=(name,'角色乙','角色丙'))
            freeze(session,name)
            hiring.tokens=[replace(t,score=.8) if unit_name(t.text)==unit_name(name) else t for t in hiring.tokens]
            hiring=approved(hiring,name)
            with self.subTest(name=name),self.assertRaises(AutomationError):options(hiring,'hiring_selection')
        unit=dict(name='小灰',zone='bench',slot=1,star=1,tier=2,traits=(),equipment=(),eligible_zones=('front','back'))
        page=exchange.panel(unit,'1-1')
        page.tokens=[replace(t,score=.8) if t.text=='小灰' else t for t in page.tokens]
        pending=approved(page,'小灰')
        with self.assertRaises(AutomationError):read_character(pending)
        reader=Mock();reader.read_configured_unit_name.return_value=Token('小灰',.99,(0,0,1,1))
        repaired=supplement_configured_names(page,reader,'小灰')
        self.assertEqual(read_character(repaired).name,'小灰')
        _,supply,_=rewards.supply_fixture(4,'seele')
        supply.tokens=[replace(t,text='小灰',score=.8) if t.text=='新角色甲' else t for t in supply.tokens]
        self.assertTrue(rewards._options(approved(supply,'小灰'),'supply_selection',.65)[0][1].startswith('unknown:'))

    def test_shop_uses_the_name_roi_and_visible_price_without_assigning_tier(self):
        for name in ('小灰','Captain-7','777','★小灰★'):
            for price in (0,1,6,12):
                _,page,session=named_shop(name,price)
                offer=next(o for o in read_match(page).offers if o.slot==1)
                self.assertEqual((offer.name,offer.cost),(unit_name(name),price))
                selected=purchase_action(page,session)
                self.assertEqual(selected.payload[5:7],(unit_name(name),price))
        _,page,session=named_shop('777')
        page.tokens.append(Token('777',.99,(.01,.96,.1,.99)))
        self.assertEqual(len([o for o in read_match(page).offers if o.name=='777']),1)
        snapshot=policy.state(gold=100,private_names=('777',),offers=(ShopOffer(0,'777',price=6),))
        self.assertEqual(rank_standard_offers(snapshot,'seele')[0].price,6)
        self.assertIsNone(snapshot.offers[0].tier)
        self.assertIsNone(snapshot.offers[0].star)

    def test_owned_name_changes_deployment_exchange_and_cleanup_consistently(self):
        field=(UnitState('强角甲','front',1,2,1,(),(),('front','back')),
               UnitState('强角乙','back',1,2,1,(),(),('front','back')),
               UnitState('强角丙','back',2,2,1,(),(),('front','back')))
        alias=UnitState('captain-7','bench',1,1,4,(),(),('front','back'))
        full=policy.state(roster=field+(alias,),bench_occupied=1)
        self.assertIsNone(choose_exchange(full,'seele'))
        self.assertEqual(choose_sale(full,'seele')[0],alias)
        configured=replace(full,private_names=('captain-7',))
        self.assertEqual(choose_exchange(configured,'seele').source,alias)
        self.assertIsNone(choose_sale(configured,'seele'))
        vacant=replace(configured,roster=field[:2]+(alias,UnitState('强角丁','bench',2,2,1,(),(),('front','back'))),bench_occupied=2)
        self.assertEqual(choose_deployment(vacant,'seele')[0],alias)

    def test_hiring_and_seele_expert_share_frozen_name_but_aglaea_expert_keeps_silverwolf(self):
        for kind,strategy,names,expected in (
            ('hiring_selection','aglaea',('角色甲','Captain-7','角色乙'),'captain-7'),
            ('expert_selection','seele',('角色甲','Captain-7','现金为王'),'captain-7'),
            ('expert_selection','aglaea',('银狼','Captain-7','现金为王'),'银狼')):
            _,page,session=characters.fixture(kind,strategy,names)
            freeze(session,'Captain-7');page=approved(page,'Captain-7')
            candidates=options(page,kind)
            self.assertEqual(choose(candidates,session['reward'],strategy)[1],expected)
            self.assertEqual(active_action(page,session).payload[6],expected)

    def test_private_metadata_roundtrips_but_public_state_and_identifier_hide_the_name(self):
        values=dict(page='shop',roster=(UnitState('Captain-7','front',1,1,4),),
                    offers=(ShopOffer(0,'Captain-7',6),),private_names=('captain-7',))
        evidence=tuple(FactEvidence(key,'synthetic://name',0) for key in ('page','roster','offers'))
        local=StrategySnapshot(**values,evidence=evidence)
        restored=StrategySnapshot.from_dict(json.loads(json.dumps(asdict(local))))
        self.assertEqual(restored,local)
        public=local.public_state()
        self.assertNotIn('private_names',public)
        self.assertNotIn('Captain-7',json.dumps(public))
        self.assertNotIn('captain-7',json.dumps(public))
        self.assertEqual(public['roster'][0]['name'],PUBLIC_NAME)
        self.assertEqual(public['offers'][0]['name'],PUBLIC_NAME)
        other=replace(local,private_names=('777',),roster=(replace(local.roster[0],name='777'),),offers=(replace(local.offers[0],name='777'),))
        self.assertEqual(local.snapshot_id,other.snapshot_id)
        with self.assertRaises(ValueError):replace(local,evidence=evidence+(FactEvidence('private_names','synthetic://config',0),))
        for value in (('CAPTAIN-7',),('',),('小灰','小灰'),['小灰']):
            with self.subTest(value=value),self.assertRaises(ValueError):replace(local,private_names=value)
        from autohsr.currency_wars_llm import request_payload
        from autohsr.currency_wars_planner import candidates
        payload=request_payload(SimpleNamespace(model='offline-test',token_limit_field='max_tokens',max_tokens=100),local,candidates(local),())
        self.assertNotIn('captain-7',json.dumps(payload).casefold())

    def test_actual_literal_ocr_runs_in_isolated_child_with_configured_name(self):
        import cv2
        import numpy as np
        from autohsr.ocr_isolation import IsolatedVision
        image=np.full((100,450,3),255,dtype=np.uint8)
        cv2.putText(image,'Captain-7',(12,68),cv2.FONT_HERSHEY_SIMPLEX,1.6,(0,0,0),3)
        with patch('autohsr.ocr_isolation._ocr_job',literal_worker):
            scene=IsolatedVision(timeout=20,configured_name='Captain-7').read(image)
        self.assertEqual(unit_name(scene.tokens[0].text),'captain-7')
        self.assertGreaterEqual(scene.tokens[0].score,.9)

    def test_cli_override_is_standard_only_and_does_not_save_settings(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings(currency_remembrance_name='原名').save(path)
            original=path.read_bytes()
            with patch('autohsr.app.Runner') as runner,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value=dict(status='partial')
                main(['--currency-wars-standard','--currency-remembrance-name','Captain-7','--config',str(path)])
                self.assertEqual(runner.call_args.kwargs['currency_remembrance_name'],'Captain-7')
            self.assertEqual(path.read_bytes(),original)
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(['--check','--currency-remembrance-name','小灰'])
        with self.assertRaises(ValueError):Runner(Settings(),currency_remembrance_name='小灰')
        runner=Runner(Settings(),operation='currency_wars_standard',currency_remembrance_name='Captain-7')
        self.assertEqual(runner.currency_remembrance_name,'captain-7')
        self.assertEqual(runner.settings.currency_remembrance_name,'')

    def test_resume_mismatch_precedes_scene_read_and_does_not_append_continuation(self):
        board,page,session=named_shop('Captain-7')
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[page])
            c.runner.currency_remembrance_name='新名';c.snapshot=Mock()
            path=Path(folder)/'currency-standard-session.json';original=path.read_bytes()
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(path.read_bytes(),original)
            c.snapshot.assert_not_called();c.currency_standard_input.assert_not_called()

    def test_durable_name_tamper_is_detected_before_input(self):
        with tempfile.TemporaryDirectory() as folder:
            store=StandardSession(Path(folder)/'session.json');store.begin(folder,dict(rank_verified=True))
            store.data['remembrance_name']='小灰';store.pending('observe',0,'before.png','seen')
            changed=deepcopy(store.data);changed['remembrance_name']='其他名字'
            store.path.write_text(json.dumps(changed),encoding='utf-8')
            with self.assertRaises(AutomationError):store.require_pending('observe',0)

    def test_context_buys_once_records_actual_payment_and_keeps_frozen_name(self):
        board,page,session=named_shop('Captain-7',6);choice=purchase_action(page,session)
        first,second=trading.purchased(page,choice),trading.purchased(page,choice)
        returned=Scene(list(board.tokens),second.image.copy(),captured_at=time.monotonic());trading.hud(returned,gold=94)
        with tempfile.TemporaryDirectory() as folder:
            c=bounded(trading.StandardTradingTests().context(folder,board,session,[page,first,second,returned]))
            c.settings.currency_remembrance_name='改名后'
            def stop_done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data['actions'][-1]['action']=='close_standard_shop_after_purchase' and store.data['actions'][-1]['status']=='verified':
                    raise Stopped('configured purchase complete')
            c.checkpoint=stop_done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            purchase=saved['actions'][1]
            self.assertEqual(saved['remembrance_name'],'captain-7')
            self.assertEqual(purchase['target'][5:7],['captain-7',6])
            self.assertEqual(purchase['receipt']['gold_after'],94)
            self.assertEqual(ledger_status(saved['actions']),'clear')
            self.assertEqual(c.window.click.call_count,2)
            self.assertFalse(saved['completion_verified'])

    def test_special_name_supply_is_selected_confirmed_and_recollected_by_actual_identity(self):
        for name in ('Captain-7','777'):
            before,page,session=rewards.supply_fixture(4,'seele')
            roi=(.223-.09,.50,.223+.09,.55)
            page.tokens=[t for t in page.tokens if not t.within(roi)]
            page.tokens.append(Token(name,.99,(.19,.505,.26,.54)))
            # Keep no higher priority preferred character in this synthetic case.
            page.tokens=[replace(t,text='角色丙') if t.text=='希儿' else t for t in page.tokens]
            freeze(session,name);page=approved(page,name)
            choice,highlight=rewards.selected(page,session);highlight=approved(highlight,name)
            self.assertEqual(choice.payload[6],unit_name(name))
            after=rewards.supply_board(before,choice)
            units=deepcopy(session['collection']['units'])
            for record in units.values():record['unit']['equipment']=()
            units['bench:6']=dict(unit=dict(name=unit_name(name),zone='bench',slot=6,star=1,tier=4,
                traits=('测试',),equipment=(),eligible_zones=('front','back')))
            cells=sorted((cell for cell in roster_cells(after) if cell.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot))
            states=[page,highlight,highlight,after,after]
            for cell in cells:
                states += [approved(exchange.panel(units[cell.zone+':'+str(cell.slot)]['unit'],'1-3'),name),after]
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                c=bounded(trading.StandardTradingTests().context(folder,before,session,states))
                def stop_done():
                    store=getattr(c,'currency_standard_session',None)
                    if store and store.data.get('reward',{}).get('status')=='verified':raise Stopped('configured supply delivered')
                c.checkpoint=stop_done
                with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3),self.assertRaises(Stopped):
                    run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                claim=next(a for a in saved['actions'] if a['action']=='confirm_standard_supply')
                self.assertTrue(claim['reward_verified']);self.assertTrue(claim['reward_effect']['unit_verified'])
                self.assertEqual(saved['collection']['units']['bench:6']['unit']['name'],unit_name(name))
                snapshot=collected_snapshot(after,saved,0,'synthetic://delivered')
                self.assertNotIn(unit_name(name),json.dumps(snapshot.public_state(),ensure_ascii=False))
                self.assertEqual(ledger_status(saved['actions']),'clear')

    def test_supply_refresh_literal_table_needs_frozen_private_name(self):
        rows=[dict(slot=i,name=name,item='battery',item_name='光能电池') for i,name in enumerate(('captain-7','角色乙','角色丙','角色丁'))]
        self.assertFalse(_valid_table(rows))
        self.assertTrue(_valid_table(rows,('captain-7',)))
        self.assertFalse(_valid_table(rows,('其他名字',)))

    def test_refresh_receipt_keeps_the_configured_name_in_its_frozen_source_chain(self):
        _,page,session=refresh.fixture(4,'seele',1);freeze(session,'Captain-7')
        final=refresh.options(page,(('Captain-7','光能电池'),)+refresh.UNWANTED[1:4]);refresh.quota(final,0)
        final=approved(final,'Captain-7')
        refresh.record(session,page,final)
        action=session['actions'][-1]
        self.assertTrue(refresh.valid_receipt(action,session['actions']))
        self.assertEqual(action['supply_refresh_receipt']['candidates_after'][0]['name'],'captain-7')
        self.assertEqual(active_action(final,session).payload[6],'captain-7')
        action['supply_refresh_origin']['basis']['snapshot']['private_names']=[]
        self.assertFalse(refresh.valid_receipt(action,session['actions']))

    def test_unknown_named_purchase_is_not_replayed_when_resuming(self):
        board,page,session=named_shop('Captain-7')
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[page,page])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',
                    SimpleNamespace(monotonic=Mock(side_effect=[0,61]))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown')
            self.assertEqual(saved['actions'][-1]['target'][5],'captain-7')
            self.assertEqual(c.window.click.call_count,1)
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(c.window.click.call_count,1)


if __name__=='__main__':unittest.main()
