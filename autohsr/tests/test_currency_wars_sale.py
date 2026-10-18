import tempfile
from unittest import TestCase
from unittest.mock import Mock

import numpy as np

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.currency_wars_roster import read_character,CharacterProfile
from autohsr.currency_wars_sale import duplicate_candidate,sale_target,sell_duplicate
from autohsr.models import AutomationError,InputInterrupted,Token
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_deployment import deployment_frame
from autohsr.tests.test_currency_wars_roster import panel


def duplicate():
    scene=deployment_frame()
    portrait=_crop(scene.image,bench_face(3)).copy()
    scene.image[830:830+portrait.shape[0],680:680+portrait.shape[1]]=portrait
    return scene


def sale_panel(scene):
    s=panel()
    s.image=scene.image.copy()
    return s


class SaleTests(TestCase):
    def test_overflow_sale_can_be_verified_when_waiting_reward_refills_the_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            first=duplicate()
            first.tokens += [Token('备战席已满，请出售角色或提升等级',.99,(.35,.48,.65,.51))]
            candidate,field=duplicate_candidate(first)
            after=duplicate()
            source=_crop(after.image,bench_face(3))
            source[:]=np.random.default_rng(123).integers(0,256,source.shape,dtype=np.uint8)
            after.tokens=[t for t in after.tokens if not t.within((.851,.829,.87,.868))]
            after.tokens += [Token('19',.99,(.852,.84,.867,.86))]
            c=helpers.NodeWorkflowTests().context(directory,[sale_panel(first),first,sale_panel(first),after])
            c.last_scene=first
            c.currency_open_field=Mock()
            c.currency_close_character=Mock()
            c.currency_open_sale_candidate=Mock()
            c.currency_sell_duplicate=Mock()
            data=dict(actions=[])
            self.assertTrue(sell_duplicate(c,first,candidate,field,data,lambda:None))
            c.currency_sell_duplicate.assert_called_once()
            self.assertFalse(data['actions'][-1]['source_empty'])
            self.assertTrue(data['actions'][-1]['overflow_reward_filled_slot'])

    def test_only_high_confidence_field_duplicates_are_candidates(self):
        scene=duplicate()
        candidate,field=duplicate_candidate(scene)
        self.assertEqual((candidate.slot,field.zone,field.slot),(3,'back',1))
        with self.assertRaises(AutomationError):
            duplicate_candidate(deployment_frame())

    def test_named_field_proof_price_and_both_portraits_required(self):
        scene=duplicate()
        candidate,field=duplicate_candidate(scene)
        s=sale_panel(scene)
        proof=read_character(s)
        self.assertEqual(sale_target(s,candidate,field,proof)[0],2)
        with self.assertRaises(AutomationError):
            sale_target(s,candidate,field,CharacterProfile('花火',('back',),'1-1'))
        _crop(s.image,bench_face(3))[:]=0
        with self.assertRaises(AutomationError):
            sale_target(s,candidate,field,proof)

    def test_inspect_both_then_sell_once_and_verify_gold_source_and_field(self):
        with tempfile.TemporaryDirectory() as directory:
            first=duplicate()
            candidate,field=duplicate_candidate(first)
            after=duplicate()
            _crop(after.image,bench_face(3))[:]=(80,35,25)
            after.tokens=[t for t in after.tokens if not t.within((.851,.829,.87,.868))]
            after.tokens += [Token('19',.99,(.852,.84,.867,.86))]
            c=helpers.NodeWorkflowTests().context(directory,[sale_panel(first),first,sale_panel(first),after])
            c.last_scene=first
            data=dict(actions=[])
            def pending(*args):
                self.assertEqual(data['actions'][-1]['status'],'pending')
            c.currency_open_field=Mock(side_effect=pending)
            c.currency_close_character=Mock(side_effect=pending)
            c.currency_open_sale_candidate=Mock(side_effect=pending)
            c.currency_sell_duplicate=Mock(side_effect=pending)
            self.assertTrue(sell_duplicate(c,first,candidate,field,data,lambda:None))
            c.currency_sell_duplicate.assert_called_once()
            self.assertTrue(data['actions'][-1]['source_empty'])
            self.assertEqual(data['actions'][-1]['gold_after'],19)

    def test_readonly_scope_and_interruption_prevent_sale(self):
        first=duplicate()
        candidate,field=duplicate_candidate(first)
        s=sale_panel(first)
        window=Mock()
        for operation in ('daily','currency_wars','currency_wars_deploy_test'):
            c=Context(Runner(Settings(),operation=operation),window,Mock())
            c.last_scene=s
            with self.assertRaises(AutomationError):
                c.currency_sell_duplicate(s,candidate,field,read_character(s))
        window.click.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[])
            c.last_scene=first
            c.currency_open_field=Mock(side_effect=InputInterrupted('paused'))
            c.currency_sell_duplicate=Mock()
            data=dict(actions=[])
            with self.assertRaises(InputInterrupted):
                sell_duplicate(c,first,candidate,field,data,lambda:None)
            self.assertEqual(data['actions'][0]['status'],'pending')
            c.currency_sell_duplicate.assert_not_called()
