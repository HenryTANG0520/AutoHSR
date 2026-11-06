"""Anonymous daily observation projections and hidden desktop lifecycle checks."""

from contextlib import ExitStack
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import theme
from autohsr.desktop_daily_observe import build_daily_observation_panel, observation_result
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
        visa = dict(entry_input='sent', destination_status=destination, before_frames=sources)
        verified = reward('support', page_verified=True, entry_input='sent', destination_status=destination,
                          steps=dict(open_more=more, open_support=visa))
        self.assertEqual(observation_result('support', verified), ('漫游签证收集展示已核实', '支援奖励状态待核对。'))
        visa['before_frames'] = list(reversed(sources))
        self.assertEqual(observation_result('support', verified)[0], '结果待核对')
        visa['before_frames'] = sources
        visa['entry_input'] = 'unconfirmed'
        self.assertEqual(observation_result('support', verified)[0], '结果待核对')

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
                                  _tool_action_changed=Mock(), _start_daily_observation=Mock(side_effect=self.start))
        self.panel = self.ui.daily_observation_panel = build_daily_observation_panel(self.root, self.ui)
        self.panel.pack(fill='x')

    def destroy_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def start(self, mode, complete):
        self.ui.busy = True
        self.callbacks.append((mode, complete))
        return True

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
        self.assertEqual(tuple(self.panel.scope['values']), (*[label for label, _ in expected], '核对所选页面'))
        for label, mode in expected:
            self.select(label)
            self.assertIn('切回游戏', self.panel.hint['text'])
            if mode in ('messages', 'odyssey', 'screen'):
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
        self.assertEqual(self.root.state(), 'withdrawn')

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
        self.ui.settings_shell = SimpleNamespace(canvas=Mock(), queue_layout=Mock())
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
                        self.assertEqual(button['text'], '日常页面核对')
                        self.assertIs(shelf.current(), panel)
                        self.assertEqual(shelf.primary_action()[0], '核对页面')
                        self.assertTrue(shelf.primary_action()[2])
                        self.assertEqual(panel.result_title['text'], '当前页面已核实 · 星际和平指南')
                        # Minimum desktop width minus the book margins, guide and settings scrollbar.
                        available = round(1100 * scale) - 2 * round(18 * scale) - round(173 * scale) - round(14 * scale)
                        self.assertLessEqual(max(button.master.winfo_reqwidth(), panel.winfo_reqwidth()), available)
                        self.ui.settings_shell.canvas.yview_moveto.assert_called_with(0)
                        self.assertEqual(self.root.state(), 'withdrawn')
                    finally:
                        shelf.destroy()


if __name__ == '__main__':
    unittest.main()
