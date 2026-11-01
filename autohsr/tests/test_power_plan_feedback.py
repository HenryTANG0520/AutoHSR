import copy
import unittest

from autohsr.power_plan_ui import goals_pending,progress_rows,result_text
from autohsr.weekly_feedback import currency_weekly_caption,outcome_caption


def receipt(**changes):
    data=dict(status='success',report_saved=True,power_plan=dict(items=[dict(category='calyx_golden',target='回忆之蕾',location='城郊雪原',count=8)],
        before=[2],done=[4],goal_complete=False,run_status='complete'))
    data.update(changes);return data


class PowerPlanFeedbackTests(unittest.TestCase):
    def test_resource_limited_run_keeps_remaining_goal_distinct(self):
        value=receipt();before=copy.deepcopy(value)
        self.assertIn('本次已结束',result_text(value));self.assertIn('剩余目标 2 次',result_text(value))
        self.assertNotIn('目标已完成',result_text(value));self.assertTrue(goals_pending(value));self.assertEqual(before,value)

    def test_original_daily_and_echo_week_are_explicit(self):
        value=receipt();value['power_plan']['weekly_echo']=dict(week='2026-10-26',due=True,state='limited',completed=1)
        text=result_text(value,reused=True)
        for part in ('原日常体力计划','原周 2026-10-26','本次预算不足','本次 1 次'):self.assertIn(part,text)
        self.assertNotIn('周额度已核实用尽',text)

    def test_zero_remaining_does_not_prove_echo_completion(self):
        value=receipt();value['power_plan'].update(goal_complete=True,before=[2],done=[6],weekly_echo=dict(week='2026-10-26',due=True,state='active',remaining=0,completed=0))
        self.assertIn('额度待核对',result_text(value));self.assertTrue(goals_pending(value))
        value['power_plan']['weekly_echo']['state']='complete'
        self.assertIn('周额度已核实用尽',result_text(value));self.assertFalse(goals_pending(value))

    def test_invalid_counts_are_not_displayed_as_zero_or_success(self):
        for changed in (dict(before=[True]),dict(done=[10]),dict(items=[]),dict(done=[None])):
            with self.subTest(changed=changed):
                value=receipt();value['power_plan'].update(changed)
                self.assertIn('次数待核对',result_text(value))

    def test_confirmed_goal_and_unsaved_parent_have_different_outcomes(self):
        value=receipt();value['power_plan'].update(done=[6],goal_complete=True)
        self.assertIn('目标已完成',result_text(value));self.assertFalse(goals_pending(value))
        value['report_saved']=False;self.assertIn('本次未完整结束',result_text(value))

    def test_per_item_progress_keeps_original_prior_and_current_counts(self):
        data=[dict(target='回忆之蕾',location='城郊雪原',count=8,before=2,done=4,remaining=2)]
        text=progress_rows(data)
        for part in ('目标 8 次','此前 2 次','本次 4 次','本目标剩余 2 次'):self.assertIn(part,text)
        data[0]['remaining']=0;self.assertEqual(progress_rows(data),'条目进度待核对')

    def test_ended_currency_matches_are_not_victories(self):
        report=dict(status='partial',report_saved=True,weekly_plan=dict(mode='currency_wars',status='defeated',
            maximum_runs=3,completed_runs=2,victories=1,defeats=1))
        text=currency_weekly_caption(report)
        self.assertIn('开发对局 2 局',text);self.assertIn('胜 1／负 1',text)
        self.assertIn('失败后已停止',text)
        self.assertEqual(outcome_caption(dict(victories=True,defeats=1),2),'')
        self.assertEqual(outcome_caption(dict(victories=2,defeats=1),2),'')


if __name__=='__main__':unittest.main()
