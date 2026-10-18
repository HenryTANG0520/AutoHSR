import unittest

from autohsr.currency_wars_economy import Mode, assess_spend, interest, reserve_for_interest


class EconomyTests(unittest.TestCase):
    def test_standard_interest_thresholds_and_cap(self):
        for gold, expected in ((0, 0), (9, 0), (10, 1), (19, 1), (20, 2), (49, 4), (50, 5), (90, 5)):
            self.assertEqual(interest(Mode.STANDARD, gold), expected)

    def test_overclock_never_saves_for_nonexistent_interest(self):
        for gold in (0, 9, 10, 49, 50, 100):
            self.assertEqual(interest(Mode.OVERCLOCK, gold), 0)
            self.assertEqual(reserve_for_interest(Mode.OVERCLOCK, gold), 0)
            self.assertEqual(assess_spend(Mode.OVERCLOCK, gold, 2).interest_lost, 0)

    def test_interest_cost_and_unaffordable_spend(self):
        purchase = assess_spend(Mode.STANDARD, 50, 1)
        self.assertEqual((purchase.remaining, purchase.interest_lost), (49, 1))
        refused = assess_spend(Mode.STANDARD, 1, 4)
        self.assertFalse(refused.affordable)
        self.assertEqual(refused.remaining, 1)

    def test_bad_values_or_unknown_mode_are_not_normalized_into_money(self):
        for value in (-1, True, 2.0, None):
            with self.assertRaises(ValueError):
                interest(Mode.STANDARD, value)
        with self.assertRaises(ValueError):
            interest("unknown", 20)
