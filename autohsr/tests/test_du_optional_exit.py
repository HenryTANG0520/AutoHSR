import unittest
from unittest.mock import Mock,patch
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.du_navigation import optional_device_prompt,random_gate
from autohsr.models import AutomationError,RunReport,Scene,Token
from autohsr.policy import guard_differential_universe_field_interact


class OptionalExitTests(unittest.TestCase):
    @staticmethod
    def native():
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture('forge_beside_awake_exit')

    def test_live_combat_forge_is_an_optional_device_before_it_has_been_opened(self):
        page=self.native()
        self.assertEqual(optional_device_prompt(page).text,'造物调试台')
        self.assertEqual(random_gate(page,fast=True).text,'差分宇宙随意门外观')

    def test_side_device_with_centred_awake_exit_keeps_heading_and_stops_when_its_prompt_leaves(self):
        page=self.native();clear=Scene([page.tokens[0]],page.image)
        ctx=Mock(settings=Settings(),report=RunReport());ctx.differential_universe_move.return_value=clear
        flow=DifferentialUniverseWorkflow(ctx,1);flow._field_cleared=True
        flow._observe=Mock(return_value='field_combat')
        self.assertEqual(flow._avoid_optional_device(page,'field_combat',optional_device_prompt(page)),(clear,'field_combat'))
        ctx.differential_universe_move.assert_called_once_with(page,'w',650)
        ctx.differential_universe_interact.assert_not_called()

    def test_still_in_range_side_device_has_only_two_short_forward_steps(self):
        page=self.native();ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_move.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1);flow._field_cleared=True
        flow._observe=Mock(return_value='field_combat')
        flow._avoid_optional_device(page,'field_combat',optional_device_prompt(page))
        self.assertEqual([c.args[1:] for c in ctx.differential_universe_move.call_args_list],[('w',650),('w',650)])

    def test_side_pass_requires_a_cleared_room_and_a_current_centred_awake_face(self):
        page=self.native();device=optional_device_prompt(page)
        for cleared,face in ((False,random_gate(page,fast=True)),
                             (True,Token('差分宇宙睡眼门',.95,(.47,.23,.53,.30))),
                             (True,Token('差分宇宙随意门外观',.95,(.70,.23,.76,.30)))):
            ctx=Mock(settings=Settings(),report=RunReport());ctx.differential_universe_move.return_value=page
            flow=DifferentialUniverseWorkflow(ctx,1);flow._field_cleared=cleared
            flow._observe=Mock(return_value='field_combat')
            with patch('autohsr.du_navigation.random_gate',return_value=face):
                flow._avoid_optional_device(page,'field_combat',device)
            self.assertEqual([c.args[1:] for c in ctx.differential_universe_move.call_args_list],
                             [('s',500),('a',1100),('w',1100)])

    def test_resumed_awake_exit_is_recognized_before_device_recovery_can_search_for_monsters(self):
        page=self.native();done=Scene([]);ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1,resume_active=True)
        flow._field_visual=Mock(return_value=(done,'station_choice'))
        self.assertEqual(flow._field_combat(page),(done,'station_choice'))
        self.assertTrue(flow._field_cleared)
        flow._field_visual.assert_called_once_with(page,prefer_enemy=False)
        ctx.differential_universe_motion.assert_not_called()

    def test_new_named_side_devices_can_be_passed_but_never_receive_implicit_f(self):
        page=self.native()
        for label in ('新的可选装置','另一台机器'):
            changed=Scene([Token(label,t.score,t.box) if t.text=='造物调试台' else t
                           for t in page.tokens],page.image)
            target=optional_device_prompt(changed)
            self.assertEqual(target.text,label)
            with self.assertRaises(AutomationError):
                guard_differential_universe_field_interact(changed,target)
            with patch('autohsr.du_navigation.random_gate',return_value=Token('差分宇宙睡眼门',.95,(.47,.23,.53,.30))):
                self.assertIsNone(optional_device_prompt(changed))
