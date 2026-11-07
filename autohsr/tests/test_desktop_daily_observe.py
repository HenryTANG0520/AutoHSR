"""Anonymous daily observation projections and hidden desktop lifecycle checks."""

from contextlib import ExitStack
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import theme
from autohsr.daily_event_claim import ACTIVITY
from autohsr.daily_message_reply import P179_SELECTION, REPLY_CHOICE, REPLY_NODE
from autohsr.daily_observe import EVENT_CLAIM_OPERATION, MESSAGE_REPLY_OPERATION
from autohsr.desktop_daily_observe import (ACHIEVEMENT_CLAIM, build_daily_observation_panel, event_claim_result,
                                          message_reply_result, observation_result)
from autohsr.desktop_tools import ToolsShelf


_MARKER = 'private-uid-and-path'


def report(operation, value, *, status='success', saved=True):
    payload = dict(schema=1, private_screenshot=_MARKER)
    payload.update(value)
    return dict(operation=operation, report_saved=saved, status=status, error=_MARKER,
                run_dir=_MARKER, **{operation: payload})


def reward(mode='achievements', *, status='success', saved=True, **value):
    return report('daily_reward_observe', dict(mode=mode, **value), status=status, saved=saved)


def messages(*, status='success', **overrides):
    value = dict(phone_entry='observed', message_page='unknown', unread_status='unknown', reward_status='unknown',
                 input_sent=False, account_verified=True, captures=2)
    value.update(overrides)
    return report('daily_message_observe', value, status=status)


def event(*, status='success', **overrides):
    value = dict(client_version='4.6.0', page='gift_of_odyssey', page_verified=True, account_verified=True,
                 claimable_state='available', claimable_days=[2], claimed_days=[1], unknown_days=[3, 4, 5, 6, 7])
    value.update(overrides)
    return report('daily_event_observe', value, status=status)


def screen(*, status='success', saved=True, **overrides):
    value = dict(page='guide', page_verified=True, account_verified=True, input_sent=False)
    value.update(overrides)
    return report('screen_test', value, status=status, saved=saved)


def achievement_claim(*, status='success', saved=True, **overrides):
    value = dict(bulk_input='sent', confirm_input='sent', account_verified=True, receipt_total=20,
                 overlay_quantity=20, overview_return_verified=True, overview_controls_cleared=True,
                 jade_balance_before=100, jade_balance_after=120, jade_balance_delta=20, jade_attributed=None)
    return report(ACHIEVEMENT_CLAIM, value | overrides, status=status, saved=saved)


def message_reply(selection=P179_SELECTION, *, status='success', saved=True, **overrides):
    value = dict(node=selection[0], choice=selection[1], input_status='sent', feedback_status='confirmed',
                 ledger_status='confirmed')
    return report(MESSAGE_REPLY_OPERATION, value | overrides, status=status, saved=saved)


def event_claim(*, status='partial', saved=True, **overrides):
    value = dict(activity=ACTIVITY, day=4, stage='return', state='pending', submission='sent',
                 popup='observed', quantity=1)
    return report(EVENT_CLAIM_OPERATION, value | overrides, status=status, saved=saved)


