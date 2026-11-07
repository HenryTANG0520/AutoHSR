"""Formal CLI through the native Runner and workflow branching, using a fake window."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image

from autohsr import notify_runtime, reward_guide_notify, workflow_notify
from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, EmptyCapture, FocusLost, Scene, Token
from autohsr.schedule_dispatch import _dependency_paths
from autohsr.task_workflow import WorkflowError, compile_recipe, task_spec
from autohsr.task_workflow_run import TaskWorkflowRunner
from autohsr.tests.test_task_workflow import condition, recipe, task
from autohsr.windows import Geometry


class ScreenWindow:
    hwnd = 1
    geometry = Geometry(0, 0, 200, 100)

    def __init__(self, frames):
        self.frames = iter(frames)
        self.guard = Mock(return_value=self.geometry)
        self.current_window_key = Mock(return_value='fake-native-window')
        self.emergency_pressed = Mock(return_value=False)
        for action in ('focus', 'send', 'click', 'key', 'move', 'scroll', 'drag'):
            setattr(self, action, Mock(side_effect=AssertionError(f'unexpected {action}')))

    def capture(self):
        image = next(self.frames, None)
        if image is None:
            raise EmptyCapture('fake frames exhausted')
        return image.copy(), self.geometry


class WorkflowGameScreenIntegrationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.config = self.root / 'config.json'
        Settings(auto_launch=True, overlay_logs=True, ocr_confidence=.91).save(self.config)
        self.original = self.config.read_bytes()
        self.template = self.root / '模板.png'
        generator = np.random.default_rng(46)
        pattern = generator.integers(0, 255, (16, 19, 3), dtype=np.uint8)
        Image.fromarray(pattern).save(self.template)
        self.absent = generator.integers(20, 40, (100, 200, 3), dtype=np.uint8)
        self.present = self.absent.copy()
        self.present[20:36, 40:59] = pattern[:, :, ::-1]

    def run_cli(self, frames, *, expect, before_publish=None, text=None, region=None, after_publish=None,
                extra_steps=(), flags=()):
        workflow = self.root / 'workflow.json'
        operation = 'workflow_game_image' if text is None else 'workflow_game_text'
        params = dict(template=self.template.name) if text is None else dict(text=text, region=[0, 0, 1, .9])
        field = 'image_found' if text is None else 'text_found'
        if region is not None:
            operation, params, field = 'workflow_game_capture', dict(region=region), 'captured'
        steps = [
            dict(task('look', operation, **params), on_failure='continue'),
            dict(id='choose', type='if', condition=condition('look', field, True),
                 steps=[dict(id='match', type='wait', seconds=0)],
                 else_steps=[dict(id='miss', type='wait', seconds=0)]),
        ]
        workflow.write_text(json.dumps(recipe(*steps, *extra_steps), ensure_ascii=False), encoding='utf-8')
        window = ScreenWindow(frames)
        account = Token('UID:135792468', .99, (.018, .957, .106, .985))
        vision = SimpleNamespace(read=lambda image, geometry: Scene([account], image, geometry))
        real_save = Runner._save_run_report

        def publish(runner, *args, **kwargs):
            if before_publish is not None:
                before_publish(window, runner)
            result = real_save(runner, *args, **kwargs)
            if after_publish is not None:
                after_publish(Path(runner.report.run_dir))
            return result

        out, err = io.StringIO(), io.StringIO()
        kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        with ExitStack() as stack:
            for target, replacement in (
                ('autohsr.app.ROOT', self.root),
                ('autohsr.task_workflow_run.ROOT', self.root),
                ('autohsr.windows.kernel32', kernel),
                ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.WorkflowScreenQA.' + uuid4().hex),
            ):
                stack.enter_context(patch(target, replacement))
            for target, kwargs in (
                ('autohsr.app.C.get_last_error', dict(return_value=0)),
                ('autohsr.app.find_game', dict(return_value=window)),
                ('autohsr.app.is_elevated', dict(return_value=False)),
                ('autohsr.app.Vision', dict(return_value=vision)),
                ('autohsr.app.Runner._arm_hotkeys', {}),
                ('autohsr.app.Runner._hotkeys', {}),
                ('autohsr.task_workflow_run.TaskWorkflowRunner._hotkeys', {}),
                ('autohsr.app.Runner._save_run_report', dict(new=publish)),
                ('autohsr.app.Runner._prepare_daily_game', dict(side_effect=AssertionError('no launch'))),
                ('autohsr.overlay.OverlayService', dict(side_effect=AssertionError('no overlay'))),
            ):
                stack.enter_context(patch(target, **kwargs))
            stack.enter_context(redirect_stdout(out))
            stack.enter_context(redirect_stderr(err))
            code = main(['--task-workflow', str(workflow), '--config', str(self.config), *flags])
        self.assertEqual(code, expect, err.getvalue() + out.getvalue())
        for action in ('focus', 'send', 'click', 'key', 'move', 'scroll', 'drag'):
            getattr(window, action).assert_not_called()
        self.assertEqual(self.config.read_bytes(), self.original)
        report = json.loads(out.getvalue())
        entry = report['workflow']['steps'][0]
        if 'source' in entry:
            original = Path(entry['source']['path'])
        else:
            original, = (path for path in (self.root / 'runs').glob('*/report.json')
                         if json.loads(path.read_text('utf-8'))['operation'] == operation)
        raw = original.read_text(encoding='utf-8')
        self.assertNotIn('135792468', raw)
        self.assertNotIn('fake-native-window', raw)
        if region is None:
            self.assertFalse(list(original.parent.glob('*.png')))
        return report, json.loads(raw)

    def test_native_template_match_and_nonmatch_are_separate_successes(self):
        for image, found, branch in ((self.present, True, 'match'), (self.absent, False, 'miss')):
            with self.subTest(branch=branch):
                report, native = self.run_cli([image] * 3, expect=0)
                steps = report['workflow']['steps']
                self.assertEqual([step['step'] for step in steps], ['look', 'choose', branch])
                self.assertEqual(steps[0]['facts'], dict(status='success', image_found=found))
                self.assertTrue(steps[0]['account_verified'])
                self.assertEqual(native['workflow_screen'], dict(image_found=found))
                self.assertEqual((native['stamina_spent'], native['stamina_pending']), (0, 0))

    def test_disagreement_and_late_focus_loss_keep_result_unknown(self):
        def lose_focus(window, runner):
            window.guard.side_effect = FocusLost('synthetic late loss of focus')

        for images, hook in (([self.present] * 2 + [self.absent], None),
                             ([self.present] * 3, lose_focus)):
            with self.subTest(late_focus_loss=hook is not None):
                report, native = self.run_cli(images, expect=1, before_publish=hook)
                steps = report['workflow']['steps']
                self.assertEqual([step['step'] for step in steps], ['look', 'choose'])
                self.assertNotIn('image_found', steps[0]['facts'])
                self.assertEqual(native['workflow_screen'], {})
                self.assertEqual(native['status'], 'failed')

    def test_real_ocr_on_game_crop_drives_the_formal_workflow_branch(self):
        image = np.full((100, 200, 3), 245, dtype=np.uint8)
        cv2.putText(image, 'AUTO', (12, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (16, 16, 16), 3, cv2.LINE_AA)
        report, native = self.run_cli([image] * 3, expect=0, text='AUTO')
        self.assertEqual(native['workflow_screen'], dict(text_found=True))
        self.assertEqual([row['step'] for row in report['workflow']['steps']], ['look', 'choose', 'match'])

    def test_template_path_resolves_and_is_frozen_by_schedule(self):
        document = recipe(task('look', 'workflow_game_image', template=self.template.name))
        compiled = compile_recipe(document, base_dir=self.root)
        node = compiled.steps[0]
        current, options = task_spec(Settings(), node, compiled.base_dir)
        self.assertEqual(options['workflow_screen_query'], dict(template=str(self.template)))
        self.assertEqual(list(_dependency_paths([(node, current, options)])), [(str(self.template), 64 * 1024 * 1024)])
        self.assertEqual(compiled.profile['daily_calls'], 0)
        with self.assertRaises(WorkflowError):
            compile_recipe(recipe(task('look', 'workflow_game_image', image='old.png', template='t.png')))

    def test_remote_template_is_rejected_before_touching_the_path(self):
        document = recipe(task('look', 'workflow_game_image', template=r'\\remote\share\template.png'))
        node = compile_recipe(document, base_dir=self.root).steps[0]
        with patch.object(Path, 'lstat', side_effect=AssertionError('remote path accessed')):
            with self.assertRaisesRegex(ValueError, '普通本地'):
                task_spec(Settings(), node, self.root)

    def test_f10_held_at_publication_stops_without_publishing_a_match(self):
        def stop_before_publish(window, runner):
            window.emergency_pressed.return_value = True

        report, native = self.run_cli([self.present] * 3, expect=130, before_publish=stop_before_publish)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(native['status'], 'stopped')
        self.assertEqual(native['workflow_screen'], {})

    def test_context_refuses_generic_input_for_game_observation(self):
        runner = Runner(Settings(), operation='workflow_game_text', workflow_screen_query=dict(text='提示'))
        window = ScreenWindow([])
        context = Context(runner, window, None)
        for action in (lambda: context.key('F'), lambda: context.click(None, (.4, .5)),
                       lambda: context.drag(None, (.4, .5), (.6, .7))):
            with self.assertRaisesRegex(AutomationError, '只允许观察'):
                action()

    def test_bundle_cli_round_trips_live_template_without_opening_game(self):
        workflow = self.root / 'saved.json'
        archive = self.root / 'shared.zip'
        imported = self.root / 'imported'
        document = recipe(task('look', 'workflow_game_image', template=str(self.template)))
        workflow.write_text(json.dumps(document), encoding='utf-8')
        with patch('autohsr.app.find_game', side_effect=AssertionError('offline bundle mode')):
            for flag, source, destination in (
                ('--task-workflow-export', workflow, archive),
                ('--task-workflow-import', archive, imported),
            ):
                with redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(main([flag, str(source), '--workflow-bundle-destination', str(destination)]), 0)
                self.assertEqual(json.loads(out.getvalue())['status'], 'success')
        copied = json.loads((imported / 'workflow.json').read_text(encoding='utf-8'))
        relative = copied['steps'][0]['params']['template']
        self.assertEqual(relative, 'assets/0001.png')
        self.assertEqual((imported / relative).read_bytes(), self.template.read_bytes())
        self.assertEqual(json.loads(workflow.read_text(encoding='utf-8')), document)

    def test_game_capture_exports_the_explicit_crop_and_verifies_it_before_branching(self):
        report, native = self.run_cli([self.absent, self.absent, self.present], expect=0,
                                      region=[.15, .1, .6, .7])
        steps = report['workflow']['steps']
        self.assertEqual([step['step'] for step in steps], ['look', 'choose', 'match'])
        self.assertEqual(steps[0]['facts'], dict(status='success', captured=True))
        capture = steps[0]['capture']
        self.assertEqual(capture, native['workflow_screen'])
        self.assertEqual(capture['source_size'], [200, 100])
        self.assertEqual(capture['box'], [30, 10, 120, 70])
        path = Path(native['run_dir']) / capture['file']
        self.assertEqual(capture['sha256'], sha256(path.read_bytes()).hexdigest())
        with Image.open(path) as image:
            np.testing.assert_array_equal(np.asarray(image), self.present[10:70, 30:120, ::-1])
        self.assertEqual((native['stamina_spent'], native['stamina_pending']), (0, 0))

    def test_game_capture_rejects_replaced_png_and_withdraws_late_focus_loss(self):
        def replace_capture(directory):
            Image.new('RGB', (90, 60), 'red').save(directory / 'capture.png')

        def lose_focus(window, _runner):
            window.guard.side_effect = FocusLost('synthetic late loss of focus')

        for hooks in (dict(after_publish=replace_capture), dict(before_publish=lose_focus)):
            with self.subTest(hooks=list(hooks)):
                report, _ = self.run_cli([self.present] * 3, expect=1, region=[.15, .1, .6, .7], **hooks)
                steps = report['workflow']['steps']
                self.assertNotIn('capture', steps[0])
                self.assertNotIn('captured', steps[0]['facts'])
                self.assertEqual([step['step'] for step in steps], ['look', 'choose'])

    def test_game_capture_requires_a_valid_explicit_region(self):
        for params in ({}, {'region': [0, 0, 1, True]}, {'region': [.2, 0, .2, 1]},
                       {'region': [0, 0, 1, 1], 'path': 'arbitrary.png'}):
            with self.subTest(params=params), self.assertRaises(WorkflowError):
                compile_recipe(recipe(task('look', 'workflow_game_capture', **params)))

    def test_capture_notification_uses_verified_pixels_and_has_one_attempt_per_step(self):
        service = notify_runtime.NotificationService(root=self.root / 'private-notify', request=Mock(
            side_effect=AssertionError('no HTTP')))
        profile = 'fixture-smtp'
        service.store.save(dict(id=profile, provider='smtp', params=dict(host='smtp.example.test',
                                user='sender@example.test', password='test-password',
                                To=['recipient@example.test'])))
        smtp = Mock()
        self.enterContext(patch('autohsr.notify_local.smtplib.SMTP_SSL', return_value=smtp))
        self.enterContext(patch('autohsr.notify_local.smtplib.SMTP', return_value=smtp))
        smtp.send_message.return_value = {}
        for module in (workflow_notify, reward_guide_notify):
            self.enterContext(patch.object(module, 'NotificationService', return_value=service))
        steps = tuple(task(f'mail-{i}', 'workflow_notify', profile=profile, message=f'消息 {i}', capture_from='look')
                      for i in (1, 2))
        flags = ('--workflow-allow-notify', '--workflow-allow-capture-notify')
        report, _ = self.run_cli([self.present] * 3, expect=0, region=[.15, .1, .6, .7],
                                 extra_steps=steps, flags=flags)
        capture, *_, first, second = report['workflow']['steps']
        digest = capture['capture']['sha256']
        for step in (first, second):
            self.assertEqual(step['attachment'], dict(step='look', sequence=1, sha256=digest))
            self.assertEqual(step['notification']['status'], 'accepted')
            intent = Path(step['source']['path']).with_name('intent.json')
            self.assertEqual(json.loads(intent.read_bytes())['capture_sha256'], digest)
        self.assertEqual(smtp.send_message.call_count, 2)
        for call in smtp.send_message.call_args_list:
            attachment, = call.args[0].iter_attachments()
            with Image.open(io.BytesIO(attachment.get_payload(decode=True))) as image:
                np.testing.assert_array_equal(np.asarray(image), self.present[10:70, 30:120, ::-1])

        check = TaskWorkflowRunner._capture_attachment

        def replace_capture(runner, reference, entry):
            capture = runner.report.workflow['steps'][0]
            path = Path(capture['source']['path']).with_name('capture.png')
            Image.new('RGB', (90, 60), 'black').save(path)
            return check(runner, reference, entry)

        with patch.object(TaskWorkflowRunner, '_capture_attachment', replace_capture):
            report, _ = self.run_cli([self.present] * 3, expect=1, region=[.15, .1, .6, .7],
                                     extra_steps=steps, flags=flags)
        self.assertIn('导出回执不符', report['workflow']['steps'][-1]['error'])
        self.assertEqual(smtp.send_message.call_count, 2)

    def test_capture_notification_requires_prior_step_and_separate_cli_authorization(self):
        capture = task('look', 'workflow_game_capture', region=[0, 0, .5, .5])
        notification = task('mail', 'workflow_notify', profile='fixture-smtp', message='消息', capture_from='look')
        for steps in ((notification, capture), (dict(capture, enabled=False), notification),
                      (capture, dict(id='loop', type='for', count=1, steps=[notification]))):
            with self.subTest(steps=steps), self.assertRaisesRegex(WorkflowError, '同一分支'):
                compile_recipe(recipe(*steps))
        with self.assertRaisesRegex(WorkflowError, '一起运行'):
            compile_recipe(recipe(capture, notification), selected_path='1')
        path = self.root / 'no-authorization.json'
        path.write_text(json.dumps(recipe(capture, notification)), encoding='utf-8')
        errors = io.StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit) as rejected:
            main(['--task-workflow', str(path), '--workflow-allow-notify'])
        self.assertEqual(rejected.exception.code, 2)
        self.assertIn('--workflow-allow-capture-notify', errors.getvalue())
