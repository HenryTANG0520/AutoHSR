from contextlib import nullcontext, redirect_stderr
import io
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
