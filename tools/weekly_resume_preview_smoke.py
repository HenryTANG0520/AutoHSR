"""Cold-start continuation cards use the original scope, with no game calls."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from PIL import ImageGrab
from ux_smoke import ROOT, Settings, Window, module
from weekly_currency_smoke import UIFactory, ActualPlanRunner, runtime, settings, points
from autohsr.currency_wars_loop_store import LoopStore

OUT = ROOT/'runs/weekly-resume-preview-ui'


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, callbacks = [], []
    def check(name, value):
        assert value, (name, callbacks)
        checks.append(name)
    for scenario in ('original_daily', 'weekly_only', 'changed_report'):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder)
            seed = UIFactory(local, [0, 0, 18000])
            flags = dict(assignments=False, battle=False, daily=False, mail=False, battlepass=False) if scenario == 'weekly_only' else {}
            owner = None
            def emit(event):
                if event['type'] == 'currency_loop_progress':
                    owner.stop()
            owner = ActualPlanRunner(settings(stamina_limit=120, challenge_count=12, **flags), emit,
                                     root=local/'runs', runner_factory=seed, now=points.NOW)
            with runtime(local):
                first = owner.run()
            assert first.status == 'stopped', first.error
            if scenario == 'changed_report':
                store = LoopStore(local/'runs'); store.load()
                path = Path(store.data['weekly_plan']['daily']['path'])
                path.write_bytes(path.read_bytes()+b' ')
            config = local/'config.json'
            Settings(overlay_logs=False, mail=True).save(config)
            before = hashes(local)
            for scale in (1., 1.5, 2.):
                prefix = scenario+'_'+str(scale)
                with patch.object(module, 'ROOT', local), \
                     patch('autohsr.plan_runner.PlanRunner', side_effect=AssertionError('Browsing must not start a plan')):
                    root = tk.Tk(); root.tk.call('tk', 'scaling', scale*96/72)
                    root.report_callback_exception = lambda kind, value, trace: callbacks.append(str(value))
                    ui = Window(root, config)
                    try:
                        root.update()
                        if scenario == 'changed_report':
                            check(prefix+'_damaged_receipt_has_no_continue', ui.start_button.cget('text') == '开始计划' and '待核对' in ui.recovery_hint.get())
                            check(prefix+'_damaged_receipt_is_not_presented_as_old_success', not ui.table.item('battle')['has_result'] and '原日常' not in ui.table.item('daily', 'values')[1])
                            continue
                        check(prefix+'_continue_uses_frozen_goal', ui.start_button.cget('text') == '继续周常' and '上限 2 局' in ui.weekly_status.get())
                        check(prefix+'_current_meter_is_not_verified', ui.training_result.get() == 'unknown' and ui.confirmed_stamina == 0 and not ui._has_run)
                        if scenario == 'original_daily':
                            check(prefix+'_original_battle_counts_replace_draft', ui.table.resource_metrics('battle') == ('12/12 次', '已用 120 开拓力') and ui.challenge_count.get() == '24')
                            check(prefix+'_original_daily_status', ui.table.item('daily', 'values')[1] == '原日常完成' and '沿用原报告' in ui.daily_caption.get())
                            check(prefix+'_unrequested_mail_is_not_a_new_task', ui.table.item('mail', 'values')[1] == '本次不执行' and ui.table.action_label('mail') == '查看安排')
                        else:
                            check(prefix+'_weekly_only_has_no_daily_metrics', all(ui.table.resource_metrics(key) is None and ui.table.item(key, 'values')[1] == '本次不执行' for key in ui.tasks))
                            check(prefix+'_weekly_only_caption', ui.daily_caption.get() == '日常 · 本次不执行')
                        rows = copy.deepcopy(ui.table.records)
                        ui.challenge_count.set('bad'); ui.stamina_limit.set('bad'); ui.tasks['daily'].set(False)
                        ui.weekly_runs.set('10'); ui.weekly_enabled.set(False)
                        root.update()
                        check(prefix+'_draft_edits_keep_original_scope', ui.table.records == rows and '上限 2 局' in ui.weekly_status.get())
                        ui.table.selected = 'daily'
                        ui.table.activate(); root.update()
                        check(prefix+'_card_opens_original_detail_without_running', ui.summary_dialog.winfo_exists() and not ui.busy and not ui.worker)
                        ui.summary_dialog.destroy(); root.update()
                        for state in ('zoomed', 'normal', 'zoomed', 'normal'):
                            root.state(state); root.update(); ui.responsive_layout.fit(); root.update()
                            check(prefix+'_'+state+'_layout_preserves_scope', ui.table.records == rows and ui.start_button.cget('text') == '继续周常')
                        ImageGrab.grab(window=root.winfo_id()).save(OUT/(prefix+'.png'))
                    finally:
                        ui.closing = True
                        for token in root.tk.splitlist(root.tk.call('after', 'info')):
                            if str(root.tk.call('after', 'info', token)[0]).endswith('_drain'):
                                root.after_cancel(token)
                        root.destroy()
            check(scenario+'_all_evidence_and_config_unchanged', before == hashes(local))
    check('no_callback_errors', not callbacks)
    (OUT/'result.json').write_text(json.dumps(dict(count=len(checks), checks=checks, game_started=False,
        synthetic_goal=True, config_and_original_evidence_unchanged=True), ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(dict(checks=len(checks), game_started=False)))


if __name__ == '__main__':
    main()
