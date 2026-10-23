from __future__ import annotations

import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport, Scene, TaskResult, Token, normalize
from autohsr.policy import guard_click
from autohsr.workflows import DailyWorkflow


TEST_DIR = Path(__file__).resolve().parent

# Real control-only pixels from three locally observed frames. The small crops
# omit account information and make regressions independent of the runs folder.
REAL_REFILL_PATCHES = (
    {
        "name": 'on',
        "box": (0.85, 0.7425925925925926, 0.9401041666666666, 0.7722222222222223),
        "origin": (3571, 1588),
        "png": (
            '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'
            'BZfdZHPmSRuP33Qcxxgb2zWd9nici2PPn3hunPy4XHsy31yx56q86m/2XnP+aKRRUYkooU9ccP23vvCDhogQjcGddDrdA0l0'
            'JIVizfy8EMtMIxrTSGDAiJ6waQSYgQBh03Oms2ebxhxAtoF3vuvdP/qjPzYejwFBlCKJ2cwBTjzxpI//3ce2bt1C76Mf/di3'
            'ffu/ByKKpOhJSLKd6cyamUyIlcRqBPjs0zb+2o8/5Fsfehqz2Fx0xc7bbl+cnyv3PHPLqATHmEynXdPjcS6OHet3HHfG4+qW'
            'B/HNVXZ+eu9XP1x3Xzs3itEoSiikn3vdJ3/vLy4SHQE26ezY2AbTi46kKBKj0RoxMI0AMcU0MstsQKIxjUTHppO9WitTzDLZ'
            '3rVr14Mf/JCrrr6GnqRSCh3TiCU2AmQOcK973esvP/C+hYUFeu9+93t/4OnPACIKICkixMCQWW0zIWYQ0zRAcNyaeNHT7/uT'
            'Tztnfq4wi83nL75hcZybNqy56ymbJY4pNmnXmuPqcfXYZd0p53HS471mM98s2nczV3/49is/MVIdlRgVlRK37tr3hJ/+y4uv'
            'vs0GhA3YTjc0lhSSIiSkEIxGawAzECAwBtETmI6xANEYI9EYBIhOZtrOdGbaZopZpiuuuOIZz3z2+Z/9LGCa0aiAABsBojGm'
            'kcwBnvKUp7zh9143NzdH73Wve/0LXvgi2xGFZZJYZidTxGyiJwmIkBRqEnjSeaf8yo896G6nbmIVN916x2VX32pzwpa1p56w'
            'IHHssEk70+Oai2OPa/q47Rvv8rjxlgehwjeB62jnp2+79CPsuXZUYm4UJVRKvPOjl/6nV//T7XeM03RsOrZZJhFSlFAHGQSj'
            'uTWATUeAaIxpRE9gjAGJZcI0AtMxznSt1T1WMsv03d/9vR/68N8AAoMUpQQHselZorGMJT7w/vc99KEPYdnznv+Tf/gHb0lb'
            'CmYwA4EZiINIAgERkkJCDWBgYd2aVz3/vO961JklxCquuXH3ldfvBk7YsvbUExYkjhE2tmu6Zo6rx+NcrFq3496jM74tjzuJ'
            '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'
            'AElFTkSuQmCC'
        ),
    },
    {
        "name": 'off_bright',
        "box": (0.8510416666666667, 0.7453703703703703, 0.9390625, 0.7703703703703704),
        "origin": (3571, 1588),
        "png": (
            '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'
            'w4/4/jTndz744OOPPoliE4xKKjbxvZ1OT1jiIARUYMX3JQ5C3JEb9Xw+jyHoW8/e4U7cqBycc3LjguyUl6VD5Y7co44hr4pA'
            'QoiDgECxUVoQsAKaE/Wzn312Pp+VCqjE8/n8+S98/k/+9E//wi/8/J/5M//u+XzmB/cv/sX/+Y/+8T/6p//0f/vtf/WvPn3+'
            'KbgBFHADqPzgihYqdmM4hrxiXgoqXiKX55tPP/n4k+eXC99TBMrVhx9+9J3vfACxiIhspKg4yCGQh87nJxzipgMV91S8VrxM'
            'btQxxuk0VNC3nr3DAwHqGENkN+eEUHZjyGu4DIiDhXKPykuKjVIByo08VFQCQs2asznn6XR++7NvnZ+cgUqMxhjim2++8aM/'
            '9qN//I//8T/3537mp//tn/59v+9Lp9OJ7+Xf/Jt/82u/9s//l6985dd+7Z//xte//jvf+lZNUEABFVD5XZjBnEEFjOEYg5fE'
            '7MA93uH7EshV9fHHH3/rW98RElARAQWMSOROxEF54Xx+wiFiESKEioqbueNx8YDcM3anMVDBt569w80YA3KDiAoqNStuVO4p'
            'RAc6IKDYCCE7ZVNslE0hIB3YjAEIyE55RQEB1dxcZgtPnjx59uyN85MnKiBuWHKMN9988w/+gT/4pS998ctf/vKPf/mP/tiP'
            '/tiXvvSld99956233jo/eTIvl48++uib3/zmb//2v/7GN77x67/+f3/1a199//33v/Evv/Gtb397zgmBAgqogMrvTtENMJTh'
            'QOS+ojln8ZB3+P7NOT/48KPvfOcDdupQVHYqxCJ34gE5nM9PY5FiUQoQ4ioiYM42c86Kl8UDcs/YncbADb717B1uzqeTww2k'
            'siuVq2IjIFfFlbILKK6EkJ1SbJTipjm7AsZwjMGNgHIVyFU3c3a5XCAiPJ9Pz95648nTp+fTCRXiqiabWVKBhzEcYwAV0A03'
            'AgooIKCyU/ndKboBFHGMgdxXdMND3uH78fz55cMPPvjwo48v80IqYwyHw8FGQG7kZbHIndP5KUsKsQixaPFQm8tlbioeiJfJ'
            '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'
            'AAAAAElFTkSuQmCC'
        ),
    },
    {
        "name": 'off_dark',
        "box": (0.8505208333333333, 0.7425925925925926, 0.9390625, 0.7722222222222223),
        "origin": (3571, 1588),
        "png": (
            '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'
        ),
    },
)


def token(text: str, x: float, y: float, score: float = 0.95) -> Token:
    return Token(text, score, (x - 0.01, y - 0.01, x + 0.01, y + 0.01))


class FakeContext:
    """A deterministic UI that records inputs and never touches Windows."""

    def __init__(self, scenes: list[Scene], settings: Settings | None = None):
        self.settings = settings or Settings(stamina_limit=60, use_support=False,
                                            allow_stamina_spend=True, battle=True)
        self.report = RunReport()
        self.scenes = scenes
        self.index = 0
        self.clicks: list[str | tuple[float, float]] = []
        self.click_targets: list[Token | tuple[float, float]] = []
        self.click_scenes: list[Scene] = []
        self.keys: list[str] = []
        self.messages: list[str] = []
        self.evidence_labels: list[str] = []
        self.snapshot_count = 0
        self.template_matches: dict[str, list[tuple[float, float, float]]] = {}
        self.template_calls: list[tuple[str, tuple[float, float, float, float]]] = []
        self.moves: list[tuple[float, float]] = []
        self.scrolls: list[int] = []

    def checkpoint(self) -> None:
        pass

    def snapshot(self) -> Scene:
        self.snapshot_count += 1
        return self.scenes[self.index]

    def _advance(self) -> None:
        self.index = min(self.index + 1, len(self.scenes) - 1)

    def click(self, scene: Scene, target: Token | tuple[float, float]) -> None:
        if scene is not self.snapshot():
            raise AssertionError("Attempted input against a stale scene")
        self.clicks.append(target.text if isinstance(target, Token) else target)
        self.click_targets.append(target)
        self.click_scenes.append(scene)
        self._advance()

    def key(self, key: str) -> None:
        self.keys.append(key)
        self._advance()

    def sleep(self, seconds: float) -> None:
        pass

    def scroll(self, amount: int) -> None:
        self.scrolls.append(amount)
        self._advance()

    def move(self, scene: Scene, point: tuple[float, float]) -> None:
        if scene is not self.scenes[self.index]:
            raise AssertionError("Attempted move against a stale scene")
        self.moves.append(point)

    def template(self, scene: Scene, name: str, roi, threshold=0.9):
        self.template_calls.append((name, roi))
        matches = [match for match in self.template_matches.get(name, [])
                   if roi[0] <= match[0] <= roi[2] and roi[1] <= match[1] <= roi[3]
                   and match[2] >= threshold]
        return max(matches, key=lambda match: match[2]) if matches else None

    def wait(self, predicate, timeout=30, description="等待页面") -> Scene:
        while True:
            scene = self.snapshot()
            if predicate(scene):
                return scene
            if self.index == len(self.scenes) - 1:
                raise AutomationError(f"Fake UI did not reach: {description}")
            self._advance()

    def log(self, message: str) -> None:
        self.messages.append(message)

    def evidence(self, scene: Scene, label: str) -> None:
        self.evidence_labels.append(label)


def quick_refill_image(track: str, knob: str | None):
    """Synthetic switch pixels, independent of real screenshots and input APIs."""
    import numpy as np

    image = np.zeros((540, 960, 3), dtype=np.uint8)
    left, right = round(0.947 * 960), round(0.979 * 960)
    top, bottom = round(0.743 * 540), round(0.771 * 540)
    patch = image[top:bottom, left:right]
    patch[:] = {"gold": (0, 190, 240), "neutral": (110, 110, 110),
                "dark": (0, 0, 0)}[track]
    half = patch.shape[1] // 2
    if knob == "left":
        patch[:, :half] = (255, 255, 255)
    elif knob == "right":
        patch[:, half:] = (255, 255, 255)
    return image


def pill_refill_image(track: str = "neutral", knobs: tuple[str, ...] = ("left",)):
    """Observed switch morphology: a dark track, thin border and round knob."""
    import cv2
    import numpy as np

    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    patch = image[round(0.743 * 1080):round(0.771 * 1080),
                  round(0.947 * 1920):round(0.979 * 1920)]
    patch[:] = (18, 18, 18)
    height, width = patch.shape[:2]
    middle, radius = height // 2, height // 3
    ends = {"left": (radius + 1, middle), "right": (width - radius - 2, middle)}
    if track == "dark":
        patch[:] = (25, 25, 25)
    else:
        cv2.line(patch, ends["left"], ends["right"], (80, 80, 80), radius * 2 + 2)
        fill = (35, 35, 35) if track == "neutral" else (0, 190, 240)
        cv2.line(patch, ends["left"], ends["right"], fill, radius * 2 - 2)
    for knob in knobs:
        cv2.circle(patch, ends[knob], radius, (246, 246, 246), -1)
    return image


def calyx_scene(available: int = 120, cost: int = 60, rounds: int = 6,
                location: str | None = "城郊雪原", quick_refill: str = "off") -> Scene:
    texts = [
        token("拟造花萼", 0.1, 0.05),
        token("回忆之蕾", 0.2, 0.2),
        token("挑战", 0.9, 0.92),
        token(str(cost), 0.7, 0.92),
        token(f"挑战次数{rounds}", 0.7, 0.8),
        token(f"{available}/300", 0.8, 0.1),
        token("快捷补充开拓力", 0.93, 0.757),
    ]
    if location:
        texts.append(token(location, 0.3, 0.26))
    image = pill_refill_image() if quick_refill == "off" else (
        pill_refill_image("gold", ("right",)) if quick_refill == "on" else None)
    return Scene(texts, image=image)


