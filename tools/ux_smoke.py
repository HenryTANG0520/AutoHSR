"""Offline GUI acceptance checks. All game backend calls are replaced before use."""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import threading
import time
import tkinter as tk
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PACKAGE = 'autohsr' if (ROOT / 'autohsr').exists() else 'autozzz'
importlib.import_module(PACKAGE + '.windows')  # establish DPI before Tk; no game actions
Settings = importlib.import_module(PACKAGE + '.config').Settings
module = importlib.import_module(PACKAGE + '.gui')
Window = module.AutoHSRWindow if PACKAGE == 'autohsr' else module.AutoZZZWindow
from PIL import ImageGrab

OUT = ROOT / 'runs' / 'ux-smoke'
OUT.mkdir(parents=True, exist_ok=True)
checks = []


def pump(root, predicate=lambda: True, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('GUI condition timed out')


def check(name, condition):
    assert condition, name
    checks.append(name)


def layout(root):
    def walk(widget):
        for child in widget.winfo_children():
            if not child.winfo_ismapped():
                continue
            x, y = child.winfo_rootx() - root.winfo_rootx(), child.winfo_rooty() - root.winfo_rooty()
            assert x >= 0 and y >= 0, (str(child), x, y)
            assert x + child.winfo_width() <= root.winfo_width() + 2, (str(child), 'width')
            assert y + child.winfo_height() <= root.winfo_height() + 2, (str(child), 'height')
            if child.winfo_class() in ('TLabel', 'TButton', 'TCheckbutton', 'TEntry', 'TCombobox'):
                assert child.winfo_height() >= child.winfo_reqheight(), (str(child), 'clipped')
            walk(child)
    walk(root)


class FakeRunner:
    instances = []
    def __init__(self, settings, emit, **kwargs):
        self.settings, self.emit, self.kwargs = settings, emit, kwargs
        self.release = threading.Event()
        self.paused = False
        self.stopped = False
        self.report = types.SimpleNamespace(operation='daily')
        self._window = None
        self.instances.append(self)

    def run(self):
        if self.kwargs.get('operation', '') == 'differential_universe':
            self.emit(dict(type='task', task='differential_universe', status='running', detail='离线假后端，无游戏输入'))
            self.release.wait(5)
            runs = int(getattr(self.settings, 'differential_universe_runs', 3))
            report = dict(status='stopped' if self.stopped else 'success', operation='differential_universe',
                results=[], differential_universe=dict(requested_runs=runs, completed_runs=0 if self.stopped else runs,
                    actions=[], page_history=[], stamina_budget_used=False, premium_currency_used=False, fuel_used=False))
            self.emit(dict(type='finished', report=report))
            return report
        if self.kwargs.get('operation', '').startswith('currency_wars'):
            self.emit(dict(type='task', task='currency_wars', status='running', detail='离线只读模拟，无游戏输入'))
            self.release.wait(5)
            report = dict(status='stopped' if self.stopped else 'partial', operation=self.kwargs['operation'],
                results=[], currency_wars=dict(mode_text_visible=True, gameplay_enabled=False, completion_verified=False),
                error='离线模拟：真实规则尚未核实', safe_next='人工采集教程后校准')
            if self.kwargs['operation'] == 'currency_wars_standard':
                report['currency_wars'].update(mode='standard_development', start_verified=True,
                                              action_status='needs_observation', rank=8, wealth=40)
            if self.kwargs['operation'] == 'currency_wars_drag_test':
                report['currency_wars'].update(mode='single_drag_test', action_status='verified', before='fake-before.png', after='fake-after.png')
            if self.kwargs['operation'] == 'currency_wars_deploy_test':
                report['currency_wars'].update(mode='single_deployment_test', action_status='verified', before='fake-before.png', after='fake-after.png')
            if self.kwargs['operation'] == 'currency_wars_node_test':
                report['currency_wars'].update(mode='single_node_test', origin_node='1-4', node_verified=True)
            if self.kwargs['operation'] == 'currency_wars_flow_test':
                report['currency_wars'].update(mode='flow_test',actions=[dict(node_verified=True)],action_status='needs_decision')
            if self.kwargs['operation'] == 'currency_wars_prepare':
                report['currency_wars'].update(mode='startup_prepare', game_ready=True,
                                              page_kind='phone', action_status='game_ready')
                if self.kwargs.get('currency_locate'):
                    report['currency_wars'].update(mode='entry_navigation', entry_ready=True,
                                                  page_kind='standard_selected', action_status='entry_ready')
                    if self.kwargs.get('currency_configure'):
                        report['currency_wars'].update(rank_verified=True, rank=8, wealth=40,
                                                      page_kind='standard_difficulty', action_status='rank_ready')
            self.emit(dict(type='finished', report=report))
            return report
        task = 'battle' if PACKAGE == 'autohsr' else 'scratch'
        self.emit(dict(type='task', task=task, status='running', detail='离线假后端，无游戏输入'))
        self.release.wait(5)
        report = dict(status='stopped' if self.stopped else 'success', stamina_spent=0,
                      daily_verified=False if self.stopped else True, engagement=400,
                      operation=self.kwargs.get('operation', self.report.operation), results=[])
        self.emit(dict(type='finished', report=report))
        return report

    def enter_game(self):
        report = dict(status='success', operation='enter_game', results=[dict(task='launch', status='ok', detail='模拟进入')])
        self.emit(dict(type='finished', report=report))
        return report

    def toggle_pause(self):
        self.paused = not self.paused
        self.emit(dict(type='paused', paused=self.paused))
        return self.paused

    def stop(self):
        self.stopped = True
        self.release.set()


class LateFinishRunner(FakeRunner):
    """Fault injection: backend announces completion before its thread exits."""
    fail_after_finish = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.early = threading.Event()
        self.tail = threading.Event()

    def run(self):
        report = dict(status='partial', operation='currency_wars', results=[])
        self.emit(dict(type='finished', report=report))
        self.early.set()
        if not self.tail.wait(3):
            raise AssertionError('late runner test release timed out')
        if self.fail_after_finish:
            raise RuntimeError('模拟完成通知后的异常')
        return report


def main():
    fake = types.ModuleType(PACKAGE + '.app')
    fake.Runner = FakeRunner
    fake.inspect_game = lambda _: dict(title='离线模拟窗口', width=1920, height=1080,
        administrator=True, input_ready=True, ocr_text='离线假后端，未启动游戏')
    fake.launch_game = lambda _: '离线模拟启动，未访问游戏'
    errors = []
    with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {PACKAGE + '.app': fake}), \
            patch.object(module, 'ROOT', Path(temp)), \
            patch.object(module.messagebox, 'showerror', side_effect=lambda *a, **k: errors.append(a)), \
            patch.object(module.messagebox, 'showinfo'), patch.object(module.messagebox, 'askyesno', return_value=False):
        config = Path(temp) / 'config.json'
        Settings().save(config)
        original = config.read_bytes()
        root = tk.Tk()
        ui = Window(root, config)
        try:
            pump(root)
            ui._log('离线 UX 验收：此界面使用假后端，未运行游戏。')
            for key in ui.pages:
                ui._show_page(key)
                pump(root)
                layout(root)
                check('persistent_controls_' + key, all(w.winfo_ismapped() for w in (ui.start_button, ui.pause_button, ui.stop_button)))
                ImageGrab.grab(window=root.winfo_id()).save(OUT / ('page-' + key + '.png'))
            if PACKAGE == 'autohsr':
                from autohsr.admin_launch import AdminLaunchError
                enabled = dict(exists=True, valid=True, enabled=True, account_is_admin=True)
                disabled = dict(exists=False, valid=False, enabled=False, account_is_admin=True)
                with patch('autohsr.admin_launch.configure', return_value=enabled) as configure:
                    ui._admin_operation('enable')
                    pump(root, lambda: not ui.busy)
                    check('admin_enable_verified_without_saving_game_config',
                          '已启用' in ui.admin_launch_status.get() and config.read_bytes() == original)
                    configure.assert_called_once_with('enable')
                with patch('autohsr.admin_launch.configure', side_effect=AdminLaunchError('已取消 Windows 管理员授权')):
                    ui._admin_operation('enable')
                    pump(root, lambda: not ui.busy)
                    check('admin_cancel_displays_actual_result', '已取消' in ui.admin_launch_status.get() and not ui.dirty)
                with patch('autohsr.admin_launch.configure', return_value=disabled):
                    ui._admin_operation('disable')
                    pump(root, lambda: not ui.busy)
                    check('admin_removal_is_independent_of_game_settings',
                          '未启用' in ui.admin_launch_status.get() and config.read_bytes() == original)
                admin_release = threading.Event()
                def admin_status():
                    admin_release.wait(3)
                    return disabled
                with patch('autohsr.admin_launch.status', side_effect=admin_status):
                    ui._admin_operation('status')
                    check('admin_pending_locks_game_and_authorization_controls',
                          ui.busy and all(str(w.cget('state')) == 'disabled' for w in ui.setting_controls))
                    ui._start()
                    check('admin_pending_prevents_concurrent_game_start', not FakeRunner.instances)
                    admin_release.set()
                    pump(root, lambda: not ui.busy)
                check('admin_actions_leave_game_config_unchanged', not ui.dirty and config.read_bytes() == original)
            ui._show_page('home')
            for value in ui.tasks.values():
                value.set(False)
            if PACKAGE == 'autohsr':
                from autohsr.dungeon_ui import select_category, change_count, set_count
                ui.tasks['battle'].set(True)
                saved_dungeon = (ui.dungeon_category.get(), ui.target_name.get(), ui.target_location.get(), ui.challenge_count.get())
                ui.dungeon_category.set('侵蚀隧洞')
                select_category(ui)
                set_count(ui, 2)
                check('dungeon_category_changes_cost_and_count_limit',
                      '80' in ui.battle_cost.get() and int(float(ui.challenge_scale.cget('to'))) == 6)
                change_count(ui, -1)
                check('dungeon_minus_changes_integer_count_without_running', ui.challenge_count.get() == '1' and not ui.busy and config.read_bytes() == original)
                ui.dungeon_category.set('历战余响')
                select_category(ui)
                set_count(ui, 20)
                check('weekly_dungeon_count_is_capped_at_three', ui.challenge_count.get() == '3' and '90' in ui.battle_cost.get())
                ui.dungeon_category.set(saved_dungeon[0])
                ui.target_name.set(saved_dungeon[1])
                ui.target_location.set(saved_dungeon[2])
                ui.challenge_count.set(saved_dungeon[3])
                ui.tasks['battle'].set(False)
                ui.stamina_limit.set('invalid disabled draft')
                ui.target_name.set('')
            else:
                ui.promoter.set('invalid ignored draft')
            ui._check()
            pump(root, lambda: not ui.busy)
            check('detect_independent_of_tasks_and_irrelevant_draft', not errors)
            check('detect_does_not_save', config.read_bytes() == original)
            ui._launch()
            pump(root, lambda: not ui.busy)
            check('launch_does_not_save_or_require_daily', config.read_bytes() == original and not errors)
            if PACKAGE == 'autohsr':
                # Independent mode must not depend on daily selections or invalid resource drafts.
                ui._show_page('currency_wars')
                check('currency_has_own_sidebar_entry_and_primary_action',
                    ui.nav_buttons['currency_wars'].cget('text') == '货币战争' and
                    ui.start_button.cget('text') == '只读识别当前画面' and
                    str(ui.start_button.cget('state')) == 'normal' and str(ui.reward_button.cget('state')) == 'disabled')
                ui.start_button.invoke()
                pump(root, lambda: ui.runner is not None)
                runner = FakeRunner.instances[-1]
                check('currency_uses_separate_operation_and_ignores_daily_draft',
                    runner.kwargs['operation'] == 'currency_wars' and
                    not any(getattr(runner.settings, name) for name in ui.tasks) and not runner.settings.auto_launch and not errors)
                check('currency_busy_locks_controls', all(str(w.cget('state')) == 'disabled' for w in ui.setting_controls))
                ui._pause()
                pump(root, lambda: ui.paused)
                ui._pause()
                pump(root, lambda: not ui.paused)
                ui._stop()
                pump(root, lambda: not ui.busy)
                check('currency_stop_does_not_offer_daily_recovery', '已停止' in ui.currency_status.get() and '补领奖' not in ui.summary.get())
                ui.start_button.invoke()
                pump(root, lambda: ui.runner is not None)
                FakeRunner.instances[-1].release.set()
                pump(root, lambda: not ui.busy)
                check('currency_observation_never_reports_gameplay_complete',
                    '玩法未完成' in ui.summary.get() and '尚未核实' in ui.summary.get() and
                    ui.currency_review.item('transitions', 'values')[1] == '部分验证' and
                    all(ui.currency_review.item(key, 'values')[1] == '4.6 已采集' for key in ('guide', 'tutorial', 'economy')))
                check('currency_does_not_save_or_change_daily_draft', config.read_bytes() == original and ui.stamina_limit.get() == 'invalid disabled draft')
                ui._currency_prepare()
                pump(root, lambda: ui.runner is not None)
                prepare_runner = FakeRunner.instances[-1]
                check('currency_prepare_is_separate_and_locks_controls',
                    prepare_runner.kwargs['operation'] == 'currency_wars_prepare' and
                    ui.current_task.get() == '货币战争启动准备' and
                    all(str(w.cget('state')) == 'disabled' for w in ui.setting_controls) and not errors)
                prepare_runner.release.set()
                pump(root, lambda: not ui.busy)
                check('currency_prepare_ready_is_not_a_match_win_or_settings_save',
                    '手机菜单' in ui.currency_observation.get() and '未开始新对局' in ui.currency_observation.get() and
                    '玩法未完成' in ui.summary.get() and config.read_bytes() == original)
                ui._currency_locate()
                pump(root, lambda: ui.runner is not None)
                locate_runner = FakeRunner.instances[-1]
                check('currency_locate_explicit_and_locks_controls',
                    locate_runner.kwargs['operation'] == 'currency_wars_prepare' and
                    locate_runner.kwargs.get('currency_locate') is True and
                    '指南定位标准模式' in ui.plan.get() and
                    all(str(w.cget('state')) == 'disabled' for w in ui.setting_controls))
                locate_runner.release.set()
                pump(root, lambda: not ui.busy)
                check('currency_locate_partial_without_daily_spend_or_settings_save',
                    '标准模式已定位' in ui.currency_observation.get() and
                    '未开始新对局' in ui.currency_observation.get() and
                    '玩法未完成' in ui.summary.get() and config.read_bytes() == original)
                ui._currency_configure()
                pump(root, lambda: ui.runner is not None)
                configure_runner = FakeRunner.instances[-1]
                check('currency_configure_is_explicit_without_starting_match',
                    configure_runner.kwargs['operation'] == 'currency_wars_prepare' and
                    configure_runner.kwargs.get('currency_locate') is True and
                    configure_runner.kwargs.get('currency_configure') is True and
                    '配置标准A8-40' in ui.plan.get() and not errors)
                configure_runner.release.set()
                pump(root, lambda: not ui.busy)
                check('currency_configure_ready_keeps_match_incomplete',
                    '标准A8财富造物主40已核实' in ui.currency_observation.get() and
                    '未开始新对局' in ui.currency_observation.get() and
                    '玩法未完成' in ui.summary.get() and config.read_bytes() == original)
                for resume in (False, True):
                    (ui._currency_resume if resume else ui._currency_standard)()
                    pump(root, lambda: ui.runner is not None)
                    standard_runner = FakeRunner.instances[-1]
                    check('currency_standard_resume_scope' if resume else 'currency_standard_start_scope',
                        standard_runner.kwargs['operation'] == 'currency_wars_standard' and
                        standard_runner.kwargs.get('currency_resume') is resume and
                        ui.current_task.get() == '标准A8-40开发' and
                        all(str(w.cget('state')) == 'disabled' for w in ui.setting_controls))
                    standard_runner.release.set()
                    pump(root, lambda: not ui.busy)
                    check('currency_standard_resume_is_not_acceptance' if resume else 'currency_standard_start_is_not_acceptance',
                        '已核实开局' in ui.currency_observation.get() and '整局未完成' in ui.currency_observation.get() and
                        '标准开发结束' in ui.summary.get() and config.read_bytes() == original)
                ui.currency_drag_button.invoke()
                pump(root, lambda: ui.runner is not None)
                drag_runner = FakeRunner.instances[-1]
                check('currency_drag_is_explicit_separate_operation', drag_runner.kwargs['operation'] == 'currency_wars_drag_test' and
                    str(ui.currency_drag_button.cget('state')) == 'disabled' and not errors)
                drag_runner.release.set()
                pump(root, lambda: not ui.busy)
                check('currency_drag_result_is_partial_and_does_not_save', '玩法未完成' in ui.summary.get() and
                    '头像已互换' in ui.currency_observation.get() and config.read_bytes() == original)
                ui.currency_source_slot.set('9')
                ui.currency_zone.set('前台')
                ui.currency_deploy_button.invoke()
                pump(root, lambda: ui.runner is not None)
                deploy_runner = FakeRunner.instances[-1]
                check('currency_deploy_is_scoped_and_locked', deploy_runner.kwargs['operation'] == 'currency_wars_deploy_test' and
                    str(ui.currency_deploy_button.cget('state')) == 'disabled' and
                    deploy_runner.kwargs['currency_source_slot']==9 and deploy_runner.kwargs['currency_zone']=='front')
                deploy_runner.release.set()
                pump(root, lambda: not ui.busy)
                check('currency_deploy_is_partial_and_does_not_save', '部署已确认' in ui.currency_observation.get() and
                    '玩法未完成' in ui.summary.get() and config.read_bytes() == original and
                    str(ui.currency_zone_combo.cget('state'))=='readonly')
                ui.currency_source_slot.set('3')
                ui.currency_zone.set('后台')
                ui.currency_node_button.invoke()
                pump(root, lambda: ui.runner is not None)
                node_runner = FakeRunner.instances[-1]
                check('currency_node_is_scoped_and_locked', node_runner.kwargs['operation'] == 'currency_wars_node_test' and
                    str(ui.currency_node_button.cget('state')) == 'disabled')
                node_runner.release.set()
                pump(root, lambda: not ui.busy)
                check('currency_node_win_is_partial_and_does_not_save', '节点胜利已验证' in ui.currency_observation.get() and
                    '玩法未完成' in ui.summary.get() and config.read_bytes() == original)
                ui.currency_target_level.set('7')
                ui.currency_flow_button.invoke()
                pump(root, lambda: ui.runner is not None)
                flow_runner=FakeRunner.instances[-1]
                check('currency_flow_is_scoped_and_locked',flow_runner.kwargs['operation']=='currency_wars_flow_test' and
                    str(ui.currency_flow_button.cget('state'))=='disabled' and
                    flow_runner.kwargs['currency_target_level']==7 and str(ui.currency_level_combo.cget('state'))=='disabled')
                flow_runner.release.set()
                pump(root,lambda:not ui.busy)
                check('currency_flow_stops_partial_without_saving','已验证 1 个节点' in ui.currency_observation.get() and
                    '玩法未完成' in ui.summary.get() and config.read_bytes()==original and
                    str(ui.currency_level_combo.cget('state'))=='readonly')
                ui.currency_target_level.set('保持')
                ui._show_page('currency_wars')
                pump(root)
                layout(root)
                ImageGrab.grab(window=root.winfo_id()).save(OUT / 'currency-readonly-result.png')
                ui._show_page('differential_universe')
                check('du_optional_saving_and_rewards_default_off',not ui.du_save.get() and not ui.du_rewards.get())
                check('du_daily_interlude_default_off',not ui.du_daily.get())
                check('du_defaults_to_periodic_named_preset',ui.du_mode.get()=='周期演算' and ui.du_team.get()=='哈哈哈哈')
                check('differential_universe_has_parallel_sidebar_and_action',
                    ui.nav_buttons['differential_universe'].cget('text') == '差分宇宙' and
                    ui.start_button.cget('text') == '开始 3 局自动演算' and
                    str(ui.start_button.cget('state')) == 'normal' and str(ui.reward_button.cget('state')) == 'disabled')
                ui.differential_universe_runs.set('10')
                ui.du_save.set(True)
                ui.du_rewards.set(True)
                ui.du_daily.set(True)
                ui.start_button.invoke()
                pump(root, lambda: ui.runner is not None)
                du_runner = FakeRunner.instances[-1]
                check('du_daily_interlude_is_explicit_in_run_snapshot',du_runner.settings.differential_universe_daily)
                check('differential_universe_is_independent_and_uses_unsaved_run_count',
                    du_runner.kwargs['operation'] == 'differential_universe' and
                    du_runner.settings.differential_universe_runs == 10 and
                    du_runner.settings.differential_universe_mode == 'periodic' and
                    du_runner.settings.differential_universe_team == '哈哈哈哈' and
                    du_runner.settings.differential_universe_save and du_runner.settings.differential_universe_rewards and
                    not any(getattr(du_runner.settings, name) for name in ui.tasks) and
                    not du_runner.settings.auto_launch and config.read_bytes() == original)
                check('differential_universe_busy_locks_controls',
                    all(str(w.cget('state')) == 'disabled' for w in ui.setting_controls))
                du_runner.release.set()
                pump(root, lambda: not ui.busy)
                check('differential_universe_report_is_separate_and_does_not_save',
                    '10/10 局' in ui.summary.get() and '每日刷本预算未使用' in ui.summary.get() and
                    config.read_bytes() == original)
                ui.differential_universe_runs.set('1')
                ui.du_save.set(False)
                ui.du_rewards.set(False)
                ui.du_daily.set(False)
                ui.du_resume_active.set(True)
                ui.du_resume_mode.set('周期难度 5')
                ui.start_button.invoke()
                pump(root,lambda:ui.runner is not None)
                du_resume_runner=FakeRunner.instances[-1]
                check('differential_universe_gui_passes_explicit_resume_context',
                    du_resume_runner.kwargs.get('du_resume_active') is True and
                    du_resume_runner.kwargs.get('du_periodic_rank')==5 and
                    du_resume_runner.kwargs.get('du_runs')==1 and
                    str(ui.du_resume_combo.cget('state'))=='disabled')
                du_resume_runner.release.set()
                pump(root,lambda:not ui.busy)
                check('differential_universe_resume_does_not_save_daily_settings',
                    config.read_bytes()==original and str(ui.du_resume_combo.cget('state'))=='readonly')
                ui.du_resume_active.set(False)
                ui.du_resume_mode.set('常规演算')
                fake.Runner = LateFinishRunner
                try:
                    ui._currency_wars()
                    pump(root, lambda: ui.runner is not None and ui.runner.early.is_set())
                    delayed = ui.runner
                    pump(root, lambda: ui.events.empty())
                    check('early_finished_keeps_worker_and_actions_locked', ui.busy and ui.worker.is_alive() and str(ui.start_button.cget('state')) == 'disabled')
                    before = len(FakeRunner.instances)
                    ui._start()
                    ui._check()
                    check('early_finished_cannot_start_daily_or_detection', len(FakeRunner.instances) == before and ui.runner is delayed)
                    delayed.tail.set()
                    pump(root, lambda: not ui.busy)
                    check('terminal_state_waits_for_worker_exit', not ui.worker.is_alive())
                    LateFinishRunner.fail_after_finish = True
                    ui._currency_wars()
                    pump(root, lambda: ui.runner is not None and ui.runner.early.is_set())
                    ui.runner.tail.set()
                    pump(root, lambda: not ui.busy)
                    check('backend_exception_after_early_finish_is_visible_failure', '失败' in ui.currency_status.get() and '模拟完成通知后的异常' in ui.summary.get())
                finally:
                    fake.Runner = FakeRunner
                    LateFinishRunner.fail_after_finish = False
                    if ui.runner and isinstance(ui.runner, LateFinishRunner):
                        ui.runner.tail.set()
                        ui.worker.join(2)
                ui._show_page('home')
                check('currency_navigation_restores_daily_primary_action', ui.start_button.cget('text') == '开始每日')
                # The resource draft is deliberately invalid; reward-only must ignore it.
                ui._reward_only()
                pump(root, lambda: ui.runner is not None)
                FakeRunner.instances[-1].release.set()
                pump(root, lambda: not ui.busy)
                check('reward_only_ignores_irrelevant_invalid_battle_draft', not errors and config.read_bytes() == original)
            # Restore a valid selected draft. Starting it must not save.
            for key, value in ui.tasks.items():
                value.set(key not in ('mail', 'battlepass'))
            if PACKAGE == 'autohsr':
                ui.stamina_limit.set('10')
                ui.rounds.set('1')
                ui.challenge_count.set('1')
                ui.target_name.set('回忆之蕾')
            else:
                ui.promoter.set('')
            ui.auto_launch.set(not ui.settings.auto_launch)
            if PACKAGE == 'autohsr':
                before_count = len(FakeRunner.instances)
                with patch('autohsr.recovery.recovery_state', return_value=dict(blocked=True, corrupt=False, spent=210, pending=10)):
                    ui._start()
                check('declining_new_budget_does_not_start_or_save', len(FakeRunner.instances) == before_count and config.read_bytes() == original)
            ui._start()
            pump(root, lambda: ui.runner is not None)
            check('start_does_not_save', config.read_bytes() == original)
            check('busy_locks_settings', all(str(w.cget('state')) == 'disabled' for w in ui.setting_controls))
            ui._pause()
            pump(root, lambda: ui.paused)
            check('pause_preserves_control', str(ui.stop_button.cget('state')) == 'normal')
            ui.emit(dict(type='focus_wait', waiting=True))
            pump(root, lambda: ui.events.empty())
            check('manual_pause_is_not_overridden_by_focus_wait', ui.paused)
            ui._stop()
            pump(root, lambda: not ui.busy)
            check('stop_does_not_save', config.read_bytes() == original)
            # Reward-only snapshot: do not persist or restart a battle.
            ui._reward_only()
            pump(root, lambda: ui.runner is not None)
            runner = FakeRunner.instances[-1]
            check('active_plan_identifies_reward_only_snapshot', '仅补领奖' in ui.plan.get())
            check('reward_only_has_no_battle_or_regular_actions',
                not runner.settings.battle if PACKAGE == 'autohsr' else not any((runner.settings.scratch, runner.settings.coffee, runner.settings.video)))
            runner.release.set()
            pump(root, lambda: not ui.busy)
            check('reward_only_does_not_change_saved_plan', config.read_bytes() == original)
            # Failure presentation retains both core proof and the optional cause.
            report = dict(status='partial', daily_verified=PACKAGE == 'autohsr', engagement=200,
                stamina_spent=210 if PACKAGE == 'autohsr' else 0, stamina_limit=240, stamina_pending=10,
                error='模拟邮件入口未识别', safe_next='人工返回主界面后仅补领奖', results=[
                    dict(task='mail' if PACKAGE == 'autohsr' else 'video', status='partial', detail='模拟入口未识别'),
                    dict(task='close_game', status='skipped', detail='本轮未完整核实')])
            (ui._finish if PACKAGE == 'autohsr' else ui._finished)(report)
            check('failure_cause_next_action_and_exit_are_visible', all(x in ui.summary.get() for x in ('原因', '下一步', '游戏保留')))
            ui._show_page('home')
            pump(root)
            layout(root)
            ImageGrab.grab(window=root.winfo_id()).save(OUT / 'failure-recovery.png')
            # A long diagnostic can be stopped cooperatively; discard its result.
            started, release = threading.Event(), threading.Event()
            def inspect(_):
                started.set()
                release.wait(4)
                return dict(title='cancelled mock', width=1920, height=1080)
            fake.inspect_game = inspect
            ui._check()
            pump(root, lambda: started.is_set())
            ui._stop()
            release.set()
            pump(root, lambda: not ui.busy)
            check('diagnostic_stop_discards_result', '停止' in ui.status.get())
            check('failed_or_cancelled_diagnostic_does_not_save', config.read_bytes() == original)
            # Explicit save and dirty-close cancel/discard.
            ui._save_settings()
            check('explicit_save_persists', config.read_bytes() != original and not errors)
            saved = config.read_bytes()
            ui.auto_launch.set(not ui.auto_launch.get())
            with patch.object(module.messagebox, 'askyesnocancel', return_value=None):
                ui._close()
            check('dirty_close_cancel_keeps_window_and_file', not ui.closing and config.read_bytes() == saved)
            root.geometry('1100x800')
            for key in ui.pages:
                ui._show_page(key)
                pump(root)
                layout(root)
            check('minimum_layout_all_pages', True)
            with patch.object(module.messagebox, 'askyesnocancel', return_value=False):
                ui._close()
            check('dirty_close_discard_does_not_save', config.read_bytes() == saved)
        finally:
            if getattr(ui, 'runner', None):
                ui.runner.stop()
            if getattr(ui, 'worker', None):
                ui.worker.join(2)
            try:
                for token in root.tk.splitlist(root.tk.call('after', 'info')):
                    root.after_cancel(token)
                if getattr(ui, 'overlay', None):
                    ui.overlay.close()
                root.destroy()
            except tk.TclError:
                pass
        if PACKAGE == 'autohsr':
            for action in ('currency_wars', 'check'):
                root = tk.Tk()
                ui = Window(root, config)
                callback_errors = []
                root.report_callback_exception = lambda *args: callback_errors.append(args)
                began, unblock = threading.Event(), threading.Event()
                def blocked_check(_):
                    began.set()
                    unblock.wait(3)
                    return dict(title='closing diagnostic', width=1920, height=1080)
                try:
                    if action == 'currency_wars':
                        ui._currency_wars()
                        # Close before runner_ready is necessarily drained.
                    else:
                        fake.inspect_game = blocked_check
                        ui._check()
                        pump(root, lambda: began.is_set())
                    ui._close()
                    check('close_requests_stop_' + action, ui.closing and ui.stop_requested.is_set())
                    unblock.set()
                    pump(root, lambda: ui.worker is not None and not ui.worker.is_alive())
                    check('close_waits_for_worker_' + action, not callback_errors and config.read_bytes() == saved)
                finally:
                    unblock.set()
                    if ui.runner:
                        ui.runner.stop()
                    if ui.worker:
                        ui.worker.join(2)
                    try:
                        for token in root.tk.splitlist(root.tk.call('after', 'info')):
                            root.after_cancel(token)
                        root.destroy()
                    except tk.TclError:
                        pass
    result = dict(product=PACKAGE, mock_backend=True, game_started=False, checks=checks, count=len(checks))
    (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
