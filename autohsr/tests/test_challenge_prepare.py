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
from autohsr.models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, Stopped, Token
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


def track_captures(c, changes):
    original = c.snapshot
    seen = []

    def snapshot():
        scene = original()
        index = len(seen)
        seen.append(scene)
        if index in changes:
            changes[index](scene)
        return scene

    c.snapshot = snapshot
    return seen


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

    def test_setup_is_rechecked_after_second_observation_is_saved(self):
        for select in (False, True):
            for change, error in (('epoch', InputInterrupted), ('age', AutomationError), ('stop', Stopped)):
                with self.subTest(select=select, change=change), tempfile.TemporaryDirectory() as folder:
                    scenes = [lobby(), lobby()] if select else []
                    c = context(folder, scenes + [setup(), setup()])

                    def publish(source, destination):
                        data = json.loads(source.read_text(encoding='utf-8'))
                        replace_file(source, destination)
                        last_kinds = [frame['kind'] for frame in data['observations'][-2:]]
                        if data['status'] == 'running' and last_kinds == ['team_setup', 'team_setup']:
                            if change == 'epoch':
                                c.runner.input_epoch += 1
                            elif change == 'age':
                                c.clock.value += 8.1
                            else:
                                c.checkpoint.side_effect = Stopped('synthetic stop during observation save')

                    with patch('autohsr.challenge_prepare.replace_file', side_effect=publish), self.assertRaises(error):
                        self.execute(c)

                    journal = Path(c.report.run_dir) / 'challenge-preparation.json'
                    saved = json.loads(journal.read_text(encoding='utf-8'))
                    failure_status = 'partial' if select else 'failed'
                    self.assertEqual(saved['status'], 'stopped' if change == 'stop' else failure_status)
                    self.assertFalse(saved['preparation_page_verified'])
                    self.assertIsNone(saved['selected_level'])
                    self.assertNotIn('preparation_frames', saved)
                    self.assertEqual([action['status'] for action in saved['actions']], ['unknown'] if select else [])
                    frames = saved['observations'][-2:]
                    self.assertEqual([frame['kind'] for frame in frames], ['team_setup', 'team_setup'])
                    self.assertTrue(all(Path(frame['path']).is_file() for frame in frames))
                    self.assertEqual(c.window.click.call_count, int(select))
                    c.window.key.assert_not_called()

    def test_final_preparation_publication_rechecks_epoch_on_sharing_retry(self):
        for select in (False, True):
            for interrupted in (False, True):
                with self.subTest(select=select, interrupted=interrupted), tempfile.TemporaryDirectory() as folder:
                    scenes = [lobby(), lobby()] if select else []
                    c = context(folder, scenes + [setup(), setup()])
                    real_replace = Path.replace
                    attempts = []

                    def publish(source, destination):
                        candidate = json.loads(source.read_text(encoding='utf-8'))
                        if candidate['status'] == 'prepared':
                            self.assertFalse(c.report.challenge['preparation_page_verified'])
                            if select:
                                self.assertEqual(c.report.challenge['actions'][0]['status'], 'submitted')
                            attempts.append(candidate['status'])
                            if len(attempts) == 1:
                                raise PermissionError('synthetic sharing violation')
                        return real_replace(source, destination)

                    def between_attempts(_seconds):
                        if interrupted:
                            c.runner.input_epoch += 1

                    with patch.object(Path, 'replace', publish), \
                            patch('autohsr.storage.time', SimpleNamespace(sleep=between_attempts)):
                        if interrupted:
                            with self.assertRaises(InputInterrupted):
                                self.execute(c)
                        else:
                            self.assertEqual(self.execute(c).status, 'ok')

                    journal = Path(c.report.run_dir) / 'challenge-preparation.json'
                    saved = json.loads(journal.read_text(encoding='utf-8'))
                    self.assertEqual(len(attempts), 1 if interrupted else 2)
                    self.assertEqual(saved['preparation_page_verified'], not interrupted)
                    self.assertEqual(saved['selected_level'], None if interrupted else 7)
                    self.assertEqual('preparation_frames' in saved, not interrupted)
                    self.assertEqual([frame['kind'] for frame in saved['observations'][-2:]],
                                     ['team_setup', 'team_setup'])
                    self.assertTrue(all(Path(frame['path']).is_file() for frame in saved['observations'][-2:]))
                    self.assertEqual([action['status'] for action in saved['actions']],
                                     [('unknown' if interrupted else 'verified')] if select else [])
                    self.assertEqual(c.window.click.call_count, int(select))
                    c.window.key.assert_not_called()

    def test_final_preparation_publication_keeps_the_original_feedback_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), setup(), setup(), setup()])
            real_replace = Path.replace
            attempts = []

            def slow_blank(_scene):
                c.clock.value += 28.9
                raise EmptyCapture('synthetic slow blank frame')

            def publish(source, destination):
                candidate = json.loads(source.read_text(encoding='utf-8'))
                if candidate['status'] == 'prepared':
                    attempts.append(candidate['status'])
                    if len(attempts) == 1:
                        raise PermissionError('synthetic sharing violation')
                return real_replace(source, destination)

            track_captures(c, {2: slow_blank})
            with patch.object(Path, 'replace', publish), \
                    patch('autohsr.storage.time', SimpleNamespace(sleep=lambda _: c.sleep(.4))), \
                    self.assertRaisesRegex(AutomationError, '超过有限观察时间'):
                self.execute(c)

            journal = Path(c.report.run_dir) / 'challenge-preparation.json'
            saved = json.loads(journal.read_text(encoding='utf-8'))
            self.assertEqual(len(attempts), 1)
            self.assertLess(c.clock.value - c.last_scene.captured_at, 8)
            self.assertFalse(saved['preparation_page_verified'])
            self.assertEqual(saved['actions'][0]['status'], 'unknown')
            c.window.click.assert_called_once()
            c.window.key.assert_not_called()

    def assert_feedback_pair_after_gap(self, gap):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), setup(), setup(), setup(), setup()])
            seen = track_captures(c, {3: gap})
            self.assertEqual(self.execute(c).status, 'ok')
            self.assertEqual(len(seen), 6)
            action = c.report.challenge['actions'][0]
            self.assertEqual(action['status'], 'verified')
            self.assertEqual([item['captured_at'] for item in action['after']],
                             [scene.captured_at for scene in seen[4:]])
            c.window.click.assert_called_once()
            c.window.key.assert_not_called()

    def test_post_selection_missing_account_requires_a_new_consecutive_pair(self):
        # The fake snapshot appends its sole account token after page tokens.
        self.assert_feedback_pair_after_gap(lambda scene: scene.tokens.pop())

    def test_post_selection_empty_capture_cannot_bridge_two_setup_frames(self):
        def empty(scene):
            raise EmptyCapture('synthetic blank frame')

        self.assert_feedback_pair_after_gap(empty)

    def test_initial_account_check_remains_strict(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), lobby()])
            seen = track_captures(c, {1: lambda scene: scene.tokens.pop()})
            with self.assertRaisesRegex(AutomationError, '账号标识未完整'):
                self.execute(c)
            self.assertEqual(len(seen), 2)
            self.assertEqual(c.report.challenge['actions'], [])
            c.window.click.assert_not_called()

    def test_post_selection_rejects_changed_or_conflicting_account_immediately(self):
        for conflict in (False, True):
            with self.subTest(conflict=conflict), tempfile.TemporaryDirectory() as folder:
                c = context(folder, [lobby(), lobby(), setup(), setup(), setup()])

                def change_account(scene):
                    if not conflict:
                        scene.tokens.pop()
                    scene.tokens.append(Token('UID:200000000', .99, (.01, .96, .10, .99)))

                seen = track_captures(c, {2: change_account})
                with self.assertRaisesRegex(AutomationError, '账号标识未完整' if conflict else '账号改变'):
                    self.execute(c)
                self.assertEqual(len(seen), 3)
                self.assertEqual(c.report.challenge['actions'][0]['status'], 'unknown')
                c.window.click.assert_called_once()

    def test_post_selection_blank_does_not_hide_epoch_change_or_stop(self):
        for signal, error in (('epoch', InputInterrupted), ('plan', AutomationError), ('stop', Stopped)):
            with self.subTest(signal=signal), tempfile.TemporaryDirectory() as folder:
                c = context(folder, [lobby(), lobby(), setup(), setup(), setup()])

                def interrupt(scene):
                    if signal == 'epoch':
                        c.runner.input_epoch += 1
                    elif signal == 'plan':
                        c.settings.challenge_plan['levels'] = [8, 8]
                    else:
                        c.checkpoint.side_effect = Stopped('synthetic stop')
                    raise EmptyCapture('synthetic blank frame')

                seen = track_captures(c, {2: interrupt})
                with self.assertRaises(error):
                    self.execute(c)
                self.assertEqual(len(seen), 3)
                self.assertEqual(c.report.challenge['actions'][0]['status'], 'unknown')
                c.window.click.assert_called_once()

    def test_post_selection_duplicate_breaks_continuity(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), setup(), setup(), setup(), setup()], duplicate_at=(3,))
            seen = track_captures(c, {})
            self.assertEqual(self.execute(c).status, 'ok')
            self.assertEqual(len(seen), 6)
            action = c.report.challenge['actions'][0]
            self.assertEqual([item['captured_at'] for item in action['after']],
                             [scene.captured_at for scene in seen[4:]])
            c.window.click.assert_called_once()

    def test_post_selection_cannot_use_a_capture_from_before_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), setup(), setup(), setup()])

            def old_capture(scene):
                scene.captured_at = c.report.challenge['actions'][0]['before']['captured_at']

            seen = track_captures(c, {2: old_capture})
            self.assertEqual(self.execute(c).status, 'ok')
            self.assertEqual(len(seen), 5)
            action = c.report.challenge['actions'][0]
            self.assertEqual([item['captured_at'] for item in action['after']],
                             [scene.captured_at for scene in seen[3:]])
            c.window.click.assert_called_once()

    def test_post_selection_reordered_capture_cannot_follow_a_newer_unreadable_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), setup(), setup(), setup(), setup(), setup()])

            def reorder(scene):
                scene.captured_at = (seen[2].captured_at + seen[3].captured_at) / 2

            seen = track_captures(c, {3: lambda scene: scene.tokens.pop(), 4: reorder})
            self.assertEqual(self.execute(c).status, 'ok')
            self.assertEqual(len(seen), 7)
            action = c.report.challenge['actions'][0]
            self.assertEqual([item['captured_at'] for item in action['after']],
                             [scene.captured_at for scene in seen[5:]])
            c.window.click.assert_called_once()

    def test_post_selection_second_frame_persistence_cannot_extend_feedback_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), setup(), setup(), setup()])

            def slow_blank(scene):
                c.clock.value += 28.9
                raise EmptyCapture('synthetic slow blank frame')

            def publish(source, destination):
                data = json.loads(source.read_text(encoding='utf-8'))
                if (data['actions'] and data['actions'][0]['status'] == 'submitted'
                        and [frame['kind'] for frame in data['observations'][-2:]] == ['team_setup', 'team_setup']):
                    c.clock.value += .5
                return replace_file(source, destination)

            seen = track_captures(c, {2: slow_blank})
            with patch('autohsr.challenge_prepare.replace_file', side_effect=publish), \
                    self.assertRaisesRegex(AutomationError, '同层备战页面'):
                self.execute(c)
            self.assertEqual(len(seen), 5)
            action = c.report.challenge['actions'][0]
            self.assertEqual(action['status'], 'unknown')
            self.assertNotIn('after', action)
            self.assertFalse(c.report.challenge['preparation_page_verified'])
            c.window.click.assert_called_once()

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
        for change in ('epoch', 'focus', 'plan', 'account_missing'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                c = context(folder, [lobby(), lobby()])
                def guard(*args):
                    if change == 'epoch':
                        c.runner.input_epoch += 1
                    elif change == 'plan':
                        c.settings.challenge_plan['levels'] = [8, 8]
                    elif change == 'account_missing':
                        c.last_scene.tokens.pop()
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

    def test_changed_target_intent_or_png_during_window_guard_blocks_click(self):
        for changed in ('target', 'intent', 'png'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                c = context(folder, [lobby(), lobby(), setup(), setup()])

                def guard(*args):
                    if changed == 'target':
                        c.last_scene.tokens = [token for token in c.last_scene.tokens if token.text != '07']
                    elif changed == 'intent':
                        (Path(c.report.run_dir) / 'challenge-preparation.json').write_text('{}', encoding='utf-8')
                    else:
                        source = c.report.challenge['actions'][0]['before']
                        Path(source['path']).write_bytes(b'changed after authorization')

                c.window.guard.side_effect = guard
                with self.assertRaises(AutomationError):
                    try:
                        self.execute(c)
                    finally:
                        c.window.click.assert_not_called()
                self.assertFalse(c.report.challenge['preparation_page_verified'])
                self.assertEqual(c.report.challenge['actions'][0]['status'], 'unknown')

    def test_final_png_reread_cannot_expire_the_scene_before_click(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [lobby(), lobby(), setup(), setup()])
            open_file = Path.open

            def delayed_open(path, *args, **kwargs):
                if c.window.guard.called and path == Path(c.report.challenge['actions'][0]['before']['path']):
                    c.clock.value = c.last_scene.captured_at + 8.01
                return open_file(path, *args, **kwargs)

            with patch.object(Path, 'open', delayed_open), \
                 self.assertRaisesRegex(AutomationError, '当前新鲜画面'):
                self.execute(c)
            c.window.click.assert_not_called()
            self.assertEqual(c.report.challenge['actions'][0]['status'], 'unknown')

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
