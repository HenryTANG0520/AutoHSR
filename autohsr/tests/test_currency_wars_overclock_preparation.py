"""Exercise the bounded A0 preparation CLI with a fake native game window."""

from contextlib import redirect_stderr
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import numpy as np

from autohsr import currency_wars_overclock as overclock, storage, windows
from autohsr.__main__ import main
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.models import Scene, Stopped, Token
from autohsr.tests import test_currency_wars_overclock_a0 as native
from autohsr.tests import test_currency_wars_overclock_start as opening
from autohsr.tests.test_currency_wars_overclock import FIXTURES, changed_token, frame


FLAG = "--currency-wars-prepare-overclock-a0"
MODE = "overclock_a0_preparation"
JOURNAL = "currency-overclock-preparation.json"
WINDOW_KEY = "a" * 64
OTHER_WINDOW_KEY = "b" * 64
ROUTE = (
    ("advance_a0_boss_preview", "下一步", "a0_first_plane"),
    ("advance_a0_first_plane", "点击空白处继续", "a0_environment"),
    ("select_a0_initial_insurance", "人身意外险", "a0_insurance_selected"),
    ("confirm_a0_initial_insurance", "确认", "a0_first_preparation"),
)
REPLACE = Path.replace


@lru_cache(maxsize=1)
def insurance_tokens():
    fixture = json.loads((FIXTURES / "currency_wars_insurance.json").read_text(encoding="utf-8"))
    return tuple(Token(row["text"], row["score"], tuple(row["box"])) for row in fixture["tokens"])


def with_account(tokens, *, image=None):
    return Scene([*tokens, Token("UID100000001", .99, (.02, .96, .13, .99))], image=image)