def assignments_scene(count: int = 4, claim: str | None = None,
                      settled: bool = False) -> Scene:
    texts = [token("委托", 0.1, 0.05), token("每小时奖励", 0.3, 0.28),
             token("已进行0/30h", 0.78, 0.56), token("进行中的委托", 0.22, 0.76),
             token(f"{count}/4", 0.46, 0.76), token("变更委托", 0.3, 0.9)]
    if settled:
        texts += [token("委托派遣中", 0.8, 0.76),
                  token("每小时可持续获得奖励帕！", 0.8, 0.84)]
    image = None
    if claim:
        import numpy as np

        texts.append(token("领取奖励", 0.83, 0.87))
        image = np.zeros((540, 960, 3), dtype=np.uint8)
        image[round(0.848 * 540):round(0.892 * 540),
              round(0.755 * 960):round(0.905 * 960)] = (
                  (0, 190, 240) if claim == "enabled" else (110, 110, 110))
    return Scene(texts, image=image)


def survival_guide(rows: list[tuple[str, float]]) -> Scene:
    texts = [token("星际和平指南", 0.08, 0.05), token("生存索引", 0.24, 0.05),
             token("拟造花萼（金）", 0.23, 0.3)]
    for place, y in rows:
        texts += [token("回忆之蕾", 0.5, y), token(place, 0.55, y + 0.04),
                  token("传送", 0.8, y)]
    return Scene(texts)


def train_supply_scene(remaining: str = "剩余：21天",
                       claim: str = "点击领取今日补给", sales: str | None = None) -> Scene:
    texts = [token("列车补给", 0.5, 0.071), token(remaining, 0.5, 0.120),
             token(claim, 0.5, 0.862)]
    if sales:
        texts.append(token(sales, 0.7, 0.85))
    return Scene(texts)


def daily_scene(activity: str, marks: int = 0, marks_y: float = 0.32) -> Scene:
    texts = [token("星际和平指南", 0.08, 0.05),
             token("每日实训", 0.24, 0.05), token(activity, 0.5, 0.28)]
    texts.extend(token("已领取", 0.24 + i * 0.15, marks_y) for i in range(marks))
    return Scene(texts)


def support_marker(scene: Scene, color: str = "green") -> Scene:
    """An isolated party support badge, not a user's character screenshot."""
    import numpy as np

    badge = token("支援", 0.88, 0.54)
    image = np.full((1080, 1920, 3), 80, dtype=np.uint8)
    x1, y1, x2, y2 = badge.box
    # Color evidence belongs to the badge, rather than the whole panel.
    fill = (65, 150, 75) if color == "green" else (100, 100, 100)
    image[round((y1 - .005) * 1080):round((y2 + .005) * 1080),
          round((x1 - .008) * 1920):round((x2 + .008) * 1920)] = fill
    return Scene([*scene.tokens, badge], image=image)


def support_picker(rows: list[tuple[str, float, bool]] | None = None,
                   marker: str | None = None) -> Scene:
    # The positions reflect the observed 4.6 layout; names are invented.
    texts = [token("角色列表", .088, .082), token("支援角色", .223, .082),
             token("仅查看好友", .093, .131), token("确认", .878, .917)]
    for name, y, friend in ([("甲", .203, True)] if rows is None else rows):
        texts.extend([token(name, .12, y), token("等级80", .052, y + .077),
                      token("示例简介", .16, y + .04)])
        if friend:
            texts.append(token("好友", .265, y))
    scene = Scene(texts)
    return support_marker(scene, marker) if marker else scene


def support_team(marker: str | None = None) -> Scene:
    scene = Scene([token("队伍", .1, .05), token("支援", .88, .87),
                   token("开始挑战", .88, .92)])
    return support_marker(scene, marker) if marker else scene


class RecognitionTests(unittest.TestCase):
    def test_normalize_ignores_ocr_spacing_and_common_punctuation(self) -> None:
        self.assertEqual(normalize(" 领取： 每日·奖励！\n"), "领取每日奖励")
        self.assertEqual(normalize(" AUTO (ON) "), "autoon")

    def test_find_respects_button_region(self) -> None:
        outside = token("领取", 0.1, 0.2)
        inside = token("领取", 0.8, 0.8)
        scene = Scene([outside, inside])
        self.assertIs(scene.find("领取", roi=(0.6, 0.6, 1, 1), exact=True), inside)
        self.assertIsNone(scene.find("领取", roi=(0.3, 0.3, 0.5, 0.5)))

    def test_exact_match_rejects_different_action_text(self) -> None:
        scene = Scene([token("全部领取", 0.8, 0.8), token("未领取", 0.5, 0.5)])
        self.assertFalse(scene.has("领取", exact=True))
        self.assertTrue(scene.has("全部领取", exact=True))

    def test_exact_label_wins_over_higher_confidence_substring(self) -> None:
        exact = token("领取", 0.8, 0.8, score=0.75)
        scene = Scene([token("领取全部奖励", 0.5, 0.5, score=0.99), exact])
        self.assertIs(scene.find("领取"), exact)

    def test_equal_labels_choose_higher_confidence_candidate(self) -> None:
        stronger = token("再次挑战", 0.8, 0.8, score=0.97)
        scene = Scene([token("再次挑战", 0.5, 0.5, score=0.7), stronger])
        self.assertIs(scene.find(["再次挑战", "再来一次"], exact=True), stronger)

    def test_roi_uses_token_center_and_includes_boundary(self) -> None:
        edge = Token("按钮", 0.9, (0.125, 0.125, 0.375, 0.375))
        self.assertEqual(edge.center, (0.25, 0.25))
        self.assertTrue(edge.within((0.25, 0.25, 0.5, 0.5)))
        self.assertFalse(edge.within((0.26, 0.26, 0.5, 0.5)))

    def test_empty_scene_and_empty_search_are_safe(self) -> None:
        self.assertIsNone(Scene([]).find("领取"))
        self.assertIsNone(Scene([token("领取", 0.8, 0.8)]).find([]))
        self.assertIsNone(Scene([token("领取", 0.8, 0.8)]).find(""))


class SettingsTests(unittest.TestCase):
    def test_default_settings_are_valid(self) -> None:
        Settings().validate()

    def test_supported_parameter_boundaries(self) -> None:
        lower = Settings(stamina_limit=10, rounds=1, action_delay=0.3,
                         battle_timeout=60, ocr_confidence=0.4)
        upper = Settings(stamina_limit=240, rounds=6, action_delay=5,
                         battle_timeout=3600, ocr_confidence=0.99)
        lower.validate()
        upper.validate()

    def test_invalid_parameter_values_are_rejected(self) -> None:
        cases = {
            "stamina_limit": [0, 9, 15, 250, True, 120.0],
            "rounds": [0, 7, True, 3.0],
            "action_delay": [0.29, 5.01, float("nan"), float("inf"), True, "1", None],
            "battle_timeout": [59, 3601, float("nan"), float("inf"), True, "900", None],
            "ocr_confidence": [0.39, 1, float("nan"), float("inf"), True, "0.7", None],
            "game_path": ["game.exe", "StarRail.exe.old", None],
            "target_name": ["", " ", "蕾", None],
            "target_location": [None, 1, False],
        }
        for name, values in cases.items():
            for value in values:
                with self.subTest(parameter=name, value=value):
                    settings = Settings()
                    setattr(settings, name, value)
                    with self.assertRaises(ValueError):
                        settings.validate()

    def test_task_switches_require_actual_booleans(self) -> None:
        for name in ("use_support", "assignments", "battle", "allow_stamina_spend", "daily", "mail",
                     "battlepass", "auto_launch"):
            with self.subTest(parameter=name):
                settings = Settings()
                setattr(settings, name, 1)
                with self.assertRaises(ValueError):
                    settings.validate()

    def test_save_load_round_trip_preserves_user_choices(self) -> None:
        expected = Settings(target_name="以太之蕾", stamina_limit=80, rounds=4,
                            assignments=False, mail=True, action_delay=1.5)
        with tempfile.TemporaryDirectory(dir=TEST_DIR) as directory:
            path = Path(directory) / "config.json"
            expected.save(path)
            self.assertEqual(Settings.load(path), expected)
            self.assertIn("以太之蕾", path.read_text(encoding="utf-8"))
            self.assertFalse(path.with_suffix(".tmp").exists())

    def test_invalid_save_does_not_replace_existing_config(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_DIR) as directory:
            path = Path(directory) / "config.json"
            Settings(stamina_limit=80).save(path)
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                Settings(stamina_limit=15).save(path)
            self.assertEqual(path.read_bytes(), original)

    def test_load_missing_config_uses_defaults_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_DIR) as directory:
            path = Path(directory) / "missing.json"
            self.assertEqual(Settings.load(path), Settings())
            self.assertFalse(path.exists())

    def test_load_rejects_unknown_fields_and_invalid_settings(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_DIR) as directory:
            path = Path(directory) / "config.json"
            for data in ({"stamina_limti": 120}, {"stamina_limit": 15},
                         {"rounds": True}, {"battle": "true"}):
                with self.subTest(data=data):
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        Settings.load(path)

    def test_load_rejects_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory(dir=TEST_DIR) as directory:
            path = Path(directory) / "config.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(ValueError):
                Settings.load(path)


class ReportTests(unittest.TestCase):
    def test_new_report_never_claims_daily_completion(self) -> None:
        report = RunReport()
        self.assertEqual(report.status, "partial")
        self.assertFalse(report.daily_verified)
        self.assertEqual(report.stamina_spent, 0)

    def test_report_serializes_task_results(self) -> None:
        report = RunReport(results=[TaskResult("每日实训", "partial", "进度不足500")])
        data = report.to_dict()
        self.assertFalse(data["daily_verified"])
        self.assertEqual(data["results"][0]["status"], "partial")
        json.dumps(data, ensure_ascii=False)


