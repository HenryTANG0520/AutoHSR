"""High-difficulty configuration/CLI/native routing, with fake IO only."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
from itertools import count
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.challenge_cli import read_plan
from autohsr.config import Settings, SettingsError
from autohsr.models import AutomationError, EmptyCapture, FocusLost, RunReport, Scene, TaskResult
from autohsr.tests import test_challenge_pages as pages
from autohsr.tests import test_runner_recovery as native
from autohsr.windows import Geometry


PLAN = dict(mode='memory_of_chaos', levels=[7, 12],
    team1=['Firefly', 'RuanMei', 'Fugue', 'Lingsha'],
    team2=['Acheron', 'Jiaoqiu', 'Pela', 'Aventurine'])


def prepare_with_fake_window(root, scenes, *, plan=PLAN, foreground=True, vision=None, confidence=.65):
    from autohsr.__main__ import main

    config = root / 'config.json'
    Settings(challenge_plan=plan, overlay_logs=plan['mode'] == 'apocalyptic_shadow',
             ocr_confidence=confidence).save(config)
    pending = iter(scenes)
    current = None
    geometry = Geometry(0, 0, 1920, 1080)

    def capture():
        nonlocal current
        current = next(pending, EmptyCapture('fixture transition'))
        if isinstance(current, Exception):
            raise current
        return current.image.copy(), geometry

    def read(image, geometry):
        return Scene(list(current.tokens), image, geometry)

    window = Mock(hwnd=1, capture=Mock(side_effect=capture))
    if not foreground:
        window.guard.side_effect = FocusLost('fixture background')
    kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
    ticks = count(1000., .01)
    clock = SimpleNamespace(monotonic=lambda: next(ticks))
    output = io.StringIO()
    with ExitStack() as stack:
        stack.enter_context(patch('autohsr.app.ROOT', root))
        stack.enter_context(patch('autohsr.app.C.get_last_error', return_value=0))
        stack.enter_context(patch('autohsr.app.threading.Thread'))
        stack.enter_context(patch('autohsr.app.is_elevated', return_value=False))
        stack.enter_context(patch('autohsr.app.find_game', return_value=window))
        stack.enter_context(patch('autohsr.app.Vision', return_value=vision or SimpleNamespace(read=read)))
        stack.enter_context(patch('autohsr.windows.kernel32', kernel))
        stack.enter_context(patch.object(Runner, '_arm_hotkeys'))
        stack.enter_context(patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no startup')))
        stack.enter_context(patch('autohsr.overlay.OverlayService', side_effect=AssertionError('no overlay')))
        stack.enter_context(patch.object(Context, 'sleep', lambda ctx, seconds: ctx.checkpoint()))
        for module in ('app', 'challenge_prepare', 'challenge_pages'):
            stack.enter_context(patch(f'autohsr.{module}.time', clock))
        stack.enter_context(redirect_stdout(output))
        stack.enter_context(redirect_stderr(io.StringIO()))
        code = main(['--challenge-prepare', '--config', str(config)])
    return code, json.loads(output.getvalue()), window


class ChallengeIntegrationTests(unittest.TestCase):
    def test_cli_rejects_a_second_complete_uid_below_the_positive_threshold(self):
        original = pages.token('UID:100000000', (15, 1035, 200, 1060))
        conflict = pages.token('UID:200000000', (220, 1035, 420, 1060), score=.80)
        for phase, index, sent, saved_frames in (
            ('first existing', 0, 0, 0), ('second existing', 1, 0, 1),
            ('before selection', 1, 0, 1), ('after selection', 3, 1, 3),
        ):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as folder:
                scenes = [pages.setup_scene(level=7), pages.setup_scene(level=7)]
                if phase in ('before selection', 'after selection'):
                    scenes[:0] = [pages.lobby_scene(levels=(7, 8)), pages.lobby_scene(levels=(7, 8))]
                for scene in scenes:
                    scene.tokens.append(original)
                scenes[index].tokens.append(conflict)

                code, report, window = prepare_with_fake_window(Path(folder), scenes)
                data = report['challenge']
                self.assertEqual((code, window.click.call_count, data['preparation_page_verified']), (1, sent, False))
                self.assertIn('多个完整', report['error'])
                self.assertEqual([action['status'] for action in data['actions']], ['unknown'] if sent else [])
                self.assertEqual(len(data['observations']), saved_frames)
                self.assertTrue(all(Path(frame['path']).is_file() for frame in data['observations']))
                journal = Path(report['run_dir']) / 'challenge-preparation.json'
                self.assertEqual(json.loads(journal.read_text(encoding='utf-8')), data)
                self.assertTrue(any(journal.parent.glob('*_failure.png')))
                window.key.assert_not_called()

    def test_cli_ignores_uid_noise_and_complete_text_outside_the_uid_region(self):
        original = pages.token('UID:100000000', (15, 1035, 200, 1060))
        noise = [pages.token('UID:200000000', (490, 1035, 690, 1060)),
                 pages.token('UID:2000', (220, 1035, 420, 1060)),
                 pages.token('UID:200000000', (220, 1035, 420, 1060), score=.64)]
        with tempfile.TemporaryDirectory() as folder:
            scenes = [pages.setup_scene(level=7), pages.setup_scene(level=7)]
            scenes[0].tokens.append(original)
            scenes[1].tokens.extend([original, *noise])
            code, report, window = prepare_with_fake_window(Path(folder), scenes)
        self.assertEqual((code, report['status']), (0, 'success'))
        self.assertTrue(report['challenge']['preparation_page_verified'])
        window.click.assert_not_called()

    def test_dormant_default_and_explicit_save_do_not_access_game(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('autohsr.app.find_game', side_effect=AssertionError('no game')):
            path = Path(folder) / 'config.json'
            original = Settings(challenge_plan=PLAN)
            snapshot = replace(original)
            original.challenge_plan['team1'][0] = 'Herta'
            self.assertEqual(snapshot.challenge_plan['team1'][0], 'Firefly')
            snapshot.save(path)
            self.assertEqual(Settings.load(path).challenge_plan, PLAN)
            Settings().validate('save')
            self.assertEqual(Settings().challenge_plan, {})
        with self.assertRaises(SettingsError):
            Settings().validate('challenge_prepare')
        Settings(challenge_plan=dict(PLAN, mode='pure_fiction', levels=[1, 4])).validate('challenge_prepare')
        apocalypse = Settings(challenge_plan=dict(PLAN, mode='apocalyptic_shadow', levels=[1, 4]))
        apocalypse.validate('save')
        apocalypse.validate('challenge_prepare')

    def test_preview_has_strict_bounded_json_without_loading_config_or_runner(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            path.write_text(json.dumps(PLAN), encoding='utf-8')
            output = io.StringIO()
            with patch.object(Settings, 'load', side_effect=AssertionError('no config')), \
                 patch('autohsr.app.Runner', side_effect=AssertionError('no runner')), redirect_stdout(output):
                self.assertEqual(main(['--challenge-check', str(path)]), 0)
            data = json.loads(output.getvalue())
            self.assertEqual(data['plan'], PLAN)
            self.assertFalse(data['game_accessed'])
            for content in ('{"mode":"memory_of_chaos","mode":"pure_fiction"}',
                            '{"mode": NaN}', ' ' * (64 * 1024 + 1)):
                path.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError):
                    read_plan(path)

    def test_prepare_cli_freezes_current_override_without_saving(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            plan = Path(folder) / 'plan.json'
            Settings().save(config)
            before = config.read_bytes()
            for values in (PLAN, dict(PLAN, mode='pure_fiction', levels=[2, 4]),
                           dict(PLAN, mode='apocalyptic_shadow', levels=[3, 4])):
                with self.subTest(mode=values['mode']):
                    plan.write_text(json.dumps(values), encoding='utf-8')
                    fake = Mock()
                    fake.run.return_value = RunReport(status='success', operation='challenge_prepare')
                    with patch('autohsr.app.Runner', return_value=fake) as factory, \
                         redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        self.assertEqual(main(['--challenge-prepare', '--challenge-plan', str(plan), '--config', str(config)]), 0)
                    self.assertEqual(factory.call_args.kwargs['operation'], 'challenge_prepare')
                    self.assertEqual(factory.call_args.args[0].challenge_plan, values)
                    self.assertEqual(config.read_bytes(), before)

    def test_mixed_or_orphan_options_are_rejected_before_config_or_game(self):
        from autohsr.__main__ import main
        for args in (['--challenge-plan', 'not-read.json'],
                     ['--challenge-prepare', '--stamina', '10'],
                     ['--challenge-prepare', '--reward-only'],
                     ['--challenge-prepare', '--redemption-code', 'x'],
                     ['--challenge-prepare', '--du-team', 'x'],
                     ['--challenge-check', 'not-read.json', '--config', 'not-read.json']):
            with self.subTest(args=args), patch.object(Settings, 'load', side_effect=AssertionError('no config')), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)

    def test_native_preparation_has_no_daily_startup_or_resource_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            helper = native.RunnerRecoveryTests()
            self.addCleanup(helper.doCleanups)
            context, find = helper.fixture(Path(folder), SimpleNamespace())
            with patch('autohsr.challenge_prepare.prepare_challenge', return_value=TaskResult('challenge_prepare', 'ok', 'prepared only')) as prepare, \
                 patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no launch/navigation')), \
                 patch.object(Runner, '_arm_hotkeys'), \
                 patch('autohsr.recovery.BattleBudget', side_effect=AssertionError('no daily budget')):
                report = Runner(Settings(challenge_plan=PLAN, overlay_logs=False), operation='challenge_prepare').run()
            self.assertEqual(report.status, 'success')
            self.assertTrue(report.report_saved)
            self.assertEqual(report.stamina_spent, 0)
            self.assertEqual(report.battle_completed, 0)
            prepare.assert_called_once_with(context)
            find.assert_called_once()
            self.assertFalse((Path(folder) / 'runs/battle-session.json').exists())

    def test_generic_input_cannot_bypass_high_difficulty_contract(self):
        c = SimpleNamespace(report=RunReport(operation='challenge_prepare'))
        with self.assertRaises(AutomationError):
            Context._require_gameplay_input(c)
        with self.assertRaises(AutomationError):
            Context.redemption_input(c, None, None)
        with self.assertRaises(AutomationError):
            Context.challenge_prepare_input(SimpleNamespace(report=RunReport(operation='daily')), None, None)

    def test_outer_notification_names_the_preparation_scope_without_private_details(self):
        from autohsr.notify_runtime import report_message
        report = RunReport(status='success', operation='challenge_prepare', report_saved=True,
            challenge=dict(plan=PLAN, account_key='fake-private-key', preparation_page_verified=True)).to_dict()
        title, body = report_message(Settings(), report)
        self.assertIn('高难备战', title)
        self.assertNotIn('fake-private-key', title + body)
        self.assertNotIn('Firefly', title + body)
