"""Exercise the read-only five-column supply layout and reject incomplete frames."""
import unittest
from dataclasses import replace

import numpy as np

from autohsr.currency_wars_supply_fields import rows
from autohsr.currency_wars_supply_observation import read_double_supply
from autohsr.models import Scene, Token
from autohsr.tests import test_currency_wars_encounter as read_only_tests


CENTERS = (.13, .315, .5, .685, .87)
ROLES = ('海瑟音', '长夜月', '镜流', '白厄', '真理医生')
UPPER = ('幸运星', '以太钻头', '和平手枪', '轮滑鞋', '红钻')
LOWER = ('折叠小刀', '光能电池', '生命之花', '量产型装甲', '红钻')


def token(text, x, y, *, width=.02, confidence=.99):
    return Token(text, confidence, (x - width, y - .013, x + width, y + .013))


def paint(image, box, shade=240):
    h, w = image.shape[:2]
    left, top, right, bottom = box
    image[round(top * h):round(bottom * h), round(left * w):round(right * w)] = shade


def supply(*, selected=None, single=False):
    image = np.full((540, 960, 3), 40, np.uint8)
    tokens = [token('补给阶段', .5, .15), token('返回备战界面', .93, .043, width=.041),
              token(f'已选择{int(selected is not None)}/1', .883, .857),
              token('确认', .9, .913), token('剩余次数：0', .746, .91)]
    for center, role, first, second in zip(CENTERS, ROLES, UPPER, LOWER):
        tokens.extend((token(role, center - .049, .525 if single else .477),
                       token(first, center, .641 if single else .598)))
        if not single:
            tokens.append(token(second, center, .695))
    if selected is not None:
        center = CENTERS[selected - 1]
        paint(image, (center - .072, .585, center + .072, .733))
        for edge in (center - .085, center + .085):
            paint(image, (edge - .002, .546, edge + .002, .765))
        paint(image, (.833, .899, .97, .923))
    return Scene(tokens, image=image)


class DoubleSupplyObservationTests(unittest.TestCase):
    def test_two_equipment_rows_preserve_order_duplicates_and_unmapped_names(self):
        data = read_double_supply(supply())
        self.assertEqual(data['layout'], 'five_cards_two_equipment_rows')
        self.assertEqual((data['selected_count'], data['selected_slot'], data['confirm_state'],
                          data['refresh_remaining']), (0, None, 'disabled', 0))
        self.assertEqual([card['character'] for card in data['cards']], list(ROLES))
        self.assertEqual([[item['text'] for item in card['equipment']] for card in data['cards']],
                         [list(pair) for pair in zip(UPPER, LOWER)])
        self.assertEqual([item['catalog_id'] for item in data['cards'][-1]['equipment']], [None, None])
        self.assertEqual([item['catalog_id'] for item in data['cards'][3]['equipment']], ['shoe', 'armor'])

    def test_selection_requires_white_card_edges_body_and_active_confirmation(self):
        scene = supply(selected=4)
        observed = read_double_supply(scene)
        self.assertEqual((observed['selected_count'], observed['selected_slot'], observed['confirm_state']),
                         (1, 4, 'enabled'))
        paint(scene.image, (.765, .546, .777, .765), shade=40)
        observed = read_double_supply(scene)
        self.assertEqual((observed['selected_count'], observed['selected_slot'], observed['confirm_state']),
                         (1, None, 'unknown'))

    def test_incomplete_or_conflicting_labels_never_fill_another_position(self):
        for changed in (None, token('生命之花', .5, .695, confidence=.64),
                        token('生命之花', .59, .695), token('生命之花', .5, .648),
                        token('生命之花、幸运星', .5, .695)):
            with self.subTest(changed=changed):
                scene = supply()
                scene.tokens = [item for item in scene.tokens if item.text != '生命之花']
                if changed is not None:
                    scene.tokens.append(changed)
                self.assertIsNone(read_double_supply(scene))

    def test_single_gear_old_reader_and_unsupported_shape_remain_separate(self):
        regular = supply(single=True)
        self.assertEqual(len(rows(regular)), 5)
        self.assertIsNone(read_double_supply(regular))
        double = supply()
        self.assertIsNone(read_double_supply(replace(double, image=double.image[:, 100:-100])))
        self.assertEqual(len(rows(double)), 5)

    def test_formal_read_only_report_has_no_input_and_leaves_overflow_separate(self):
        def cli(scene):
            case = read_only_tests.EncounterTests()
            try:
                return case.cli_report(scene)
            finally:
                case.doCleanups()

        scene = supply(selected=4)
        report = cli(scene)
        self.assertEqual(report['page_kind'], 'supply_selection')
        self.assertEqual(report['double_supply']['selected_slot'], 4)
        self.assertNotIn('reward_effect', report)
        scene.tokens.append(token('备战席已满，请出售角色或提升等级', .54, .492, width=.098))
        self.assertNotIn('double_supply', cli(scene))