class WorkflowSafetyTests(unittest.TestCase):
    def test_denied_stamina_spending_never_sends_inputs(self) -> None:
        context = FakeContext([calyx_scene()], settings=Settings(allow_stamina_spend=False))
        result = DailyWorkflow(context).battle()
        self.assertEqual(result.status, "skipped")
        self.assertEqual(context.snapshot_count, 0)
        self.assertEqual(context.clicks, [])
        self.assertEqual(context.keys, [])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_unknown_page_refuses_navigation_inputs(self) -> None:
        context = FakeContext([Scene([token("领取", 0.5, 0.8)])])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).ensure_main()
        self.assertEqual(context.clicks, [])
        self.assertEqual(context.keys, [])
        self.assertIn("unknown_navigation", context.evidence_labels)

    def test_verified_phone_menu_needs_no_blind_escape(self) -> None:
        phone = Scene([token("开拓等级", 0.8, 0.15), token("委托", 0.8, 0.6)])
        context = FakeContext([phone])
        self.assertIs(DailyWorkflow(context).ensure_main(), phone)
        self.assertEqual(context.keys, [])
        self.assertEqual(context.clicks, [])

    def test_deep_known_navigation_reaches_phone_after_five_escapes(self) -> None:
        phone = Scene([token("开拓等级", .8, .15), token("委托", .8, .6)])
        world = Scene([token("大世界提示", .5, .5)])
        context = FakeContext([support_picker(), support_team(), calyx_scene(),
                               survival_guide([("城郊雪原", .4)]), world, phone])
        context.template_matches["world_character"] = [(.965, .045, .99)]
        self.assertIs(DailyWorkflow(context).ensure_main(), phone)
        self.assertEqual(context.keys, ["esc"] * 5)
        self.assertEqual(context.clicks, [])

    def test_deep_navigation_stops_when_an_unknown_page_interrupts_the_chain(self) -> None:
        unknown = Scene([token("陌生弹窗", .1, .05)])
        phone = Scene([token("开拓等级", .8, .15), token("委托", .8, .6)])
        context = FakeContext([support_picker(), support_team(), unknown, phone])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).ensure_main()
        self.assertEqual(context.keys, ["esc", "esc"])
        self.assertIs(context.scenes[context.index], unknown)
        self.assertEqual(context.clicks, [])
        self.assertIn("unknown_navigation", context.evidence_labels)

    def test_known_navigation_loop_has_a_five_escape_limit(self) -> None:
        unchanged = Scene([token("生存索引", .1, .05)])
        context = FakeContext([unchanged])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).ensure_main()
        self.assertEqual(context.keys, ["esc"] * 5)
        self.assertEqual(context.clicks, [])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_existing_ready_settlement_can_return_to_phone_without_new_stamina(self) -> None:
        for status in ("挑战成功", "战斗失败"):
            with self.subTest(status=status):
                ready = Scene([token(status, .5, .5), token("退出关卡", .8, .9)])
                world = Scene([token("大世界提示", .5, .5)])
                phone = Scene([token("开拓等级", .8, .15), token("委托", .8, .6)])
                context = FakeContext([ready, world, phone])
                context.template_matches["world_character"] = [(.965, .045, .99)]
                self.assertIs(DailyWorkflow(context).ensure_main(), phone)
                self.assertEqual(context.clicks, ["退出关卡"])
                self.assertEqual(context.keys, ["esc"])
                self.assertEqual(context.report.stamina_spent, 0)
                self.assertNotIn("battle_success_1", context.evidence_labels)

    def test_incomplete_settlement_and_active_battle_cannot_be_escaped_as_navigation(self) -> None:
        for scene in (Scene([token("挑战成功", .5, .5)]),
                      Scene([token("战斗设置", .5, .5)]),
                      Scene([token("退出关卡", .8, .9)])):
            with self.subTest(text=scene.text):
                context = FakeContext([scene])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).ensure_main()
                self.assertEqual(context.clicks, [])
                self.assertEqual(context.keys, [])
                self.assertEqual(context.report.stamina_spent, 0)

    def test_insufficient_stamina_only_cancels_replenishment(self) -> None:
        calyx = calyx_scene()
        popup = Scene([token("开拓力补充", 0.5, 0.35),
                       token("取消", 0.4, 0.8), token("确认", 0.6, 0.8)])
        context = FakeContext([calyx, popup, calyx])
        result = DailyWorkflow(context).battle()
        self.assertEqual(result.status, "partial")
        self.assertEqual(context.clicks, ["挑战", "取消"])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_missing_cancel_never_clicks_replenishment_confirmation(self) -> None:
        popup = Scene([token("开拓力不足", 0.5, 0.35), token("确认", 0.6, 0.8)])
        context = FakeContext([calyx_scene(), popup])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).battle()
        self.assertEqual(context.clicks, ["挑战"])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_under_ten_stamina_never_starts_challenge(self) -> None:
        context = FakeContext([calyx_scene(available=9)])
        result = DailyWorkflow(context).battle()
        self.assertEqual(result.status, "partial")
        self.assertEqual(context.clicks, [])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_misread_cost_disagreeing_with_round_count_never_starts(self) -> None:
        context = FakeContext([calyx_scene(cost=10, rounds=6)],
                              settings=Settings(stamina_limit=10, rounds=1,
                                                use_support=False, allow_stamina_spend=True))
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).battle()
        self.assertEqual(context.clicks, [])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_missing_round_count_cannot_reuse_cost_as_second_evidence(self) -> None:
        scene = calyx_scene()
        scene.tokens = [value for value in scene.tokens if not value.text.startswith("挑战次数")]
        context = FakeContext([scene])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).battle()
        self.assertEqual(context.clicks, [])

    def test_budget_ten_starts_only_verified_single_round(self) -> None:
        team = Scene([token("队伍", 0.1, 0.05), token("开始挑战", 0.8, 0.9)])
        success = Scene([token("挑战成功", 0.5, 0.3), token("退出关卡", 0.8, 0.9)])
        context = FakeContext([calyx_scene(cost=10, rounds=1), team, success, Scene([])],
                              settings=Settings(stamina_limit=10, rounds=1,
                                                use_support=False, allow_stamina_spend=True))
        self.assertEqual(DailyWorkflow(context).battle().status, "ok")
        self.assertEqual(context.report.stamina_spent, 10)

    def test_start_button_without_verified_team_page_is_rejected(self) -> None:
        context = FakeContext([calyx_scene(), Scene([token("开始挑战", 0.8, 0.9)])])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).battle()
        self.assertEqual(context.clicks, ["挑战"])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_failed_battle_does_not_claim_success_or_count_stamina(self) -> None:
        team = Scene([token("队伍", 0.1, 0.05), token("开始挑战", 0.8, 0.9)])
        failed = Scene([token("战斗失败", 0.5, 0.3), token("退出关卡", 0.8, 0.9)])
        context = FakeContext([calyx_scene(), team, failed, Scene([])])
        result = DailyWorkflow(context).battle()
        self.assertEqual(result.status, "partial")
        self.assertEqual(context.clicks, ["挑战", "开始挑战", "退出关卡"])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_verified_battle_success_counts_cost_once(self) -> None:
        team = Scene([token("队伍", 0.1, 0.05), token("开始挑战", 0.8, 0.9)])
        success = Scene([token("挑战成功", 0.5, 0.3), token("退出关卡", 0.8, 0.9)])
        context = FakeContext([calyx_scene(), team, success, Scene([])])
        result = DailyWorkflow(context).battle()
        self.assertEqual(result.status, "ok")
        self.assertEqual(context.report.stamina_spent, 60)
        self.assertEqual(context.clicks.count("开始挑战"), 1)

    def test_result_exit_waits_for_the_exact_bottom_button_with_success_evidence(self) -> None:
        early = Scene([token("挑战成功", .5, .3)])
        ready = Scene([token("挑战成功", .5, .3), token("退出关卡", .8, .9)])
        context = FakeContext([early, ready, Scene([])])
        DailyWorkflow(context)._exit_result(early)
        self.assertEqual(context.clicks, ["退出关卡"])
        self.assertEqual(context.click_scenes, [ready])
        self.assertEqual(context.keys, [])

    def test_result_exit_does_not_click_unknown_or_unbound_exit_controls(self) -> None:
        early = Scene([token("挑战成功", .5, .3)])
        responses = [Scene([token("未知界面", .5, .3)]),
                     Scene([token("退出关卡", .8, .9)]),
                     Scene([token("挑战成功", .5, .3), token("退出关卡", .8, .4)]),
                     Scene([token("挑战成功", .5, .3), token("退出关卡再来一次", .8, .9)])]
        for response in responses:
            with self.subTest(text=response.text):
                context = FakeContext([early, response])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context)._exit_result(early)
                self.assertEqual(context.clicks, [])
                self.assertEqual(context.keys, [])

    def test_delayed_result_button_counts_the_successful_batch_once(self) -> None:
        early = Scene([token("挑战成功", .5, .3)])
        ready = Scene([token("挑战成功", .5, .3), token("退出关卡", .8, .9)])
        context = FakeContext([calyx_scene(cost=10, rounds=1), support_team(), early, ready, Scene([])],
                              Settings(stamina_limit=10, rounds=1, use_support=False))
        result = DailyWorkflow(context).battle()
        self.assertEqual(result.status, "ok")
        self.assertEqual(context.report.stamina_spent, 10)
        self.assertEqual(context.clicks, ["挑战", "开始挑战", "退出关卡"])
        self.assertEqual(context.evidence_labels.count("battle_success_1"), 1)

    def test_incomplete_daily_activity_never_claims_completion(self) -> None:
        for activity in ("400/500", "活跃度400", "500", "奖励500"):
            with self.subTest(activity=activity):
                context = FakeContext([daily_scene(activity, marks=5)])
                context.report.daily_verified = True
                result = DailyWorkflow(context).daily()
                self.assertEqual(result.status, "partial")
                self.assertFalse(context.report.daily_verified)
                self.assertEqual(context.clicks, [])

    def test_500_without_all_milestone_rewards_is_partial(self) -> None:
        for marks, marks_y in ((0, 0.32), (4, 0.32), (5, 0.7)):
            with self.subTest(marks=marks, marks_y=marks_y):
                context = FakeContext([daily_scene("500/500", marks=marks, marks_y=marks_y)])
                result = DailyWorkflow(context).daily()
                self.assertEqual(result.status, "partial")
                self.assertFalse(context.report.daily_verified)

    def test_500_with_five_verified_rewards_completes_daily(self) -> None:
        for activity in ("500/500", "活跃度500"):
            with self.subTest(activity=activity):
                context = FakeContext([daily_scene(activity, marks=5)])
                result = DailyWorkflow(context).daily()
                self.assertEqual(result.status, "ok")
                self.assertTrue(context.report.daily_verified)
                self.assertEqual(context.clicks, [])

    def test_each_milestone_template_requires_a_separate_slot(self) -> None:
        context = FakeContext([daily_scene("500/500")])
        context.template_matches["daily_completed"] = [
            (x, 0.3, 0.99) for x in (0.27, 0.43, 0.58, 0.72, 0.87)]
        result = DailyWorkflow(context).daily()
        self.assertEqual(result.status, "ok")
        self.assertTrue(context.report.daily_verified)
        regions = [roi for name, roi in context.template_calls if name == "daily_completed"]
        self.assertEqual(len(set(regions)), 5)
        for position, region in zip(context.template_matches["daily_completed"], regions):
            self.assertTrue(region[0] <= position[0] <= region[2])

    def test_one_completed_icon_cannot_prove_all_five_rewards(self) -> None:
        context = FakeContext([daily_scene("500/500")])
        context.template_matches["daily_completed"] = [(0.27, 0.3, 0.99)]
        result = DailyWorkflow(context).daily()
        self.assertEqual(result.status, "partial")
        self.assertFalse(context.report.daily_verified)
        self.assertEqual(context.clicks, [])

    def test_unknown_auto_battle_state_does_not_toggle_controls(self) -> None:
        scene = Scene([])
        context = FakeContext([scene])
        self.assertFalse(DailyWorkflow(context)._enable_auto(scene))
        self.assertEqual(context.clicks, [])
        self.assertEqual(context.keys, [])


