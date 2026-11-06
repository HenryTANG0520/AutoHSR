"""Read-only station descriptions on masked historical captures."""
from dataclasses import replace
import unittest

from autohsr.du_station_preview import card_for_label, station_cards, station_effect_ink, station_preview_observation
from autohsr.models import AutomationError
from autohsr.policy import guard_differential_universe_click
from autohsr.tests import test_du_runtime
from autohsr.tests.test_du_station_policy import flow
from autohsr.tests.test_du_team import fixture


class StationPreviewObservationTests(unittest.TestCase):
    def test_native_three_card_sequence_binds_the_right_duplicate_and_reads_the_description(self):
        current = flow()
        for frame in (447, 450, 451):
            page = fixture(f'station_preview_three_{frame}')
            self.assertEqual(current._observe(page), 'station_choice')
        unselected, danger, forge = [row['station_preview'] for row in current.report['page_history']]
        self.assertEqual(unselected, dict(status='awaiting_selection', visible_card_count=3))
        self.assertEqual((danger['selected_column'], danger['selected_label']), (1, '战斗'))
        self.assertIsNone(danger['beacon_caption'])
        self.assertEqual((forge['visible_card_count'], forge['selected_column'], forge['selected_label']),
                         (3, 3, '铸造'))
        self.assertEqual(''.join(forge['body_text']), '在这个区域中可以获取和调整加权奇物，购买塔奥牌，购买区域强化和信标相关服务')
        self.assertEqual(forge['beacon_caption'], '暂无信标')
        current.ctx.click.assert_not_called()

    def test_ocr_without_body_pixels_or_the_selected_footer_does_not_prove_those_fields(self):
        page = fixture('station_preview_three_451')
        image = page.image.copy()
        image[76:178, 96:365] = 0
        observation = station_preview_observation(replace(page, image=image))
        self.assertIsNone(observation['body_text'])

        selected = station_cards(page)[2]
        tokens = [token for token in page.tokens if not (token.text == '铸造' and selected.holds_label(token))]
        self.assertTrue(any(token.text == '铸造' for token in tokens))
        self.assertIsNone(station_preview_observation(replace(page, tokens=tokens)))

    def test_native_four_card_danger_still_blocks_confirmation(self):
        page = fixture('station_explosion_beacon')
        observation = station_preview_observation(page)
        self.assertEqual((observation['visible_card_count'], observation['selected_column'],
                          observation['selected_label']), (4, 1, '战斗'))
        with self.assertRaisesRegex(AutomationError, '未点击'):
            guard_differential_universe_click(page, page.find('确定', exact=True), intent='station_confirm')

    def test_historical_description_observation_does_not_satisfy_the_input_gate(self):
        before = fixture('station_preview_three_450')
        after = fixture('station_preview_three_451')
        self.assertIsNone(station_effect_ink(after))
        cards = station_cards(before)
        target, = [token for token in before.tokens
                   if token.text == '铸造' and card_for_label(before, cards, token) == cards[2]]
        frames = [before, *(replace(after) for _ in range(7))]
        with test_du_runtime.DuRuntimeTests().captured_du_flow(frames) as (current, window):
            page = current.ctx.snapshot()
            with self.assertRaisesRegex(AutomationError, '未核实替代站点选中及新效果'):
                current._select_station_alternative(page, target)
            window.click.assert_called_once()
            self.assertEqual(current.report['page_history'][-1]['station_preview']['selected_column'], 3)