class DailyObservationReceiptTests(unittest.TestCase):
    def test_scope_and_saved_receipt_binding(self):
        verified = reward(page_verified=True, entry_input='sent', destination_status='achievement_overview')
        self.assertEqual(observation_result('achievements', verified), ('成就总览已核实', '奖励状态待核对。'))
        for mode, value in (('support', verified), ('achievements', dict(verified, report_saved=1)),
                            ('messages', dict(messages(), operation='daily_reward_observe')),
                            ('messages', messages(mode='support')), ('messages', messages(schema=True)),
                            ('odyssey', event(page_verified=1))):
            with self.subTest(mode=mode):
                self.assertEqual(observation_result(mode, value)[0], '结果待核对')
        stopped = reward('support', status='stopped', page_verified=False)
        self.assertEqual(observation_result('support', stopped)[0], '已停止')
        self.assertEqual(observation_result('support', dict(stopped, status='failed'))[0], '核对未完成')

    def test_navigation_title_and_more_receipt_do_not_verify_destination(self):
        more = dict(entry_input='sent', destination_status='more_menu_verified')
        candidate = dict(entry_input='sent', destination_status='support_title_only')
        partial = reward('support', status='partial', page_verified=False, destination_status='support_title_only',
                         steps=dict(open_more=more, open_support=candidate))
        title, detail = observation_result('support', partial)
        self.assertEqual(title, '漫游签证待核对')
        self.assertIn('记录漫游签证标题', detail)
        partial['daily_reward_observe']['steps']['open_support']['entry_input'] = 'not_sent'
        self.assertEqual(observation_result('support', partial)[1], '更多菜单已核实，签证页面与奖励状态待核对。')
        claimed = reward('support', page_verified=True, destination_status='support_title_only')
        self.assertEqual(observation_result('support', claimed)[0], '结果待核对')
        wrong_page = reward('support', page_verified=True, destination_status='achievement_overview')
        self.assertEqual(observation_result('support', wrong_page)[0], '结果待核对')
        title_only = reward(status='partial', page_verified=False, destination_status='achievement_title_only',
                            entry_input='sent')
        self.assertEqual(observation_result('achievements', title_only)[0], '成就总览待核对')

    def test_messages_show_only_proven_view_with_unread_and_reward_unknown(self):
        self.assertEqual(observation_result('messages', messages()),
                         ('手机短信入口已核实', '未读状态和奖励状态待核对。'))
        panel = messages(phone_entry='unknown', message_page='observed')
        self.assertEqual(observation_result('messages', panel)[0], '新消息通知面板已核实')
        for value in (messages(captures=1), messages(account_verified=False), messages(input_sent=True),
                      messages(message_page='observed'), messages(reward_status='available')):
            self.assertEqual(observation_result('messages', value)[0], '结果待核对')

    def test_support_collection_requires_both_navigation_receipts(self):
        destination = 'support_collection_overview'
        sources = [dict(capture_sequence=4), dict(capture_sequence=5)]
        more = dict(entry_input='sent', destination_status='more_menu_verified', after_frames=sources)
        after = [dict(capture_sequence=7, hint=destination), dict(capture_sequence=8, hint=destination)]
        visa = dict(entry_input='sent', destination_status=destination, before_frames=sources, after_frames=after)
        verified = reward('support', page_verified=True, entry_input='sent', destination_status=destination,
                          steps=dict(open_more=more, open_support=visa))
        self.assertEqual(observation_result('support', verified), ('漫游签证收集展示已核实', '支援奖励状态待核对。'))
        visa['before_frames'] = list(reversed(sources))
        self.assertEqual(observation_result('support', verified)[0], '结果待核对')
        visa['before_frames'] = sources
        visa['entry_input'] = 'unconfirmed'
        self.assertEqual(observation_result('support', verified)[0], '结果待核对')

    def test_open_support_receipt_keeps_visibility_claimability_and_credit_separate(self):
        destination = 'support_character_overview'
        idle = dict(entry_input='not_sent', destination_status='unknown', before_frames=[], after_frames=[])
        after = [dict(capture_sequence=1, hint=destination), dict(capture_sequence=2, hint=destination)]
        values = dict(page_verified=True, entry_input='not_sent', destination_status=destination,
                      steps=dict(open_more=dict(idle), open_support=dict(idle)), after_frames=after,
                      support_section='visible', claimable_state='unknown', claim_receipt_status='not_observed')
        verified = reward('support', **values)
        self.assertEqual(observation_result('support', verified),
                         ('漫游签证支援区已核实', '可领取状态待核对。到账状态待核对。'))
        for invalid in (dict(after_frames=after[:1]), dict(after_frames=after[::-1]),
                        dict(after_frames=[after[0], dict(after[1], hint='support_title_only')]),
                        dict(steps=dict(open_more=dict(idle, entry_input='sent'), open_support=idle)),
                        dict(steps=dict(open_more=dict(idle, intent=_MARKER), open_support=idle)),
                        dict(support_section='unknown'), dict(claimable_state='none'),
                        dict(claimable_state='available'), dict(claim_receipt_status='claimed')):
            with self.subTest(invalid=invalid):
                result = observation_result('support', reward('support', **(values | invalid)))
                self.assertEqual(result[0], '结果待核对')
                self.assertNotIn(_MARKER, repr(result))

    def test_message_receipt_shows_only_consistent_anonymous_panel_fields(self):
        state = dict(phone_entry='unknown', message_page='observed', unread_status='badge_visible',
                     conversation_status='selected', reply_status='options_visible', reply_options=3)
        self.assertEqual(observation_result('messages', messages(**state)),
                         ('新消息通知面板已核实', '看到未读标记，当前会话可见 3 个回复选项，奖励状态待核对。'))
        for bad in (dict(reply_options=True), dict(conversation_status='unknown'), dict(input_sent=True),
                    dict(phone_entry='observed', message_page='unknown'), dict(reply_status='not_visible')):
            self.assertEqual(observation_result('messages', messages(**(state | bad)))[0], '结果待核对')

    def test_odyssey_distinguishes_available_none_and_only_explicit_days(self):
        title, detail = observation_result('odyssey', event())
        self.assertEqual(title, '巡星之礼有可领奖励')
        self.assertEqual(detail.splitlines(), ['可领取：第 2 天', '已领取：第 1 天', '待核对：第 3、4、5、6、7 天'])
        none = event(claimable_state='none', claimable_days=[], claimed_days=list(range(1, 8)), unknown_days=[])
        self.assertEqual(observation_result('odyssey', none)[0], '巡星之礼暂无可领奖励')
        incomplete = event(status='partial', claimable_state='unknown', claimable_days=[], claimed_days=[3],
                           unknown_days=[1, 2, 4, 5, 6, 7])
        self.assertEqual(observation_result('odyssey', incomplete),
                         ('巡星之礼领取状态待核对', '已领取：第 3 天\n待核对：第 1、2、4、5、6、7 天'))
        phone = event(page='phone_entry', claimable_state='not_observed',
                      claimable_days=[], claimed_days=[], unknown_days=[])
        self.assertEqual(observation_result('odyssey', phone)[0], '旅情事记入口已核实')

    def test_odyssey_never_fills_missing_days_or_shows_conflicting_lists(self):
        for value in (event(unknown_days=[2]), event(claimable_days=[True]), event(claimable_days=[8]),
                      event(claimable_days=[2, 2]), event(page_verified=False),
                      event(account_verified=False), event(account_verified=1), event(unknown_days=[3, 4, 5, 6]),
                      event(page='phone_entry', claimable_state='not_observed'),
                      event(claimable_state='none', claimable_days=[], claimed_days=[1, 2], unknown_days=[]),
                      event(claimable_state='available', claimable_days=[])):
            with self.subTest(value=value['daily_event_observe']['claimable_state']):
                self.assertEqual(observation_result('odyssey', value)[0], '结果待核对')

    def test_current_screen_receipt_shows_only_a_saved_anonymous_verified_page(self):
        verified = screen()
        self.assertEqual(observation_result('screen', verified),
                         ('当前页面已核实 · 星际和平指南', '同一账号的连续两帧一致。'))
        for invalid in (screen(page=_MARKER), screen(account_verified=False), screen(input_sent=True),
                        screen(page_verified=1), screen(status='partial')):
            title, detail = observation_result('screen', invalid)
            self.assertEqual(title, '当前页面待核对')
            self.assertNotIn(_MARKER, detail)
        for invalid in (screen(saved=False), screen(mode='odyssey'), event()):
            self.assertEqual(observation_result('screen', invalid)[0], '结果待核对')
        self.assertEqual(observation_result('screen', screen(status='stopped'))[0], '已停止')

    def test_achievement_sends_return_reward_and_balance_are_separate(self):
        title, detail = observation_result(ACHIEVEMENT_CLAIM, achievement_claim())
        self.assertEqual(title, '成就领取回页已核实')
        self.assertEqual(detail.splitlines(), ['一键领取 · 已发送', '明细确认 · 已发送', '成就总览 · 已回页',
            '原领取控件 · 已清除', '星琼展示 · 明细 20 星琼，物品 20 星琼',
            '星琼余额 · 100 → 120，差额 +20', '余额归因 · 待核对'])
        self.assertNotIn(_MARKER, detail)
        returned = achievement_claim(overview_controls_cleared=False, jade_attributed=20)
        title, detail = observation_result(ACHIEVEMENT_CLAIM, returned)
        self.assertEqual(title, '成就领取待核对')
        self.assertIn('成就总览 · 已回页', detail)
        self.assertIn('原领取控件 · 待核对', detail)
        self.assertIn('余额归因 · 待核对', detail)

    def test_achievement_partial_and_stopped_preserve_sends_without_inventing_return(self):
        for status, title in (('partial', '成就领取待核对'), ('stopped', '成就领取已停止')):
            with self.subTest(status=status):
                actual, detail = observation_result(ACHIEVEMENT_CLAIM, achievement_claim(
                    status=status, confirm_input='unknown', overlay_quantity=None,
                    overview_return_verified=False, overview_controls_cleared=False,
                    jade_balance_after=None, jade_balance_delta=None))
                self.assertEqual(actual, title)
                self.assertIn('一键领取 · 已发送', detail)
                self.assertIn('明细确认 · 发送待核对', detail)
                self.assertIn('成就总览 · 待核对', detail)
                self.assertIn('星琼余额 · 领前 100，领后待核对', detail)
        unverified = achievement_claim(status='partial', account_verified=False)
        _, detail = observation_result(ACHIEVEMENT_CLAIM, unverified)
        self.assertIn('有回页记录，来源待核对', detail)
        self.assertIn('星琼余额 · 待核对', detail)

    def test_achievement_rejects_wrong_receipt_and_inconsistent_balance_attribution(self):
        for invalid in (achievement_claim(saved=False), achievement_claim(schema=True), reward()):
            self.assertEqual(observation_result(ACHIEVEMENT_CLAIM, invalid),
                             ('成就领取待核对', '本次领取回执待核对。'))
        for invalid in (achievement_claim(jade_balance_delta=True, jade_attributed=20),
                        achievement_claim(jade_attributed=21), achievement_claim(overlay_quantity=21)):
            _, detail = observation_result(ACHIEVEMENT_CLAIM, invalid)
            self.assertIn('余额归因 · 待核对', detail)
        _, detail = observation_result(ACHIEVEMENT_CLAIM, achievement_claim(jade_attributed=20))
        self.assertIn('余额归因 · 已归因 20 星琼', detail)

    def test_message_reply_receipt_separates_current_send_feedback_and_ledger(self):
        title, detail = message_reply_result(P179_SELECTION, message_reply())
        self.assertEqual(title, '本次短信回复已核实')
        self.assertEqual(detail.splitlines(), [
            '最近一次 · 工作与休假／提议休假出游', '输入 · 已发送', '反馈 · 新发出回复已核实',
            '持久账本 · 确认记录已保存',
        ])
        for status, saved, sent, ledger, title, ledger_text in (
            ('partial', True, 'not_sent', 'confirmed', '已有确认记录，本次未发送', '已有确认记录'),
            ('success', True, 'not_sent', 'confirmed', '已有确认记录，本次未发送', '已有确认记录'),
            ('partial', True, 'unconfirmed', 'pending', '本次短信回复待核对', '待核对记录已保留'),
            ('stopped', True, 'sent', 'confirmed', '本次短信回复已停止', '确认记录已保存'),
            ('partial', False, 'sent', 'confirmed', '本次短信回复待核对', '确认记录已保存'),
            ('failed', True, 'not_sent', 'none', '本次短信回复待核对', '未取得记录'),
        ):
            with self.subTest(status=status, sent=sent, ledger=ledger):
                receipt = message_reply(status=status, saved=saved, input_status=sent, ledger_status=ledger)
                actual, detail = message_reply_result(P179_SELECTION, receipt)
                self.assertEqual(actual, title)
                self.assertIn('反馈 · 待核对', detail)
                self.assertIn('持久账本 · ' + ledger_text, detail)
                self.assertEqual('本次报告 · 未发布' in detail, not saved)
                self.assertNotIn(_MARKER, detail)

    def test_message_reply_rejects_unbound_or_unknown_receipts(self):
        unknown = ('本次短信回复待核对', '本次回复回执待核对。')
        for receipt in (message_reply((REPLY_NODE, REPLY_CHOICE)), message_reply(schema=True),
                        message_reply(input_status=_MARKER), messages(), dict(message_reply(), report_saved=1)):
            self.assertEqual(message_reply_result(P179_SELECTION, receipt), unknown)
        self.assertEqual(message_reply_result(list(P179_SELECTION), message_reply()), unknown)

    def test_event_claim_keeps_submission_popup_return_and_balance_separate(self):
        title, detail = event_claim_result(4, False, event_claim())
        self.assertEqual(title, '本次巡星之礼领取待核对')
        self.assertEqual(detail.splitlines(), [
            '最近一次 · 第 4 天', '输入 · 已发送', '奖励弹窗 · 已核实 星轨专票 ×1',
            '关闭后同卡 · 本次未启用核对', '账户余额 · 待核对',
        ])
        receipt = event_claim(status='success', state='verified', stage='done', balance=120)
        title, detail = event_claim_result(4, True, receipt)
        self.assertEqual(title, '本次巡星之礼领取已核实')
        self.assertIn('关闭后同卡 · 已核实为已领取', detail)
        self.assertIn('账户余额 · 待核对', detail)
        self.assertNotIn('120', detail)
        self.assertNotIn(_MARKER, detail)
        self.assertIn('关闭后同卡 · 本次未启用核对', event_claim_result(4, False, receipt)[1])

    def test_event_claim_does_not_credit_old_unsaved_or_conflicting_feedback(self):
        for receipt, input_status, popup_status in (
            (event_claim(status='failed', submission='not_sent', state='verified', stage='done'), '未发送', '未观察'),
            (event_claim(submission='unconfirmed', popup='not_observed'), '发送待核对', '待核对'),
            (event_claim(status='stopped', popup='unknown'), '已发送', '待核对'),
            (event_claim(status='success', saved=False, state='verified', stage='done'), '已发送', '待核对'),
            (event_claim(status='success', state='verified', stage='done', quantity=3), '已发送', '待核对'),
            (event_claim(stage='return_unverified'), '已发送', '已核实 星轨专票 ×1'),
        ):
            with self.subTest(receipt=receipt):
                title, detail = event_claim_result(4, True, receipt)
                self.assertNotEqual(title, '本次巡星之礼领取已核实')
                self.assertIn(f'输入 · {input_status}', detail)
                self.assertIn(f'奖励弹窗 · {popup_status}', detail)
                self.assertIn('关闭后同卡 · 待核对', detail)
                self.assertIn('账户余额 · 待核对', detail)
                self.assertEqual('本次报告 · 未发布' in detail, not receipt['report_saved'])
        for invalid in (event(), event_claim(day=5), event_claim(day=4.0), event_claim(schema=True)):
            self.assertEqual(event_claim_result(4, True, invalid),
                             ('本次巡星之礼领取待核对', '本次领取回执待核对。\n账户余额 · 待核对'))


class DailyObservationPanelTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.geometry('1100x800')
        theme.apply_theme(self.root, 1.)
        self.addCleanup(self.destroy_root)
        self.callbacks = []
        self.ui = SimpleNamespace(root=self.root, ui_scale=1., busy=False, closing=False, active=True,
                                  _selected_tool='daily_observation', _in_tools=lambda: self.ui.active,
                                  _tool_action_changed=Mock(), _start_daily_observation=Mock(side_effect=self.start),
                                  _start_achievement_bulk_claim=Mock(side_effect=self.start_claim),
                                  _start_daily_message_reply=Mock(side_effect=self.start),
                                  _start_daily_event_claim=Mock(side_effect=self.start_event_claim))
        self.panel = self.ui.daily_observation_panel = build_daily_observation_panel(self.root, self.ui)
        self.panel.pack(fill='x')

    def destroy_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def start(self, mode, complete):
        self.ui.busy = True
        self.callbacks.append((mode, complete))
        return True

    def start_claim(self, complete):
        return self.start(ACHIEVEMENT_CLAIM, complete)

    def start_event_claim(self, day, observe_return, complete):
        return self.start((day, observe_return), complete)

    def select(self, label, panel=None):
        panel = self.panel if panel is None else panel
        panel.scope.set(label)
        panel._selected()

    def deliver(self, value, index=-1):
        self.ui.busy = False
        self.callbacks[index][1](value)

    def test_select_five_ranges_and_submit_only_current_explicit_mode(self):
        expected = (('成就总览', 'achievements'), ('漫游签证', 'support'), ('短信', 'messages'),
                    ('巡星之礼', 'odyssey'), ('当前页面', 'screen'))
        self.assertEqual(tuple(self.panel.scope['values']),
                         (*[label for label, _ in expected], '核对所选页面', '本次成就一键领取', '本次短信回复',
                          '本次巡星之礼领取'))
        for label, mode in expected:
            self.select(label)
            self.assertIn('切回游戏', self.panel.hint['text'])
            if mode in ('support', 'messages', 'odyssey', 'screen'):
                self.assertIn('只读当前页面', self.panel.hint['text'])
            if mode == 'screen':
                self.assertIn('手动切回游戏', self.panel.hint['text'])
                self.assertIn('已登录', self.panel.hint['text'])
            self.assertTrue(self.panel.primary_action()[2])
            self.assertTrue(self.panel.primary_action()[1]())
            self.assertEqual(self.callbacks[-1][0], mode)
            self.assertTrue(self.panel.scope.instate(('disabled',)))
            self.assertFalse(self.panel.start())
            self.deliver(screen() if mode == 'screen' else None)
            self.assertTrue(self.panel.scope.instate(('readonly', '!disabled')))
        self.assertEqual(self.panel.result_title['text'], '当前页面已核实 · 星际和平指南')
        self.assertNotIn(_MARKER, repr(self.ui._daily_observation_state))
        self.select('巡星之礼')
        self.assertEqual(self.panel.result_title['text'], '结果待核对')
        self.select('当前页面')
        self.assertEqual(self.panel.result_title['text'], '当前页面已核实 · 星际和平指南')
        self.assertEqual(self.ui._start_daily_observation.call_count, 5)
        self.ui._start_achievement_bulk_claim.assert_not_called()
        self.ui._start_daily_message_reply.assert_not_called()
        self.ui._start_daily_event_claim.assert_not_called()
        self.assertEqual(self.root.state(), 'withdrawn')

    def test_event_claim_requires_day_and_footer_with_independent_return_choice(self):
        self.assertEqual(self.panel.scope.get(), '成就总览')
        self.select('巡星之礼')
        self.assertFalse(self.panel.event_fields.grid_info())
        self.assertTrue(self.panel.primary_action()[1]())
        self.deliver(event())
        read_only = self.panel.result_detail['text']

        self.select('本次巡星之礼领取')
        self.assertTrue(self.panel.event_fields.grid_info())
        self.assertIn('手动打开巡星之礼活动页', self.panel.hint['text'])
        self.assertEqual(self.panel.event_day.get(), '')
        self.assertFalse(self.panel.event_return.get())
        self.assertEqual(tuple(self.panel.event_day['values']), tuple(f'第 {day} 天' for day in range(3, 8)))
        self.panel.event_return_check.invoke()
        self.assertTrue(self.panel.event_return.get())
        self.assertIn('手动关闭', self.panel.event_return_hint['text'])
        self.assertFalse(self.panel.primary_action()[2])
        self.assertFalse(self.panel.start())
        for label, enabled in (('第 2 天', False), ('第 7 天', True), ('第 4 天', True)):
            self.panel.event_day.set(label)
            self.panel._event_day_selected()
            self.assertEqual(self.panel.primary_action()[2], enabled)
        self.ui._start_daily_event_claim.assert_not_called()
        label, invoke, enabled = self.panel.primary_action()
        self.assertEqual((label, enabled), ('提交本次巡星之礼领取', True))
        self.assertTrue(invoke())
        self.assertEqual(self.callbacks[-1][0], (4, True))
        self.assertTrue(all(widget.instate(('disabled',)) for widget in
                            (self.panel.scope, self.panel.event_day, self.panel.event_return_check)))
        self.assertFalse(self.panel.start())

        self.panel.destroy()
        self.panel = self.ui.daily_observation_panel = build_daily_observation_panel(self.root, self.ui)
        self.panel.pack(fill='x')
        self.assertEqual(self.panel.event_day.get(), '第 4 天')
        self.assertTrue(self.panel.event_return.get())
        self.deliver(event_claim(status='success', state='verified', stage='done'))
        self.deliver(event_claim())
        self.assertEqual(self.panel.result_title['text'], '本次巡星之礼领取已核实')
        self.assertIn('账户余额 · 待核对', self.panel.result_detail['text'])
        self.assertEqual(self.panel.event_day.get(), '')
        self.assertFalse(self.panel.event_return.get())
        self.assertFalse(self.panel.primary_action()[2])
        self.select('巡星之礼')
        self.assertEqual(self.panel.result_detail['text'], read_only)
        self.ui._start_daily_event_claim.assert_called_once()
        self.assertEqual(self.root.state(), 'withdrawn')

    def test_sms_reply_requires_both_selections_and_shared_footer(self):
        self.select('短信')
        self.assertEqual(self.panel.primary_action()[0], '核对页面')
        self.assertTrue(self.panel.start())
        self.deliver(messages())
        self.select('本次短信回复')
        self.assertTrue(self.panel.reply_fields.grid_info())
        self.assertEqual((self.panel.reply_node.get(), self.panel.reply_choice.get()), ('', ''))
        self.assertTrue(self.panel.reply_choice.instate(('disabled',)))
        self.assertFalse(self.panel.start())
        self.panel.reply_node.set(REPLY_NODE)
        self.panel._reply_node_selected()
        self.assertEqual(tuple(self.panel.reply_choice['values']),
                         (REPLY_CHOICE, '恭喜获得新形态', '说对方看起来很开心'))
        self.assertEqual(self.panel.reply_choice.get(), '')
        self.assertFalse(self.panel.primary_action()[2])
        self.panel.reply_choice.set(REPLY_CHOICE)
        self.panel._reply_choice_selected()
        self.assertTrue(self.panel.primary_action()[2])
        self.panel.reply_node.set(P179_SELECTION[0])
        self.panel._reply_node_selected()
        self.assertEqual(tuple(self.panel.reply_choice['values']),
                         ('羡慕对方的爱好', '回应工作狂', P179_SELECTION[1]))
        self.assertEqual(self.panel.reply_choice.get(), '')
        self.panel.reply_choice.set(REPLY_CHOICE)
        self.panel._reply_choice_selected()
        self.assertFalse(self.panel.primary_action()[2])
        self.panel.reply_choice.set(P179_SELECTION[1])
        self.panel._reply_choice_selected()
        self.ui._start_daily_message_reply.assert_not_called()
        label, invoke, enabled = self.panel.primary_action()
        self.assertEqual((label, enabled), ('提交本次短信回复', True))
        self.assertTrue(invoke())
        self.assertEqual(self.callbacks[-1][0], P179_SELECTION)
        self.assertTrue(all(widget.instate(('disabled',)) for widget in
                            (self.panel.scope, self.panel.reply_node, self.panel.reply_choice)))
        self.assertFalse(self.panel.start())

        self.panel.destroy()
        self.panel = self.ui.daily_observation_panel = build_daily_observation_panel(self.root, self.ui)
        self.panel.pack(fill='x')
        self.assertEqual((self.panel.reply_node.get(), self.panel.reply_choice.get()), P179_SELECTION)
        self.deliver(message_reply(status='partial', input_status='not_sent', feedback_status='unknown'))
        self.deliver(message_reply())
        self.assertEqual(self.panel.result_title['text'], '已有确认记录，本次未发送')
        self.assertEqual((self.panel.reply_node.get(), self.panel.reply_choice.get()), ('', ''))
        self.assertFalse(self.panel.primary_action()[2])
        self.select('短信')
        self.assertEqual(self.panel.result_title['text'], '手机短信入口已核实')
        self.assertNotIn(_MARKER, repr(self.ui._daily_observation_state))
        self.ui._start_daily_message_reply.assert_called_once()

    def test_achievement_claim_requires_explicit_scope_and_footer_then_preserves_read_only_result(self):
        self.assertEqual(self.panel.scope.get(), '成就总览')
        self.assertTrue(self.panel.start())
        self.deliver(reward(page_verified=True, entry_input='sent', destination_status='achievement_overview'))
        self.select('本次成就一键领取')
        self.ui._start_achievement_bulk_claim.assert_not_called()
        self.assertIn('手动关闭', self.panel.note['text'])
        self.assertEqual(self.panel.primary_action()[0], '本次成就一键领取')
        self.assertEqual(self.panel.result_title['text'], '等待领取')
        self.assertTrue(self.panel.primary_action()[1]())
        self.ui._start_achievement_bulk_claim.assert_called_once()
        self.assertTrue(self.panel.scope.instate(('disabled',)))
        self.assertFalse(self.panel.start())
        self.select('成就总览')
        self.assertEqual(self.panel.scope.get(), '本次成就一键领取')
        self.deliver(achievement_claim())
        self.deliver(achievement_claim(status='stopped'))  # Old ticket cannot replace the result.
        self.assertEqual(self.panel.result_title['text'], '成就领取回页已核实')
        self.assertIn('余额归因 · 待核对', self.panel.result_detail['text'])
        self.select('成就总览')
        self.assertEqual(self.panel.result_title['text'], '成就总览已核实')
        self.assertEqual(self.panel.primary_action()[0], '核对页面')
        self.assertNotIn(_MARKER, repr(self.ui._daily_observation_state))

    def test_rebuilt_panel_keeps_selection_and_only_current_anonymous_callback(self):
        self.select('巡星之礼')
        self.assertTrue(self.panel.start())
        self.select('短信')
        self.assertEqual(self.panel.scope.get(), '巡星之礼')
        self.panel.destroy()
        self.ui.ui_scale = 1.25
        self.root.geometry('1375x1000')
        replacement = self.ui.daily_observation_panel = build_daily_observation_panel(self.root, self.ui)
        replacement.pack(fill='x')
        self.assertEqual(replacement.scope.get(), '巡星之礼')
        self.assertEqual(replacement.result_title['text'], '正在核对')
        self.deliver(event())
        self.assertEqual(replacement.result_title['text'], '巡星之礼有可领奖励')
        self.assertNotIn(_MARKER, repr(self.ui._daily_observation_state))
        self.deliver(event(page_verified=False))  # Duplicate callback from the old panel.
        self.assertEqual(replacement.result_title['text'], '巡星之礼有可领奖励')
        self.select('短信', replacement)
        self.assertEqual(replacement.result_title['text'], '等待核对')
        self.select('巡星之礼', replacement)
        self.assertEqual(replacement.result_title['text'], '巡星之礼有可领奖励')

    def test_inactive_or_rejected_work_cannot_lock_scope_and_stop_has_own_state(self):
        self.ui._selected_tool = 'screenshot'
        self.assertFalse(self.panel.primary_action()[2])
        self.assertFalse(self.panel.start())
        self.ui._start_daily_observation.assert_not_called()
        self.ui._selected_tool = 'daily_observation'
        self.ui._start_daily_observation.side_effect = None
        self.ui._start_daily_observation.return_value = False
        self.assertFalse(self.panel.start())
        self.assertTrue(self.panel.primary_action()[2])
        self.ui._start_daily_observation.side_effect = self.start
        self.assertTrue(self.panel.start())
        self.deliver(reward(status='stopped', page_verified=False))
        self.assertEqual(self.panel.result_title['text'], '已停止')
        self.assertTrue(self.panel.primary_action()[2])

    def test_tools_shelf_reuses_the_shared_navigation_and_footer(self):
        def other(parent, _ui):
            panel = ttk.Frame(parent)
            panel.refresh = panel.refresh_actions = Mock()
            panel.focus_entry = panel.focus_initial = Mock()
            panel.primary_action = Mock(return_value=('其他工具', Mock(), True))
            return panel

        self.panel.destroy()
        with ExitStack() as stack:
            for name in ('desktop_warp.build_warp_panel', 'desktop_services.build_redemption_panel',
                         'desktop_services.build_notifications_panel', 'desktop_workflows.build_workflow_panel',
                         'desktop_workflows.build_schedule_panel', 'desktop_screenshot.build_screenshot_panel'):
                stack.enter_context(patch('autohsr.' + name, side_effect=other))
            for scale in (1., 1.5, 2.):
                with self.subTest(scale=scale):
                    self.ui.ui_scale = scale
                    self.ui._selected_tool = 'warp'
                    theme.apply_theme(self.root, scale)
                    nav = ttk.Frame(self.root)
                    self.ui.settings_shell = SimpleNamespace(tools_nav=nav, canvas=Mock(), queue_layout=Mock())
                    shelf = self.ui.tools_shelf = ToolsShelf(self.root, self.ui)
                    try:
                        shelf.pack(fill='x')
                        shelf.select('daily_observation')
                        panel = self.ui.daily_observation_panel
                        self.select('当前页面', panel)
                        self.assertTrue(shelf.primary_action()[1]())
                        self.deliver(screen())
                        self.root.update_idletasks()
                        button = shelf.buttons['daily_observation']
                        self.assertIs(shelf.nav, nav)
                        self.assertIs(button.master, nav)
                        self.assertEqual(button['text'], '日常页面核对')
                        self.assertIs(shelf.current(), panel)
                        self.assertEqual(shelf.primary_action()[0], '核对页面')
                        self.assertTrue(shelf.primary_action()[2])
                        self.assertEqual(panel.result_title['text'], '当前页面已核实 · 星际和平指南')
                        # Minimum desktop width minus the book margins, guide and settings scrollbar.
                        available = round(1100 * scale) - 2 * round(18 * scale) - round(173 * scale) - round(14 * scale)
                        self.assertLessEqual(max(button.master.winfo_reqwidth(), panel.winfo_reqwidth()), available)
                        self.select('本次成就一键领取', panel)
                        self.assertTrue(shelf.primary_action()[1]())
                        self.deliver(achievement_claim())
                        self.root.update_idletasks()
                        self.assertEqual(shelf.primary_action()[0], '本次成就一键领取')
                        self.assertLessEqual(panel.winfo_reqwidth(), available)
                        self.assertEqual(len(panel.result_detail['text'].splitlines()), 7)
                        self.select('本次巡星之礼领取', panel)
                        self.assertFalse(shelf.primary_action()[2])
                        panel.event_day.set('第 4 天')
                        panel._event_day_selected()
                        panel.event_return_check.invoke()
                        self.root.update_idletasks()
                        self.assertLessEqual(panel.winfo_reqwidth(), available)
                        self.assertTrue(shelf.primary_action()[2])
                        self.assertTrue(shelf.primary_action()[1]())
                        self.deliver(event_claim(stage='return_unverified'))
                        self.assertIn('关闭后同卡 · 待核对', panel.result_detail['text'])
                        self.assertFalse(shelf.primary_action()[2])
                        self.ui.settings_shell.canvas.yview_moveto.assert_called_with(0)
                        self.assertEqual(self.root.state(), 'withdrawn')
                    finally:
                        shelf.destroy()
                        nav.destroy()


if __name__ == '__main__':
    unittest.main()