class SupportSelectionTests(unittest.TestCase):
    @staticmethod
    def full_team_picker(rows: list[tuple[str, float, bool]]) -> Scene:
        scene = support_picker(rows)
        scene.tokens.append(token("队伍角色已满", .5, .278))
        return scene

    def test_explicit_full_team_then_fresh_next_friend_can_be_confirmed(self) -> None:
        rows = [("甲", .203, True), ("乙", .332, True)]
        initial = support_picker(rows)
        cleared = support_picker(rows)
        selected = support_picker(rows, marker="green")
        team = support_team("green")
        context = FakeContext([support_team(), initial, self.full_team_picker(rows),
                               cleared, selected, team])
        self.assertIs(DailyWorkflow(context)._support(context.snapshot()), team)
        self.assertEqual(context.clicks, ["支援", "好友", "好友", "确认"])
        self.assertEqual([round(t.center[1], 3) for t in context.click_targets[1:3]],
                         [.203, .332])
        self.assertIs(context.click_scenes[2], cleared)
        self.assertIs(context.click_targets[2], cleared.find("好友", (.235, .31, .29, .35), exact=True))
        self.assertEqual(context.keys, [])

    def test_all_full_team_candidates_are_attempted_once_with_a_visible_bound(self) -> None:
        rows = [("甲", .203, True), ("乙", .332, True), ("丙", .459, True)]
        scenes = [support_team(), support_picker(rows)]
        for index in range(len(rows)):
            scenes.append(self.full_team_picker(rows))
            if index + 1 < len(rows):
                # A newly seen fourth row cannot extend the initial retry bound.
                scenes.append(support_picker([*rows, ("新出现", .586, True)]))
        context = FakeContext(scenes)
        with self.assertRaises(AutomationError):
            DailyWorkflow(context)._support(context.snapshot())
        self.assertEqual(context.clicks, ["支援", "好友", "好友", "好友"])
        self.assertEqual([round(t.center[1], 3) for t in context.click_targets[1:]],
                         [.203, .332, .459])
        self.assertEqual(context.keys, [])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_unknown_or_unchanged_selection_feedback_never_tries_another_card(self) -> None:
        rows = [("甲", .203, True), ("乙", .332, True)]
        for response in (support_picker(rows), Scene([token("陌生弹窗", .5, .3)]),
                         Scene([token("队伍角色已满", .5, .278)])):
            with self.subTest(text=response.text):
                context = FakeContext([support_team(), support_picker(rows), response])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context)._support(context.snapshot())
                self.assertEqual(context.clicks, ["支援", "好友"])
                self.assertEqual(context.keys, [])

    def test_full_team_toast_must_clear_before_the_next_card_is_clicked(self) -> None:
        rows = [("甲", .203, True), ("乙", .332, True)]
        context = FakeContext([support_team(), support_picker(rows), self.full_team_picker(rows)])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context)._support(context.snapshot())
        self.assertEqual(context.clicks, ["支援", "好友"])

    def test_one_frame_full_team_feedback_is_consumed_before_waiting_again(self) -> None:
        rows = [("甲", .203, True), ("乙", .332, True)]
        transient = self.full_team_picker(rows)

        class ToastFadesContext(FakeContext):
            """Only the first capture sees the toast; later captures see its absence."""
            seen_toast = False

            def snapshot(self) -> Scene:
                if self.scenes[self.index] is transient and self.seen_toast:
                    self._advance()
                scene = super().snapshot()
                if scene is transient:
                    self.seen_toast = True
                return scene

            def wait(self, predicate, timeout=30, description="等待页面") -> Scene:
                # Without another input, the cleared list stays unchanged.
                # This prevents a future card's outcome leaking into the wait.
                scene = self.snapshot()
                if predicate(scene):
                    return scene
                raise AutomationError(f"Unchanged fresh capture: {description}")

        cleared = support_picker(rows)
        final = support_team("green")
        context = ToastFadesContext([support_team(), support_picker(rows), transient,
                                    cleared, support_picker(rows, marker="green"), final])
        self.assertIs(DailyWorkflow(context)._support(context.snapshot()), final)
        self.assertEqual(context.clicks, ["支援", "好友", "好友", "确认"])
        self.assertIs(context.click_scenes[2], cleared)
        self.assertEqual([round(t.center[1], 3) for t in context.click_targets[1:3]],
                         [.203, .332])

    def test_full_team_retry_rejects_noncentral_and_merged_ocr_text(self) -> None:
        rows = [("甲", .203, True), ("乙", .332, True)]
        variants = [("队伍角色已满", .12, .243), ("队伍角色已满", .85, .278),
                    ("队伍角色已满", .5, .70), ("队伍角色已满，请调整", .5, .278),
                    ("未提示队伍角色已满", .5, .278), ("队伍角色已满确认", .5, .278)]
        for text, x, y in variants:
            with self.subTest(text=text, point=(x, y)):
                response = support_picker(rows)
                response.tokens.append(token(text, x, y))
                context = FakeContext([support_team(), support_picker(rows), response])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context)._support(context.snapshot())
                self.assertEqual(context.clicks, ["支援", "好友"])
                self.assertEqual(context.keys, [])

    def test_next_card_must_still_have_the_original_fresh_identity(self) -> None:
        rows = [("甲", .203, True), ("乙", .332, True)]
        missing = support_picker(rows[:1])
        renamed = support_picker([rows[0], ("更名", .332, True)])
        different_level = support_picker(rows)
        different_level.tokens = [token("等级79", .052, .409)
                                  if t.text == "等级80" and abs(t.center[1] - .409) < .01 else t
                                  for t in different_level.tokens]
        for changed in (missing, renamed, different_level):
            with self.subTest(text=changed.text):
                context = FakeContext([support_team(), support_picker(rows),
                                       self.full_team_picker(rows), changed])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context)._support(context.snapshot())
                self.assertEqual(context.clicks, ["支援", "好友"])
                self.assertEqual(context.keys, [])

    def test_friend_card_can_have_a_single_letter_or_latin_nickname(self) -> None:
        for name in ("甲", "Friend7"):
            with self.subTest(name=name):
                picker = support_picker([(name, .203, True)])
                selected = support_picker([(name, .203, True)], marker="green")
                team = support_team("green")
                context = FakeContext([support_team(), picker, selected, team])
                self.assertIs(DailyWorkflow(context)._support(context.snapshot()), team)
                self.assertEqual(context.clicks, ["支援", "好友", "确认"])
                self.assertIs(context.click_targets[1], picker.find("好友", exact=True))
                self.assertNotIn("仅查看好友", context.clicks)

    def test_nonfriend_card_before_friend_does_not_win_selection(self) -> None:
        rows = [("陌生访客", .203, False), ("甲", .332, True)]
        picker = support_picker(rows)
        context = FakeContext([support_team(), picker,
                               support_picker(rows, marker="green"), support_team("green")])
        DailyWorkflow(context)._support(context.snapshot())
        self.assertAlmostEqual(context.click_targets[1].center[1], .332)
        self.assertEqual(context.clicks, ["支援", "好友", "确认"])

    def test_filter_and_unbound_friend_labels_never_authorize_selection(self) -> None:
        scenarios = {
            "filter_only": support_picker([]),
            "friend_outside_card": Scene([*support_picker([]).tokens,
                                           token("好友", .14, .13),
                                           token("甲", .12, .13), token("等级80", .052, .207)]),
            "no_portrait_level": Scene([*support_picker([]).tokens,
                                         token("好友", .265, .203), token("甲", .12, .203)]),
            "level_from_another_row": Scene([*support_picker([]).tokens,
                                              token("好友", .265, .203), token("甲", .12, .203),
                                              token("等级80", .052, .408)]),
            "description_only": Scene([*support_picker([]).tokens,
                                         token("好友", .265, .203), token("简介", .12, .243),
                                         token("等级80", .052, .280)]),
        }
        for name, picker in scenarios.items():
            with self.subTest(name=name):
                context = FakeContext([support_team(), picker])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context)._support(context.snapshot())
                self.assertEqual(context.clicks, ["支援"])
                self.assertEqual(context.keys, [])

    def test_unknown_entry_page_cannot_open_support_picker(self) -> None:
        unknown = Scene([token("支援", .88, .87), token("开始挑战", .88, .92)])
        context = FakeContext([unknown, support_picker()])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context)._support(unknown)
        self.assertEqual(context.clicks, [])

    def test_missing_or_gray_support_badge_stops_before_confirmation(self) -> None:
        for marker in (None, "gray"):
            with self.subTest(marker=marker):
                context = FakeContext([support_team(), support_picker(),
                                       support_picker(marker=marker)])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context)._support(context.snapshot())
                self.assertEqual(context.clicks, ["支援", "好友"])
                self.assertNotIn("确认", context.clicks)

    def test_already_present_green_marker_is_not_new_selection_proof(self) -> None:
        context = FakeContext([support_team(), support_picker(marker="green")])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context)._support(context.snapshot())
        self.assertEqual(context.clicks, ["支援"])

    def test_unrelated_green_pixels_and_ambiguous_labels_are_not_support_proof(self) -> None:
        import numpy as np

        elsewhere = support_picker(marker="gray")
        elsewhere.image[200:400, 700:1000] = (65, 150, 75)
        missing_label = Scene(support_picker().tokens,
                              image=np.full((1080, 1920, 3), (65, 150, 75), dtype=np.uint8))
        ambiguous = support_picker(marker="green")
        ambiguous.tokens.append(token("支援", .6, .54))
        wrong_column = support_picker(marker="green")
        wrong_column.tokens = [t for t in wrong_column.tokens if t.text != "支援"]
        wrong_column.tokens.append(token("支援", .15, .54))
        for scene in (elsewhere, missing_label, ambiguous, wrong_column):
            with self.subTest(text=scene.text):
                self.assertFalse(DailyWorkflow._support_marker(scene))

    def test_returned_team_without_green_support_never_starts_battle(self) -> None:
        for marker in (None, "gray"):
            with self.subTest(marker=marker):
                context = FakeContext([calyx_scene(cost=10, rounds=1), support_team(),
                                       support_picker(), support_picker(marker="green"),
                                       support_team(marker)],
                                      Settings(stamina_limit=10, rounds=1, use_support=True))
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).battle()
                self.assertEqual(context.clicks, ["挑战", "支援", "好友", "确认"])
                self.assertNotIn("开始挑战", context.clicks)
                self.assertEqual(context.report.stamina_spent, 0)

    def test_two_support_checks_gate_the_only_battle_start(self) -> None:
        success = Scene([token("挑战成功", .5, .3), token("退出关卡", .8, .9)])
        context = FakeContext([calyx_scene(cost=10, rounds=1), support_team(),
                               support_picker(), support_picker(marker="green"),
                               support_team("green"), success, Scene([])],
                              Settings(stamina_limit=10, rounds=1, use_support=True))
        result = DailyWorkflow(context).battle()
        self.assertEqual(result.status, "ok")
        self.assertEqual(context.clicks, ["挑战", "支援", "好友", "确认", "开始挑战", "退出关卡"])
        self.assertEqual(context.report.stamina_spent, 10)
        self.assertEqual(context.clicks.count("开始挑战"), 1)


