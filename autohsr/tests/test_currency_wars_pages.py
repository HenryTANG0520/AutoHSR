"""Golden OCR from observed 4.6.0 UI; no desktop or game access."""
import json
from pathlib import Path
import unittest

from autohsr.currency_wars import decide, observe
from autohsr.models import Scene, Token


class CalibratedPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / "fixtures" / "currency_wars_pages.json"
        cls.pages = json.loads(path.read_text(encoding="utf-8"))["pages"]

    def tokens(self, kind):
        return [Token(**token) for token in self.pages[kind]["tokens"]]

    def test_observed_pages_are_distinct_and_never_enable_gameplay(self):
        for kind in self.pages:
            with self.subTest(page=kind):
                result = observe(Scene(self.tokens(kind)), .65)
                self.assertEqual(result.page_kind, kind)
                self.assertTrue(result.page_verified)
                self.assertFalse(any((result.rules_verified, result.gameplay_enabled, result.completion_verified)))
                self.assertEqual(decide(result).action, "stop_without_input")
                self.assertEqual(decide(result).reason, "rules_unverified")

    def test_moving_ui_text_out_of_its_region_never_recognizes_a_page(self):
        for kind in self.pages:
            with self.subTest(page=kind):
                tokens = [Token(t.text, t.score, (.4, .96, .6, .99)) for t in self.tokens(kind)]
                self.assertEqual(observe(Scene(tokens), .65).page_kind, "unknown")

    def test_low_confidence_background_text_cannot_form_a_page(self):
        for kind in self.pages:
            with self.subTest(page=kind):
                tokens = [Token(t.text, .64, t.box) for t in self.tokens(kind)]
                self.assertFalse(observe(Scene(tokens), .65).page_verified)

    def test_modal_takes_precedence_over_visible_background(self):
        for kind in ("team_save", "guide_legend", "standard_rules"):
            with self.subTest(modal=kind):
                tokens = self.tokens("lobby") + self.tokens(kind)
                self.assertEqual(observe(Scene(tokens), .65).page_kind, kind)

    def test_loot_modals_and_full_bench_block_preparation_inputs(self):
        from autohsr.currency_wars_node import start_target
        from autohsr.models import AutomationError
        for kind in ('equipment_selection', 'expert_selection', 'bench_full'):
            tokens = self.tokens('preparation') + self.tokens(kind)
            self.assertEqual(observe(Scene(tokens), .65).page_kind, kind)
            with self.assertRaises(AutomationError):
                start_target(Scene(tokens))
        for kind in ('equipment_selection', 'expert_selection'):
            tokens = self.tokens('preparation') + self.tokens('bench_full') + self.tokens(kind)
            self.assertEqual(observe(Scene(tokens), .65).page_kind, kind)

    def test_conflicting_modal_or_base_evidence_is_unclassified(self):
        for first, second in (("team_save", "guide_legend"), ("lobby", "mode_select")):
            with self.subTest(first=first, second=second):
                result = observe(Scene(self.tokens(first) + self.tokens(second)), .65)
                self.assertEqual(result.page_kind, "unknown")
                self.assertFalse(result.page_verified)

    def test_desktop_toast_does_not_promote_a_page_or_hide_the_modal(self):
        toast = [Token("Close", .99, (.9, .92, .95, .95)),
                 Token("Codex 有个问题", .99, (.85, .89, .99, .92))]
        self.assertEqual(observe(Scene(toast), .65).page_kind, "unknown")
        result = observe(Scene(self.tokens("standard_rules") + toast), .65)
        self.assertEqual(result.page_kind, "standard_rules")
        self.assertFalse(result.gameplay_enabled)

    def test_native_resolution_ocr_icon_prefix_is_accepted_only_in_the_front_label(self):
        original = self.tokens('preparation')
        tokens = [Token('昌前台区域', t.score, t.box) if t.text == '前台区域' else t for t in original]
        self.assertEqual(observe(Scene(tokens), .65).page_kind, 'preparation')
        tokens = [Token('伪装前台区域', t.score, t.box) if t.text == '前台区域' else t for t in original]
        self.assertEqual(observe(Scene(tokens), .65).page_kind, 'unknown')
