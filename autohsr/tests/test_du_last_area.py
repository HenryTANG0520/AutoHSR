"""Final-route modal regressions from a masked native capture."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow, classify_page
from autohsr.models import AutomationError, FocusLost, InputInterrupted, RunReport, Scene, Token, normalize
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

    def interrupted_confirmation(self, *, during_wait=False):
        page=self.fixture()
        warnings=[Scene(page.tokens,page.image) for _ in range(2 if during_wait else 1)]
        done=Scene([Token('战斗失败',.99,(.45,.21,.55,.26))])
        pages=[page,*warnings,done]
        runner=SimpleNamespace(settings=Settings(),report=RunReport(operation='differential_universe'),
                               input_epoch=0,inactive_duration=0,checkpoint=Mock(),log=Mock(),wait_for_focus=Mock())
        window,vision=Mock(),Mock()
        window.capture.side_effect=[(page.image,page.geometry) for page in pages]
        vision.read.side_effect=pages
        ctx=Context(runner,window,vision)
        ctx.evidence=Mock(return_value='fixture.png')
        ctx.sleep=Mock()
        flow=DifferentialUniverseWorkflow(ctx,1)
        return flow,ctx.snapshot(),window

    def test_interrupted_feedback_does_not_send_final_area_confirmation_again(self):
        for during in ('after_click','after_warning_observed'):
            with self.subTest(during=during):
                flow,page,window=self.interrupted_confirmation(during_wait=during=='after_warning_observed')
                interrupted=InputInterrupted('test interruption during confirmation feedback')
                if during=='after_click':
                    flow.ctx.sleep.side_effect=[interrupted,None]
                else:
                    # After the first confirmation Context has already read
                    # another warning frame, so the outer loop has to recapture it.
                    flow.ctx.wait=Mock(side_effect=interrupted)
                with TemporaryDirectory() as folder:
                    flow.report['run_dir']=folder
                    with self.assertRaises(AutomationError) as failure:
                        flow._progress_run(page,'last_area_confirm')
                    self.assertEqual(window.click.call_count,1)
                    self.assertIn('未重复点击',str(failure.exception))
                    ledger=json.loads((Path(folder)/'differential-universe-ledger.json').read_text('utf8'))
                    self.assertEqual(ledger['actions'][0]['feedback_status'],'unverified')
                    self.assertEqual(ledger['actions'][0]['intent'],'last_area_confirm')
                    self.assertEqual(len(ledger['actions']),2)

    def test_epoch_change_before_input_refreshes_warning_then_sends_once(self):
        flow,page,window=self.interrupted_confirmation()
        runner=flow.ctx.runner

        def checkpoint():
            if runner.input_epoch==0 and flow.report['actions']:
                runner.input_epoch+=1

        runner.checkpoint.side_effect=checkpoint
        with self.assertRaisesRegex(AutomationError,'差分宇宙已失败'):
            flow._progress_run(page,'last_area_confirm')
        window.click.assert_called_once()
        requests=[action for action in flow.report['actions'] if action.get('intent')=='last_area_confirm']
        self.assertEqual([action['status'] for action in requests],['not_sent','sent'])
        self.assertEqual(flow.ctx.scene_epoch,1)

    def test_focus_loss_at_window_boundary_does_not_replay_final_area_confirmation(self):
        flow,page,window=self.interrupted_confirmation()
        window.click.side_effect=[FocusLost('test focus loss'),None]
        with self.assertRaisesRegex(AutomationError,'反馈待核对，未重复点击'):
            flow._progress_run(page,'last_area_confirm')
        window.click.assert_called_once()
        flow.ctx.runner.wait_for_focus.assert_called_once_with(window)
        self.assertEqual(flow.report['actions'][0]['feedback_status'],'unverified')
