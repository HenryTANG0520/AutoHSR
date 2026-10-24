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
        page=self.fixture('prompt')
        target=optional_device_prompt(page)
        self.assertIsNotNone(target)
        self.assertEqual(target.text,'乐园币柜台')
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,target)
        changed=Scene([Token(t.text.replace('财富','事件'),t.score,t.box) for t in page.tokens],page.image)
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

    def test_workflow_waits_for_wealth_field_after_closing_without_trading(self):
        page=self.fixture('menu');field=self.fixture('prompt')
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.checkpoint.side_effect=[None,Stopped('menu handled')]
        ctx.differential_universe_close_coin_counter.return_value=field
        def wait(predicate,**kwargs):
            self.assertFalse(predicate(page));self.assertTrue(predicate(field));return field
        ctx.wait.side_effect=wait
        flow=DifferentialUniverseWorkflow(ctx,1);flow._observe=Mock(return_value='field_wealth')
        with self.assertRaises(Stopped):flow._progress_run(page,'coin_counter')
        ctx.differential_universe_close_coin_counter.assert_called_once_with(page)
        self.assertFalse(flow._forge_console_used)
        ctx.click.assert_not_called()
