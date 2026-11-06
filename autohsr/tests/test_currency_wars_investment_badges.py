"""Badge declaration recognition through the read-only Currency Wars report."""
from dataclasses import replace
import json
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars import CurrencyWarsWorkflow
from autohsr.currency_wars_investment_badges import parse_badge_declaration, read_grail_gold_receipt
from autohsr.currency_wars_investment_policy import badge_declarations, choose, option_digest, options
from autohsr.models import AutomationError, Scene, Token


def fixture(name='investment_plane3'):
    path = Path(__file__).parent / 'fixtures' / f'currency_wars_{name}.json'
    tokens = json.loads(path.read_text(encoding='utf-8'))['tokens']
    return Scene([Token(t['text'], t['score'], tuple(t['box'])) for t in tokens], captured_at=time.monotonic())


def grail_candidate():
    scene = fixture()
    old_name = next(t for t in scene.tokens if t.text == '昼之半神星徽套组')
    scene.tokens = [t for t in scene.tokens if not t.within((.115, .478, .365, .705))]
    scene.tokens[scene.tokens.index(old_name)] = replace(old_name, text='都是这家伙的错！')
    scene.tokens.extend([
        Token('获得【命运圣杯星徽】和10金', .97, (.151, .480, .322, .512)),
        Token('币。若未完美通关战斗且有携', .98, (.152, .509, .319, .540)),
        Token('带该星徽的角色参战，后续有条件。', .98, (.151, .538, .319, .563)),
    ])
    scene.image = np.zeros((540, 960, 3), np.uint8)
    return scene


