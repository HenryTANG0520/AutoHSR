"""Official A0 CLI with a native click against synthetic Win32 and OCR."""
from contextlib import nullcontext, redirect_stderr, redirect_stdout
import ctypes as C
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.currency_wars_session import StandardSession
from autohsr.models import Scene, Token
from autohsr.tests.test_currency_wars_overclock import FIXTURES, changed_token, frame


OPEN_A0 = "--currency-wars-open-overclock-a0"
SELECT_MODE = "--currency-wars-configure-overclock"
JOURNAL = "currency-overclock-config.json"


class OverclockA0NativeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="autohsr-overclock-a0-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.runs = self.root / "runs"
        self.runs.mkdir()
        self.executable = self.root / "fake-client" / "StarRail.exe"
        self.executable.parent.mkdir()
        self.executable.write_bytes(b"synthetic client, never executed")
        self.client_ini = self.executable.with_name("config.ini")
        self.set_version("4.6.0")
        self.config = self.root / "explicit-config.json"
        Settings(game_path=str(self.executable), overlay_logs=False, action_delay=.3).save(self.config)
        self.config_bytes = self.config.read_bytes()
        self.geometry = windows.Geometry(31, 27, 960, 540)
        self.metrics = {76: -64, 77: -32, 78: 1600, 79: 900}
        self.hwnd = 71
        self.clock = 100.0

    def set_version(self, version):
        self.client_ini.write_text(f"[General]\ngame_version={version}\n", encoding="utf-8")

    def advance(self, seconds):
        self.clock += max(.001, seconds)

    def native_cli(self, *scenes, flag=OPEN_A0, on_capture=None, on_send=None):
        pending = iter(scenes)
        captures = 0
        packets = []
        at_send = []
        previous = set(self.runs.iterdir())
        geometry = self.geometry

        def client_rect(hwnd, rect):
            self.assertEqual(hwnd, self.hwnd)
            rect._obj.right = geometry.width
            rect._obj.bottom = geometry.height
            return 1

        def client_origin(hwnd, point):
            self.assertEqual(hwnd, self.hwnd)
            point._obj.x, point._obj.y = geometry.left, geometry.top
            return 1

        def grab(rect):
            nonlocal captures
            self.assertEqual(rect, dict(left=geometry.left, top=geometry.top, width=geometry.width,
                                        height=geometry.height))
            captures += 1
            self.advance(.01)
            if on_capture is not None:
                on_capture(captures)
            # Distinct, nonblack BGRA images for actual capture and PNG checks.
            image = np.zeros((geometry.height, geometry.width, 4), dtype=np.uint8)
            image[:, geometry.width // 2:, :3] = 80 + captures
            image[:, :, 3] = 255
            return image

        def recognize(image, captured_geometry):
            self.assertEqual(captured_geometry, geometry)
            scene = next(pending)
            return Scene(tokens=list(scene.tokens), image=image, geometry=geometry)

        def send_input(count, items, structure_size):
            self.assertEqual(count, len(items))
            self.assertEqual(structure_size, C.sizeof(windows.INPUT))
            if on_send is not None:
                on_send()
            packets.append([(item.type, item.mi.dwFlags, item.mi.dx, item.mi.dy) for item in items])
            current = [folder / JOURNAL for folder in self.runs.iterdir() if folder not in previous]
            self.assertEqual(len(current), 1)
            at_send.append(json.loads(current[0].read_bytes()))
            return count

        def process_path(hwnd):
            self.assertEqual(hwnd, self.hwnd)
            return str(self.executable)

        user32 = Mock()
        user32.EnumWindows.side_effect = lambda visitor, value: visitor(self.hwnd, value)
        user32.IsWindowVisible.side_effect = lambda hwnd: hwnd == self.hwnd
        user32.IsWindow.side_effect = lambda hwnd: hwnd == self.hwnd
        user32.IsIconic.return_value = 0
        user32.GetForegroundWindow.return_value = self.hwnd
        user32.GetAsyncKeyState.return_value = 0
        user32.GetClientRect.side_effect = client_rect
        user32.ClientToScreen.side_effect = client_origin
        user32.GetSystemMetrics.side_effect = self.metrics.__getitem__
        user32.SendInput.side_effect = send_input

        def runner_mutex(*_):
            C.set_last_error(0)
            return 1

        kernel32 = Mock()
        kernel32.CreateMutexW.side_effect = runner_mutex
        capture = SimpleNamespace(grab=grab)
        ocr = SimpleNamespace(read=recognize)
        with (
            patch("autohsr.app.ROOT", self.root),
            patch("autohsr.workflow_lease.NAME", f"Local\\AutoHSR.A0Test.{self.root.name}"),
            patch.object(windows, "user32", user32),
            patch.object(windows, "kernel32", kernel32),
            patch.object(windows, "process_path", side_effect=process_path),
            patch("autohsr.app.is_elevated", return_value=False),
            patch("autohsr.app.launch_game", side_effect=AssertionError("unexpected launch")),
            patch.object(Runner, "_prepare_daily_game", side_effect=AssertionError("unexpected preparation")),
            patch("mss.mss", return_value=nullcontext(capture)),
            patch("autohsr.app.IsolatedVision", return_value=ocr),
            patch.object(time, "monotonic", side_effect=lambda: self.clock),
            patch.object(time, "sleep", side_effect=self.advance),
            redirect_stdout(io.StringIO()) as stdout,
            redirect_stderr(io.StringIO()) as stderr,
        ):
            code = main([flag, "--config", str(self.config)])
        self.assertTrue(stdout.getvalue(), stderr.getvalue())
        report = json.loads(stdout.getvalue())
        directory = Path(report["run_dir"])
        self.assertTrue(directory.is_relative_to(self.runs))
        self.assertTrue(report["report_saved"], report["error"])
        self.assertEqual(json.loads((directory / "report.json").read_bytes()), report)
        self.assertEqual(self.config.read_bytes(), self.config_bytes)
        for field in ("stamina_spent", "stamina_pending", "immersifiers_spent", "immersifiers_pending",
                      "battle_completed"):
            self.assertEqual(report[field], 0, field)
        kernel32.CloseHandle.assert_called_once_with(1)
        return SimpleNamespace(code=code, report=report, journal=directory / JOURNAL,
                               packets=packets, captures=captures, at_send=at_send,
                               enumeration_count=user32.EnumWindows.call_count)

    def record(self, outcome):
        data = json.loads(outcome.journal.read_bytes())
        self.assertEqual(data, outcome.report["currency_wars"])
        self.assertFalse(data["match_started"])
        self.assertFalse(data["completion_verified"])
        return data

    def assert_a0(self, outcome):
        self.assertEqual((outcome.code, outcome.report["status"]), (0, "success"), outcome.report["error"])
        data = self.record(outcome)
        self.assertTrue(data["mode_verified"])
        self.assertTrue(data["difficulty_verified"])
        self.assertEqual(data["client_version"], "4.6.0")
        self.assertEqual((data["observation"]["rank"], data["observation"]["enemy_difficulty"]), ("A0", 1))
        first, second = data["feedback"]
        self.assertEqual([first["state"], second["state"]], ["a0_observed"] * 2)
        self.assertLess(first["captured_at"], second["captured_at"])
        self.assertNotEqual(first["sha256"], second["sha256"])
        for proof in (first, second):
            path = Path(proof["screenshot"])
            self.assertTrue(path.is_relative_to(outcome.journal.parent))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), proof["sha256"])
        return data

    def test_standard_selected_stops_without_any_native_input(self):
        result = self.native_cli(frame("standard", account=1))
        self.assertEqual((result.code, result.captures, result.packets), (1, 1, []))
        data = self.record(result)
        self.assertEqual(data["observation"]["state"], "standard_selected")
        self.assertEqual(data["actions"], [])
        self.assertFalse(data["mode_verified"])

    def test_selected_overclock_sends_only_one_right_entry_packet_and_checks_two_a0_frames(self):
        selected = frame("overclock", account=1)
        a0 = frame("a0", account=1)
        result = self.native_cli(selected, a0, a0)
        data = self.assert_a0(result)
        self.assertEqual(result.captures, 3)
        self.assertEqual(len(result.packets), 1)
        move, down, up = result.packets[0]
        self.assertEqual([move[:2], down, up], [(0, 0xC001), (0, 0x0002, 0, 0), (0, 0x0004, 0, 0)])
        entry = selected.find("进入超频博弈", exact=True)
        pixel_x = round(move[2] * (self.metrics[78] - 1) / 65535) + self.metrics[76]
        pixel_y = round(move[3] * (self.metrics[79] - 1) / 65535) + self.metrics[77]
        self.assertAlmostEqual((pixel_x - self.geometry.left) / (self.geometry.width - 1), entry.center[0],
                               delta=1 / self.geometry.width)
        self.assertAlmostEqual((pixel_y - self.geometry.top) / (self.geometry.height - 1), entry.center[1],
                               delta=1 / self.geometry.height)
        pending, = result.at_send
        self.assertFalse(pending["difficulty_verified"])
        self.assertEqual(pending["feedback"], [])
        intent, = pending["actions"]
        self.assertEqual((intent["action"], intent["status"], intent["target"]),
                         ("open_overclock_difficulty", "pending", list(entry.box)))
        self.assertEqual(data["actions"], [dict(intent, status="verified")])

    def test_already_at_a0_uses_two_frames_and_does_not_start_the_match(self):
        a0 = frame("a0", account=1)
        result = self.native_cli(a0, a0)
        self.assertEqual((result.captures, result.packets), (2, []))
        self.assertEqual(self.assert_a0(result)["actions"], [])

    def test_non_a0_feedback_is_unknown_and_retry_refuses_another_native_send(self):
        selected, a0 = frame("overclock", account=1), frame("a0", account=1)
        a1 = changed_token(a0, "AO黑铁", "A1青铜")
        result = self.native_cli(selected, a1)
        self.assertEqual((result.code, result.captures, len(result.packets)), (1, 2, 1))
        data = self.record(result)
        self.assertEqual(data["observation"]["state"], "rank_unsupported")
        self.assertEqual([item["status"] for item in data["actions"]], ["unknown"])
        self.assertFalse(data["difficulty_verified"])
        original = result.journal.read_bytes()

        retry = self.native_cli(selected)
        self.assertEqual((retry.code, retry.captures, retry.packets), (1, 1, []))
        self.assertEqual(self.record(retry)["actions"], [])
        self.assertEqual(result.journal.read_bytes(), original)

        already_there = self.native_cli(a0, a0)
        self.assertEqual(already_there.packets, [])
        self.assertEqual(self.assert_a0(already_there)["actions"], [])
        self.assertEqual(result.journal.read_bytes(), original)

    def test_conflicting_enemy_difficulty_is_terminal_even_with_later_a0_frames(self):
        selected, a0 = frame("overclock", account=1), frame("a0", account=1)
        conflict = changed_token(a0, "敌人难度+1", "敌人难度+2", before_y=.25)
        result = self.native_cli(selected, conflict, a0, a0)
        self.assertEqual((result.code, result.captures, len(result.packets)), (1, 2, 1))
        data = self.record(result)
        self.assertEqual(data["observation"]["state"], "effects_conflicting")
        self.assertEqual([item["status"] for item in data["actions"]], ["unknown"])
        self.assertFalse(data["difficulty_verified"])

    def test_recognized_boss_preview_cannot_be_reinterpreted_as_difficulty_feedback(self):
        selected, a0 = frame("overclock", account=1), frame("a0", account=1)
        pages = json.loads((FIXTURES / "currency_wars_pages.json").read_text(encoding="utf-8"))["pages"]
        boss = Scene([Token(**token) for token in pages["boss_preview"]["tokens"]] + a0.tokens[-1:])
        result = self.native_cli(selected, boss, a0, a0)
        self.assertEqual((result.code, result.captures, len(result.packets)), (1, 2, 1))
        data = self.record(result)
        self.assertEqual(data["observation"]["state"], "unexpected_page")
        self.assertEqual([item["status"] for item in data["actions"]], ["unknown"])

    def test_incomplete_feedback_breaks_the_pair_and_can_recover_without_resending(self):
        selected, a0 = frame("overclock", account=1), frame("a0", account=1)
        incomplete = changed_token(a0, "当前职级难度效果*效果叠加生效中", None)
        result = self.native_cli(selected, a0, incomplete, a0, a0)
        self.assertEqual((result.captures, len(result.packets)), (5, 1))
        self.assert_a0(result)

    def test_verified_old_mode_switch_keeps_original_evidence_and_allows_a0_open(self):
        standard, selected, a0 = (frame(kind, account=1) for kind in ("standard", "overclock", "a0"))
        previous = self.native_cli(standard, selected, selected, flag=SELECT_MODE)
        self.assertEqual((previous.code, len(previous.packets)), (0, 1), previous.report["error"])
        data = self.record(previous)
        intent, = data["actions"]
        self.assertEqual((intent["action"], intent["status"]), ("select_overclock", "verified"))
        files = [previous.journal, Path(intent["before"]["screenshot"]),
                 *(Path(proof["screenshot"]) for proof in data["feedback"])]
        before = {path: path.read_bytes() for path in files}

        result = self.native_cli(selected, a0, a0)
        self.assert_a0(result)
        self.assertEqual(len(result.packets), 1)
        self.assertEqual({path: path.read_bytes() for path in files}, before)

    def test_pending_old_mode_selection_vetoes_new_a0_open(self):
        standard = frame("standard", account=1)
        switched_account = frame("overclock", account=2)
        previous = self.native_cli(standard, switched_account, flag=SELECT_MODE)
        self.assertEqual((previous.code, len(previous.packets)), (1, 1))
        intent, = self.record(previous)["actions"]
        self.assertEqual((intent["action"], intent["status"]), ("select_overclock", "pending"))
        original = previous.journal.read_bytes()

        result = self.native_cli(frame("overclock", account=1))
        self.assertEqual((result.code, result.packets), (1, []))
        self.assertEqual(self.record(result)["reason"], "previous_selection_unresolved")
        self.assertEqual(previous.journal.read_bytes(), original)

    def test_unresolved_standard_session_stops_before_window_enumeration(self):
        path = self.runs / "currency-standard-session.json"
        StandardSession(path).begin(self.root / "old-run", {})
        original = path.read_bytes()

        result = self.native_cli()
        self.assertEqual((result.code, result.enumeration_count, result.packets), (1, 0, []))
        self.assertIn("未核实结束的标准对局", result.report["error"])
        self.assertFalse(result.journal.exists())
        self.assertEqual(path.read_bytes(), original)

    def test_feedback_is_held_when_temporary_receipt_is_read(self):
        selected, a0 = frame("overclock", account=1), frame("a0", account=1)
        original_open = Path.open
        denied = []

        def try_replace_after_proof_read(path, mode="r", *args, **kwargs):
            if path.name == "currency-overclock-config.tmp" and mode == "rb":
                first = next(path.parent.glob("*feedback_first.png"), None)
                if first is not None:
                    replacement = self.root / "old-page.png"
                    old_page = next(path.parent.glob("*before_open_difficulty.png"))
                    replacement.write_bytes(old_page.read_bytes())
                    with self.assertRaises(PermissionError):
                        replacement.replace(first)
                    denied.append(first)
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", try_replace_after_proof_read):
            result = self.native_cli(selected, a0, a0)
        self.assert_a0(result)
        first, = denied
        with first.open("r+b"):
            pass

    def test_version_source_is_held_until_native_send_returns(self):
        selected, a0 = frame("overclock", account=1), frame("a0", account=1)
        original = self.client_ini.read_bytes()
        replacement = self.client_ini.with_name("different-version.ini")
        replacement.write_bytes(original.replace(b"4.6.0", b"4.7.0"))
        denied = []

        def try_replacing_config():
            with self.assertRaises(PermissionError):
                replacement.replace(self.client_ini)
            denied.append(True)
            self.assertEqual(self.client_ini.read_bytes(), original)

        result = self.native_cli(selected, a0, a0, on_send=try_replacing_config)
        self.assert_a0(result)
        self.assertEqual((len(result.packets), denied), (1, [True]))
        replacement.replace(self.client_ini)
        self.assertIn(b"4.7.0", self.client_ini.read_bytes())

    def test_uncalibrated_installed_version_blocks_capture_and_click(self):
        self.set_version("4.7.0")
        result = self.native_cli(frame("overclock", account=1))
        self.assertEqual((result.code, result.captures, result.packets), (1, 0, []))
        self.assertIn("版本证据", result.report["error"])
        self.assertFalse(result.journal.exists())

    def test_installed_version_change_after_initial_check_blocks_native_send(self):
        def change_version(_):
            self.set_version("4.7.0")

        result = self.native_cli(frame("overclock", account=1), on_capture=change_version)
        self.assertEqual((result.code, result.captures, result.packets), (1, 1, []))
        self.assertIn("版本证据", result.report["error"])
        data = self.record(result)
        self.assertEqual([item["status"] for item in data["actions"]], ["pending"])
        self.assertFalse(data["difficulty_verified"])

    def test_cli_rejects_conflicting_modes_and_parameters_before_loading_settings(self):
        with patch.object(Settings, "load") as load:
            for options in ((SELECT_MODE,), ("--currency-wars-standard",), ("--challenge-result",), ("--plan",),
                            ("--currency-wealth", "40"), ("--game-path", "irrelevant.exe")):
                with self.subTest(options=options), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main([OPEN_A0, "--config", str(self.config), *options])
                self.assertEqual(error.exception.code, 2)
        load.assert_not_called()
