"""Use real local plan orchestration with synthetic game children only."""
from datetime import datetime
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import Mock, patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module, pump
from ui_layout_smoke import check_layout
from autohsr import weekly_plan
from autohsr.tests.test_weekly_plan import du_report

OUT = ROOT/'runs/plan-scope-ui'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, calls, errors = [], [], []
    now = datetime(2026,10,29,10,0,tzinfo=weekly_plan.CHINA)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    def check(name, value):
        assert value, name
        checks.append(name)

    class Child:
        def __init__(self, settings, emit, **options):
            assert options.get('operation') in ('differential_universe', 'currency_wars_points'), 'No game backend is allowed'
            self.options, self.settings = options, settings
            calls.append(options['operation'])
        def run(self):
            if self.options['operation'] == 'currency_wars_points':
                return dict(operation='currency_wars_points',status='partial',report_saved=True,results=[],error='模拟积分未核实')
            guard = self.options['weekly_plan']
            guard.receipt = weekly_plan.WeeklyReceipt(guard.root, 'a'*24, guard.slot)
            guard.already_complete = not guard.receipt.begin(guard.settings)
            folder = guard.root/('synthetic-'+str(len(calls)))
            folder.mkdir(parents=True)
            return du_report(folder, self.options['du_runs'])
        def stop(self):
            pass
        def toggle_pause(self):
            return False

    fake = types.ModuleType('autohsr.app')
    fake.Runner = Child
    with patch.dict(sys.modules, {'autohsr.app':fake}), patch.object(weekly_plan, 'datetime', Clock):
        from autohsr import plan_runner
        with patch.object(plan_runner, 'datetime', Clock):
            for scale in (1.,1.25,1.5,2.):
                now = datetime(2026,10,29,10,0,tzinfo=weekly_plan.CHINA)
                prefix = str(scale)+'_'
                with tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)):
                    config = Path(folder)/'config.json'
                    Settings(assignments=False,battle=False,daily=False,mail=False,battlepass=False,
                             weekly_enabled=True,weekly_day=4,weekly_time='11:00').save(config)
                    original = config.read_bytes()
                    root = tk.Tk()
                    root.tk.call('tk','scaling',scale*96/72)
                    root.report_callback_exception = lambda kind,value,trace: errors.append(str(value))
                    ui = Window(root, config)
                    root.iconify = Mock(wraps=root.iconify)
                    try:
                        root.update()
                        before = len(calls)
                        ui.start_button.invoke()
                        pump(root, lambda: not ui.busy)
                        root.update()
                        raw = json.loads(ui.report_text.get('1.0','end-1c'))
                        summary = ui.summary.get()
                        check(prefix+'future_weekly_only_has_no_child_or_minimization', len(calls)==before and not root.iconify.called)
                        check(prefix+'noop_is_clear_and_keeps_deadline', '本次无需执行' in ui.status.get() and
                              '周常未到期' in summary and '2026-10-29 11:00' in summary)
                        check(prefix+'unrequested_daily_and_zero_costs_are_absent', '实训' not in summary and
                              '开拓力' not in summary and '游戏保留' not in summary)
                        check(prefix+'unrequested_cards_stay_unjoined', all(ui.table.item(key,'values')[1]=='未加入' and
                              not ui.table.item(key,'has_result') for key in ui.tasks))
                        check(prefix+'backend_report_status_and_frozen_scope_are_preserved', raw['status']=='success' and
                              raw['weekly_plan']['daily_tasks']==[] and raw['weekly_plan']['status']=='not_due')
                        check_layout(root)
                        if scale == 1.25:
                            ImageGrab.grab(window=root.winfo_id()).save(OUT/'not-due.png')
                        ui._show_summary()
                        root.update()
                        text = ui.summary_detail_text.get('1.0','end-1c') if hasattr(ui,'summary_detail_text') else None
                        dialog = ui.summary_dialog
                        if text is None:
                            text = next(w for f in dialog.winfo_children() for w in f.winfo_children()
                                        if w.winfo_class()=='Text').get('1.0','end-1c')
                        check(prefix+'one_click_details_keep_schedule', '2026-10-29 11:00' in text and '周常未到期' in text)
                        if scale == 1.25:
                            ImageGrab.grab(window=dialog.winfo_id()).save(OUT/'not-due-detail.png')
                        root.tk.call(dialog.protocol('WM_DELETE_WINDOW'))
                        root.update()
                        now = datetime(2026,10,29,11,0,tzinfo=weekly_plan.CHINA)
                        pump(root, lambda: '到期，运行时核对' in ui.weekly_status.get())
                        check(prefix+'time_change_refreshes_preview_without_rewriting_result', ui.summary.get()==summary and
                              '本次无需执行' in ui.status.get() and not root.iconify.called and len(calls)==before)
                        ui.tasks['daily'].set(True)
                        root.update()
                        check(prefix+'draft_changes_do_not_reclassify_the_frozen_result', ui.summary.get()==summary and
                              json.loads(ui.report_text.get('1.0','end-1c'))==raw)
                        ui.tasks['daily'].set(False)
                        ui.start_button.invoke()
                        pump(root, lambda: not ui.busy)
                        root.update()
                        due = json.loads(ui.report_text.get('1.0','end-1c'))
                        check(prefix+'due_weekly_starts_one_synthetic_child_and_minimizes_on_phase', len(calls)==before+1 and root.iconify.call_count==1)
                        check(prefix+'weekly_completion_has_no_unrequested_daily_warning', '周常演算完成' in ui.status.get() and
                              '实训' not in ui.summary.get() and '开拓力' not in ui.summary.get() and
                              '周积分奖励未核实' in ui.summary.get())
                        check(prefix+'completed_report_keeps_empty_daily_scope_and_week_proof', due['weekly_plan']['daily_tasks']==[] and
                              due['weekly_plan']['status']=='complete' and due['differential_universe']['completed_runs']==1)
                        if scale == 1.25:
                            ImageGrab.grab(window=root.winfo_id()).save(OUT/'weekly-complete.png')
                        ui.weekly_mode.set('货币战争')
                        root.iconify.reset_mock()
                        ui.start_button.invoke()
                        pump(root, lambda: not ui.busy)
                        check(prefix+'currency_points_failure_keeps_partial_after_weekly_phase', len(calls)==before+2 and
                              root.iconify.called and '部分完成' in ui.status.get() and '模拟积分未核实' in ui.summary_label.message())
                        check(prefix+'unrequested_daily_result_is_not_claimed', '日常结果' not in ui.summary.get())
                        ui._finish(dict(operation='plan',status='partial',report_saved=False,daily_verified=True,
                            battle_completed=12,battle_requested=24,stamina_spent=120,stamina_pending=10,
                            immersifiers_spent=2,immersifiers_pending=None,error='结算画面未核实。',safe_next='核对原结算与报告。',
                            results=[],weekly_plan=dict(daily_tasks=['battle','daily'],status='needs_review',
                            week='2026-10-26',message='周常未完成。')))
                        root.update()
                        check(prefix+'actual_scope_preserves_costs_and_verified_daily_even_after_draft_changed', all(value in ui.summary.get()
                              for value in ('12/24 次','已确认 120 开拓力','10 开拓力待核对','已确认 2 沉浸器',
                                            '沉浸器待核对','实训奖励已核实','核对原结算与报告')))
                        check(prefix+'save_failure_and_uncertain_cost_remain_prominent', all(value in ui.summary_label.message()
                              for value in ('报告未保存','10 开拓力待核对','沉浸器待核对','结算画面未核实')) and ui.training_meter.verified)
                        check(prefix+'configuration_is_never_saved', config.read_bytes()==original)
                        check_layout(root)
                    finally:
                        if ui.worker:
                            ui.worker.join(timeout=2)
                        ui.closing = True
                        for token in root.tk.splitlist(root.tk.call('after','info')):
                            if str(root.tk.call('after','info',token)[0]).endswith('_drain'):
                                root.after_cancel(token)
                        root.destroy()
    check('no_callback_errors', not errors)
    result = dict(count=len(checks),checks=checks,game_started=False,real_game_calls=0,synthetic_children=len(calls))
    (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
