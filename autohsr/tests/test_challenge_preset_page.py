"""Observe preset rows independently of the role tab and actual setup slots."""
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr import challenge_preset_page as page
from autohsr.challenge_roster import ASSET_ROOT
from autohsr.models import Scene, Token


def fixture(*, preset_tab=True, name='哈哈哈哈', offset=0, portrait='Pearl', captions=4, level='物竞天择其十'):
    image = np.full((1080, 1920, 3), 28, np.uint8)
    left, right = (299, 557) if preset_tab else (39, 296)
    image[111:154, left:right] = 226
    tokens = [
        Token('忘却之庭', .98, (.052, .036, .096, .061)),
        Token('编队', .98, (.052, .059, .082, .089)),
        Token('角色列表', .98, (.064, .114, .112, .139)),
        Token('预设编队', .98, (.199, .114, .246, .139)),
        Token(level, .98, (.330, .113, .435, .145)),
        Token('挑战目标', .98, (.329, .288, .382, .313)),
        Token('角色编队', .98, (.329, .608, .382, .638)),
        Token('建议属性', .98, (.571, .668, .623, .693)),
        Token('建议属性', .98, (.570, .772, .622, .799)),
        Token(name, .98, (.037, .175 + offset, .090, .199 + offset)),
        Token('没有角色无法战斗', .98, (.359, .423, .460, .450)),
    ]
    for center in (.054, .121, .189, .256)[:captions]:
        tokens.append(Token('等级80', .98, (center - .017, .310 + offset, center + .017, .334 + offset)))
    if portrait:
        sample = cv2.imdecode(np.frombuffer((ASSET_ROOT / (portrait + '.png')).read_bytes(), np.uint8),
                             cv2.IMREAD_COLOR)
        bottom = round((.310 + offset) * image.shape[0])
        start = 103 - sample.shape[1] // 2
        image[bottom - sample.shape[0]:bottom, start:start + sample.shape[1]] = sample
    return Scene(tokens, image, captured_at=time.monotonic())


def native_4k(scene, dx=0, dy=0):
    expanded = cv2.resize(scene.image, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    height, width = expanded.shape[:2]
    image = np.full_like(expanded, 28)
    image[dy:, dx:] = expanded[:height - dy, :width - dx]
    return Scene(scene.tokens, image, captured_at=time.monotonic())


class ChallengePresetPageTests(unittest.TestCase):
    def test_active_tab_requires_both_actual_styles(self):
        roles = fixture(preset_tab=False)
        self.assertEqual(page.observe(roles)['tab'], 'role_list')
        self.assertEqual(page.observe(roles)['rows'], [])
        roles.image[111:154, 299:557] = 226
        self.assertIsNone(page.observe(roles))

    def test_floor_and_two_teams_are_required_with_conflicting_caption_veto(self):
        self.assertIsNone(page.observe(fixture(level='物竞天择其十一')))
        scene = fixture()
        scene.tokens.append(Token('物竞天择其十一', .72, (.330, .113, .454, .145)))
        self.assertIsNone(page.observe(scene, .93))
        scene = fixture()
        scene.tokens = [token for token in scene.tokens if token.text != '建议属性' or token.box[1] < .7]
        self.assertIsNone(page.observe(scene))
        scene = fixture()
        scene.tokens.append(Token('是否退出', .72, (.40, .45, .55, .52)))
        self.assertIsNone(page.observe(scene))

    def test_row_and_four_physical_captions_are_separate_from_eight_actual_slots(self):
        first, second = (page.observe(fixture()) for _ in range(2))
        agreed = page.compare(first, second)
        row, = agreed['visible_presets']
        self.assertEqual(row['name'], '哈哈哈哈')
        self.assertEqual([slot['visible_level'] for slot in row['slots']], [80] * 4)
        self.assertEqual([slot['portrait_asset_id'] for slot in row['slots']], ['Pearl', None, None, None])
        self.assertIsNone(agreed['eight_slots_empty'])

    def test_repeated_and_cropped_fields_do_not_fill_another_position(self):
        scene = fixture(portrait=None, captions=1)
        scene.tokens.extend([scene.tokens[-1]] * 3)
        self.assertEqual(page.observe(scene)['rows'], [])
        scene = fixture(portrait=None, captions=1)
        row, = page.observe(scene)['rows']
        self.assertEqual([bool(slot['level']) for slot in row['slots']], [True, False, False, False])
        scene.tokens[-1] = Token('等级80', .99, (.037, .327, .071, .336))
        self.assertEqual(page.observe(scene)['rows'], [])

    def test_a_similar_name_or_two_exact_rows_are_not_an_exact_preset(self):
        self.assertEqual(page.observe(fixture(name='哈·哈哈哈', portrait=None))['rows'], [])
        scene = fixture(portrait=None)
        scene.tokens.append(Token('哈哈哈哈', .73, (.037, .366, .090, .389)))
        self.assertEqual(page.observe(scene, .93)['rows'], [])

    def test_scroll_or_tab_change_breaks_pair_and_conflicting_portrait_stays_unknown(self):
        first = page.observe(fixture())
        self.assertIsNone(page.compare(first, page.observe(fixture(offset=.04))))
        self.assertIsNone(page.compare(first, page.observe(fixture(preset_tab=False))))
        agreed = page.compare(first, page.observe(fixture(portrait='Tribbie')))
        self.assertIsNone(agreed['visible_presets'][0]['slots'][0]['portrait_asset_id'])

    def test_full_portrait_can_start_at_any_native_4k_pixel_phase(self):
        scene = fixture(portrait='Sunday', captions=1)
        for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
            with self.subTest(dx=dx, dy=dy):
                reading = page.observe(native_4k(scene, dx, dy))['rows'][0]['slots'][0]['portrait']
                self.assertEqual(reading['asset_id'], 'Sunday')
                self.assertEqual(reading['native_sample_phase'], [dx, dy])
                self.assertGreater(reading['score'], .999)

    def test_different_identities_across_phases_stay_ambiguous(self):
        scene = native_4k(fixture(captions=1))
        pearl = dict(asset_id='Pearl', box=[.028, .214, .080, .310], score=.99)
        rival = dict(pearl, asset_id='Tribbie', score=.945)
        with patch.object(page.roster, '_matches', side_effect=([pearl], [rival], [pearl], [])) as scan:
            slot = page.observe(scene)['rows'][0]['slots'][0]
        self.assertEqual(scan.call_count, 4)
        self.assertIsNone(slot['portrait'])


if __name__ == '__main__':
    unittest.main()
