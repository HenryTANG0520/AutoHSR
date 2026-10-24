import unittest
from unittest.mock import Mock,patch
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow,classify_page
from autohsr.du_navigation import optional_device_prompt
from autohsr.models import AutomationError,RunReport,Scene,Stopped,Token
from autohsr.policy import du_coin_counter_menu,guard_differential_universe_field_interact


class CoinCounterTests(unittest.TestCase):
    @staticmethod
    def fixture(name):
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture('coin_counter_'+name)

    def test_native_counter_f_prompt_allows_only_bounded_avoidance(self):
        for name in ('prompt','combat'):
            page=self.fixture(name)
            target=optional_device_prompt(page)
            self.assertIsNotNone(target)
            self.assertEqual(target.text,'乐园币柜台')
            with self.assertRaises(AutomationError):guard_differential_universe_field_interact(page,target)
            changed=Scene([t for t in page.tokens if '位面' not in t.text],page.image)
            self.assertIsNone(optional_device_prompt(changed))
            with patch('autohsr.du_navigation.interaction_hint',return_value=False):
                self.assertIsNone(optional_device_prompt(page))

    def test_native_menu_requires_both_trade_options(self):
        page=self.fixture('menu')
        self.assertTrue(du_coin_counter_menu(page))
        self.assertEqual(classify_page(page),'coin_counter')
        for label in ('乐园币柜台','购买乐园币','出售乐园币'):
            self.assertFalse(du_coin_counter_menu(Scene([t for t in page.tokens if t.text!=label],page.image)))

    def test_menu_close_uses_only_escape_and_rechecks_current_context(self):
        page=self.fixture('menu');ctx=Context.__new__(Context);ctx.window=Mock()
        def send(before,action,operation,**kwargs):
            self.assertIs(before,page);self.assertEqual(action,'coin_counter_close')
            kwargs['guard'](before)
            with self.assertRaises(AutomationError):kwargs['guard'](Scene([]))
            operation();return page
        ctx._du_observed_input=Mock(side_effect=send)
        ctx.differential_universe_close_coin_counter(page)
        ctx.window.key.assert_called_once_with('esc')
        ctx.window.click.assert_not_called()

    def test_workflow_accepts_the_counter_return_in_wealth_and_combat_without_trading(self):
        page=self.fixture('menu');field=self.fixture('prompt')
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.checkpoint.side_effect=[None,Stopped('menu handled')]
        ctx.differential_universe_close_coin_counter.return_value=field
        def wait(predicate,**kwargs):
            self.assertFalse(predicate(page));self.assertTrue(predicate(field))
            self.assertTrue(predicate(self.fixture('combat')));return field
        ctx.wait.side_effect=wait
        flow=DifferentialUniverseWorkflow(ctx,1);flow._observe=Mock(return_value='field_wealth')
        with self.assertRaises(Stopped):flow._progress_run(page,'coin_counter')
        ctx.differential_universe_close_coin_counter.assert_called_once_with(page)
        self.assertFalse(flow._forge_console_used)
        ctx.click.assert_not_called()

    def test_blocking_counter_takes_precedence_over_a_visible_enemy_attack_ring(self):
        from autohsr.du_navigation import verified_attack_reticle
        page=self.fixture('combat');done=Scene([Token('战斗回合',.99,(.4,.01,.5,.05))])
        self.assertIsNotNone(verified_attack_reticle(page))
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1);flow._combat_chest=Mock(return_value=None)
        flow._avoid_optional_device=Mock(return_value=(done,'battle'))
        self.assertEqual(flow._field_visual(page),(done,'battle'))
        flow._avoid_optional_device.assert_called_once_with(page,'field_combat',optional_device_prompt(page))
        ctx.differential_universe_interact.assert_not_called()
        ctx.differential_universe_attack.assert_not_called()

    def test_combat_entry_handles_the_blocker_before_any_scan_or_forward_probe(self):
        for fresh in (False,True):
            ctx=Mock(settings=Settings(),report=RunReport())
            flow=DifferentialUniverseWorkflow(ctx,1,resume_active=not fresh)
            page=self.fixture('combat');done=Scene([])
            flow._combat_chest=Mock(return_value=None)
            flow._field_visual=Mock(return_value=(done,'battle'))
            self.assertEqual(flow._field_combat(page,fresh_entry=fresh),(done,'battle'))
            self.assertFalse(flow._resume_field_needs_target)
            flow._field_visual.assert_called_once_with(page,prefer_enemy=True)
            ctx.differential_universe_motion.assert_not_called()

    def test_optional_revival_device_requires_its_live_f_prompt_and_does_not_interact(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        page=DuRuntimeTests.optional_device_fixture('revival_device_blocks_combat')
        target=optional_device_prompt(page)
        self.assertEqual(target.text,'复活装置')
        with self.assertRaises(AutomationError):guard_differential_universe_field_interact(page,target)
        with patch('autohsr.du_navigation.interaction_hint',return_value=False):
            self.assertIsNone(optional_device_prompt(page))

    def test_counter_detour_uses_world_label_position_rather_than_fixed_right_f_caption(self):
        page=self.fixture('combat');device=optional_device_prompt(page)
        for world_x,side in ((.44,'d'),(.70,'a')):
            changed=Scene([Token(t.text,t.score,(world_x-.03,.38,world_x+.03,.41))
                           if t.text=='乐园币柜台' and t.within((.08,.10,.90,.49)) else t
                           for t in page.tokens],page.image)
            ctx=Mock(settings=Settings(),report=RunReport())
            ctx.differential_universe_move.return_value=changed
            flow=DifferentialUniverseWorkflow(ctx,1);flow._observe=Mock(return_value='field_combat')
            self.assertEqual(flow._avoid_optional_device(changed,'field_combat',device),(changed,'field_combat'))
            self.assertEqual([c.args[1:] for c in ctx.differential_universe_move.call_args_list],
                             [('s',500),(side,650),('w',700)])
            ctx.differential_universe_interact.assert_not_called()

    def test_enemy_bearing_has_priority_over_gate_anchor_after_a_device_detour(self):
        page=self.fixture('combat');clear=Scene([page.tokens[0]],page.image);done=Scene([])
        device=optional_device_prompt(page)
        ctx=Mock(settings=Settings(),report=RunReport());ctx.differential_universe_look.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1);flow._combat_chest=Mock(return_value=None)
        flow._avoid_optional_device=Mock(return_value=(clear,'field_combat'))
        flow._observe=Mock(return_value='battle')
        enemy=Token('Enemy',.9,(.64,.15,.78,.53));gate=Token('Target',.9,(.48,.2,.52,.5))
        with patch('autohsr.du_navigation.optional_device_prompt',side_effect=[device,None]), \
             patch('autohsr.du_navigation.interaction_hint',return_value=False), \
             patch('autohsr.du_navigation.random_gate',return_value=None), \
             patch('autohsr.du_navigation.navigation_targets',return_value=[gate]), \
             patch('autohsr.du_detector.detect_recovery_enemies',return_value=[enemy]):
            self.assertEqual(flow._field_visual(page),(done,'battle'))
        ctx.differential_universe_look.assert_called_once_with(clear,.12,0,220)
        ctx.differential_universe_motion.assert_not_called()

    def test_detour_stops_when_the_enemy_becomes_attackable_without_a_blocking_device(self):
        page=self.fixture('combat');device=optional_device_prompt(page)
        ready=Scene([t for t in page.tokens if t.text!='乐园币柜台'],page.image)
        ctx=Mock(settings=Settings(),report=RunReport());ctx.differential_universe_move.return_value=ready
        flow=DifferentialUniverseWorkflow(ctx,1);flow._observe=Mock(return_value='field_combat')
        self.assertEqual(flow._avoid_optional_device(page,'field_combat',device),(ready,'field_combat'))
        ctx.differential_universe_move.assert_called_once_with(page,'s',500)
        ctx.differential_universe_attack.assert_not_called()
