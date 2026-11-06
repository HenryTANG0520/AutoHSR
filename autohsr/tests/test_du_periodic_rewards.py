"""Periodic reward receipts through the real Context and fake native sends."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2

from autohsr import du_periodic_rewards as periodic, windows
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.du_reward_store import NAME, digest, encoded, preflight
from autohsr.du_rewards_only import run_rewards
from autohsr.models import AutomationError, RunReport, Stopped
from autohsr.storage import hold_read_sources
from autohsr.tests.test_du_rewards_only import dot, home, overlay, page, token
from autohsr.weekly_plan import CHINA


NOW = datetime(2026, 10, 26, 9, 35, tzinfo=CHINA)


def points_home(marked, current=18000):
    scene = home()
    scene.tokens += [token('本期剩余时间：6天18小时', .100, .871, .147),
                     token(f'{current}/18000', .159, .926, .096)]
    if marked:
        dot(scene, .210, .896)
    return scene


def points_panel(*, claimed=False, uid='100000000', omit_last=False):
    scene = page([token('积分奖励', .09, .317), token('规则说明', .83, .317),
                  token('当前积分', .106, .650), token('18000/18000', .150, .694, .09),
                  token('本期剩余时间：6天18小时', .12, .348, .14), token(f'UID:{uid}', .07, .975)])
    for i, threshold in enumerate(range(1800, 18001, 1800)):
        x = .081 + i * .0906
        if i == 9 and omit_last:
            break
        if claimed:
            cx, cy = round(x * 1280), 343
            cv2.ellipse(scene.image, (cx, cy), (16, 14), 0, 0, 320, (230, 230, 230), 2)
            cv2.line(scene.image, (cx-9, cy-1), (cx-2, cy+5), (230, 230, 230), 3)
            cv2.line(scene.image, (cx-2, cy+5), (cx+14, cy-9), (230, 230, 230), 3)
        else:
            scene.tokens.append(token(str(threshold), x, .547, .034))
            col = round(x * 1280)
            scene.image[324:365, col-26:col+26] = 150
    if not claimed:
        scene.tokens.append(token('一键领取', .86, .669))
        scene.image[453:504, 975:1210] = (70, 175, 240)
    return scene


def twice(scene):
    other = deepcopy(scene)
    other.image[0, 0] = 220
    return scene, other


class PeriodicRewardTests(unittest.TestCase):
    def play(self, frames, *, gate=lambda: None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        directory = root / 'run'
        directory.mkdir()
        geometry = windows.Geometry(0, 0, 1280, 720)
        runner = SimpleNamespace(settings=Settings(action_delay=0),
                                 report=RunReport(operation='du_rewards', run_dir=str(directory)),
                                 input_epoch=0, inactive_duration=0., checkpoint=Mock(), log=Mock())
        window = windows.GameWindow.__new__(windows.GameWindow)
        window.hwnd = 12345
        window.guard = Mock(return_value=geometry)
        vision = Mock()
        feed = iter(frames)

        def capture():
            scene = deepcopy(next(feed, None))
            if scene is None:
                raise Stopped('fake frame sequence ended')
            scene.geometry = geometry
            vision.read.return_value = scene
            return scene.image, geometry

        window.capture = capture
        native = SimpleNamespace(
            SendInput=Mock(side_effect=lambda count, *_: count),
            GetAsyncKeyState=lambda _key: 0,
            GetSystemMetrics=lambda i: {76:0, 77:0, 78:1280, 79:720}[i],
            MapVirtualKeyW=lambda *_: 1,
        )
        context = Context(runner, window, vision)
        context.sleep = Mock()
        return root, context, native, patch.multiple(windows, user32=native, require_followup_week=gate)

    def test_full_receipt_binds_consecutive_feedback_and_cannot_drop_original_tier(self):
        frames = [*twice(points_home(True)), *twice(points_panel()), *twice(overlay()),
                  *twice(points_panel(claimed=True)), *twice(points_home(False))]
        root, context, native, simulated = self.play(frames)
        with simulated, patch.object(periodic, 'local_now', return_value=NOW):
            self.assertEqual(run_rewards(context, periodic_only=True).status, 'ok')
        record = preflight(root)
        self.assertEqual([call.args[0] for call in native.SendInput.call_args_list], [3, 3, 3, 1, 1])
        self.assertTrue(record['periodic_rewards_verified'])
        self.assertEqual(record['claims'][0]['identity']['tiers'], list(periodic.TIERS))
        record['claims'][0]['identity']['tiers'].pop()
        record['digest'] = digest({key: value for key, value in record.items() if key != 'digest'})
        (root / NAME).write_bytes(encoded(record))
        Path(record['journal']).write_bytes(encoded(record))
        with self.assertRaises(AutomationError):
            preflight(root)

    def test_missing_last_check_keeps_claim_unknown_and_prevents_reentry(self):
        frames = [*twice(points_home(True)), *twice(points_panel()), *twice(overlay()),
                  *twice(points_panel(claimed=True, omit_last=True))]
        root, context, native, simulated = self.play(frames)
        with simulated, patch.object(periodic, 'local_now', return_value=NOW), self.assertRaises(Stopped):
            run_rewards(context, periodic_only=True)
        self.assertEqual(native.SendInput.call_count, 3)
        self.assertFalse(context.report.du_rewards['periodic_rewards_verified'])
        with self.assertRaises(AutomationError):
            preflight(root)

    def test_verified_delivery_survives_unconfirmed_home_return(self):
        frames = [*twice(points_home(True)), *twice(points_panel()), *twice(overlay()),
                  *twice(points_panel(claimed=True))]
        root, context, native, simulated = self.play(frames)
        with simulated, patch.object(periodic, 'local_now', return_value=NOW), self.assertRaises(Stopped):
            run_rewards(context, periodic_only=True)
        self.assertEqual(native.SendInput.call_count, 5)
        self.assertTrue(context.report.du_rewards['periodic_rewards_verified'])
        self.assertFalse(context.report.du_rewards['rewards_verified'])
        with self.assertRaises(AutomationError):
            preflight(root)

    def test_unverified_eligibility_returns_home_without_claiming(self):
        frames = [*twice(points_home(True)), *twice(points_panel(omit_last=True)), *twice(points_home(True))]
        root, context, native, simulated = self.play(frames)
        with simulated, patch.object(periodic, 'local_now', return_value=NOW):
            self.assertEqual(run_rewards(context, periodic_only=True).status, 'partial')
        self.assertEqual([call.args[0] for call in native.SendInput.call_args_list], [3, 1, 1])
        self.assertEqual(preflight(root)['claims'], [])

    def test_foreign_uid_and_duplicate_feedback_cannot_authorize_claim(self):
        for panels, error in ((twice(points_panel(uid='200000000')), AutomationError),
                              ((points_panel(),) * 2, Stopped)):
            with self.subTest(error=error.__name__):
                root, context, native, simulated = self.play([*twice(points_home(True)), *panels])
                with simulated, patch.object(periodic, 'local_now', return_value=NOW), self.assertRaises(error):
                    run_rewards(context, periodic_only=True)
                self.assertEqual(native.SendInput.call_count, 1)
                self.assertEqual(context.report.du_rewards['claims'], [])
                with self.assertRaises(AutomationError):
                    preflight(root)

    def test_prior_home_png_replacement_blocks_final_claim_submission(self):
        root, context, native, simulated = self.play([*twice(points_home(True)), *twice(points_panel())])

        @contextmanager
        def replaced_before_lock(paths):
            if native.SendInput.call_count == 1:
                Path(paths[2]).write_bytes(b'fixture replacement')
            with hold_read_sources(paths):
                yield

        with (simulated, patch.object(periodic, 'local_now', return_value=NOW),
              patch('autohsr.app.hold_read_sources', side_effect=replaced_before_lock),
              self.assertRaises(AutomationError)):
            run_rewards(context, periodic_only=True)
        self.assertEqual(native.SendInput.call_count, 1)
        with self.assertRaises(AutomationError):
            preflight(root)

    def test_non_full_score_and_reset_at_native_boundary_send_nothing(self):
        for current in (0, 18000):
            with self.subTest(current=current):
                clock = [NOW]

                def rollover():
                    clock[0] = datetime(2026, 11, 2, 4, 0, tzinfo=CHINA)

                root, context, native, simulated = self.play(twice(points_home(True, current)), gate=rollover)
                with (simulated, patch.object(periodic, 'local_now', side_effect=lambda: clock[0]),
                      self.assertRaises(AutomationError)):
                    run_rewards(context, periodic_only=True)
                native.SendInput.assert_not_called()
                if current == 0:
                    self.assertEqual(preflight(root)['status'], 'abort_before_input')
                else:
                    with self.assertRaises(AutomationError):
                        preflight(root)
