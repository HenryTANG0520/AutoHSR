import unittest
from autohsr.tests.test_du_team import fixture
from autohsr.models import AutomationError, Scene, Token
from autohsr.planar_team import preparation, selection, entry, preset, enabled, guard_click


class PlanarPresetTests(unittest.TestCase):
    def test_native_preparation_and_preset_have_different_layout_from_du(self):
        page = fixture('planar_preparation')
        listing = fixture('planar_preset_list')
        self.assertTrue(preparation(page))
        self.assertFalse(selection(page))
        self.assertTrue(selection(listing))
        guard_click(page, entry(page), 'planar_team_open', '哈哈哈哈')
        target = preset(listing, '哈哈哈哈')
        self.assertIsNotNone(target)
        guard_click(listing, target, 'planar_team_select', '哈哈哈哈')
        with self.assertRaises(AutomationError):
            guard_click(listing, preset(listing, '追击'), 'planar_team_select', '哈哈哈哈')
        with self.assertRaises(AutomationError):
            entry(listing)
        with self.assertRaises(AutomationError):
            entry(fixture('periodic_setup'))

    def test_four_level_labels_and_same_row_enabled_badge_are_required(self):
        self.assertTrue(enabled(fixture('planar_preset_enabled'), '哈哈哈哈'))
        page = fixture('planar_preset_list')
        self.assertFalse(enabled(page, '哈哈哈哈'))
        y = preset(page, '哈哈哈哈').center[1]
        page.tokens.append(Token('已启用', .99, (.25, y-.01, .28, y+.01)))
        self.assertTrue(enabled(page, '哈哈哈哈'))
        page.tokens.remove(next(t for t in page.tokens if t.text.startswith('等级') and t.within((.02, y+.08, .29, y+.16))))
        self.assertFalse(enabled(page, '哈哈哈哈'))
        self.assertFalse(enabled(Scene([]), '哈哈哈哈'))
