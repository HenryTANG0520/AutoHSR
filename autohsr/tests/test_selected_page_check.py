"""A generated page-check flow, its anonymous projection, and fake native replay."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import ctypes
from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2

from autohsr import selected_page_check as pages
from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.models import FocusLost, Scene, Stopped, Token
from autohsr.task_workflow import ACTIVITY_WORKFLOW_PAGES, MESSAGE_WORKFLOW_PAGE, PAGE_TASK, WORKFLOW_PAGES, WorkflowError
from autohsr.task_workflow_run import TaskWorkflowRunner, _bytes
from autohsr.tests.test_daily_reward_observe import ACCOUNT, OTHER, _Window, phone
from autohsr.windows import INPUT


def row(target, status, sent=None, unconfirmed=None):
    return dict(target=target, status=status, actions_sent=sent, actions_unconfirmed=unconfirmed)


def action(kind, source, expected, *, input_status='sent', destination=None):
    value = dict(action=kind, source_page=source, expected_pages=list(expected), input_status=input_status,
                 destination_status='verified' if destination else 'unknown')
    if destination:
        value['destination_page'] = destination
    return value


class PageCheckProjectionTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.recipe = pages.build_recipe(('phone', 'mail', 'odyssey'), base_dir=self.root)
        self.report = dict(operation='task_workflow', status='partial', report_saved=True,
                           run_dir=str(self.root / 'parent'), finished_at='2026-11-07T00:00:02+08:00',
                           workflow=dict(name=pages.NAME, selected_path=[], steps=[],
                                         definition_sha256=sha256(_bytes(self.recipe.document)).hexdigest()))
        self.sources = {}
        self.load = Mock(side_effect=self.sources.__getitem__)

    def record(self, target, status, actions, *, page_verified=None, account_verified=True):
        index = len(self.report['workflow']['steps']) + 1
        path = self.root / f'child-{index}' / 'report.json'
        positive = status == 'success' if page_verified is None else page_verified
        child = dict(operation=PAGE_TASK, report_saved=True, status=status, run_dir=str(path.parent),
                     workflow_navigation=dict(target=target, page_verified=positive, actions=actions),
                     error='synthetic-private-message')
        self.sources[path] = raw = _bytes(child)
        facts = dict(status=status, page_verified=True) if positive else dict(status=status)
        self.report['workflow']['steps'].append(dict(step=f'page_{target}', task=PAGE_TASK, type='task',
            sequence=index, trail=[], status=status, account_verified=account_verified, facts=facts,
            source=dict(path=str(path), sha256=sha256(raw).hexdigest())))
        return path

    def project(self, report=None):
        return pages.project_result(self.recipe, self.report if report is None else report, read_source=self.load)

    def test_preview_order_is_explicit_and_never_writes_or_starts(self):
        ordinary = tuple(page for page in WORKFLOW_PAGES if page not in (*ACTIVITY_WORKFLOW_PAGES, MESSAGE_WORKFLOW_PAGE))
        targets = (*reversed(ordinary), *ACTIVITY_WORKFLOW_PAGES)
        with patch.object(TaskWorkflowRunner, 'run', side_effect=AssertionError('preview cannot run')) as run:
            recipe = pages.build_recipe(targets, base_dir=self.root)
        self.assertEqual(tuple(step['params']['target'] for step in recipe.steps), targets)
        self.assertTrue(all(step['task'] == PAGE_TASK and step['on_failure'] == 'stop' for step in recipe.steps))
        self.assertEqual(recipe.profile['executions'], len(targets))
        self.assertTrue(all(value == 0 for field, value in recipe.profile.items() if field != 'executions'))
        self.assertEqual(list(self.root.iterdir()), [])
        run.assert_not_called()
        for bad in (None, [], 'mail', ('mail', 'mail'), ['world'], ['unknown'], ['mail', {}], ['odyssey', 'mail'],
                    ['reward_guide', 'mail'], ['mail', 'reward_guide', 'odyssey'], ['mail', 'messages']):
            with self.subTest(selection=bad), self.assertRaises(WorkflowError):
                pages.build_recipe(bad, base_dir=self.root)

    def test_unknown_arrival_preserves_recorded_send_and_stops_projection_at_the_unrun_page(self):
        self.record('phone', 'success', [])
        self.record('mail', 'partial', [action('open_mail', 'phone', ('mail',))])
        projection = self.project()
        self.assertEqual(projection, dict(status='partial', pages=[
            row('phone', 'verified', 0, 0), row('mail', 'unknown', 1, 0), row('odyssey', 'not_run'),
        ]))
        raw = json.dumps(projection, ensure_ascii=False)
        for private in ('synthetic-private-message', 'report.json', 'sha256', 'run_dir', str(self.root)):
            self.assertNotIn(private, raw)

    def test_incomplete_tail_requires_a_saved_final_report_and_only_the_original_setup_fields(self):
        self.record('phone', 'success', [])
        tail = dict(sequence=2, step='page_mail', type='task', task=PAGE_TASK, trail=[],
                    status='running', started_at='2026-11-07T00:00:01+08:00')
        self.report['workflow']['steps'].append(tail)
        self.assertEqual(self.project(), dict(status='partial', pages=[
            row('phone', 'verified', 0, 0), row('mail', 'unknown'), row('odyssey', 'not_run'),
        ]))
        self.load.reset_mock()
        invalid = [dict(self.report, status='running'), dict(self.report, finished_at=''),
                   dict(self.report, report_saved=False), dict(self.report, status='failed')]
        extra_source = dict(path=str(self.root / 'child-2' / 'report.json'), sha256='a' * 64)
        for change in (dict(sequence=3), dict(step='page_odyssey'), dict(source=extra_source),
                       dict(account_verified=True), dict(facts={'page_verified': True}),
                       dict(actions_sent=1), dict(finished_at=self.report['finished_at'])):
            report = deepcopy(self.report)
            report['workflow']['steps'][-1].update(change)
            invalid.append(report)
        double = deepcopy(self.report)
        double['workflow']['steps'].append(dict(tail, sequence=3, step='page_odyssey'))
        invalid.append(double)
        for report in invalid:
            with self.subTest(report=report):
                self.assertEqual(self.project(report), dict(status='unknown', pages=[
                    row('phone', 'unknown'), row('mail', 'unknown'), row('odyssey', 'unknown'),
                ]))
        self.load.assert_not_called()

    def test_short_send_and_changed_source_are_distinct_from_zero_actions(self):
        self.record('phone', 'success', [])
        path = self.record('mail', 'partial', [action('open_mail', 'phone', ('mail',), input_status='unconfirmed')])
        self.assertEqual(self.project()['pages'][1], row('mail', 'unknown', 0, 1))
        self.sources[path] += b'\n'
        self.assertEqual(self.project()['pages'], [row('phone', 'verified', 0, 0), row('mail', 'unknown'),
                                                  row('odyssey', 'not_run')])

    def test_odyssey_chained_receipt_uses_only_the_selected_target_and_native_action_count(self):
        self.record('phone', 'success', [])
        self.record('mail', 'success', [action('open_mail', 'phone', ('mail',), destination='mail')])
        self.record('odyssey', 'success', [
            action('return_to_hub', 'mail', ('world', 'phone'), destination='phone'),
            action('open_journey_events', 'phone', ('activity_list', 'odyssey'), destination='activity_list'),
            action('open_odyssey', 'activity_list', ('odyssey',), destination='odyssey'),
        ])
        self.report['status'] = 'success'
        self.assertEqual(self.project(), dict(status='success', pages=[
            row('phone', 'verified', 0, 0), row('mail', 'verified', 1, 0), row('odyssey', 'verified', 3, 0),
        ]))

    def test_rejects_wrong_scope_order_or_nonlocal_source_before_reading(self):
        self.record('phone', 'success', [])
        for report in (dict(self.report, report_saved=1), dict(self.report, finished_at=''),
                       dict(self.report, status='success'),
                       dict(self.report, workflow=dict(self.report['workflow'], selected_path=[0])),
                       dict(self.report, workflow=dict(self.report['workflow'], definition_sha256='0' * 64))):
            self.assertEqual(self.project(report)['status'], 'unknown')
        report = deepcopy(self.report)
        report['workflow']['steps'][0]['step'] = 'page_mail'
        self.assertEqual(self.project(report)['status'], 'unknown')
        self.load.assert_not_called()

        source = self.report['workflow']['steps'][0]['source']
        for bad in (str(self.root.parent / 'other-run' / 'report.json'), r'\\network.invalid\runs\other\report.json',
                    str(self.root / 'parent' / 'report.json'), str(self.root / 'child' / 'proof.json')):
            source['path'] = bad
            self.assertEqual(self.project()['pages'][0], row('phone', 'unknown'))
        self.load.assert_not_called()

    def test_parent_account_and_child_target_or_action_consistency_gate_page_facts(self):
        child_path = self.record('phone', 'success', [], account_verified=False)
        self.assertEqual(self.project()['pages'][0], row('phone', 'unknown', 0, 0))
        entry = self.report['workflow']['steps'][0]
        entry['account_verified'] = True
        child = json.loads(self.sources[child_path])
        for change in (dict(target='mail'), dict(actions=[
                action('open_phone', 'world', ('phone',), input_status='unconfirmed', destination='phone'),
        ])):
            modified = dict(child, workflow_navigation=child['workflow_navigation'] | change)
            self.sources[child_path] = raw = _bytes(modified)
            entry['source']['sha256'] = sha256(raw).hexdigest()
            self.assertEqual(self.project()['pages'][0], row('phone', 'unknown'))

    def test_saved_projection_reads_only_current_local_run_root_and_bound_bytes(self):
        path = self.record('phone', 'success', [])
        path.parent.mkdir()
        path.write_bytes(self.sources[path])
        self.assertEqual(pages.saved_result(self.recipe, self.report, runs_root=self.root)['pages'][0],
                         row('phone', 'verified', 0, 0))
        self.assertEqual(pages.saved_result(self.recipe, self.report, runs_root=self.root / 'other')['pages'][0],
                         row('phone', 'unknown'))
        path.write_bytes(self.sources[path] + b'\n')
        self.assertEqual(pages.saved_result(self.recipe, self.report, runs_root=self.root)['pages'][0],
                         row('phone', 'unknown'))

    def test_linked_child_report_is_never_used_even_when_hash_matches(self):
        path = self.record('phone', 'success', [])
        path.parent.mkdir()
        other = self.root / 'different.json'
        other.write_bytes(self.sources[path])
        try:
            path.symlink_to(other)
        except OSError:
            self.skipTest('Windows file link privilege is unavailable')
        self.assertEqual(pages.saved_result(self.recipe, self.report, runs_root=self.root)['pages'][0],
                         row('phone', 'unknown'))

    def test_cli_preview_and_invalid_order_do_not_load_settings_or_access_game(self):
        output = io.StringIO()
        with patch.object(Settings, 'load', side_effect=AssertionError('preview read config')), \
                patch.object(TaskWorkflowRunner, 'run', side_effect=AssertionError('preview ran game')), \
                redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--screen-check-plan', 'mail', 'odyssey']), 0)
            self.assertEqual(main(['--screen-check-pages', 'odyssey', 'mail']), 2)
            with self.assertRaises(SystemExit) as invalid:
                main(['--screen-check-pages', 'mail', '--stamina', '10'])
            self.assertEqual(invalid.exception.code, 2)
        self.assertEqual(json.loads(output.getvalue())['pages'], ['mail', 'odyssey'])

    def test_messages_preview_requires_a_separate_check(self):
        for argv, expected in ((['messages'], 0), (['messages', 'phone'], 2)):
            with self.subTest(argv=argv), redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--screen-check-plan', *argv]), expected)
                if expected == 0:
                    self.assertEqual(json.loads(output.getvalue())['pages'], argv)

    def test_cli_rejects_bad_settings_as_anonymous_json_before_runner_start(self):
        config = self.root / 'config-private-fixture.json'
        for raw in ('{"private-fixture":', 'null', '{"private-fixture":true}'):
            with self.subTest(raw=raw):
                config.write_text(raw, encoding='utf8')
                errors = io.StringIO()
                with patch('autohsr.task_workflow_run.TaskWorkflowRunner', side_effect=AssertionError('invalid config ran game')), \
                        redirect_stderr(errors):
                    self.assertEqual(main(['--screen-check-pages', 'mail', '--config', str(config)]), 2)
                self.assertEqual(json.loads(errors.getvalue()),
                                 dict(status='failed', error='所选页面核对无法读取有效的设置文件。'))


class PageCheckRunnerTests(TestCase):
    def run_case(self, targets, *, late_loss=False, short_send=False, account_drift=False, cli=False):
        with TemporaryDirectory() as temp, ExitStack() as stack:
            root = Path(temp).resolve()
            recipe = pages.build_recipe(targets, base_dir=root)
            packets = []
            changed = False
            start = phone()

            def mailbox(account):
                return Scene([account, Token('邮箱', .99, (.03, .027, .072, .054)),
                              Token('暂无邮件', .99, (.28, .45, .34, .49))], start.image)

            if targets == ('messages',):
                from autohsr.tests.test_daily_message_world import bright_sequence, world_pair

                world, panel = (Scene(frame.tokens, cv2.resize(frame.image, (1920, 1080)))
                                for frame in (world_pair()[-1], bright_sequence()[-1]))

            def frames():
                if targets == ('messages',):
                    while True:
                        yield panel if packets else world
                current, different = mailbox(ACCOUNT), mailbox(OTHER)
                while True:
                    yield different if changed else current if packets else start

            def send(length, events, _size):
                packet = ctypes.cast(events, ctypes.POINTER(INPUT))
                packets.append(tuple(packet[index].mi.dwFlags for index in range(length)))
                return length - 1 if short_send and length == 3 else length

            window = _Window(frames())
            if targets == ('messages',):
                (root / 'config.ini').write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
                executable = root / 'StarRail.exe'
                executable.touch()
                window.current_executable = Mock(return_value=str(executable))
            original = Runner._save_run_report

            def save(runner, *args, **kwargs):
                nonlocal changed
                mail = runner.workflow_page == 'mail'
                if mail and late_loss:
                    window.guard.side_effect = FocusLost('fake late foreground loss')
                saved = original(runner, *args, **kwargs)
                if mail and account_drift:
                    changed = True
                return saved

            user = SimpleNamespace(GetAsyncKeyState=Mock(return_value=0), SendInput=Mock(side_effect=send),
                GetSystemMetrics=Mock(side_effect={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__))
            kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
            for name, value in (('autohsr.app.ROOT', root), ('autohsr.windows.user32', user),
                                ('autohsr.task_workflow_run.ROOT', root), ('autohsr.selected_page_check.ROOT', root),
                                ('autohsr.windows.kernel32', kernel),
                                ('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.SelectedPageQA.' + uuid4().hex)):
                stack.enter_context(patch(name, value))
            for name, options in (
                    ('autohsr.app.C.get_last_error', dict(return_value=0)),
                    ('autohsr.app.find_game', dict(return_value=window)),
                    ('autohsr.app.is_elevated', dict(return_value=False)),
                    ('autohsr.app.Vision', dict(side_effect=window.vision)),
                    ('autohsr.app.Context.template', dict(return_value=None)),
                    ('autohsr.app.Runner._arm_hotkeys', {}), ('autohsr.app.Runner._hotkeys', {}),
                    ('autohsr.task_workflow_run.TaskWorkflowRunner._hotkeys', {}),
                    ('autohsr.app.Runner._save_run_report', dict(new=save)),
                    ('autohsr.app.Runner._prepare_daily_game', dict(side_effect=AssertionError('no launch or login'))),
                    ('autohsr.overlay.OverlayService', dict(side_effect=AssertionError('no overlay')))):
                stack.enter_context(patch(name, **options))
            settings = Settings(overlay_logs=True, auto_launch=True, ocr_confidence=.91)
            if cli:
                path = root / 'config.json'
                settings.save(path)
                config_bytes = path.read_bytes()
                out = io.StringIO()
                with redirect_stdout(out), redirect_stderr(io.StringIO()):
                    code = main(['--screen-check-pages', *targets, '--config', str(path)])
                self.assertEqual(code, 1 if late_loss or short_send or account_drift else 0, out.getvalue())
                self.assertEqual(path.read_bytes(), config_bytes)
                window.focus.assert_not_called()
                return json.loads(out.getvalue()), packets, None
            runner = TaskWorkflowRunner(settings, recipe.document, root=root / 'runs', base_dir=recipe.base_dir)
            report = runner.run().to_dict()
            with (Path(report['run_dir']) / 'report.json').open(encoding='utf8') as source:
                self.assertEqual(json.load(source), report)
            projection = pages.saved_result(recipe, report, runs_root=root / 'runs')
            self.assertEqual((report['stamina_spent'], report['stamina_pending']), (0, 0))
            window.focus.assert_not_called()
            return projection, packets, report['workflow']

    def test_normal_flow_preserves_noop_then_one_native_click(self):
        for cli in (False, True):
            with self.subTest(cli=cli):
                projection, packets, _ = self.run_case(('phone', 'mail'), cli=cli)
                self.assertEqual(packets, [(0xC001, 0x0002, 0x0004)])
                self.assertEqual(projection, dict(status='success', pages=[row('phone', 'verified', 0, 0),
                                                                          row('mail', 'verified', 1, 0)]))

    def test_formal_message_diagnostic_projects_the_native_receipt(self):
        projection, packets, _ = self.run_case(('messages',), cli=True)
        self.assertEqual(packets, [(0xC001, 0x0002, 0x0004)])
        self.assertEqual(projection, dict(status='success', pages=[row('messages', 'verified', 1, 0)]))

    def test_late_loss_or_short_send_retains_prior_proof_and_never_runs_third_page(self):
        targets = ('phone', 'mail', 'odyssey')
        for condition, sent, unconfirmed in ((dict(late_loss=True), 1, 0), (dict(short_send=True), 0, 1)):
            with self.subTest(condition=condition):
                projection, packets, workflow = self.run_case(targets, **condition)
                self.assertEqual(len(packets), 2 if unconfirmed else 1)
                if unconfirmed:
                    self.assertEqual(packets[-1], (0x0004,))
                self.assertEqual([step['step'] for step in workflow['steps']], ['page_phone', 'page_mail'])
                self.assertEqual(projection, dict(status='partial', pages=[row('phone', 'verified', 0, 0),
                    row('mail', 'unknown', sent, unconfirmed), row('odyssey', 'not_run')]))

    def test_interrupted_step_setup_keeps_saved_prefix_and_never_starts_the_tail(self):
        targets = ('phone', 'mail', 'odyssey', 'reward_guide')
        original = TaskWorkflowRunner._record
        for outcome, error in (('partial', OSError), ('stopped', Stopped)):
            def record(runner, entry):
                if entry['event'] == 'intent' and entry['step'] == 'page_odyssey':
                    raise error('synthetic interruption before child startup')
                return original(runner, entry)

            with self.subTest(outcome=outcome), patch.object(TaskWorkflowRunner, '_record', new=record):
                projection, packets, workflow = self.run_case(targets)
                self.assertEqual(packets, [(0xC001, 0x0002, 0x0004)])
                self.assertEqual([step['status'] for step in workflow['steps']], ['success', 'success', 'running'])
                self.assertEqual(projection, dict(status=outcome, pages=[
                    row('phone', 'verified', 0, 0), row('mail', 'verified', 1, 0),
                    row('odyssey', 'unknown'), row('reward_guide', 'not_run'),
                ]))

    def test_account_change_blocks_the_second_page_and_preserves_the_first(self):
        projection, packets, workflow = self.run_case(('mail', 'assignments', 'phone'), account_drift=True)
        self.assertEqual(len(packets), 1)
        self.assertTrue(workflow['identity']['account_changed'])
        self.assertEqual(projection['pages'][0], row('mail', 'verified', 1, 0))
        self.assertEqual(projection['pages'][1]['status'], 'unknown')
        self.assertEqual(projection['pages'][2], row('phone', 'not_run'))
