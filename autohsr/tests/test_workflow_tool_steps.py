from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
from itertools import product
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr.__main__ import main
from autohsr.config import Settings
from autohsr.gui import AutoHSRWindow
from autohsr.schedule_dispatch import NativeScheduleExecutor
from autohsr.schedule_plan import ScheduleError
from autohsr.task_workflow import WorkflowError, compile_recipe
from autohsr.task_workflow_run import TaskWorkflowRunner, _write, step_notification_aliases


def document(*steps):
    return dict(version=1, name='工具步骤', steps=list(steps))


def task(identity, kind, **params):
    return dict(id=identity, type='task', task=kind, params=params)


def notice(identity='notify'):
    return task(identity, 'workflow_notify', profile='test', message='PRIVATE_SYNTHETIC_MESSAGE')


class WorkflowToolStepTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.enterContext(patch('autohsr.task_workflow_run.workflow_lease', side_effect=nullcontext))
        self.enterContext(patch.object(TaskWorkflowRunner, '_hotkeys'))

    def test_local_observation_false_drives_only_the_expected_branch(self):
        flow = document(task('screen', 'workflow_image', image='scene.png', template='sample.png',
                             region=[0, .1, .6, .8], threshold=.91),
                        dict(id='choose', type='if', condition=dict(step='screen', field='image_found',
                                                                   op='eq', value=True),
                             steps=[dict(id='yes', type='wait', seconds=0)],
                             else_steps=[dict(id='no', type='wait', seconds=0)]))
        with patch('autohsr.workflow_vision.observe', return_value=dict(status='success', image_found=False)) as observe:
            report = TaskWorkflowRunner(Settings(), flow, base_dir=self.root, root=self.root).run()
        self.assertEqual(report.status, 'success', report.error)
        self.assertEqual([row['step'] for row in report.workflow['steps']], ['screen', 'choose', 'no'])
        self.assertEqual(report.workflow['steps'][0]['facts'], dict(status='success', image_found=False))
        self.assertEqual(observe.call_args.kwargs['image'], str(self.root / 'scene.png'))
        self.assertEqual(observe.call_args.kwargs['template'], str(self.root / 'sample.png'))

    def test_audio_and_text_sources_are_frozen_for_the_scheduled_manifest(self):
        for name in ('prompt.wav', 'image.png'):
            (self.root / name).write_bytes(b'fixture')
        flow = document(task('play', 'workflow_audio', path='prompt.wav'),
                        task('text', 'workflow_text', image='image.png', text='按钮', contains=False))
        path = self.root / 'workflow.json'
        path.write_text(json.dumps(flow, ensure_ascii=False), encoding='utf8')
        plan = dict(version=1, id='test', name='test', time='08:00', target=dict(type='workflow', path=str(path)))
        executor = NativeScheduleExecutor(Settings(), base_dir=self.root)
        budget, fingerprint = executor.preview_activation(plan)
        self.assertEqual(budget['whole_batch']['daily_stamina_max'], 0)
        (self.root / 'prompt.wav').write_bytes(b'changed')
        self.assertNotEqual(executor.preview_activation(plan)[1], fingerprint)
        with patch('autohsr.workflow_audio.play', return_value=dict(status='success', playback_status='completed')) as play:
            audio = TaskWorkflowRunner(Settings(), document(flow['steps'][0]), base_dir=self.root,
                                       root=self.root).run()
        self.assertEqual(audio.status, 'success', audio.error)
        self.assertEqual(play.call_args.args, (str(self.root / 'prompt.wav'),))
        self.assertFalse(play.call_args.kwargs['stopped']())

    def test_notification_is_bounded_and_denied_without_per_run_authorization(self):
        flow = document(notice())
        self.assertEqual(step_notification_aliases(compile_recipe(flow)), ('test',))
        with self.assertRaisesRegex(WorkflowError, '明确授权'):
            TaskWorkflowRunner(Settings(), flow, root=self.root)
        loop = dict(id='loop', type='for', count=21, steps=[notice()])
        with self.assertRaisesRegex(WorkflowError, '最多执行 20'):
            compile_recipe(document(loop))
        path = self.root / 'workflow.json'
        path.write_text(json.dumps(flow), encoding='utf8')
        plan = dict(version=1, id='test', name='test', time='08:00', target=dict(type='workflow', path=str(path)))
        with self.assertRaisesRegex(ScheduleError, '手动授权'):
            NativeScheduleExecutor(Settings()).preview_budget(plan)
        config = self.root / 'config.json'
        Settings().save(config)
        with (patch('autohsr.task_workflow_run.freeze_step_notifications') as freeze,
              redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped):
            main(['--task-workflow', str(path), '--config', str(config)])
        self.assertEqual(stopped.exception.code, 2)
        freeze.assert_not_called()

    def test_desktop_decline_prevents_worker_and_default_is_no(self):
        ui = SimpleNamespace(root=None, busy=False, closing=False, _read_settings=Mock(return_value=Settings()),
                             _start_scoped_runner=Mock(), result_alert=Mock())
        with (patch('autohsr.task_workflow_run.freeze_step_notifications', return_value={'test': 'a' * 64}),
              patch('autohsr.gui.messagebox.askyesno', return_value=False) as question):
            self.assertFalse(AutoHSRWindow._start_task_workflow(ui, compile_recipe(document(notice()))))
        self.assertEqual(question.call_args.kwargs['default'], 'no')
        self.assertIn('test', question.call_args.args[1])
        ui._start_scoped_runner.assert_not_called()

    def test_image_notification_keeps_check_offline_and_requires_manual_cli(self):
        from autohsr.workflow_bundle import BundleError, export_bundle

        step = notice()
        step['params']['png'] = 'missing.png'
        flow = document(step, dict(id='wait', type='wait', seconds=0))
        path = self.root / 'workflow.json'
        path.write_text(json.dumps(flow), encoding='utf8')
        recipe = compile_recipe(flow, base_dir=self.root)
        plan = dict(version=1, id='test', name='test', time='08:00', target=dict(type='workflow', path=str(path)))
        ui = SimpleNamespace(_read_settings=Mock(), _start_scoped_runner=Mock(), result_alert=Mock())
        with patch('autohsr.reward_guide_notify._load_attachment') as read:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(['--task-workflow-check', str(path)]), 0)
            self.assertFalse(json.loads(output.getvalue())['source_files_read'])
            with self.assertRaisesRegex(WorkflowError, '本地 PNG'):
                TaskWorkflowRunner(Settings(), flow, base_dir=self.root, notification_versions={'test': 'a' * 64})
            selected = TaskWorkflowRunner(Settings(), flow, base_dir=self.root, selected_path='1', root=self.root)
            self.assertEqual(selected.run().status, 'success')
            with self.assertRaisesRegex(ScheduleError, '手动授权'):
                NativeScheduleExecutor(Settings()).preview_budget(plan)
            with self.assertRaises(BundleError):
                export_bundle(path, self.root / 'flow.zip')
            self.assertFalse(AutoHSRWindow._start_task_workflow(ui, recipe))
            self.assertIn('命令行', ui.result_alert.set.call_args.args[0])
            read.assert_not_called()
        ui._read_settings.assert_not_called()
        ui._start_scoped_runner.assert_not_called()

    def test_stopped_imported_single_step_does_not_link_unwritten_final_report(self):
        from autohsr.task_workflow_draft import WorkflowDraft
        from autohsr.workflow_bundle import export_bundle, import_bundle
        from autohsr.workflow_yaml import load_march7th_yaml

        original = self.root / 'source.yaml'
        original.write_text('name: 等待流程\nsteps: [{type: wait, seconds: 1}, {type: wait, seconds: 2}]\n', 'utf8')
        yaml_saved = load_march7th_yaml(original).save_as(self.root / 'yaml-saved.json')
        bundle = export_bundle(yaml_saved.path, self.root / 'workflow.zip')
        imported = import_bundle(bundle, self.root / 'unpacked')
        zip_saved = WorkflowDraft.load(imported).save_as(self.root / 'zip-saved.json')
        for saved, fail_final in product((yaml_saved, zip_saved), (False, True)):
            with self.subTest(source=saved.path.name, fail_final=fail_final):
                outcome = 'write-failure' if fail_final else 'saved'
                case_root = self.root / f'{saved.path.stem}-{outcome}'
                runner = TaskWorkflowRunner(Settings(), saved.recipe.document, selected_path='1', root=case_root / 'runs')
                write_report = runner._save

                def save_report():
                    if fail_final and runner.report.finished_at:
                        raise OSError('synthetic final write failure')
                    write_report()

                def stop_wait(_seconds):
                    runner.stop()
                    runner.checkpoint()

                def submit(_title, work, present, _failed, *, game, clear_run_evidence):
                    self.assertFalse(game)
                    self.assertTrue(clear_run_evidence)
                    present(work(None))
                    return True

                ui = SimpleNamespace(events=Mock(), _native_run=SimpleNamespace(run=lambda value: value.run()),
                                     status=Mock(), last_report_file=self.root / 'older.json', history_context=Mock(),
                                     report_text=object(), _replace_text=Mock(), _refresh_recovery=Mock(),
                                     _refresh_controls=Mock(), _start_desktop_job=submit)
                ui._reset_run_evidence = AutoHSRWindow._reset_run_evidence.__get__(ui)
                ui._record_run = AutoHSRWindow._record_run.__get__(ui)
                on_report = Mock()
                with (patch.object(runner, '_save', side_effect=save_report),
                      patch.object(runner, '_wait', side_effect=stop_wait) as wait):
                    self.assertTrue(AutoHSRWindow._start_scoped_runner(
                        ui, '运行已保存流程', 'task_workflow', lambda _emit: runner, on_report, game=False))
                wait.assert_called_once_with(2)
                result = on_report.call_args.args[0]
                disk = ui.last_run_dir / 'report.json'
                before = disk.read_bytes()
                self.assertEqual(json.loads(ui._replace_text.call_args.args[1]), result)
                self.assertEqual([step['step'] for step in result['workflow']['steps']], ['m7-1'])
                self.assertTrue(result['finished_at'])
                if fail_final:
                    self.assertFalse(result['report_saved'])
                    self.assertFalse(json.loads(before)['finished_at'])
                    self.assertIsNone(ui.last_report_file)
                    self.assertIn('最终报告未保存', ui.history_context.set.call_args.args[0])
                else:
                    self.assertTrue(result['report_saved'])
                    self.assertEqual(json.loads(before), result)
                    self.assertEqual(ui.last_report_file, disk)

                ui.last_report_file = None
                with patch('autohsr.gui.ROOT', case_root):
                    AutoHSRWindow._discover_report(ui)
                self.assertEqual(json.loads(ui._replace_text.call_args.args[1]), json.loads(before))
                if fail_final:
                    self.assertIsNone(ui.last_report_file)
                    self.assertIn('仅有中间快照', ui.history_context.set.call_args.args[0])
                else:
                    self.assertEqual(ui.last_report_file, disk)
                self.assertEqual(disk.read_bytes(), before)

    def test_unknown_notification_blocks_later_sends_but_preserves_anonymous_result(self):
        first = dict(notice('first'), on_failure='continue')
        flow = document(first, notice('second'))

        def send(profile, message, *, directory, sequence, **_options):
            child = directory / f'notify-{sequence}'
            child.mkdir()
            data = dict(operation='workflow_notify', status='partial', report_saved=True, run_dir=str(child),
                        notification=dict(status='unknown', reused=False))
            _write(child / 'report.json', data)
            return data

        with patch('autohsr.workflow_notify.send_step', side_effect=send) as transport:
            runner = TaskWorkflowRunner(Settings(), flow, root=self.root, notification_versions={'test': 'a' * 64})
            report = runner.run()
        self.assertEqual(report.status, 'partial')
        transport.assert_called_once()
        self.assertEqual(transport.call_args.kwargs['expected_version'], 'a' * 64)
        first, second = report.workflow['steps']
        self.assertEqual(first['notification']['status'], 'unknown')
        self.assertIn('未发送后续主动通知', second['error'])
        self.assertNotIn('PRIVATE_SYNTHETIC_MESSAGE', json.dumps(report.to_dict()))
