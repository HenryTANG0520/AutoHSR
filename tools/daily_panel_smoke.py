"""Exercise the daily guide content with local fixtures and a fake dispatcher."""

import hashlib
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import Mock, patch

from ux_smoke import Settings, Window, module
from autohsr.desktop_daily import ASSIGNMENT_FLOW, ASSIGNMENTS, DRAFT, OPEN_TARGET, PREVIEW, DailyPanel, assignment_runner
from autohsr.dungeon_ui import show_advanced
from autohsr.power_plan_ui import result_text, rows, show as show_power_plan


def replace_panel(panel):
    snapshot = panel.snapshot_draft()
    rebuilt = DailyPanel(panel.master, panel.ui, start=panel.start)
    rebuilt.restore_draft(snapshot)
    panel.destroy()
    rebuilt.grid(row=0, column=0, sticky='nsew')
    rebuilt.tkraise()
    return rebuilt


def main():
    with tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)):
        directory = Path(folder)
        config = directory / 'config.json'
        Settings().save(config)
        original = config.read_bytes()
        runner = assignment_runner(Settings(), Mock(), root=directory)
        frozen, options = runner.specs['assignments']
        assert options['assignments_only'] and frozen.assignments
        assert not any((frozen.battle, frozen.daily, frozen.mail, frozen.battlepass, frozen.redemption_enabled))
        for scale in (1., 1.5, 2.):
            root = tk.Tk()
            root.attributes('-alpha', 0)
            root.attributes('-disabled', True)
            root.tk.call('tk', 'scaling', scale * 96 / 72)
            ui = Window(root, config)
            try:
                root.update()
                ui._show_page('home')
                start = Mock()
                panel = DailyPanel(ui.guide.content, ui, start=start)
                panel.grid(row=0, column=0, sticky='nsew')
                panel.tkraise()
                panel.invoke_primary()
                start.assert_called_once_with(ASSIGNMENTS)
                child = directory / 'assignment.json'
                child_report = dict(operation='daily', report_saved=True, status='success', results=[dict(
                    task='assignments', status='ok', detail='持续委托暂无可收取奖励，已核对原委托进行中。',
                )])
                child.write_text(json.dumps(child_report, ensure_ascii=False), encoding='utf-8')
                receipt = dict(operation='task_workflow', report_saved=True, workflow=dict(name=ASSIGNMENT_FLOW,
                    steps=[dict(step='assignments', task='daily', status='success', account_verified=True,
                    source=dict(path=str(child), sha256=hashlib.sha256(child.read_bytes()).hexdigest()))]))
                panel.present(ASSIGNMENTS, receipt)
                panel = replace_panel(panel)
                assert panel.assignment_title.get() == '委托状态已核实' and '暂无' in panel.assignment_detail.get()
                with patch.object(ui, '_open_path') as open_path:
                    panel.assignment_record.invoke()
                    open_path.assert_called_once_with(child)
                    open_path.reset_mock()
                    child.write_text('{}', encoding='utf-8')
                    panel.assignment_record.invoke()
                    open_path.assert_not_called()
                assert '待核对' in panel.assignment_title.get() and panel.assignment_record.instate(('disabled',))
                panel = replace_panel(panel)
                assert panel.assignment_record.instate(('disabled',))
                child.write_text(json.dumps(child_report, ensure_ascii=False), encoding='utf-8')
                step = receipt['workflow']['steps'][0]
                step['account_verified'] = False
                panel.present(ASSIGNMENTS, receipt)
                assert '待核对' in panel.assignment_title.get() and '已核对' not in panel.assignment_detail.get()
                assert not panel.assignment_record.instate(('disabled',))
                step['account_verified'] = True
                child_report['status'] = 'partial'
                child.write_text(json.dumps(child_report, ensure_ascii=False), encoding='utf-8')
                step['source']['sha256'] = hashlib.sha256(child.read_bytes()).hexdigest()
                panel.present(ASSIGNMENTS, receipt)
                assert '待核对' in panel.assignment_title.get() and '已核对' not in panel.assignment_detail.get()

                ui._show_page('tasks')
                panel.show(PREVIEW)
                root.geometry('%dx%d' % root.minsize())
                root.update()
                assert panel.winfo_viewable() and panel.generate.winfo_viewable() and panel.open_target.winfo_viewable()
                assert panel.generate.winfo_rootx() + panel.generate.winfo_width() <= panel.winfo_rootx() + panel.winfo_width()
                assert panel.primary_label == '预览材料'
                initial_entry = panel.entry_status.get()
                start.return_value = False
                panel.open_target.invoke()
                start.assert_called_with(OPEN_TARGET)
                assert panel.entry_status.get() == initial_entry
                start.return_value = True
                panel.open_target.invoke()
                start.assert_called_with(OPEN_TARGET)
                assert '正在核对' in panel.entry_status.get()
                panel.present(OPEN_TARGET, dict(status='success', report_saved=False,
                    build_target=dict(entry_input='sent', page_verified=True)))
                assert '反馈待核对' in panel.entry_status.get()
                panel.present(OPEN_TARGET, dict(status='success', report_saved=True,
                    build_target=dict(entry_input='sent', page_verified=True)))
                panel = replace_panel(panel)
                assert '已核实培养目标页' in panel.entry_status.get() and panel.build_title.get() == '等待预览'
                panel.invoke_primary()
                start.assert_called_with(PREVIEW)
                calls_before_draft = start.call_count
                assert panel.generate.instate(('disabled',))
                item = dict(category='calyx_golden', target='回忆之蕾', location='城郊雪原', count=2)
                report = dict(report_saved=True, status='partial', build_target=dict(preview=dict(
                    state='catalogue_candidates', material='漫游指南', held=0,
                    candidates=[dict(item, location='绘世学院', stamina_cost=10, max_challenges_by_config=24),
                                dict(item, stamina_cost=10, max_challenges_by_config=24)],
                )))
                panel.present(PREVIEW, report)
                assert '当前持有 0' in panel.build_detail.get() and panel.source.current() == -1
                panel.source.current(1)
                panel.source.event_generate('<<ComboboxSelected>>')
                root.update()
                panel.count.set('0')
                panel.generate.invoke()
                assert '1～6' in panel.draft_detail.get() and start.call_count == calls_before_draft
                panel.count.set('02')
                panel = replace_panel(panel)
                assert panel.section == PREVIEW and panel.source.current() == 1 and panel.count.get() == '02'
                panel.set_busy(True)
                panel.invoke_primary()
                panel._open_target()
                assert panel.open_target.instate(('disabled',)) and panel.generate.instate(('disabled',))
                assert start.call_count == calls_before_draft
                panel.set_busy(False)
                panel.generate.invoke()
                operation, = start.call_args.args
                selection = start.call_args.kwargs['build_target_selection']
                assert operation == DRAFT and (selection.material, selection.location, selection.count) == ('漫游指南', item['location'], 2)
                plan = directory / 'power-plan.json'
                raw = json.dumps([item], ensure_ascii=False).encode('utf-8')
                plan.write_bytes(raw)
                draft = dict(report_saved=True, status='success', run_dir=str(directory), build_target=dict(draft=dict(
                    state='prepared', file=plan.name, sha256=hashlib.sha256(raw).hexdigest(), items=[item],
                )))
                panel.present(DRAFT, draft)
                assert '草稿已生成' in panel.draft_detail.get() and rows(ui) == []
                panel = replace_panel(panel)
                assert not panel.add_draft.instate(('disabled',)) and panel.source.current() == 1
                plan.write_bytes(b'[]')
                panel.add_draft.invoke()
                assert '待核对' in panel.draft_detail.get() and rows(ui) == []
                plan.write_bytes(raw)
                before = ui.tasks['battle'].get(), ui.power_mode.get()
                panel.add_draft.invoke()
                assert rows(ui) == [item] and (ui.tasks['battle'].get(), ui.power_mode.get()) == before
                assert panel.add_draft.instate(('disabled',)) and config.read_bytes() == original
                panel = replace_panel(panel)
                panel.present(DRAFT, draft)
                assert panel.add_draft.instate(('disabled',)) and '已加入' in panel.draft_detail.get()
                assert rows(ui) == [item]
                show_power_plan(ui, return_page='tasks')
                panel.grid_remove()
                root.update()
                ui.settings_shell.see(ui.power_support_button)
                assert ui.power_support_button.winfo_ismapped()
                assert ui.power_plan_list.item('0', 'values')[1] == item['target']
                with patch('autohsr.support_ui.SupportDialog') as dialog:
                    ui.power_support_button.invoke()
                    dialog.assert_called_once_with(ui)
                completed = dict(report_saved=True, support_selections=[dict(state='borrowed', fallback_used=True)],
                                 power_plan=dict(run_status='complete', goal_complete=False,
                                                 items=[item], before=[0], done=[1]))
                status = result_text(completed)
                assert '剩余目标 1 次' in status and '已核实支援入队（备用好友）' in status
                ui._show_page('tasks')
                show_advanced(ui)
                root.update()
                assert ui.dungeon_support_button.winfo_viewable()
                with patch('autohsr.support_ui.SupportDialog') as dialog:
                    ui.dungeon_support_button.invoke()
                    dialog.assert_called_once_with(ui)
            finally:
                ui.closing = True
                root.update_idletasks()
                for job in root.tk.splitlist(root.tk.call('after', 'info')):
                    if str(root.tk.call('after', 'info', job)[0]).endswith('_drain'):
                        root.after_cancel(job)
                root.destroy()
    print('Daily guide checks passed at 100%, 150% and 200%.')


if __name__ == '__main__':
    main()
