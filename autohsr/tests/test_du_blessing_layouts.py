import unittest
from unittest.mock import Mock,patch
import cv2
import numpy as np
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.du_strategy import blessing_columns,blessing_recommendation,same_blessing_titles
from autohsr.models import RunReport,Scene,Token


class BlessingLayoutsTests(unittest.TestCase):
    @staticmethod
    def native():
        from autohsr.tests.test_du_runtime import DuRuntimeTests
        return DuRuntimeTests.optional_device_fixture('blessing_two_choices')

    def test_native_two_choices_are_complete_across_resolutions_and_retain_marker_priority(self):
        source=self.native()
        for width in (960,1280,1920,3840):
            page=Scene(source.tokens,cv2.resize(source.image,(width,round(width*9/16))))
            columns=blessing_columns(page)
            self.assertEqual(len(columns),2)
            self.assertEqual(DifferentialUniverseWorkflow._choice_identity(page,'blessing_choice'),
                             ('唇须','顺序写入的轨道'))
            self.assertEqual([bool(blessing_recommendation(page,(a+b)/2)) for a,b in columns],[True,False])

    def test_native_two_card_selection_previews_only_real_cards_and_selects_recommended_one(self):
        page=self.native();ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'blessing_choice'))
        flow._click=Mock(return_value=(page,'blessing_choice'))
        self.assertEqual(flow._select_blessing(page),(page,'blessing_choice'))
        self.assertEqual(flow.report['reward_decisions'][-1]['selected'],'唇须')
        self.assertEqual(len(flow.report['reward_decisions'][-1]['candidates']),2)
        self.assertEqual([round(c.args[1].center[0],3) for c in flow._click.call_args_list],[.375,.625,.375])

    def test_missing_title_in_a_three_slot_page_does_not_shrink_it_to_two(self):
        from autohsr.tests.test_du_strategy import page as fixture
        original,_=fixture('none')
        partial=Scene([t for t in original.tokens if not t.within((.39,.35,.61,.54))],original.image)
        self.assertEqual(len(blessing_columns(partial)),3)
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(side_effect=[(original,'blessing_choice'),(original,'blessing_choice')])
        self.assertIs(flow._settle_blessing_titles(partial),original)
        self.assertEqual(flow._snapshot.call_count,2)

    def test_single_frame_layout_requires_no_other_visible_title(self):
        image=np.zeros((540,960,3),np.uint8)
        cv2.rectangle(image,(376,120),(584,423),(190,190,190),2)
        one=Scene([Token('单张祝福',.99,(.45,.46,.55,.49))],image)
        self.assertEqual(len(blessing_columns(one)),1)
        self.assertEqual(DifferentialUniverseWorkflow._choice_identity(one,'blessing_choice'),('单张祝福',))
        one.tokens.append(Token('仍在滑入的祝福',.99,(.20,.46,.30,.49)))
        self.assertEqual(len(blessing_columns(one)),3)

    def test_title_pixel_corroboration_uses_every_card_and_rejects_a_changed_group(self):
        page=self.native()
        self.assertTrue(same_blessing_titles(page,page))
        changed=page.image.copy();h,w=changed.shape[:2]
        changed[round(.45*h):round(.495*h),round(.53*w):round(.72*w)]=0
        self.assertFalse(same_blessing_titles(page,Scene(page.tokens,changed)))

    def test_native_title_refinement_does_not_create_phantom_third_column_fragments(self):
        from autohsr.vision import Vision
        page=self.native();names=DifferentialUniverseWorkflow._choice_identity(page,'blessing_choice')
        vision=Vision();vision.read=Mock(side_effect=AssertionError('Both titles already exist'))
        vision.refine_du_blessing_names(page)
        self.assertEqual(DifferentialUniverseWorkflow._choice_identity(page,'blessing_choice'),names)
