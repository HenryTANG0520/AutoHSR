"""Exercise the real desktop routes with a queued host and isolated fake inputs."""
from argparse import ArgumentParser
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from queue import Queue
import sys
from tempfile import TemporaryDirectory
from threading import Event, current_thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid


parser = ArgumentParser(add_help=False)
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
arguments, remaining = parser.parse_known_args()
sys.path.insert(0, str(arguments.repo.resolve()))
sys.argv[1:] = remaining

from autohsr import workflow_lease
from autohsr.config import Settings
from autohsr.desktop_daily import assignment_result
from autohsr.desktop_jobs import NativeRunSlot
from autohsr.desktop_schedule import DesktopSchedule
from autohsr.desktop_tools import ToolsShelf
from autohsr.desktop_warp import WarpPanel, _State
from autohsr.gui import AutoHSRWindow
from autohsr.schedule_plan import ScheduleError
from autohsr.tests import test_assignment_only as assignment_fixture

workflow_lease.NAME = r'Local\AutoHSR.QA.' + uuid.uuid4().hex


class GatedQueue(Queue):
    """Make the short publication-to-thread-exit interval observable."""
    def __init__(self, event_type):
        super().__init__()
        self.event_type = event_type
        self.owner = current_thread()
        self.published = Event()
        self.release = Event()
        self.item = None

    def put(self, item, *args, **kwargs):
        super().put(item, *args, **kwargs)
        if item['type'] == self.event_type and current_thread() is not self.owner:
            self.item = item
            self.published.set()
            if not self.release.wait(5):
                raise TimeoutError('test did not release the publication gate')


class Host:
    emit = AutoHSRWindow.emit
    _start_desktop_job = AutoHSRWindow._start_desktop_job
    _submit_tool_job = AutoHSRWindow._submit_tool_job
    _desktop_job_finished = AutoHSRWindow._desktop_job_finished
    _start_scoped_runner = AutoHSRWindow._start_scoped_runner
    _drain = AutoHSRWindow._drain
    _stop = AutoHSRWindow._stop
    _close = AutoHSRWindow._close

    def __init__(self, event_type):
        self.events = GatedQueue(event_type)
        self.stop_requested = Event()
        self._native_run = NativeRunSlot(self.events, self.stop_requested)
        self.runner = self.worker = None
        self.busy = self.running = self.paused = self.stopping = self.closing = self.dirty = False
        self.status, self.summary, self.result_alert, self.current_task = (Mock() for _ in range(4))
        self.root = SimpleNamespace(iconify=Mock(), withdraw=Mock(), destroy=Mock(), after=Mock(), after_cancel=Mock())
        self.desktop_schedule = SimpleNamespace(owned=False, tick=Mock(), stop=Mock(),
                                                runtime=SimpleNamespace(wait_idle=Mock(return_value=True)))
        self._clock = self._freeze_clock = self._refresh_weekly_caption = Mock()
        self._refresh_controls = self._refresh_recovery = self._restore = self._log = Mock()

    def _set_busy(self, busy, running=False):
        self.busy, self.running = busy, running
        if not running:
            self.paused = self.stopping = False


