"""Independent daily attachment views using synthetic reports and withdrawn Tk."""
from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event
import time
import tkinter as tk
from types import ModuleType
import unittest
from unittest.mock import Mock, patch

from autohsr import windows  # Set DPI awareness before creating a Tk window.
from autohsr.config import Settings
from autohsr.desktop_daily import ASSIGNMENTS, BATTLEPASS, MAIL, attachment_result
from autohsr.gui import AutoHSRWindow


FLOWS = {'mail': '独立邮件样本', 'battlepass': '独立勋礼样本'}


def backend(factory=None):
    module = ModuleType('autohsr.daily_attachments')
    module.ATTACHMENT_FLOWS = FLOWS
    module.attachment_runner = factory if factory is not None else Mock(side_effect=AssertionError('no native runner'))
    return patch.dict(sys.modules, {module.__name__: module})


def write_report(path, report):
    path.write_text(json.dumps(report, ensure_ascii=False), 'utf8')


def receipt(root, task, outcome, claims=(), *, status='success', child_status=None, row=True, account=True,
            bootstrap=False):
    root = root.resolve()
    parent_dir, child_dir = root / 'parent', root / 'child'
    parent_dir.mkdir(parents=True)
    child_dir.mkdir()
    parent, child = parent_dir / 'report.json', child_dir / 'report.json'
    child_status = child_status or status
    results = [dict(task=task, status='ok' if child_status == 'success' else child_status,
                    detail='本次子任务详情。', attachment_outcome=outcome, verified_claims=list(claims))] if row else []
    if bootstrap:
        results = [dict(task='run', status='failed', detail='当前未找到游戏窗口。')]
    write_report(child, dict(operation='daily', status=child_status, report_saved=True, run_dir=str(child_dir),
                             results=results))
    step = dict(type='task', task='daily', step=task, status=child_status, account_verified=account,
                source=dict(path=str(child), sha256=hashlib.sha256(child.read_bytes()).hexdigest()))
    report = dict(operation='task_workflow', status=status, report_saved=True, run_dir=str(parent_dir),
                  workflow=dict(name=FLOWS[task], steps=[step], identity=dict(verified=account, account_changed=False)))
    write_report(parent, report)
    return report, child


class AttachmentResultTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='autohsr-attachment-receipts-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        module = backend()
        module.start()
        self.addCleanup(module.stop)

    def test_claim_and_empty_are_distinct_from_an_unproven_success(self):
        claimed, source = receipt(self.root / 'claimed', 'mail', 'claimed', ['mail_attachments'])
        empty, other = receipt(self.root / 'empty', 'mail', 'empty')
        unknown, _ = receipt(self.root / 'unknown', 'mail', 'unknown')
        self.assertEqual(attachment_result(MAIL, claimed), ('邮件附件已核实领取', '已核实领取 邮件附件。', source))
        self.assertEqual(attachment_result(MAIL, empty), ('暂无可领邮件附件', '已核对当前可领取状态。', other))
        self.assertEqual(attachment_result(MAIL, unknown)[0], '邮件附件结果待核对')

    def test_partial_and_stop_preserve_only_verified_claim_categories(self):
        partial, _ = receipt(self.root / 'partial', 'battlepass', 'unknown', ['battlepass_weekly_tasks'],
                             status='partial')
        label, detail, _ = attachment_result(BATTLEPASS, partial)
        self.assertEqual(label, '部分领取已核实')
        self.assertIn('本周任务经验', detail)
        self.assertIn('其余结果待核对', detail)
        self.assertNotIn('免费等级奖励', detail)
        stopped, _ = receipt(self.root / 'stopped', 'battlepass', 'unknown', ['battlepass_free_levels'],
                             status='stopped')
        self.assertEqual(attachment_result(BATTLEPASS, stopped)[:2], (
            '已停止', '已核实领取 免费等级奖励。其余结果待核对。'))
        before_claim, path = receipt(self.root / 'no-row', 'battlepass', 'unknown', status='stopped', row=False)
        self.assertEqual(attachment_result(BATTLEPASS, before_claim), ('已停止', '请查看本次运行报告。', path))

    def test_identity_scope_unexpected_claims_and_no_field_cannot_claim_success(self):
        wrong, path = receipt(self.root / 'account', 'mail', 'claimed', ['mail_attachments'], account=False)
        self.assertEqual(attachment_result(MAIL, wrong), ('邮件附件结果待核对', '请查看本次运行报告。', path))
        conflicted, _ = receipt(self.root / 'conflict', 'mail', 'empty', ['mail_attachments'])
        self.assertEqual(attachment_result(MAIL, conflicted)[0], '邮件附件结果待核对')
        mixed, _ = receipt(self.root / 'mixed', 'battlepass', 'claimed', ['mail_attachments'])
        self.assertEqual(attachment_result(BATTLEPASS, mixed)[0], '无名勋礼结果待核对')
        self.assertEqual(attachment_result(MAIL, mixed)[0], '邮件附件记录待核对')
        untyped, child = receipt(self.root / 'legacy', 'mail', 'empty')
        value = json.loads(child.read_bytes())
        value['results'][0].pop('attachment_outcome')
        write_report(child, value)
        untyped['workflow']['steps'][0]['source']['sha256'] = hashlib.sha256(child.read_bytes()).hexdigest()
        write_report(Path(untyped['run_dir']) / 'report.json', untyped)
        self.assertEqual(attachment_result(MAIL, untyped)[0], '邮件附件结果待核对')

    def test_child_stop_and_bootstrap_failure_retain_the_original_report_link(self):
        stopped, source = receipt(self.root / 'early-stop', 'battlepass', 'unknown',
                                  status='partial', child_status='stopped', account=False)
        self.assertEqual(attachment_result(BATTLEPASS, stopped), ('已停止', '本次子任务详情。', source))
        failure, other = receipt(self.root / 'bootstrap', 'mail', 'unknown', status='partial',
                                 child_status='failed', account=False, bootstrap=True)
        self.assertEqual(attachment_result(MAIL, failure), ('邮件附件结果待核对', '当前未找到游戏窗口。', other))

    def test_modified_parent_or_child_and_wrong_report_path_fail_closed(self):
        report, child = receipt(self.root / 'tampered', 'mail', 'claimed', ['mail_attachments'])
        parent = Path(report['run_dir']) / 'report.json'
        original_child = child.read_bytes()
        child.write_bytes(original_child + b'\n')
        self.assertEqual(attachment_result(MAIL, report)[::2], ('邮件附件记录待核对', None))
        child.write_bytes(original_child)
        write_report(parent, dict(report, status='partial'))
        self.assertEqual(attachment_result(MAIL, report)[::2], ('邮件附件记录待核对', None))
        forged = deepcopy(report)
        alias = child.with_name('alternate.json')
        alias.write_bytes(original_child)
        forged['workflow']['steps'][0]['source']['path'] = str(alias)
        write_report(parent, forged)
        self.assertEqual(attachment_result(MAIL, forged)[::2], ('邮件附件记录待核对', None))


