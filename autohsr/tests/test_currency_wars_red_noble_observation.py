"""Read the red-noble card through the report and keep its effects unclaimed."""
from dataclasses import replace
import unittest

from autohsr.currency_wars_environment import (
    CENTERS, ENVIRONMENT_CONFLICTS, read_red_noble_declaration, standard_environment_options,
)
from autohsr.currency_wars_standard_flow import next_action
from autohsr.models import AutomationError, Token
from autohsr.tests import test_currency_wars_encounter as reports
from autohsr.tests import test_currency_wars_standard_environment as environments


BODY = '开局时拥有【红钻】和一个【简易武装箱】。'


def red_card(slot=0, *, selected=(), enabled=False):
    scene = environments.environment(selected, enabled)
    center = CENTERS[slot]
    scene.tokens = [t for t in scene.tokens if not t.within((center - .115, .34, center + .115, .79))]
    offset = center - CENTERS[0]
    for text, box in (
        ('红钻贵族', (.199, .348, .259, .381)),
        ('开局时拥有【红钻】和一个【简易武装', (.123, .387, .313, .415)),
        ('箱】。', (.123, .408, .157, .442)),
        ('装备', (.220, .692, .237, .708)),
    ):
        x1, y1, x2, y2 = box
        scene.tokens.append(Token(text, .99, (x1 + offset, y1, x2 + offset, y2)))
    return scene


class RedNobleObservationTests(unittest.TestCase):
    def test_same_card_reads_full_body_and_reports_only_a_declaration(self):
        for slot in range(3):
            for selected in (False, True):
                with self.subTest(slot=slot, selected=selected):
                    scene = red_card(slot, selected=(slot,) if selected else (), enabled=selected)
                    self.assertEqual(
                        read_red_noble_declaration(scene),
                        dict(slot=slot + 1, name='红钻贵族', body=BODY, red_diamond_declared=True,
                             simple_armament_box_count=1, selection_state='selected' if selected else 'unselected',
                             delivery_status='unknown'),
                    )

    def test_wrong_or_incomplete_declaration_stays_unread(self):
        for original, replacement in (
            ('红钻贵族', '红钻贯族'),
            ('【红钻】', '【蓝钻】'),
            ('简易武装', '进阶武装'),
            ('和一个【简易武装', '和【简易武装'),
            ('和一个【简易武装', '和两个【简易武装'),
            ('箱】。', '箱】。再消耗金币'),
        ):
            with self.subTest(original=original, replacement=replacement):
                scene = environments.change_text(red_card(), original, replacement)
                self.assertIsNone(read_red_noble_declaration(scene))

    def test_only_the_calibrated_preview_label_is_separate_from_the_body(self):
        original = red_card()
        label = next(t for t in original.tokens if t.text == '装备')
        without_preview = [t for t in original.tokens if t is not label]
        replacements = (
            (),
            (replace(label, box=(.491, .692, .508, .708)),),
            (replace(label, box=(.199, .692, .237, .708)),),
            (replace(label, box=(.220, .656, .237, .673)),),
            (replace(label, score=.64),),
            (label, replace(label)),
            (label, Token('需要消耗金币', .99, (.127, .515, .206, .545))),
            (label, Token('装备', .99, (.192, .740, .215, .759))),
        )
        for added in replacements:
            with self.subTest(added=added):
                self.assertIsNone(read_red_noble_declaration(replace(original, tokens=[*without_preview, *added])))
        for conflict in (
            Token('每次消耗金币', .64, (.127, .434, .206, .461)),
            Token('次数', .64, (.320, .437, .392, .460)),
        ):
            with self.subTest(conflict=conflict):
                self.assertIsNone(read_red_noble_declaration(
                    replace(original, field_reads={ENVIRONMENT_CONFLICTS: (conflict,)})
                ))
        other_column = Token('次数', .64, (.429, .437, .472, .460))
        self.assertIsNotNone(read_red_noble_declaration(
            replace(original, field_reads={ENVIRONMENT_CONFLICTS: (other_column,)})
        ))

    def test_selected_requires_a_single_same_card_border_and_a_bright_confirmation(self):
        for chosen, enabled in (((0, 1), True), ((1,), True), ((0,), False), ((), True)):
            with self.subTest(chosen=chosen, enabled=enabled):
                declaration = read_red_noble_declaration(red_card(selected=chosen, enabled=enabled))
                self.assertEqual(declaration['selection_state'], 'unknown')
        selected = red_card(selected=(0,), enabled=True)
        button = next(t for t in selected.tokens if t.text == '确认')
        without_button = [t for t in selected.tokens if t is not button]
        self.assertIsNone(read_red_noble_declaration(replace(selected, tokens=without_button)))
        weak = replace(button, score=.64)
        self.assertIsNone(read_red_noble_declaration(replace(selected, tokens=[*without_button, weak])))
        for conflict in (weak, replace(button, text='取消')):
            with self.subTest(conflict=conflict):
                scene = replace(selected, tokens=[*selected.tokens, conflict])
                self.assertEqual(read_red_noble_declaration(scene)['selection_state'], 'unknown')

    def test_wrong_page_unproven_shape_or_duplicate_title_yields_no_declaration(self):
        scene = red_card()
        missing_page = [t for t in scene.tokens if '投资环境' not in t.text]
        duplicate = Token('红钻贵族', .99, (.461, .348, .513, .381))
        for changed in (replace(scene, tokens=missing_page),
                        replace(scene, image=scene.image[:, 100:-100]),
                        replace(scene, tokens=[*scene.tokens, duplicate])):
            self.assertIsNone(read_red_noble_declaration(changed))

    def test_standard_environment_strategy_never_uses_the_read_only_declaration(self):
        scene = red_card()
        card = next(o for o in standard_environment_options(scene) if o.name.text == '红钻贵族')
        self.assertIsNone(card.kind)
        self.assertEqual(next_action(scene).intent, 'select_standard_environment_1')
        only_red = replace(scene, tokens=[t for t in scene.tokens if not t.within((.37, .34, .89, .79))])
        with self.assertRaises(AutomationError):
            next_action(only_red)

    def test_formal_read_only_report_is_separate_from_rewards_and_inputs(self):
        def check(scene):
            case = reports.EncounterTests()
            try:
                return case.cli_report(scene)
            finally:
                case.doCleanups()

        selected = red_card(selected=(0,), enabled=True)
        report = check(selected)
        self.assertEqual(report['red_noble_declaration'], read_red_noble_declaration(selected))
        self.assertNotIn('reward_effect', report)
        self.assertNotIn('initial_environment', report)
        self.assertNotIn('red_noble_declaration', check(reports.encounter()))