class LoginSupplyTests(unittest.TestCase):
    @staticmethod
    def phone() -> Scene:
        return Scene([token("开拓等级", 0.8, 0.15), token("委托", 0.8, 0.6)])

    @staticmethod
    def revealed(amount: str | None = "90", currency: str | None = "星琼",
                 central_card: bool = True) -> Scene:
        scene = train_supply_scene()
        x = 0.5 if central_card else 0.85
        if amount is not None:
            scene.tokens.append(token(amount, x, 0.554))
        if currency is not None:
            scene.tokens.append(token(currency, x, 0.585))
        return scene

    def test_claim_then_revealed_reward_closes_with_one_separate_second_click(self) -> None:
        first, unchanged, revealed = train_supply_scene(), train_supply_scene(), self.revealed()
        context = FakeContext([first, unchanged, revealed, self.phone()])
        self.assertIs(DailyWorkflow(context).ensure_main(), context.scenes[-1])
        self.assertEqual(context.clicks, ["点击领取今日补给"] * 2)
        self.assertEqual(context.click_scenes, [first, revealed])
        self.assertEqual(context.keys, [])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_starting_at_revealed_supply_only_closes_once(self) -> None:
        revealed = self.revealed()
        context = FakeContext([revealed, self.phone()])
        self.assertIs(DailyWorkflow(context).ensure_main(), context.scenes[-1])
        self.assertEqual(context.clicks, ["点击领取今日补给"])
        self.assertEqual(context.click_scenes, [revealed])
        self.assertEqual(context.keys, [])

    def test_reward_amount_with_degree_ocr_suffix_keeps_the_two_stage_sequence(self) -> None:
        first, revealed = train_supply_scene(), self.revealed(amount="90°")
        context = FakeContext([first, revealed, self.phone()])
        self.assertIs(DailyWorkflow(context).ensure_main(), context.scenes[-1])
        self.assertEqual(context.clicks, ["点击领取今日补给"] * 2)
        self.assertEqual(context.click_scenes, [first, revealed])
        self.assertEqual(context.keys, [])

    def test_partial_or_different_reward_text_never_authorizes_claim_or_close(self) -> None:
        for amount, currency in (("190", "星琼"), ("90x", "星琼"), ("90°", None)):
            for after_claim in (False, True):
                with self.subTest(amount=amount, currency=currency, after_claim=after_claim):
                    revealed = self.revealed(amount=amount, currency=currency)
                    context = FakeContext([train_supply_scene(), revealed] if after_claim else [revealed])
                    with self.assertRaises(AutomationError):
                        DailyWorkflow(context).ensure_main()
                    self.assertEqual(context.clicks, ["点击领取今日补给"] if after_claim else [])
                    self.assertEqual(context.keys, [])

    def test_second_click_requires_distinct_complete_reward_card_evidence(self) -> None:
        for revealed in (self.revealed(amount=None), self.revealed(currency=None),
                         self.revealed(amount="300"), self.revealed(currency="信用点"),
                         self.revealed(central_card=False)):
            with self.subTest(text=revealed.text):
                first = train_supply_scene()
                context = FakeContext([first, revealed])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).ensure_main()
                self.assertEqual(context.clicks, ["点击领取今日补给"])
                self.assertEqual(context.click_scenes, [first])
                self.assertEqual(context.keys, [])

    def test_starting_at_incomplete_reward_card_does_not_attempt_a_new_claim(self) -> None:
        for scene in (self.revealed(amount=None), self.revealed(currency=None),
                      self.revealed(amount="300"), self.revealed(currency="信用点")):
            with self.subTest(text=scene.text):
                context = FakeContext([scene])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).ensure_main()
                self.assertEqual(context.clicks, [])
                self.assertEqual(context.keys, [])

    def test_revealed_supply_that_does_not_close_is_not_clicked_again(self) -> None:
        first, unchanged = self.revealed(), self.revealed()
        context = FakeContext([first, unchanged])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).ensure_main()
        self.assertEqual(context.clicks, ["点击领取今日补给"])
        self.assertEqual(context.keys, [])

    def test_sales_text_stops_revealed_supply_even_after_first_free_claim(self) -> None:
        for after_claim, sales, x in ((False, "续购", 0.90), (True, "支付", 0.10)):
            with self.subTest(after_claim=after_claim, sales=sales):
                revealed = self.revealed()
                revealed.tokens.append(token(sales, x, 0.85))
                first = train_supply_scene()
                context = FakeContext([first, revealed] if after_claim else [revealed])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).ensure_main()
                self.assertEqual(context.clicks, ["点击领取今日补给"] if after_claim else [])
                self.assertEqual(context.keys, [])

    def test_existing_train_supply_claims_only_exact_daily_label_once(self) -> None:
        context = FakeContext([train_supply_scene(), self.phone()])
        result = DailyWorkflow(context).ensure_main()
        self.assertIs(result, context.scenes[-1])
        self.assertEqual(context.clicks, ["点击领取今日补给"])
        self.assertEqual(context.keys, [])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_login_handles_supply_overlay_before_treating_it_as_world(self) -> None:
        login = Scene([token("点击进入", 0.5, 0.92)])
        context = FakeContext([login, train_supply_scene(), self.phone()])
        # A coincidental icon match must not send Escape through the overlay.
        context.template_matches["world_character"] = [(0.967, 0.045, 0.99)]
        DailyWorkflow(context).ensure_main()
        self.assertEqual(context.clicks, ["点击进入", "点击领取今日补给"])
        self.assertEqual(context.keys, [])

    def test_purchase_or_renewal_page_is_never_clicked_or_escaped(self) -> None:
        for sales in ("购买", "续购", "续费", "订购", "支付", "立即购买"):
            with self.subTest(sales=sales):
                context = FakeContext([train_supply_scene(sales=sales)])
                context.template_matches["world_character"] = [(0.967, 0.045, 0.99)]
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).ensure_main()
                self.assertEqual(context.clicks, [])
                self.assertEqual(context.keys, [])

    def test_side_renewal_or_payment_controls_stop_both_login_overlay_types(self) -> None:
        for after_claim, sales, x in ((False, "续购", 0.90),
                                      (True, "支付", 0.10), (True, "付款", 0.90)):
            with self.subTest(after_claim=after_claim, sales=sales, x=x):
                if after_claim:
                    overlay = Scene([token("获得物品", 0.5, 0.3),
                                     token("点击空白处关闭", 0.5, 0.88),
                                     token(sales, x, 0.85)])
                    scenes = [train_supply_scene(), overlay, self.phone()]
                else:
                    overlay = train_supply_scene()
                    overlay.tokens.append(token(sales, x, 0.85))
                    scenes = [overlay]
                context = FakeContext(scenes)
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).ensure_main()
                self.assertEqual(context.clicks, ["点击领取今日补给"] if after_claim else [])
                self.assertEqual(context.keys, [])

    def test_claim_needs_current_entitlement_and_exact_action(self) -> None:
        for remaining, label in (("剩余：0天", "点击领取今日补给"),
                                 ("", "点击领取今日补给"),
                                 ("剩余：21天", "领取"),
                                 ("剩余：21天", "点击领取今日补给并续购")):
            with self.subTest(remaining=remaining, label=label):
                context = FakeContext([train_supply_scene(remaining=remaining, claim=label)])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).ensure_main()
                self.assertEqual(context.clicks, [])
                self.assertEqual(context.keys, [])

    def test_persistent_overlay_after_claim_is_not_clicked_twice(self) -> None:
        context = FakeContext([train_supply_scene(), train_supply_scene()])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).ensure_main()
        self.assertEqual(context.clicks, ["点击领取今日补给"])
        self.assertEqual(context.keys, [])

    def test_unrecognized_post_claim_overlay_does_not_trigger_blind_escape(self) -> None:
        context = FakeContext([train_supply_scene(), Scene([token("奖励已到账", 0.5, 0.5)])])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).ensure_main()
        self.assertEqual(context.clicks, ["点击领取今日补给"])
        self.assertEqual(context.keys, [])

    def test_post_claim_reward_can_close_only_with_title_and_exact_close_hint(self) -> None:
        reward = Scene([token("获得物品", 0.5, 0.3),
                        token("点击空白处关闭", 0.5, 0.88)])
        context = FakeContext([train_supply_scene(), reward, self.phone()])
        DailyWorkflow(context).ensure_main()
        self.assertEqual(context.clicks, ["点击领取今日补给", "点击空白处关闭"])
        self.assertEqual(context.keys, [])

    def test_unbound_close_hint_after_claim_does_not_authorize_another_click(self) -> None:
        unknown = Scene([token("点击空白处关闭", 0.5, 0.88)])
        context = FakeContext([train_supply_scene(), unknown])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).ensure_main()
        self.assertEqual(context.clicks, ["点击领取今日补给"])
        self.assertEqual(context.keys, [])


class PersistentAssignmentTests(unittest.TestCase):
    def test_opening_animation_does_not_lock_in_legacy_assignment_handling(self) -> None:
        from unittest.mock import patch
        from autohsr.tests.test_du_team import fixture
        ready=fixture('assignments_after_claim')
        opening=Scene([t for t in ready.tokens if t.text!='4/4'],ready.image)
        self.assertFalse(DailyWorkflow._persistent_assignments(opening))
        self.assertTrue(DailyWorkflow._persistent_assignments(ready))
        context=FakeContext([ready]);flow=DailyWorkflow(context)
        with patch.object(flow,'_snapshot',side_effect=[opening,ready]):
            result=flow.assignments()
        self.assertEqual(result.status,'ok')
        self.assertIn('4/4',result.detail)
        self.assertEqual(context.clicks,[])

    def test_four_active_assignments_without_rewards_needs_no_input(self) -> None:
        for scene in (assignments_scene(settled=True), assignments_scene(claim="disabled")):
            with self.subTest(visible_claim=scene.has("领取奖励", exact=True)):
                context = FakeContext([scene])
                result = DailyWorkflow(context).assignments()
                self.assertEqual(result.status, "ok")
                self.assertEqual(context.clicks, [])
                self.assertEqual(context.keys, [])
                self.assertEqual(context.report.stamina_spent, 0)

    def test_claim_once_then_verify_all_four_remain_active(self) -> None:
        context = FakeContext([assignments_scene(claim="enabled"),
                               assignments_scene(claim="disabled")])
        result = DailyWorkflow(context).assignments()
        self.assertEqual(result.status, "ok")
        self.assertEqual(context.clicks, ["领取奖励"])
        self.assertNotIn("变更委托", context.clicks)

    def test_delayed_yellow_button_is_not_clicked_twice(self) -> None:
        context = FakeContext([assignments_scene(claim="enabled"),
                               assignments_scene(claim="enabled"),
                               assignments_scene(settled=True)])
        self.assertEqual(DailyWorkflow(context).assignments().status, "ok")
        self.assertEqual(context.clicks, ["领取奖励"])

    def test_unverified_claim_stops_after_one_collection(self) -> None:
        context = FakeContext([assignments_scene(claim="enabled"),
                               assignments_scene(claim="enabled")])
        self.assertEqual(DailyWorkflow(context).assignments().status, "partial")
        self.assertEqual(context.clicks, ["领取奖励"])

    def test_three_active_assignments_is_not_success_and_never_changes_selection(self) -> None:
        context = FakeContext([assignments_scene(count=3, settled=True)])
        self.assertEqual(DailyWorkflow(context).assignments().status, "partial")
        self.assertEqual(context.clicks, [])

    def test_label_without_visible_button_fill_does_not_prove_enabled(self) -> None:
        scene = assignments_scene(claim="enabled")
        scene.image[:] = 0
        context = FakeContext([scene])
        self.assertEqual(DailyWorkflow(context).assignments().status, "partial")
        self.assertEqual(context.clicks, [])


