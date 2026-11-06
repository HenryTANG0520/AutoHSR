"""Hidden Tk coverage of the selected-page preview and scoped desktop start."""

import tkinter as tk
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import theme
from autohsr.desktop_daily_observe import build_daily_observation_panel
from autohsr.task_workflow import WORKFLOW_PAGES


_PRIVATE = 'private-account-and-path-fixture'


def targets(recipe):
    return tuple(step['params']['target'] for step in recipe.steps)


def page(target, status='verified', sent=0, uncertain=0):
    return dict(target=target, status=status, actions_sent=sent, actions_unconfirmed=uncertain)


class DesktopSelectedPageCheckTests(TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        theme.apply_theme(self.root, 1.)
        self.pending = None
        self.ui = SimpleNamespace(root=self.root, ui_scale=1., busy=False, closing=False,
            _selected_tool='daily_observation', _in_tools=lambda: True, _tool_action_changed=Mock(),
            _start_daily_observation=Mock(return_value=False),
            _start_selected_page_check=Mock(side_effect=self.start))
        self.panel = self.make_panel()
        self.saved_result = self.enterContext(patch('autohsr.selected_page_check.saved_result', create=True))

    def destroy_root(self):
        self.root.update_idletasks()
        self.root.destroy()

    def make_panel(self):
        panel = self.ui.daily_observation_panel = build_daily_observation_panel(self.root, self.ui)
        panel.pack(fill='x')
        panel.refresh()
        return panel

    def start(self, recipe, complete):
        self.assertIsNone(self.pending)
        self.ui.busy = True
        self.pending = recipe, complete
        return True

    def select_scope(self, label):
        self.panel.scope.set(label)
        self.panel._selected()

    def select_pages(self, *chosen):
        self.select_scope('核对所选页面')
        for target in chosen:
            self.panel.page_check.checks[target].invoke()

    def preview(self):
        self.panel.page_check.preview_button.invoke()
        return self.panel.page_check.recipe

    def deliver(self, receipt):
        recipe, complete = self.pending
        self.pending = None
        self.ui.busy = False
        self.saved_result.return_value = receipt
        report = dict(operation='task_workflow', error=_PRIVATE, run_dir=_PRIVATE)
        complete(report)
        self.saved_result.assert_called_with(recipe, report)
        return complete

    def test_no_start_without_explicit_preview_and_odyssey_moves_to_the_end(self):
        self.select_scope('核对所选页面')
        self.assertIn('手动切回已登录的游戏前台', self.panel.hint['text'])
        self.assertTrue(self.panel.page_check.preview_button.instate(('disabled',)))
        self.assertFalse(self.panel.primary_action()[2])
        self.assertFalse(self.panel.start())
        self.select_pages('reward_guide', 'odyssey', 'mail', 'phone')
        self.assertFalse(self.panel.start())
        recipe = self.preview()
        self.assertEqual(targets(recipe), ('mail', 'phone', 'odyssey', 'reward_guide'))
        self.assertEqual(self.panel.page_check.order['text'], '实际核对顺序 · 邮件 → 手机 → 巡星之礼 → 奖励指南')
        self.assertTrue(self.panel.primary_action()[2])
        self.ui._start_selected_page_check.assert_not_called()
        self.ui._start_daily_observation.assert_not_called()
        self.panel.page_check.checks['mail'].invoke()
        self.assertIsNone(self.panel.page_check.recipe)
        self.assertFalse(self.panel.primary_action()[2])
        self.assertFalse(self.panel.start())
        self.assertEqual(targets(self.preview()), ('phone', 'odyssey', 'reward_guide'))

    def test_messages_is_an_independent_desktop_selection(self):
        self.select_pages('messages')
        checks = self.panel.page_check.checks
        self.assertTrue(checks['phone'].instate(('disabled',)))
        self.assertIn('未读角标', self.panel.page_check.order['text'])
        self.assertEqual(targets(self.preview()), ('messages',))
        checks['messages'].invoke()
        self.assertTrue(checks['phone'].instate(('!disabled',)))
        checks['phone'].invoke()
        self.assertTrue(checks['messages'].instate(('disabled',)))
        self.assertEqual(targets(self.preview()), ('phone',))

    def test_running_disables_edits_and_only_projects_anonymous_pages(self):
        self.select_pages('phone', 'mail', 'odyssey')
        recipe = self.preview()
        label, run, enabled = self.panel.primary_action()
        self.assertEqual((label, enabled), ('核对所选页面', True))
        self.assertTrue(run())
        self.assertIs(self.pending[0], recipe)
        self.assertTrue(self.panel.page_check.checks['mail'].instate(('disabled',)))
        self.assertTrue(self.panel.page_check.preview_button.instate(('disabled',)))
        self.panel.page_check.checks['mail'].invoke()
        self.select_scope('短信')
        self.assertEqual(self.panel.scope.get(), '核对所选页面')
        self.assertIs(self.panel.page_check.recipe, recipe)
        self.assertFalse(self.panel.start())
        self.deliver(dict(status='partial', pages=[page('phone'), page('mail', 'unknown', 1, 1),
                                                   page('odyssey', 'not_run', None, None)]))
        self.assertEqual(self.panel.result_title['text'], '所选页面核对未完整结束')
        self.assertEqual(self.panel.result_detail['text'].splitlines(), [
            '手机 · 到页已核实 · 已发送 0 次，发送待核对 0 次',
            '邮件 · 到页待核对 · 已发送 1 次，发送待核对 1 次', '巡星之礼 · 未执行',
        ])
        self.assertNotIn(_PRIVATE, repr(self.ui._daily_observation_state))
        self.ui._start_daily_observation.assert_not_called()
        self.select_scope('当前页面')
        self.assertFalse(self.panel.page_check.grid_info())
        self.assertEqual(self.panel.primary_action()[0], '核对页面')
        self.assertEqual(self.panel.result_title['text'], '等待核对')
        self.assertFalse(self.panel.start())
        self.ui._start_daily_observation.assert_called_once()
        self.assertEqual(self.ui._start_daily_observation.call_args.args[0], 'screen')
        self.select_scope('核对所选页面')
        self.assertEqual(self.panel.result_title['text'], '所选页面核对未完整结束')
        self.panel.page_check.checks['mail'].invoke()
        self.assertEqual(self.panel.result_title['text'], '等待核对')

    def test_resize_keeps_preview_and_current_callback_while_ignoring_the_duplicate(self):
        self.select_pages('mail')
        recipe = self.preview()
        self.assertTrue(self.panel.start())
        self.panel.destroy()
        self.ui.ui_scale = 1.5
        self.panel = self.make_panel()
        self.assertIs(self.panel.page_check.recipe, recipe)
        self.assertTrue(self.panel.page_check.variables['mail'].get())
        self.assertEqual(self.panel.result_title['text'], '正在核对')
        complete = self.deliver(dict(status='success', pages=[page('mail', sent=1)]))
        self.assertEqual(self.panel.result_title['text'], '所选页面已核实')
        complete(dict(error=_PRIVATE))
        self.saved_result.assert_called_once()
        self.assertEqual(self.panel.result_title['text'], '所选页面已核实')

    def test_inactive_rejected_and_closed_work_does_not_reuse_the_result(self):
        self.select_pages('phone')
        self.preview()
        self.ui._selected_tool = 'screenshot'
        self.assertFalse(self.panel.primary_action()[2])
        self.assertFalse(self.panel.start())
        self.ui._start_selected_page_check.assert_not_called()
        self.ui._selected_tool = 'daily_observation'
        self.ui._start_selected_page_check.side_effect = None
        self.ui._start_selected_page_check.return_value = False
        self.assertFalse(self.panel.start())
        self.assertTrue(self.panel.primary_action()[2])
        self.ui._start_selected_page_check.side_effect = self.start
        self.assertTrue(self.panel.start())
        self.ui.closing = True
        self.pending[1](dict(error=_PRIVATE))
        self.saved_result.assert_not_called()
        self.assertIsNone(self.panel.model.job)

    def test_inconsistent_summary_or_out_of_order_page_never_displays_success(self):
        self.select_pages('mail')
        self.preview()
        for row in (page('mail', 'unknown', None, None), page('mail', uncertain=1), page(_PRIVATE)):
            self.assertTrue(self.panel.start())
            self.deliver(dict(status='success', pages=[row]))
            self.assertEqual(self.panel.result_title['text'], '结果待核对')
            self.assertNotIn(_PRIVATE, self.panel.result_detail['text'])

    def test_maximum_selection_fits_the_minimum_guide_width_at_each_scale(self):
        compatible = tuple(target for target in WORKFLOW_PAGES if target != 'messages')
        for scale in (1., 1.5, 2.):
            with self.subTest(scale=scale):
                self.panel.destroy()
                del self.ui._daily_observation_state
                theme.apply_theme(self.root, scale)
                self.ui.ui_scale = scale
                self.panel = self.make_panel()
                self.select_pages(*compatible)
                recipe = self.preview()
                self.assertTrue(self.panel.start())
                self.deliver(dict(status='success', pages=[page(target) for target in targets(recipe)]))
                self.root.update_idletasks()
                self.assertEqual(len(self.panel.result_detail['text'].splitlines()), len(compatible))
                available = round(1100 * scale) - 2 * round(18 * scale) - round(173 * scale) - round(14 * scale)
                self.assertLessEqual(self.panel.winfo_reqwidth(), available)
                self.assertEqual(self.root.state(), 'withdrawn')
