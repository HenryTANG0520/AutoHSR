"""Owned slots are located before their identities are read; no transactions."""
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from autohsr.currency_wars_collector import roster_cells, first_unit_probe
from autohsr.currency_wars_collector import character_stars, owned_profile, supplement_character_tier, collected_snapshot, TIER_FIELD
from autohsr.currency_wars_state import StrategySnapshot, FactEvidence, UnitState
from autohsr.currency_wars_deployment import bench_face
from autohsr.models import AutomationError, Scene, Token
from autohsr.tests.test_currency_wars_node import screen


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(page='preparation',node='1-1',deployment=(0,3))
        self.match = patch('autohsr.currency_wars_collector.read_match',return_value=self.state)
        self.layout = patch('autohsr.currency_wars_collector.backend_layout',return_value=(6,[.315+i*.074 for i in range(6)]))
        self.match.start()
        self.layout.start()
        self.addCleanup(self.match.stop)
        self.addCleanup(self.layout.stop)

    def scene(self):
        return Scene([],np.zeros((1440,2560,3),dtype=np.uint8))

    def fill(self, scene, roi):
        x1,y1,x2,y2=roi
        patch=scene.image[round(y1*1440):round(y2*1440),round(x1*2560):round(x2*2560)]
        patch[:]=np.random.default_rng(4).integers(0,256,patch.shape,dtype=np.uint8)

    def test_all_nineteen_cells_scanned_and_only_existing_unit_probed(self):
        state=self.scene()
        for slot in (1,2,5):
            self.fill(state,bench_face(slot))
        cells=roster_cells(state)
        self.assertEqual(len(cells),19)
        self.assertEqual([(c.zone,c.slot) for c in cells if c.state=='occupied'], [('bench',1),('bench',2),('bench',5)])
        cell,target=first_unit_probe(state)
        self.assertEqual((cell.zone,cell.slot),('bench',1))
        self.assertEqual(target.center,cell.point)

    def test_uncertain_slot_is_not_treated_as_empty(self):
        state=self.scene()
        x1,y1,x2,y2=bench_face(1)
        patch=state.image[round(y1*1440):round(y2*1440),round(x1*2560):round(x2*2560)]
        patch[:]=118
        patch[::2]=138
        with self.assertRaises(AutomationError):
            roster_cells(state)

    def test_items_not_units_and_no_unit_is_not_default_first_slot(self):
        state=self.scene()
        self.fill(state,bench_face(1))
        state.tokens=[Token('开启',.99,(.21,.8,.24,.86))]
        self.assertEqual(next(c.state for c in roster_cells(state) if c.zone=='bench' and c.slot==1),'reward')
        with self.assertRaises(AutomationError):
            first_unit_probe(state)

    def test_board_count_and_image_required_before_inspection(self):
        state=self.scene()
        self.state.deployment=(1,3)
        with self.assertRaises(AutomationError):
            roster_cells(state)
        self.state.deployment=(0,3)
        state.image=None
        with self.assertRaises(AutomationError):
            roster_cells(state)

    def test_portrait_signature_changes_when_slot_content_changes(self):
        state=self.scene()
        self.fill(state,bench_face(1))
        first,_=first_unit_probe(state)
        state.image=255-state.image
        second,_=first_unit_probe(state)
        self.assertNotEqual(first.signature,second.signature)

    def test_complete_snapshot_requires_each_current_slot_and_unknowns_stay_unknown(self):
        state=self.scene()
        self.fill(state,bench_face(1))
        cell,_=first_unit_probe(state)
        snapshot=StrategySnapshot(page='preparation',node='1-1',capacity=3,
            evidence=(FactEvidence('page','test',0),FactEvidence('node','test',0)))
        session=dict(status='active',start_verified=True,entry=dict(rank_verified=True),actions=[],
            collection=dict(input_epoch=0,complete=True,units={'bench:1':dict(signature=cell.signature,node='1-1',
                unit=asdict(UnitState('砂金','bench',1,2,2)))}))
        with patch('autohsr.currency_wars_state.snapshot_from_scene',return_value=snapshot):
            result=collected_snapshot(state,session,0,'current')
            self.assertTrue(result.roster_complete)
            self.assertEqual((result.bench_capacity,result.bench_occupied),(9,1))
            self.assertTrue(result.known('mode','rank','wealth','roster'))
            self.assertFalse(result.known('game_version','inventory'))
            for changed in (dict(signature='changed'),dict(node='1-2')):
                original=dict(session['collection']['units']['bench:1'])
                session['collection']['units']['bench:1'].update(changed)
                self.assertFalse(collected_snapshot(state,session,0,'current').roster_complete)
                session['collection']['units']['bench:1']=original
            session['collection']['input_epoch']=1
            self.assertFalse(collected_snapshot(state,session,0,'current').roster_complete)


class OwnedProfileTests(unittest.TestCase):
    def scene(self, count=2):
        import cv2
        state=screen('character')
        state.image=np.zeros((1440,2560,3),dtype=np.uint8)
        state.tokens=[t for t in state.tokens if not t.within((.775,.19,.91,.235))]
        state.tokens.append(Token('银狼Lv.999',.99,(.778,.20,.85,.227)))
        for index in range(count):
            x=round((.85+(index-(count-1)/2)*.010)*2560)
            y=round(.16*1440)
            points=np.array([(x,y-11),(x+3,y-3),(x+11,y),(x+3,y+3),
                             (x,y+11),(x-3,y+3),(x-11,y),(x-3,y-3)],dtype=np.int32)
            cv2.fillPoly(state.image,[points],(80,190,250))
        return state

    def test_star_grammar_supports_one_to_four_and_missing_icons_stop(self):
        for count in range(1,5):
            self.assertEqual(character_stars(self.scene(count)),count)
        with self.assertRaises(AutomationError):
            character_stars(self.scene(0))

    def test_tier_is_not_star_or_sale_refund_and_full_name_is_preserved(self):
        state=self.scene(2)
        state.tokens.append(Token('3',.99,TIER_FIELD))
        state.tokens.append(Token('+9',.99,(.85,.83,.89,.86)))
        with patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3):
            unit=owned_profile(state,dict(zone='bench',slot=4,node='1-1'))
        self.assertEqual((unit.name,unit.star,unit.tier),('银狼Lv.999',2,3))
        self.assertEqual(unit.equipment,())
        with self.assertRaises(AutomationError):
            owned_profile(state,dict(zone='bench',slot=4,node='1-2'))
        state.tokens=[t for t in state.tokens if t.box != TIER_FIELD]
        with self.assertRaises(AutomationError):
            owned_profile(state,dict(zone='bench',slot=4,node='1-1'))

    def test_local_tier_reads_must_agree_and_never_replace_existing_tier(self):
        from unittest.mock import Mock
        state=self.scene()
        reader=Mock()
        reader.read_number.side_effect=[Token('2',.99,(0,0,1,1)),Token('2',.99,(0,0,1,1))]
        result=supplement_character_tier(state,reader)
        self.assertTrue(any(t.text=='2' and t.box==TIER_FIELD for t in result.tokens))
        reader.reset_mock()
        supplement_character_tier(result,reader)
        reader.read_number.assert_not_called()
        for a,b in (('2','3'),('6','6')):
            reader.read_number.side_effect=[Token(a,.99,(0,0,1,1)),Token(b,.99,(0,0,1,1))]
            self.assertIs(supplement_character_tier(state,reader),state)


if __name__ == '__main__':
    unittest.main()
