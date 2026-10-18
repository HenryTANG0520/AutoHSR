"""Guide provenance, fail-closed config and fact-derived advice; no game access."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from autohsr.currency_wars_advice import DEFAULT_STRATEGY, advise, load_strategy


class AdviceTests(unittest.TestCase):
    def state(self, **changes):
        # Synthetic complete 4.4 state; never label this live validation.
        state = dict(page='preparation', game_version='4.4', mode='overclock',
                     selected_strategy='joy_quantum_lv7', guide_scope_confirmed=True,
                     level=7, core_present=True, core_cost=3)
        return dict(state, **changes)

    def test_upgrade_order_and_exact_explanation(self):
        before = advise(self.state())
        self.assertEqual((before['action'], before['rule_ids']), ('hold_experience', ['G7-before-four-cost']))
        self.assertEqual(before['reasons'][0]['facts'][1], dict(field='core_cost', op='lt', value=4, observed=3))
        after = advise(self.state(core_cost=4))
        self.assertEqual(after['action'], 'review_level8')
        self.assertFalse(after['executable'])
        self.assertFalse(after['game_accessed'])

    def test_missing_fuzzy_and_unknown_states_never_get_action(self):
        for changes in ({'core_cost': None}, {'level': None}, {'page': 'unknown'},
                        {'core_present': False}, {'game_version': '4.6'},
                        {'guide_scope_confirmed': False}, {'level': 8}, {'mode': None}, {'mode': 'standard'},
                        {'core_cost': True}, {'core_cost': 3.0}, {'core_cost': -1}, {'level': float('nan')}):
            with self.subTest(changes=changes):
                result = advise(self.state(**changes))
                self.assertIsNone(result['action'])
                self.assertEqual(result['status'], 'refused')

    def test_preferences_and_gold_do_not_cause_buy(self):
        state = self.state()
        state.update(gold=999, preferred_names=['银狼Lv.999'], offers=[{'name': '银狼Lv.999', 'cost': 1}])
        self.assertEqual(advise(state)['action'], 'hold_experience')
        self.assertNotIn('buy', load_strategy()[0]['allowed_actions'])

    def test_invalid_config_and_code_are_rejected(self):
        original = json.loads(DEFAULT_STRATEGY.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'strategy.json'
            for change in ('action', 'operator', 'boolean_threshold', 'unknown_field', 'duplicate_priority', 'version', 'source'):
                config = copy.deepcopy(original)
                if change == 'action': config['rules'][0]['action'] = 'buy'
                if change == 'operator': config['rules'][0]['all'][0]['op'] = '__import__("os").system'
                if change == 'boolean_threshold': config['rules'][0]['all'][0]['value'] = True
                if change == 'unknown_field': config['exec'] = 'raise Exception()'
                if change == 'duplicate_priority': config['rules'][1]['priority'] = config['rules'][0]['priority']
                if change == 'version': config['applicability']['game_versions'].append('4.6')
                if change == 'source': config['rules'][0]['source_id'] = 'fabricated'
                path.write_text(json.dumps(config), encoding='utf-8')
                self.assertEqual(advise(self.state(), path)['reasons'][0]['code'], 'invalid_config', change)
            path.write_text('{"schema_version":1,"schema_version":1}', encoding='utf-8')
            self.assertIsNone(advise(self.state(), path)['action'])
            self.assertIsNone(advise(self.state(), Path(folder) / 'missing')['action'])

    def test_input_unchanged_and_config_digest_stable(self):
        state = self.state(core_cost=None)
        before = copy.deepcopy(state)
        first, second = advise(state), advise(state)
        self.assertEqual(state, before)
        self.assertEqual(first, second)
        self.assertEqual(first['missing'], ['core_cost'])
        self.assertEqual(len(first['strategy_sha256']), 64)
        self.assertIn('7级', first['message'])
        self.assertIn('当前费用', first['message'])


if __name__ == '__main__':
    unittest.main()
