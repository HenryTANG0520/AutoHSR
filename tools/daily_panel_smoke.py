"""Exercise the daily guide content with local fixtures and a fake dispatcher."""

import hashlib
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import Mock, patch

from ux_smoke import Settings, Window, module
from autohsr.desktop_daily import ASSIGNMENTS, DRAFT, OPEN_TARGET, PREVIEW, DailyPanel
from autohsr.task_workflow import ASSIGNMENT_FLOW, assignment_runner
from autohsr.desktop_dialogs import _work_area
from autohsr.dungeon_ui import show_advanced
from autohsr.power_plan_ui import result_text, rows, show as show_power_plan
from tools.gui_layout import check_layout


def replace_panel(panel):
    snapshot = panel.snapshot_draft()
    rebuilt = DailyPanel(panel.master, panel.ui, start=panel.start)
    rebuilt.restore_draft(snapshot)
    panel.destroy()
    rebuilt.grid(row=0, column=0, sticky='nsew')
    rebuilt.tkraise()
    return rebuilt


def check_cultivation_preview(root, ui, default_geometry):
    prior = ui.power_rows.get()
    long_rows = [dict(observed_needed=[999_999_999] * 4, shown_stamina=10) for _ in range(5)]
    long_rows[0]['identified_materials'] = [dict(material='银河沙盘', amount=999_999_999, slot=0)]
    route = dict(category='calyx_crimson', target='虚无之蕾', location='「辉痕圣林」神悟树庭',
                 stamina_cost=10, max_challenges_by_config=24, max_draft_challenges_by_config=6)

    with patch.object(ui, '_start_build_target', return_value=True) as start:
        def preview(fields, status='partial'):
            ui.start_button.invoke()
            operation, selection, present = start.call_args.args
            assert operation == PREVIEW and selection is None
            present(dict(status=status, report_saved=True, build_target=dict(preview=fields)))
            root.update()

        for geometry in (default_geometry, '%dx%d' % root.minsize()):
            root.geometry(geometry)
            root.update()
            ui.responsive_layout.fit()
            root.update()
            ui._show_daily_panel(PREVIEW, focus=False)
            panel = ui.daily_panel
            preview(dict(state='target_resources_needed', shortfall_rows=long_rows,
                         suggestion_reason='material_shortfall_unbound'))
            detail = panel.build.grid_slaves(row=2, column=0)[0]
            assert '银河沙盘 缺口 999999999 件' in panel.build_detail.get()
            assert panel.build_detail.get().count('999999999') == 21
            assert detail.winfo_height() >= detail.winfo_reqheight() > panel.count_hint.winfo_height()
            check_layout(root, work_area=_work_area)

            candidate_preview = dict(state='catalogue_candidates', material='法吉娜之心', held=999_999_999,
                                     candidates=[route], suggestion_reason='material_shortfall_unbound')
            for blocker in ('incomplete_source', 'repeated_location'):
                preview(dict(candidate_preview, candidates=[dict(route, manual_draft_blocker=blocker)]))
                assert panel.source.get() == '来源待核实' and '草稿待核对' in panel.draft_detail.get()
                assert all(widget.instate(('disabled',)) for widget in
                           (panel.source, panel.times, panel.generate, panel.add_draft))
                assert not ui.start_button.instate(('disabled',))
                next_focus = panel.open_target.tk_focusNext()
                assert next_focus not in (panel.source, panel.times, panel.generate, panel.add_draft)

            preview(candidate_preview)
            panel.source.current(0)
            panel.source.event_generate('<<ComboboxSelected>>')
            root.update()
            assert '「辉痕圣林」神悟树庭' in panel.source.get() and panel.source.xview() == (0.0, 1.0)
            assert panel.source.tk_focusNext() is panel.times and panel.times.tk_focusNext() is panel.generate
            assert panel.count_hint.cget('text') == '手填 1～6 次' and float(panel.times.cget('to')) == 6
            panel.count.set('6')
            check_layout(root, work_area=_work_area)

            lowered = dict(route, max_challenges_by_config=2, max_draft_challenges_by_config=2)
            preview(dict(candidate_preview, candidates=[lowered]))
            assert panel.count.get() == '' and panel.source.current() == -1 and panel.generate.instate(('disabled',))
            panel.source.current(0)
            panel.source.event_generate('<<ComboboxSelected>>')
            root.update()
            assert panel.count_hint.cget('text') == '手填 1～2 次' and float(panel.times.cget('to')) == 2
            calls = start.call_count
            panel.count.set('3')
            panel.generate.invoke()
            assert start.call_count == calls and '最多 2 次' in panel.draft_detail.get()
            panel.count.set('2')
            panel.generate.invoke()
            operation, selection, _ = start.call_args.args
            assert operation == DRAFT and selection.count == 2 and selection.location == route['location']
            assert ui.power_rows.get() == prior

            preview(candidate_preview, status='stopped')
            assert panel.build_title.get() == '已停止'
            assert all(widget.instate(('disabled',)) for widget in
                       (panel.source, panel.times, panel.generate, panel.add_draft))


