"""Independent 4.6 phone fixture and synthetic contrasts for the event page."""
from dataclasses import replace
import time
import unittest

import numpy as np

from autohsr.daily_event_pages import OdysseyObservation, phone_journey_event_entry, read_gift_of_odyssey
from autohsr.models import Scene, Token
from autohsr.tests.test_du_team import fixture


VERSION = '4.6.0'


def _phone():
    return replace(fixture('phone_mail_icon'), captured_at=time.monotonic())


def _paint(image, bounds, bgr):
    height, width = image.shape[:2]
    left, top, right, bottom = (round(value * size) for value, size in zip(bounds, (width, height, width, height)))
    image[top:bottom, left:right] = bgr


def _odyssey():
    image = np.full((540, 960, 3), (72, 98, 115), np.uint8)
    for left, right in ((.588, .598), (.675, .685), (.763, .773)):
        _paint(image, (left, .416, right, .528), (213, 224, 235))
    for left, right in ((.675, .685), (.763, .773)):
        _paint(image, (left, .632, right, .745), (213, 224, 235))
    for left, right in ((.600, .677), (.687, .763), (.779, .875)):
        _paint(image, (left, .754, right, .793), (208, 227, 246))
    tokens = [
        Token('活动礼记', .94, (.052, .056, .106, .091)),
        Token('1活动说明', .95, (.884, .112, .960, .150)),
        Token('巡星之礼', .998, (.841, .155, .958, .209)),
        Token('巡星之礼', .91, (.030, .314, .076, .334)),  # List row, not the open page.
        Token('已领取', .89, (.535, .762, .568, .787)),
        Token('领取', .88, (.633, .761, .659, .785)),
        Token('领取', .95, (.719, .760, .746, .785)),
        Token('领取', .85, (.819, .760, .845, .785)),
    ]
    return Scene(tokens, image, captured_at=time.monotonic())


class JourneyEventEntryTests(unittest.TestCase):
    def read(self, scene, version=VERSION):
        return phone_journey_event_entry(scene, client_version=version)

    def test_native_redacted_phone_returns_its_original_caption(self):
        phone = _phone()
        caption = next(token for token in phone.tokens if token.text == '旅情事记')
        self.assertIs(self.read(phone), caption)
        self.assertIsNone(self.read(phone, '4.7.0'))

    def test_missing_phone_anchor_clipped_or_duplicate_caption_stays_unknown(self):
        phone = _phone()
        caption = next(token for token in phone.tokens if token.text == '旅情事记')
        for rows in (
                [token for token in phone.tokens if token.text != '合成'],
                [token for token in phone.tokens if token.text != '编队'],
                [replace(token, box=(.643, .485, .720, .510)) if token is caption else token for token in phone.tokens],
                [*phone.tokens, Token('旅情事记', .69, (.104, .101, .151, .125))]):
            with self.subTest(rows=len(rows)):
                self.assertIsNone(self.read(replace(phone, tokens=rows)))

    def test_modal_and_actual_activity_page_are_never_the_phone(self):
        phone = _phone()
        popup = Token('获得物品', .97, (.473, .144, .528, .178))
        self.assertIsNone(self.read(replace(phone, tokens=[*phone.tokens, popup])))
        self.assertIsNone(self.read(_odyssey()))


class GiftOfOdysseyTests(unittest.TestCase):
    def read(self, scene, version=VERSION, *, confidence=.65):
        return read_gift_of_odyssey(scene, client_version=version, confidence=confidence)

    def test_exact_page_separates_three_readable_active_cards_and_one_claimed(self):
        self.assertEqual(self.read(_odyssey()), OdysseyObservation((5, 6, 7), (4,), (1, 2, 3)))

    def test_day_positions_are_separate_with_top_row_and_full_height_card(self):
        scene = _odyssey()
        _paint(scene.image, (.512, .534, .590, .568), (209, 229, 248))
        scene.tokens.append(Token('领取', .92, (.543, .540, .569, .565)))
        self.assertEqual(self.read(scene), OdysseyObservation((1, 5, 6, 7), (4,), (2, 3)))

    def test_exact_labels_without_matching_same_card_pixels_are_unknown(self):
        scene = _odyssey()
        scene.tokens.append(Token('领取', .98, (.633, .540, .658, .564)))
        scene.tokens = [replace(token, text='已领取') if token.text == '领取' and token.center[0] > .8 else token
                        for token in scene.tokens]
        self.assertEqual(self.read(scene), OdysseyObservation((5, 6), (4,), (1, 2, 3, 7)))

    def test_card_conflict_weak_read_and_split_read_are_not_claimable(self):
        scene = _odyssey()
        scene.tokens.append(Token('已领取', .66, (.633, .764, .660, .788)))
        scene.tokens = [replace(token, score=.72) if token.text == '领取' and .7 < token.center[0] < .8 else token
                        for token in scene.tokens]
        scene.tokens = [token for token in scene.tokens if token.text != '领取' or token.center[0] < .8]
        scene.tokens.extend((Token('领', .97, (.818, .760, .830, .786)),
                             Token('取', .98, (.832, .760, .844, .786))))
        self.assertEqual(self.read(scene), OdysseyObservation((), (4,), (1, 2, 3, 5, 6, 7)))

    def test_wrong_version_or_other_activity_or_competing_title_is_rejected(self):
        scene = _odyssey()
        for version in (None, '4.6', '4.7.0'):
            with self.subTest(version=version):
                self.assertIsNone(self.read(scene, version))
        for label in ('巡光之礼', '庆典祝礼', '星际幻宠乐园', '镇伏贪饕'):
            with self.subTest(label=label):
                rows = [replace(token, text=label) if token.center[0] > .8 and token.text == '巡星之礼'
                        else token for token in scene.tokens]
                self.assertIsNone(self.read(replace(scene, tokens=rows)))
        scene.tokens.append(Token('星际幻宠乐园', .92, (.843, .156, .964, .213)))
        self.assertIsNone(self.read(scene))

    def test_popups_and_overlay_with_visible_background_do_not_report_cards(self):
        scene = _odyssey()
        for label in ('获得物品', '点击空白处关闭', '活动说明', '切换账号', '确认购买'):
            with self.subTest(label=label):
                popup = Token(label, .97, (.473, .144, .528, .178))
                self.assertIsNone(self.read(replace(scene, tokens=[*scene.tokens, popup])))
        self.assertIsNone(self.read(replace(scene, image=scene.image // 2)))

    def test_geometry_and_timestamp_are_observation_requirements(self):
        scene = _odyssey()
        self.assertIsNone(self.read(replace(scene, captured_at=time.monotonic() - 12)))
        self.assertIsNone(self.read(replace(scene, image=scene.image[:, :820])))
        self.assertIsNone(self.read(scene, confidence=float('nan')))
        self.assertIsNone(self.read(replace(scene, image=np.zeros_like(scene.image))))
        self.assertIsNone(self.read(replace(scene, tokens=None)))


if __name__ == '__main__':
    unittest.main()