class Lifecycle(unittest.TestCase):
    def hold_publication(self, ui):
        worker = ui.worker

        def release():
            ui.events.release.set()
            worker.join(5)
            self.assertFalse(worker.is_alive())

        self.addCleanup(release)
        self.assertTrue(ui.events.published.wait(5))
        return release

    def test_terminal_event_holds_execution_until_thread_exit_then_calls_main(self):
        ui = Host('tool_job_result')
        calls = []

        def done(value):
            calls.append((value, current_thread(), ui.busy, ui.worker))

        self.assertTrue(ui._submit_tool_job('fixture', lambda _: 17, done))
        release = self.hold_publication(ui)
        self.assertEqual(ui.events.item, dict(type='tool_job_result', value=17))
        ui._drain()
        self.assertTrue(ui.busy)
        self.assertFalse(calls)
        self.assertFalse(ui._submit_tool_job('competing', Mock(), Mock()))
        release()
        ui._drain()
        self.assertEqual(calls, [(17, current_thread(), False, None)])

    def test_close_waits_for_both_work_and_scheduler_before_destroy(self):
        ui = Host('tool_job_result')
        done = Mock()
        self.assertTrue(ui._submit_tool_job('fixture', lambda _: 17, done))
        release = self.hold_publication(ui)
        idle = ui.desktop_schedule.runtime.wait_idle
        idle.return_value = False
        ui._close()
        self.assertTrue(ui.stop_requested.is_set())
        ui.root.withdraw.assert_called_once()
        ui.desktop_schedule.stop.assert_called_once()
        ui._drain()
        ui.root.destroy.assert_not_called()
        release()
        ui._drain()
        ui.root.destroy.assert_not_called()
        idle.return_value = True
        ui._drain()
        ui.root.destroy.assert_called_once()
        done.assert_not_called()

    def test_stop_after_publication_does_not_hide_completed_result(self):
        ui = Host('tool_job_result')
        done = Mock()
        self.assertTrue(ui._submit_tool_job('fixture', lambda _: 17, done))
        release = self.hold_publication(ui)
        ui._stop()
        release()
        ui._drain()
        done.assert_called_once_with(17)
        ui.summary.set.assert_called_with('')
        ui.status.set.assert_called_with('● 操作已结束')

    def test_stop_before_tk_consumes_native_ready_prevents_live_entry(self):
        ui = Host('runner_ready')
        stopped = Event()
        native_entry = Mock()

        def run():
            if not stopped.is_set():
                native_entry()
            return dict(status='stopped' if stopped.is_set() else 'success')

        runner = SimpleNamespace(stop=stopped.set, run=run)
        present = Mock()
        self.assertTrue(ui._start_scoped_runner('fixture', 'daily', lambda _: runner, present))
        release = self.hold_publication(ui)
        self.assertIsNone(ui.runner)
        ui._stop()
        release()
        ui._drain()
        native_entry.assert_not_called()
        present.assert_called_once_with(dict(status='stopped'))

    def test_manual_and_scheduled_owners_block_each_other(self):
        ui = Host('tool_job_result')
        ui.config_path, ui.settings = Path('unused.json'), Settings()
        desktop = DesktopSchedule(ui)
        self.assertTrue(ui._submit_tool_job('fixture', lambda _: 17, Mock()))
        release = self.hold_publication(ui)
        with patch('autohsr.desktop_schedule._execution_busy', side_effect=AssertionError('native lock not needed')):
            self.assertTrue(desktop._busy())
        release()
        ui._drain()
        desktop.sync(dict(active=object(), active_game=False))
        self.assertTrue(desktop.owned)
        self.assertFalse(ui._submit_tool_job('competing', Mock(), Mock()))
        desktop.sync(dict(active=None, pending=None))
        self.assertFalse(desktop.owned)
        self.assertFalse(ui.busy)

    def test_daily_budget_confirmation_rechecks_ownership_after_native_modal(self):
        for interruption in ('schedule', 'close'):
            with self.subTest(interruption=interruption):
                ui = Host('tool_job_result')
                settings = Settings(battle=True, allow_stamina_spend=True)
                ui.config_path, ui.settings = Path('unused.json'), settings
                ui.power_mode = SimpleNamespace(get=lambda: '单副本')
                ui._read_settings = Mock(return_value=settings)
                ui.plan = SimpleNamespace(set=Mock(side_effect=AssertionError('old request continued past the modal')))
                desktop = ui.desktop_schedule = DesktopSchedule(ui)

                def confirm(*args, **kwargs):
                    with patch('autohsr.desktop_schedule._execution_busy',
                               side_effect=AssertionError('modal must prevent a native probe')):
                        self.assertTrue(desktop._busy())
                    if interruption == 'schedule':
                        desktop.sync(dict(active=object(), active_game=False))
                    else:
                        ui.closing = True
                    return True

                with (patch('autohsr.recovery.recovery_state', return_value=dict(blocked=True, spent=40)),
                      patch('autohsr.recovery.new_budget_block_reason', return_value=None),
                      patch('autohsr.gui.immersifier_text', return_value=''),
                      patch('autohsr.gui.messagebox.askyesno', side_effect=confirm)):
                    AutoHSRWindow._start(ui)
                ui.plan.set.assert_not_called()
                self.assertIsNone(ui.worker)
                self.assertFalse(desktop.manual_confirmation)

    def test_scale_rebuild_delivers_to_current_panel_and_ignores_old_focus(self):
        current, old = SimpleNamespace(), SimpleNamespace()
        ui = SimpleNamespace(_in_tools=lambda: True, tools_shelf=current, _tool_action_changed=Mock())
        old.ui, old.current = ui, Mock()
        ToolsShelf.focus_entry(old)
        old.current.assert_not_called()
        job = object()
        old_panel = SimpleNamespace(ui=ui, model=_State(job=job), refresh_actions=Mock())
        new_panel = SimpleNamespace(winfo_exists=lambda: True, refresh_actions=Mock(), model=old_panel.model)
        ui.warp_panel = new_panel
        result = dict(status='success', mode='analysis', records=0, details=dict(accounts=[]))
        WarpPanel._finish(old_panel, job, result, (Path('synthetic.json'),), ('fixture-hash',), None)
        old_panel.refresh_actions.assert_not_called()
        new_panel.refresh_actions.assert_called_once()
        ui._tool_action_changed.assert_called_once()
        self.assertIsNone(new_panel.model.job)
        self.assertEqual(new_panel.model.result['status'], 'success')

    def test_daily_assignment_route_retains_account_and_original_report_proof(self):
        projections = []

        def drive(args):
            config = Path(args[args.index('--config') + 1])

            def run_scope(_title, operation, factory, on_report):
                self.assertEqual(operation, 'task_workflow')
                report = factory(lambda _: None).run().to_dict()
                on_report(report)
                print(json.dumps(report, ensure_ascii=False))
                return True

            host = SimpleNamespace(_read_settings=lambda **_: Settings.load(config), _start_scoped_runner=run_scope)
            self.assertTrue(AutoHSRWindow._start_daily_assignment(host, lambda report: projections.append(
                assignment_result(report))))
            return 0

        with patch.object(assignment_fixture, 'main', side_effect=drive):
            verified = assignment_fixture.AssignmentOnlyTests.invoke(self, workflow=False)
            conflict = assignment_fixture.AssignmentOnlyTests.invoke(self, workflow=False, event='other_uid_after_claim')
        self.assertEqual(verified.sent, ['委托', '领取奖励', '点击空白处关闭'])
        self.assertEqual(conflict.sent, ['委托', '领取奖励'])
        self.assertEqual(projections[0][0], '委托状态已核实')
        self.assertEqual(projections[1][0], '委托结果待核对')
        missing_account = deepcopy(verified.report)
        missing_account['workflow']['steps'][0]['account_verified'] = False
        self.assertEqual(assignment_result(missing_account)[0], '委托结果待核对')
        child = projections[0][2]
        child.write_bytes(child.read_bytes() + b'\n')
        self.assertEqual(assignment_result(verified.report)[0], '委托记录待核对')

    def test_daily_observation_routes_to_the_scoped_runner_with_manual_foreground_handoff(self):
        settings, callback = Settings(auto_launch=True), Mock()
        host = SimpleNamespace(_read_settings=Mock(return_value=settings), _start_scoped_runner=Mock(return_value=True))
        for mode, operation in (('achievements', 'daily_reward_observe'), ('support', 'daily_reward_observe'),
                                ('messages', 'daily_message_observe'), ('odyssey', 'daily_event_observe')):
            with self.subTest(mode=mode):
                self.assertTrue(AutoHSRWindow._start_daily_observation(host, mode, callback))
                _, actual, factory, present = host._start_scoped_runner.call_args.args
                runner = factory(Mock())
                self.assertIs(present, callback)
                self.assertEqual(actual, operation)
                self.assertEqual(runner.report.operation, operation)
                self.assertTrue(runner.observation_wait_for_foreground)
                self.assertIsNone(runner.battle_budget)
        self.assertTrue(all(call.kwargs == {'operation': 'check'} for call in host._read_settings.call_args_list))

    def test_achievement_claim_runs_only_its_native_operation_with_manual_handoff(self):
        settings, callback, emit = Settings(auto_launch=True), Mock(), Mock()
        host = SimpleNamespace(_read_settings=Mock(return_value=settings), _start_scoped_runner=Mock(return_value=True))
        with patch('autohsr.app.Runner') as runner:
            self.assertTrue(AutoHSRWindow._start_achievement_bulk_claim(host, callback))
            title, operation, factory, present = host._start_scoped_runner.call_args.args
            self.assertEqual((title, operation), ('本次成就一键领取', 'achievement_bulk_claim'))
            self.assertIs(present, callback)
            host._read_settings.assert_called_once_with(operation='check')
            runner.assert_not_called()
            self.assertIs(factory(emit), runner.return_value)
            runner.assert_called_once_with(settings, emit, operation='achievement_bulk_claim',
                                           observation_wait_for_foreground=True)
        host._read_settings.return_value = None
        host._start_scoped_runner.reset_mock()
        self.assertFalse(AutoHSRWindow._start_achievement_bulk_claim(host, callback))
        host._start_scoped_runner.assert_not_called()

    def test_sms_reply_routes_only_supported_explicit_pairs_to_its_native_runner(self):
        from autohsr.daily_message_reply import P179_SELECTION, REPLY_CHOICE, REPLY_NODE
        from autohsr.daily_observe import MESSAGE_REPLY_OPERATION

        settings, callback, emit = Settings(auto_launch=True), Mock(), Mock()
        host = SimpleNamespace(_read_settings=Mock(return_value=settings), _start_scoped_runner=Mock(return_value=True))
        self.assertFalse(AutoHSRWindow._start_daily_message_reply(host, (REPLY_NODE, P179_SELECTION[1]), callback))
        host._read_settings.assert_not_called()
        host._start_scoped_runner.assert_not_called()
        for selection in ((REPLY_NODE, REPLY_CHOICE), P179_SELECTION):
            with self.subTest(selection=selection), patch('autohsr.app.Runner') as runner:
                self.assertTrue(AutoHSRWindow._start_daily_message_reply(host, selection, callback))
                title, operation, factory, present = host._start_scoped_runner.call_args.args
                self.assertEqual((title, operation), ('本次短信回复', MESSAGE_REPLY_OPERATION))
                self.assertIs(present, callback)
                runner.assert_not_called()
                self.assertIs(factory(emit), runner.return_value)
                runner.assert_called_once_with(settings, emit, operation=MESSAGE_REPLY_OPERATION,
                                               daily_message_reply=selection, observation_wait_for_foreground=True)

    def test_event_claim_routes_only_explicit_days_and_boolean_return_to_the_scoped_runner(self):
        from autohsr.daily_observe import EVENT_CLAIM_OPERATION

        settings, callback, emit = Settings(auto_launch=True), Mock(), Mock()
        host = SimpleNamespace(_read_settings=Mock(return_value=settings), _start_scoped_runner=Mock(return_value=True))
        for day, observe_return in ((2, False), (8, True), (True, False), (4, 1), ('4', False)):
            with self.subTest(day=day, observe_return=observe_return):
                self.assertFalse(AutoHSRWindow._start_daily_event_claim(host, day, observe_return, callback))
        host._read_settings.assert_not_called()
        host._start_scoped_runner.assert_not_called()
        for day, observe_return in ((3, False), (7, True)):
            with self.subTest(day=day, observe_return=observe_return), patch('autohsr.app.Runner') as runner:
                self.assertTrue(AutoHSRWindow._start_daily_event_claim(host, day, observe_return, callback))
                title, operation, factory, present = host._start_scoped_runner.call_args.args
                self.assertEqual((title, operation), ('本次巡星之礼领取', EVENT_CLAIM_OPERATION))
                self.assertIs(present, callback)
                runner.assert_not_called()
                self.assertIs(factory(emit), runner.return_value)
                runner.assert_called_once_with(settings, emit, operation=EVENT_CLAIM_OPERATION,
                                               daily_event_claim_day=day, daily_event_observe_return=observe_return,
                                               observation_wait_for_foreground=True)

    def test_schedule_activation_rejects_saved_revision_source_and_budget_drift(self):
        with TemporaryDirectory(prefix='autohsr-schedule-desktop-qa-') as directory:
            root = Path(directory)
            recipe = root / 'workflow.json'
            settings = [Settings(allow_stamina_spend=True, stamina_limit=120)]
            ui = SimpleNamespace(config_path=root / 'settings.json', settings=settings[0], busy=False, closing=False,
                                 emit=Mock(), _read_settings=lambda **_: settings[0])
            desktop = DesktopSchedule(ui)
            self.addCleanup(desktop.stop)
            for change in ('revision', 'source', 'budget', 'none'):
                with self.subTest(change=change):
                    recipe.write_text(json.dumps(dict(version=1, name='fixture',
                        steps=[dict(id='daily', type='task', task='daily')])), 'utf8')
                    plan = dict(version=1, id=change, name='fixture', time='08:30', weekdays=[5],
                                target=dict(type='workflow', path=str(recipe)))
                    desktop.store.save(plan)
                    saved, original = desktop.store.load(change)
                    preview = desktop.preview(saved)
                    self.assertEqual(preview['revision'], original)
                    self.assertEqual(preview['whole_batch']['daily_stamina_max'], settings[0].stamina_limit)
                    if change == 'revision':
                        plan['time'] = '08:31'
                        desktop.store.save(plan, replace=True, expected_revision=original)
                    if change == 'source':
                        recipe.write_bytes(recipe.read_bytes() + b'\n')
                    if change == 'budget':
                        settings[0] = replace(settings[0], stamina_limit=100)
                    if change == 'none':
                        self.assertIn(change, desktop.enable(change, original)['enabled_ids'])
                    else:
                        with self.assertRaises(ScheduleError):
                            desktop.enable(change, original)
                        self.assertEqual(desktop.runtime.snapshot()['enabled_ids'], [])
            desktop.stop()
            self.assertFalse((desktop.store.root / 'slots').exists())


if __name__ == '__main__':
    unittest.main()
