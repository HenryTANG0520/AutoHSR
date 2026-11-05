"""Pure anonymous receipt presentation; no Runner, GUI, files or game IO."""
from copy import deepcopy
import math
import unittest

from autohsr.du_rewards_feedback import rewards_result


FREE = ['拟合等级', '稳态数组', '可能性画廊']


def report(*, use=False, state='success', receipt_state='complete'):
    return dict(operation='du_rewards', status=state, report_saved=True,
        du_rewards=dict(schema=1, operation='du_rewards', status=receipt_state,
            rewards_verified=receipt_state == 'complete', safe_to_restart=receipt_state in ('complete', 'partial', 'abort_before_input'),
            battle_started=False, use_cassettes=use, requested_categories=FREE + (['月下奇谭'] if use else []),
            skipped_optional_categories=[], remaining_categories=[], all_notifications_cleared=receipt_state == 'complete',
            actions=[], claims=[], obligation=None,
            cassettes=dict(initial_balance=None, limit=0, spent_verified=0)))


def add_claim(value, source='拟合等级', *, status='verified', balance=300):
    data = value['du_rewards']
    intent = {'拟合等级': 'du_reward_dot', '稳态数组': 'du_reward_claim',
              '可能性画廊': 'du_reward_gallery_claim', '月下奇谭': 'du_reward_unlock'}[source]
    action_id = len(data['actions'])
    data['actions'].append(dict(id=action_id, request=dict(intent=intent),
        status='verified' if status == 'verified' else 'unknown'))
    claim = dict(id=len(data['claims']), action_id=action_id, source=source, status=status)
    if source == '月下奇谭':
        claim.update(amount=100, balance_before=balance)
        if status == 'verified':claim['balance_after'] = balance - 100
    data['claims'].append(claim)
    if status != 'verified':data['obligation'] = deepcopy(claim)
    return claim


