from unittest import TestCase

from autohsr.currency_wars_economy import Mode
from autohsr.currency_wars_match import Offer
from autohsr.currency_wars_strategy import PurchaseSituation,rank_purchases,score_purchase


class StrategyTests(TestCase):
    def test_completing_observed_trait_outweighs_fixed_roster_preference(self):
        offers=(Offer(0,'翡翠',2),Offer(1,'飞霄',2))
        state=PurchaseSituation(Mode.OVERCLOCK,20,5)
        result=rank_purchases(offers,state,traits={1:('追击',)},progress={'追击':(2,3)},preferences={'翡翠':8})
        self.assertEqual(result[0].name,'飞霄')
        self.assertIn(('羁绊适配候选:追击',40.),result[0].reasons)

    def test_verified_pair_upgrade_beats_new_trait_and_duplicates_do_not_add_unique_member(self):
        offers=(Offer(0,'翡翠',2),Offer(1,'飞霄',2))
        state=PurchaseSituation(Mode.OVERCLOCK,20,5,owned_names=frozenset({'翡翠'}),roster_complete=True)
        result=rank_purchases(offers,state,traits={0:('公司',),1:('追击',)},progress={'公司':(1,2),'追击':(2,3)},copies={'翡翠':2})
        self.assertEqual(result[0].name,'翡翠')
        self.assertFalse(any('公司' in label for label,_ in result[0].reasons))
        self.assertIn(('即将升星',70.),result[0].reasons)

    def test_unknown_stars_never_get_upgrade_bonus_and_missing_roster_never_claims_vacancy_gain(self):
        result=score_purchase(Offer(0,'翡翠',2),PurchaseSituation(Mode.OVERCLOCK,20,4,vacancies=1))
        labels={label for label,_ in result.reasons}
        self.assertNotIn('即将升星',labels)
        self.assertNotIn('补足上阵人数',labels)
        complete=score_purchase(Offer(0,'翡翠',2),PurchaseSituation(Mode.OVERCLOCK,20,4,vacancies=1,roster_complete=True))
        self.assertIn(('补足上阵人数',35.),complete.reasons)

    def test_cash_space_interest_and_low_health_change_the_decision(self):
        offer=Offer(0,'翡翠',1)
        self.assertIsNone(score_purchase(offer,PurchaseSituation(Mode.OVERCLOCK,10,3)))
        self.assertIsNone(score_purchase(offer,PurchaseSituation(Mode.OVERCLOCK,20,0)))
        urgent=score_purchase(offer,PurchaseSituation(Mode.OVERCLOCK,10,3,hp=30))
        self.assertIsNotNone(urgent)
        normal=score_purchase(offer,PurchaseSituation(Mode.OVERCLOCK,20,3))
        standard=score_purchase(offer,PurchaseSituation(Mode.STANDARD,20,3))
        self.assertTrue(standard is None or standard.score<normal.score)

    def test_candidates_are_deterministic_and_unreadable_price_never_scores(self):
        offers=(Offer(0,'翡翠',None),Offer(1,'飞霄',1),Offer(2,'椒丘',1))
        state=PurchaseSituation(Mode.OVERCLOCK,5,3)
        self.assertEqual([item.slot for item in rank_purchases(offers,state)],[1,2])
        self.assertEqual(rank_purchases(offers,state),rank_purchases(offers,state))