def grail_gold_chip():
    image = np.zeros((540, 960, 3), np.uint8)
    image[400:444, 762:854] = (105, 200, 104)
    image[424:441, 793:810] = (36, 140, 245)
    labels = [
        Token('备战阶段', .99, (.224, .030, .267, .057)),
        Token('3-2', .99, (.229, .054, .262, .089)),
        Token('前台区域', .99, (.476, .269, .525, .301)),
        Token('后台区域', .99, (.476, .517, .525, .549)),
        Token('购买经验', .99, (.128, .783, .182, .817)),
        Token('出战', .99, (.930, .676, .966, .713)),
        Token('67', .99, (.847, .835, .871, .868)),
        Token('都是这家伙的错！', .99, (.799, .752, .886, .780)),
        Token('10', .99, (.829, .779, .865, .812)),
    ]
    return Scene(labels, image=image, captured_at=time.monotonic())


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

    def test_single_badge_declaration_has_only_the_printed_amount_and_does_not_change_policy(self):
        scene = grail_candidate()
        choices = options(scene)
        old_digest = option_digest(choices)
        entry = badge_declarations(scene)[0]
        self.assertEqual(entry, dict(slot=0, title='都是这家伙的错', badge='命运圣杯星徽',
                                     badge_count=None, other_rewards=(('金币', 10),), selection_state='unverified',
                                     status='delivery_unverified', delivery_verified=False))
        height, width = scene.image.shape[:2]
        x = choices[0].name.center[0]
        y_range = slice(round(.198*height), round(.722*height))
        grail_border = scene.image[y_range, round((x-.106)*width):round((x-.103)*width)]
        grail_border[:] = 245
        scene.image[round(.892*height):round(.925*height), round(.43*width):round(.57*width)] = 240
        self.assertEqual(badge_declarations(scene)[0]['selection_state'], 'selected')
        x = choices[1].name.center[0]
        scene.image[y_range, round((x-.106)*width):round((x-.103)*width)] = 245
        self.assertEqual(badge_declarations(scene)[0]['selection_state'], 'unverified')
        grail_border[:] = 0
        self.assertEqual(badge_declarations(scene)[0]['selection_state'], 'other_selected')
        self.assertEqual(option_digest(options(scene)), old_digest)
        self.assertIsNone(options(scene)[0].kind)
        self.assertEqual(choose(options(scene), 'default').name.text, '保守派')

    def test_single_badge_opening_requires_exact_title_effect_boundary_and_same_column(self):
        for change in ('bad_name', 'bad_badge', 'bad_amount', 'missing_boundary', 'cross_column', 'distant_row', 'low_score'):
            with self.subTest(change=change):
                scene = grail_candidate()
                index = next(i for i,t in enumerate(scene.tokens) if t.text.startswith('获得【命运'))
                first, second = scene.tokens[index:index+2]
                if change == 'bad_name':
                    scene.tokens = [replace(t, text='都是这家伙的功劳！') if t.text.startswith('都是') else t
                                    for t in scene.tokens]
                elif change == 'bad_badge':
                    scene.tokens[index] = replace(first, text=first.text.replace('命运', '追击'))
                elif change == 'bad_amount':
                    scene.tokens[index] = replace(first, text=first.text.replace('10', '100'))
                elif change == 'missing_boundary':
                    scene.tokens[index+1] = replace(second, text='币若未完美通关战斗')
                elif change == 'cross_column':
                    scene.tokens[index+1] = replace(second, box=(.415, .509, .559, .540))
                elif change == 'distant_row':
                    scene.tokens[index+1] = replace(second, box=(.152, .569, .319, .600))
                else:
                    scene.tokens[index] = replace(first, score=.84)
                self.assertNotIn('命运圣杯星徽', [d['badge'] for d in badge_declarations(scene)])

    def test_named_gold_receipt_is_separate_from_wallet_and_badge_delivery(self):
        scene = grail_gold_chip()
        expected = dict(title='都是这家伙的错', node='3-2', gold_received=10, wallet=67,
                        badge_delivery_verified=False)
        self.assertEqual(read_grail_gold_receipt(scene), expected)
        window = Mock()
        context = Context(Runner(Settings(), operation='currency_wars'), window, Mock())
        context.last_scene = scene
        context.snapshot = Mock(return_value=scene)
        context.evidence = Mock(return_value=Path('offline-grail-gold.png'))
        with patch('autohsr.currency_wars_replay.save_sample', return_value=Path('offline-grail-gold.sample.json')):
            CurrencyWarsWorkflow(context).inspect()
        report = context.report.currency_wars
        self.assertEqual(report['investment_badge_gold_receipt'], expected)
        self.assertEqual(report['decision'], 'stop_without_input')
        self.assertFalse(report['completion_verified'])
        self.assertEqual(window.mock_calls, [])

    def test_gold_receipt_rejects_other_chip_wrong_page_overlap_and_conflicting_digits(self):
        for change in ('other_title', 'double_title', 'wrong_page', 'wide_amount', 'wrong_amount', 'double_amount',
                       'weak_amount', 'no_green_chip', 'split_chip', 'no_coin', 'node_conflict'):
            with self.subTest(change=change):
                scene = grail_gold_chip()
                title, amount = scene.tokens[-2:]
                if change == 'other_title':
                    scene.tokens[-2] = replace(title, text='剩余价值')
                elif change == 'double_title':
                    scene.tokens.append(replace(title, text='剩余价值'))
                elif change == 'wrong_page':
                    scene.tokens = [*fixture().tokens, title, amount]
                elif change == 'wide_amount':
                    scene.tokens[-1] = replace(amount, box=(.811, .779, .869, .813))
                elif change == 'wrong_amount':
                    scene.tokens[-1] = replace(amount, text='11')
                elif change == 'double_amount':
                    scene.tokens.append(replace(amount, text='11'))
                elif change == 'weak_amount':
                    scene.tokens[-1] = replace(amount, score=.84)
                elif change == 'no_green_chip':
                    scene.image[:] = 0
                elif change == 'split_chip':
                    scene.image[414:422, 760:856] = 0
                elif change == 'no_coin':
                    scene.image[424:441, 793:810] = (105, 200, 104)
                else:
                    scene.tokens.append(Token('3-3', .99, (.231, .058, .263, .090)))
                self.assertIsNone(read_grail_gold_receipt(scene))

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