class DURewardsFeedbackTests(unittest.TestCase):
    def test_default_free_scope_success_does_not_imply_all_visible_dots_cleared(self):
        value = report()
        value['du_rewards'].update(skipped_optional_categories=['月下奇谭'], all_notifications_cleared=False)
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖已核实')
        self.assertIn('本次请求：拟合等级、稳态数组、可能性画廊', body)
        self.assertIn('本次请求范围已核实', body)
        self.assertIn('未请求，已跳过：月下奇谭', body)
        self.assertIn('未确认全部可见红点清空', body)
        self.assertNotIn('全部可见红点已核实清空', body)
        self.assertIn('本次未授权使用月下卡带', body)

    def test_all_visible_clear_is_a_separate_explicit_verified_fact(self):
        title, body = rewards_result(report())
        self.assertEqual(title, '差分领奖已核实')
        self.assertIn('全部可见红点已核实清空', body)
        partial = report(state='partial', receipt_state='partial')
        partial['du_rewards']['remaining_categories'] = ['未绑定红点']
        self.assertEqual(rewards_result(partial)[0], '差分领奖未完成')
        self.assertIn('尚待核实：未绑定红点', rewards_result(partial)[1])

    def test_explicit_cassettes_show_frozen_limit_and_verified_consumption(self):
        value = report(use=True)
        add_claim(value, '月下奇谭')
        value['du_rewards']['cassettes'] = dict(initial_balance=350, limit=300, spent_verified=100)
        # The first debit is bound to the exact initial balance, including remainder.
        value['du_rewards']['claims'][0].update(balance_before=350, balance_after=250)
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖已核实')
        self.assertIn('可能性画廊、月下奇谭', body)
        self.assertIn('冻结额度 300，已核实消耗 100', body)
        self.assertNotIn('350', body)
        self.assertIn('已核实领取 1 项', body)

    def test_large_current_balance_keeps_exact_frozen_budget_without_a_new_numeric_cap(self):
        value = report(use=True)
        add_claim(value, '月下奇谭', balance=100000050)
        value['du_rewards']['cassettes'] = dict(initial_balance=100000050, limit=100000000, spent_verified=100)
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖已核实')
        self.assertIn('冻结额度 100000000，已核实消耗 100', body)

    def test_parent_failure_preserves_already_verified_requested_scope_and_claims(self):
        value = report(state='failed')
        add_claim(value)
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖失败')
        self.assertIn('本次请求范围已核实', body)
        self.assertIn('已核实领取 1 项', body)
        self.assertIn('后续处理失败，已核实结果保留', body)

    def test_stopped_unknown_payment_keeps_verified_cost_and_exact_pending_obligation_separate(self):
        value = report(use=True, state='stopped', receipt_state='unknown')
        add_claim(value, '月下奇谭', balance=300)
        add_claim(value, '月下奇谭', status='received', balance=200)
        value['du_rewards']['cassettes'] = dict(initial_balance=300, limit=300, spent_verified=100)
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖已停止')
        self.assertIn('已核实消耗 100', body)
        self.assertIn('另有 100 月下卡带待核对', body)
        self.assertIn('已核实领取 1 项', body)
        self.assertNotIn('已核实消耗 200', body)
        self.assertNotIn('本次请求范围已核实', body)

    def test_safe_partial_keeps_claims_and_remaining_requested_category(self):
        value = report(use=True, state='partial', receipt_state='partial')
        add_claim(value, '拟合等级')
        value['du_rewards'].update(remaining_categories=['月下奇谭'],
            cassettes=dict(initial_balance=0, limit=0, spent_verified=0))
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖未完成')
        self.assertIn('已核实领取 1 项', body)
        self.assertIn('尚待核实：月下奇谭', body)
        self.assertIn('冻结额度 0，已核实消耗 0', body)

    def test_initial_abort_failure_is_distinct_from_a_stopped_or_unknown_run(self):
        value = report(state='failed', receipt_state='abort_before_input')
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖失败')
        self.assertIn('尚未提交输入', body)
        self.assertNotIn('本次请求范围已核实', body)
        value['status'] = 'stopped'
        self.assertEqual(rewards_result(value)[0], '差分领奖已停止')
        value['status'] = 'partial';value['du_rewards'].update(status='unknown', safe_to_restart=False)
        self.assertEqual(rewards_result(value)[0], '差分领奖待核对')

    def test_a_pending_claim_persisted_before_its_input_is_not_reported_as_spent(self):
        value = report(use=True, state='partial', receipt_state='unknown')
        data = value['du_rewards']
        pending = dict(id=0, action_id=0, source='月下奇谭', status='pending', amount=100, balance_before=300)
        data.update(claims=[pending], obligation=deepcopy(pending),
            cassettes=dict(initial_balance=300, limit=300, spent_verified=0))
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖待核对')
        self.assertIn('已核实消耗 0', body)
        self.assertIn('另有 100 月下卡带待核对', body)

    def test_old_du_counts_or_unrelated_success_cannot_complete_new_rewards(self):
        for value in (None, [], {}, dict(status='success', report_saved=True,
                differential_universe=dict(completed_runs=10, requested_runs=10,
                    reward_collection=dict(status='complete')), weekly_plan=dict(score_rewards_verified=True))):
            with self.subTest(value=value):
                title, body = rewards_result(value)
                self.assertEqual(title, '差分领奖待核对')
                self.assertNotIn('本次请求范围已核实', body)
        missing = report();missing.pop('status')
        self.assertEqual(rewards_result(missing)[0], '差分领奖待核对')
        self.assertNotIn('本次请求范围已核实', rewards_result(missing)[1])
        for operation in ('differential_universe', 'daily', 'task_workflow', None):
            wrong = report();wrong['operation'] = operation
            with self.subTest(operation=operation):
                self.assertEqual(rewards_result(wrong)[0], '差分领奖待核对')
                self.assertNotIn('本次请求范围已核实', rewards_result(wrong)[1])

    def test_missing_corrupt_contradictory_and_untyped_fields_remain_unverified(self):
        changes = [lambda d: d.pop('requested_categories'),
            lambda d: d.update(requested_categories=FREE + ['拟合等级']),
            lambda d: d.update(rewards_verified=1), lambda d: d.update(schema=True),
            lambda d: d.update(battle_started=True), lambda d: d.update(remaining_categories=['拟合等级']),
            lambda d: d.update(skipped_optional_categories=['月下奇谭']),
            lambda d: d.update(obligation={'private': 'not a claim'}),
            lambda d: d.update(actions='untrusted'), lambda d: d.update(use_cassettes='yes')]
        for change in changes:
            value = report();change(value['du_rewards'])
            with self.subTest(change=change):
                title, body = rewards_result(value)
                self.assertEqual(title, '差分领奖待核对')
                self.assertNotIn('本次请求范围已核实', body)

    def test_untrusted_numbers_and_claim_coverage_cannot_create_completed_costs(self):
        for number in (True, -100, 100.0, math.inf, '100', 100000000):
            value = report(use=True);value['du_rewards']['cassettes']['spent_verified'] = number
            with self.subTest(number=number):
                title, body = rewards_result(value)
                self.assertEqual(title, '差分领奖待核对')
                self.assertNotIn(str(number), body)
        value = report(use=True);add_claim(value, '月下奇谭')
        value['du_rewards']['cassettes'] = dict(initial_balance=300, limit=300, spent_verified=100)
        value['du_rewards']['claims'] = []
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖待核对')
        self.assertNotIn('已核实消耗 100', body)

    def test_private_fields_and_unrecognized_categories_never_escape_or_mutate_the_report(self):
        private = 'UID:123456789 secret-fingerprint C:\\private\\report.json OCR-SECRET'
        value = report()
        value.update(error=private, safe_next=private, source=private, input_error_field=private,
            report_write_error=private, results=[dict(status='failed', detail=private)])
        value['du_rewards'].update(account_key=private, journal=private, failure_type=private,
            observations=[dict(evidence=private)], extra=private)
        add_claim(value)
        value['du_rewards']['actions'][0]['request'].update(target=dict(text=private), payload=private)
        original = deepcopy(value)
        title, body = rewards_result(value)
        self.assertEqual(value, original)
        self.assertEqual(title, '差分领奖已核实')
        self.assertNotIn(private, body)
        for text in ('123456789', 'fingerprint', 'private', 'OCR-SECRET', 'report.json'):
            self.assertNotIn(text, title + body)
        for field in ('requested_categories', 'remaining_categories', 'skipped_optional_categories'):
            changed = deepcopy(value);changed['du_rewards'][field] = [private]
            title, body = rewards_result(changed)
            self.assertEqual(title, '差分领奖待核对')
            self.assertNotIn(private, body)

    def test_unsaved_report_does_not_promote_valid_receipt_or_expose_raw_error(self):
        value = report();value.update(report_saved=False, report_write_error='secret path')
        title, body = rewards_result(value)
        self.assertEqual(title, '差分领奖待核对')
        self.assertIn('报告未完整保存', body)
        self.assertNotIn('本次请求范围已核实', body)
        self.assertNotIn('secret path', body)
        value['status'] = 'stopped'
        self.assertEqual(rewards_result(value)[0], '差分领奖已停止')


if __name__ == '__main__':
    unittest.main()