class FakeRunner:
    def __init__(self, report):
        self.report = report
        self.entered, self.release = Event(), Event()

    def run(self):
        self.entered.set()
        if not self.release.wait(8):
            raise AssertionError('fake runner was not released')
        return self.report

    def stop(self):
        self.release.set()

    def toggle_pause(self):
        return False


class AttachmentRoutesTests(unittest.TestCase):
    def wait_finished(self, root, ui):
        deadline = time.monotonic() + 7
        while ui.busy and time.monotonic() < deadline:
            root.update()
            time.sleep(.015)
        self.assertFalse(ui.busy)

    def test_withdrawn_desktop_routes_each_claim_and_restores_results_after_resize(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            raise unittest.SkipTest('Tk 不可用') from error
        root.withdraw()
        ui = None
        runners = {}
        with TemporaryDirectory(prefix='autohsr-attachment-desktop-') as directory:
            folder = Path(directory)
            try:
                mail, mail_path = receipt(folder / 'mail', 'mail', 'claimed', ['mail_attachments'])
                battlepass, _ = receipt(folder / 'bp', 'battlepass', 'empty')
                runners = {'mail': FakeRunner(mail), 'battlepass': FakeRunner(battlepass)}
                factory = Mock(side_effect=lambda settings, emit, *, task: runners[task])
                config = folder / 'config.json'
                Settings(game_path=r'C:\Fixture\StarRail.exe', mail=False, battlepass=True, weekly_enabled=True,
                         support_daily_only=True, power_plan_enabled=True, notification_enabled=True,
                         notification_profiles=['fixture'], redemption_enabled=True,
                         redemption_source='manual', redemption_codes=['FixtureCode']).save(config)
                original = config.read_bytes()
                with (backend(factory), patch('autohsr.gui.ROOT', folder),
                      patch('autohsr.notify_profiles.DEFAULT_ROOT', folder / 'notifications'),
                      patch.object(root, 'iconify')):
                    ui = AutoHSRWindow(root, config)
                    ui._restore = Mock()
                    root.update_idletasks()
                    # The guide reserves its margins and paper edges at the minimum width.
                    paper_width = root.minsize()[0] - round(210 * ui.ui_scale)
                    self.assertLessEqual(ui.daily_entry_buttons[MAIL].master.winfo_reqwidth(), paper_width)
                    selected = {name: field.get() for name, field in ui.tasks.items()}
                    self.assertIs(ui.daily_entry_buttons[ASSIGNMENTS], ui.assignment_button)
                    ui.daily_entry_buttons[MAIL].invoke()
                    self.assertEqual(ui.active_page, 'home')
                    self.assertEqual(ui.page_title.get(), '邮件附件')
                    self.assertEqual(ui.start_button.cget('text'), '仅领取邮件附件')
                    self.assertFalse(ui.reward_button.winfo_manager())
                    with patch.object(ui.daily_entry_buttons[MAIL], 'focus_set') as returned:
                        ui.daily_back_button.invoke()
                        root.update_idletasks()
                        returned.assert_called_once_with()
                    factory.assert_not_called()
                    ui.daily_entry_buttons[MAIL].invoke()
                    ui.start_button.invoke()
                    self.assertTrue(runners['mail'].entered.wait(5))
                    self.assertTrue(ui.start_button.instate(('disabled',)))
                    ui.daily_panel.invoke_primary()
                    factory.assert_called_once()
                    ui.daily_back_button.invoke()
                    ui.daily_entry_buttons[BATTLEPASS].invoke()
                    self.assertEqual(ui.start_button.cget('text'), '仅领取免费勋礼')
                    self.assertTrue(ui.start_button.instate(('disabled',)))
                    old_panel = ui.daily_panel
                    ui.responsive_layout._rebuild(ui.ui_scale + .25)
                    self.assertIsNot(ui.daily_panel, old_panel)
                    self.assertTrue(ui.start_button.instate(('disabled',)))
                    runners['mail'].release.set()
                    self.wait_finished(root, ui)
                    self.assertEqual(ui.daily_section, BATTLEPASS)
                    self.assertEqual(ui.daily_panel._attachments[BATTLEPASS][1].get(), '等待领取')
                    self.assertEqual(ui.daily_panel._attachments[MAIL][1].get(), '邮件附件已核实领取')
                    self.assertEqual(old_panel._attachments[MAIL][1].get(), '等待领取')
                    self.assertEqual(ui.status.get(), '● 邮件附件已核实领取')
                    ui.start_button.invoke()
                    self.assertTrue(runners['battlepass'].entered.wait(5))
                    runners['battlepass'].release.set()
                    self.wait_finished(root, ui)
                    self.assertEqual(ui.daily_panel._attachments[BATTLEPASS][1].get(), '暂无可领免费勋礼')
                    self.assertEqual(ui.status.get(), '● 暂无可领免费勋礼')

                    previous = ui.daily_panel
                    ui.responsive_layout._rebuild(ui.ui_scale + .25)
                    self.assertIsNot(ui.daily_panel, previous)
                    self.assertEqual(ui.daily_panel._attachments[BATTLEPASS][1].get(), '暂无可领免费勋礼')
                    ui.daily_back_button.invoke()
                    ui.daily_entry_buttons[MAIL].invoke()
                    _, title, _, record = ui.daily_panel._attachments[MAIL]
                    self.assertEqual(title.get(), '邮件附件已核实领取')
                    with patch.object(ui, '_open_path') as opened:
                        record.invoke()
                        opened.assert_called_once_with(mail_path)
                        mail_path.write_bytes(mail_path.read_bytes() + b'\n')
                        record.invoke()
                        opened.assert_called_once_with(mail_path)
                    self.assertEqual(title.get(), '邮件附件记录待核对')

                    self.assertEqual([call.kwargs['task'] for call in factory.call_args_list], ['mail', 'battlepass'])
                    for call in factory.call_args_list:
                        frozen, _ = call.args
                        task = call.kwargs['task']
                        self.assertTrue(getattr(frozen, task))
                        self.assertFalse(getattr(frozen, 'battlepass' if task == 'mail' else 'mail'))
                        self.assertFalse(any(getattr(frozen, key) for key in (
                            'auto_launch', 'assignments', 'battle', 'daily', 'allow_stamina_spend', 'daily_synthesis',
                            'weekly_enabled', 'redemption_enabled', 'notification_enabled', 'power_plan_enabled',
                            'use_support', 'support_daily_only')))
                    self.assertEqual({name: field.get() for name, field in ui.tasks.items()}, selected)
                    self.assertEqual(config.read_bytes(), original)
                    self.assertEqual(root.state(), 'withdrawn')
                    ui._close()
            finally:
                for runner in runners.values():
                    runner.release.set()
                if ui is not None and ui.worker is not None:
                    ui.worker.join(5)
                try:
                    root.destroy()
                except tk.TclError:
                    pass
        del ui, root
        gc.collect()


if __name__ == '__main__':
    unittest.main()