class DailyBadgeTests(unittest.TestCase):
    @staticmethod
    def badge_scene(value: int, full_text: bool = False) -> Scene:
        scene = daily_scene("奖励500")
        scene.tokens.append(token(str(value), 0.177, 0.33))
        if full_text:
            scene.tokens.append(token("本日活跃度已满", 0.5, 0.77))
        return scene

    @staticmethod
    def completed(context: FakeContext, count: int = 5) -> None:
        context.template_matches["daily_completed"] = [
            (x, 0.3, 0.99) for x in (0.27, 0.43, 0.58, 0.72, 0.87)[:count]]

    def test_left_badge_500_and_full_text_and_five_checkmarks_complete(self) -> None:
        context = FakeContext([self.badge_scene(500, full_text=True)])
        self.completed(context)
        self.assertEqual(DailyWorkflow(context).daily().status, "ok")
        self.assertTrue(context.report.daily_verified)
        self.assertEqual(context.clicks, [])

    def test_bare_left_badge_without_corresponding_label_or_icon_is_unverified(self) -> None:
        context = FakeContext([self.badge_scene(500)])
        self.completed(context)
        self.assertEqual(DailyWorkflow(context).daily().status, "partial")
        self.assertFalse(context.report.daily_verified)

    def test_badge_template_identifies_current_value_but_does_not_raise_it_to_500(self) -> None:
        for value, expected in ((400, "partial"), (500, "ok")):
            with self.subTest(value=value):
                context = FakeContext([self.badge_scene(value)])
                self.completed(context)
                context.template_matches["daily_activity_badge"] = [(0.177, 0.28, 0.99)]
                self.assertEqual(DailyWorkflow(context).daily().status, expected)
                self.assertEqual(context.report.daily_verified, value == 500)

    def test_full_badge_with_four_checkmarks_still_does_not_complete(self) -> None:
        context = FakeContext([self.badge_scene(500, full_text=True)])
        self.completed(context, count=4)
        self.assertEqual(DailyWorkflow(context).daily().status, "partial")
        self.assertFalse(context.report.daily_verified)

    def test_five_labels_clustered_in_one_milestone_cannot_prove_all_rewards(self) -> None:
        scene = self.badge_scene(500, full_text=True)
        scene.tokens.extend(token("已领取", 0.23 + i * 0.02, 0.32) for i in range(5))
        context = FakeContext([scene])
        self.assertEqual(DailyWorkflow(context).daily().status, "partial")
        self.assertFalse(context.report.daily_verified)


class StaminaBoundaryTests(unittest.TestCase):
    @staticmethod
    def adjustable(cost: int, rounds: int, available: int = 120,
                   plus: bool = True, minus: bool = True) -> Scene:
        scene = calyx_scene(available=available, cost=cost, rounds=rounds)
        if plus:
            scene.tokens.append(token("+", 0.962, 0.80))
        if minus:
            scene.tokens.append(token("−", 0.65, 0.80))
        return scene

    def test_current_stamina_counter_ignores_trailing_ui_separator(self) -> None:
        for suffix in ("", "|", "丨", "+", "＋"):
            with self.subTest(suffix=suffix):
                scene = Scene([token("59/300" + suffix, 0.90, 0.075),
                               token("60", 0.7, 0.92)])
                self.assertEqual(DailyWorkflow._available(scene), 59)

    def test_unknown_or_ambiguous_current_stamina_is_not_inferred_from_cost(self) -> None:
        cases = ([token("60", 0.7, 0.92)], [token("301/300", 0.90, 0.075)],
                 [token("59/300", 0.90, 0.075), token("30/300", 0.8, 0.075)])
        for tokens in cases:
            with self.subTest(tokens=[value.text for value in tokens]):
                self.assertIsNone(DailyWorkflow._available(Scene(tokens)))

    def test_reward_only_degree_suffix_is_not_accepted_as_stamina_cost(self) -> None:
        for amount in ("10°", "90°"):
            with self.subTest(amount=amount):
                self.assertIsNone(DailyWorkflow._cost(Scene([token(amount, 0.7, 0.92)])))

    def test_available_59_caps_a_six_round_batch_at_five_rounds(self) -> None:
        before = self.adjustable(60, 6, available=59)
        after = self.adjustable(50, 5, available=59)
        context = FakeContext([before, after], Settings(stamina_limit=240, rounds=6))
        scene, cost = DailyWorkflow(context)._limit_batch(before, 240)
        self.assertIs(scene, after)
        self.assertEqual(cost, 50)
        self.assertEqual(context.clicks, ["−"])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_increasing_count_obeys_both_remaining_budget_and_per_batch_rounds(self) -> None:
        for remaining, rounds, expected in ((20, 6, 20), (240, 3, 30)):
            with self.subTest(remaining=remaining, rounds=rounds):
                scenes = [self.adjustable(cost, cost // 10) for cost in range(10, expected + 10, 10)]
                context = FakeContext(scenes, Settings(stamina_limit=240, rounds=rounds))
                _, cost = DailyWorkflow(context)._limit_batch(scenes[0], remaining)
                self.assertEqual(cost, expected)
                self.assertEqual(context.clicks, ["+"] * (expected // 10 - 1))
                self.assertNotIn("挑战", context.clicks)

    def test_ten_remaining_decreases_six_rounds_to_exactly_one(self) -> None:
        scenes = [self.adjustable(cost, cost // 10) for cost in range(60, 0, -10)]
        context = FakeContext(scenes, Settings(stamina_limit=240, rounds=6))
        _, cost = DailyWorkflow(context)._limit_batch(scenes[0], 10)
        self.assertEqual(cost, 10)
        self.assertEqual(context.clicks, ["−"] * 5)

    def test_single_changed_indicator_after_increment_or_decrement_blocks_challenge(self) -> None:
        for before_cost, before_rounds, after_cost, after_rounds, remaining, click in (
            (10, 1, 20, 1, 20, "+"), (10, 1, 10, 2, 20, "+"),
            (60, 6, 50, 6, 50, "−"), (60, 6, 60, 5, 50, "−"),
        ):
            with self.subTest(before=before_cost, after=(after_cost, after_rounds)):
                before = self.adjustable(before_cost, before_rounds)
                after = self.adjustable(after_cost, after_rounds)
                context = FakeContext([before, after],
                                      Settings(stamina_limit=remaining, rounds=6, use_support=False))
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context).battle()
                self.assertEqual(context.clicks, [click])
                self.assertEqual(context.report.stamina_spent, 0)

    def test_missing_increment_control_uses_only_existing_verified_smaller_batch(self) -> None:
        scene = self.adjustable(10, 1, plus=False)
        context = FakeContext([scene], Settings(stamina_limit=240, rounds=6))
        _, cost = DailyWorkflow(context)._limit_batch(scene, 240)
        self.assertEqual(cost, 10)
        self.assertEqual(context.clicks, [])

    def test_later_batch_is_limited_by_remaining_run_budget(self) -> None:
        team = Scene([token("队伍", 0.1, 0.05), token("开始挑战", 0.8, 0.9)])
        success = Scene([token("挑战成功", 0.5, 0.3), token("退出关卡", 0.8, 0.9)])
        context = FakeContext([calyx_scene(cost=20, rounds=2), team, success,
                               calyx_scene(cost=10, rounds=1), team, success, Scene([])],
                              Settings(stamina_limit=30, rounds=2, use_support=False))
        self.assertEqual(DailyWorkflow(context).battle().status, "ok")
        self.assertEqual(context.report.stamina_spent, 30)
        self.assertEqual(context.clicks.count("开始挑战"), 2)

    def test_switch_needs_both_track_and_knob_position(self) -> None:
        cases = (("gold", "right", "on"), ("neutral", "left", "off"),
                 ("gold", "left", None), ("neutral", "right", None),
                 ("gold", None, None), ("neutral", None, None),
                 ("dark", "left", None))
        for track, knob, expected in cases:
            with self.subTest(track=track, knob=knob):
                scene = calyx_scene()
                scene.image = pill_refill_image(track, (knob,) if knob else ())
                self.assertEqual(DailyWorkflow(FakeContext([scene]))._quick_refill_state(scene)[0], expected)

    def test_realistic_switch_with_thin_neutral_border_is_off_and_not_toggled(self) -> None:
        scene = calyx_scene()
        scene.image = pill_refill_image()
        context = FakeContext([scene])
        self.assertEqual(DailyWorkflow(context)._quick_refill_state(scene)[0], "off")
        self.assertIs(DailyWorkflow(context)._disable_quick_refill(scene), scene)
        self.assertEqual(context.clicks, [])

    def test_round_right_knob_and_orange_track_prove_on_and_require_verified_off(self) -> None:
        on, off = calyx_scene(), calyx_scene()
        on.image = pill_refill_image(track="gold", knobs=("right",))
        off.image = pill_refill_image()
        context = FakeContext([on, off])
        workflow = DailyWorkflow(context)
        self.assertEqual(workflow._quick_refill_state(on)[0], "on")
        self.assertIs(workflow._disable_quick_refill(on), off)
        self.assertEqual(len(context.clicks), 1)
        self.assertIsInstance(context.clicks[0], tuple)

    def test_dark_or_double_knob_shapes_do_not_prove_switch_off(self) -> None:
        for track, knobs in (("dark", ("left",)), ("neutral", ("left", "right")),
                             ("gold", ("left", "right"))):
            with self.subTest(track=track, knobs=knobs):
                scene = calyx_scene()
                scene.image = pill_refill_image(track=track, knobs=knobs)
                context = FakeContext([scene])
                workflow = DailyWorkflow(context)
                self.assertIsNone(workflow._quick_refill_state(scene)[0])
                with self.assertRaises(AutomationError):
                    workflow._disable_quick_refill(scene)
                self.assertEqual(context.clicks, [])

    def test_two_visible_white_knobs_are_ambiguous_even_when_right_is_larger(self) -> None:
        import cv2

        scene = calyx_scene()
        scene.image = pill_refill_image(track="gold", knobs=())
        patch = scene.image[round(0.743 * 1080):round(0.771 * 1080),
                            round(0.947 * 1920):round(0.979 * 1920)]
        height, width = patch.shape[:2]
        radius, y = height // 3, height // 2
        left, right = (radius + 1, y), (width - radius - 2, y)
        cv2.line(patch, left, right, (0, 190, 240), radius * 2 + 2)
        cv2.circle(patch, left, radius - 2, (246, 246, 246), -1)
        cv2.circle(patch, right, radius, (246, 246, 246), -1)
        context = FakeContext([scene])
        workflow = DailyWorkflow(context)
        self.assertIsNone(workflow._quick_refill_state(scene)[0])
        with self.assertRaises(AutomationError):
            workflow._disable_quick_refill(scene)
        self.assertEqual(context.clicks, [])

    def test_realistic_off_pixels_without_label_are_not_safe_to_click(self) -> None:
        scene = calyx_scene()
        scene.image = pill_refill_image()
        scene.tokens = [value for value in scene.tokens if value.text != "快捷补充开拓力"]
        context = FakeContext([scene])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context)._disable_quick_refill(scene)
        self.assertEqual(context.clicks, [])

    @staticmethod
    def actual_refill_scene(frame) -> Scene:
        import cv2
        import numpy as np

        pixels = cv2.imdecode(np.frombuffer(base64.b64decode(frame["png"]), dtype=np.uint8),
                              cv2.IMREAD_COLOR)
        scene = calyx_scene()
        scene.image = np.zeros((2160, 3840, 3), dtype=np.uint8)
        x, y = frame["origin"]
        scene.image[y:y + pixels.shape[0], x:x + pixels.shape[1]] = pixels
        scene.tokens = [value for value in scene.tokens if value.text != "快捷补充开拓力"]
        scene.tokens.append(Token("快捷补充开拓力", 0.99, frame["box"]))
        return scene

    def test_real_switch_frames_keep_state_across_transparent_background_changes(self) -> None:
        for frame in REAL_REFILL_PATCHES:
            with self.subTest(frame=frame["name"]):
                scene = self.actual_refill_scene(frame)
                context = FakeContext([scene])
                expected = "on" if frame["name"] == "on" else "off"
                workflow = DailyWorkflow(context)
                self.assertEqual(workflow._quick_refill_state(scene)[0], expected)
                if expected == "off":
                    self.assertIs(workflow._disable_quick_refill(scene), scene)
                    self.assertEqual(context.clicks, [])

    def test_real_on_turns_off_once_with_either_observed_background(self) -> None:
        for frame in REAL_REFILL_PATCHES[1:]:
            with self.subTest(frame=frame["name"]):
                on = self.actual_refill_scene(REAL_REFILL_PATCHES[0])
                off = self.actual_refill_scene(frame)
                context = FakeContext([on, off])
                self.assertIs(DailyWorkflow(context)._disable_quick_refill(on), off)
                self.assertEqual(len(context.clicks), 1)
                self.assertIsInstance(context.clicks[0], tuple)
                self.assertEqual(context.report.stamina_spent, 0)

    def test_real_switch_pixels_without_verified_calyx_page_do_not_authorize_input(self) -> None:
        scene = self.actual_refill_scene(REAL_REFILL_PATCHES[0])
        scene.tokens = [value for value in scene.tokens if value.text == "快捷补充开拓力"]
        context = FakeContext([scene])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context)._disable_quick_refill(scene)
        self.assertEqual(context.clicks, [])

    def test_rectangular_white_patch_is_not_a_verified_round_switch_knob(self) -> None:
        for track, knob in (("gold", "right"), ("neutral", "left")):
            with self.subTest(track=track, knob=knob):
                scene = calyx_scene()
                scene.image = quick_refill_image(track, knob)
                context = FakeContext([scene])
                with self.assertRaises(AutomationError):
                    DailyWorkflow(context)._disable_quick_refill(scene)
                self.assertEqual(context.clicks, [])

    def test_switch_pixels_without_bound_label_cannot_prove_off(self) -> None:
        scene = calyx_scene()
        scene.tokens = [value for value in scene.tokens if value.text != "快捷补充开拓力"]
        context = FakeContext([scene])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).battle()
        self.assertEqual(context.clicks, [])

    def test_unknown_switch_blocks_challenge_even_with_valid_ten_cost_and_round_count(self) -> None:
        scene = calyx_scene(cost=10, rounds=1, quick_refill="unknown")
        context = FakeContext([scene], Settings(stamina_limit=10, rounds=1, use_support=False))
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).battle()
        self.assertEqual(context.clicks, [])
        self.assertEqual(context.report.stamina_spent, 0)

    def test_enabled_switch_must_transition_to_verified_off_before_challenge(self) -> None:
        on = calyx_scene(cost=10, rounds=1, quick_refill="on")
        off = calyx_scene(cost=10, rounds=1)
        team = Scene([token("队伍", 0.1, 0.05), token("开始挑战", 0.8, 0.9)])
        success = Scene([token("挑战成功", 0.5, 0.3), token("退出关卡", 0.8, 0.9)])
        context = FakeContext([on, off, team, success, Scene([])],
                              Settings(stamina_limit=10, rounds=1, use_support=False))
        self.assertEqual(DailyWorkflow(context).battle().status, "ok")
        self.assertIsInstance(context.clicks[0], tuple)
        self.assertEqual(context.clicks[1:], ["挑战", "开始挑战", "退出关卡"])
        self.assertEqual(context.report.stamina_spent, 10)

    def test_unconfirmed_switch_change_never_starts_challenge(self) -> None:
        context = FakeContext([calyx_scene(quick_refill="on"), calyx_scene(quick_refill="on")])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).battle()
        self.assertEqual(len(context.clicks), 1)
        self.assertIsInstance(context.clicks[0], tuple)
        self.assertNotIn("挑战", context.clicks)

    def test_fuel_prompt_after_start_is_cancelled_without_success_or_expense(self) -> None:
        team = Scene([token("队伍", 0.1, 0.05), token("开始挑战", 0.8, 0.9)])
        fuel = Scene([token("使用燃料", 0.5, 0.35), token("确认", 0.6, 0.8),
                      token("取消", 0.4, 0.8)])
        context = FakeContext([calyx_scene(cost=10, rounds=1), team, fuel, calyx_scene()],
                              Settings(stamina_limit=10, rounds=1, use_support=False))
        self.assertEqual(DailyWorkflow(context).battle().status, "partial")
        self.assertEqual(context.clicks, ["挑战", "开始挑战", "取消"])
        self.assertEqual(context.report.stamina_spent, 0)


