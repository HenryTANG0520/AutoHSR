import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from autohsr.config import Settings, RESOURCE_ROOT
from autohsr.models import AutomationError, RunReport, Scene
from autohsr.recovery import BattleBudget, recovery_state
from autohsr.vision import Vision
from autohsr.workflows import DailyWorkflow
from autohsr.planar_resources import payment, limit_batch
from autohsr.tests.test_du_team import fixture


class PlanarResourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision = Vision()

    def workflow(self, page):
        ctx = SimpleNamespace(settings=Settings(dungeon_category='planar', challenge_count=5),
                              report=RunReport(), planar_payment=self.vision.planar_payment,
                              template=lambda s,n,r,threshold: self.vision.template(s,RESOURCE_ROOT/'assets/templates'/(n+'.png'),r,threshold)
                              if s.image is not None and (RESOURCE_ROOT/'assets/templates'/(n+'.png')).exists() else None)
        return DailyWorkflow(ctx)

    def test_native_mixed_price_separately_verifies_four_tokens_and_forty_stamina(self):
        page = fixture('planar_mixed_payment')
        flow = self.workflow(page)
        self.assertEqual(payment(flow, page), (40, 4))
        self.assertEqual(limit_batch(flow, page, 40)[1], 200)
        with self.assertRaisesRegex(AutomationError,'次数在选队后'):
            payment(flow,page,expected_count=6)
        self.assertEqual(payment(self.workflow(fixture('planar_preparation')), fixture('planar_preparation')), (40, 0))
        flow.ctx.planar_payment = lambda _: dict(stamina=40, immersifiers=3)
        with self.assertRaises(AutomationError):
            payment(flow, page)

    def test_unaffordable_intermediate_count_can_be_decreased_but_cannot_start(self):
        page=fixture('planar_mixed_payment')
        flow=self.workflow(page)
        flow._available=Mock(return_value=0)
        with self.assertRaises(AutomationError):
            payment(flow,page)
        self.assertEqual(payment(flow,page,require_affordable=False),(40,4))

    def test_native_stamina_only_intermediate_price_with_animated_glow(self):
        page=fixture('planar_two_stamina')
        self.assertEqual(payment(self.workflow(page),page),(80,0))

    def test_marginal_stamina_icon_requires_both_layout_templates_at_same_position(self):
        from autohsr.models import Token
        page=fixture('planar_two_stamina')
        for second,valid in [((.765,.911,.89),True),(None,False),((.80,.911,.89),False)]:
            with self.subTest(second=second):
                def match(scene,path,roi,threshold):
                    if threshold!=.88:
                        return None
                    return (.764,.911,.885) if path.stem=='planar_stamina_cost' else second
                with patch.object(self.vision,'template',side_effect=match), \
                     patch.object(self.vision,'_read_field',return_value=Token('80',.99,(0,0,1,1))):
                    if valid:
                        self.assertEqual(payment(self.workflow(page),page),(80,0))
                    else:
                        with self.assertRaises(AutomationError):
                            payment(self.workflow(page),page)

    def test_count_button_hover_is_cleared_once_then_fresh_icon_is_required(self):
        from autohsr.tests.test_core import FakeContext
        from autohsr.models import Token
        hover=fixture('planar_two_stamina')
        normal=Scene(hover.tokens,hover.image)
        final=Scene([Token(t.text.replace('挑战次数2','挑战次数3').replace('×80','×120'),t.score,t.box)
                     for t in normal.tokens],normal.image)
        class Context(FakeContext):
            def move(self,scene,point):
                super().move(scene,point)
                self._advance()
        for found in (True,False):
            with self.subTest(found=found):
                context=Context([hover,normal,final],Settings(dungeon_category='planar',challenge_count=3,rounds=3))
                context.planar_payment=Mock(return_value=dict(stamina=120,immersifiers=0))
                flow=DailyWorkflow(context)
                flow._icon=Mock(side_effect=[None,(.96,.83) if found else None])
                if found:
                    self.assertEqual(limit_batch(flow,hover,120),(final,120))
                    self.assertEqual(context.clicks,[(.96,.83)])
                else:
                    with self.assertRaisesRegex(AutomationError,'次数按钮'):
                        limit_batch(flow,hover,120)
                    self.assertEqual(context.clicks,[])
                self.assertEqual(context.moves,[(.70,.68)])

    def test_dim_auto_is_observation_only_instead_of_a_toggle(self):
        import cv2
        for name in ('planar_disabled_auto', 'planar_disabled_stage'):
            page = fixture(name)
            for image in (page.image, cv2.resize(page.image,(3840,2160))):
                page.image=image
                flow = self.workflow(page)
                flow.ctx.click = Mock()
                self.assertEqual(flow._auto_state(page)[0], 'disabled')
                self.assertFalse(flow._enable_auto(page))
                flow.ctx.click.assert_not_called()
        self.assertEqual(flow._auto_state(Scene([])), (None, None))

    def test_immersifier_reservation_blocks_restart_until_unique_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            report = RunReport()
            settings = Settings(dungeon_category='planar', stamina_limit=40)
            budget = BattleBudget(Path(folder), settings, report)
            budget.begin()
            budget.reserve(40, immersifiers=4)
            self.assertTrue(recovery_state(Path(folder))['blocked'])
            with self.assertRaises(AutomationError):
                budget.reserve(0, immersifiers=1)
            with self.assertRaises(AutomationError):
                budget.confirm(40, immersifiers=3)
            budget.confirm(40, immersifiers=4)
            report.status = 'success'
            budget.finish()
            self.assertEqual((report.stamina_spent, report.immersifiers_spent), (40, 4))
            self.assertFalse(recovery_state(Path(folder))['blocked'])

    def test_free_token_only_batch_still_has_a_durable_pending_intent(self):
        with tempfile.TemporaryDirectory() as folder:
            report = RunReport()
            budget = BattleBudget(Path(folder), Settings(dungeon_category='planar'), report)
            budget.begin()
            budget.reserve(0, immersifiers=2)
            self.assertTrue(recovery_state(Path(folder))['blocked'])
            budget.confirm(0, immersifiers=2)
            self.assertEqual(report.stamina_spent, 0)
            self.assertEqual(report.immersifiers_spent, 2)
