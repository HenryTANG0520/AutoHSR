"""Overclock setup against redacted OCR and a fake native window."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
from functools import lru_cache
import io
import json
import mmap
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import ANY, Mock, patch

import cv2
import numpy as np

from autohsr import currency_wars_overclock, windows
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars import CurrencyWarsWorkflow
from autohsr.currency_wars_overclock import OPERATION, _Configuration, configure_overclock, read_overclock
from autohsr.currency_wars_session import StandardSession
from autohsr.models import AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, Token
from autohsr.windows import Geometry


FIXTURES = Path(__file__).parent / "fixtures"
FLAG = "--currency-wars-configure-overclock"
FIXTURE_LAYOUTS = {
    "standard": ("currency_wars_navigation.json", "standard_selected"),
    "overclock": ("currency_wars_overclock_selected.json", None),
    "a0": ("currency_wars_pages.json", "difficulty_select"),
}


@lru_cache(maxsize=len(FIXTURE_LAYOUTS))
def redacted_tokens(kind):
    name, page = FIXTURE_LAYOUTS[kind]
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    rows = data if page is None else data["pages"][page]
    return tuple(Token(row["text"], row["score"], tuple(row["box"])) for row in rows["tokens"])


def frame(kind, *, account=None):
    tokens = list(redacted_tokens(kind))
    if account is not None:
        tokens.append(Token(f"UID{100000000 + account}", .99, (.02, .96, .13, .99)))
    return Scene(tokens)


def changed_token(scene, label, new_text, *, score=None, before_y=None):
    tokens = []
    for token in scene.tokens:
        if token.text != label or (before_y is not None and token.center[1] >= before_y):
            tokens.append(token)
        elif new_text is not None:
            tokens.append(replace(token, text=new_text, score=token.score if score is None else score))
    return replace(scene, tokens=tokens)


def overclock_row(scene):
    return next(t for t in scene.tokens if t.text == "超频博弈" and t.center[0] < .2)


class OverclockObservationTests(unittest.TestCase):
    def test_three_public_samples_distinguish_mode_selection_and_a0_difficulty(self):
        for kind, expected in (
            ("standard", ("standard_selected", "standard", None, None)),
            ("overclock", ("overclock_selected", "overclock", None, None)),
            ("a0", ("a0_observed", "overclock", "A0", 1)),
        ):
            with self.subTest(kind=kind):
                observation = read_overclock(frame(kind))
                self.assertEqual(
                    (observation.state, observation.mode, observation.rank, observation.enemy_difficulty), expected
                )

    def test_decorative_quotes_preserve_the_corresponding_mode_button(self):
        for kind, label, expected in (
            ("standard", "进入标准博弈", "standard_selected"),
            ("overclock", "进入超频博弈", "overclock_selected"),
        ):
            with self.subTest(kind=kind):
                wrapped = changed_token(frame(kind), label, f"「{label}」")
                self.assertEqual(read_overclock(wrapped).state, expected)

    def test_sidebar_button_or_conflicting_detail_alone_cannot_confirm_mode(self):
        standard, selected = frame("standard"), frame("overclock")
        for scene in (
            changed_token(selected, "进入超频博弈", "进入标准博弈"),
            changed_token(selected, "*无法通过该玩法模式提升职级", None),
            changed_token(selected, "进入超频博弈", "进入超频博弈", score=.4),
            replace(standard, tokens=[*standard.tokens, overclock_row(standard)]),
        ):
            with self.subTest(tokens=scene.text):
                observation = read_overclock(scene)
                self.assertEqual(observation.state, "mode_unverified")
                self.assertIsNone(observation.mode)

    def test_a0_effect_rank_and_page_anchors_are_independent(self):
        a0 = frame("a0")
        for scene, expected in (
            (changed_token(a0, "AO黑铁", "A1青铜"), "rank_unsupported"),
            (changed_token(a0, "AO黑铁", "AO黑铁", score=.2), "rank_unverified"),
            (changed_token(a0, "开始对局", None), "difficulty_unverified"),
            (changed_token(a0, "敌人难度+1", "敌人难度+2", before_y=.25), "effects_unverified"),
            (changed_token(a0, "开局时获得【精密拆装扳手】", None), "effects_unverified"),
        ):
            with self.subTest(expected=expected):
                observation = read_overclock(scene)
                self.assertEqual(observation.state, expected)
                self.assertIsNone(observation.enemy_difficulty)
        self.assertEqual(read_overclock(Scene([])).state, "other_page")

    def test_auth_and_active_match_overlays_veto_background_controls(self):
        for kind, label in (("standard", "验证码"), ("overclock", "当前有未结算的对局"), ("a0", "放弃并结算")):
            with self.subTest(kind=kind):
                scene = frame(kind)
                scene.tokens.append(Token(label, .99, (.43, .45, .57, .49)))
                self.assertEqual(read_overclock(scene).state, "blocked")


class OverclockWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="currency-overclock-test-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.run_number = 0
        self.clock = 100.0
        self.geometry = Geometry(10, 20, 1920, 1080)
        clock_patch = patch("time.monotonic", side_effect=lambda: self.clock)
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    def advance(self, seconds):
        self.clock += seconds

    def context(self, *frames, operation=OPERATION, fallback=None, runs=None):
        self.run_number += 1
        root = self.directory / f"root-{self.run_number}" / "runs" if runs is None else runs
        folder = root / f"run-{self.run_number}"
        folder.mkdir(parents=True)
        runner = Runner(Settings(), operation=operation)
        runner.report.run_dir = str(folder)
        context = Context(runner, Mock(), Mock())
        context.checkpoint = Mock()
        context.sleep = Mock(side_effect=self.advance)
        pending = iter(frames)
        last_capture = None

        def capture():
            nonlocal last_capture
            self.advance(.01)
            item = next(pending, fallback)
            context.last_scene = None
            if isinstance(item, EmptyCapture):
                raise item
            self.assertIsNotNone(item, "workflow requested more captures than the test supplied")
            if isinstance(item, tuple):
                scene, delta = item
                captured_at = last_capture + delta
            else:
                scene, captured_at = item, self.clock
            last_capture = captured_at
            context.scene_epoch = runner.input_epoch
            geometry = scene.geometry or self.geometry
            image = np.full((geometry.height, geometry.width, 3), context.snapshot.call_count, np.uint8)
            context.last_scene = replace(scene, captured_at=captured_at, geometry=geometry, image=image)
            return context.last_scene

        def evidence(scene, label):
            path = folder / f"{context.snapshot.call_count:02d}_{label}.png"
            success, content = cv2.imencode(".png", scene.image)
            self.assertTrue(success)
            path.write_bytes(content.tobytes())
            return path

        def click(*args, before_send=None):
            if before_send is not None:
                before_send()

        context.snapshot = Mock(side_effect=capture)
        context.window.click.side_effect = click
        context.window.emergency_pressed.return_value = False
        context.evidence = evidence
        return context

    def journal(self, context):
        return Path(context.report.run_dir) / "currency-overclock-config.json"

    def saved(self, context):
        record = json.loads(self.journal(context).read_text(encoding="utf-8"))
        self.assertEqual(record, context.report.currency_wars)
        self.assertEqual(record["mode"], "overclock_configuration")
        self.assertFalse(record["match_started"])
        self.assertFalse(record["completion_verified"])
        return record

    def native_window(self, context):
        game = windows.GameWindow.__new__(windows.GameWindow)
        game.hwnd, game.path = 71, ""
        context.window = game
        context.runner.wait_for_focus = Mock()
        user32 = Mock()
        user32.IsWindow.return_value = 1
        user32.IsIconic.return_value = 0
        user32.GetForegroundWindow.return_value = 71
        user32.GetAsyncKeyState.return_value = 0
        user32.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 2560, 79: 1440}.__getitem__
        user32.SendInput.side_effect = lambda count, *_: count
        return user32

    def test_selects_only_left_row_after_pending_and_requires_two_feedback_captures(self):
        initial = frame("standard", account=1)
        selected = frame("overclock", account=1)
        context = self.context(initial, selected, selected)

        def at_send(*_, before_send):
            before_send()
            record = self.saved(context)
            self.assertEqual(record["actions"][0]["status"], "pending")
            self.assertFalse(record["mode_verified"])
            self.assertEqual(context.snapshot.call_count, 1)

        context.window.click.side_effect = at_send
        context.runner._inspect_currency_wars(context)
        context.window.click.assert_called_once_with(*overclock_row(initial).center, self.geometry, before_send=ANY)
        context.window.key.assert_not_called()
        self.assertEqual(context.report.status, 'success')
        self.assertEqual([result.status for result in context.report.results], ['ok'])
        record = self.saved(context)
        self.assertEqual([a["status"] for a in record["actions"]], ["verified"])
        self.assertTrue(record["mode_verified"])
        self.assertFalse(record["difficulty_verified"])
        self.assertEqual([entry["state"] for entry in record["feedback"]], ["overclock_selected"] * 2)
        self.assertLess(record["feedback"][0]["captured_at"], record["feedback"][1]["captured_at"])
        self.assertNotIn("100000001", self.journal(context).read_text(encoding="utf-8"))

    def test_already_selected_and_a0_use_two_frames_without_any_input(self):
        for kind, difficulty_verified in (("overclock", False), ("a0", True)):
            with self.subTest(kind=kind):
                selected = frame(kind, account=1)
                context = self.context(selected, selected)
                configure_overclock(context)
                record = self.saved(context)
                self.assertTrue(record["mode_verified"])
                self.assertIs(record["difficulty_verified"], difficulty_verified)
                self.assertEqual(record["actions"], [])
                self.assertEqual(len(record["feedback"]), 2)
                self.assertEqual(context.snapshot.call_count, 2)
                context.window.click.assert_not_called()
                context.window.key.assert_not_called()

    def test_duplicate_older_blank_or_missing_identity_breaks_the_feedback_pair(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        for reason, gap in (
            ("duplicate", (selected, 0.0)),
            ("older", (selected, -.02)),
            ("blank", EmptyCapture("synthetic transition")),
            ("no identity", frame("overclock")),
        ):
            with self.subTest(reason=reason):
                context = self.context(standard, selected, gap, selected, selected)
                configure_overclock(context)
                self.assertEqual(context.snapshot.call_count, 5)
                self.assertTrue(self.saved(context)["mode_verified"])
                context.window.click.assert_called_once()

    def test_wrong_mode_feedback_becomes_unknown_and_same_run_refuses_replay(self):
        standard = frame("standard", account=1)
        context = self.context(standard, fallback=standard)
        self.assertEqual(configure_overclock(context).status, "partial")
        record = self.saved(context)
        self.assertFalse(record["mode_verified"])
        self.assertEqual([a["status"] for a in record["actions"]], ["unknown"])
        original = self.journal(context).read_bytes()
        with self.assertRaises(AutomationError):
            configure_overclock(context)
        self.assertEqual(self.journal(context).read_bytes(), original)
        context.window.click.assert_called_once()
        context.window.key.assert_not_called()

    def test_new_account_or_window_cannot_verify_pending_selection(self):
        standard = frame("standard", account=1)
        for reason, changed in (
            ("account", frame("overclock", account=2)),
            ("geometry", replace(frame("overclock", account=1), geometry=replace(self.geometry, left=11))),
        ):
            with self.subTest(reason=reason):
                context = self.context(standard, changed)
                with self.assertRaises(AutomationError):
                    configure_overclock(context)
                record = self.saved(context)
                self.assertFalse(record["mode_verified"])
                self.assertEqual([a["status"] for a in record["actions"]], ["pending"])
                context.window.click.assert_called_once()

    def test_pending_snapshot_changed_in_window_guard_blocks_input(self):
        standard = frame("standard", account=1)
        context = self.context(standard)

        def replace_evidence(_):
            proof = self.saved(context)["actions"][0]["before"]
            Path(proof["screenshot"]).write_bytes(b"changed synthetic evidence")

        context.window.guard.side_effect = replace_evidence
        with self.assertRaises(AutomationError):
            configure_overclock(context)
        self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")
        context.window.click.assert_not_called()

    def test_change_of_epoch_at_native_send_does_not_deliver_the_old_click(self):
        context = self.context(frame("standard", account=1))
        delivered = Mock()

        def native_click(*args, before_send):
            context.runner.input_epoch += 1
            before_send()
            delivered(*args)

        context.window.click.side_effect = native_click
        with self.assertRaises(InputInterrupted):
            configure_overclock(context)
        delivered.assert_not_called()
        self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")

    def test_native_input_rechecks_window_frame_and_pending_after_final_evidence_read(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        original_check = _Configuration._check_saved
        for variant in ("valid", "foreground", "epoch", "age", "journal"):
            with self.subTest(variant=variant):
                context = self.context(standard, selected, selected)
                journal = self.journal(context)
                user32 = self.native_window(context)
                entered_native = False
                original_journal = None

                def native_checkpoint(_):
                    nonlocal entered_native
                    entered_native = True
                    return 0

                def after_evidence(flow, proof):
                    nonlocal original_journal
                    original_check(flow, proof)
                    if not entered_native:
                        return
                    if variant == "foreground":
                        user32.GetForegroundWindow.return_value = 909
                    elif variant == "epoch":
                        context.runner.input_epoch += 1
                    elif variant == "age":
                        self.advance(9)
                    elif variant == "journal":
                        original_journal = journal.read_bytes()
                        row = json.loads(original_journal)
                        row["actions"][0]["status"] = "unknown"
                        journal.write_bytes(json.dumps(row).encode("utf-8"))

                user32.GetAsyncKeyState.side_effect = native_checkpoint
                with (
                    patch.object(windows, "user32", user32),
                    patch.object(windows, "geometry", return_value=self.geometry),
                    patch.object(_Configuration, "_check_saved", after_evidence),
                ):
                    if variant == "valid":
                        self.assertEqual(configure_overclock(context).status, "ok")
                        user32.SendInput.assert_called_once()
                        self.assertEqual(user32.SendInput.call_args.args[0], 3)
                    else:
                        with self.assertRaises(AutomationError):
                            configure_overclock(context)
                        user32.SendInput.assert_not_called()
                self.assertTrue(entered_native)
                if variant == "journal":
                    self.assertIsNotNone(original_journal)
                    self.assertEqual(journal.read_bytes(), original_journal)
                if variant != "valid":
                    self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")

    def test_native_final_window_check_refuses_writes_to_any_verified_input_file(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        variants = ("current_png", "current_journal", "old_journal", "old_before", "old_first", "old_second")
        for variant in variants:
            with self.subTest(variant=variant):
                runs = self.directory / variant / "runs"
                previous = self.context(standard, selected, selected, runs=runs)
                self.assertEqual(configure_overclock(previous).status, "ok")
                saved = self.saved(previous)
                old_paths = {
                    "old_journal": self.journal(previous),
                    "old_before": Path(saved["actions"][0]["before"]["screenshot"]),
                    "old_first": Path(saved["feedback"][0]["screenshot"]),
                    "old_second": Path(saved["feedback"][1]["screenshot"]),
                }
                context = self.context(standard, selected, selected, runs=runs)
                user32 = self.native_window(context)
                reached_send = False
                attempted = None

                def native_checkpoint(_):
                    nonlocal reached_send
                    reached_send = True
                    return 0

                def final_foreground():
                    nonlocal attempted
                    if reached_send and attempted is None:
                        path = old_paths.get(variant, self.journal(context))
                        if variant == "current_png":
                            intent = self.saved(context)["actions"][0]
                            path = Path(intent["before"]["screenshot"])
                        attempted = path, path.read_bytes()
                        path.write_bytes(b"unexpected write during native foreground check")
                    return 71

                user32.GetAsyncKeyState.side_effect = native_checkpoint
                user32.GetForegroundWindow.side_effect = final_foreground
                with (
                    patch.object(windows, "user32", user32),
                    patch.object(windows, "geometry", return_value=self.geometry),
                    self.assertRaisesRegex(AutomationError, "共享读保护失败"),
                ):
                    configure_overclock(context)
                self.assertTrue(reached_send)
                self.assertIsNotNone(attempted)
                path, original = attempted
                self.assertEqual(path.read_bytes(), original)
                user32.SendInput.assert_not_called()
                self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")

    def test_native_send_rechecks_foreground_and_f10_after_frame_and_history_reads(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        check_pixels = currency_wars_overclock._pixels
        history_paths = _Configuration._history_paths
        for variant in ("frame_sha", "history_scan", "f10_after_frame_sha"):
            with self.subTest(variant=variant):
                runs = self.directory / variant / "runs"
                previous = self.context(standard, selected, selected, runs=runs)
                self.assertEqual(configure_overclock(previous).status, "ok")
                old_journal = self.journal(previous).read_bytes()
                context = self.context(standard, selected, selected, runs=runs)
                user32 = self.native_window(context)
                injected = False
                native_scans = 0

                def interrupt_after_read():
                    nonlocal injected
                    if user32.GetAsyncKeyState.called and not injected:
                        injected = True
                        if variant == "f10_after_frame_sha":
                            user32.GetAsyncKeyState.return_value = 0x8001
                        else:
                            user32.GetForegroundWindow.return_value = 909

                def hash_frame(image, geometry):
                    result = check_pixels(image, geometry)
                    if variant != "history_scan":
                        interrupt_after_read()
                    return result

                def scan_history(flow):
                    nonlocal native_scans
                    result = history_paths(flow)
                    if variant == "history_scan" and user32.GetAsyncKeyState.called:
                        native_scans += 1
                        if native_scans == 2:
                            interrupt_after_read()
                    return result

                def fake_delivery(count, *_):
                    user32.GetForegroundWindow.return_value = 71
                    return count

                user32.SendInput.side_effect = fake_delivery
                expected = Stopped if variant == "f10_after_frame_sha" else InputInterrupted
                with (
                    patch.object(windows, "user32", user32),
                    patch.object(windows, "geometry", return_value=self.geometry),
                    patch.object(currency_wars_overclock, "_pixels", hash_frame),
                    patch.object(_Configuration, "_history_paths", scan_history),
                    self.assertRaises(expected),
                ):
                    configure_overclock(context)
                self.assertTrue(injected)
                user32.SendInput.assert_not_called()
                self.assertEqual(self.journal(previous).read_bytes(), old_journal)
                self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")

    def test_native_selection_refuses_an_existing_writable_mapping_with_unchanged_bytes(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        for source in ("current_journal", "old_second"):
            with self.subTest(source=source), ExitStack() as mappings:
                runs = self.directory / source / "runs"
                previous = self.context(standard, selected, selected, runs=runs)
                self.assertEqual(configure_overclock(previous).status, "ok")
                old_journal = self.journal(previous).read_bytes()
                previous_feedback = Path(self.saved(previous)["feedback"][1]["screenshot"])
                context = self.context(standard, selected, selected, runs=runs)
                user32 = self.native_window(context)
                path = self.journal(context) if source == "current_journal" else previous_feedback
                mapped = []

                def open_mapping(_):
                    original = path.read_bytes()
                    with path.open("r+b") as stream:
                        view = mappings.enter_context(mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_WRITE))
                    mapped.append((view, original))
                    return 0

                user32.GetAsyncKeyState.side_effect = open_mapping
                with (
                    patch.object(windows, "user32", user32),
                    patch.object(windows, "geometry", return_value=self.geometry),
                    self.assertRaises(AutomationError),
                ):
                    configure_overclock(context)
                self.assertEqual(len(mapped), 1)
                view, original = mapped[0]
                self.assertEqual(view[:], original)
                self.assertEqual(path.read_bytes(), original)
                self.assertEqual(self.journal(previous).read_bytes(), old_journal)
                self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")
                user32.SendInput.assert_not_called()

    def test_native_final_window_check_rejects_restored_unknown_selection(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        for existing_folder in (False, True):
            with self.subTest(existing_folder=existing_folder):
                runs = self.directory / f"restored-history-{existing_folder}" / "runs"
                previous = self.context(standard, selected, selected, runs=runs)
                self.assertEqual(configure_overclock(previous).status, "ok")
                old_journal = self.journal(previous).read_bytes()
                restored = json.loads(old_journal)
                restored["status"] = "partial"
                restored["actions"][0]["status"] = "unknown"
                payload = json.dumps(restored, ensure_ascii=False).encode("utf-8")
                path = runs / "restored-attempt" / self.journal(previous).name
                if existing_folder:
                    path.parent.mkdir()
                context = self.context(standard, selected, selected, runs=runs)
                user32 = self.native_window(context)

                def restore_at_final_foreground():
                    if user32.GetAsyncKeyState.called and not path.exists():
                        path.parent.mkdir(exist_ok=True)
                        path.write_bytes(payload)
                    return 71

                user32.GetForegroundWindow.side_effect = restore_at_final_foreground
                with (
                    patch.object(windows, "user32", user32),
                    patch.object(windows, "geometry", return_value=self.geometry),
                    self.assertRaisesRegex(AutomationError, "旧记录集合已改变"),
                ):
                    configure_overclock(context)
                user32.SendInput.assert_not_called()
                self.assertEqual(path.read_bytes(), payload)
                self.assertEqual(self.journal(previous).read_bytes(), old_journal)
                self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")

    def test_native_final_window_keeps_frozen_image_and_vetoes_late_frame_changes(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        for variant in ("image", "tokens", "epoch", "age", "occlusion"):
            with self.subTest(variant=variant):
                context = self.context(standard, selected, selected)
                user32 = self.native_window(context)
                injected = False

                def change_at_final_foreground():
                    nonlocal injected
                    if user32.GetAsyncKeyState.called and not injected:
                        injected = True
                        scene = context.last_scene
                        with self.assertRaises(ValueError):
                            scene.image.setflags(write=True)
                        if variant == "image":
                            image = scene.image.copy()
                            image[0, 0, 0] ^= 1
                            scene.image = image
                        elif variant == "tokens":
                            target = overclock_row(scene)
                            index = scene.tokens.index(target)
                            x1, y1, x2, y2 = target.box
                            scene.tokens[index] = replace(target, box=(x1, y1 + .01, x2, y2 + .01))
                        elif variant == "epoch":
                            context.runner.input_epoch += 1
                        elif variant == "age":
                            self.advance(9)
                        else:
                            context.capture_occlusion_count += 1
                    return 71

                user32.GetForegroundWindow.side_effect = change_at_final_foreground
                with (
                    patch.object(windows, "user32", user32),
                    patch.object(windows, "geometry", return_value=self.geometry),
                    self.assertRaises(AutomationError),
                ):
                    configure_overclock(context)
                self.assertTrue(injected)
                user32.SendInput.assert_not_called()
                self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")

    def test_native_selection_holds_verified_sources_until_send_returns(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        runs = self.directory / "held-sources" / "runs"
        previous = self.context(standard, selected, selected, runs=runs)
        self.assertEqual(configure_overclock(previous).status, "ok")
        old = self.saved(previous)
        historical = [self.journal(previous), Path(old["actions"][0]["before"]["screenshot"]),
                      *(Path(row["screenshot"]) for row in old["feedback"])]
        history_bytes = {path: path.read_bytes() for path in historical}
        context = self.context(standard, selected, selected, runs=runs)
        user32 = self.native_window(context)
        attempted = []

        def inspect_sources_during_send(count, *_):
            pending = self.saved(context)["actions"][0]
            self.assertEqual(pending["status"], "pending")
            for path in (self.journal(context), Path(pending["before"]["screenshot"]), *historical):
                with self.assertRaises(PermissionError), path.open("r+b"):
                    pass
                attempted.append(path)
            return count

        user32.SendInput.side_effect = inspect_sources_during_send
        with (
            patch.object(windows, "user32", user32),
            patch.object(windows, "geometry", return_value=self.geometry),
        ):
            self.assertEqual(configure_overclock(context).status, "ok")
        user32.SendInput.assert_called_once()
        self.assertEqual(user32.SendInput.call_args.args[0], 3)
        self.assertEqual(len(attempted), 6)
        for path in attempted:
            with path.open("r+b"):
                pass
        self.assertEqual({path: path.read_bytes() for path in historical}, history_bytes)
        self.assertEqual(self.saved(context)["actions"][0]["status"], "verified")

    def test_complete_uid_conflict_below_positive_confidence_vetoes_pair(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        conflict = replace(selected, tokens=[*selected.tokens, Token("UID100000002", .80, (.14, .96, .22, .99))])
        context = self.context(standard, selected, conflict)
        with self.assertRaises(AutomationError):
            configure_overclock(context)
        self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")
        context.window.click.assert_called_once()

    def test_assistant_occlusion_breaks_a_pair_even_if_snapshot_retries_internally(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        context = self.context(standard, selected, selected, selected)
        capture = context.snapshot.side_effect
        captured_times = []

        def capture_after_occlusion():
            if context.snapshot.call_count == 3:
                context.capture_occlusion_count += 1
            scene = capture()
            captured_times.append(scene.captured_at)
            return scene

        context.snapshot.side_effect = capture_after_occlusion
        self.assertEqual(configure_overclock(context).status, "ok")
        self.assertEqual([proof["captured_at"] for proof in self.saved(context)["feedback"]], captured_times[2:])
        context.window.click.assert_called_once()

    def test_receipt_vetoes_png_replaced_in_last_window_check(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        context = self.context(standard, selected, selected)
        folder = Path(context.report.run_dir)

        def replace_at_final_guard(_):
            if list(folder.glob("*feedback_second.png")):
                next(folder.glob("*feedback_first.png")).write_bytes(b"changed after window guard")

        context.window.guard.side_effect = replace_at_final_guard
        with self.assertRaisesRegex(AutomationError, "落盘证据已改变"):
            configure_overclock(context)
        self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")
        context.window.click.assert_called_once()

    def test_valid_png_from_different_pixels_cannot_be_adopted_as_feedback(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        context = self.context(standard, selected, selected)
        evidence = context.evidence

        def wrong_frame(scene, label):
            path = evidence(scene, label)
            if label.endswith("feedback_first"):
                success, content = cv2.imencode(".png", 255 - scene.image)
                self.assertTrue(success)
                path.write_bytes(content.tobytes())
            return path

        context.evidence = wrong_frame
        with self.assertRaisesRegex(AutomationError, "原画面像素不同"):
            configure_overclock(context)
        self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")
        context.window.click.assert_called_once()

    def test_changed_pending_journal_is_not_overwritten_by_receipt(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        context = self.context(standard, selected, selected)
        changed = b'{"externally_replaced":true}'

        def replace_after_input(seconds):
            if context.sleep.call_count == 1:
                context.window.click.assert_called_once()
                self.journal(context).write_bytes(changed)
            self.advance(seconds)

        context.sleep.side_effect = replace_after_input
        with self.assertRaisesRegex(AutomationError, "原落盘记录已改变"):
            configure_overclock(context)
        self.assertEqual(self.journal(context).read_bytes(), changed)
        self.assertFalse(context.report.currency_wars["mode_verified"])
        context.window.click.assert_called_once()

    def test_new_run_does_not_repeat_unknown_and_a0_can_still_be_verified(self):
        runs = self.directory / "shared-runs"
        standard = frame("standard", account=1)
        first = self.context(standard, fallback=standard, runs=runs)
        self.assertEqual(configure_overclock(first).status, "partial")
        first.window.click.assert_called_once()
        old_data = self.saved(first)
        self.assertEqual(old_data["actions"][0]["status"], "unknown")
        old = self.journal(first).read_bytes()
        proof = Path(old_data["actions"][0]["before"]["screenshot"])
        original_image = proof.read_bytes()
        retry = self.context(standard, runs=runs)
        self.assertEqual(configure_overclock(retry).status, "partial")
        self.assertEqual(self.saved(retry)["reason"], "previous_selection_unresolved")
        retry.window.click.assert_not_called()
        a0 = frame("a0", account=1)
        observe_a0 = self.context(a0, a0, runs=runs)
        self.assertEqual(configure_overclock(observe_a0).status, "ok")
        self.assertTrue(self.saved(observe_a0)["difficulty_verified"])
        observe_a0.window.click.assert_not_called()
        self.assertEqual(self.journal(first).read_bytes(), old)
        self.assertEqual(proof.read_bytes(), original_image)

    def test_new_selection_requires_original_action_and_both_verified_feedback_files(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        cases = ("before_bytes", "feedback_bytes", "missing_feedback", "foreign_path", "duplicate_path",
                 "reversed_frames", "other_target")
        for variant in cases:
            with self.subTest(variant=variant):
                runs = self.directory / variant / "runs"
                first = self.context(standard, selected, selected, runs=runs)
                self.assertEqual(configure_overclock(first).status, "ok")
                journal = self.journal(first)
                record = self.saved(first)
                action = record["actions"][0]
                before, feedback = Path(action["before"]["screenshot"]), record["feedback"]
                first_feedback = Path(feedback[0]["screenshot"])
                if variant == "before_bytes":
                    before.write_bytes(b"changed original selection")
                elif variant == "feedback_bytes":
                    first_feedback.write_bytes(b"changed verified feedback")
                elif variant == "missing_feedback":
                    Path(feedback[1]["screenshot"]).unlink()
                elif variant == "foreign_path":
                    copy = runs / "same-bytes.png"
                    copy.write_bytes(first_feedback.read_bytes())
                    feedback[0]["screenshot"] = str(copy)
                elif variant == "duplicate_path":
                    feedback[1].update(screenshot=feedback[0]["screenshot"], sha256=feedback[0]["sha256"])
                elif variant == "reversed_frames":
                    feedback.reverse()
                else:
                    action["target"] = [.76, .87, .92, .93]
                journal.write_text(json.dumps(record), encoding="utf-8")
                old = {path.name: path.read_bytes() for path in journal.parent.iterdir() if path.is_file()}

                second = self.context(standard, selected, selected, runs=runs)
                self.assertEqual(configure_overclock(second).status, "partial")
                self.assertEqual(self.saved(second)["reason"], "previous_selection_unresolved")
                second.window.click.assert_not_called()
                self.assertEqual({path.name: path.read_bytes() for path in journal.parent.iterdir() if path.is_file()}, old)

    def test_complete_previous_selection_allows_a_new_switch_with_known_path_forms(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        for relative in (False, True):
            with self.subTest(relative=relative):
                runs = self.directory / str(relative) / "runs"
                first = self.context(standard, selected, selected, runs=runs)
                self.assertEqual(configure_overclock(first).status, "ok")
                journal = self.journal(first)
                if relative:
                    record = self.saved(first)
                    for proof in (record["actions"][0]["before"], *record["feedback"]):
                        proof["screenshot"] = Path(proof["screenshot"]).name
                    journal.write_text(json.dumps(record), encoding="utf-8")
                old = journal.read_bytes()

                second = self.context(standard, selected, selected, runs=runs)
                self.assertEqual(configure_overclock(second).status, "ok")
                second.window.click.assert_called_once()
                self.assertEqual(journal.read_bytes(), old)

    def test_receipt_replace_rechecks_frame_age_after_sharing_lock(self):
        standard, selected = frame("standard", account=1), frame("overclock", account=1)
        context = self.context(standard, selected, selected)
        journal = self.journal(context)
        original_replace = Path.replace
        receipt_attempts = []

        def locked(source, destination):
            if Path(destination) == journal:
                receipt = json.loads(source.read_text(encoding="utf-8"))
                if receipt["mode_verified"]:
                    receipt_attempts.append(receipt)
                    if len(receipt_attempts) == 1:
                        raise PermissionError("synthetic sharing lock")
            return original_replace(source, destination)

        with (
            patch.object(Path, "replace", locked),
            patch("autohsr.storage.time.sleep", side_effect=lambda _: self.advance(9)),
            self.assertRaises(AutomationError),
        ):
            configure_overclock(context)
        self.assertEqual(len(receipt_attempts), 1)
        record = self.saved(context)
        self.assertEqual([a["status"] for a in record["actions"]], ["pending"])
        self.assertFalse(record["mode_verified"])
        context.window.click.assert_called_once()

    def test_unknown_or_unavailable_initial_state_never_touches_controls(self):
        blocked = frame("standard", account=1)
        blocked.tokens.append(Token("继续对局", .99, (.44, .45, .52, .49)))
        rank = changed_token(frame("a0", account=1), "AO黑铁", "A1青铜")
        no_account = frame("standard")
        for scene in (blocked, rank, no_account, Scene([])):
            with self.subTest(state=read_overclock(scene).state):
                context = self.context(scene, fallback=scene)
                self.assertEqual(configure_overclock(context).status, "partial")
                record = self.saved(context)
                self.assertFalse(record["mode_verified"])
                self.assertEqual(record["actions"], [])
                context.window.click.assert_not_called()
                context.window.key.assert_not_called()

    def test_context_rejects_foreign_scope_missing_intent_and_forged_enter_button(self):
        standard = frame("standard", account=1)
        for operation in ("currency_wars", "currency_wars_prepare", "currency_wars_flow_test", OPERATION):
            with self.subTest(operation=operation):
                context = self.context(standard, operation=operation)
                scene = context.snapshot()
                with self.assertRaises(AutomationError):
                    context.currency_overclock_input(scene, overclock_row(scene))
                context.window.click.assert_not_called()

        context = self.context(standard)
        send = context.currency_overclock_input

        def substitute(scene, _):
            return send(scene, scene.find("进入标准博弈", exact=True))

        context.currency_overclock_input = substitute
        with self.assertRaises(AutomationError):
            configure_overclock(context)
        self.assertEqual(self.saved(context)["actions"][0]["status"], "pending")
        context.window.click.assert_not_called()
        with self.assertRaises(AutomationError):
            context.click(context.last_scene, overclock_row(context.last_scene))
        with self.assertRaises(AutomationError):
            context.key("esc")
        context.window.click.assert_not_called()
        context.window.key.assert_not_called()

    def test_existing_readonly_workflow_reports_single_frame_diagnosis_only(self):
        context = self.context(frame("a0", account=1), operation="currency_wars")
        with patch("autohsr.currency_wars_replay.save_sample", return_value=self.directory / "fake.sample.json"):
            result = CurrencyWarsWorkflow(context).inspect()
        report = context.report.currency_wars
        self.assertEqual(result.status, "partial")
        self.assertEqual(report["mode"], "read_only_calibration")
        self.assertEqual(report["overclock_configuration"]["state"], "a0_observed")
        self.assertEqual(report["overclock_configuration"]["enemy_difficulty"], 1)
        self.assertFalse(report["completion_verified"])
        self.assertFalse(self.journal(context).exists())
        context.window.click.assert_not_called()

    def test_unresolved_standard_match_blocks_runner_before_game_access(self):
        path = self.directory / "runs" / "currency-standard-session.json"
        store = StandardSession(path)
        store.begin(self.directory / "old-synthetic-run", {})
        original = path.read_bytes()
        runner = Runner(Settings(), operation=OPERATION)
        with (
            patch("autohsr.app.ROOT", self.directory),
            patch("autohsr.windows.kernel32") as kernel,
            patch("autohsr.app.C.get_last_error", return_value=0),
            patch("autohsr.workflow_lease.require_workflow_access"),
            patch("autohsr.app.find_game") as find_game,
            patch.object(runner, "_prepare_daily_game") as prepare,
        ):
            kernel.CreateMutexW.return_value = 1
            report = runner.run()
        self.assertEqual(report.status, "failed")
        self.assertIn("未核实结束的标准对局", report.error)
        self.assertTrue(report.report_saved)
        self.assertEqual(path.read_bytes(), original)
        find_game.assert_not_called()
        prepare.assert_not_called()


    def test_cli_uses_explicit_operation_and_preserves_selected_config_bytes(self):
        from autohsr.__main__ import main

        config = self.directory / "explicit.json"
        Settings().save(config)
        original = config.read_bytes()
        with (
            patch('autohsr.notify_runtime.hooks') as notify,
            patch('autohsr.app.Runner') as runner,
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
        ):
            runner.return_value.run.return_value = {"status": "partial"}
            self.assertEqual(main([FLAG, "--config", str(config)]), 1)
            self.assertEqual(runner.call_args.kwargs["operation"], OPERATION)
        notify.assert_not_called()
        self.assertEqual(config.read_bytes(), original)

    def test_cli_rejects_conflicting_mode_and_overrides_before_configuration_load(self):
        from autohsr.__main__ import main

        with patch.object(Settings, "load") as load, patch("autohsr.app.Runner") as runner:
            for options in (
                ("--currency-wars-check",),
                ("--currency-wars-standard",),
                ("--currency-wealth", "40"),
                ("--resume-active-currency",),
                ("--game-path", "not-read.exe"),
            ):
                with (
                    self.subTest(options=options),
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as caught,
                ):
                    main([FLAG, *options])
                self.assertEqual(caught.exception.code, 2)
            load.assert_not_called()
            runner.assert_not_called()
