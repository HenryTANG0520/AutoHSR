from dataclasses import replace
import json
from pathlib import Path
import unittest

from autohsr.currency_wars_match import MatchState, Offer, read_match, verify_experience, verify_purchase, supplement_numbers
from autohsr.models import Scene, Token


class MatchReaderTests(unittest.TestCase):
    def test_compact_reward_badge_reads_only_its_node_without_stripping_icon_letters(self):
        import numpy as np
        from unittest.mock import Mock
        from autohsr.currency_wars_node import result_node
        s=self.fixture('node_result')
        s.tokens=[t for t in s.tokens if not t.within((.4,.24,.55,.30))]
        s.tokens.append(Token('1-1M奖励',.99,(.462,.25,.54,.28)))
        s.image=np.zeros((1440,2560,3),dtype=np.uint8)
        self.assertIsNone(result_node(s))
        reader=Mock(spec=['read','read_node'])
        reader.read.side_effect=[Scene([]),Scene([Token('1',.99,(0,0,1,1))])]
        reader.read_node.side_effect=[None,Token('1-1',.99,(0,0,1,1))]
        self.assertEqual(result_node(supplement_numbers(s,reader)),'1-1')

    def test_result_node_crop_excludes_decorative_icon_text(self):
        import numpy as np
        from unittest.mock import Mock
        from autohsr.currency_wars_node import result_node
        s=self.fixture('node_result')
        s.tokens=[t for t in s.tokens if not t.within((.4,.24,.47,.30))]
        s.tokens.append(Token('2-1X战斗',.99,(.41,.25,.49,.28)))
        s.image=np.zeros((1440,2560,3),dtype=np.uint8)
        self.assertIsNone(result_node(s))
        reader=Mock(spec=['read'])
        reader.read.return_value=Scene([Token('2-1',.99,(0,0,1,1))])
        self.assertEqual(result_node(supplement_numbers(s,reader)),'2-1')
        reader.read.return_value=Scene([Token('2-1X',.99,(0,0,1,1))])
        self.assertIsNone(result_node(supplement_numbers(s,reader)))
    def test_obscured_level_is_read_as_a_digit_in_its_own_field(self):
        import numpy as np
        from unittest.mock import Mock
        s=self.fixture('preparation')
        s.tokens=[Token('Lv.C',t.score,t.box) if t.text.lower().startswith('lv') else t for t in s.tokens]
        s.image=np.zeros((1440,2560,3),dtype=np.uint8)
        self.assertIsNone(read_match(s).level)
        reader=Mock(spec=['read','read_number'])
        reader.read.side_effect=[Scene([])]*3
        reader.read_number.return_value=Token('6',.99,(0,0,1,1))
        self.assertEqual(read_match(supplement_numbers(s,reader)).level,6)

    def test_single_digit_fallback_does_not_rewrite_the_combined_hud_text(self):
        import numpy as np
        from unittest.mock import Mock
        s=self.fixture('preparation')
        s.tokens=[t for t in s.tokens if not t.within((.43,.18,.55,.26))]
        s.tokens += [Token('i777',.99,(.44,.195,.535,.26))]
        s.image=np.zeros((1440,2560,3),dtype=np.uint8)
        reader=Mock(spec=['read','read_number'])
        reader.read.side_effect=[Scene([])]*6
        reader.read_number.side_effect=[Token('7',.99,(0,0,1,1)),Token('7',.99,(0,0,1,1))]
        self.assertEqual(read_match(supplement_numbers(s,reader)).deployment,(7,7))

    def test_direct_recognition_only_accepts_one_confident_numeric_field(self):
        from unittest.mock import Mock
        from autohsr.vision import Vision
        reader=Vision.__new__(Vision)
        reader.confidence=.65
        reader.engine=Mock()
        for result,expected in (([['7',.99]],'7'),([['i777',.99]],None),([['7',.84]],None),
                                ([['7',float('nan')]],None),([['7',.99],['8',.99]],None)):
            reader.engine.return_value=(result,[])
            token=reader.read_number(object())
            self.assertEqual(token.text if token else None,expected)

    def test_valid_deployment_does_not_gain_conflicting_crop_digits(self):
        import numpy as np
        from unittest.mock import Mock
        s = self.fixture('preparation')
        s.tokens = [t for t in s.tokens if '/' not in t.text or not t.within((.43,.18,.55,.36))]
        s.tokens.append(Token('i7/7', .99, (.46,.19,.54,.265)))
        s.image = np.zeros((1440,2560,3),dtype=np.uint8)
        reader = Mock(spec=['read'])
        reader.read.side_effect = [Scene([]), Scene([]),Scene([])]
        self.assertEqual(read_match(supplement_numbers(s,reader)).deployment,(7,7))
        self.assertEqual(reader.read.call_count,3)

    def test_slanted_capacity_uses_two_positioned_numbers_not_string_replacement(self):
        import numpy as np
        from unittest.mock import Mock
        s = self.fixture('preparation')
        s.tokens = [t for t in s.tokens if not t.within((.43,.18,.55,.26))]
        s.tokens += [Token('i616',.99,(.44,.195,.535,.26))]
        s.image = np.zeros((1440,2560,3),dtype=np.uint8)
        self.assertIsNone(read_match(s).deployment)
        for parts, expected in (([Token('6',.99,(.06,.1,.40,.89)),Token('6',.99,(.67,.1,.94,.84))],(6,6)),
                                ([Token('6',.99,(.06,.1,.40,.89))],None),
                                ([Token('6',.99,(.06,.1,.40,.89)),Token('5',.99,(.67,.1,.94,.84))],None)):
            reader = Mock(spec=['read'])
            reader.read.side_effect = [Scene([]),Scene([]),Scene([]),Scene(parts),Scene([]),Scene([])]
            self.assertEqual(read_match(supplement_numbers(s,reader)).deployment,expected)

    def fixture(self, page):
        path = Path(__file__).parent / 'fixtures/currency_wars_pages.json'
        return Scene([Token(**t) for t in json.loads(path.read_text(encoding='utf-8'))['pages'][page]['tokens']])

    def test_actual_preparation_ocr_has_capacity_experience_and_level(self):
        value = read_match(self.fixture('preparation'))
        self.assertEqual((value.node, value.level, value.experience, value.deployment, value.hp),
                         ('1-1', 3, (0, 4), (0, 3), 100))
        self.assertIsNone(value.gold)

    def test_actual_shop_reports_names_probabilities_and_missing_prices(self):
        value = read_match(self.fixture('shop'))
        self.assertEqual([(o.slot, o.name) for o in value.offers], [(0, '翡翠'), (2, '乱破'), (3, '阿格莱雅'), (4, '飞霄')])
        self.assertEqual(value.probabilities, (65, 25, 10, 0, 0))
        self.assertTrue(all(o.cost is None for o in value.offers))

    def test_desktop_toast_cannot_supply_a_digit_for_gold(self):
        scene = self.fixture('preparation')
        scene.tokens += [Token('1', .99, (.855, .84, .865, .86)), Token('Close', .99, (.9, .92, .94, .94))]
        self.assertIsNone(read_match(scene).gold)

    def test_conflicting_digits_or_low_confidence_never_become_balance(self):
        for tokens in ([Token('5', .99, (.855, .84, .865, .86)), Token('6', .99, (.855, .84, .865, .86))],
                       [Token('5', .64, (.855, .84, .865, .86))]):
            scene = self.fixture('preparation')
            scene.tokens += tokens
            self.assertIsNone(read_match(scene).gold)

    def test_other_pages_never_supply_match_fields(self):
        for page in ('tutorial', 'lobby', 'guide_applied', 'environment'):
            self.assertIsNone(read_match(self.fixture(page)))


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.offer = Offer(1, '椒丘', 1)
        self.before = MatchState('shop', '1-1', 5, 3, (0, 4), offers=(self.offer,))
        self.after = replace(self.before, gold=4, offers=())

    def test_purchase_requires_both_candidate_and_exact_gold_change(self):
        self.assertEqual(verify_purchase(self.before, self.after, self.offer), 'verified')
        for after in (replace(self.after, gold=None), replace(self.after, gold=3), replace(self.after, node='1-2'),
                      replace(self.after, offers=(self.offer,)), replace(self.after, page='unknown')):
            self.assertEqual(verify_purchase(self.before, after, self.offer), 'unknown')

    def test_missing_cost_or_balance_never_confirms_purchase(self):
        for before in (replace(self.before, gold=None), replace(self.before, offers=(replace(self.offer, cost=None),)),
                       replace(self.before, gold=0)):
            self.assertEqual(verify_purchase(before, self.after, before.offers[0]), 'unknown')

    def test_unchanged_feedback_is_not_success(self):
        self.assertEqual(verify_purchase(self.before, self.before, self.offer), 'unchanged')
        self.assertEqual(verify_experience(self.before, self.before), 'unchanged')

    def test_experience_rollover_and_partial_progress(self):
        self.assertEqual(verify_experience(self.after, replace(self.after, gold=0, level=4, experience=(0, 6))), 'verified')
        before = replace(self.after, level=4, experience=(0, 6))
        self.assertEqual(verify_experience(before, replace(before, gold=0, experience=(4, 6))), 'verified')
        for after in (replace(before, gold=0, experience=(3, 6)), replace(before, gold=None),
                      replace(before, gold=0, level=6), replace(before, gold=0, experience=None)):
            self.assertEqual(verify_experience(before, after), 'unknown')
