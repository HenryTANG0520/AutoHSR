"""Occupied-slot optimization requires both fresh identities after a drag."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_collector import TIER_FIELD, collected_snapshot, roster_cells
from autohsr.currency_wars_deployment import _crop
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_exchange import (active_action, after_close, begin_verification,
    choose_exchange, exchange_proposal, inspectable, record_intent)
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.models import AutomationError, InputInterrupted, Scene, Stopped, Token
from autohsr.tests import test_currency_wars_collector as collector_helpers
from autohsr.tests import test_currency_wars_standard_trading as trading_helpers


def fixture(variant='core'):
    board,session = trading_helpers.full_board_fixture(gold=25)
    units = session['collection']['units']
    if variant == 'same_name':
        units['bench:4']['unit'].update(name='乱破',star=2,tier=1,eligible_zones=('front',))
    elif variant == 'positions':
        session['strategy'] = 'seele'
        units['front:1']['unit']['name']='符玄'
        units['back:1']['unit'].update(name='希儿',eligible_zones=('front','back'),traits=())
        units['front:2']['unit'].update(name='瓦尔特',eligible_zones=('front','back'),traits=())
    else:
        session['strategy'] = 'aglaea'
        units['bench:4']['unit'].update(name='阿格莱雅',star=1,tier=1,eligible_zones=('front','back'),traits=('协同',))
    choice = exchange_proposal(board,session)
    after = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
    if variant != 'same_name':
        cells = {(cell.zone,cell.slot):cell for cell in roster_cells(board)}
        for index,position in enumerate(((choice.payload[4],choice.payload[5]),(choice.payload[6],choice.payload[7]))):
            patch = _crop(after.image,cells[position].roi)
            patch[:] = np.random.default_rng(910+index).integers(0,256,patch.shape,dtype=np.uint8)
    return board,after,session,choice


def panel(unit, node='1-1'):
    scene = collector_helpers.OwnedProfileTests().scene(unit['star'])
    scene.tokens = [token for token in scene.tokens if not token.within((.775,.19,.91,.235))
                    and not token.within((.78,.235,.90,.28)) and not token.within(TIER_FIELD)
                    and not token.within((.72,.27,.98,.315))]
    scene.tokens += [Token(unit['name'],.99,(.79,.20,.88,.23)),Token(str(unit['tier']),.99,TIER_FIELD)]
    zones = unit['eligible_zones']
    mode = '前后台' if set(zones) == {'front','back'} else '前台' if zones == ['front'] or zones == ('front',) else '后台'
    scene.tokens.append(Token(mode,.99,(.80,.24,.88,.26)))
    for index,trait in enumerate(unit.get('traits') or ()):
        scene.tokens.append(Token(trait,.99,(.73+index*.05,.28,.77+index*.05,.31)))
    scene.tokens = [Token(node,token.score,token.box) if token.text == '1-1' else token for token in scene.tokens]
    scene.captured_at = time.monotonic()
    return scene


def expected_units(session, choice):
    source = session['collection']['units'][choice.payload[4]+':'+str(choice.payload[5])]['unit']
    target = session['collection']['units'][choice.payload[6]+':'+str(choice.payload[7])]['unit']
    return (dict(source,zone=target['zone'],slot=target['slot']),
            dict(target,zone=source['zone'],slot=source['slot']))


class StandardExchangeTests(unittest.TestCase):
    def context(self, folder, board, session, states):
        c = trading_helpers.StandardTradingTests().context(folder,board,session,states)
        actual = Context(Runner(Settings(),operation='currency_wars_standard'),c.window,Mock())
        actual.checkpoint,actual.sleep = lambda:c.checkpoint(),c.sleep
        def dispatch(scene,choice):
            actual.last_scene = c.last_scene
            actual.currency_standard_session = c.currency_standard_session
            actual.currency_standard_input(scene,choice)
            c.last_scene = actual.last_scene
        c.currency_standard_input = Mock(side_effect=dispatch)
        return c

    def stage(self, folder, variant='core'):
        board,after,session,choice = fixture(variant)
        c = self.context(folder,board,session,[board])
        store = StandardSession(Path(c.report.run_dir).parent/'currency-standard-session.json')
        item = store.pending(choice.intent,0,'before.png',choice.expected)
        item['target'] = list(choice.payload)
        record_intent(store.data,choice)
        item.update(status='verified',after='after.png')
        begin_verification(store.data,choice,board,after)
        store.persist()
        return board,after,store,choice

    def test_candidate_is_a_legal_strict_improvement_and_cannot_repeat_in_reverse(self):
        for variant in ('core','same_name','positions'):
            with self.subTest(variant=variant):
                board,_,session,choice = fixture(variant)
                self.assertEqual(next_action(board,session=session),choice)
                snapshot = collected_snapshot(board,session,0,'candidate')
                selected = choose_exchange(snapshot,session['strategy'])
                self.assertGreater(selected.improvement,0)
                if variant == 'same_name':
                    self.assertEqual(selected.source.name,selected.target.name)
                    self.assertGreater(selected.source.star,selected.target.star)
                if variant == 'positions':
                    self.assertEqual((selected.source.name,selected.target.zone),('希儿','front'))
                replacements = dict(zip(((selected.source.zone,selected.source.slot),(selected.target.zone,selected.target.slot)),
                                        (replace(selected.target,zone=selected.source.zone,slot=selected.source.slot),
                                         replace(selected.source,zone=selected.target.zone,slot=selected.target.slot))))
                moved = replace(snapshot,roster=tuple(replacements.get((unit.zone,unit.slot),unit) for unit in snapshot.roster))
                self.assertIsNone(choose_exchange(moved,session['strategy']))

    def test_unknown_ineligible_and_duplicate_field_rosters_do_not_authorize_exchange(self):
        board,_,session,_ = fixture()
        snapshot = collected_snapshot(board,session,0,'candidate')
        for unit in (replace(snapshot.roster[0],star=None),replace(snapshot.roster[0],eligible_zones=None)):
            with self.assertRaises(AutomationError):
                choose_exchange(replace(snapshot,roster=(unit,)+snapshot.roster[1:]))
        units = tuple(replace(unit,eligible_zones=('back',)) if unit.name=='阿格莱雅' else unit for unit in snapshot.roster)
        selected = choose_exchange(replace(snapshot,roster=units),'aglaea')
        self.assertEqual(selected.target.zone,'back')
        changed = list(snapshot.roster)
        field = [i for i,unit in enumerate(changed) if unit.zone != 'bench']
        changed[field[1]] = replace(changed[field[1]],name=changed[field[0]].name)
        with self.assertRaises(AutomationError):choose_exchange(replace(snapshot,roster=tuple(changed)))

    def test_full_context_exchange_reads_both_names_stars_and_tiers_before_completion(self):
        for variant in ('core','same_name','positions'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                board,after,session,choice = fixture(variant)
                expected = expected_units(session,choice)
                states = [board,after,after,panel(expected[0]),after,panel(expected[1]),after]
                c = self.context(folder,board,session,states)
                def stop_verified():
                    data = getattr(c,'currency_standard_session',None)
                    if data and data.data.get('exchange',{}).get('status') == 'verified':
                        raise Stopped('exchange fixture completed')
                c.checkpoint = stop_verified
                with patch('autohsr.currency_wars_replay.save_sample'), \
                        patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3), \
                        self.assertRaises(Stopped):
                    run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['exchange']['status'],'verified')
                self.assertTrue(saved['actions'][0]['movement_verified'])
                self.assertEqual(saved['exchange']['inspection_attempts'],2)
                self.assertEqual(len(saved['exchange_history']),1)
                self.assertEqual(ledger_status(saved['actions']),'clear')
                for unit in expected:
                    actual = saved['collection']['units'][unit['zone']+':'+str(unit['slot'])]['unit']
                    self.assertEqual((actual['name'],actual['star'],actual['tier']),(unit['name'],unit['star'],unit['tier']))
                c.window.drag.assert_called_once()
                self.assertEqual(c.window.click.call_count,4)
                self.assertFalse(saved['completion_verified'])

    def test_returned_or_unchanged_board_is_not_proof_of_identity_and_is_not_retried(self):
        for variant in ('core','same_name'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                board,_,session,choice = fixture(variant)
                old = session['collection']['units'][choice.payload[6]+':'+str(choice.payload[7])]['unit']
                self.assertTrue(inspectable(choice,board,board))
                c = self.context(folder,board,session,[board,board,board,panel(old)])
                with patch('autohsr.currency_wars_replay.save_sample'), \
                        patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3), \
                        self.assertRaises(AutomationError):
                    run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['exchange']['status'],'identity_mismatch')
                self.assertFalse(saved['actions'][0]['movement_verified'])
                c.window.drag.assert_called_once()
                c.window.click.assert_called_once()
                with self.assertRaises(AutomationError):run_standard(c)
                c.window.drag.assert_called_once()
                c.window.click.assert_called_once()

    def test_moved_board_needs_same_money_life_level_and_deployment(self):
        board,after,session,choice = fixture()
        for label,value in (('gold',24),('level',4),('deployment',(2,3))):
            bad = Scene(list(after.tokens),after.image.copy())
            trading_helpers.hud(bad,**{label:value})
            self.assertFalse(inspectable(choice,board,bad))
        bad = Scene(list(after.tokens),after.image.copy())
        bad.tokens = [Token('99',token.score,token.box) if token.text=='100' else token for token in bad.tokens]
        self.assertFalse(inspectable(choice,board,bad))

    def test_pause_keeps_pending_drag_and_new_epoch_closes_then_reidentifies_panel(self):
        with tempfile.TemporaryDirectory() as folder:
            board,after,store,choice = self.stage(folder)
            inspect = next_action(after,session=store.data)
            item = store.pending(inspect.intent,0,'before_profile.png',inspect.expected)
            item.update(target=list(inspect.payload),status='verified',after='profile.png')
            store.data['inspecting'] = dict(zone=inspect.payload[0],slot=inspect.payload[1],node=inspect.payload[2],
                                            signature=inspect.payload[3],exchange_id=inspect.payload[4],input_epoch=0)
            store.data['account_verified_epoch'] = 1
            unit = store.data['exchange']['expected'][inspect.payload[0]+':'+str(inspect.payload[1])]
            close = next_action(panel(unit),session=store.data)
            self.assertEqual(close.intent,'close_standard_exchange_stale_panel')
            after_close(store.data,close,after)
            self.assertEqual(next_action(after,session=store.data).intent,'inspect_standard_exchange_unit')
            self.assertFalse(store.data['actions'][0]['movement_verified'])
            # A new Runner may start at epoch 0 again; run identity also binds
            # the view and prevents recycling a prior run's location evidence.
            store.data['inspecting'] = dict(zone=inspect.payload[0],slot=inspect.payload[1],node=inspect.payload[2],
                                            signature=inspect.payload[3],exchange_id=inspect.payload[4],
                                            input_epoch=0,run_dir='previous-run')
            store.data['account_verified_epoch'] = 0
            self.assertEqual(next_action(panel(unit),session=store.data).intent,'close_standard_exchange_stale_panel')
        with tempfile.TemporaryDirectory() as folder:
            board,_,session,_ = fixture()
            c = self.context(folder,board,session,[board])
            c.currency_standard_input.side_effect = InputInterrupted('pause during drag')
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaises(InputInterrupted):run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'pending')
            self.assertNotIn('exchange',saved)
            c.currency_standard_input.reset_mock()
            with self.assertRaises(AutomationError):run_standard(c)
            c.currency_standard_input.assert_not_called()

    def test_unproven_source_and_exhausted_inspection_never_fall_through_to_trading(self):
        with tempfile.TemporaryDirectory() as folder:
            _,after,store,_ = self.stage(folder)
            store.data['exchange']['inspection_attempts'] = 6
            with self.assertRaises(AutomationError):next_action(after,session=store.data)
            store.data['exchange']['inspection_attempts'] = 0
            store.data['actions'][0]['status'] = 'unknown'
            with self.assertRaises(AutomationError):active_action(after,store.data)

    def test_context_rejects_forged_drag_and_readonly_scope_before_any_input(self):
        with tempfile.TemporaryDirectory() as folder:
            board,_,session,choice = fixture()
            c = self.context(folder,board,session,[board])
            store = StandardSession(Path(c.report.run_dir).parent/'currency-standard-session.json')
            item = store.pending(choice.intent,0,'before.png',choice.expected)
            item['target'] = list(choice.payload)
            record_intent(store.data,choice);store.persist()
            for operation in ('currency_wars','currency_wars_standard'):
                actual = Context(Runner(Settings(),operation=operation),Mock(),Mock())
                actual.last_scene,actual.currency_standard_session = board,store
                actual.checkpoint,actual.sleep = Mock(),Mock()
                proposed = replace(choice,target=replace(choice.target,end=(.1,.1)))
                with self.assertRaises(AutomationError):actual.currency_standard_input(board,proposed)
                actual.window.drag.assert_not_called()
                actual.window.click.assert_not_called()
            source_folder = Path(folder)/'source'
            source_folder.mkdir()
            board,after,store,_ = self.stage(str(source_folder))
            store.data['exchange']['board'][0] = '2-1'
            with self.assertRaises(AutomationError):next_action(after,session=store.data)


if __name__ == '__main__':
    unittest.main()
