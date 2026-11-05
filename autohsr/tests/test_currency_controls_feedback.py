"""Pure native summary/event projections; no Runner, GUI or private IO."""
from copy import deepcopy
import unittest

from autohsr.currency_controls_feedback import progress, result


WEEK = '2026-11-02'


def loop_report(*, requested=3, total=2, losses=0, nested='active', parent='partial', until=False):
    return dict(operation='currency_wars_loop', status=parent, report_saved=True,
        currency_wars=dict(mode='standard_loop', requested_runs=requested, completed=total,
            settled_games=total, victories=total-losses, defeats=losses, status=nested,
            active=None, development_only=True, acceptance_runs=0,
            until_points=until, continue_after_defeat=False))


def goal(value, *, current=1000, period=True, checked=None, week=WEEK):
    data = value['currency_wars']
    data['until_points'] = True
    observation = dict(current=current, limit=18000, score_complete=current == 18000,
        period_verified=period, weekly_target_verified=current == 18000 and period,
        game_week=week, observed_at='not displayed')
    data['points_goal'] = dict(week=WEEK, observation=observation,
        checked_completed=data['completed'] if checked is None else checked,
        latest=dict(receipt='private receipt', report='private source'))
    data['rewards_verified'] = False
    return value


def points_report(*, current=9000, period=True, parent='success'):
    return dict(operation='currency_wars_points', status=parent, report_saved=True,
        currency_wars=dict(schema=1, mode='weekly_points', points_verified=True,
            current=current, limit=18000, score_complete=current == 18000,
            weekly_target_verified=current == 18000 and period, period=dict(verified=period),
            game_week=WEEK, rewards_verified=False, completion_verified=False, match_started=False))


def reward_report(*, claimed=True, current=18000, parent='success'):
    intents = ['open_points_rewards', 'claim_weekly_rewards', 'dismiss_weekly_rewards', 'return_weekly_lobby'] if claimed else ['open_points_rewards', 'return_weekly_lobby']
    results = dict(open_points_rewards='points_rewards', claim_weekly_rewards='reward_overlay',
                   dismiss_weekly_rewards='points_rewards', return_weekly_lobby='lobby')
    return dict(operation='currency_wars_rewards', status=parent, report_saved=True,
        currency_wars=dict(schema=1, mode='weekly_rewards', status='complete', phase='returned',
            current=current, game_week=WEEK, rewards_verified=True, weekly_rewards_verified=current == 18000,
            claimed_now=claimed, completion_verified=False, match_started=False,
            actions=[dict(id=index, intent=intent, status='verified', result=results[intent]) for index,intent in enumerate(intents)]))


