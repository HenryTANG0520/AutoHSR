import json,unittest
from pathlib import Path
import cv2,numpy as np
from autohsr.models import Scene,Token,AutomationError
from autohsr.du_events import option_stars,preferred_option,action
from autohsr.policy import guard_differential_universe_click


def sample():
    root=Path(__file__).parent/'fixtures/du_runtime'
    data=json.loads((root/'event_star_choices.json').read_text('utf8'))
    return Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in data['tokens']],
                 cv2.imread(str(root/'event_star_choices.png')))


class DuEventStarTests(unittest.TestCase):
    def test_native_three_stars_choose_smallest_negative_curio_count_at_multiple_sizes(self):
        page=sample()
        for width in (960,1280,1920):
            with self.subTest(width=width):
                page.image=cv2.resize(page.image,(width,round(width*9/16)))
                stars=option_stars(page)
                self.assertEqual(len(stars),3)
                self.assertEqual(preferred_option(page),stars[0])
                target,intent=action(page)
                self.assertEqual(intent,'event_star_select')
                guard_differential_universe_click(page,target,intent=intent)
                with self.assertRaises(AutomationError):
                    guard_differential_universe_click(page,stars[-1],intent=intent)

    def test_user_authorized_star_fallback_does_not_require_readable_option_text(self):
        page=sample()
        page.tokens=[t for t in page.tokens if t.within((0,0,.32,.13))]
        self.assertEqual(action(page)[0].center[1],option_stars(page)[0].center[1])
        target,intent=action(page)
        guard_differential_universe_click(page,target,intent=intent)

    def test_selection_keeps_pointer_clear_of_the_star_detector_region(self):
        page=sample()
        target,intent=action(page)
        star=preferred_option(page)
        self.assertEqual(target.center[1],star.center[1])
        self.assertGreater(target.box[0],.735)
        self.assertLess(target.box[2],.99)
        guard_differential_universe_click(page,target,intent=intent)

    def test_stars_require_event_heading_and_reject_blank_or_non_event_pixels(self):
        page=sample()
        self.assertEqual(option_stars(Scene([],page.image)),[])
        self.assertEqual(option_stars(Scene(page.tokens,np.zeros_like(page.image))),[])
        self.assertEqual(option_stars(Scene(page.tokens)),[])
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(Scene(page.tokens),option_stars(page)[0],intent='event_star_select')

    def test_gray_disabled_looking_stars_do_not_become_selectable_gold_rows(self):
        page=sample()
        page.image=cv2.cvtColor(cv2.cvtColor(page.image,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        self.assertEqual(option_stars(page),[])

    def test_confirm_is_bound_to_preferred_star_row(self):
        page=sample()
        confirm=Token('确定',.99,(.88,.395,.92,.425))
        page.tokens.append(confirm)
        self.assertEqual(action(page),(confirm,'event_star_confirm'))
        guard_differential_universe_click(page,confirm,intent='event_star_confirm')
        other=Token('确定',.99,(.88,.55,.92,.57))
        page.tokens[-1]=other
        self.assertEqual(action(page)[1],'event_star_select')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,other,intent='event_star_confirm')

    def test_observed_external_resource_costs_are_not_authorized_by_stars(self):
        page=sample()
        rows=option_stars(page)
        page.tokens=[t for t in page.tokens if not t.within((.68,.31,.99,.70))]
        for row in rows:
            y=row.center[1]+.04
            page.tokens.append(Token('消耗星琼',.99,(.74,y-.01,.90,y+.01)))
        self.assertIsNone(action(page))
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,rows[0],intent='event_star_select')


if __name__=='__main__':
    unittest.main()
