"""Exercise the old current-match Runner at a trusted A0 preparation handoff."""

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from autohsr import currency_wars_overclock as overclock, windows
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.models import AutomationError, Stopped
from autohsr.tests import test_currency_wars_overclock_preparation as preparation
from autohsr.tests import test_currency_wars_overclock_start as opening
from autohsr.tests.test_currency_wars_overclock import changed_token, frame


class OverclockLegacyHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = preparation.OverclockPreparationNativeTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def run_old(self, *scenes, **kwargs):
        return opening.OverclockStartNativeTests.legacy_runner(
            self.fixture, False, *scenes, flag=opening.START, **kwargs)

    def complete_preparation(self):
        self.fixture.open_match()
        return self.fixture.follow_route(len(preparation.ROUTE))[-1]

    def original_receipts(self):
        fixture = self.fixture
        original = {fixture.session: fixture.session.read_bytes()}
        opening_record = json.loads(original[fixture.session])
        proofs = [opening_record["actions"][0]["before"], *opening_record["feedback"]]
        if fixture.progress.exists():
            original[fixture.progress] = fixture.progress.read_bytes()
            for step in json.loads(original[fixture.progress])["steps"]:
                proofs.extend((step["before"], *step["feedback"]))
        for proof in proofs:
            path = Path(proof["screenshot"]).resolve(strict=True)
            self.assertTrue(path.is_relative_to(fixture.runs))
            original[path] = path.read_bytes()
        return original

    def assert_receipts_unchanged(self, originals):
        for path, raw in originals.items():
            self.assertEqual(path.read_bytes(), raw, path)

    def assert_no_flow_journal(self, result):
        run = Path(result.report["run_dir"])
        self.assertFalse((run / "currency-flow.json").exists())
        return run

    def assert_no_handoff(self, result):
        self.assertEqual(result.code, 1, result.report["error"])
        self.assertEqual(result.packets, [])
        self.assertEqual(result.enumeration_count, 1)
        data = result.report["currency_wars"]
        self.assertIs(data.get("handoff_verified", False), False)
        self.assertIs(data.get("first_preparation_verified", False), False)
        self.assertEqual(data.get("actions", []), [])
        self.assert_no_flow_journal(result)

    def test_completed_chain_allows_two_current_frames_and_never_sends_input(self):
        fixture = self.fixture
        current = self.complete_preparation()
        original = self.original_receipts()
        self.assertEqual(len(original), 17)
        previous_stamp = fixture.progress_data()["steps"][-1]["feedback"][-1]["captured_at"]
        prior_run = None
        snapshot = Context.snapshot
        attempts = []

        def try_old_actions(context):
            scene = snapshot(context)
            for action in (context.currency_start_node, context.currency_buy_experience):
                with self.assertRaisesRegex(AutomationError, "首备战接续仅可观察当前节点"):
                    action(scene)
                attempts.append(action.__name__)
            return scene

        for capture_patch in (nullcontext(), patch.object(Context, "snapshot", try_old_actions)):
            with capture_patch:
                result = self.run_old(current, current)
            self.assertEqual((result.code, result.report["status"], result.report["operation"]),
                             (1, "partial", "currency_wars_flow_test"), result.report["error"])
            self.assertEqual((result.enumeration_count, result.captures, result.packets), (1, 2, []))
            run = self.assert_no_flow_journal(result)
            self.assertNotEqual(run, prior_run)
            prior_run = run
            data = result.report["currency_wars"]
            self.assertEqual((data["mode"], data["status"], data["actions"]),
                             ("overclock_a0_legacy_handoff", "verified", []))
            for flag in ("handoff_verified", "first_preparation_verified"):
                self.assertIs(data[flag], True)
            for flag in ("gameplay_enabled", "completion_verified", "roster_verified", "loot_verified"):
                self.assertIs(data[flag], False)
            self.assertEqual(data["start_sha256"], hashlib.sha256(original[fixture.session]).hexdigest())
            self.assertEqual(data["preparation_sha256"], hashlib.sha256(original[fixture.progress]).hexdigest())
            first, second = data["feedback"]
            self.assertLess(previous_stamp, first["captured_at"])
            self.assertLess(first["captured_at"], second["captured_at"])
            previous_stamp = second["captured_at"]
            self.assertNotEqual(first["screenshot"], second["screenshot"])
            for proof in (first, second):
                path = Path(proof["screenshot"]).resolve(strict=True)
                self.assertTrue(path.is_relative_to(run))
                self.assertNotIn(path, original)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), proof["sha256"])
            self.assert_receipts_unchanged(original)
        self.assertEqual(attempts, ["currency_start_node", "currency_buy_experience"] * 2)

    def test_missing_root_or_unusable_preparation_cannot_verify_handoff(self):
        fixture = self.fixture
        current = fixture.route_pages()[-1]
        fixture.assert_preflight_veto(self.run_old(current))
        self.assertFalse(fixture.session.exists())

        fixture.open_match()
        original = self.original_receipts()
        no_preparation = self.run_old(current)
        self.assertEqual((no_preparation.code, no_preparation.enumeration_count,
                          no_preparation.captures, no_preparation.packets), (1, 1, 1, []))
        self.assertEqual(no_preparation.report["currency_wars"]["actions"], [])
        self.assertFalse(fixture.progress.exists())
        self.assert_receipts_unchanged(original)
        observed = Path(no_preparation.report["run_dir"]) / "currency-flow.json"
        observed_raw = observed.read_bytes()

        fixture.follow_route(3)
        original = self.original_receipts()
        original[observed] = observed_raw
        self.assertEqual(len(fixture.progress_data()["steps"]), 3)
        fixture.assert_preflight_veto(self.run_old(current))
        self.assert_receipts_unchanged(original)

        corrupt = b'{"status":'
        fixture.progress.write_bytes(corrupt)
        original[fixture.progress] = corrupt
        fixture.assert_preflight_veto(self.run_old(current))
        self.assert_receipts_unchanged(original)

    def test_pending_confirmation_blocks_even_when_first_preparation_is_visible(self):
        fixture = self.fixture
        fixture.open_match()
        *_, chosen, current = fixture.follow_route(3)

        def stop_on_second_feedback(number):
            if number == 3:
                raise Stopped("synthetic stop before the second first-preparation frame")

        result = fixture.native_cli(chosen, current, current, on_capture=stop_on_second_feedback)
        self.assertEqual(result.report["status"], "stopped")
        batch, = result.packets
        fixture.assert_packet_target(batch, chosen, "确认")
        data = fixture.progress_data()
        self.assertEqual((len(data["steps"]), data["status"], data["steps"][-1]["status"]),
                         (4, "pending", "pending"))

        original = self.original_receipts()
        fixture.assert_preflight_veto(self.run_old(current))
        self.assert_receipts_unchanged(original)

    def test_changed_png_from_earlier_step_blocks_before_enumerating(self):
        current = self.complete_preparation()
        fixture = self.fixture
        original = self.original_receipts()
        old_step = fixture.progress_data()["steps"][0]
        first, second = (Path(proof["screenshot"]).resolve(strict=True) for proof in old_step["feedback"])
        self.assertTrue(first.is_relative_to(fixture.runs))
        self.assertNotEqual(original[first], original[second])
        fixture.alternate("changed-early-plane.png", original[second]).replace(first)
        original[first] = original[second]

        fixture.assert_preflight_veto(self.run_old(current))
        self.assert_receipts_unchanged(original)

    def test_unresolved_standalone_actions_and_non_origin_flow_block_before_enumerating(self):
        current = self.complete_preparation()
        fixture = self.fixture
        original = self.original_receipts()
        old_flow = json.loads(opening.OverclockStartNativeTests.legacy_record(
            fixture, dict(action="confirm_environment", status="verified")))
        old_flow["overclock_session_id"] = fixture.ledger()["match_id"]
        history = fixture.runs / "historical-other-run"
        history.mkdir()
        flags = dict(completion_verified=False, gameplay_enabled=False)
        for name, record, reason in (
            ("currency-drag.json", dict(flags, mode="single_drag_test", action_status="pending"), "记录待核对"),
            ("currency-node.json", dict(flags, mode="single_node_test", action="start_node",
                                        action_status="unknown", node_verified=False), "记录待核对"),
            ("currency-node-7.json", dict(flags, mode="single_node_test", action="observe_existing_battle",
                                          action_status="verified", node_verified=False), "记录待核对"),
            ("currency-flow.json", old_flow, "原开局之外的旧流程动作"),
        ):
            with self.subTest(journal=name):
                raw = json.dumps(record).encode("utf-8")
                journal = history / name
                journal.write_bytes(raw)
                try:
                    result = self.run_old(current)
                    fixture.assert_preflight_veto(result)
                    self.assertIn(reason, result.report["error"])
                    self.assertEqual(journal.read_bytes(), raw)
                    self.assert_receipts_unchanged(original)
                finally:
                    journal.unlink()

    def test_original_legacy_opening_can_handoff_after_stop_before_preview_advance(self):
        fixture = self.fixture
        a0, preview = frame("a0", account=1), opening.boss()

        def stop_before_advancing(number):
            if number == 5:
                raise Stopped("synthetic stop after opening receipt was saved")

        started = opening.OverclockStartNativeTests.legacy_runner(
            fixture, True, a0, a0, preview, preview, flag=opening.START, on_capture=stop_before_advancing)
        self.assertEqual((started.code, started.report["status"], started.captures), (1, "stopped", 5))
        start_batch, = started.packets
        fixture.assert_packet_target(start_batch, a0, "开始对局")
        old_flow = Path(started.report["run_dir"]) / "currency-flow.json"
        raw = old_flow.read_bytes()
        root = fixture.ledger()
        self.assertEqual(root["status"], "verified")
        self.assertEqual(root["window_key"], preparation.WINDOW_KEY)
        self.assertEqual(Path(root["run_dir"]), old_flow.parent)
        self.assertEqual(json.loads(raw)["actions"], root["actions"])

        current = fixture.follow_route(len(preparation.ROUTE))[-1]
        original = self.original_receipts()
        original[old_flow] = raw
        handoff = self.run_old(current, current)
        self.assertTrue(handoff.report["currency_wars"]["handoff_verified"], handoff.report["error"])
        self.assertEqual((handoff.captures, handoff.packets), (2, []))
        self.assert_no_flow_journal(handoff)
        self.assert_receipts_unchanged(original)

    def test_later_node_shop_and_reward_pages_never_observe_first_preparation(self):
        current = self.complete_preparation()
        original = self.original_receipts()
        for label, scene in (
            ("later node", changed_token(current, "1-1", "1-2")),
            ("already deployed on first node", changed_token(current, "i0/3", "1/3")),
            ("shop", preparation.with_account(opening.page_tokens("shop"))),
            ("reward", preparation.with_account(opening.page_tokens("equipment_selection"))),
            ("earlier preview", opening.boss()),
        ):
            with self.subTest(page=label):
                result = self.run_old(*([scene] * 110))
                self.assert_no_handoff(result)
                self.assertGreaterEqual(result.captures, 1)
                self.assert_receipts_unchanged(original)

    def test_wrong_account_and_window_lifetime_cannot_observe_first_preparation(self):
        current = self.complete_preparation()
        original = self.original_receipts()
        wrong_account = changed_token(current, "UID100000001", "UID100000002")
        self.assert_no_handoff(self.run_old(wrong_account, wrong_account))
        self.assert_receipts_unchanged(original)

        with patch.object(self.fixture, "window_key", preparation.OTHER_WINDOW_KEY):
            self.assert_no_handoff(self.run_old(current, current))
        self.assert_receipts_unchanged(original)

    def test_same_version_in_another_installation_cannot_observe_first_preparation(self):
        current = self.complete_preparation()
        original = self.original_receipts()
        fixture = self.fixture
        another = fixture.root / "other-fake-client" / "StarRail.exe"
        another.parent.mkdir()
        another.write_bytes(fixture.executable.read_bytes())
        another.with_name("config.ini").write_bytes(fixture.client_ini.read_bytes())
        settings = Settings.load(fixture.config)
        settings.game_path = str(another)
        settings.save(fixture.config)
        fixture.config_bytes = fixture.config.read_bytes()

        with patch.object(fixture, "executable", another):
            self.assert_no_handoff(self.run_old(current, current))
        self.assert_receipts_unchanged(original)

    def test_account_change_between_the_two_readings_prevents_handoff(self):
        current = self.complete_preparation()
        original = self.original_receipts()
        wrong_account = changed_token(current, "UID100000001", "UID100000002")
        result = self.run_old(current, wrong_account)
        self.assert_no_handoff(result)
        self.assertEqual(result.captures, 2)
        self.assert_receipts_unchanged(original)

    def _check_interrupted_handoff(self, interrupt):
        current = self.complete_preparation()
        original = self.original_receipts()
        watch = overclock._hold_history_names
        calls = []

        def after_file_checks(directory, sources):
            check = watch(directory, sources)

            def notify():
                check()
                interrupt()
                calls.append(True)

            return notify

        with patch.object(overclock, "_hold_history_names", after_file_checks):
            result = self.run_old(current, current)
        self.assertEqual(calls, [True])
        self.assertEqual(result.captures, 2)
        self.assert_no_handoff(result)
        self.assert_receipts_unchanged(original)

    def test_losing_focus_after_final_files_are_checked_prevents_handoff(self):
        def lose_focus():
            windows.user32.GetForegroundWindow.side_effect = [0] + [self.fixture.hwnd] * 30

        self._check_interrupted_handoff(lose_focus)

    def test_pressing_f10_after_final_files_are_checked_prevents_handoff(self):
        def press_f10():
            windows.user32.GetAsyncKeyState.side_effect = [1] + [0] * 30

        self._check_interrupted_handoff(press_f10)
