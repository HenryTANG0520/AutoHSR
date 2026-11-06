"""Formal CLI through the native Runner and workflow branching, using a fake window."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
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

from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, EmptyCapture, FocusLost, Scene, Token
from autohsr.schedule_dispatch import _dependency_paths
from autohsr.task_workflow import WorkflowError, compile_recipe, task_spec
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

    def run_cli(self, frames, *, expect, before_publish=None, text=None):
        workflow = self.root / 'workflow.json'
        operation = 'workflow_game_image' if text is None else 'workflow_game_text'
        params = dict(template=self.template.name) if text is None else dict(text=text, region=[0, 0, 1, .9])
        field = 'image_found' if text is None else 'text_found'
        steps = [
            dict(task('look', operation, **params), on_failure='continue'),
            dict(id='choose', type='if', condition=condition('look', field, True),
                 steps=[dict(id='match', type='wait', seconds=0)],
                 else_steps=[dict(id='miss', type='wait', seconds=0)]),
        ]
        workflow.write_text(json.dumps(recipe(*steps), ensure_ascii=False), encoding='utf-8')
        window = ScreenWindow(frames)
        account = Token('UID:135792468', .99, (.018, .957, .106, .985))
        vision = SimpleNamespace(read=lambda image, geometry: Scene([account], image, geometry))
        real_save = Runner._save_run_report

        def publish(runner, *args, **kwargs):
            if before_publish is not None:
                before_publish(window, runner)
            return real_save(runner, *args, **kwargs)

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
            code = main(['--task-workflow', str(workflow), '--config', str(self.config)])
        self.assertEqual(code, expect, err.getvalue())
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