class GuideTargetTests(unittest.TestCase):
    def test_survival_icon_remains_locatable_beneath_new_notification_badge(self) -> None:
        from pathlib import Path
        from autohsr.tests.test_du_team import fixture
        from autohsr.vision import Vision
        import numpy as np
        page=fixture('daily_survival_badge')
        vision=Vision.__new__(Vision)
        path=Path(__file__).resolve().parents[2]/'assets/templates/survival_tab_base.png'
        match=vision.template(page,path,(.15,.14,.55,.25),.94)
        self.assertIsNotNone(match)
        self.assertAlmostEqual(match[0],.251,places=2)
        self.assertIsNone(vision.template(Scene(page.tokens,np.zeros_like(page.image)),path,(.15,.14,.55,.25),.94))
        ready=survival_guide([])
        context=FakeContext([page,ready])
        context.template_matches['survival_tab_base']=[match]
        self.assertIs(DailyWorkflow(context)._open_guide('生存索引'),ready)
        self.assertEqual(context.clicks,[match[:2]])

    def test_chosen_guide_row_carries_map_evidence_into_details_that_omit_it(self) -> None:
        guide = survival_guide([("边缘通路", 0.36), ("城郊雪原", 0.60)])
        details = calyx_scene(location=None)
        context = FakeContext([guide, guide, details])
        workflow = DailyWorkflow(context)
        self.assertIs(workflow._open_calyx(), details)
        self.assertTrue(workflow._calyx_target(details))
        self.assertEqual(context.clicks, ["拟造花萼（金）", "传送"])
        self.assertAlmostEqual(context.click_targets[-1].center[1], 0.60)
        self.assertIn("calyx_guide_target_verified", context.evidence_labels)

    def test_unbound_details_without_map_returns_to_guide_before_selection(self) -> None:
        details = calyx_scene(location=None)
        phone = Scene([token("开拓等级", 0.8, 0.15), token("指南", 0.8, 0.6)])
        guide = survival_guide([("城郊雪原", 0.6)])
        context = FakeContext([details, phone, guide, guide, details])
        workflow = DailyWorkflow(context)
        self.assertFalse(workflow._calyx_target(details))
        self.assertIs(workflow._open_calyx(), details)
        self.assertEqual(context.keys, ["esc"])
        self.assertEqual(context.clicks, ["指南", "拟造花萼（金）", "传送"])

    def test_map_and_entry_from_different_rows_cannot_authorize_target(self) -> None:
        guide = survival_guide([("边缘通路", 0.36), ("城郊雪原", 0.6)])
        # Remove the intended row's entry; the other row remains clickable.
        guide.tokens = [value for value in guide.tokens
                        if not (value.text == "传送" and value.center[1] > 0.5)]
        context = FakeContext([guide, guide])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context)._open_calyx()
        self.assertEqual(context.clicks, ["拟造花萼（金）"])
        self.assertNotIn("挑战", context.clicks)

    def test_ambiguous_matching_map_rows_are_not_selected(self) -> None:
        guide = survival_guide([("城郊雪原", 0.36), ("城郊雪原", 0.6)])
        context = FakeContext([guide, guide])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context)._open_calyx()
        self.assertEqual(context.clicks, ["拟造花萼（金）"])


