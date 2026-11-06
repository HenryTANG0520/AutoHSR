"""Confirmed outfit identities, without game, account or selection inference."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autohsr.challenge_plan import ChallengePlan, ChallengePlanError, MODE_LIMITS
from autohsr.tests.test_challenge_plan import TEAM1, TEAM2, raw_plan


PAIRS=(('March7th','March7thNascentSpring'),('Firefly','FireflySpringMissive'),
       ('Castorice','CastoriceGossamerFlutter'),('Hyacine','HyacineWarmCottonSkies'),
       ('Evanescia','EvanesciaLunarBlossoming'),('Sparxie','SparxieCandyCoatedWaves'))


class ChallengeIdentityTests(unittest.TestCase):
    def test_firefly_skin_is_same_unit_in_both_halves(self):
        with self.assertRaises(ChallengePlanError) as error:
            ChallengePlan.from_dict(raw_plan(team1=['Firefly',*TEAM1[1:]],team2=['FireflySpringMissive',*TEAM2[1:]]))
        self.assertEqual(error.exception.field,'teams')

    def test_confirmed_outfits_conflict_with_base_in_both_directions_and_all_modes(self):
        for mode in MODE_LIMITS:
            for first,second in PAIRS:
                for a,b in ((first,second),(second,first)):
                    with self.subTest(mode=mode,first=a,second=b):
                        with self.assertRaises(ChallengePlanError) as error:
                            ChallengePlan(mode,(1,1),(a,b,*TEAM1[2:]),TEAM2)
                        self.assertEqual(error.exception.field,'team1')
                        with self.assertRaises(ChallengePlanError) as error:
                            ChallengePlan(mode,(1,1),TEAM1,(a,b,*TEAM2[2:]))
                        self.assertEqual(error.exception.field,'team2')
                        with self.assertRaises(ChallengePlanError) as error:
                            ChallengePlan(mode,(1,1),(a,*TEAM1[1:]),(b,*TEAM2[1:]))
                        self.assertEqual(error.exception.field,'teams')

    def test_unique_complete_chinese_names_cannot_evade_unit_deduplication(self):
        for first,second in (('流萤','流萤「春日手信」'),('三月七（冰）','三月七「冬去煦至」'),
                ('遐蝶','遐蝶「幽梦翩跹」'),('风堇','风堇·云边拾暖'),('绯英','绯英·月待花时')):
            with self.subTest(first=first):
                base=ChallengePlan.from_dict(raw_plan(team1=[first,*TEAM1[1:]]))
                outfit=ChallengePlan.from_dict(raw_plan(team1=[second,*TEAM1[1:]]))
                self.assertNotEqual(base.team1[0],outfit.team1[0])
                with self.assertRaises(ChallengePlanError) as error:
                    ChallengePlan.from_dict(raw_plan(team1=[first,*TEAM1[1:]],team2=[second,*TEAM2[1:]]))
                self.assertEqual(error.exception.field,'teams')

    def test_preview_deduplicates_sparxie_ids_and_full_names(self):
        from autohsr.__main__ import main

        with TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            for base, outfit in (('Sparxie', 'SparxieCandyCoatedWaves'), ('火花', '火花·甜梦电波')):
                for first, second, asset in (
                    ([base, *TEAM1[1:]], TEAM2, 'Sparxie'),
                    ([outfit, *TEAM1[1:]], TEAM2, 'SparxieCandyCoatedWaves'),
                    ([base, outfit, *TEAM1[2:]], TEAM2, None),
                    ([base, *TEAM1[1:]], [outfit, *TEAM2[1:]], None),
                ):
                    with self.subTest(first=first, second=second):
                        raw = raw_plan(team1=first, team2=list(second))
                        path.write_text(json.dumps(raw, ensure_ascii=False), encoding='utf-8')
                        output, errors = StringIO(), StringIO()
                        with redirect_stdout(output), redirect_stderr(errors):
                            code = main(['--challenge-check', str(path)])
                        self.assertEqual(code, 0 if asset else 2)
                        if asset:
                            receipt = json.loads(output.getvalue())
                            self.assertEqual(receipt['plan']['team1'][0], asset)
                        else:
                            receipt = json.loads(errors.getvalue())
                            self.assertIn('同一单位', receipt['error'])
                            self.assertFalse(output.getvalue())
                        self.assertFalse(receipt['game_accessed'])

    def test_one_explicit_outfit_keeps_its_exact_id_serialization_and_digest(self):
        for base,outfit in PAIRS:
            with self.subTest(outfit=outfit):
                value=raw_plan(team1=[outfit,*TEAM1[1:]])
                plan=ChallengePlan.from_dict(value)
                self.assertEqual(plan.to_dict(),value)
                self.assertEqual(plan.team1[0],outfit)
                base_plan=ChallengePlan.from_dict(raw_plan(team1=[base,*TEAM1[1:]]))
                self.assertNotEqual(plan.digest,base_plan.digest)

    def test_unlisted_asset_relationships_are_not_merged_by_story_name_or_prefix(self):
        # Configuration acceptance preserves explicit asset IDs only. For
        # unlisted relations this does not assert actual co-deployability,
        # ownership, character availability or an observed game selection.
        pairs=(('DanHeng','DanHengImbibitorLunae'),('DanHengImbibitorLunae','DanHengPermansorTerrae'),
               ('Tingyun','Fugue'),('Herta','TheHerta'),('March7th','Evernight'),
               ('SilverWolf','SilverWolfLV999'),('Himeko','HimekoNova'),('Blade','MortenaxBlade'),
               ('Robin','RobinSummeretto'),('Aventurine','AventurineWaveflair'))
        for mode in MODE_LIMITS:
            for first,second in pairs:
                with self.subTest(mode=mode,pair=(first,second)):
                    plan=ChallengePlan(mode,(1,1),(first,second,'Asta','JingYuan'),TEAM2)
                    self.assertEqual(plan.team1[:2],(first,second))

    def test_group_lookup_does_not_guess_unlisted_forms_or_future_outfit_names(self):
        from autohsr.challenge_identities import unit_key
        for first,second in PAIRS:self.assertEqual(unit_key(first),unit_key(second))
        for unknown in ('FireflyUnknownOutfit','March7thImaginary','StelleRemembrance','CaelumImaginary','RuanMeiPlumblossomLetter'):
            self.assertEqual(unit_key(unknown),unknown)
        self.assertNotEqual(unit_key('DanHeng'),unit_key('DanHengImbibitorLunae'))

    def test_existing_valid_plan_canonical_json_and_digest_remain_unchanged(self):
        expected=raw_plan()
        encoded=json.dumps(expected,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
        plan=ChallengePlan.from_dict(expected)
        self.assertEqual(plan.to_dict(),expected)
        self.assertEqual(plan.digest,hashlib.sha256(encoded).hexdigest())
