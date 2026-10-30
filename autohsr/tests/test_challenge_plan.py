"""Pure challenge configuration tests; no roster, process, or game inspection."""
import builtins
from dataclasses import FrozenInstanceError
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autohsr import challenge_plan
from autohsr.challenge_plan import (ChallengePlan, ChallengePlanError, MODE_LIMITS,
    from_values, known_characters)


TEAM1 = ('Asta', 'JingYuan', 'Tingyun', 'Huohuo')
TEAM2 = ('FuXuan', 'Bronya', 'Pela', 'Qingque')


def raw_plan(**changes):
    return dict(dict(mode='memory_of_chaos', levels=[1, 12],
                     team1=list(TEAM1), team2=list(TEAM2)), **changes)


class ChallengePlanTests(unittest.TestCase):
    def test_each_mode_accepts_explicit_valid_range_and_two_full_teams(self):
        for mode, limit in MODE_LIMITS.items():
            for levels in ((1, 1), (1, limit), (limit, limit)):
                plan = ChallengePlan.from_dict(raw_plan(mode=mode, levels=list(levels)))
                self.assertEqual((plan.mode, plan.levels), (mode, levels))
                self.assertEqual(plan.teams, (TEAM1, TEAM2))
                self.assertEqual((plan.level_start, plan.level_end), levels)

    def test_complete_display_names_resolve_to_exact_pinned_ids(self):
        plan = ChallengePlan.from_dict(raw_plan(
            team1=['艾丝妲', '景元', '停云', '藿藿'],
            team2=['符玄', '布洛妮娅', '佩拉', '青雀']))
        canonical = ChallengePlan.from_dict(raw_plan())
        self.assertEqual(plan, canonical)
        self.assertEqual(plan.digest, canonical.digest)
        self.assertEqual(plan.to_dict(), raw_plan())

    def test_mixed_explicit_ids_and_full_names_keep_slot_and_half_order(self):
        plan = from_values('pure_fiction', [2, 4],
                           ['Asta', '景元', 'Tingyun', '藿藿'], list(reversed(TEAM2)))
        self.assertEqual(plan.team1, TEAM1)
        self.assertEqual(plan.team2, tuple(reversed(TEAM2)))
        self.assertEqual(plan.levels, (2, 4))

    def test_direct_constructor_freezes_nested_mutable_inputs(self):
        levels, first, second = [1, 12], list(TEAM1), list(TEAM2)
        plan = ChallengePlan('memory_of_chaos', levels, first, second)
        original_digest = plan.digest
        levels[:] = [2, 4]
        first[0] = 'unknown'
        second.clear()
        self.assertEqual(plan.levels, (1, 12))
        self.assertEqual(plan.teams, (TEAM1, TEAM2))
        self.assertEqual(plan.digest, original_digest)
        for name, value in (('mode', 'pure_fiction'), ('levels', (2, 3)),
                            ('team1', TEAM2), ('team2', TEAM1)):
            with self.assertRaises(FrozenInstanceError):
                setattr(plan, name, value)

    def test_serialized_outputs_are_detached_and_json_round_trip_is_stable(self):
        plan = ChallengePlan.from_dict(raw_plan())
        serialized = plan.to_dict()
        restored = ChallengePlan.from_dict(json.loads(json.dumps(serialized)))
        self.assertEqual(restored, plan)
        self.assertEqual(restored.digest, plan.digest)
        serialized['levels'][0] = 9
        serialized['team1'][0] = 'unknown'
        serialized['team2'].clear()
        self.assertEqual(plan.to_dict(), raw_plan())
        self.assertRegex(plan.digest, r'^[0-9a-f]{64}$')

    def test_digest_distinguishes_mode_range_slot_order_and_half_assignment(self):
        variants = [raw_plan(), raw_plan(mode='pure_fiction', levels=[1, 4]),
            raw_plan(levels=[2, 12]), raw_plan(team1=list(reversed(TEAM1))),
            raw_plan(team1=list(TEAM2), team2=list(TEAM1))]
        digests = [ChallengePlan.from_dict(value).digest for value in variants]
        self.assertEqual(len(set(digests)), len(variants))

    def test_only_three_exact_mode_ids_are_allowed(self):
        for mode in (None, True, 1, [], {}, '', 'forgottenhall', 'memoryone',
                     'Memory_of_chaos', 'memory_of_chaos ', '混沌回忆',
                     'pure_fiction\n', 'apocalyptic_shadow\x00'):
            with self.subTest(mode=mode), self.assertRaises(ChallengePlanError) as error:
                ChallengePlan.from_dict(raw_plan(mode=mode))
            self.assertEqual(error.exception.field, 'mode')

    def test_level_range_requires_two_exact_integers_without_coercion(self):
        bad = (None, '1,12', {}, {1, 12}, [], [1], [1, 2, 3],
               [True, 12], [1, False], [1.0, 12], ['1', 12], [1, '12'])
        for levels in bad:
            with self.subTest(levels=levels), self.assertRaises(ChallengePlanError) as error:
                ChallengePlan.from_dict(raw_plan(levels=levels))
            self.assertEqual(error.exception.field, 'levels')

    def test_mode_specific_limits_and_range_order_are_enforced(self):
        for mode, limit in MODE_LIMITS.items():
            for levels in ((0, 1), (-1, 1), (1, limit + 1), (limit + 1, limit + 1), (2, 1)):
                with self.subTest(mode=mode, levels=levels), self.assertRaises(ChallengePlanError):
                    ChallengePlan(mode, levels, TEAM1, TEAM2)

    def test_each_team_must_be_a_four_item_list_or_tuple(self):
        bad = (None, '', 'Asta', {}, set(TEAM1), [], list(TEAM1[:3]), list(TEAM1) + ['Blade'])
        for field in ('team1', 'team2'):
            for value in bad:
                with self.subTest(field=field, value=value), self.assertRaises(ChallengePlanError) as error:
                    ChallengePlan.from_dict(raw_plan(**{field: value}))
                self.assertEqual(error.exception.field, field)

    def test_empty_unknown_partial_casefolded_and_control_names_are_rejected(self):
        bad = ('', 'unknown', 'asta', 'ASTA', 'Asta ', ' 艾丝妲', '景', '星',
               '穹', '三月七', 'Asta\n', 'Asta\t', 'Asta\x00', 'Asta\u202e',
               'Asta\ud800', 'Asta\u2028', 'A' * 81, None, False, 1, {}, [])
        for field in ('team1', 'team2'):
            original = TEAM1 if field == 'team1' else TEAM2
            for name in bad:
                value = [name, *original[1:]]
                with self.subTest(field=field, name=name), self.assertRaises(ChallengePlanError):
                    ChallengePlan.from_dict(raw_plan(**{field: value}))

    def test_same_team_rejects_exact_and_name_alias_duplicates(self):
        for field, original, duplicate in (('team1', TEAM1, '艾丝妲'), ('team2', TEAM2, '符玄')):
            for name in (original[0], duplicate):
                value = [original[0], name, *original[2:]]
                with self.subTest(field=field, name=name), self.assertRaises(ChallengePlanError) as error:
                    ChallengePlan.from_dict(raw_plan(**{field: value}))
                self.assertEqual(error.exception.field, field)

    def test_across_teams_rejects_exact_and_name_alias_duplicates(self):
        for duplicate in ('Asta', '艾丝妲'):
            with self.assertRaises(ChallengePlanError) as error:
                ChallengePlan.from_dict(raw_plan(team2=[duplicate, *TEAM2[1:]]))
            self.assertEqual(error.exception.field, 'teams')

    def test_plan_requires_exact_keys_and_never_infers_teams_or_optional_behaviors(self):
        bad = (None, [], '', {}, {'mode': 'memory_of_chaos'},
               {**raw_plan(), 'teams': [list(TEAM1), list(TEAM2)]},
               {**raw_plan(), 'techniques': [0, 0, 0, 0]},
               {**raw_plan(), 'retry_on_failure': True},
               {**raw_plan(), 'claim_rewards': True},
               {**raw_plan(), 'unlocked': True})
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ChallengePlanError) as error:
                ChallengePlan.from_dict(value)
            self.assertEqual(error.exception.field, 'plan')
        for missing in raw_plan():
            value = raw_plan()
            del value[missing]
            with self.assertRaises(ChallengePlanError):
                ChallengePlan.from_dict(value)

    def test_all_105_pinned_identities_are_known_without_claiming_account_availability(self):
        characters = known_characters()
        self.assertIs(type(characters), tuple)
        self.assertEqual(len(characters), 105)
        self.assertEqual(len(set(characters)), 105)
        self.assertIn('StelleRemembrance', characters)
        self.assertIn('March7thImaginary', characters)
        for identity in characters:
            others = [name for name in characters if name != identity][:7]
            plan = ChallengePlan('memory_of_chaos', (1, 1), (identity, *others[:3]), tuple(others[3:]))
            self.assertEqual(plan.team1[0], identity)
            self.assertEqual(set(plan.to_dict()), {'mode', 'levels', 'team1', 'team2'})

    def test_explicit_forms_are_preserved_without_guessing_an_active_path(self):
        plan = ChallengePlan.from_dict(raw_plan(team1=['星（记忆）', *TEAM1[1:]]))
        self.assertEqual(plan.team1[0], 'StelleRemembrance')
        with self.assertRaises(ChallengePlanError):
            ChallengePlan.from_dict(raw_plan(team1=['星', *TEAM1[1:]]))

    def test_manifest_failure_is_bounded_and_does_not_report_a_local_path(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogue.json'
            for raw in (b'{}', b'not json', b'x' * (challenge_plan.MAX_MANIFEST_BYTES + 1)):
                path.write_bytes(raw)
                challenge_plan._catalogue.cache_clear()
                with patch.object(challenge_plan, '_manifest_path', return_value=path):
                    with self.assertRaises(ChallengePlanError) as error:
                        ChallengePlan.from_dict(raw_plan())
                self.assertEqual(error.exception.field, 'catalogue')
                self.assertNotIn(folder, str(error.exception))
        challenge_plan._catalogue.cache_clear()
        self.assertEqual(len(known_characters()), 105)

    def test_lf_and_crlf_checkouts_preserve_the_same_pinned_catalogue(self):
        canonical = challenge_plan._manifest_path().read_bytes().replace(b'\r\n', b'\n')
        self.addCleanup(challenge_plan._catalogue.cache_clear)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalogue.json'
            for raw in (canonical, canonical.replace(b'\n', b'\r\n')):
                path.write_bytes(raw)
                challenge_plan._catalogue.cache_clear()
                with patch.object(challenge_plan, '_manifest_path', return_value=path):
                    self.assertEqual(len(known_characters()), 105)
                    self.assertEqual(ChallengePlan.from_dict(raw_plan()).team1, TEAM1)
            path.write_bytes(canonical.replace(b'"Acheron"', b'"Changed"', 1))
            challenge_plan._catalogue.cache_clear()
            with patch.object(challenge_plan, '_manifest_path', return_value=path), self.assertRaises(ChallengePlanError):
                known_characters()

    def test_missing_manifest_fails_closed_without_default_characters(self):
        with tempfile.TemporaryDirectory() as folder:
            challenge_plan._catalogue.cache_clear()
            with patch.object(challenge_plan, '_manifest_path', return_value=Path(folder) / 'missing.json'):
                with self.assertRaises(ChallengePlanError) as error:
                    ChallengePlan.from_dict(raw_plan())
                self.assertEqual(error.exception.field, 'catalogue')
        challenge_plan._catalogue.cache_clear()

    def test_standalone_module_validation_does_not_import_settings_runner_or_game_io(self):
        # Execute a separate instance so this checks imports even when other
        # tests in the process have already imported unrelated project code.
        spec = importlib.util.spec_from_file_location('challenge_plan_import_probe', challenge_plan.__file__)
        probe = importlib.util.module_from_spec(spec)
        original = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name in ('autohsr.config', 'autohsr.app', 'autohsr.windows', 'winreg', 'config', 'app', 'windows'):
                raise AssertionError('pure plan must not import settings or game IO')
            return original(name, *args, **kwargs)

        with patch.dict('sys.modules', {spec.name: probe}), patch('builtins.__import__', side_effect=guarded):
            spec.loader.exec_module(probe)
            value = probe.ChallengePlan.from_dict(raw_plan())
            self.assertEqual(value.to_dict(), raw_plan())


if __name__ == '__main__':
    unittest.main()
