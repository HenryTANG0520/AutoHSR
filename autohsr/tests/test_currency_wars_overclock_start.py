"""A0 match start via the real CLI and native Win32 send with fake capture."""
from contextlib import redirect_stderr
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autohsr import storage
from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.currency_wars import observe
from autohsr.currency_wars_session import StandardSession
from autohsr.models import Scene, Token
from autohsr.tests import test_currency_wars_overclock_a0 as native
from autohsr.tests.test_currency_wars_overclock import FIXTURES, changed_token, frame


START = "--currency-wars-start-overclock-a0"
SESSION = "currency-overclock-session.json"
MODE = "overclock_a0_start"
REPLACE = Path.replace
SHARING_ERRORS = {5, 32, 33}


@lru_cache(maxsize=2)
def page_tokens(kind):
    data = json.loads((FIXTURES / "currency_wars_pages.json").read_text(encoding="utf-8"))
    return tuple(Token(row["text"], row["score"], tuple(row["box"]))
                 for row in data["pages"][kind]["tokens"])


def boss(*, account=1, difficulty=1):
    tokens = [Token(f"敌人难度{difficulty}", row.score, row.box) if row.text == "敌人难度1" else row
              for row in page_tokens("boss_preview")]
    tokens.append(Token(f"UID{100000000 + account}", .99, (.02, .96, .13, .99)))
    return Scene(tokens)


def plane_map():
    return Scene([*page_tokens("plane_map"), Token("UID100000001", .99, (.02, .96, .13, .99))])


class _RunDirectories:
    """Only adapt the old fixture's run lookup. Runner uses the real root."""

    def __init__(self, root):
        self.root = root

    def __fspath__(self):
        return str(self.root)

    def iterdir(self):
        return (entry for entry in self.root.iterdir() if entry.is_dir())


