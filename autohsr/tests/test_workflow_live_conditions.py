"""Native live conditions with a fake window and real saved child receipts."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import numpy as np
from PIL import Image

from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.models import FocusLost, Scene, Token
from autohsr.schedule_dispatch import NativeScheduleExecutor
from autohsr.schedule_plan import ScheduleError, ScheduleSourceUnverified, validate
from autohsr.task_workflow import WorkflowError, compile_recipe
from autohsr.task_workflow_run import TaskWorkflowRunner
from autohsr.tests.test_task_workflow import condition, recipe
from autohsr.tests.test_workflow_game_screen_integration import ScreenWindow


def wait(identity):
    return dict(id=identity, type='wait', seconds=0)


def image_query(value=True):
    return dict(task='workflow_game_image', params=dict(template='template.png'), value=value)


def screen_if(query=None):
    return dict(id='gate', type='if', screen_condition=query or image_query(),
                steps=[wait('match')], else_steps=[wait('miss')])


def screen_while(bound, *steps):
    return dict(id='loop', type='while', max_iterations=bound, screen_condition=image_query(),
                steps=list(steps) or [wait('body')])


def observations(report):
    return [entry for entry in report.workflow['steps'] if entry['type'] == 'screen_condition']


def body_steps(report):
    return [entry['step'] for entry in report.workflow['steps'] if entry['type'] != 'screen_condition']


class WorkflowLiveConditionSchemaTests(unittest.TestCase):
    def test_condition_is_exclusive_and_uses_only_native_screen_parameters(self):
        for modify in (
            lambda node: node.update(condition=condition('prior')),
            lambda node: node.pop('screen_condition'),
            lambda node: node.update(screen_condition=None),
            lambda node: node['screen_condition'].update(task='daily'),
            lambda node: node['screen_condition'].update(task='workflow_image'),
            lambda node: node['screen_condition'].update(value=1),
            lambda node: node['screen_condition'].update(retries=2),
            lambda node: node['screen_condition']['params'].update(image='saved.png'),
            lambda node: node['screen_condition']['params'].update(region=[0, 0, 0, 1]),
            lambda node: node['screen_condition']['params'].pop('template'),
        ):
            with self.subTest(modify=modify):
                node = screen_if()
                modify(node)
                with self.assertRaises(WorkflowError):
                    compile_recipe(recipe(wait('prior'), node))

    def test_reserves_every_observation_including_the_while_limit(self):
        self.assertEqual(compile_recipe(recipe(screen_if())).profile['executions'], 3)
        document = recipe(screen_while(3), wait('tail'))
        self.assertEqual(compile_recipe(document).profile['executions'], 9)
        self.assertEqual(compile_recipe(document, selected_path='0').profile['executions'], 8)
        self.assertEqual(compile_recipe(document, selected_path='0/0').profile['executions'], 1)
        disabled = dict(screen_if(), enabled=False)
        self.assertEqual(compile_recipe(recipe(disabled)).profile['executions'], 1)
        legacy = recipe(wait('prior'), dict(id='legacy', type='while', max_iterations=3,
                                            condition=condition('prior'), steps=[wait('body')]))
        self.assertEqual(compile_recipe(legacy).profile['executions'], 5)
        with self.assertRaisesRegex(WorkflowError, '10000'):
            compile_recipe(recipe(dict(id='outer', type='for', count=1000, steps=[screen_while(4)])))


class WorkflowLiveConditionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.template = self.root / 'template.png'
        generator = np.random.default_rng(161)
        pattern = generator.integers(0, 255, (16, 19, 3), dtype=np.uint8)
        Image.fromarray(pattern).save(self.template)
        self.absent = generator.integers(20, 40, (100, 200, 3), dtype=np.uint8)
        self.present = self.absent.copy()
        self.present[20:36, 40:59] = pattern[:, :, ::-1]
        self.changed_account = self.present.copy()
        self.changed_account[0, 0, 0] = 123
        self.settings = Settings(auto_launch=True, overlay_logs=True, ocr_confidence=.91)

    def workflow(self, *nodes, **options):
        return TaskWorkflowRunner(self.settings, recipe(*nodes), base_dir=self.root,
                                  root=self.root / 'runs', **options)

    def run_offline(self, workflow, frames, *, before_publish=None, after_publish=None, handoff=False):
        window = ScreenWindow(frames)
        window.capture = Mock(wraps=window.capture)
        self.window = window
        if handoff:
            def guard(*_):
                if window.guard.call_count == 1:
                    raise FocusLost('waiting for user handoff')
                return window.geometry

            window.guard.side_effect = guard

        def read(image, geometry):
            uid = '246813579' if image[0, 0, 0] == 123 else '135792468'
            token = Token('UID:' + uid, .99, (.018, .957, .106, .985))
            return Scene([token], image, geometry)

        native_save = Runner._save_run_report

        def publish(native, *args, **kwargs):
            if before_publish is not None:
                before_publish(native, window)
            native_save(native, *args, **kwargs)
            if after_publish is not None:
                after_publish(native, window)

        kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        with ExitStack() as stack:
            for target, value in (
                ('autohsr.app.ROOT', self.root),
                ('autohsr.windows.kernel32', kernel),
                ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.LiveConditionQA.' + uuid4().hex),
            ):
                stack.enter_context(patch(target, value))
            for target, kwargs in (
                ('autohsr.app.C.get_last_error', dict(return_value=0)),
                ('autohsr.app.find_game', dict(return_value=window)),
                ('autohsr.app.is_elevated', dict(return_value=False)),
                ('autohsr.app.Vision', dict(return_value=SimpleNamespace(read=read))),
                ('autohsr.app.Runner._arm_hotkeys', {}),
                ('autohsr.app.Runner._hotkeys', {}),
                ('autohsr.task_workflow_run.TaskWorkflowRunner._hotkeys', {}),
                ('autohsr.app.Runner._save_run_report', dict(new=publish)),
                ('autohsr.app.Runner._prepare_daily_game', dict(side_effect=AssertionError('no launch'))),
                ('autohsr.overlay.OverlayService', dict(side_effect=AssertionError('no overlay'))),
            ):
                stack.enter_context(patch(target, **kwargs))
            result = workflow.run()
        for name in ('focus', 'send', 'click', 'key', 'move', 'scroll', 'drag'):
            getattr(window, name).assert_not_called()
        return result

    def assert_receipt(self, entry, *, found, passed, phase='branch'):
        self.assertEqual((entry['status'], entry['phase'], entry['condition']), ('success', phase, passed))
        self.assertTrue(entry['account_verified'])
        self.assertEqual(entry['facts'], dict(status='success', image_found=found))
        path = Path(entry['source']['path'])
        raw = path.read_bytes()
        self.assertEqual(entry['source']['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(json.loads(raw)['workflow_screen'], {'image_found': found})
        self.assertNotIn(b'135792468', raw)
        self.assertFalse(list(path.parent.glob('*.png')))

    def test_if_branch_uses_fresh_true_and_false_even_when_reentered(self):
        node = dict(id='repeat', type='for', count=2, steps=[screen_if()])
        report = self.run_offline(self.workflow(node), [self.present] * 3 + [self.absent] * 3)
        self.assertEqual(report.status, 'success', report.error)
        self.assertEqual(body_steps(report), ['repeat', 'gate', 'match', 'gate', 'miss'])
        one, two = observations(report)
        self.assert_receipt(one, found=True, passed=True)
        self.assert_receipt(two, found=False, passed=False)
        self.assertEqual([row['trail'] for row in (one, two)], [[['repeat', 0]], [['repeat', 1]]])
        self.assertNotEqual(one['source']['path'], two['source']['path'])
        self.assertEqual(report.workflow['identity']['checked_contexts'], 2)

    def test_explicit_desktop_handoff_waits_only_for_the_first_native_task(self):
        options = []
        node = dict(id='repeat', type='for', count=2, steps=[screen_if()])
        report = self.run_offline(
            self.workflow(node, wait_for_foreground=True),
            [self.present] * 3 + [self.absent] * 3,
            handoff=True,
            after_publish=lambda native, _: options.append(native.observation_wait_for_foreground),
        )
        self.assertEqual(report.status, 'success', report.error)
        self.assertEqual(options, [True, False])
        self.assertEqual([entry['condition'] for entry in observations(report)], [True, False])

    def test_text_query_matches_verified_false_with_explicit_boolean(self):
        query = dict(task='workflow_game_text', params=dict(text='结束', region=[0, 0, 1, 1]), value=False)
        cropped_ocr = SimpleNamespace(read=lambda image: Scene([Token('继续', .99, (.1, .2, .3, .4))]))
        with patch('autohsr.workflow_vision.Vision', return_value=cropped_ocr):
            report = self.run_offline(self.workflow(screen_if(query)), [self.present] * 3)
        self.assertEqual(report.status, 'success', report.error)
        self.assertEqual(body_steps(report), ['gate', 'match'])
        self.assertEqual(observations(report)[0]['facts'], {'status': 'success', 'text_found': False})

    def test_disagreement_and_late_focus_loss_do_not_satisfy_negative_query(self):
        def lose_focus(native, window):
            window.guard.side_effect = FocusLost('fake late loss of focus')

        for frames, hook in (([self.present] * 2 + [self.absent], None), ([self.present] * 3, lose_focus)):
            with self.subTest(hook=hook):
                report = self.run_offline(self.workflow(screen_if(image_query(False)), wait('tail')),
                                          frames, before_publish=hook)
                self.assertEqual(report.status, 'partial')
                self.assertEqual(body_steps(report), ['gate'])
                entry, = observations(report)
                self.assertNotIn('condition', entry)
                self.assertNotIn('image_found', entry['facts'])

    def test_while_reobserves_before_next_body_and_does_not_follow_changed_account(self):
        for image, status in ((self.absent, 'success'), (self.changed_account, 'partial')):
            with self.subTest(status=status):
                report = self.run_offline(self.workflow(screen_while(3), wait('tail')),
                                          [self.present] * 3 + [image] * 3)
                self.assertEqual(report.status, status, report.error)
                one, two = observations(report)
                self.assert_receipt(one, found=True, passed=True, phase='iteration')
                self.assertEqual((one['iteration'], two['iteration']), (0, 1))
                if status == 'success':
                    self.assert_receipt(two, found=False, passed=False, phase='iteration')
                    self.assertEqual(body_steps(report), ['loop', 'body', 'tail'])
                else:
                    self.assertNotIn('condition', two)
                    self.assertTrue(report.workflow['identity']['account_changed'])
                    self.assertEqual(body_steps(report), ['loop', 'body'])

    def test_limit_probe_is_new_and_distinguishes_false_true_and_unknown(self):
        for limit, status, expected in (
            ([self.absent] * 3, 'success', False),
            ([self.present] * 3, 'partial', True),
            ([self.present] * 2 + [self.absent], 'partial', None),
        ):
            with self.subTest(expected=expected):
                report = self.run_offline(self.workflow(screen_while(1), wait('tail')), [self.present] * 3 + limit)
                self.assertEqual(report.status, status, report.error)
                loop = report.workflow['steps'][0]
                self.assertEqual(loop['iterations'], 1)
                self.assertEqual(loop.get('limit_reached', False), expected is True)
                one, two = observations(report)
                self.assertEqual((one['phase'], two['phase'], two['iteration']), ('iteration', 'limit', 1))
                if expected is None:
                    self.assertNotIn('condition', two)
                    self.assertNotIn('image_found', two['facts'])
                else:
                    self.assert_receipt(two, found=expected, passed=expected, phase='limit')
                    self.assertNotEqual(one['source']['path'], two['source']['path'])
                self.assertEqual(body_steps(report), ['loop', 'body'] + (['tail'] if status == 'success' else []))

    def test_break_avoids_limit_probe_and_continue_does_not(self):
        for control, phases in (('break', ['iteration']), ('continue', ['iteration', 'limit'])):
            with self.subTest(control=control):
                loop = screen_while(1, dict(id='control', type=control), wait('skipped'))
                report = self.run_offline(self.workflow(loop, wait('tail')), [self.present] * 3 + [self.absent] * 3)
                self.assertEqual(report.status, 'success', report.error)
                self.assertEqual(body_steps(report), ['loop', 'control', 'tail'])
                self.assertEqual([row['phase'] for row in observations(report)], phases)

    def test_late_stop_or_pause_does_not_advance_the_branch(self):
        def stop(native, window):
            window.emergency_pressed.return_value = True

        stopped = self.run_offline(self.workflow(screen_if()), [self.present] * 3, before_publish=stop)
        self.assertEqual(stopped.status, 'stopped')
        self.assertEqual(body_steps(stopped), ['gate'])
        self.assertNotIn('condition', observations(stopped)[0])

        def on_event(event):
            if event['type'] == 'workflow_step' and event['sequence'] == 2 and event['status'] == 'success':
                workflow.toggle_pause()
                workflow.toggle_pause()

        workflow = self.workflow(screen_if(), emit=on_event)
        resumed = self.run_offline(workflow, [self.present] * 3)
        self.assertEqual(resumed.status, 'partial')
        self.assertTrue(resumed.workflow['input_blocked'])
        self.assertEqual(body_steps(resumed), ['gate'])
        self.assertNotIn('condition', resumed.workflow['steps'][0])
        self.assert_receipt(observations(resumed)[0], found=True, passed=True)

    def test_focus_loss_or_window_change_after_native_publication_blocks_branch(self):
        for mutation in ('focus', 'window', 'stop'):
            with self.subTest(mutation=mutation):
                node = screen_if()
                node['steps'] = [dict(id='action', type='task', task='workflow_audio', params=dict(path='prompt.wav'))]

                def after_publish(_native, window):
                    if mutation == 'focus':
                        window.guard.side_effect = FocusLost('synthetic foreground loss after publication')
                    elif mutation == 'window':
                        window.current_window_key.return_value = 'another-window'
                    else:
                        window.emergency_pressed.return_value = True

                with patch('autohsr.workflow_audio.play') as play:
                    report = self.run_offline(self.workflow(node), [self.present] * 3, after_publish=after_publish)
                play.assert_not_called()
                self.assertEqual(report.status, 'stopped' if mutation == 'stop' else 'partial')
                self.assertEqual(body_steps(report), ['gate'])
                observed = observations(report)[0]
                original = Path(observed['source']['path']).read_bytes()
                self.assertEqual(hashlib.sha256(original).hexdigest(), observed['source']['sha256'])
                self.assertEqual(json.loads(original)['status'], 'success')
                self.assertNotIn('condition', report.workflow['steps'][0])

    def test_pause_after_first_action_intent_aborts_if_else_and_while_body(self):
        for form in ('if', 'else', 'while'):
            with self.subTest(form=form):
                action = dict(id='action', type='task', task='workflow_audio', on_failure='continue',
                              params=dict(path='prompt.wav'))
                if form == 'while':
                    node = screen_while(1, action)
                else:
                    node = screen_if(image_query(form == 'if'))
                    node['steps' if form == 'if' else 'else_steps'] = [action]

                def on_event(event):
                    if (event.get('type'), event.get('step'), event.get('status')) == ('workflow_step', 'action', 'running'):
                        workflow.toggle_pause()
                        workflow.toggle_pause()

                workflow = self.workflow(node, wait('tail'), emit=on_event)
                with patch('autohsr.workflow_audio.play') as play:
                    report = self.run_offline(workflow, [self.present] * 3)
                play.assert_not_called()
                self.assertEqual(report.status, 'partial')
                self.assertTrue(report.workflow['input_blocked'])
                self.assertEqual(body_steps(report), ['loop' if form == 'while' else 'gate', 'action'])
                self.assertEqual(report.workflow['steps'][-1]['status'], 'partial')
                self.assert_receipt(observations(report)[0], found=True, passed=form != 'else',
                                    phase='iteration' if form == 'while' else 'branch')

    def test_late_focus_after_branch_intent_cannot_start_its_first_action(self):
        node = screen_if()
        node['steps'] = [dict(id='action', type='task', task='workflow_audio', params=dict(path='prompt.wav'))]

        def on_event(event):
            if (event.get('type'), event.get('step'), event.get('status')) == ('workflow_step', 'action', 'running'):
                self.window.guard.side_effect = FocusLost('synthetic foreground loss during the branch intent')

        with patch('autohsr.workflow_audio.play') as play:
            report = self.run_offline(self.workflow(node, emit=on_event), [self.present] * 3)
        play.assert_not_called()
        self.assertEqual(report.status, 'partial')
        self.assertEqual(body_steps(report), ['gate', 'action'])
        self.assert_receipt(observations(report)[0], found=True, passed=True)

    def test_intent_and_report_verification_fail_before_branch(self):
        workflow = self.workflow(screen_if())
        original_record = workflow._record

        def fail_intent(data):
            if data['event'] == 'intent' and data['type'] == 'screen_condition':
                raise OSError('fake intent failure')
            return original_record(data)

        with patch.object(workflow, '_record', side_effect=fail_intent):
            report = self.run_offline(workflow, [self.present] * 3)
        self.assertEqual(report.status, 'partial')
        self.window.capture.assert_not_called()
        self.assertEqual(body_steps(report), ['gate'])

        workflow = self.workflow(screen_if())
        original_record = workflow._record

        def fail_result(data):
            if data['event'] == 'result' and data['type'] == 'screen_condition':
                raise OSError('fake result publication failure')
            return original_record(data)

        with patch.object(workflow, '_record', side_effect=fail_result):
            report = self.run_offline(workflow, [self.present] * 3)
        self.assertEqual(report.status, 'partial')
        self.assertEqual(body_steps(report), ['gate'])
        self.assertIn('result publication failure', report.error)
        self.assert_receipt(observations(report)[0], found=True, passed=True)

        def corrupt_report(native, window):
            path = Path(native.report.run_dir) / 'report.json'
            data = json.loads(path.read_bytes())
            data['workflow_screen'] = {'image_found': False}
            path.write_text(json.dumps(data), 'utf-8')

        report = self.run_offline(self.workflow(screen_if()), [self.present] * 3, after_publish=corrupt_report)
        self.assertEqual(report.status, 'partial')
        self.assertEqual(body_steps(report), ['gate'])
        self.assertNotIn('condition', observations(report)[0])

    def test_observation_uses_the_same_runtime_execution_limit(self):
        with patch('autohsr.task_workflow_run.MAX_EXECUTIONS', 1):
            report = self.run_offline(self.workflow(screen_if()), [self.present] * 3)
        self.assertEqual(report.status, 'partial')
        self.assertEqual(body_steps(report), ['gate'])
        self.assertEqual(observations(report), [])
        self.window.capture.assert_not_called()

    def test_schedule_freezes_template_and_counts_condition_as_game(self):
        source = self.root / 'flow.json'
        source.write_text(json.dumps(recipe(screen_if())), 'utf-8')
        plan = validate(dict(version=1, id='offline', name='Condition', time='08:30', weekdays=[1],
                             target=dict(type='workflow', path=source.name)))
        executor = NativeScheduleExecutor(self.settings, base_dir=self.root, run_root=self.root / 'runs')
        budget, digest = executor.preview_activation(plan)
        manifest = executor.freeze(plan)
        self.assertTrue(budget['contains_game_tasks'])
        self.assertEqual(budget['whole_batch'], dict(workflow_steps=3, daily_stamina_max=0, du_runs_max=0))
        self.assertEqual(manifest['sha256'], digest)
        entry, = manifest['dependencies']
        self.assertEqual(Path(entry['path']), self.template)
        self.assertEqual(entry['sha256'], hashlib.sha256(self.template.read_bytes()).hexdigest())
        repeat = deepcopy(plan)
        repeat['repeat']['count'] = 2
        with self.assertRaisesRegex(ScheduleError, '游戏计划重复'):
            executor.freeze(repeat)
        scheduled = executor.create(plan['target'], manifest, lambda event: None)
        self.assertEqual(self.run_offline(scheduled, [self.present] * 3).status, 'success')
        stale = executor.create(plan['target'], manifest, lambda event: None)
        self.template.write_bytes(b'changed before trigger')
        with patch('autohsr.app.find_game', side_effect=AssertionError('stale plan reached game')):
            with self.assertRaises(ScheduleSourceUnverified):
                stale.run()


if __name__ == '__main__':
    unittest.main()
