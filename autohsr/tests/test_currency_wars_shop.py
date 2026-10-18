import tempfile
from unittest import TestCase
from unittest.mock import Mock

from autohsr.currency_wars import observe
from autohsr.currency_wars_shop import close_shop_target,close_shop
from autohsr.models import AutomationError,Token
from autohsr.tests import test_currency_wars_node as helpers
from autohsr.tests.test_currency_wars_node import screen,prepared


def shop():
    s=screen('shop')
    s.tokens=[t for t in s.tokens if not t.within((.851,.829,.87,.868))]
    s.tokens += [Token('17',.99,(.852,.84,.867,.86))]
    return s


class ShopTests(TestCase):
    def test_color_square_prefix_is_valid_in_each_bounded_probability_field(self):
        s=shop()
        s.tokens=[Token('■'+t.text.lstrip('■□'),t.score,t.box) if '%' in t.text else t for t in s.tokens]
        self.assertEqual(observe(s,.65).page_kind,'shop')
        close_shop_target(s)
        s.tokens=[t for t in s.tokens if t.text!='收起']
        with self.assertRaises(AutomationError):
            close_shop_target(s)

    def test_close_observes_same_node_and_gold_without_any_purchase(self):
        with tempfile.TemporaryDirectory() as directory:
            first=shop()
            after=prepared()
            after.tokens=[t for t in after.tokens if not t.within((.851,.829,.87,.868))]
            after.tokens += [Token('17',.99,(.852,.84,.867,.86))]
            c=helpers.NodeWorkflowTests().context(directory,[after])
            c.last_scene=first
            data=dict(actions=[])
            c.currency_close_shop=Mock(side_effect=lambda s:self.assertEqual(data['actions'][-1]['status'],'pending'))
            self.assertTrue(close_shop(c,first,data,lambda:None))
            c.currency_close_shop.assert_called_once()
            self.assertEqual(data['actions'][-1]['status'],'verified')
