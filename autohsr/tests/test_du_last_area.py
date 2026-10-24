"""Final-route modal regressions from a masked native capture."""
import unittest
from unittest.mock import Mock

from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow, classify_page
from autohsr.models import AutomationError, RunReport, Scene, Token, normalize
from autohsr.policy import du_last_area_confirm, guard_differential_universe_click


class LastAreaTests(unittest.TestCase):
    @staticmethod
    def fixture():
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture('last_area_confirm')

    def test_native_warning_takes_priority_over_area_choice_wording(self):
        page=self.fixture()
        self.assertEqual(classify_page(page),'last_area_confirm')
        confirm=du_last_area_confirm(page)
        self.assertIsNotNone(confirm)
        guard_differential_universe_click(page,confirm,intent='last_area_confirm')
        cancel=page.find('取消',exact=True)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,cancel,intent='last_area_confirm')

    def test_incomplete_warning_and_paid_modal_never_authorize_confirmation(self):
        page=self.fixture()
        target=du_last_area_confirm(page)
        for text in ('提示','取消','确认','本次为最后一次区域选择阶段'):
            with self.subTest(missing=text):
                partial=Scene([t for t in page.tokens if normalize(text) not in normalize(t.text)])
                self.assertIsNone(du_last_area_confirm(partial))
                with self.assertRaises(AutomationError):
                    guard_differential_universe_click(partial,target,intent='last_area_confirm')
        paid=Scene(page.tokens+[Token('消耗星琼',.99,(.40,.55,.60,.57))])
        self.assertIsNone(du_last_area_confirm(paid))
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(paid,target,intent='last_area_confirm')

    def test_wrapped_body_still_requires_the_entire_same_warning(self):
        page=self.fixture()
        body=page.find('本次为最后一次区域选择阶段')
        parts=['本次为最后一次区域选择阶段，','之后将无法再进入储蓄间，是否继续？']
        wrapped=Scene([t for t in page.tokens if t!=body]+[
            Token(parts[0],.99,(.27,.44,.73,.48)),Token(parts[1],.99,(.27,.49,.73,.53))])
        self.assertIsNotNone(du_last_area_confirm(wrapped))

    def test_confirmation_is_sent_once_then_waits_for_actual_feedback(self):
        page=self.fixture()
        done=Scene([Token('选择下一站',.99,(.05,.04,.17,.08)),
                    Token('战斗',.99,(.50,.60,.60,.70))])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(return_value=(page,'last_area_confirm'))
        flow._observe=Mock(return_value='station_choice')
        flow._wait_known=Mock(side_effect=lambda p,k,*a:(p,k))
        ctx.wait.return_value=done
        self.assertEqual(flow._confirm_last_area(page),(done,'station_choice'))
        flow._click.assert_called_once_with(page,du_last_area_confirm(page),
            intent='last_area_confirm',label='last_area_confirmed')
        predicate=ctx.wait.call_args.args[0]
        self.assertFalse(predicate(page))
        self.assertTrue(predicate(done))
