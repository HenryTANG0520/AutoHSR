"""Badge declaration recognition through the read-only Currency Wars report."""
from dataclasses import replace
import json
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars import CurrencyWarsWorkflow
from autohsr.currency_wars_investment_badges import parse_badge_declaration
from autohsr.currency_wars_investment_policy import badge_declarations, choose, option_digest, options
from autohsr.models import AutomationError, Scene, Token


def fixture(name='investment_plane3'):
    path = Path(__file__).parent / 'fixtures' / f'currency_wars_{name}.json'
    tokens = json.loads(path.read_text(encoding='utf-8'))['tokens']
    return Scene([Token(t['text'], t['score'], tuple(t['box'])) for t in tokens], captured_at=time.monotonic())


class BadgeDeclarationTests(unittest.TestCase):
    def test_redacted_plane_three_reports_each_declaration_but_keeps_existing_choices(self):
        scene = fixture()
        choices = options(scene)
        original_digest = option_digest(choices)
        declarations = badge_declarations(scene)
        self.assertEqual([(d['slot'], d['badge'], d['badge_count'], d['other_rewards']) for d in declarations], [
            (0, '昼之半神星徽', 1, (('风堇', 1), ('生命之环', 1))),
            (1, '追击星徽', 1, (('飞雪', 1), ('永动机', 1))),
        ])
        self.assertTrue(all(d['status'] == 'delivery_unverified' and not d['delivery_verified'] for d in declarations))
        self.assertEqual(option_digest(options(scene)), original_digest)
        self.assertEqual(choose(choices, 'default').name.text, '保守派')
        with self.assertRaises(AutomationError):
            choose(choices[:2], 'default')

    def test_counts_belong_to_independent_declared_labels(self):
        declaration = parse_badge_declaration('追击星徽套组', '获得两 个【追击星徽】，和1个【飞霄】，以及三件【永动机】。')
        self.assertEqual((declaration.badge, declaration.badge_count), ('追击星徽', 2))
        self.assertEqual(declaration.other_rewards, (('飞霄', 1), ('永动机', 3)))

    def test_title_body_and_quantity_grammar_are_exact(self):
        effect = '获得1个【昼之半神星徽】，和1个【风堇】，以及1个【生命之环】。'
        for title, text in (
                ('追击星徽套组', effect), ('盛会之星', effect), ('昼之半神星徽套组', '获得1个【昼之半神星徽】'),
                ('昼之半神星徽套组', effect.replace('【风堇】', '【花火】')),
                ('昼之半神星徽套组', effect.replace('获得1个', '获得10个')),
                ('昼之半神星徽套组', effect+'随后需支付金币')):
            with self.subTest(title=title, effect=text):
                self.assertIsNone(parse_badge_declaration(title, text))

    def test_missing_detached_or_ambiguous_body_does_not_claim_a_declaration(self):
        for change in ('truncated', 'cross_column', 'detached_row', 'extra_low_confidence'):
            with self.subTest(change=change):
                scene = fixture()
                index = next(i for i, token in enumerate(scene.tokens) if token.text == '之环】。')
                if change == 'truncated':
                    del scene.tokens[index]
                elif change == 'cross_column':
                    scene.tokens[index] = replace(scene.tokens[index], box=(.09,.534,.36,.566))
                elif change == 'detached_row':
                    scene.tokens[index] = replace(scene.tokens[index], box=(.152,.700,.200,.731))
                else:
                    scene.tokens.append(Token('另需支付3金币', .3, (.15,.57,.31,.60)))
                self.assertEqual([d['slot'] for d in badge_declarations(scene)], [1])

    def test_same_card_wrapping_and_horizontal_splits_require_adjacent_boxes(self):
        for name, left_box, right_box, expected in (
                ('slightly_higher_suffix', (.152,.486,.220,.513), (.217,.480,.309,.505), [0,1]),
                ('detached_suffix', (.152,.486,.220,.513), (.280,.487,.363,.513), [1]),
                ('disjoint_vertical_boxes', (.152,.493,.220,.504), (.226,.505,.309,.515), [1])):
            with self.subTest(name=name):
                scene = fixture()
                index = next(i for i, token in enumerate(scene.tokens) if token.text.startswith('获得1个【昼之半神'))
                scene.tokens[index:index+1] = [
                    Token('获得1个【昼之', .96, left_box),
                    Token('半神星徽】，和', .96, right_box),
                ]
                tail = next(i for i, token in enumerate(scene.tokens) if token.text == '之环】。')
                scene.tokens[tail:tail+1] = [
                    Token('之', .96, (.152,.534,.166,.566)),
                    Token('环】。', .96, (.152,.563,.200,.592)),
                ]
                self.assertEqual([d['slot'] for d in badge_declarations(scene)], expected)

    def test_wrapped_lines_allow_edge_overlap_but_require_separate_vertical_space(self):
        for name, box, expected in (
                ('edge_overlap', (.152,.531,.200,.563), [0,1]),
                ('overlaid_body', (.152,.514,.200,.559), [1])):
            with self.subTest(name=name):
                scene = fixture()
                index = next(i for i, token in enumerate(scene.tokens) if token.text == '之环】。')
                scene.tokens[index] = replace(scene.tokens[index], box=box)
                self.assertEqual([d['slot'] for d in badge_declarations(scene)], expected)

    def test_narrow_same_row_fragments_require_distinct_boxes(self):
        for right_start, expected in ((.161, [0,1]), (.154, [1])):
            with self.subTest(right_start=right_start):
                scene = fixture()
                index = next(i for i, token in enumerate(scene.tokens) if token.text.startswith('获得1个【昼之半神'))
                scene.tokens[index:index+1] = [
                    Token('获', .96, (.153,.484,.164,.506)),
                    Token('得1个【昼之半神星徽】，和', .96, (right_start,.484,.323,.506)),
                ]
                self.assertEqual([d['slot'] for d in badge_declarations(scene)], expected)

    def test_festival_star_popup_is_a_different_mechanism(self):
        self.assertEqual(badge_declarations(fixture('star')), [])

    def test_formal_readonly_inspection_emits_only_parsed_badge_fields(self):
        scene = fixture()
        local_only = 'UID' + str(10**8 + 19)
        scene.tokens.append(Token(local_only, .99, (.02, .96, .13, .99)))
        window = Mock()
        context = Context(Runner(Settings(), operation='currency_wars'), window, Mock())
        context.last_scene = scene
        context.snapshot = Mock(return_value=scene)
        context.evidence = Mock(return_value=Path('offline-badge-evidence.png'))
        with patch('autohsr.currency_wars_replay.save_sample', return_value=Path('offline-badge.sample.json')):
            result = CurrencyWarsWorkflow(context).inspect()
        report = context.report.currency_wars
        self.assertEqual(result.status, 'partial')
        self.assertEqual(report['decision'], 'stop_without_input')
        self.assertFalse(report['completion_verified'])
        self.assertEqual(report['investment_badge_declarations'], badge_declarations(scene))
        payload = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(local_only, payload)
        self.assertNotIn('获得1个【昼之半神星徽】', payload)
        self.assertEqual(window.mock_calls, [])