class OverclockStartNativeTests(unittest.TestCase):
    advance = native.OverclockA0NativeTests.advance
    set_version = native.OverclockA0NativeTests.set_version

    def setUp(self):
        native.OverclockA0NativeTests.setUp(self)
        self.session = self.runs / SESSION
        self.attack_dir = self.root / "atomic-replacements"
        self.attack_dir.mkdir()

    def native_cli(self, *scenes, **kwargs):
        with (
            patch.object(native, "JOURNAL", Path("..") / SESSION),
            patch.object(self, "runs", _RunDirectories(self.runs)),
        ):
            outcome = native.OverclockA0NativeTests.native_cli(self, *scenes, flag=START, **kwargs)
        outcome.journal = self.session
        return outcome

    def legacy_runner(self, from_lobby, *scenes, **kwargs):
        def run_from_desktop_settings(args):
            self.assertEqual(args, [START, "--config", str(self.config)])
            report = Runner(
                Settings.load(self.config),
                operation="currency_wars_flow_test",
                currency_start_from_lobby=from_lobby,
            ).run()
            print(json.dumps(report.to_dict(), ensure_ascii=False))
            return 0 if report.status == "success" else 1

        # Reuse the native fixture, replacing only the entry adapter for this legacy Runner.
        with patch.object(native, "main", run_from_desktop_settings):
            return self.native_cli(*scenes, **kwargs)

    def ledger(self):
        return json.loads(self.session.read_bytes())

    def assert_session(self, result, *, started):
        data = self.ledger()
        self.assertEqual(data["mode"], MODE)
        self.assertEqual(result.report["currency_wars"]["mode"], MODE)
        self.assertIs(data["match_started"], started)
        self.assertIs(data["completion_verified"], False)
        self.assertIs(result.report["currency_wars"]["match_started"], started)
        self.assertIs(result.report["currency_wars"]["completion_verified"], False)
        if started:
            self.assertEqual((result.code, result.report["status"], data["status"]), (0, "success", "verified"))
            self.assertEqual(len(data["feedback"]), 2)
            first, second = data["feedback"]
            self.assertEqual([first["state"], second["state"]], ["a0_boss_preview"] * 2)
            self.assertEqual(data["observation"]["enemy_difficulty"], 1)
            self.assertLess(first["captured_at"], second["captured_at"])
            self.assertNotEqual(first["sha256"], second["sha256"])
            for proof in (first, second):
                path = Path(proof["screenshot"])
                self.assertTrue(path.resolve().is_relative_to(self.runs))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), proof["sha256"])
        else:
            self.assertEqual(result.code, 1)
            self.assertIn((data["status"], data["actions"][0]["status"]),
                          (("pending", "pending"), ("partial", "unknown")))
            self.assertEqual(data["feedback"], [])
        return data

    def assert_pending_at_send(self, result):
        pending, = result.at_send
        self.assertEqual(pending["status"], "pending")
        self.assertFalse(pending["match_started"])
        self.assertFalse(pending["completion_verified"])
        return pending

    def assert_single_start_click(self, result, source):
        batch, = result.packets
        self.assert_packet_target(batch, source, "开始对局")

    def assert_packet_target(self, batch, source, label):
        move, down, up = batch
        self.assertEqual([move[:2], down, up], [(0, 0xC001), (0, 0x0002, 0, 0), (0, 0x0004, 0, 0)])
        x = round(move[2] * (self.metrics[78] - 1) / 65535) + self.metrics[76]
        y = round(move[3] * (self.metrics[79] - 1) / 65535) + self.metrics[77]
        token = source.find(label, exact=True)
        self.assertIsNotNone(token)
        self.assertAlmostEqual((x - self.geometry.left) / (self.geometry.width - 1), token.center[0],
                               delta=1 / self.geometry.width)
        self.assertAlmostEqual((y - self.geometry.top) / (self.geometry.height - 1), token.center[1],
                               delta=1 / self.geometry.height)

    def assert_preflight_veto(self, result):
        self.assertEqual((result.code, result.enumeration_count, result.captures, result.packets), (1, 0, 0, []))
        self.assertTrue(result.report["error"])

    def write_legacy(self, raw):
        journal = self.runs / "historical-synthetic" / "currency-flow.json"
        journal.parent.mkdir()
        journal.write_bytes(raw)
        return journal

    def legacy_record(self, *actions):
        return json.dumps(dict(
            mode="flow_test",
            actions=list(actions),
            completion_verified=False,
            gameplay_enabled=False,
            action_status="entry_verified" if actions else "observing",
            screenshot="",
            target_level=0,
            start_from_lobby_requested=True,
        )).encode("utf-8")

    def test_cli_starts_once_at_actual_a0_button_and_stops_at_two_boss_previews(self):
        old = self.legacy_record()
        legacy = self.write_legacy(old)
        a0 = frame("a0", account=1)
        result = self.native_cli(a0, boss(), boss())
        self.assertEqual(result.captures, 3)
        self.assert_single_start_click(result, a0)
        pending, = self.assert_pending_at_send(result)["actions"]
        self.assertEqual(pending["action"], "start_overclock_a0")
        self.assertEqual(pending["target"], list(a0.find("开始对局", exact=True).box))
        self.assertEqual(pending["before"]["state"], "a0_observed")
        data = self.assert_session(result, started=True)
        self.assertEqual(data["actions"], [dict(pending, status="verified")])
        self.assertEqual(legacy.read_bytes(), old)

        before = self.session.read_bytes()
        self.assert_preflight_veto(self.native_cli(a0))
        self.assertEqual(self.session.read_bytes(), before)

    def test_missing_upper_difficulty_proof_never_clicks(self):
        a0 = frame("a0", account=1)
        incomplete = changed_token(a0, "敌人难度+1", None, before_y=.25)
        result = self.native_cli(*([incomplete] * 3))
        self.assertEqual((result.code, result.packets), (1, []))
        self.assertGreaterEqual(result.captures, 1)
        self.assertFalse(self.session.exists())
        self.assertFalse(result.report["currency_wars"]["match_started"])
        self.assertEqual(result.report["currency_wars"]["observation"]["state"], "effects_unverified")

    def test_conflicting_enemy_difficulty_preview_cannot_verify_the_send(self):
        a0 = frame("a0", account=1)
        wrong = boss(difficulty=2)
        self.assertEqual(observe(wrong, .65).page_kind, "boss_preview")
        result = self.native_cli(a0, wrong, boss(), boss())
        self.assertEqual(result.captures, 2)
        self.assert_single_start_click(result, a0)
        self.assert_pending_at_send(result)
        data = self.assert_session(result, started=False)
        self.assertEqual((data["status"], data["reason"]), ("partial", "boss_difficulty_conflicting"))
        self.assertEqual(data["actions"][0]["status"], "unknown")

    def test_already_at_boss_preview_cannot_adopt_a_match_or_advance(self):
        result = self.native_cli(boss())
        self.assertEqual((result.code, result.packets), (1, []))
        self.assertEqual(result.captures, 1)
        self.assertFalse(self.session.exists())

    def test_account_changes_before_second_preview_and_pending_blocks_a_new_run(self):
        a0 = frame("a0", account=1)
        result = self.native_cli(a0, boss(), boss(account=2))
        self.assertEqual(result.captures, 3)
        self.assert_single_start_click(result, a0)
        self.assert_pending_at_send(result)
        self.assertEqual(self.assert_session(result, started=False)["status"], "pending")
        before = self.session.read_bytes()

        self.assert_preflight_veto(self.native_cli(a0))
        self.assertEqual(self.session.read_bytes(), before)

    def assert_legacy_veto(self, raw, expected_error):
        journal = self.write_legacy(raw)
        result = self.native_cli(frame("a0", account=1))
        self.assert_preflight_veto(result)
        self.assertIn(expected_error, result.report["error"])
        self.assertEqual(journal.read_bytes(), raw)
        self.assertFalse(self.session.exists())

    def test_nonempty_old_flow_blocks_before_window_enumeration(self):
        raw = self.legacy_record(dict(action="start_overclock_a0", status="verified"))
        self.assert_legacy_veto(raw, "原超频流程")
        result = self.legacy_runner(True, frame("a0", account=1))
        self.assert_preflight_veto(result)
        self.assertIn("原超频流程", result.report["error"])
        self.assertEqual((self.runs / "historical-synthetic" / "currency-flow.json").read_bytes(), raw)
        self.assertFalse(self.session.exists())

    def test_corrupt_old_flow_blocks_before_window_enumeration(self):
        self.assert_legacy_veto(b'{"mode":"flow_test","actions":[', "原货币战争记录或证据")

    def test_unresolved_standard_match_blocks_before_window_enumeration(self):
        original = self.runs / "currency-standard-session.json"
        StandardSession(original).begin(self.runs / "synthetic-standard-run", {})
        saved = original.read_bytes()

        result = self.native_cli(frame("a0", account=1))
        self.assert_preflight_veto(result)
        self.assertIn("未核实结束的标准对局", result.report["error"])
        self.assertEqual(original.read_bytes(), saved)
        self.assertFalse(self.session.exists())

    def test_exclusive_intent_creation_preserves_late_record_and_sends_nothing(self):
        original = b'{"status":"pending"}'
        rename = Path.rename
        injected = []

        def install_old_record(temporary, destination):
            if destination == self.session:
                destination.write_bytes(original)
                injected.append(destination)
            return rename(temporary, destination)

        with patch.object(Path, "rename", install_old_record):
            result = self.native_cli(frame("a0", account=1))
        self.assertEqual((result.code, result.captures, result.packets), (1, 1, []))
        self.assertEqual(injected, [self.session])
        self.assertEqual(self.session.read_bytes(), original)

    def test_uncalibrated_version_never_captures_or_sends(self):
        self.set_version("4.6.1")
        result = self.native_cli(frame("a0", account=1))
        self.assertEqual((result.code, result.captures, result.packets), (1, 0, []))
        self.assertIn("版本证据", result.report["error"])
        self.assertFalse(self.session.exists())

    def test_legacy_whole_match_shares_the_start_and_cannot_open_again_after_preview(self):
        a0 = frame("a0", account=1)
        preview = boss()
        flow_at_send = []

        def inspect_flow_at_send():
            path, = (self.root / "runs").glob("*/currency-flow.json")
            flow_at_send.append(json.loads(path.read_bytes()))

        result = self.legacy_runner(True, a0, a0, preview, preview, preview, plane_map(), a0,
                                    on_send=inspect_flow_at_send)
        self.assertEqual((result.code, result.report["status"], result.captures), (1, "partial", 7),
                         result.report["error"])
        start, next_page = result.packets
        self.assert_packet_target(start, a0, "开始对局")
        self.assert_packet_target(next_page, preview, "下一步")
        pending, verified = result.at_send
        self.assertEqual((pending["status"], pending["match_started"]), ("pending", False))
        self.assertEqual((pending["actions"][0]["action"], pending["actions"][0]["status"]),
                         ("start_overclock_a0", "pending"))
        self.assertEqual((verified["status"], verified["match_started"], verified["completion_verified"]),
                         ("verified", True, False))
        self.assertEqual(pending["match_id"], verified["match_id"])
        self.assertEqual(self.ledger(), verified)
        before_start, before_next = flow_at_send
        self.assertEqual(before_start["actions"], [])
        self.assertEqual(before_next["actions"][-1]["action"], "advance_boss_preview")
        self.assertEqual(before_next["actions"][-1]["status"], "pending")
        flow = result.report["currency_wars"]
        self.assertEqual(flow["overclock_session_id"], verified["match_id"])
        self.assertEqual([(a["action"], a["status"]) for a in flow["actions"]],
                         [("start_overclock_a0", "verified"), ("advance_boss_preview", "verified")])
        self.assertFalse(flow["completion_verified"])

    def test_legacy_advance_without_verified_root_blocks_before_window_enumeration(self):
        result = self.legacy_runner(False, boss())
        self.assert_preflight_veto(result)
        self.assertIn("没有已核实的超频 A0 开局", result.report["error"])
        self.assertFalse(self.session.exists())

    def test_legacy_advance_checks_nonempty_old_flow_even_with_a_verified_root(self):
        a0, preview = frame("a0", account=1), boss()
        started = self.native_cli(a0, preview, preview)
        self.assert_session(started, started=True)
        original = self.session.read_bytes()
        old = self.legacy_record(dict(action="start_overclock_a0", status="verified"))
        legacy = self.write_legacy(old)

        result = self.legacy_runner(False, preview)
        self.assert_preflight_veto(result)
        self.assertIn("原超频流程", result.report["error"])
        self.assertEqual(self.session.read_bytes(), original)
        self.assertEqual(legacy.read_bytes(), old)

    def test_legacy_advance_uses_matching_cli_preview_without_another_start(self):
        a0, preview = frame("a0", account=1), boss()
        started = self.native_cli(a0, preview, preview)
        data = self.assert_session(started, started=True)
        original = self.session.read_bytes()

        result = self.legacy_runner(False, preview, plane_map(), a0)
        self.assertEqual((result.code, result.report["status"], result.captures), (1, "partial", 3),
                         result.report["error"])
        batch, = result.packets
        self.assert_packet_target(batch, preview, "下一步")
        self.assertEqual(result.at_send, [data])
        flow = result.report["currency_wars"]
        self.assertEqual(flow["overclock_session_id"], data["match_id"])
        self.assertEqual([(a["action"], a["status"]) for a in flow["actions"]],
                         [("advance_boss_preview", "verified")])
        self.assertFalse(flow["completion_verified"])
        self.assertEqual(self.session.read_bytes(), original)

        flow_path = Path(result.report["run_dir"]) / "currency-flow.json"
        first_flow = flow_path.read_bytes()
        replay = self.legacy_runner(False, preview)
        self.assert_preflight_veto(replay)
        self.assertIn("原超频首领预览已经推进", replay.report["error"])
        self.assertEqual(flow_path.read_bytes(), first_flow)
        self.assertEqual(self.session.read_bytes(), original)

    def test_cli_rejects_other_modes_and_overrides_before_loading_settings(self):
        with patch.object(Settings, "load") as load:
            for options in (
                (native.OPEN_A0,), ("--currency-wars-standard",), ("--resume-active-currency",),
                ("--currency-wealth", "40"), ("--game-path", "unused.exe"),
            ):
                with (
                    self.subTest(options=options),
                    redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit) as error,
                ):
                    main([START, "--config", str(self.config), *options])
                self.assertEqual(error.exception.code, 2)
        load.assert_not_called()

    def alternate(self, name, payload):
        replacement = self.attack_dir / name
        replacement.write_bytes(payload)
        return replacement

    def assert_ntfs_denies_replace(self, replacement, target):
        target = target.resolve(strict=True)
        self.assertTrue(target.is_relative_to(self.root))
        original = target.read_bytes()
        candidate = replacement.read_bytes()
        self.assertNotEqual(candidate, original)
        with self.assertRaises(OSError) as caught:
            REPLACE(replacement, target)
        self.assertIn(caught.exception.winerror, SHARING_ERRORS)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual(replacement.read_bytes(), candidate)
        return original

    def assert_released(self, replacement, target, original):
        self.assertTrue(target.resolve(strict=True).is_relative_to(self.root))
        candidate = replacement.read_bytes()
        REPLACE(replacement, target)
        self.assertEqual(target.read_bytes(), candidate)
        replacement.write_bytes(original)
        REPLACE(replacement, target)
        self.assertEqual(target.read_bytes(), original)

    def test_version_ini_is_held_until_native_send_returns(self):
        original = self.client_ini.read_bytes()
        replacement = self.alternate("different-version.ini", original.replace(b"4.6.0", b"4.7.0"))
        denied = []

        def try_replace_at_send():
            self.assertEqual(self.ledger()["status"], "pending")
            denied.append(self.assert_ntfs_denies_replace(replacement, self.client_ini))

        result = self.native_cli(frame("a0", account=1), boss(), boss(), on_send=try_replace_at_send)
        self.assert_session(result, started=True)
        self.assert_pending_at_send(result)
        self.assertEqual(denied, [original])
        self.assert_released(replacement, self.client_ini, original)

    def test_feedback_png_is_held_through_actual_receipt_replace(self):
        denied = []

        def check_receipt_replace(source, destination):
            if Path(destination) == self.session:
                proposed = json.loads(source.read_bytes())
                if proposed["match_started"]:
                    self.assertEqual(self.ledger()["status"], "pending")
                    first, second = (Path(row["screenshot"]) for row in proposed["feedback"])
                    alternate = self.alternate("wrong-preview.png", second.read_bytes())
                    original = self.assert_ntfs_denies_replace(alternate, first)
                    denied.append((alternate, first, original))
            return REPLACE(source, destination)

        with patch.object(Path, "replace", check_receipt_replace):
            result = self.native_cli(frame("a0", account=1), boss(), boss())
        self.assert_session(result, started=True)
        alternate, target, original = denied.pop()
        self.assertFalse(denied)
        self.assert_released(alternate, target, original)

    def test_receipt_replace_retry_rechecks_png_and_preserves_pending(self):
        first_replace, wait, attempted = [], [], []

        def fail_first_receipt_replace(source, destination):
            if Path(destination) != self.session:
                return REPLACE(source, destination)
            proposal = json.loads(source.read_bytes())
            if not proposal["match_started"]:
                return REPLACE(source, destination)
            attempted.append(Path(destination))
            self.assertEqual(len(attempted), 1, "changed feedback must prevent a second journal replace")
            pending = self.session.read_bytes()
            self.assertEqual(json.loads(pending)["status"], "pending")
            first, second = (Path(row["screenshot"]) for row in proposal["feedback"])
            with storage.hold_read_sources((self.session,)):
                try:
                    REPLACE(source, destination)
                except OSError as error:
                    self.assertIn(error.winerror, SHARING_ERRORS)
                    self.assertEqual(self.session.read_bytes(), pending)
                    self.assertTrue(source.is_file())
                    first_replace.append((pending, first, second))
                    raise
            self.fail("NTFS allowed replacement while the destination had a read-only sharing handle")

        def change_png_between_attempts(delay):
            self.assertEqual(delay, storage.REPLACE_RETRY_DELAYS[0])
            self.assertFalse(wait)
            pending, first, second = first_replace[0]
            self.assertTrue(first.resolve(strict=True).is_relative_to(self.root))
            original, changed = first.read_bytes(), second.read_bytes()
            self.assertNotEqual(original, changed)
            REPLACE(self.alternate("retry-feedback.png", changed), first)
            self.assertEqual(self.session.read_bytes(), pending)
            wait.append((first, original, changed))
            self.advance(delay)

        a0 = frame("a0", account=1)
        with (
            patch.object(Path, "replace", fail_first_receipt_replace),
            patch.object(storage, "time", SimpleNamespace(sleep=change_png_between_attempts)),
        ):
            result = self.native_cli(a0, boss(), boss())
        ((pending, _, _),), ((first, original, changed),) = first_replace, wait
        self.assertEqual(attempted, [self.session])
        self.assertIn("落盘证据已改变", result.report["error"])
        self.assertEqual(self.assert_pending_at_send(result), json.loads(pending))
        self.assert_single_start_click(result, a0)
        self.assertEqual(self.assert_session(result, started=False)["status"], "pending")
        self.assertEqual(self.session.read_bytes(), pending)
        self.assertEqual(first.read_bytes(), changed)
        self.assert_preflight_veto(self.native_cli(a0))
        self.assertEqual(self.session.read_bytes(), pending)
        REPLACE(self.alternate("restore-feedback.png", original), first)
        self.assertEqual(first.read_bytes(), original)
