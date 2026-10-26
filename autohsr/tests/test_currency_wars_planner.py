"""Decision semantics on synthetic cases, plus the existing real OCR fixtures."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, fields, replace
from pathlib import Path

from autohsr.currency_wars_planner import OfflineProvider, RouteSpec, candidates, load_routes, route_ranking, validate_decision
from autohsr.currency_wars_state import FactEvidence, ShopOffer, StrategySnapshot, UnitState, load_snapshot, snapshot_from_scene
from autohsr.models import Scene, Token


def snapshot(**changes):
    values = dict(page='shop', input_epoch=4, observed_at=100., game_version='4.6', mode='standard',
        rank=8, wealth=40, node='2-1', gold=52, hp=100, level=7, experience=(10, 48),
        capacity=1, bench_capacity=9, bench_occupied=1,
        roster=(UnitState('核心', 'front', 1, 1, 4, ('输出',), (), ('front',)),
                UnitState('核心', 'bench', 1, 1, 4, ('输出',), (), ('front',))),
        roster_complete=True, offers=(ShopOffer(0, '核心', 2, 4, 1, ('输出',)),),
        inventory=(), environment=(), investments=(), recent_losses=(),
        transaction_status='clear', refresh_budget=4, rules_version='4.6')
    values.update(changes)
    values.setdefault('evidence', tuple(FactEvidence(name, 'synthetic://decision-case', values['input_epoch'])
                      for name, value in values.items() if name not in ('input_epoch', 'observed_at') and value is not None))
    return StrategySnapshot(**values)


def route(name='route', **changes):
    values = dict(route_id=name, game_versions=('4.6',), modes=('standard',), sources=('synthetic://guide',),
                  core_names=('核心',), preferred_names=('辅助',), target_level=8, rules_checked=True)
    values.update(changes)
    return RouteSpec(**values)


class StateTests(unittest.TestCase):
    def test_price_tier_and_star_are_independent(self):
        state = snapshot(offers=(ShopOffer(0, '核心', 2, 5, 2),))
        self.assertEqual(asdict(state.offers[0]), dict(slot=0, name='核心', price=2, tier=5, star=2, traits=None))
        self.assertTrue(all(c.kind != 'buy' for c in candidates(state)))

    def test_duplicate_equipment_is_valid(self):
        unit = UnitState('核心', 'front', 1, equipment=('反重力靴', '反重力靴'))
        self.assertEqual(unit.equipment.count('反重力靴'), 2)

    def test_unknown_and_stale_facts_not_exported(self):
        state = snapshot()
        state = replace(state, evidence=tuple(e for e in state.evidence if e.field != 'gold'))
        self.assertFalse(state.known('gold'))
        self.assertIsNone(state.public_state()['gold'])
        self.assertTrue(all(c.kind == 'observe' for c in candidates(state)))
        self.assertTrue(all(c.kind == 'observe' for c in candidates(replace(state, input_epoch=5))))

    def test_reobserve_same_facts_but_changed_state_or_epoch_invalidates_answer(self):
        state = snapshot()
        reobserved = replace(state, observed_at=108, evidence=tuple(replace(e, source_id='another-local-path') for e in state.evidence))
        self.assertEqual(state.snapshot_id, reobserved.snapshot_id)
        self.assertNotEqual(state.snapshot_id, snapshot(gold=51).snapshot_id)
        choices = candidates(reobserved)
        answer = OfflineProvider().decide(state)
        self.assertTrue(validate_decision(reobserved, answer, choices, now=108, input_epoch=4))
        self.assertFalse(validate_decision(reobserved, answer, choices, now=117, input_epoch=4))
        self.assertFalse(validate_decision(reobserved, answer, choices, now=108, input_epoch=5))
        self.assertFalse(answer.executable)

    def test_invalid_shapes_types_and_conflicts_are_rejected(self):
        for change in (dict(gold=True), dict(hp=101), dict(observed_at=float('nan')), dict(mode='auto'),
                       dict(experience=(48, 48)), dict(capacity=0), dict(bench_occupied=0),
                       dict(roster=(UnitState('甲', 'front', 1), UnitState('乙', 'front', 1))),
                       dict(offers=(ShopOffer(0, '甲'), ShopOffer(0, '乙')))):
            with self.subTest(change=change), self.assertRaises(ValueError):
                snapshot(**change)

    def test_file_roundtrip_and_unknown_personal_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            original = asdict(snapshot())
            path.write_text(json.dumps(original), encoding='utf-8')
            loaded = load_snapshot(path)
            self.assertEqual(loaded, replace(snapshot(), observed_at=0))
            self.assertFalse(loaded.fresh(100, 4))
            original['uid'] = 'private'
            path.write_text(json.dumps(original), encoding='utf-8')
            with self.assertRaises(ValueError):
                load_snapshot(path)
            path.write_text('{"gold":1,"gold":2}', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_snapshot(path)

    def test_real_hud_fixture_does_not_invent_mode_roster_or_ledger(self):
        from autohsr.tests.test_currency_wars_shop import shop
        result = snapshot_from_scene(shop(), 3)
        self.assertEqual(result.page, 'shop')
        self.assertIsNone(result.mode)
        self.assertIsNone(result.offers[0].star)
        self.assertIsNone(result.offers[0].tier)
        self.assertFalse(result.roster_complete)
        self.assertEqual(result.transaction_status, 'unknown')
        self.assertTrue(all(c.kind == 'observe' for c in candidates(result)))

    def test_cli_emits_utf8_json_and_never_marks_action_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            path.write_text(json.dumps(asdict(snapshot())), encoding='utf-8')
            completed = subprocess.run([sys.executable, '-m', 'autohsr.currency_wars_planner', '--state', str(path)],
                cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, encoding='utf-8', timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            data = json.loads(completed.stdout)
            self.assertFalse(data['automatic_execution'])
            self.assertFalse(data['game_accessed'])
            self.assertIn('实际支付', ''.join(data['decision']['reasons']))


class PlannerTests(unittest.TestCase):
    def selected(self, state, knowledge=()):
        provider = OfflineProvider()
        answer = provider.decide(state, knowledge=knowledge)
        current_route = next((r for r in knowledge if r.route_id == answer.route_id), None)
        return next(c for c in candidates(state, current_route) if c.candidate_id == answer.candidate_id)

    def test_same_star_same_tier_merge_beats_hold(self):
        state = snapshot()
        selected = self.selected(state)
        self.assertEqual((selected.kind, selected.target, selected.price), ('buy', '0', 2))
        self.assertIn('已有两张同星同费用角色', ''.join(selected.reasons))
        for offer in (ShopOffer(0, '核心', 2, 4, 2), ShopOffer(0, '核心', 2, 3, 1), ShopOffer(0, '核心', 2)):
            self.assertEqual(self.selected(snapshot(offers=(offer,))).kind, 'hold')

    def test_standard_interest_and_overclock_produce_different_tradeoffs(self):
        roster = (UnitState('核心', 'front', 1, 1, 4),)
        common = dict(gold=10, roster=roster, bench_occupied=0, offers=(ShopOffer(0, '核心', 2, 4, 1),))
        standard = next(c for c in candidates(snapshot(**common)) if c.kind == 'buy')
        overclock = next(c for c in candidates(snapshot(**common, mode='overclock')) if c.kind == 'buy')
        # The tutorial proves the economic difference, not the optimal choice.
        self.assertLess(standard.utility, overclock.utility)
        self.assertIn('机会成本0.00', ''.join(overclock.reasons))

    def test_recent_damage_changes_interest_tradeoff_without_fixed_hp40(self):
        common = dict(gold=10, hp=55, roster=(UnitState('核心', 'front', 1, 1, 4),), bench_occupied=0)
        calm = next(c for c in candidates(snapshot(**common)) if c.kind == 'buy')
        threatened = next(c for c in candidates(snapshot(**common, recent_losses=(20, 20))) if c.kind == 'buy')
        self.assertGreater(threatened.utility, calm.utility)

    def test_pending_or_unknown_transactions_block_money(self):
        for status in ('unknown', 'pending'):
            result = candidates(snapshot(transaction_status=status))
            self.assertEqual([(c.kind, c.target, c.price) for c in result], [('observe', 'transaction_status', 0)])

    def test_full_bench_not_assumed_to_support_merge(self):
        self.assertEqual(self.selected(snapshot(bench_capacity=1)).kind, 'hold')

    def test_known_two_step_pair_has_a_reason_but_never_executes_it(self):
        state = snapshot(roster=(UnitState('核心', 'front', 1, 1, 4),), bench_occupied=0,
                         offers=(ShopOffer(0, '核心', 2, 4, 1), ShopOffer(1, '核心', 2, 4, 1)))
        chosen = self.selected(state)
        self.assertIn('两步可见购买', ''.join(chosen.reasons))
        self.assertFalse(OfflineProvider().decide(state).executable)
        self.assertEqual(len(state.roster), 1)

    def test_routes_need_matching_version_mode_and_rules(self):
        for spec in (route(game_versions=('4.4',)), route(modes=('overclock',)), route(rules_checked=False)):
            self.assertEqual(route_ranking(snapshot(), (spec,)), ())
        mismatched = snapshot(game_version='4.7')
        self.assertTrue(all(c.kind == 'observe' for c in candidates(mismatched)))

    def test_fitting_equipment_ranks_route_with_real_duplicates(self):
        state = snapshot(roster=(), bench_occupied=0, capacity=0, inventory=('靴子', '靴子'))
        a = route('a', core_names=(), required_equipment=('武器',))
        b = route('b', core_names=(), required_equipment=('靴子', '靴子'))
        self.assertEqual(OfflineProvider().decide(state, knowledge=(a, b)).route_id, 'b')

    def test_experience_and_search_require_specific_observed_goal_and_budget(self):
        self.assertEqual(self.selected(snapshot(page='preparation')).kind, 'hold')
        state = snapshot(page='preparation', experience=(46, 48), offers=())
        self.assertEqual(self.selected(state, (route(),)).kind, 'experience')
        state = snapshot(offers=(), roster=(UnitState('过渡', 'front', 1),), bench_occupied=0)
        self.assertEqual(self.selected(state, (route(),)).kind, 'refresh')
        self.assertEqual(self.selected(replace(state, refresh_budget=0), (route(),)).kind, 'hold')

    def test_route_loader_rejects_code_duplicate_ids_and_bad_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'routes.json'
            valid = dict(schema_version=1, routes=[asdict(route())])
            path.write_text(json.dumps(valid), encoding='utf-8')
            self.assertEqual(load_routes(path), (route(),))
            for change in ('duplicate', 'code', 'bad_mode'):
                data = copy.deepcopy(valid)
                if change == 'duplicate': data['routes'].append(data['routes'][0])
                if change == 'code': data['routes'][0]['exec'] = 'code'
                if change == 'bad_mode': data['routes'][0]['modes'] = ['auto']
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises((ValueError, TypeError)):
                    load_routes(path)


if __name__ == '__main__':
    unittest.main()