class CurrencyControlsFeedbackTests(unittest.TestCase):
    def test_development_ended_games_and_losses_are_separate_from_acceptance(self):
        value = loop_report(requested=2, total=2, losses=1, nested='complete')
        title, body = result(value)
        self.assertIn('指定开发局数已结算（含败局）', title)
        self.assertIn('已结束开发局 2 局 · 胜 1／负 1', body)
        self.assertIn('独立验收 0 局', body)
        self.assertIn('本循环未核实领奖', body)
        self.assertNotIn('胜 2', body)

    def test_zero_cap_means_until_stopped_and_retains_completed_counts(self):
        value = loop_report(requested=0, total=123456, losses=7, parent='stopped')
        title, body = result(value)
        self.assertIn('已停止', title)
        self.assertIn('0（直到停止）', body)
        self.assertIn('已结束开发局 123456 局', body)
        self.assertNotIn('指定开发局数已结算', title)

    def test_parent_failure_or_unsaved_summary_does_not_erase_ended_games(self):
        value = loop_report(requested=2, total=2, nested='complete', parent='failed')
        title, body = result(value)
        self.assertIn('指定开发局数已结算', title)
        self.assertIn('后续失败', title)
        self.assertIn('胜 2／负 0', body)
        value['report_saved'] = False;value['status'] = 'partial'
        title, body = result(value)
        self.assertIn('报告待核对', title)
        self.assertIn('已结束开发局 2 局', body)
        self.assertIn('汇总报告未完整保存', body)

    def test_target_can_complete_zero_games_without_claiming_rewards(self):
        value = goal(loop_report(total=0, nested='complete', parent='success'), current=18000)
        title, body = result(value)
        self.assertEqual(title, '本周积分目标已达标')
        self.assertIn('已结束开发局 0 局', body)
        self.assertIn('18000/18000', body)
        self.assertIn('本循环未核实领奖', body)

    def test_exhausted_expired_and_defeated_have_distinct_known_meanings(self):
        exhausted = goal(loop_report(total=3, nested='exhausted'), current=9000)
        self.assertEqual(result(exhausted)[0], '局数上限已用完')
        self.assertIn('没有追加开发局', result(exhausted)[1])
        expired = goal(loop_report(total=1, nested='expired'), current=9000)
        self.assertIn('原周积分目标已过期', result(expired)[0])
        self.assertIn('原目标没有自动迁移', result(expired)[1])
        defeated = loop_report(total=1, losses=1, nested='defeated')
        self.assertIn('败局结算后已停止', result(defeated)[0])
        self.assertIn('未算作胜利', result(defeated)[1])

    def test_stale_wrong_week_period_gap_or_conflicting_goal_does_not_complete(self):
        cases = [goal(loop_report(total=1, nested='complete'), current=18000, checked=0),
                 goal(loop_report(total=1, nested='complete'), current=18000, week='2026-10-26'),
                 goal(loop_report(total=1, nested='complete'), current=18000, period=False),
                 goal(loop_report(total=3, nested='exhausted'), current=18000)]
        for value in cases:
            with self.subTest(value=value):
                title, body = result(value)
                self.assertIn('待核对', title)
                self.assertNotIn('本周积分目标已达标', title)
                self.assertIn('已结束开发局', body)
        self.assertIn('最新结束局后的积分尚待核对', result(cases[0])[1])
        missing = loop_report(until=True, nested='expired')
        self.assertIn('待核对', result(missing)[0])
        self.assertNotIn('原周积分目标已过期', result(missing)[0])

    def test_unknown_current_game_is_not_added_to_verified_ended_count(self):
        value = loop_report(total=1, parent='failed')
        value['currency_wars']['active'] = {'private': 'active details'}
        title, body = result(value)
        self.assertIn('失败', title)
        self.assertIn('已结束开发局 1 局', body)
        self.assertIn('未计入已结束局数', body)
        self.assertNotIn('active details', body)

    def test_points_alone_never_prove_rewards_or_completed_matches(self):
        for current, period, expected in ((9000, True, '尚未达标'), (18000, False, '游戏周待核对'), (18000, True, '积分已达标')):
            value = points_report(current=current, period=period)
            title, body = result(value)
            self.assertIn(expected, title)
            self.assertIn(f'{current}/18000', body)
            self.assertIn('积分观察不证明奖励已领取', body)
            self.assertIn('不增加开发对局或独立验收计数', body)
            self.assertNotIn('积分领奖已核实', title)

    def test_points_true_flags_with_contradictory_score_or_wrong_operation_are_unknown(self):
        for change in ('boolean', 'limit', 'target', 'period', 'week', 'operation'):
            value = points_report(current=9000)
            if change == 'boolean':value['currency_wars']['current'] = True
            elif change == 'limit':value['currency_wars']['limit'] = 9000
            elif change == 'target':value['currency_wars']['weekly_target_verified'] = True
            elif change == 'period':value['currency_wars']['period'] = 'private OCR'
            elif change == 'week':value['currency_wars']['game_week'] = 'private week'
            else:value['operation'] = 'daily'
            with self.subTest(change=change):
                title, body = result(value)
                self.assertIn('待核对', title)
                self.assertNotIn('private', body)

    def test_reward_claimed_and_already_empty_both_require_verified_return(self):
        claimed = reward_report()
        self.assertEqual(result(claimed)[0], '积分领奖已核实')
        self.assertIn('本次领取与主页返回已核实', result(claimed)[1])
        empty = reward_report(claimed=False, current=9000)
        self.assertEqual(result(empty)[0], '积分领奖已核实')
        self.assertIn('当前无可领取积分奖励已核实', result(empty)[1])
        self.assertIn('周积分尚未满额', result(empty)[1])
        self.assertNotIn('本次领取与主页返回已核实', result(empty)[1])

    def test_unknown_unsaved_blocked_and_false_complete_cannot_claim_full_rewards(self):
        for change in ('saved', 'unknown', 'returned', 'flag', 'claimed', 'missing', 'weekly'):
            value = reward_report()
            if change == 'saved':value['report_saved'] = False
            elif change == 'unknown':value['currency_wars']['actions'][-1]['status'] = 'unknown'
            elif change == 'returned':value['currency_wars']['phase'] = 'panel_after_claim'
            elif change == 'flag':value['currency_wars']['rewards_verified'] = 1
            elif change == 'claimed':value['currency_wars']['claimed_now'] = False
            elif change == 'missing':value['currency_wars']['actions'] = []
            else:value['currency_wars']['weekly_rewards_verified'] = False
            with self.subTest(change=change):
                title, body = result(value)
                self.assertIn('待核对', title)
                self.assertNotIn('本次领取与主页返回已核实', body)
        blocked = reward_report(parent='partial')
        blocked['currency_wars'].update(status='active', phase='blocked', rewards_verified=False,
            weekly_rewards_verified=False, claimed_now=False,
            actions=[dict(id=0, intent='open_points_rewards', status='verified', result='points_rewards'),
                     dict(id=1, intent='claim_weekly_rewards', status='verified', result='fuel_ticket_limit')])
        self.assertIn('助燃券满额', result(blocked)[0])
        self.assertIn('未清理或重发', result(blocked)[1])
        blocked['currency_wars']['actions'][-1]['status'] = 'unknown'
        self.assertIn('待核对', result(blocked)[0])
        self.assertNotIn('助燃券满额', result(blocked)[0])

    def test_explicit_verified_action_results_cannot_turn_a_limit_dialog_into_delivery(self):
        for index, wrong in ((0, 'lobby'), (1, 'fuel_ticket_limit'), (2, 'lobby'), (3, 'points_rewards')):
            value = reward_report()
            value['currency_wars']['actions'][index]['result'] = wrong
            with self.subTest(index=index, wrong=wrong):
                title, body = result(value)
                self.assertIn('待核对', title)
                self.assertNotIn('本次领取与主页返回已核实', body)
                if wrong == 'fuel_ticket_limit':self.assertNotIn('已记录本次到账展示', body)
        value = reward_report(parent='partial')
        value['currency_wars'].update(status='active', phase='blocked', rewards_verified=False,
            weekly_rewards_verified=False, claimed_now=False)
        value['currency_wars']['actions'] = value['currency_wars']['actions'][:2]
        self.assertIn('待核对', result(value)[0])
        self.assertNotIn('助燃券满额', result(value)[0])

    def test_later_reward_failure_or_stop_keeps_verified_receipt_separate(self):
        for status, expected in (('failed', '后续失败'), ('stopped', '后续已停止')):
            value = reward_report(parent=status)
            title, body = result(value)
            self.assertIn('积分领奖已核实', title)
            self.assertIn(expected, title)
            self.assertIn('本次领取与主页返回已核实', body)

    def test_native_progress_events_are_bounded_facts_not_raw_messages(self):
        self.assertIn('准备新局', progress(dict(type='currency_loop_phase', slot=1, requested_runs=3, resume=False)))
        self.assertIn('接续原局 · 直到停止', progress(dict(type='currency_loop_phase', slot=99, requested_runs=0, resume=True)))
        data = loop_report(total=2, losses=1)['currency_wars']
        self.assertIn('胜 1／负 1', progress(dict(type='currency_loop_progress', data=data)))
        self.assertIn('独立验收 0 局', progress(dict(type='currency_loop_progress', data=data)))
        self.assertEqual(progress(dict(type='currency_loop_points', message='secret path')), '正在核对本周积分与游戏周；积分奖励单独核实。')
        for event in (None, {}, dict(type='finished'), dict(type='currency_loop_phase', slot=True, requested_runs=1, resume=False),
                      dict(type='currency_loop_phase', slot=2, requested_runs=1, resume=True),
                      dict(type='currency_loop_phase', slot=1, requested_runs=1, resume='yes'),
                      dict(type='currency_loop_progress', data=dict(data, victories=3))):
            with self.subTest(event=event):self.assertIsNone(progress(event))

    def test_private_fields_are_never_echoed_and_input_reports_are_not_mutated(self):
        private = 'UID:123456789 account-fingerprint C:\\private\\report.json OCR-SECRET'
        for value in (loop_report(), goal(loop_report()), points_report(), reward_report()):
            value.update(error=private, safe_next=private, report_write_error=private, source=private,
                results=[dict(status='failed', detail=private)])
            value['currency_wars'].update(account_key=private, loop_id=private, loop_record=private,
                tokens=[private], actionpayload=private, initial=dict(evidence=private), reason=private)
            original = deepcopy(value)
            title, body = result(value)
            self.assertEqual(value, original)
            for text in ('123456789', 'fingerprint', 'private', 'OCR-SECRET', 'report.json'):
                self.assertNotIn(text, title + body)
        for value in (None, [], dict(status='success', currency_wars=reward_report()['currency_wars'])):
            self.assertIn('待核对', result(value)[0])
        missing = reward_report();missing.pop('status')
        self.assertIn('待核对', result(missing)[0])
        self.assertNotIn('本次领取与主页返回已核实', result(missing)[1])

    def test_inconsistent_loop_counts_do_not_invent_success_or_acceptance(self):
        for field, number in (('completed', True), ('victories', 99), ('defeats', -1), ('settled_games', 8), ('requested_runs', '0')):
            value = loop_report(requested=2, total=2, nested='complete', parent='success')
            value['currency_wars'][field] = number
            with self.subTest(field=field):
                title, body = result(value)
                self.assertIn('待核对', title)
                self.assertNotIn('指定开发局数已结算', title)
        value = loop_report(requested=2, total=2, nested='complete', parent='success')
        value['currency_wars']['acceptance_runs'] = 2
        self.assertIn('待核对', result(value)[0])
        self.assertNotIn('独立验收 2 局', result(value)[1])

    def test_count_only_completion_with_leftover_points_goal_keeps_counts_but_is_unverified(self):
        value = loop_report(requested=1, total=1, nested='complete', parent='success')
        value['currency_wars']['points_goal'] = {}
        title, body = result(value)
        self.assertIn('待核对', title)
        self.assertNotIn('指定开发局数已结算', title)
        self.assertIn('已结束开发局 1 局 · 胜 1／负 0', body)


if __name__ == '__main__':
    unittest.main()
