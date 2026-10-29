import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autohsr.plan_runner import PlanRunner
from autohsr.tests.test_plan_feedback import report
from autohsr.tests.test_currency_wars_weekly_plan import Factory, runtime, settings, points
from autohsr.ux import plan_result
from autohsr.weekly_feedback import currency_weekly_caption, pending_currency_week


def currency_report(**changes):
    data = report()
    data['weekly_plan'].update(mode='currency_wars',status='complete',score_rewards_verified=True,
                               maximum_runs=3,completed_runs=0,message='本周货币战争积分及奖励已核实。')
    data.update(changes)
    return data


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


class WeeklyFeedbackTests(unittest.TestCase):
    def test_zero_matches_can_complete_points_and_rewards_without_claiming_three_wins(self):
        data = currency_report()
        label, text = plan_result(data)
        self.assertEqual(label,'周常积分及奖励完成')
        self.assertIn('积分及奖励已核实',text)
        self.assertIn('开发对局 0 局／上限 3 局',text)
        self.assertNotIn('3 局已完成',text)

    def test_parent_acceptance_and_saved_result_are_required(self):
        for change in ('parent_flag','unsaved','partial'):
            with self.subTest(change=change):
                data = currency_report()
                data['currency_wars'] = dict(score_rewards_verified=True)
                if change=='parent_flag':data['weekly_plan']['score_rewards_verified']=False
                elif change=='unsaved':data['report_saved']=False
                else:data['status']='partial'
                label,text=plan_result(data)
                self.assertEqual(label,'周常待核对')
                self.assertNotIn('积分及奖励已核实',text)

    def test_readonly_audit_preserves_original_completion_context(self):
        data=currency_report(currency_wars=dict(read_only_recovery=True,current_account_verified=False))
        label,text=plan_result(data)
        self.assertEqual(label,'原周常结果已补存')
        self.assertIn('原周常回执已核对',text)
        self.assertNotIn('积分及奖励已核实',text)

    def test_exhausted_uses_frozen_limit_and_keeps_daily_success(self):
        data=currency_report(status='partial',daily_verified=True,stamina_spent=120)
        data['weekly_plan'].update(status='exhausted',maximum_runs=1,completed_runs=1,score_rewards_verified=False)
        text=plan_result(data)[1]
        self.assertIn('原上限已用完',text)
        self.assertIn('1 局／上限 1 局',text)
        self.assertIn('实训奖励已核实',text)
        self.assertNotIn('积分及奖励已核实',text)

    def test_reused_daily_costs_rewards_and_exit_are_explicitly_original(self):
        data=currency_report(daily_verified=True,stamina_spent=120,budget_scope='original_daily_run',
                             results=[dict(task='close_game',status='ok')])
        data['weekly_plan']['daily_reused']=True
        original=copy.deepcopy(data)
        text=plan_result(data)[1]
        self.assertIn('沿用原日常结果',text)
        self.assertIn('原日常已确认 120 开拓力',text)
        self.assertIn('原日常实训奖励已核实',text)
        self.assertIn('原日常：游戏已退出',text)
        self.assertEqual(data,original)

    def test_invalid_counts_and_future_week_do_not_invent_progress(self):
        data=currency_report()
        data['weekly_plan'].update(completed_runs=True)
        self.assertNotIn('开发对局',currency_weekly_caption(data))
        data['weekly_plan']['status']='not_due'
        self.assertIsNone(currency_weekly_caption(data))

    def test_absent_and_corrupt_pointer_are_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'runs'
            self.assertIsNone(pending_currency_week(root));self.assertFalse(root.exists())
            root.mkdir();(root/'currency-loop-current.json').write_text('{}','utf-8')
            before=hashes(root)
            result=pending_currency_week(root)
            self.assertFalse(result['resume']);self.assertIn('待核对',result['caption'])
            self.assertEqual(before,hashes(root))

    def test_real_stopped_goal_is_offered_without_rewriting_index_or_any_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[0,0,18000]);owner=None
            def emit(event):
                if event['type']=='currency_loop_progress':owner.stop()
            owner=PlanRunner(settings(),emit,root=root/'runs',runner_factory=factory,now=points.NOW)
            with runtime(root):first=owner.run()
            self.assertEqual(first.status,'stopped',first.error)
            before=hashes(root)
            with patch('autohsr.currency_wars_weekly.ensure_index',side_effect=AssertionError('UI must not write')):
                result=pending_currency_week(root/'runs')
            self.assertTrue(result['resume']);self.assertEqual(result['maximum'],2);self.assertEqual(result['completed'],1)
            self.assertIn('沿用原日常报告',result['caption'])
            self.assertNotIn('account',result);self.assertEqual(before,hashes(root))

    def test_committed_completion_is_not_offered_as_another_run(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);factory=Factory(root,[18000,18000]);factory.reward_available=False
            child=PlanRunner(settings(),root=root/'runs',runner_factory=factory,now=points.NOW)
            with runtime(root):done=child.run()
            self.assertEqual(done.status,'success',done.error)
            before=hashes(root)
            self.assertIsNone(pending_currency_week(root/'runs'))
            self.assertEqual(before,hashes(root))


if __name__=='__main__':
    unittest.main()
