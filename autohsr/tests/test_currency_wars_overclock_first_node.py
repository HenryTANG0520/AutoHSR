"""A0 first-node evidence and bounded legacy Runner inputs with a fake window."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr import windows
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
        return preparation.with_account(scene.tokens, image=image)

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

    def replay_current_deployments_and_drops(self, *, stop_at_start=False):
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
        scenes = (
            preview, plane, plane, insurance, insurance, no_units, no_units,
            first_unit, first_unit, second_unit, second_unit, full, full,
            gray_delivered, gray_delivered, gray_delivered,
            blue_delivered, blue_delivered, blue_delivered, blue_delivered,
        )
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

        sent, start_at_send = [], []

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
            preflight = data["first_node_preflight"]
            self.assertEqual((preflight["status"], preflight["node"]), ("verified", "1-1"))
            first, second = preflight["feedback"]
            self.assertLess(first["captured_at"], second["captured_at"])
            proof = Path(first["screenshot"])
            replacement = fixture.alternate("changed-first-node-preflight.png", b"synthetic replacement")
            original = fixture.assert_ntfs_denies_replace(replacement, proof)
            self.assertEqual(hashlib.sha256(original).hexdigest(), first["sha256"])
            start_at_send.append((flow, node, proof, replacement, original))

        def stop_after_start(_number):
            if start_at_send:
                raise Stopped("synthetic stop after the native 1-1 start")

        finish = LegacyFirstNode._finish_native_check

        def final_history_check(workflow, scene, unchanged, *args, **kwargs):
            def check_then_stop():
                unchanged()
                if stop_at_start and workflow.flow['actions'][-1]['action'] == 'run_current_node':
                    windows.user32.GetAsyncKeyState.side_effect = [1] + [0] * 120

            return finish(workflow, scene, check_then_stop, *args, **kwargs)

        with (
            patch("autohsr.currency_wars_roster.next_candidate", side_effect=candidate),
            patch("autohsr.currency_wars_roster.deploy_candidate", side_effect=deploy),
            patch("autohsr.currency_wars_equipment.equipment_fields", return_value=()),
            patch.object(LegacyFirstNode, '_finish_native_check', final_history_check),
        ):
            result = opening.OverclockStartNativeTests.legacy_runner(
                fixture, False, *scenes, flag=opening.START, on_send=inspect_send, on_capture=stop_after_start)
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
        self.assertEqual((result.code, result.report["status"], result.captures),
                         (1, "stopped", len(scenes) + 1), result.report["error"])
        self.assertEqual(sent, [(name, "pending") for name in (
            "advance_boss_preview", "advance_plane", "confirm_environment",
            "collect_loot", "collect_loot", "run_current_node",
        )])
        boss_click, plane_click, confirm_click, gray_click, blue_click, start_click = result.packets
        fixture.assert_packet_target(boss_click, preview, "下一步")
        fixture.assert_packet_target(plane_click, plane, "点击空白处继续")
        fixture.assert_packet_target(confirm_click, insurance, "确认")
        for packet, (x, y, _, _) in ((gray_click, GRAY), (blue_click, BLUE)):
            x, y = x / 2560, y / 1440
            point = Scene([Token("晶矿", 1., (x - .01, y - .01, x + .01, y + .01))])
            fixture.assert_packet_target(packet, point, "晶矿")
        fixture.assert_packet_target(start_click, blue_delivered, "出战")

        (flow, node, proof, replacement, original), = start_at_send
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
        final_node = json.loads(node.read_bytes())
        self.assertTrue(final_node["start_dispatched"])
        self.assertEqual(final_node["action_status"], "pending")
        self.assertFalse(final_node["node_verified"])
        self.assertFalse(data["completion_verified"])
        self.assertEqual(fixture.session.read_bytes(), opening_bytes)
        fixture.assert_released(replacement, proof, original)

    def test_verified_current_deployments_and_drops_authorize_one_native_start(self):
        self.replay_current_deployments_and_drops()

    def test_f10_after_the_last_history_check_preserves_both_pending_intents(self):
        self.replay_current_deployments_and_drops(stop_at_start=True)
