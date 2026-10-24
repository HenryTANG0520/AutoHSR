import unittest
from unittest.mock import Mock
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow,classify_page
from autohsr.du_strategy import curio_card_selected
from autohsr.models import AutomationError,RunReport,Scene,Token
from autohsr.policy import du_curio_discard_page,guard_differential_universe_click


class CurioDiscardTests(unittest.TestCase):
    @staticmethod
    def native():
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture('curio_discard_generic_prompt')

    def test_discard_heading_and_controls_outrank_incidental_blessing_text(self):
        page=self.native()
        self.assertTrue(du_curio_discard_page(page))
        self.assertEqual(classify_page(page),'curio_discard')
        for label in ('请舍弃奇物','丢弃'):
            changed=Scene([t for t in page.tokens if t.text!=label],page.image)
            self.assertFalse(du_curio_discard_page(changed))
            self.assertEqual(classify_page(changed),'unknown')

    def test_native_damaged_curio_is_preferred_and_both_guarded_actions_are_supported(self):
        page=self.native();ctx=Mock(settings=Settings(),report=RunReport())
        target=DifferentialUniverseWorkflow(ctx,1)._choice_target(page,'curio_discard')
        self.assertEqual(target.text,'降维骰子')
        guard_differential_universe_click(page,target,intent='curio_discard_select')
        button=page.find('丢弃',(.78,.85,.99,.96),exact=True)
        guard_differential_universe_click(page,button,intent='curio_discard_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,Token('不存在的奇物',.99,target.box),intent='curio_discard_select')

    def test_white_selection_border_belongs_only_to_the_current_card(self):
        page=self.native()
        for name,expected in (('智识火漆',True),('星际漂流鱼',False),('降维骰子',False)):
            target=page.find(name,(.14,.35,.87,.54),exact=True)
            self.assertEqual(curio_card_selected(page,target),expected)

    def test_failed_selection_does_not_discard_the_previously_selected_other_card(self):
        page=self.native();ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(return_value=(page,'curio_discard'))
        with self.assertRaisesRegex(AutomationError,'选中边框'):
            flow._progress_run(page,'curio_discard')
        self.assertEqual(flow._click.call_count,1)
        self.assertEqual(flow._click.call_args.kwargs['intent'],'curio_discard_select')
