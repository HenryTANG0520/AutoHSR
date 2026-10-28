"""The standard shop has its own scope; overclock trial guards stay intact."""
import unittest
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from autohsr.currency_wars_standard_market import open_standard_shop, close_standard_shop
from autohsr.currency_wars_standard_flow import next_action, transition_ready
from autohsr.models import AutomationError, Scene, Token
from autohsr.currency_wars_match import read_match, supplement_shop_fields, verify_purchase, MatchState


class StandardMarketTests(unittest.TestCase):
    def setUp(self):
        self.state=SimpleNamespace(page='preparation',node='1-1',gold=5,hp=80,level=3)
        self.match=patch('autohsr.currency_wars_standard_market.read_match',return_value=self.state)
        self.trading_match=patch('autohsr.currency_wars_standard_trading.read_match',side_effect=lambda *args:self.state)
        self.layout=patch('autohsr.currency_wars_standard_market.backend_layout',return_value=(6,[]))
        self.mode=patch('autohsr.currency_wars_market.overclock_board',return_value=False)
        self.match.start(); self.layout.start(); self.mode.start(); self.trading_match.start()
        self.addCleanup(self.match.stop);self.addCleanup(self.layout.stop);self.addCleanup(self.mode.stop)
        self.addCleanup(self.trading_match.stop)

    def session(self):
        return dict(status='active',start_verified=True,entry=dict(rank_verified=True),account_key='a'*64,
                    account_verified_run='run',account_verified_epoch=0,rules_version='4.6',
                    client=dict(version='4.6',verified_run='run',input_epoch=0),
                    collection=dict(run_dir='run',input_epoch=0,complete=True))

    def frame(self):
        return Scene([Token('商店',.99,(.83,.89,.87,.93))])

    def test_metadata_roster_and_single_button_required_before_opening(self):
        session=self.session()
        self.assertEqual(open_standard_shop(self.frame(),session).text,'商店')
        for key,value in (('account_key',None),('start_verified',False),('account_verified_epoch',1)):
            changed={**session,key:value}
            with self.assertRaises(AutomationError):
                open_standard_shop(self.frame(),changed)
        session['client']['version']='4.7'
        with self.assertRaises(AutomationError):
            open_standard_shop(self.frame(),session)

    def test_overclock_visual_counterexample_blocks_standard_resume(self):
        with patch('autohsr.currency_wars_market.overclock_board',return_value=True):
            with self.assertRaises(AutomationError):
                open_standard_shop(self.frame(),self.session())

    def test_open_feedback_needs_same_node_money_life_and_level(self):
        from autohsr.currency_wars_standard_flow import StandardAction
        action=StandardAction('open_standard_shop','standard_shop_observe',self.frame().tokens[0],payload=('1-1',5,80,3))
        with patch('autohsr.currency_wars_match.read_match',return_value=SimpleNamespace(page='shop',node='1-1',gold=5,hp=80,level=3)):
            self.assertTrue(transition_ready(action,self.frame()))
        with patch('autohsr.currency_wars_match.read_match',return_value=SimpleNamespace(page='shop',node='1-1',gold=5,hp=None,level=3)):
            self.assertTrue(transition_ready(action,self.frame()))
        for node,gold,hp,level in (('1-2',5,80,3),('1-1',4,80,3),('1-1',5,79,3),('1-1',5,80,4)):
            with patch('autohsr.currency_wars_match.read_match',return_value=SimpleNamespace(page='shop',node=node,gold=gold,hp=hp,level=level)):
                self.assertFalse(transition_ready(action,self.frame()))

    def test_close_requires_matching_verified_open_and_fully_visible_board_feedback(self):
        from autohsr.currency_wars_standard_flow import StandardAction
        self.state.page='shop'
        self.state.hp=None
        session=self.session()
        session.update(pre_shop_snapshot=dict(node='1-1',gold=5,hp=80,level=3),
                       actions=[dict(action='open_standard_shop',status='verified')])
        scene=Scene([Token('收起',.99,(.83,.89,.87,.93))])
        self.assertEqual(close_standard_shop(scene,session).text,'收起')
        session['actions'].append(dict(action='close_standard_shop',status='pending'))
        self.assertEqual(close_standard_shop(scene,session).text,'收起')
        session['actions'].pop()
        choice=StandardAction('close_standard_shop','standard_shop_closed',scene.tokens[0],payload=('1-1',5,80,3))
        for hp,expected in ((None,False),(79,False),(80,True)):
            with patch('autohsr.currency_wars_match.read_match',return_value=MatchState('preparation',node='1-1',gold=5,hp=hp,level=3)):
                self.assertEqual(transition_ready(choice,scene),expected)
        session['actions'][-1]['status']='unknown'
        with self.assertRaises(AutomationError):
            close_standard_shop(scene,session)


class ShopFieldsTests(unittest.TestCase):
    def scene(self):
        data=json.loads((Path(__file__).parent/'fixtures/currency_wars_standard_shop.json').read_text(encoding='utf-8'))
        return Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in data['tokens']])

    def test_real_five_offers_and_observed_prices_do_not_infer_star_or_tier(self):
        from autohsr.currency_wars_state import snapshot_from_scene
        state=read_match(self.scene())
        self.assertEqual([(o.name,o.cost) for o in state.offers],
                         [('黑塔',1),('阿格莱雅',1),('藿藿',1),('黑塔',1),('乱破',1)])
        offers=snapshot_from_scene(self.scene(),0).offers
        self.assertTrue(all(o.star is None and o.tier is None and o.price==1 for o in offers))

    def test_price_variants_are_facts_while_legacy_purchase_scope_stays_limited(self):
        from dataclasses import replace
        state=self.scene()
        rois=[(.301+.14*i,.265,.317+.14*i,.305) for i in range(5)]
        state.tokens=[t for t in state.tokens if not any(t.within(roi) for roi in rois)]
        state.tokens += [Token(str(price),.99,roi) for price,roi in zip((0,6,12,99,1),rois)]
        observed=read_match(state)
        self.assertEqual(tuple(o.cost for o in observed.offers),(0,6,12,99,1))
        before=MatchState('shop',node='1-1',gold=10,offers=(observed.offers[1],))
        self.assertEqual(verify_purchase(before,replace(before,gold=4,offers=()),observed.offers[1]),'unknown')

    def test_missing_fields_need_agreeing_crop_variants(self):
        import numpy as np
        from unittest.mock import Mock
        state=self.scene()
        state.tokens=[t for t in state.tokens if t.text!='藿藿' and
                      not any(t.within((.301+.14*i,.265,.317+.14*i,.305)) for i in range(5))]
        state.image=np.zeros((1080,1920,3),dtype=np.uint8)
        state.image[round(.275*1080):round(.29*1080),round(.475*1920):round(.51*1920)]=240
        reader=Mock()
        reader.read_number.return_value=Token('1',.99,(0,0,1,1))
        reader.read_unit_name.return_value=Token('藿藿',.99,(0,0,1,1))
        refined=supplement_shop_fields(state,reader)
        self.assertEqual(len(read_match(refined).offers),5)
        self.assertEqual(reader.read_number.call_count,10)
        reader.read_unit_name.side_effect=[Token('藿藿',.99,(0,0,1,1)),Token('翡翠',.99,(0,0,1,1))]
        self.assertEqual(len(read_match(supplement_shop_fields(state,reader)).offers),4)


if __name__=='__main__':
    unittest.main()