class OverclockPreparationNativeTests(unittest.TestCase):
    advance = opening.OverclockStartNativeTests.advance
    set_version = opening.OverclockStartNativeTests.set_version
    ledger = opening.OverclockStartNativeTests.ledger
    assert_session = opening.OverclockStartNativeTests.assert_session
    assert_packet_target = opening.OverclockStartNativeTests.assert_packet_target
    assert_preflight_veto = opening.OverclockStartNativeTests.assert_preflight_veto
    alternate = opening.OverclockStartNativeTests.alternate
    assert_ntfs_denies_replace = opening.OverclockStartNativeTests.assert_ntfs_denies_replace
    assert_released = opening.OverclockStartNativeTests.assert_released

    def setUp(self):
        opening.OverclockStartNativeTests.setUp(self)
        self.progress = self.runs / JOURNAL
        self.window_key = WINDOW_KEY

    def native_cli(self, *scenes, flag=FLAG, **kwargs):
        scripted = iter(scenes)
        journal = self.session if flag == opening.START else self.progress

        def fake_ocr_scene(*, tokens, image, geometry):
            pixels = next(scripted).image
            if pixels is not None:
                mask = np.any(pixels, axis=2)
                image[mask] = pixels[mask]
            return Scene(tokens=tokens, image=image, geometry=geometry)

        # Reuse the native fixture, painting only synthetic UI state in the fake OCR input.
        with (
            patch.object(native, "JOURNAL", Path("..") / journal.name),
            patch.object(native, "Scene", side_effect=fake_ocr_scene),
            patch.object(self, "runs", opening._RunDirectories(self.runs)),
            patch.object(windows.GameWindow, "current_window_key", lambda _window: self.window_key),
        ):
            return native.OverclockA0NativeTests.native_cli(self, *scenes, flag=flag, **kwargs)

    def open_match(self):
        outcome = self.native_cli(frame("a0", account=1), opening.boss(), opening.boss(), flag=opening.START)
        self.assert_session(outcome, started=True)
        return self.session.read_bytes()

    def paint(self, image, roi, color):
        width, height = self.geometry.width, self.geometry.height
        left, top, right, bottom = roi
        image[round(top * height):round(bottom * height), round(left * width):round(right * width)] = color

    def pixels(self):
        return np.zeros((self.geometry.height, self.geometry.width, 3), dtype=np.uint8)

    def plane(self, *highlighted):
        image = self.pixels()
        centers = (.23, .50, .77)
        for index in highlighted:
            center = centers[index - 1]
            self.paint(image, (center - .025, .39, center + .025, .47), (0, 230, 230))
        return with_account(opening.page_tokens("plane_map"), image=image)

    def environment(self, *, selected=None, confirm_enabled=None):
        image = self.pixels()
        if selected is not None:
            center = (.229, .50, .771)[selected]
            self.paint(image, (center - .123, .20, center - .121, .79), (255, 255, 255))
        if confirm_enabled is None:
            confirm_enabled = selected is not None
        shade = 255 if confirm_enabled else 32
        self.paint(image, (.50, .895, .62, .925), (shade, shade, shade))
        return with_account(insurance_tokens(), image=image)

    def route_pages(self):
        return (opening.boss(), self.plane(1), self.environment(),
                self.environment(selected=0), with_account(opening.page_tokens("preparation")))

    def progress_data(self):
        return json.loads(self.progress.read_bytes())

    def check_step(self, index, source, feedback, *, transition=()):
        action, label, state = ROUTE[index]
        previous = self.progress_data()["steps"] if self.progress.exists() else []
        root = self.session.read_bytes()
        result = self.native_cli(source, *transition, feedback, feedback)
        self.assertEqual((result.code, result.report["status"], result.captures), (0, "success", 3 + len(transition)),
                         result.report["error"])
        batch, = result.packets
        self.assert_packet_target(batch, source, label)
        at_send, = result.at_send
        self.assertEqual(at_send["status"], "pending")
        self.assertEqual(at_send["steps"][:-1], previous)
        intent = at_send["steps"][-1]
        self.assertEqual((intent["action"], intent["status"], intent["feedback"]), (action, "pending", []))
        record = self.progress_data()
        self.assertEqual((record["mode"], record["status"]), (MODE, "verified"))
        self.assertEqual(record["match_id"], json.loads(root)["match_id"])
        self.assertEqual(record["start_sha256"], hashlib.sha256(root).hexdigest())
        self.assertEqual(record["steps"][:-1], previous)
        verified = record["steps"][-1]
        self.assertEqual((verified["action"], verified["status"], verified["observation"]["state"]),
                         (action, "verified", state))
        self.assertEqual(verified["target"], list(source.find(label, exact=True).box))
        self.assertEqual(verified["target"], intent["target"])
        self.assertEqual(verified["before"], intent["before"])
        first, second = verified["feedback"]
        self.assertLess(verified["before"]["captured_at"], first["captured_at"])
        self.assertLess(first["captured_at"], second["captured_at"])
        self.assertNotEqual(first["screenshot"], second["screenshot"])
        for evidence in (verified["before"], first, second):
            path = Path(evidence["screenshot"]).resolve(strict=True)
            self.assertTrue(path.is_relative_to(Path(result.report["run_dir"]).resolve()))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), evidence["sha256"])
        report = result.report["currency_wars"]
        self.assertEqual((report["mode"], report["status"]), (MODE, "verified"))
        self.assertEqual([(entry["action"], entry["status"]) for entry in report["actions"]],
                         [(action, "verified")])
        self.assertIs(report["match_started"], True)
        self.assertIs(report["first_preparation_verified"], index == len(ROUTE) - 1)
        self.assertIs(report["completion_verified"], False)
        self.assertEqual(self.session.read_bytes(), root)
        return result

    def follow_route(self, count):
        pages = self.route_pages()
        for index in range(count):
            self.check_step(index, pages[index], pages[index + 1])
        return pages

    def assert_no_step(self, source):
        old = self.progress.read_bytes() if self.progress.exists() else None
        root = self.session.read_bytes()
        result = self.native_cli(*([source] * 50))
        self.assertEqual((result.code, result.packets), (1, []), result.report["error"])
        self.assertEqual(self.progress.read_bytes() if self.progress.exists() else None, old)
        self.assertEqual(self.session.read_bytes(), root)

    def test_four_cli_invocations_each_send_one_step_and_terminal_is_read_only(self):
        root = self.open_match()
        pages = self.route_pages()
        preparation = pages[-1]
        incomplete = changed_token(pages[2], "夜之半神概念股", None)
        for index in range(len(ROUTE)):
            transition = (incomplete,) if index == 1 else ()
            self.check_step(index, pages[index], pages[index + 1], transition=transition)
        _, entered_environment, selected_insurance, _ = self.progress_data()["steps"]
        unselected = entered_environment["observation"]
        self.assertEqual(unselected["key"][-1], "none")
        self.assertEqual(selected_insurance["before_observation"], unselected)
        terminal = self.progress.read_bytes()
        repeated = self.native_cli(preparation, preparation)
        self.assertEqual((repeated.code, repeated.captures, repeated.packets), (0, 2, []),
                         repeated.report["error"])
        report = repeated.report["currency_wars"]
        self.assertEqual((report["mode"], report["status"], report["actions"]), (MODE, "verified", []))
        self.assertIs(report["first_preparation_verified"], True)
        self.assertIs(report["completion_verified"], False)
        self.assertEqual(self.progress.read_bytes(), terminal)
        self.assertEqual(self.session.read_bytes(), root)

    def test_stop_between_first_and_second_feedback_preserves_pending_and_vetoes_either_page(self):
        root = self.open_match()
        source, first_plane = self.route_pages()[:2]
        sent, captured_after_send = [], []

        def after_send():
            sent.append(self.progress.read_bytes())

        def stop_on_second_feedback(number):
            if sent:
                captured_after_send.append(number)
                if len(captured_after_send) == 2:
                    raise Stopped("synthetic stop before second A0 feedback")

        result = self.native_cli(source, first_plane, first_plane,
                                 on_send=after_send, on_capture=stop_on_second_feedback)
        self.assertEqual((result.code, result.report["status"]), (1, "stopped"), result.report["error"])
        batch, = result.packets
        self.assert_packet_target(batch, source, "下一步")
        pending, = sent
        self.assertEqual(self.progress.read_bytes(), pending)
        self.assertEqual(self.progress_data()["steps"][-1]["status"], "pending")
        for page in (source, first_plane):
            self.assert_preflight_veto(self.native_cli(page))
            self.assertEqual(self.progress.read_bytes(), pending)
        legacy = opening.OverclockStartNativeTests.legacy_runner(
            self, False, source, flag=opening.START)
        self.assert_preflight_veto(legacy)
        self.assertEqual(self.progress.read_bytes(), pending)
        self.assertEqual(self.session.read_bytes(), root)

    def test_known_wrong_plane_feedback_cannot_verify_or_send_again(self):
        root = self.open_match()
        source = opening.boss()
        wrong = self.plane(2)
        result = self.native_cli(source, *([wrong] * 100))
        self.assertEqual((result.code, result.report["status"]), (1, "partial"), result.report["error"])
        batch, = result.packets
        self.assert_packet_target(batch, source, "下一步")
        self.assertEqual(self.progress_data()["steps"][-1]["status"], "unknown")
        unresolved = self.progress.read_bytes()
        self.assert_preflight_veto(self.native_cli(self.plane(1)))
        self.assertEqual(self.progress.read_bytes(), unresolved)
        self.assertEqual(self.session.read_bytes(), root)

    def test_changed_account_window_or_wrong_page_at_source_do_not_send(self):
        self.open_match()
        for label, source, key in (
            ("other account", opening.boss(account=2), WINDOW_KEY),
            ("other window lifetime", opening.boss(), OTHER_WINDOW_KEY),
            ("skipped preview", self.plane(1), WINDOW_KEY),
        ):
            with self.subTest(case=label):
                self.window_key = key
                self.assert_no_step(source)
        self.assertFalse(self.progress.exists())

    def test_window_lifetime_changes_between_feedback_frames(self):
        root = self.open_match()
        source, first_plane = self.route_pages()[:2]

        def change_window_key(number):
            if number == 3:
                self.window_key = OTHER_WINDOW_KEY

        result = self.native_cli(source, first_plane, first_plane, on_capture=change_window_key)
        self.assertEqual(result.code, 1)
        batch, = result.packets
        self.assert_packet_target(batch, source, "下一步")
        self.assertIn(self.progress_data()["steps"][-1]["status"], ("pending", "unknown"))
        unresolved = self.progress.read_bytes()
        self.window_key = WINDOW_KEY
        self.assert_preflight_veto(self.native_cli(first_plane))
        self.assertEqual(self.progress.read_bytes(), unresolved)
        self.assertEqual(self.session.read_bytes(), root)

    def test_verified_stage_does_not_authorize_wrong_plane_or_unrecorded_preselection(self):
        self.open_match()
        _, first_plane, environment, chosen, _ = self.follow_route(1)
        for source in (opening.boss(), self.plane(2), self.plane(1, 2)):
            self.assert_no_step(source)
        self.check_step(1, first_plane, environment)
        self.assert_no_step(chosen)
        self.assert_no_step(self.environment(confirm_enabled=True))

    def test_verified_environment_with_another_card_selected_can_switch_to_insurance(self):
        self.open_match()
        _, first_plane, _, insurance, _ = self.follow_route(1)
        other_card = self.environment(selected=1)
        self.check_step(1, first_plane, other_card)
        self.check_step(2, other_card, insurance)
        prior, selection = self.progress_data()["steps"][-2:]
        self.assertEqual(prior["observation"]["key"][-1], "1")
        self.assertEqual(selection["before_observation"], prior["observation"])
        self.assertEqual(selection["observation"]["key"][-1], "0")

    def test_reward_shop_and_changed_insurance_never_authorize_confirmation(self):
        self.open_match()
        *_, chosen, _ = self.follow_route(3)
        altered = changed_token(chosen, "所有首领节点前都加入一个额外补给阶", "所有首领节点前都加入一个额外战斗阶")
        for label, scene in (
            ("shop", with_account(opening.page_tokens("shop"))),
            ("reward", with_account(opening.page_tokens("equipment_selection"))),
            ("insurance effect changed", altered),
        ):
            with self.subTest(page=label):
                self.assert_no_step(scene)

    def test_shop_feedback_at_node_one_one_never_verifies_preparation(self):
        root = self.open_match()
        *_, chosen, preparation = self.follow_route(3)
        shop = with_account(opening.page_tokens("shop"))
        result = self.native_cli(chosen, *([shop] * 100))
        self.assertEqual((result.code, result.report["status"]), (1, "partial"), result.report["error"])
        batch, = result.packets
        self.assert_packet_target(batch, chosen, "确认")
        self.assertEqual(self.progress_data()["steps"][-1]["status"], "unknown")
        self.assertIs(result.report["currency_wars"]["first_preparation_verified"], False)
        unresolved = self.progress.read_bytes()
        self.assert_preflight_veto(self.native_cli(preparation))
        self.assertEqual(self.progress.read_bytes(), unresolved)
        self.assertEqual(self.session.read_bytes(), root)

    def test_changed_verified_feedback_vetoes_the_following_stage_before_enumeration(self):
        root = self.open_match()
        _, first_plane, _, _, _ = self.follow_route(1)
        original = self.progress.read_bytes()
        first, second = (Path(row["screenshot"]) for row in self.progress_data()["steps"][0]["feedback"])
        self.assertTrue(first.resolve(strict=True).is_relative_to(self.root))
        changed = second.read_bytes()
        self.assertNotEqual(first.read_bytes(), changed)
        REPLACE(self.alternate("corrupted-old-feedback.png", changed), first)

        self.assert_preflight_veto(self.native_cli(first_plane))
        self.assertEqual(self.progress.read_bytes(), original)
        self.assertEqual(first.read_bytes(), changed)
        self.assertEqual(self.session.read_bytes(), root)

    def test_cross_run_source_capture_older_than_verified_feedback_cannot_send(self):
        root = self.open_match()
        _, first_plane, _, _, _ = self.follow_route(1)
        old = self.progress.read_bytes()
        last_feedback = self.progress_data()["steps"][-1]["feedback"][-1]["captured_at"]
        self.clock = last_feedback - .5

        result = self.native_cli(first_plane)
        self.assertEqual((result.code, result.captures, result.packets), (1, 1, []))
        self.assertEqual(result.report["currency_wars"]["reason"], "source_not_new")
        self.assertFalse(self.progress.with_suffix(".tmp").exists())
        self.assertEqual(self.progress.read_bytes(), old)
        self.assertEqual(self.session.read_bytes(), root)

    def test_window_key_includes_process_creation_time_and_rejects_missing_identity(self):
        with patch.object(windows, "process_path", return_value=str(self.executable)):
            game = windows.GameWindow(self.hwnd)
        pid, thread, handle = 53, 29, 137
        created = 0x1234567812345678

        def window_process(hwnd, pid_pointer):
            self.assertEqual(hwnd, self.hwnd)
            pid_pointer._obj.value = pid
            return thread

        def process_times(opened, creation, _exit, _kernel, _user):
            self.assertEqual(opened, handle)
            creation._obj.dwLowDateTime = created & 0xFFFFFFFF
            creation._obj.dwHighDateTime = created >> 32
            return 1

        user32 = SimpleNamespace(GetWindowThreadProcessId=Mock(side_effect=window_process))
        kernel32 = SimpleNamespace(OpenProcess=Mock(return_value=handle),
                                   GetProcessTimes=Mock(side_effect=process_times), CloseHandle=Mock())
        with (
            patch.object(game, "guard", return_value=self.geometry),
            patch.object(windows, "user32", user32),
            patch.object(windows, "kernel32", kernel32),
        ):
            key = game.current_window_key()
            self.assertRegex(key, r"^[0-9a-f]{64}$")
            self.assertEqual(game.current_window_key(), key)
            created += 1 << 32
            recycled = game.current_window_key()
            self.assertRegex(recycled, r"^[0-9a-f]{64}$")
            self.assertNotEqual(recycled, key)
            kernel32.GetProcessTimes.side_effect = None
            kernel32.GetProcessTimes.return_value = 0
            self.assertIsNone(game.current_window_key())
            user32.GetWindowThreadProcessId.side_effect = None
            user32.GetWindowThreadProcessId.return_value = 0
            self.assertIsNone(game.current_window_key())

        self.assertEqual(kernel32.OpenProcess.call_args_list, [call(0x1000, False, pid)] * 4)
        self.assertEqual(kernel32.CloseHandle.call_args_list, [call(handle)] * 4)

    def test_old_verified_preview_advance_blocks_before_enumeration(self):
        root = self.open_match()
        record = json.loads(opening.OverclockStartNativeTests.legacy_record(
            self, dict(action="advance_boss_preview", status="verified")))
        record["overclock_session_id"] = json.loads(root)["match_id"]
        old = json.dumps(record, ensure_ascii=False).encode()
        journal = opening.OverclockStartNativeTests.write_legacy(self, old)
        self.assert_preflight_veto(self.native_cli(opening.boss()))
        self.assertEqual(journal.read_bytes(), old)
        self.assertEqual(self.session.read_bytes(), root)
        self.assertFalse(self.progress.exists())

    def test_window_bound_legacy_whole_match_continues_to_plane_in_the_same_run(self):
        a0, preview, first_plane = frame("a0", account=1), opening.boss(), self.plane(1)
        result = opening.OverclockStartNativeTests.legacy_runner(
            self, True, a0, a0, preview, preview, preview, first_plane, a0, flag=opening.START)
        self.assertEqual((result.code, result.report["status"], result.captures), (1, "partial", 7),
                         result.report["error"])
        start, advance = result.packets
        self.assert_packet_target(start, a0, "开始对局")
        self.assert_packet_target(advance, preview, "下一步")
        self.assertEqual(self.ledger()["window_key"], WINDOW_KEY)
        self.assertEqual([(step["action"], step["status"]) for step in result.report["currency_wars"]["actions"]],
                         [("start_overclock_a0", "verified"), ("advance_boss_preview", "verified")])
        self.assertFalse(self.progress.exists())

    def test_window_bound_independent_opening_allows_one_legacy_preview_without_preparation(self):
        root = self.open_match()
        preview, first_plane, a0 = opening.boss(), self.plane(1), frame("a0", account=1)
        seen = []

        def record_pending():
            journal, = self.runs.root.glob("*/currency-flow.json")
            seen.append(json.loads(journal.read_bytes())["actions"][-1])

        result = opening.OverclockStartNativeTests.legacy_runner(
            self, False, preview, first_plane, a0, flag=opening.START, on_send=record_pending)
        self.assertEqual((result.code, result.report["status"], result.captures), (1, "partial", 3),
                         result.report["error"])
        batch, = result.packets
        self.assert_packet_target(batch, preview, "下一步")
        intent, = seen
        self.assertEqual((intent["action"], intent["status"]), ("advance_boss_preview", "pending"))
        self.assertEqual(hashlib.sha256(Path(intent["before"]).read_bytes()).hexdigest(), intent["before_sha256"])
        self.assertEqual(result.report["currency_wars"]["actions"][0]["status"], "verified")
        self.assertEqual(self.session.read_bytes(), root)
        self.assertFalse(self.progress.exists())
        self.assert_preflight_veto(opening.OverclockStartNativeTests.legacy_runner(
            self, False, preview, flag=opening.START))
        self.assert_preflight_veto(self.native_cli(preview))

    def test_legacy_preview_rechecks_window_at_native_send(self):
        root = self.open_match()
        click = windows.GameWindow.click

        def switch_window(window, x, y, geometry, *, before_send=None):
            self.assertIsNotNone(before_send)
            self.window_key = OTHER_WINDOW_KEY
            return click(window, x, y, geometry, before_send=before_send)

        with patch.object(windows.GameWindow, "click", switch_window):
            result = opening.OverclockStartNativeTests.legacy_runner(
                self, False, opening.boss(), flag=opening.START)
        self.assertEqual((result.code, result.captures, result.packets), (1, 1, []))
        self.assertIn("当前游戏窗口", result.report["error"])
        self.assertEqual(result.report["currency_wars"]["actions"][0]["status"], "pending")
        self.assertEqual(self.session.read_bytes(), root)

    def test_legacy_preview_rechecks_preparation_intent_at_native_send(self):
        root = self.open_match()
        temporary = self.progress.with_suffix(".tmp")
        click = windows.GameWindow.click

        def add_intent(window, x, y, geometry, *, before_send=None):
            self.assertIsNotNone(before_send)
            temporary.write_bytes(b"pending preparation")
            return click(window, x, y, geometry, before_send=before_send)

        with patch.object(windows.GameWindow, "click", add_intent):
            result = opening.OverclockStartNativeTests.legacy_runner(
                self, False, opening.boss(), flag=opening.START)
        self.assertEqual((result.code, result.captures, result.packets), (1, 1, []))
        self.assertIn("已有首个备战", result.report["error"])
        self.assertEqual(result.report["currency_wars"]["actions"][0]["status"], "pending")
        self.assertEqual(temporary.read_bytes(), b"pending preparation")
        self.assertEqual(self.session.read_bytes(), root)

    def _check_after_history_notification(self, *, legacy, interrupt):
        root = self.open_match()
        preview, plane = self.route_pages()[:2]
        directory_notification = overclock._hold_history_names
        captured = []
        triggered = []
        snapshot = Context.snapshot

        def remember(context):
            scene = snapshot(context)
            captured.append(scene)
            return scene

        def notification(directory, sources):
            check = directory_notification(directory, sources)

            def notify():
                check()
                if not triggered and (legacy or self.progress.exists()):
                    interrupt(captured[-1])
                    triggered.append(True)

            return notify

        def restore_window_after_wrong_send():
            windows.user32.GetForegroundWindow.side_effect = None
            windows.user32.GetAsyncKeyState.side_effect = None

        with (patch.object(Context, "snapshot", remember),
              patch.object(overclock, "_hold_history_names", notification)):
            if legacy:
                result = opening.OverclockStartNativeTests.legacy_runner(
                    self, False, preview, plane, frame("a0", account=1), flag=opening.START,
                    on_send=restore_window_after_wrong_send)
            else:
                result = self.native_cli(preview, plane, plane, on_send=restore_window_after_wrong_send)

        self.assertEqual(triggered, [True])
        self.assertEqual((result.code, result.packets), (1, []), result.report["error"])
        journal = Path(result.report["run_dir"]) / "currency-flow.json" if legacy else self.progress
        pending = journal.read_bytes()
        data = json.loads(pending)
        intent, = data["actions"] if legacy else data["steps"]
        self.assertEqual(intent["status"], "pending")
        self.assertEqual(self.session.read_bytes(), root)
        self.assert_preflight_veto(self.native_cli(preview))
        self.assertEqual(journal.read_bytes(), pending)

    def _lose_focus(self, _scene):
        windows.user32.GetForegroundWindow.side_effect = [0] + [self.hwnd] * 30

    @staticmethod
    def _press_stop_key(_scene):
        windows.user32.GetAsyncKeyState.side_effect = [1] + [0] * 30

    def test_legacy_preview_rechecks_focus_after_history_notification(self):
        self._check_after_history_notification(legacy=True, interrupt=self._lose_focus)

    def test_legacy_preview_rechecks_f10_after_history_notification(self):
        self._check_after_history_notification(legacy=True, interrupt=self._press_stop_key)

    def test_preparation_rechecks_focus_after_history_notification(self):
        self._check_after_history_notification(legacy=False, interrupt=self._lose_focus)

    def test_preparation_rechecks_f10_after_history_notification(self):
        self._check_after_history_notification(legacy=False, interrupt=self._press_stop_key)

    def test_legacy_preview_rechecks_tokens_after_history_notification(self):
        self._check_after_history_notification(legacy=True, interrupt=lambda scene: scene.tokens.clear())

    def test_legacy_preview_rechecks_image_source_after_history_notification(self):
        def replace_image(scene):
            replacement = scene.image.copy()
            replacement[0, 0] = (175, 110, 45)
            scene.image = replacement

        self._check_after_history_notification(legacy=True, interrupt=replace_image)

    def test_legacy_preview_png_must_match_current_capture_before_native_send(self):
        root = self.open_match()
        preview, plane = self.route_pages()[:2]
        evidence = Context.evidence

        def change_capture_after_saving(context, scene, name, **kwargs):
            saved = evidence(context, scene, name, **kwargs)
            if name == "currency_entry_advance_boss_preview":
                scene.image[0, 0] = (175, 110, 45)
            return saved

        with patch.object(Context, "evidence", change_capture_after_saving):
            result = opening.OverclockStartNativeTests.legacy_runner(
                self, False, preview, plane, frame("a0", account=1), flag=opening.START)
        self.assertEqual((result.code, result.captures, result.packets), (1, 1, []))
        self.assertIn("落盘 PNG 与原画面像素不同", result.report["error"])
        self.assertEqual(result.report["currency_wars"]["actions"][0]["status"], "pending")
        self.assertEqual(self.session.read_bytes(), root)

    def test_opening_root_without_window_identity_is_not_migrated(self):
        record = json.loads(self.open_match())
        del record["window_key"]
        old = json.dumps(record, ensure_ascii=False).encode()
        self.session.write_bytes(old)
        self.assert_preflight_veto(self.native_cli(opening.boss()))
        self.assertEqual(self.session.read_bytes(), old)
        self.assertFalse(self.progress.exists())

    def test_cli_accepts_only_explicit_config_option(self):
        with patch.object(Settings, "load") as load:
            for extra in ((opening.START,), ("--currency-wars-standard",), ("--resume-active-currency",),
                          ("--game-path", "unused.exe"), ("--currency-wealth", "40")):
                with (
                    self.subTest(extra=extra),
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as rejected,
                ):
                    main([FLAG, "--config", str(self.config), *extra])
                self.assertEqual(rejected.exception.code, 2)
        load.assert_not_called()

    def test_native_send_holds_current_version_and_opening_root(self):
        root = self.open_match()
        version = self.client_ini.read_bytes()
        version_edit = self.alternate("different-client.ini", version.replace(b"4.6.0", b"4.7.0"))
        root_edit = self.alternate("different-root.json", root + b" ")
        denied = []

        def try_replace_at_send():
            self.assertEqual(self.progress_data()["steps"][-1]["status"], "pending")
            denied.extend((self.assert_ntfs_denies_replace(version_edit, self.client_ini),
                           self.assert_ntfs_denies_replace(root_edit, self.session)))

        source, first_plane = self.route_pages()[:2]
        result = self.native_cli(source, first_plane, first_plane, on_send=try_replace_at_send)
        self.assertEqual(result.code, 0, result.report["error"])
        self.assertEqual(denied, [version, root])
        self.assertEqual(self.progress_data()["steps"][-1]["status"], "verified")
        self.assert_released(version_edit, self.client_ini, version)
        self.assert_released(root_edit, self.session, root)

    def test_verified_receipt_holds_feedback_png_at_real_ntfs_replace(self):
        root = self.open_match()
        denied = []

        def replace_receipt(source, destination):
            if Path(destination) == self.progress:
                proposed = json.loads(source.read_bytes())["steps"][-1]
                if proposed["status"] == "verified":
                    first, second = (Path(item["screenshot"]) for item in proposed["feedback"])
                    edited = self.alternate("other-plane.png", second.read_bytes())
                    original = self.assert_ntfs_denies_replace(edited, first)
                    denied.append((edited, first, original))
                    self.assertEqual(self.progress_data()["steps"][-1]["status"], "pending")
            return REPLACE(source, destination)

        source, first_plane = self.route_pages()[:2]
        with patch.object(Path, "replace", replace_receipt):
            result = self.native_cli(source, first_plane, first_plane)
        self.assertEqual(result.code, 0, result.report["error"])
        (edited, first, original), = denied
        self.assert_released(edited, first, original)
        self.assertEqual(self.session.read_bytes(), root)

    def test_receipt_rechecks_tampered_feedback_after_real_ntfs_sharing_conflict(self):
        root = self.open_match()
        attempted, changed = [], []

        def block_receipt(source, destination):
            if Path(destination) != self.progress:
                return REPLACE(source, destination)
            proposed = json.loads(source.read_bytes())["steps"][-1]
            if proposed["status"] != "verified":
                return REPLACE(source, destination)
            self.assertFalse(attempted, "changed feedback must prevent a second replace")
            pending = self.progress.read_bytes()
            self.assertEqual(self.progress_data()["steps"][-1]["status"], "pending")
            first, second = (Path(item["screenshot"]) for item in proposed["feedback"])
            with storage.hold_read_sources((self.progress,)):
                try:
                    return REPLACE(source, destination)
                except OSError as error:
                    self.assertIn(error.winerror, opening.SHARING_ERRORS)
                    self.assertEqual(self.progress.read_bytes(), pending)
                    attempted.append((pending, first, second))
                    raise

        def mutate_before_retry(delay):
            self.assertEqual(delay, storage.REPLACE_RETRY_DELAYS[0])
            self.assertFalse(changed)
            pending, first, second = attempted[0]
            self.assertTrue(first.resolve(strict=True).is_relative_to(self.root))
            original, alternate = first.read_bytes(), second.read_bytes()
            self.assertNotEqual(original, alternate)
            REPLACE(self.alternate("retry-plane.png", alternate), first)
            changed.append(first)
            self.assertEqual(self.progress.read_bytes(), pending)
            self.advance(delay)

        source, first_plane = self.route_pages()[:2]
        with (
            patch.object(Path, "replace", block_receipt),
            patch.object(storage, "time", SimpleNamespace(sleep=mutate_before_retry)),
        ):
            result = self.native_cli(source, first_plane, first_plane)
        self.assertEqual(result.code, 1)
        batch, = result.packets
        self.assert_packet_target(batch, source, "下一步")
        (pending, first, _), = attempted
        self.assertEqual(changed, [first])
        self.assertEqual(self.progress.read_bytes(), pending)
        self.assert_preflight_veto(self.native_cli(first_plane))
        self.assertEqual(self.progress.read_bytes(), pending)
        self.assertEqual(self.session.read_bytes(), root)