def main():
    with (tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)),
          patch('autohsr.app.find_game', side_effect=AssertionError('Offline smoke accessed game lookup')) as find_game):
        directory = Path(folder)
        config = directory / 'config.json'
        saved = dict(category='calyx_crimson', target='智识之蕾', location='海原电视塔', count=3)
        Settings(power_plan=[saved]).save(config)
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
                default_geometry = root.geometry()
                existing = [saved, dict(category='calyx_crimson', target='智识之蕾', location='铆钉镇', count=2)]
                assert rows(ui) == [saved]
                ui.power_rows.set(json.dumps(existing, ensure_ascii=False))
                ui._show_page('home')
                start = Mock()
                panel = DailyPanel(ui.guide.content, ui, start=start)
                panel.grid(row=0, column=0, sticky='nsew')
                panel.tkraise()
                panel.invoke_primary()
                start.assert_called_once_with(ASSIGNMENTS)
                parent_dir = directory / f'assignment-flow-{scale}'
                child_dir = directory / f'assignment-run-{scale}'
                parent_dir.mkdir()
                child_dir.mkdir()
                parent, child = parent_dir / 'report.json', child_dir / 'report.json'
                child_report = dict(operation='daily', report_saved=True, status='success', run_dir=str(child_dir), results=[dict(
                    task='assignments', status='ok', detail='持续委托暂无可收取奖励，已核对原委托进行中。',
                )])
                child.write_text(json.dumps(child_report, ensure_ascii=False), encoding='utf-8')
                receipt = dict(operation='task_workflow', report_saved=True, status='success', run_dir=str(parent_dir),
                    workflow=dict(name=ASSIGNMENT_FLOW, identity=dict(verified=True, account_changed=False),
                    steps=[dict(step='assignments', type='task', task='daily', status='success', account_verified=True,
                    source=dict(path=str(child), sha256=hashlib.sha256(child.read_bytes()).hexdigest()))]))
                parent.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
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
                parent.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
                panel.present(ASSIGNMENTS, receipt)
                assert '待核对' in panel.assignment_title.get() and '已核对' not in panel.assignment_detail.get()
                assert not panel.assignment_record.instate(('disabled',))
                step['account_verified'] = True
                child_report['status'] = 'partial'
                child.write_text(json.dumps(child_report, ensure_ascii=False), encoding='utf-8')
                step['source']['sha256'] = hashlib.sha256(child.read_bytes()).hexdigest()
                parent.write_text(json.dumps(receipt, ensure_ascii=False), encoding='utf-8')
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
                assert '草稿已生成' in panel.draft_detail.get() and rows(ui) == existing
                panel = replace_panel(panel)
                assert not panel.add_draft.instate(('disabled',)) and panel.source.current() == 1
                plan.write_bytes(b'[]')
                panel.add_draft.invoke()
                assert '待核对' in panel.draft_detail.get() and rows(ui) == existing
                plan.write_bytes(raw)
                before = ui.tasks['battle'].get(), ui.power_mode.get()
                panel.add_draft.invoke()
                assert rows(ui) == [*existing, item] and (ui.tasks['battle'].get(), ui.power_mode.get()) == before
                assert panel.add_draft.instate(('disabled',)) and config.read_bytes() == original
                panel = replace_panel(panel)
                panel.present(DRAFT, draft)
                assert panel.add_draft.instate(('disabled',)) and '已加入' in panel.draft_detail.get()
                assert rows(ui) == [*existing, item]
                show_power_plan(ui, return_page='tasks')
                panel.grid_remove()
                root.update()
                ui.settings_shell.see(ui.power_support_button)
                assert ui.power_support_button.winfo_ismapped()
                assert ui.power_plan_list.item(str(len(existing)), 'values')[1] == item['target']
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
                check_cultivation_preview(root, ui, default_geometry)
                assert config.read_bytes() == original
            finally:
                ui.closing = True
                root.update_idletasks()
                for job in root.tk.splitlist(root.tk.call('after', 'info')):
                    if str(root.tk.call('after', 'info', job)[0]).endswith('_drain'):
                        root.after_cancel(job)
                root.destroy()
        find_game.assert_not_called()
    print('Daily guide checks passed at 100%, 150% and 200%.')


if __name__ == '__main__':
    main()
