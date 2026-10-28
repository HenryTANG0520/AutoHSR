"""Policies respond to observed rosters/prices rather than a static fee table."""
from dataclasses import replace
import unittest

from autohsr.currency_wars_standard_policy import can_buy_experience, growth_target, rank_standard_offers
from autohsr.currency_wars_state import ShopOffer, StrategySnapshot, UnitState


def state(**changes):
    data = dict(page='preparation', mode='standard', node='1-1', gold=25, hp=80, level=3,
                experience=(0,6), capacity=3, bench_capacity=9, bench_occupied=0, roster_complete=True,
                roster=(UnitState('甲','front',1,1,1),UnitState('乙','back',1,1,1),UnitState('丙','back',2,1,1)))
    return StrategySnapshot(**dict(data, **changes))


class StandardPolicyTests(unittest.TestCase):
    def test_owned_deployment_can_include_the_observed_core_when_filling_vacancies(self):
        from autohsr.currency_wars_standard_deployment import choose_deployment
        units = tuple(UnitState(name,'bench',i,star,1,(),(),('front','back')) for i,(name,star) in
                      enumerate((('强角甲',2),('强角乙',2),('强角丙',2),('阿格莱雅',1)),1))
        snapshot = state(roster=units,bench_occupied=4)
        selected = []
        for index in range(3):
            unit,zone,_ = choose_deployment(snapshot,'aglaea')
            selected.append(unit.name)
            snapshot = replace(snapshot,roster=tuple(replace(u,zone=zone,slot=index+1) if u==unit else u for u in snapshot.roster),
                               bench_occupied=3-index)
        self.assertIn('阿格莱雅',selected)

    def test_named_core_and_supports_use_visible_price_without_inventing_tier(self):
        snapshot = state(offers=(ShopOffer(0,'阿格莱雅',price=12),ShopOffer(1,'藿藿',price=1)))
        ranked = rank_standard_offers(snapshot,'aglaea')
        self.assertEqual(ranked[0].name,'阿格莱雅')
        self.assertEqual(ranked[0].price,12)
        self.assertIsNone(snapshot.offers[0].tier)
        self.assertIsNone(snapshot.offers[0].star)
        snapshot = replace(snapshot,offers=(ShopOffer(0,'希儿',price=6),ShopOffer(1,'藿藿',price=1)))
        self.assertEqual(rank_standard_offers(snapshot,'seele')[0].name,'希儿')

    def test_reserve_space_unknown_prices_and_complete_roster_are_respected(self):
        offers = (ShopOffer(0,'阿格莱雅',price=1),)
        self.assertFalse(rank_standard_offers(state(gold=10,offers=offers),'aglaea'))
        self.assertTrue(rank_standard_offers(state(gold=10,hp=30,offers=offers),'aglaea'))
        self.assertFalse(rank_standard_offers(state(roster_complete=False,offers=offers),'aglaea'))
        full = state(roster=tuple(UnitState(str(i),'bench',i,1,1) for i in range(1,10)),
                     capacity=3,bench_occupied=9,offers=offers)
        self.assertFalse(rank_standard_offers(full,'aglaea'))
        self.assertFalse(rank_standard_offers(state(offers=(ShopOffer(0,'阿格莱雅'),)),'aglaea'))
        self.assertFalse(rank_standard_offers(state(gold=3,offers=(ShopOffer(0,'阿格莱雅',price=6),)),'aglaea'))
        self.assertTrue(rank_standard_offers(state(gold=0,offers=(ShopOffer(0,'阿格莱雅',price=0),)),'aglaea'))

    def test_default_can_fill_missing_names_and_does_not_buy_unrelated_bench_clutter(self):
        offer = ShopOffer(0,'任意新角色',price=1)
        self.assertFalse(rank_standard_offers(state(offers=(offer,))))
        snapshot = state(roster=(UnitState('甲','front',1,1,1),),offers=(offer,))
        self.assertEqual(rank_standard_offers(snapshot)[0].name,'任意新角色')
        core = UnitState('希儿','front',1,3,1)
        snapshot = state(roster=(core,),offers=(ShopOffer(0,'希儿',price=1),))
        self.assertFalse(rank_standard_offers(snapshot,'seele'))

    def test_whole_level_affordability_avoids_partial_experience_spending(self):
        self.assertTrue(can_buy_experience(state(gold=18)))
        self.assertFalse(can_buy_experience(state(gold=17)))  # 8 required, reserve 10.
        self.assertFalse(can_buy_experience(state(gold=7)))
        self.assertTrue(can_buy_experience(state(gold=8)))
        self.assertFalse(can_buy_experience(state(experience=None)))
        self.assertFalse(can_buy_experience(state(capacity=4)))  # Deploy before growing again.
        self.assertFalse(can_buy_experience(state(level=10)))

    def test_core_observation_controls_seele_and_aglaea_growth_phases(self):
        self.assertEqual(growth_target(state(),'seele'),6)
        for star, expected in ((1,7),(2,7),(3,9)):
            snapshot = state(roster=(UnitState('希儿','front',1,star,1),))
            self.assertEqual(growth_target(snapshot,'seele'),expected)
        self.assertEqual(growth_target(state(),'aglaea'),3)
        units = tuple(UnitState(name,'bench',i,3 if name=='阿格莱雅' else 1,1)
                      for i,name in enumerate(('阿格莱雅','风堇','缇宝','藿藿'),1))
        self.assertEqual(growth_target(state(roster=units,bench_occupied=4),'aglaea'),9)
        self.assertEqual(growth_target(state(roster=units[:-1],bench_occupied=3),'aglaea'),3)


if __name__ == '__main__':
    unittest.main()
