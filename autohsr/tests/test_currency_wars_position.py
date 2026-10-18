from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import Mock

import cv2
import numpy as np

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_position import misplaced_backend,position_plan,correct_position
from autohsr.currency_wars_deployment import _crop
from autohsr.currency_wars_sale import field_roi
from autohsr.currency_wars_roster import CharacterProfile
from autohsr.models import AutomationError,Token
from autohsr.tests.test_currency_wars_node import prepared
from autohsr.tests.test_currency_wars_roster import panel
from autohsr.tests import test_currency_wars_node as helpers


def board():
    s=prepared()
    s.tokens=[t for t in s.tokens if not t.within((.84,.83,1,.95))]
    s.tokens.append(Token('3',.99,(.852,.84,.867,.86)))
    s.image=np.zeros((1440,2560,3),dtype=np.uint8)
    patch=cv2.imread(str(Path(__file__).parent/'fixtures/currency_layout/misplaced_backend.png'))
    s.image[430:1000,680:1860]=patch
    return s


class PositionTests(TestCase):
    def test_correction_inspects_source_and_destination_identity_and_journals_once(self):
        first=board()
        field=misplaced_backend(first)
        profile=CharacterProfile('灵砂',('front',),field.node)
        target=position_plan(first,field,profile)
        after=board()
        face=_crop(first.image,field_roi(field)).copy()
        _crop(after.image,field_roi(field))[:]=0
        _crop(after.image,field_roi(target))[:]=face
        identity=panel()
        identity.tokens=[Token('灵砂' if t.text=='阮·梅' else '前台' if t.text in ('后台','日后台') else t.text,t.score,t.box) for t in identity.tokens]
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[identity,first,after,identity,after])
            c.last_scene=first
            data=dict(actions=[])
            c.currency_open_field=Mock(side_effect=lambda *a:self.assertEqual(data['actions'][-1]['status'],'pending'))
            c.currency_close_character=Mock()
            c.currency_correct_position=Mock()
            self.assertTrue(correct_position(c,first,field,data,lambda:None))
            c.currency_correct_position.assert_called_once()
            self.assertEqual(c.currency_open_field.call_count,2)
            self.assertTrue(all(a['status']=='verified' for a in data['actions']))

    def test_real_red_badge_only_triggers_identity_check_and_front_empty_slot(self):
        s=board()
        field=misplaced_backend(s)
        self.assertEqual((field.zone,field.slot),('back',1))
        profile=CharacterProfile('灵砂',('front',),field.node)
        target=position_plan(s,field,profile)
        self.assertEqual((target.zone,target.slot),('front',1))
        for zones,node in [(('back',),field.node),(('front','back'),field.node),(('front',),'2-1')]:
            with self.assertRaises(AutomationError):
                position_plan(s,field,CharacterProfile('灵砂',zones,node))
        s.image[810:835,850:890]=0
        self.assertIsNone(misplaced_backend(s))

    def test_occupied_target_and_stale_source_are_never_used(self):
        s=board()
        field=misplaced_backend(s)
        profile=CharacterProfile('灵砂',('front',),field.node)
        noise=np.random.default_rng(8).integers(0,255,(116,128,3),dtype=np.uint8)
        for x in (990,1180,1370,1560):
            s.image[475:591,x-64:x+64]=noise
        with self.assertRaises(AutomationError):
            position_plan(s,field,profile)
        s=board()
        s.image[835:950,730:880]=0
        with self.assertRaises(AutomationError):
            position_plan(s,field,profile)

    def test_readonly_rejects_correction_and_flow_uses_held_drag_and_blank_band(self):
        for operation in ('currency_wars','daily'):
            c=Context(Runner(Settings(),operation=operation),Mock(),Mock())
            s=board()
            field=misplaced_backend(s)
            c.last_scene=s
            with self.assertRaises(AutomationError):
                c.currency_correct_position(s,field,CharacterProfile('灵砂',('front',),field.node))
            c.window.drag.assert_not_called()
        c=Context(Runner(Settings(),operation='currency_wars_flow_test'),Mock(),Mock())
        s=board()
        field=misplaced_backend(s)
        c.last_scene=s
        c.sleep=Mock()
        c.currency_correct_position(s,field,CharacterProfile('灵砂',('front',),field.node))
        self.assertIsNone(c._currency_position_request)
        self.assertEqual(c.window.drag.call_args.kwargs['waypoints'],((field.point[0],.495),(990/2560,.495)))
        self.assertIsNone(c.last_scene)
