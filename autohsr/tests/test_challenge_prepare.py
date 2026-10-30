"""Real preparation/Context with original-crop composites and fake IO.

These are protocol checks; the composites are not real full-page calibration.
"""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autohsr.app import Context
from autohsr.challenge_prepare import ChallengePreparation, prepare_challenge
from autohsr.config import Settings
from autohsr.models import AutomationError, FocusLost, InputInterrupted, Token
from autohsr.storage import replace_file
from autohsr.tests.test_challenge_integration import PLAN
from autohsr.tests import test_challenge_pages as pages
from autohsr.tests import test_redemption_run as fixtures


def lobby():
    return pages.lobby_scene(levels=(7, 8), stars={7:1, 8:2})


def setup():
    return pages.setup_scene(level=7)


def context(folder, scenes, **kwargs):
    c = fixtures.context(folder, scenes, **kwargs)
    c.settings = Settings(challenge_plan=PLAN)
    c.report.operation = 'challenge_prepare'
    c.challenge_prepare_input = lambda scene, action: Context.challenge_prepare_input(c, scene, action)
    return c


class ChallengePreparationTests(unittest.TestCase):
    def execute(self, c):
        clock = SimpleNamespace(monotonic=lambda: c.clock.value)
        with patch('autohsr.challenge_prepare.time', clock), patch('autohsr.challenge_pages.time', clock):
            return prepare_challenge(c)

    def test_current_level_click_once_then_independent_same_level_setup_is_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), setup(), setup()])
            result = self.execute(c)
            self.assertEqual(result.status, 'ok')
            data = c.report.challenge
            self.assertEqual(data['selected_level'], 7)
            self.assertTrue(data['preparation_page_verified'])
            self.assertFalse(data['team_verified'])
            self.assertFalse(data['battle_started'])
            self.assertFalse(data['completion_verified'])
            self.assertEqual([(a['intent'], a['status']) for a in data['actions']], [('select_level', 'verified')])
            for key in ('lobby_frames', 'after'):
                frames = data['actions'][0][key]
                self.assertEqual(len(frames), 2)
                self.assertLess(frames[0]['captured_at'], frames[1]['captured_at'])
                self.assertNotEqual(frames[0]['path'], frames[1]['path'])
            self.assertEqual(data, json.loads((Path(c.report.run_dir) / 'challenge-preparation.json').read_text(encoding='utf-8')))
            c.window.click.assert_called_once()
            c.window.key.assert_not_called()
            c.window.type_redemption_code.assert_not_called()

    def test_existing_same_level_setup_is_only_observed_without_selection_or_start(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [setup(), setup()])
            self.assertEqual(self.execute(c).status, 'ok')
            self.assertEqual(c.report.challenge['entry'], 'existing_team_setup')
            self.assertEqual(c.report.challenge['actions'], [])
            c.window.click.assert_not_called()
            c.window.key.assert_not_called()

    def test_unknown_after_selection_is_preserved_without_replaying_or_overwriting(self):
        with tempfile.TemporaryDirectory() as folder:
            unknown = setup()
            unknown.tokens = []
            c = context(folder, [lobby(), lobby()] + [unknown] * 100)
            with self.assertRaises(AutomationError):
                self.execute(c)
            data = c.report.challenge
            self.assertEqual(data['status'], 'partial')
            self.assertEqual(data['actions'][0]['status'], 'unknown')
            self.assertFalse(data['preparation_page_verified'])
            c.window.click.assert_called_once()
            original = (Path(c.report.run_dir) / 'challenge-preparation.json').read_bytes()
            with self.assertRaises(AutomationError):
                ChallengePreparation(c)
            self.assertEqual((Path(c.report.run_dir) / 'challenge-preparation.json').read_bytes(), original)

    def test_target_without_gold_source_or_ambiguous_level_group_never_clicks(self):
        for mutate in ('no_gold', 'duplicate'):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as folder:
                page = pages.lobby_scene(levels=(7, 8), stars={7:0, 8:2}) if mutate == 'no_gold' else lobby()
                if mutate == 'duplicate':
                    page.tokens.append(Token('07', .99, (.6, .4, .62, .43)))
                c = context(folder, [page] * 100)
                with self.assertRaises(AutomationError):
                    self.execute(c)
                self.assertEqual(c.report.challenge['actions'], [])
                c.window.click.assert_not_called()

    def test_wrong_level_or_account_after_selection_does_not_verify_preparation(self):
        for change in ('level', 'account'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                page = pages.setup_scene(level=8) if change == 'level' else setup()
                if change == 'account':
                    page.tokens.append(Token('UID:200000000', .99, (.01, .94, .10, .959)))
                c = context(folder, [lobby(), lobby()] + [page] * 100)
                with self.assertRaises(AutomationError):
                    self.execute(c)
                self.assertFalse(c.report.challenge['preparation_page_verified'])
                self.assertEqual(c.report.challenge['actions'][0]['status'], 'unknown')
                c.window.click.assert_called_once()

    def test_guard_epoch_focus_and_changed_plan_drop_pending_target(self):
        for change in ('epoch', 'focus', 'plan'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                c = context(folder, [lobby(), lobby()])
                def guard(*args):
                    if change == 'epoch':
                        c.runner.input_epoch += 1
                    elif change == 'plan':
                        c.settings.challenge_plan['levels'] = [8, 8]
                c.window.guard.side_effect = guard
                if change == 'focus':
                    c.window.click.side_effect = FocusLost('fake focus loss')
                with self.assertRaises((AutomationError, InputInterrupted)):
                    self.execute(c)
                self.assertEqual(c.report.challenge['actions'][0]['status'], 'unknown')
                if change == 'focus':
                    self.assertEqual(c.window.click.call_count, 1)
                else:
                    c.window.click.assert_not_called()

    def test_failed_pending_write_or_changed_png_cannot_authorize_click(self):
        for change in ('write', 'png'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                c = context(folder, [lobby(), lobby()])
                if change == 'png':
                    def input_(scene, action):
                        source = c.report.challenge['actions'][-1]['before']
                        Path(source['path']).write_bytes(b'changed source')
                        Context.challenge_prepare_input(c, scene, action)
                    c.challenge_prepare_input = input_
                def publish(source, destination):
                    data = json.loads(source.read_text(encoding='utf-8'))
                    if change == 'write' and data.get('actions') and data['actions'][-1]['status'] == 'pending':
                        raise OSError('fake disk lock')
                    return replace_file(source, destination)
                with patch('autohsr.challenge_prepare.replace_file', side_effect=publish), \
                     self.assertRaises((OSError, AutomationError)):
                    self.execute(c)
                c.window.click.assert_not_called()

    def test_duplicate_capture_cannot_be_second_independent_lobby(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), lobby(), setup(), setup()], duplicate_at=(1,))
            self.assertEqual(self.execute(c).status, 'ok')
            frames = c.report.challenge['actions'][0]['lobby_frames']
            self.assertLess(frames[0]['captured_at'], frames[1]['captured_at'])
            c.window.click.assert_called_once()

    def test_wrong_operation_or_missing_run_directory_is_rejected_before_capture(self):
        for change in ('operation', 'directory'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                c = context(folder, [])
                if change == 'operation':
                    c.report.operation = 'daily'
                else:
                    c.report.run_dir = str(Path(folder) / 'not-created')
                with self.assertRaises(AutomationError):
                    ChallengePreparation(c)
                c.window.click.assert_not_called()
