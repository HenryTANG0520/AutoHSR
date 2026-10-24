"""Named adventure NPCs provide bearing, never implicit permission to press F."""
import unittest
from unittest.mock import patch, Mock
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow, classify_page
from autohsr.du_adventure import hanu_challenge, hanu_result_exit
from autohsr.models import RunReport
from autohsr.policy import guard_differential_universe_click
from autohsr.models import AutomationError, Scene, Token
from autohsr.du_navigation import event_targets
from autohsr.policy import du_named_field_interaction, guard_differential_universe_field_interact


class AdventureTests(unittest.TestCase):
    @staticmethod
    def fixture():
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture('adventure_hanu_field')

    def test_native_floating_npc_name_supplies_bearing_in_adventure_room(self):
        page=self.fixture()
        with patch('autohsr.du_detector.detect_cards',return_value=[]):
            targets=event_targets(page)
        self.assertEqual(len(targets),1)
        self.assertAlmostEqual(targets[0].center[0],page.find('哈努兄弟',exact=True).center[0])
        self.assertIsNone(du_named_field_interaction(page))
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,page.find('哈努兄弟',exact=True))

    def test_npc_name_without_adventure_header_never_becomes_a_target(self):
        page=self.fixture()
        changed=Scene([Token(t.text.replace('冒险','事件'),t.score,t.box) for t in page.tokens],page.image)
        with patch('autohsr.du_detector.detect_cards',return_value=[]):
            self.assertEqual(event_targets(changed),[])

    def test_npc_f_requires_the_separate_prompt_and_current_glyph(self):
        page=self.fixture()
        prompt=Token('开始挑战',.99,(.63,.54,.74,.59))
        ready=Scene(page.tokens+[prompt],page.image)
        with patch('autohsr.du_navigation.interaction_hint',return_value=True):
            self.assertEqual(du_named_field_interaction(ready),prompt)
            guard_differential_universe_field_interact(ready,prompt)
        with patch('autohsr.du_navigation.interaction_hint',return_value=False):
            self.assertIsNone(du_named_field_interaction(ready))
            with self.assertRaises(AutomationError):
                guard_differential_universe_field_interact(ready,prompt)

    def test_native_start_prompt_requires_both_adventure_and_named_npc(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        page=DuRuntimeTests.optional_device_fixture('adventure_hanu_prompt')
        target=du_named_field_interaction(page)
        self.assertIsNotNone(target)
        self.assertEqual(target.text,'开始挑战')
        guard_differential_universe_field_interact(page,target)
        for omitted in ('冒险','哈努兄弟'):
            partial=Scene([t for t in page.tokens if omitted not in t.text],page.image)
            with self.assertRaises(AutomationError):
                guard_differential_universe_field_interact(partial,target)

    @staticmethod
    def result_page():
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture('adventure_hanu_result')

    def test_result_exit_requires_the_full_mini_game_context(self):
        page=self.result_page()
        target=hanu_result_exit(page)
        self.assertEqual(classify_page(page),'adventure_result')
        guard_differential_universe_click(page,target,intent='adventure_result_exit')
        for token in page.tokens:
            changed=Scene([t for t in page.tokens if t!=token])
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(changed,target,intent='adventure_result_exit')

    def test_countdown_is_observed_without_repeating_f_or_sending_gameplay_input(self):
        countdown=Scene([Token('即将开拍',.99,(.45,.04,.55,.09))])
        self.assertTrue(hanu_challenge(countdown))
        self.assertEqual(classify_page(countdown),'adventure_challenge')
        result=self.result_page();done=self.fixture()
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='adventure_result')
        flow._click=Mock(return_value=(done,'field_adventure'))
        flow._wait_known=Mock(side_effect=lambda p,k,*a:(p,k))
        ctx.wait.return_value=result
        self.assertEqual(flow._finish_adventure(countdown,'adventure_challenge'),(done,'field_adventure'))
        condition=ctx.wait.call_args.args[0]
        self.assertFalse(condition(countdown));self.assertFalse(condition(Scene([])))
        self.assertTrue(condition(result))
        self.assertEqual(ctx.wait.call_args.kwargs['timeout'],150)
        flow._click.assert_called_once_with(result,hanu_result_exit(result),
            intent='adventure_result_exit',label='adventure_result_left')
        ctx.differential_universe_interact.assert_not_called()

    def test_native_countdown_and_score_hud_are_challenge_pages(self):
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        for phase in ('countdown','playing'):
            with self.subTest(phase=phase):
                page=DuRuntimeTests.optional_device_fixture('adventure_hanu_'+phase)
                self.assertEqual(classify_page(page),'adventure_challenge')
                self.assertIsNone(hanu_result_exit(page))

    def test_missing_result_times_out_without_any_exit_or_replay(self):
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.wait.side_effect=AutomationError('拍摄结束等待超时')
        flow=DifferentialUniverseWorkflow(ctx,1);flow._click=Mock()
        with self.assertRaisesRegex(AutomationError,'等待超时'):
            flow._finish_adventure(Scene([]),'adventure_challenge')
        flow._click.assert_not_called()
        ctx.differential_universe_interact.assert_not_called()
