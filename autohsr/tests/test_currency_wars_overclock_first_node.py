"""A0 first-node receipts through the ordinary legacy Runner and fake Win32."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr import storage, windows
from autohsr.currency_wars_equipment import equipment_template
from autohsr.currency_wars_overclock_first_node import LegacyFirstNode
from autohsr.currency_wars_overclock_first_node_pages import drop_delivery, read_first_node_board
from autohsr.models import AutomationError, Scene, Stopped, Token
from autohsr.tests import test_currency_wars_overclock_preparation as preparation
from autohsr.tests import test_currency_wars_overclock_start as opening
from autohsr.tests.test_currency_wars_deployment import deployment_frame
from autohsr.tests.test_currency_wars_node import screen as node_screen
from autohsr.tests.test_currency_wars_overclock import changed_token
from autohsr.tests.test_currency_wars_standard_trading import hud
from autohsr.windows import Geometry


CONFIDENCE = .65
GRAY = (2086, 486, 28, (200, 200, 200))
BLUE = (2114, 558, 47, (220, 150, 48))
MOVED_BLUE = (1970, 548, 47, BLUE[3])
FRONT = (990, 1180, 1370, 1560)
BACK = (805, 995, 1185, 1375, 1565, 1755)
BATTERY_POINT = (2460 / 2560, 330 / 1440)


def first_node_scene(*, front=(), back=(), gold=3, crystals=(), batteries=()):
    """Keep the public 1-1 OCR layout and draw synthetic UI pixels at native scale."""
    scene = deployment_frame(6)
    hud(scene, gold=gold, level=3, xp=(0, 4), deployment=(len(front) + len(back), 3))
    for slots, centers, y in ((front, FRONT, 530), (back, BACK, 890)):
        for slot in slots:
            x = centers[slot - 1]
            patch = scene.image[y - 28:y + 28, x - 35:x + 35]
            patch[:] = np.random.default_rng(x + y).integers(0, 256, patch.shape, dtype=np.uint8)
    for x, y, radius, color in crystals:
        cv2.circle(scene.image, (x, y), radius, color, -1)
    for slot in batteries:
        column, row = divmod(slot, 6)
        x, y = (2350, 2460)[column], (330, 430, 535, 640, 745, 845)[row]
        image = equipment_template("battery")
        height, width = image.shape[:2]
        left, top = x - width // 2, y - height // 2
        scene.image[top:top + height, left:left + width] = image
    return scene


def two_crystals():
    return first_node_scene(front=(1, 2), back=(1,), crystals=(GRAY, BLUE))


def one_blue():
    return first_node_scene(front=(1, 2), back=(1,), gold=5, crystals=(BLUE,))


def empty_ground(*, gold=5, batteries=()):
    return first_node_scene(front=(1, 2), back=(1,), gold=gold, batteries=batteries)


class FirstNodePageTests(unittest.TestCase):
    def test_empty_back_only_and_full_formations_are_distinct_board_facts(self):
        for front, back in (((), ()), ((), (1,)), ((1, 2), (1,))):
            with self.subTest(front=front, back=back):
                scene = first_node_scene(front=front, back=back, crystals=(GRAY, BLUE))
                board = read_first_node_board(scene, CONFIDENCE)
                self.assertEqual((board.match.node, board.match.hp, board.match.level,
                                  board.match.experience, board.match.deployment),
                                 ("1-1", 100, 3, (0, 4), (len(front) + len(back), 3)))
                occupied = {(cell.zone, cell.slot) for cell in board.cells
                            if cell.zone != "bench" and cell.state == "occupied"}
                self.assertEqual(occupied, {("front", slot) for slot in front} | {("back", slot) for slot in back})
                self.assertEqual(len(board.crystals), 2)
                self.assertEqual(board.batteries, ())
                self.assertEqual(board.target, scene.find("出战", exact=True))

    def test_duplicate_or_weak_start_button_is_unverified_and_missing_button_is_unreadable(self):
        scene = first_node_scene(front=(1, 2), back=(1,))
        target = scene.find("出战", exact=True)
        duplicate = replace(target, box=(.910, .676, .939, .709))
        ambiguous = replace(scene, tokens=[*scene.tokens, duplicate])
        self.assertIsNone(read_first_node_board(ambiguous, CONFIDENCE).target)
        weak = changed_token(scene, "出战", "出战", score=.80)
        self.assertIsNone(read_first_node_board(weak, CONFIDENCE).target)
        with self.assertRaises(AutomationError):
            read_first_node_board(changed_token(scene, "出战", None), CONFIDENCE)

    def test_conflicting_hud_unknown_formation_shop_and_other_node_are_unreadable(self):
        scene = first_node_scene(front=(1, 2), back=(1,))
        hud_conflict = replace(scene, tokens=[*scene.tokens, Token("13/3", .747, (.446, .198, .535, .257))])
        gold_conflict = replace(scene, tokens=[*scene.tokens, Token("4", .82, (.851, .829, .87, .868))])
        wrong_formation = hud(first_node_scene(back=(1,)), deployment=(3, 3))
        open_shop = replace(scene, tokens=list(opening.page_tokens("shop")))
        for label, invalid in (
            ("deployment OCR conflict", hud_conflict),
            ("gold OCR conflict", gold_conflict),
            ("slots do not match deployment HUD", wrong_formation),
            ("open shop", open_shop),
            ("other node", changed_token(scene, "1-1", "1-2")),
        ):
            with self.subTest(board=label), self.assertRaises(AutomationError):
                read_first_node_board(invalid, CONFIDENCE)

    def test_two_to_one_requires_gold_delivery_and_the_same_remaining_crystal(self):
        before, after = two_crystals(), one_blue()
        old = read_first_node_board(before, CONFIDENCE)
        new = read_first_node_board(after, CONFIDENCE)
        gray, blue = sorted(old.crystals, key=lambda crystal: crystal[2])
        self.assertEqual(new.crystals, (blue,))
        delivered = drop_delivery(before, after, gray, CONFIDENCE)
        self.assertIsNotNone(delivered)
        self.assertEqual((delivered.kind, delivered.value, delivered.remaining), ("gold", 2, (blue,)))

    def test_gray_disappearance_without_exact_gold_or_remaining_match_is_unverified(self):
        before = two_crystals()
        gray = min(read_first_node_board(before, CONFIDENCE).crystals, key=lambda crystal: crystal[2])
        still_visible = hud(two_crystals(), gold=5)
        no_gold = hud(one_blue(), gold=3)
        other_blue = first_node_scene(front=(1, 2), back=(1,), gold=5, crystals=(MOVED_BLUE,))
        wrong_node = changed_token(one_blue(), "1-1", "1-2")
        for label, after in (
            ("target still visible", still_visible),
            ("only disappearance", no_gold),
            ("wrong gold increment", hud(one_blue(), gold=4)),
            ("other surviving crystal", other_blue),
            ("both crystals gone", empty_ground()),
            ("wrong node", wrong_node),
        ):
            with self.subTest(feedback=label):
                self.assertIsNone(drop_delivery(before, after, gray, CONFIDENCE))
        self.assertIsNone(drop_delivery(before, one_blue(), (.69, .31, .011), CONFIDENCE))

    def test_one_to_zero_requires_the_single_new_battery_at_unchanged_gold(self):
        before, after = one_blue(), empty_ground(batteries=(6,))
        blue, = read_first_node_board(before, CONFIDENCE).crystals
        observed = read_first_node_board(after, CONFIDENCE)
        self.assertEqual((observed.crystals, observed.batteries), ((), (BATTERY_POINT,)))
        delivered = drop_delivery(before, after, blue, CONFIDENCE)
        self.assertIsNotNone(delivered)
        self.assertEqual((delivered.kind, delivered.value, delivered.remaining), ("battery", BATTERY_POINT, ()))

    def test_blue_disappearance_without_a_unique_new_battery_is_unverified(self):
        before = one_blue()
        blue, = read_first_node_board(before, CONFIDENCE).crystals
        for label, after in (
            ("only disappearance", empty_ground()),
            ("multiple batteries", empty_ground(batteries=(6, 7))),
            ("simultaneous gold change", empty_ground(gold=6, batteries=(6,))),
        ):
            with self.subTest(feedback=label):
                self.assertIsNone(drop_delivery(before, after, blue, CONFIDENCE))
        already = first_node_scene(front=(1, 2), back=(1,), gold=5, crystals=(BLUE,), batteries=(6,))
        self.assertIsNone(drop_delivery(already, empty_ground(batteries=(6,)), blue, CONFIDENCE))


def synthetic_battle(node="1-1"):
    # Keep the public 127 battle layout. Its bounded 1-1 reads are synthetic.
    tokens = [replace(token, text=f"{node}50%") if token.text == "1-250%" else token
              for token in opening.page_tokens("battle")]
    bounds = (.358, .008, .386, .040)
    return Scene(tokens, field_reads={
        "currency_battle_node.normal": (Token(node, .99, bounds), Token(node, .98, bounds)),
    })


def victory(node="1-1", *, conflicting=False):
    # Keep 109's merged OCR and supply an independent bounded number.
    tokens = [replace(token, text=f"{node}M奖励") if token.text == "1-1M奖励" else token
              for token in opening.page_tokens("node_result")]
    tokens.append(Token(node, .99, (.462, .245, .485, .286)))
    if conflicting:
        tokens.append(Token("1-2", .99, (.405, .245, .438, .286)))
    return Scene(tokens)


class _RepeatedCaptureTime(Scene):
    """Inject duplicate OCR timestamps while retaining distinct native captures."""

    def __init__(self, tokens, image, geometry, field_reads, timestamps):
        self.timestamps = timestamps
        super().__init__(tokens, image, geometry, field_reads=field_reads)

    def __setattr__(self, name, value):
        if name == "captured_at" and value > 0:
            self.timestamps.append(value)
            value = self.timestamps[0]
        super().__setattr__(name, value)


class LegacyFirstNodeNativeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = preparation.OverclockPreparationNativeTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fixture.geometry = Geometry(31, 27, 1280, 720)

    def with_native_pixels(self, scene):
        geometry = self.fixture.geometry
        image = (None if scene.image is None else cv2.resize(
            scene.image, (geometry.width, geometry.height), interpolation=cv2.INTER_AREA))
        return replace(preparation.with_account(scene.tokens, image=image), field_reads=scene.field_reads)

    def arrive_then_observe(self, final_scene):
        fixture = self.fixture
        original = fixture.open_match()
        preview, plane, insurance = opening.boss(), fixture.plane(1), fixture.environment(selected=0)
        arrival = self.with_native_pixels(first_node_scene())
        after = self.with_native_pixels(final_scene)
        result = opening.OverclockStartNativeTests.legacy_runner(
            fixture, False, preview, plane, plane, insurance, insurance, arrival, after,
            flag=opening.START)
        self.assertEqual((result.code, result.report["status"], result.captures), (1, "partial", 7),
                         result.report["error"])
        boss_click, plane_click, confirm_click = result.packets
        fixture.assert_packet_target(boss_click, preview, "下一步")
        fixture.assert_packet_target(plane_click, plane, "点击空白处继续")
        fixture.assert_packet_target(confirm_click, insurance, "确认")
        self.assertEqual(fixture.session.read_bytes(), original)
        data = result.report["currency_wars"]
        self.assertEqual(data["first_node_preflight"], {"status": "pending", "node": "1-1"})
        self.assertEqual(data["action_status"], "needs_decision")
        self.assertIs(data["completion_verified"], False)
        self.assertEqual([(row["action"], row["status"]) for row in data["actions"]],
                         [("advance_boss_preview", "verified"), ("advance_plane", "verified"),
                          ("confirm_environment", "verified")])
        run_dir = Path(result.report["run_dir"])
        self.assertEqual(json.loads((run_dir / "currency-flow.json").read_bytes()), data)
        self.assertEqual(list(run_dir.glob("currency-node*.json")), [])
        return data

    def test_existing_full_formation_without_current_deployment_receipts_never_picks_up_or_starts(self):
        data = self.arrive_then_observe(two_crystals())
        self.assertEqual(data["page_kind"], "preparation")
        self.assertRegex(data["reason"], "部署回执.*阵容.*不一致")

    def test_already_settled_first_node_after_arrival_never_advances_or_replays(self):
        data = self.arrive_then_observe(node_screen("node_result", "1-1"))
        self.assertEqual(data["page_kind"], "node_result")
        self.assertIn("结算", data["reason"])

    def run_started_node(self, *feedback, verify_lock=False, repeat_timestamps=(), on_feedback=None, stop_at_start=False):
        fixture = self.fixture
        fixture.geometry = Geometry(31, 27, 2560, 1440)
        fixture.metrics.update({78: 3200, 79: 1800})
        opening_bytes = fixture.open_match()
        preview, plane, insurance = opening.boss(), fixture.plane(1), fixture.environment(selected=0)
        no_units = self.with_native_pixels(first_node_scene(crystals=(GRAY, BLUE)))
        first_unit = self.with_native_pixels(first_node_scene(front=(1,), crystals=(GRAY, BLUE)))
        second_unit = self.with_native_pixels(first_node_scene(front=(1, 2), crystals=(GRAY, BLUE)))
        full = self.with_native_pixels(two_crystals())
        gray_delivered = self.with_native_pixels(one_blue())
        blue_delivered = self.with_native_pixels(empty_ground(batteries=(6,)))
        prefix = (
            preview, plane, plane, insurance, insurance, no_units, no_units,
            first_unit, first_unit, second_unit, second_unit, full, full,
            gray_delivered, gray_delivered, gray_delivered,
            blue_delivered, blue_delivered, blue_delivered, blue_delivered,
        )
        if feedback:
            # The fake clock has no tick between acknowledging SendInput and
            # the first capture. Use that frame as a loading transition.
            prefix += (self.with_native_pixels(Scene([])),)
        scenes = (*prefix, *(self.with_native_pixels(scene) for scene in feedback))
        scripted = iter(enumerate(scenes))
        real_times = []

        def fake_scene(*, tokens, image, geometry):
            index, source = next(scripted)
            if index - len(prefix) in repeat_timestamps:
                return _RepeatedCaptureTime(tokens, image, geometry, source.field_reads, real_times)
            return Scene(tokens=tokens, image=image, geometry=geometry, field_reads=source.field_reads)
        roster = (("front", 1, "前台一"), ("front", 2, "前台二"), ("back", 1, "后台一"))

        def candidate(_scene, _confidence, excluded):
            return SimpleNamespace(slot=len(excluded) + 1)

        def deploy(context, before, current, data, persist):
            index = current.slot - 1
            zone, slot, name = roster[index]
            plan = SimpleNamespace(zone=zone, target_slot=slot)
            profile = SimpleNamespace(node="1-1", name=name, zones=(zone,))
            self.assertIs(context.last_scene, before)
            action = dict(action="deploy_candidate", status="pending",
                          before=str(context.evidence(before, "test_a0_deploy_before")))
            data["actions"].append(action)
            data.update(action_status="pending", screenshot=action["before"])
            persist()
            after = context.snapshot()
            self.assertEqual(read_first_node_board(before, CONFIDENCE).match.deployment, (index, 3))
            self.assertEqual(read_first_node_board(after, CONFIDENCE).match.deployment, (index + 1, 3))
            action.update(status="verified", after=str(context.evidence(after, "test_a0_deploy_after")),
                          feedback=dict(status="verified", deployment_before=(index, 3),
                                        deployment_after=(index + 1, 3)))
            data.update(action_status="verified", screenshot=action["after"])
            persist()
            context._legacy_first_node.record_deployment(before, after, action, plan, profile)
            return True

        sent, start_at_send, after_send = [], [], []
        locked_proofs = []

        def inspect_send():
            flow, = (fixture.root / "runs").glob("*/currency-flow.json")
            data = json.loads(flow.read_bytes())
            last = data["actions"][-1]
            sent.append((last["action"], last["status"]))
            if last["action"] != "run_current_node":
                return
            node, = flow.parent.glob("currency-node-*.json")
            pending = json.loads(node.read_bytes())
            self.assertEqual((pending["action"], pending["action_status"], pending["origin_node"]),
                             ("start_node", "pending", "1-1"))
            self.assertFalse(pending.get("start_dispatched", False))
            self.assertNotIn("dispatched_at", pending)
            preflight = data["first_node_preflight"]
            self.assertEqual((preflight["status"], preflight["node"]), ("verified", "1-1"))
            first, second = preflight["feedback"]
            self.assertLess(first["captured_at"], second["captured_at"])
            if verify_lock:
                proof = Path(first["screenshot"])
                replacement = fixture.alternate("changed-first-node-preflight.png", b"synthetic replacement")
                original = fixture.assert_ntfs_denies_replace(replacement, proof)
                self.assertEqual(hashlib.sha256(original).hexdigest(), first["sha256"])
                locked_proofs.append((replacement, proof, original))
            start_at_send.append((flow, node))

        def inspect_capture(number):
            if start_at_send and number > len(prefix):
                if len(after_send) == len(feedback):
                    raise Stopped("synthetic stop at the end of the first-node observations")
                _, node = start_at_send[0]
                record = json.loads(node.read_bytes())
                after_send.append(record)
                if on_feedback is not None:
                    on_feedback(record)

        finish = LegacyFirstNode._finish_native_check

        def final_history_check(workflow, scene, unchanged, *args, **kwargs):
            def check_then_stop():
                unchanged()
                if stop_at_start and workflow.flow['actions'][-1]['action'] == 'run_current_node':
                    windows.user32.GetAsyncKeyState.side_effect = [1] + [0] * 120

            return finish(workflow, scene, check_then_stop, *args, **kwargs)

        with (
            patch.object(preparation, "Scene", fake_scene),
            patch("autohsr.currency_wars_roster.next_candidate", side_effect=candidate),
            patch("autohsr.currency_wars_roster.deploy_candidate", side_effect=deploy),
            patch("autohsr.currency_wars_equipment.equipment_fields", return_value=()),
            patch.object(LegacyFirstNode, '_finish_native_check', final_history_check),
        ):
            result = opening.OverclockStartNativeTests.legacy_runner(
                fixture, False, *scenes, flag=opening.START, on_send=inspect_send, on_capture=inspect_capture)
        if stop_at_start:
            self.assertEqual((result.report['status'], len(result.packets), start_at_send), ('stopped', 5, []))
            self.assertIn('本次操作已停止', result.report['error'])
            run_dir = Path(result.report['run_dir'])
            flow = json.loads((run_dir / 'currency-flow.json').read_bytes())
            node, = run_dir.glob('currency-node-*.json')
            pending = json.loads(node.read_bytes())
            self.assertEqual((flow['actions'][-1]['status'], pending['action_status']), ('pending', 'pending'))
            self.assertFalse(pending.get('start_dispatched', False))
            self.assertEqual(fixture.session.read_bytes(), opening_bytes)
            return
        self.assertEqual(sent, [(name, "pending") for name in (
            "advance_boss_preview", "advance_plane", "confirm_environment",
            "collect_loot", "collect_loot", "run_current_node",
        )], result.report["error"])
        boss_click, plane_click, confirm_click, gray_click, blue_click, start_click = result.packets
        fixture.assert_packet_target(boss_click, preview, "下一步")
        fixture.assert_packet_target(plane_click, plane, "点击空白处继续")
        fixture.assert_packet_target(confirm_click, insurance, "确认")
        for packet, (x, y, _, _) in ((gray_click, GRAY), (blue_click, BLUE)):
            x, y = x / 2560, y / 1440
            point = Scene([Token("晶矿", 1., (x - .01, y - .01, x + .01, y + .01))])
            fixture.assert_packet_target(packet, point, "晶矿")
        fixture.assert_packet_target(start_click, blue_delivered, "出战")

        (flow, node), = start_at_send
        data = json.loads(flow.read_bytes())
        preflight = data["first_node_preflight"]
        self.assertEqual({(entry["zone"], entry["slot"], entry["name"]) for entry in preflight["team"]}, set(roster))
        gold, battery = preflight["opening_drops"]
        self.assertEqual((gold["kind"], gold["value"], battery["kind"], battery["value"]),
                         ("gold", 2, "battery", list(BATTERY_POINT)))
        for receipt in (gold, battery, preflight):
            first, second = receipt["feedback"]
            self.assertLess(first["captured_at"], second["captured_at"])
            self.assertNotEqual(first["screenshot"], second["screenshot"])
        self.assertFalse(data["completion_verified"])
        self.assertEqual(fixture.session.read_bytes(), opening_bytes)
        if verify_lock:
            (replacement, proof, original), = locked_proofs
            fixture.assert_released(replacement, proof, original)
        return SimpleNamespace(result=result, node=json.loads(node.read_bytes()), flow=data,
                               run_dir=node.parent, after_send=after_send, actual_times=real_times,
                               prefix_count=len(prefix))

    def test_verified_current_deployments_and_drops_authorize_one_native_start(self):
        run = self.run_started_node(verify_lock=True)
        self.assertEqual((run.result.code, run.result.report["status"], run.result.captures),
                         (1, "stopped", run.prefix_count + 1), run.result.report["error"])
        self.assertTrue(run.node["start_dispatched"])
        self.assertEqual(run.node["action_status"], "pending")
        self.assertFalse(run.node["node_verified"])

    def test_f10_after_the_last_history_check_preserves_both_pending_intents(self):
        self.run_started_node(stop_at_start=True)

    def assert_dispatched(self, run):
        first = run.after_send[0]
        self.assertIs(first["start_dispatched"], True)
        self.assertEqual(first["action_status"], "pending")
        stamp = first["dispatched_at"]
        self.assertLess(first["first_node_preflight"]["feedback"][-1]["captured_at"], stamp)
        self.assertEqual(run.node["dispatched_at"], stamp)
        self.assertIs(run.node["completion_verified"], False)
        self.assertIs(run.node["next_node_verified"], False)
        return stamp

    def assert_feedback_pair(self, run, key, state, after):
        first, second = run.node[key]
        self.assertEqual((first["state"], second["state"]), (state, state))
        self.assertLess(after, first["captured_at"])
        self.assertLess(first["captured_at"], second["captured_at"])
        self.assertNotEqual(first["screenshot"], second["screenshot"])
        for proof in (first, second):
            path = Path(proof["screenshot"]).resolve(strict=True)
            self.assertTrue(path.is_relative_to(run.run_dir))
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), proof["sha256"])
        return second["captured_at"]

    def test_native_start_observes_stable_battle_and_victory_without_continuing(self):
        second = changed_token(victory(), "继续挑战", "继续挑战", score=.86)
        run = self.run_started_node(synthetic_battle(), synthetic_battle(), victory(), second)
        sent_at = self.assert_dispatched(run)
        self.assertEqual((run.result.code, run.result.report["status"], run.result.captures),
                         (1, "partial", run.prefix_count + 4), run.result.report["error"])
        persisted_battle = run.after_send[2]
        self.assertEqual(persisted_battle["action_status"], "battle_observed")
        self.assertIs(persisted_battle["battle_observed"], True)
        self.assertIs(persisted_battle["result_observed"], False)
        self.assertEqual(persisted_battle["battle_feedback"], run.node["battle_feedback"])
        battle_at = self.assert_feedback_pair(run, "battle_feedback", "battle", sent_at)
        self.assert_feedback_pair(run, "result_feedback", "victory", battle_at)
        self.assertEqual(run.node["action_status"], "verified")
        self.assertIs(run.node["result_observed"], True)
        self.assertIs(run.node["node_verified"], True)
        self.assertEqual(run.node["auto_state"], "unknown")
        self.assertEqual(run.node["remaining_hp"], 100)
        self.assertEqual(run.flow["action_status"], "node_verified")
        self.assertIs(run.flow["actions"][-1]["node_verified"], True)

    def test_two_victory_frames_without_stable_battle_only_observe_result(self):
        run = self.run_started_node(victory(), victory())
        sent_at = self.assert_dispatched(run)
        self.assertEqual(run.result.captures, run.prefix_count + 2)
        self.assert_feedback_pair(run, "result_feedback", "victory", sent_at)
        self.assertIs(run.node["result_observed"], True)
        self.assertIs(run.node["battle_observed"], False)
        self.assertIs(run.node["node_verified"], False)
        self.assertEqual(run.node["action_status"], "unknown")

    def test_f10_after_the_last_history_check_keeps_the_existing_battle_receipt(self):
        hold = LegacyFirstNode._hold_input_sources

        def sources(workflow, stack, *proofs, frame=None):
            reader, unchanged = hold(workflow, stack, *proofs, frame=frame)
            if frame is not None or len(proofs) != 4:
                return reader, unchanged

            def check_then_stop():
                unchanged()
                windows.user32.GetAsyncKeyState.side_effect = [1] + [0] * 120

            return reader, check_then_stop

        with patch.object(LegacyFirstNode, '_hold_input_sources', sources):
            run = self.run_started_node(synthetic_battle(), synthetic_battle(), victory(), victory())
        self.assertEqual((run.result.report['status'], run.node['action_status']), ('stopped', 'battle_observed'))
        self.assertTrue(run.node['battle_observed'])
        self.assertFalse(run.node['result_observed'])
        self.assertEqual(len(run.result.packets), 6)

    def test_other_node_battle_stops_before_a_later_matching_result(self):
        run = self.run_started_node(synthetic_battle("1-2"), victory(), victory())
        self.assert_dispatched(run)
        self.assertEqual(run.result.captures, run.prefix_count + 1)
        self.assertEqual(run.node["action_status"], "unknown")
        self.assertIn("异节点", run.node["reason"])
        self.assertIs(run.node["battle_observed"], False)
        self.assertIs(run.node["result_observed"], False)
        self.assertIs(run.node["node_verified"], False)

    def test_conflicting_victory_node_keeps_battle_only_and_stops(self):
        run = self.run_started_node(synthetic_battle(), synthetic_battle(),
                                    victory(conflicting=True), victory(), victory())
        sent_at = self.assert_dispatched(run)
        self.assertEqual(run.result.captures, run.prefix_count + 3)
        self.assert_feedback_pair(run, "battle_feedback", "battle", sent_at)
        self.assertEqual(run.node["action_status"], "unknown")
        self.assertIn("冲突", run.node["reason"])
        self.assertIs(run.node["battle_observed"], True)
        self.assertIs(run.node["result_observed"], False)
        self.assertIs(run.node["node_verified"], False)

    def test_repeated_timestamp_never_creates_a_stable_battle_pair(self):
        run = self.run_started_node(synthetic_battle(), synthetic_battle(), victory(), victory(),
                                    repeat_timestamps=(0, 1))
        sent_at = self.assert_dispatched(run)
        first, second = run.actual_times
        self.assertLess(sent_at, first)
        self.assertLess(first, second)
        self.assertEqual(run.result.captures, run.prefix_count + 4)
        self.assertIs(run.node["battle_observed"], False)
        self.assertFalse(run.node.get("battle_feedback"))
        self.assertIs(run.node["result_observed"], True)
        self.assert_feedback_pair(run, "result_feedback", "victory", sent_at)
        self.assertIs(run.node["node_verified"], False)
        self.assertEqual(run.node["action_status"], "unknown")

    def test_victory_retry_rechecks_locked_result_pngs_and_preserves_battle_receipt(self):
        fixture = self.fixture
        runs = fixture.root / "runs"
        attempts, conflicts, changed = [], [], []

        def replace_victory(source, destination):
            destination = Path(destination)
            if destination.parent.parent != runs or not destination.name.startswith("currency-node-"):
                return opening.REPLACE(source, destination)
            proposal = json.loads(source.read_bytes())
            if not proposal.get("result_observed"):
                return opening.REPLACE(source, destination)

            attempts.append(destination)
            self.assertEqual(len(attempts), 1, "changed result evidence must stop before another replace")
            before = destination.read_bytes()
            published = json.loads(before)
            self.assertEqual(published["action_status"], "battle_observed")
            self.assertTrue(published["battle_observed"])
            self.assertFalse(published["result_observed"])

            first, second = (Path(proof["screenshot"]) for proof in proposal["result_feedback"])
            first_edit = fixture.alternate("victory-first-replacement.png", second.read_bytes())
            second_edit = fixture.alternate("victory-second-replacement.png", first.read_bytes())
            first_original = fixture.assert_ntfs_denies_replace(first_edit, first)
            second_original = fixture.assert_ntfs_denies_replace(second_edit, second)
            with storage.hold_read_sources((destination,)):
                try:
                    opening.REPLACE(source, destination)
                except OSError as error:
                    self.assertIn(error.winerror, opening.SHARING_ERRORS)
                    self.assertEqual(destination.read_bytes(), before)
                    self.assertTrue(source.is_file())
                    conflicts.append((destination, before, first, first_edit, first_original, second, second_original))
                    raise
            self.fail("NTFS allowed replacement of a node ledger held for shared read")

        def replace_png_between_attempts(delay):
            self.assertEqual(delay, storage.REPLACE_RETRY_DELAYS[0])
            self.assertFalse(changed)
            (destination, before, first, first_edit, first_original, _, _), = conflicts
            self.assertTrue(first.resolve(strict=True).is_relative_to(runs))
            self.assertEqual(first.read_bytes(), first_original)
            alternate = first_edit.read_bytes()
            opening.REPLACE(first_edit, first)
            self.assertEqual(first.read_bytes(), alternate)
            self.assertEqual(destination.read_bytes(), before)
            changed.append(alternate)
            fixture.advance(delay)

        with (
            patch.object(Path, "replace", replace_victory),
            patch.object(storage, "time", SimpleNamespace(sleep=replace_png_between_attempts)),
        ):
            run = self.run_started_node(synthetic_battle(), synthetic_battle(), victory(), victory())
        sent_at = self.assert_dispatched(run)
        (destination, before, first, _, _, second, second_original), = conflicts
        alternate, = changed
        self.assertEqual(attempts, [destination])
        self.assertEqual(destination.read_bytes(), before)
        self.assertEqual(first.read_bytes(), alternate)
        self.assertEqual(second.read_bytes(), second_original)
        self.assertEqual(run.result.code, 1)
        self.assertRegex(run.result.report["error"], "证据|截图")
        self.assert_feedback_pair(run, "battle_feedback", "battle", sent_at)
        self.assertTrue(run.node["battle_observed"])
        self.assertFalse(run.node["result_observed"])
        self.assertFalse(run.node["node_verified"])
        self.assertNotIn("result_feedback", run.node)

    def test_f10_during_result_observation_preserves_the_published_battle_pair(self):
        queried = []

        def held_f10(key):
            if key == 0x79:
                queried.append(key)
                return 0x8000
            return 0

        def press_after_battle(record):
            if record["battle_observed"]:
                windows.user32.GetAsyncKeyState.side_effect = held_f10

        run = self.run_started_node(synthetic_battle(), synthetic_battle(), victory(), victory(),
                                    on_feedback=press_after_battle)
        sent_at = self.assert_dispatched(run)
        self.assertTrue(queried)
        self.assertEqual(run.result.report["status"], "stopped", run.result.report["error"])
        self.assertLessEqual(run.result.captures, run.prefix_count + 4)
        self.assert_feedback_pair(run, "battle_feedback", "battle", sent_at)
        self.assertEqual(run.node["action_status"], "battle_observed")
        self.assertIs(run.node["battle_observed"], True)
        self.assertIs(run.node["result_observed"], False)
        self.assertIs(run.node["node_verified"], False)

    def test_unresolved_older_node_child_blocks_before_window_access(self):
        fixture = self.fixture
        root = fixture.open_match()
        previous = fixture.runs / "historical-node" / "currency-node-4.json"
        previous.parent.mkdir()
        original = json.dumps(dict(mode="single_node_test", action="start_node", origin_node="1-1",
                                   start_dispatched=True, node_verified=False, action_status="pending",
                                   completion_verified=False, gameplay_enabled=False)).encode("utf-8")
        previous.write_bytes(original)
        outcome = opening.OverclockStartNativeTests.legacy_runner(fixture, False, opening.boss(), flag=opening.START)
        fixture.assert_preflight_veto(outcome)
        self.assertIn("出战记录待核对", outcome.report["error"])
        self.assertEqual(previous.read_bytes(), original)
        self.assertEqual(fixture.session.read_bytes(), root)
