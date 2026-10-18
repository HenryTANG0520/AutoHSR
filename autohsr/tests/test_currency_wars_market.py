from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock,patch

import cv2
import numpy as np

from autohsr.currency_wars_market import purchase_choice,purchase_feedback,buy_offer
from autohsr.app import Context,Runner
from autohsr.config import Settings,RESOURCE_ROOT
from autohsr.currency_wars_experience import target_level
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.models import Token,AutomationError
from autohsr.tests.test_currency_wars_position import board
from autohsr.tests.test_currency_wars_shop import shop
from autohsr.tests import test_currency_wars_node as helpers


def market(gold=17):
    s=shop()
    s.image=board().image
    template=cv2.imread(str(Path(__file__).resolve().parents[2]/'assets/templates/currency_overclock_4_6.png'))
    if template is None:
        from autohsr.config import RESOURCE_ROOT
        template=cv2.imread(str(RESOURCE_ROOT/'assets/templates/currency_overclock_4_6.png'))
    s.image[1048:1084,312:354]=template
    s.tokens=[t for t in s.tokens if not t.within((.851,.829,.87,.868))]
    s.tokens.append(Token(str(gold),.99,(.852,.84,.867,.86)))
    for offer in read_match(s).offers:
        left=.301+.14*offer.slot
        s.tokens.append(Token('1',.99,(left,.27,left+.012,.30)))
    return s


class MarketTests(TestCase):
    def test_normal_flow_and_readonly_cannot_buy_without_explicit_whole_match_request(self):
        s=market()
        for operation,flag in [('currency_wars',True),('currency_wars_flow_test',False)]:
            c=Context(Runner(Settings(),operation=operation,currency_start_from_lobby=flag),Mock(),Mock())
            c.last_scene=s
            with self.assertRaises(AutomationError):
                c.currency_buy_offer(s,purchase_choice(s))
            with self.assertRaises(AutomationError):
                c.currency_open_shop(s)
            c.window.click.assert_not_called()

    def test_automatic_experience_requires_overclock_cash_reserve_and_explicit_request(self):
        s=board()
        s.image[1048:1084,312:354]=cv2.imread(str(RESOURCE_ROOT/'assets/templates/currency_overclock_4_6.png'))
        s.tokens=[Token('14',t.score,t.box) if t.text=='3' and t.within((.851,.829,.87,.868)) else
                  Token('2-1',t.score,t.box) if t.text=='1-1' else t for t in s.tokens]
        r=Runner(Settings(),currency_start_from_lobby=True)
        self.assertEqual(target_level(s,r),7)
        self.assertEqual(target_level(s,Runner(Settings())),0)
        s.tokens=[Token('13',t.score,t.box) if t.text=='14' else t for t in s.tokens]
        self.assertEqual(target_level(s,r),0)
        self.assertEqual(target_level(s,Runner(Settings(),currency_target_level=8)),8)
        s.tokens=[Token('14',t.score,t.box) if t.text=='13' else t for t in s.tokens]
        s.image[1048:1084,312:354]=0
        self.assertEqual(target_level(s,r),0)

    def test_only_affordable_recognized_roles_with_bench_space_are_selected(self):
        first=market()
        self.assertEqual(purchase_choice(first).name,'翡翠')
        self.assertIsNone(purchase_choice(market(10)))
        noise=np.random.default_rng(4)
        for slot in range(1,6):
            patch=_crop(first.image,bench_face(slot))
            patch[:]=noise.integers(0,255,patch.shape,dtype=np.uint8)
        self.assertIsNone(purchase_choice(first))

    def test_gold_card_and_bench_feedback_must_all_agree(self):
        first=market()
        offer=purchase_choice(first)
        after=market(16)
        left=.192+.14*offer.slot
        after.tokens=[t for t in after.tokens if not t.within((left,.265,left+.125,.305))]
        self.assertFalse(purchase_feedback(first,after,offer))
        patch=_crop(after.image,bench_face(1))
        patch[:]=np.random.default_rng(4).integers(0,255,patch.shape,dtype=np.uint8)
        self.assertTrue(purchase_feedback(first,after,offer))
        self.assertFalse(purchase_feedback(first,market(16),offer))
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[after])
            c.last_scene=first
            data=dict(actions=[])
            c.currency_buy_offer=Mock(side_effect=lambda *a:self.assertEqual(data['actions'][-1]['status'],'pending'))
            self.assertTrue(buy_offer(c,first,offer,data,lambda:None))
            self.assertEqual(data['actions'][0]['gold_after'],16)

    def test_unknown_purchase_never_retries(self):
        first=market()
        with tempfile.TemporaryDirectory() as directory:
            c=helpers.NodeWorkflowTests().context(directory,[first])
            c.last_scene=first
            c.currency_buy_offer=Mock()
            data=dict(actions=[])
            with patch('autohsr.currency_wars_market.time',SimpleNamespace(monotonic=Mock(side_effect=[0,13]))):
                self.assertFalse(buy_offer(c,first,purchase_choice(first),data,lambda:None))
            c.currency_buy_offer.assert_called_once()
            self.assertEqual(data['actions'][0]['status'],'unknown')