class ContextInputSafetyTests(unittest.TestCase):
    def test_helper_window_frame_is_discarded_even_after_focus_was_restored(self):
        from autohsr.vision import helper_overlay
        from autohsr.tests.test_du_team import fixture
        self.assertTrue(helper_overlay(fixture('helper_occluded_blessing')))
        overlay=Scene([token('选择祝福',.1,.06),token('AutoHSR',.2,.2),
                       token('保存设置',.3,.7),token('运行日志',.3,.6)],geometry=object())
        game=Scene([token('选择祝福',.1,.06)],geometry=overlay.geometry)
        self.assertTrue(helper_overlay(overlay))
        self.assertFalse(helper_overlay(game))
        context=self.context(game)
        context.window.capture.return_value=(object(),game.geometry)
        context.vision.read.side_effect=[overlay,game]
        self.assertIs(context.snapshot(),game)
        self.assertEqual(context.window.capture.call_count,2)
        context.window.click.assert_not_called()

    def test_persistent_helper_occlusion_is_bounded_and_never_becomes_a_game_target(self):
        overlay=Scene([token('AutoHSR',.2,.2),token('保存设置',.3,.7),token('运行日志',.3,.6)],geometry=object())
        context=self.context(overlay)
        context.window.capture.return_value=(object(),overlay.geometry)
        context.vision.read.return_value=overlay
        with self.assertRaisesRegex(AutomationError,'遮挡'):
            context.snapshot()
        self.assertIsNone(context.last_scene)
        context.window.click.assert_not_called()
        self.assertEqual(context.window.capture.call_count,8)
    @staticmethod
    def context(scene: Scene):
        from autohsr.app import Context
        runner = SimpleNamespace(settings=Settings(), report=RunReport(), input_epoch=0,
                                 checkpoint=Mock(), log=Mock())
        window = Mock()
        context = Context(runner, window, Mock())
        context.last_scene = scene
        context.sleep = Mock()
        context.evidence = Mock()
        return context

    def test_expired_recognition_never_reaches_window_input(self) -> None:
        scene = Scene([token("领取", 0.5, 0.8)], captured_at=time.monotonic() - 9)
        context = self.context(scene)
        with self.assertRaises(AutomationError):
            context.click(scene, scene.tokens[0])
        context.window.click.assert_not_called()

    def test_slow_capture_and_ocr_cannot_make_old_pixels_fresh_for_click(self) -> None:
        clock = [100.0]
        scene = Scene([token("领取", 0.5, 0.8)], geometry=object())
        context = self.context(scene)

        def capture():
            clock[0] += 3
            return object(), scene.geometry

        def recognize(*args):
            clock[0] += 20
            # Even an OCR adapter returning a completion timestamp must not
            # overwrite the age of the pixels captured before processing.
            scene.captured_at = clock[0]
            return scene

        context.window.capture.side_effect = capture
        context.vision.read.side_effect = recognize
        with patch("autohsr.app.time.monotonic", side_effect=lambda: clock[0]):
            recognized = context.snapshot()
            self.assertEqual(recognized.captured_at, 100)
            with self.assertRaises(AutomationError):
                context.click(recognized, recognized.tokens[0])
        context.window.click.assert_not_called()

    def test_vision_preserves_age_during_slow_ocr_without_loading_models(self) -> None:
        import numpy as np
        from autohsr.vision import Vision

        clock = [100.0]
        vision = Vision.__new__(Vision)
        vision.confidence = 0.65

        def recognize(*args, **kwargs):
            clock[0] += 20
            return ([[[(0, 0), (5, 0), (5, 5), (0, 5)], "领取", 0.95]], None)

        vision.engine = recognize
        with patch("autohsr.vision.time.monotonic", side_effect=lambda: clock[0]):
            scene = vision.read(np.zeros((8, 16, 3), dtype=np.uint8))
        self.assertEqual(scene.captured_at, 100)
        self.assertGreater(clock[0] - scene.captured_at, 8)
        self.assertTrue(scene.has("领取", exact=True))

    def test_resume_epoch_invalidates_previous_scene_before_input(self) -> None:
        scene = Scene([token("领取", 0.5, 0.8)], captured_at=time.monotonic())
        context = self.context(scene)
        context.runner.checkpoint.side_effect = lambda: setattr(context.runner, "input_epoch", 1)
        with self.assertRaises(AutomationError):
            context.click(scene, scene.tokens[0])
        context.window.click.assert_not_called()

    def test_pause_during_snapshot_cannot_revalidate_old_pixels(self) -> None:
        old = Scene([token("领取", 0.5, 0.8)], geometry=object(), captured_at=time.monotonic())
        fresh = Scene([token("邮件", 0.1, 0.05)], geometry=old.geometry, captured_at=time.monotonic())
        context = self.context(old)
        context.window.capture.return_value = (object(), old.geometry)
        context.vision.read.side_effect = [old, fresh]
        checkpoints = 0

        def resume_during_ocr():
            nonlocal checkpoints
            checkpoints += 1
            if checkpoints == 2:
                context.runner.input_epoch += 1

        context.runner.checkpoint.side_effect = resume_during_ocr
        try:
            result = context.snapshot()
        except AutomationError:
            # Refusing the transition is also safe; old pixels must not be used.
            return
        self.assertIs(result, fresh)

    def test_other_scene_identity_never_reaches_window_input(self) -> None:
        scene = Scene([token("领取", 0.5, 0.8)], captured_at=time.monotonic())
        context = self.context(scene)
        old_scene = Scene(scene.tokens, captured_at=scene.captured_at)
        with self.assertRaises(AutomationError):
            context.click(old_scene, old_scene.tokens[0])
        context.window.click.assert_not_called()

    def test_resource_popup_blocks_confirm_and_coordinate_clicks(self) -> None:
        for target in (token("确认", 0.6, 0.8), (0.6, 0.8)):
            with self.subTest(target=target):
                scene = Scene([token("开拓力补充", 0.5, 0.3),
                               token("确认", 0.6, 0.8)], captured_at=time.monotonic())
                context = self.context(scene)
                with self.assertRaises(AutomationError):
                    context.click(scene, target)
                context.window.click.assert_not_called()

    def test_resource_popup_allows_only_visible_cancel(self) -> None:
        cancel = token("取消", 0.4, 0.8)
        scene = Scene([token("开拓力补充", 0.5, 0.3), cancel],
                      geometry=object(), captured_at=time.monotonic())
        context = self.context(scene)
        context.click(scene, cancel)
        context.window.click.assert_called_once_with(*cancel.center, scene.geometry)
        self.assertIsNone(context.last_scene)

    def test_fuel_or_premium_replenishment_text_blocks_raw_and_named_confirm(self) -> None:
        for label in ("使用燃料", "使用星琼", "开拓力不足", "购买开拓力", "兑换开拓力"):
            for raw_coordinate in (False, True):
                with self.subTest(label=label, raw_coordinate=raw_coordinate):
                    confirm = token("确认", 0.6, 0.8)
                    scene = Scene([token(label, 0.5, 0.35), confirm],
                                  captured_at=time.monotonic())
                    context = self.context(scene)
                    with self.assertRaises(AutomationError):
                        context.click(scene, confirm.center if raw_coordinate else confirm)
                    context.window.click.assert_not_called()

    def test_quick_refill_setting_label_alone_allows_verified_switch_coordinate(self) -> None:
        scene = calyx_scene()
        scene.geometry = object()
        scene.captured_at = time.monotonic()
        context = self.context(scene)
        context.click(scene, (0.963, 0.757))
        context.window.click.assert_called_once_with(0.963, 0.757, scene.geometry)


    def test_forbidden_labels_never_reach_window_input(self) -> None:
        for name in ("跃迁", "商店", "合成", "角色", "光锥", "遗器", "背包",
                     "强化", "升级", "兑换", "购买", "突破", "叠影"):
            with self.subTest(name=name):
                target = token(name, 0.8, 0.8)
                scene = Scene([target], captured_at=time.monotonic())
                context = self.context(scene)
                with self.assertRaises(AutomationError):
                    context.click(scene, target)
                context.window.click.assert_not_called()

    def test_coordinate_click_on_forbidden_phone_item_is_rejected(self) -> None:
        scene = Scene([token("开拓等级", 0.8, 0.15), token("委托", 0.65, 0.6),
                       token("跃迁", 0.95, 0.6)], captured_at=time.monotonic())
        context = self.context(scene)
        with self.assertRaises(AutomationError):
            context.click(scene, (0.95, 0.54))
        context.window.click.assert_not_called()

    def test_non_navigation_keys_are_rejected_before_window_input(self) -> None:
        for key in ("v", "f3", "c", "b", "space", "enter"):
            with self.subTest(key=key):
                context = self.context(Scene([], captured_at=time.monotonic()))
                with self.assertRaises(AutomationError):
                    context.key(key)
                context.window.key.assert_not_called()

    def test_navigation_keys_remain_usable(self) -> None:
        for key in ("esc", "f4"):
            with self.subTest(key=key):
                context = self.context(Scene([], captured_at=time.monotonic()))
                context.key(key)
                context.window.key.assert_called_once_with(key)


class HotkeyScopeTests(unittest.TestCase):
    GAME = 100
    ASSISTANT = 200

    def run_hotkey_frames(self, frames: list[tuple[int, bool, bool]]):
        """Drive virtual foreground/key states; never poll actual Win32 input."""
        from autohsr.app import Runner

        state = [None]
        iterator = iter(frames)
        events = []
        runner = Runner(Settings(), emit=events.append)
        runner._window = SimpleNamespace(hwnd=self.GAME,
                                        emergency_pressed=lambda: state[0][2])

        def next_frame(seconds):
            try:
                state[0] = next(iterator)
                return False
            except StopIteration:
                return True

        runner._monitor_end = SimpleNamespace(wait=next_frame)
        user32 = SimpleNamespace(
            GetAsyncKeyState=lambda key: (0x8000 if state[0][1] is True else state[0][1]),
            GetForegroundWindow=lambda: state[0][0],
        )
        with patch("autohsr.windows.user32", user32):
            runner._hotkeys()
        paused = [event["paused"] for event in events if event["type"] == "paused"]
        return runner, paused

    def test_game_foreground_press_and_hold_f9_pauses_once(self) -> None:
        runner, paused = self.run_hotkey_frames([
            (self.GAME, False, False), (self.GAME, True, False),
            (self.GAME, True, False), (self.GAME, False, False),
        ])
        self.assertEqual(paused, [True])
        self.assertEqual(runner.input_epoch, 1)
        self.assertTrue(runner._pause.is_set())

    def test_short_f9_press_between_monitor_polls_is_not_lost(self):
        runner,paused=self.run_hotkey_frames([
            (self.GAME,0,False),(self.GAME,1,False),(self.GAME,0,False),
            (self.GAME,1,False),(self.GAME,0,False)])
        self.assertEqual(paused,[True,False])
        self.assertEqual(runner.input_epoch,2)

    def test_assistant_foreground_f9_is_not_a_global_pause_key(self) -> None:
        runner, paused = self.run_hotkey_frames([
            (self.ASSISTANT, True, False), (self.ASSISTANT, False, False),
            (self.ASSISTANT, True, False), (self.ASSISTANT, False, False),
        ])
        self.assertEqual(paused, [])
        self.assertEqual(runner.input_epoch, 0)
        self.assertFalse(runner._pause.is_set())

    def test_held_f9_across_focus_changes_does_not_retrigger_or_resume(self) -> None:
        for frames, expected in (
            ([(self.GAME, True, False), (self.ASSISTANT, True, False),
              (self.GAME, True, False), (self.GAME, False, False)], [True]),
            ([(self.ASSISTANT, True, False), (self.GAME, True, False),
              (self.GAME, False, False)], []),
        ):
            with self.subTest(first_foreground=frames[0][0]):
                runner, paused = self.run_hotkey_frames(frames)
                self.assertEqual(paused, expected)
                self.assertEqual(runner.input_epoch, len(expected))

    def test_f10_emergency_stop_remains_global_when_assistant_has_focus(self) -> None:
        runner, paused = self.run_hotkey_frames([(self.ASSISTANT, False, True)])
        self.assertTrue(runner._stop.is_set())
        self.assertEqual(paused, [])


class PermanentExclusionTests(unittest.TestCase):
    def test_phone_menu_allows_only_verified_daily_entries(self) -> None:
        for label in ("委托", "指南", "星际和平指南", "邮件", "无名勋礼"):
            with self.subTest(label=label):
                entry = token(label, 0.8, 0.6)
                scene = Scene([token("开拓等级", 0.8, 0.15), entry])
                guard_click(scene, entry)
                guard_click(scene, (0.8, 0.54))

    def test_phone_coordinate_requires_nearby_permitted_label(self) -> None:
        scene = Scene([token("开拓等级", 0.8, 0.15), token("委托", 0.65, 0.6)])
        for point in ((0.95, 0.54), (0.65, 0.3), (0.65, 0.75), (0.5, 0.6)):
            with self.subTest(point=point):
                with self.assertRaises(AutomationError):
                    guard_click(scene, point)

    def test_forbidden_page_cannot_be_operated_by_ordinary_button_or_coordinate(self) -> None:
        for title in ("商店", "角色", "光锥", "遗器", "背包", "跃迁", "合成"):
            with self.subTest(title=title):
                scene = Scene([token(title, 0.1, 0.05), token("确认", 0.8, 0.8)])
                for target in (scene.tokens[1], (0.8, 0.8)):
                    with self.assertRaises(AutomationError):
                        guard_click(scene, target)

    def test_forbidden_page_still_allows_cancel(self) -> None:
        cancel = token("取消", 0.5, 0.8)
        guard_click(Scene([token("商店", 0.1, 0.05), cancel]), cancel)

    def test_compound_resource_actions_are_rejected(self) -> None:
        for label in ("确认购买", "立即充值", "立即抽卡", "确认合成", "确认升级", "星琼兑换",
                      "续购", "续费", "订购", "支付", "确认支付", "付款"):
            with self.subTest(label=label):
                target = token(label, 0.8, 0.8)
                with self.assertRaises(AutomationError):
                    guard_click(Scene([target]), target)

    def test_support_character_selection_is_not_a_training_action(self) -> None:
        target = token("选择支援角色", 0.8, 0.8)
        guard_click(Scene([token("支援", 0.1, 0.05), target]), target)


if __name__ == "__main__":
    unittest.main()
