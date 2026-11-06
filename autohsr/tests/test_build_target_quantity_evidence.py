"""Replay bounded material fields and verify the offline plan calculation."""
from copy import deepcopy
from dataclasses import replace
import json
import re
import unittest
from unittest.mock import patch

from autohsr.models import Scene, Token
from autohsr.tests import test_build_target_preview as fixtures
from tools.build_target_plan_probe import FIXTURE, Scope, Yield, estimate, replay_fixture


DATA = json.loads(FIXTURE.read_text(encoding='utf-8'))
FRAMES = {row['id']: row for row in DATA['frames']}
SYNTHESIS = json.loads(FIXTURE.with_name('build_target_synthesis.json').read_text(encoding='utf-8'))


def evidence_token(field):
    return Token(field['t'], field['q'], tuple(field['box']))


class QuantityEvidenceCliTests(unittest.TestCase):
    setup = fixtures.BuildTargetPreviewTests
    setUp, runtime, cli, draft_cli = setup.setUp, setup.runtime, setup.cli, setup.draft_cli
    material, route = setup.material, setup.route

    @staticmethod
    def frame(key):
        return [fixtures.fixtures.ACCOUNT, *map(evidence_token, FRAMES[key]['tokens'])]

    @staticmethod
    def recipe():
        return [fixtures.fixtures.ACCOUNT, *map(evidence_token, SYNTHESIS['recipe']['tokens'])]

    @staticmethod
    def recipe_crop(fields):
        read_frame = fixtures.fixtures.Window.read

        def read(window, image, geometry=None):
            if geometry is None:
                return Scene(list(fields), image)
            return read_frame(window, image, geometry)

        return patch.object(fixtures.fixtures.Window, 'read', read)

    def assert_observations_only(self, report):
        self.assertNotIn('draft', report['build_target'])
        preview = report['build_target']['preview']
        self.assertEqual(preview['candidates'], [])
        for key in ('material', 'held', 'shortfall', 'craftable', 'units_per_challenge', 'count', 'effective_limit'):
            self.assertIsNone(preview[key], key)
        return preview

    def test_current_complete_panel_reports_only_level_and_trace_status(self):
        frame = self.frame('target-complete-local')
        report = self.cli([frame, frame])
        preview = self.assert_observations_only(report)
        self.assertTrue(report['build_target']['page_verified'])
        self.assertTrue(preview['target_section_visible'])
        self.assertEqual(preview['state'], 'target_level_trace_complete')
        self.assertEqual(preview['suggestion_reason'], 'level_trace_requirements_met')
        self.assertEqual(preview['shortfall_rows'], [])
        self.assertNotIn('draft', self.draft_cli([frame, frame], code=1)['build_target'])

    def test_public_target_slot_amount_excludes_cost_and_relic_recommendation(self):
        report = self.cli([self.frame('need-a'), self.frame('need-c')])
        preview = self.assert_observations_only(report)
        self.assertEqual(preview['state'], 'target_resources_needed')
        self.assertEqual(preview['suggestion_reason'], 'material_shortfall_unbound')
        self.assertEqual(preview['shortfall_rows'], [{'observed_needed': [90], 'shown_stamina': 10}])

    def test_different_shortfall_slots_on_one_row_are_kept_separate(self):
        frame = [*self.frame('need-b'), fixtures.token('32', .47, .457, width=.018)]
        preview = self.assert_observations_only(self.cli([frame, frame]))
        self.assertEqual(preview['shortfall_rows'], [{'observed_needed': [90, 32], 'shown_stamina': 10}])
        bad = [*frame, fixtures.token('3O', .52, .457, width=.018, score=.82)]
        self.assertEqual(self.cli([bad, bad])['build_target']['preview']['shortfall_rows'], [])

    def test_result_reminder_has_its_own_count_and_previous_wave_count(self):
        before, first, second = (self.frame(key) for key in ('result-animating', 'result-a', 'result-b'))
        pending = self.assert_observations_only(self.cli([before] * 8))
        self.assertNotIn('post_battle_shortfall', pending)
        preview = self.assert_observations_only(self.cli([before, first, second]))
        self.assertEqual(preview['state'], 'calyx_result_shortfall')
        self.assertEqual(preview['suggestion_reason'], 'settled_batch_only')
        self.assertEqual(preview['post_battle_shortfall'], dict(
            observed_needed=[72], completed_rounds=18, repeat_stamina=180))

    def test_mixed_or_conflicting_status_does_not_supply_quantity(self):
        complete, target = self.frame('target-complete-local'), self.frame('need-b')
        conflicts = (
            [*complete, fixtures.token('培养还需获取资源', .48, .385, width=.14)],
            [*complete, fixtures.token('已获得足够的', .45, .38, width=.08),
             fixtures.token('等级和行迹材料', .55, .38, width=.105)],
            [*target, fixtures.token('已完成等级、', .55, .39, width=.094),
             fixtures.token('行迹的提升', .6465, .39, width=.09)],
            [*target, *self.frame('result-b')[1:]],
        )
        for frames in ([frame] * 8 for frame in conflicts):
            preview = self.assert_observations_only(self.cli(frames))
            self.assertEqual(preview['state'], 'unverified')
            self.assertNotIn('shortfall_rows', preview)
            self.assertNotIn('post_battle_shortfall', preview)
        mixed = self.assert_observations_only(self.cli([target, self.frame('result-b')] * 4))
        self.assertEqual(mixed['state'], 'unverified')

    def test_prior_panel_can_be_observed_when_new_status_layout_is_incomplete(self):
        frame = [*fixtures.fixtures.HEADERS, *[
            replace(t, text='培养还需获取资源') if '培养还需获取资源' in t.text else t
            for t in self.frame('need-b') if t.text not in ('培养设置', '遗器装配不全', '隧洞遗器推荐', '位面饰品推荐')
        ]]
        self.assertEqual(self.cli([frame, frame])['build_target']['preview']['state'], 'panel_observed')

    def test_numeric_slots_do_not_move_between_frames_or_bind_elsewhere_in_result(self):
        target = self.frame('need-b')
        moved = [replace(t, box=(.573, .448, .592, .465)) if t.text == '90' else t for t in target]
        preview = self.assert_observations_only(self.cli([target, moved] * 4))
        self.assertEqual(preview['state'], 'unverified')
        result = self.frame('result-b')
        for box in ((.60, .636, .622, .662), (.41, .62, .99, .678)):
            with self.subTest(box=box):
                frame = [replace(t, box=box) if t.text == '72' else t for t in result]
                preview = self.assert_observations_only(self.cli([frame] * 8))
                self.assertEqual(preview['state'], 'unverified')

    def test_result_rejects_split_failure_duplicate_waves_and_stage_overlay(self):
        result = self.frame('result-b')
        for fields in (
            [fixtures.token('挑战', .595, .21, width=.038), fixtures.token('失败', .642, .21, width=.04)],
            [fixtures.token('上轮挑战', .585, .811, width=.06), fixtures.token('波次：19', .65, .811, width=.056)],
            self.frame('stage-18')[1:],
        ):
            with self.subTest(fields=fields):
                frame = [*result, *fields]
                preview = self.assert_observations_only(self.cli([frame] * 8))
                self.assertNotIn('post_battle_shortfall', preview)

    def test_eighteen_selected_rounds_keep_preview_budget_separate(self):
        toast, stage = self.frame('stage-locked-toast'), self.frame('stage-18')
        preview = self.assert_observations_only(self.cli([toast] * 8))
        self.assertEqual(preview['state'], 'unverified')
        preview = self.assert_observations_only(self.cli([stage, stage]))
        self.assertEqual(preview['state'], 'calyx_reward_preview')
        self.assertEqual(preview['suggestion_reason'], 'possible_rewards_only')
        self.assertEqual(preview['calyx_reward_preview'], dict(
            category='calyx_crimson', target='智识之蕾', difficulty=6, selected_rounds=18,
            shown_total_stamina=180, rewards='possible_items', stamina_per_challenge=10,
            selected_stamina_within_config=False, max_draft_challenges_by_config=2,
        ))

    def test_native_recipe_counts_are_separate_and_cannot_prepare_a_draft(self):
        frame = self.recipe()
        crop = tuple(map(evidence_token, SYNTHESIS['recipe']['quantity_crop_tokens']))
        with self.recipe_crop(crop):
            preview = self.assert_observations_only(self.cli([frame, frame]))
            self.assertNotIn('draft', self.draft_cli([frame] * 8, code=1)['build_target'])
        self.assertEqual(preview['state'], 'synthesis_preview')
        self.assertEqual(preview['suggestion_reason'], 'recipe_only')
        self.assertEqual(preview['synthesis_preview'], dict(
            material='梦现管锥', held=0, selected_output=6, slider_limit=765))

    def test_recipe_pair_restarts_when_an_early_cultivation_status_is_visible(self):
        recipe = self.recipe()
        crop = tuple(map(evidence_token, SYNTHESIS['recipe']['quantity_crop_tokens']))
        completed = next(t for t in self.frame('target-complete-local') if t.text == '已完成等级、行迹的提升')
        enough = replace(completed, text='已获得足够的等级和行迹材料')
        split = (replace(completed, text='已完成等级、', box=(.4062, .3269, .466, .3519)),
                 replace(completed, text='行迹的提升', box=(.473, .3269, .5411, .3519)))
        wrong = [replace(t, text='童真蜡笔') if t.text == '梦现管锥' else t for t in recipe]
        with self.recipe_crop(crop):
            for status in ((completed,), (enough,), split):
                with self.subTest(status=[t.text for t in status]):
                    transition = [*recipe, *status]
                    for frames in ([transition] * 8, [transition, recipe, *([wrong, recipe] * 3)]):
                        preview = self.assert_observations_only(self.cli(frames))
                        self.assertEqual(preview['state'], 'unverified')
                        self.assertEqual(preview['suggestion_reason'], 'no_current_evidence')
                        self.assertNotIn('synthesis_preview', preview)

    def test_recipe_accepts_a_larger_merged_quantity_but_rejects_conflicts(self):
        frame = self.recipe()
        selected = [replace(t, text='合成数量：123') if t.text == '合成数量：' else t for t in frame]
        preview = self.assert_observations_only(self.cli([selected, selected]))
        self.assertEqual(preview['synthesis_preview']['selected_output'], 123)
        conflicts = (
            [replace(t, text='合成数量：766') if t.text == '合成数量：' else t for t in frame],
            [*selected, fixtures.token('6', .706, .779, width=.01, score=.77)],
            [*selected, fixtures.token('童真蜡笔', .644, .154, width=.05, score=.79)],
            [t for t in selected if t.text != '+'],
            [*selected, fixtures.token('开拓力不足', .53, .57, width=.12)],
        )
        for conflict in conflicts:
            with self.subTest(fields=[t.text for t in conflict]):
                preview = self.assert_observations_only(self.cli([conflict] * 8))
                self.assertEqual(preview['state'], 'unverified')

    def test_recipe_crop_needs_its_label_and_both_frames_need_the_same_quantity(self):
        frame = self.recipe()
        crop = tuple(map(evidence_token, SYNTHESIS['recipe']['quantity_crop_tokens']))
        with self.recipe_crop(crop[1:]):
            preview = self.assert_observations_only(self.cli([frame] * 8))
            self.assertEqual(preview['state'], 'unverified')
        with self.recipe_crop(crop):
            changed = [replace(t, text='合成数量：12') if t.text == '合成数量：' else t for t in frame]
            preview = self.assert_observations_only(self.cli([frame, changed] * 4))
            self.assertEqual(preview['state'], 'unverified')

    def test_native_confirmation_titles_block_an_underlying_current_target_or_draft(self):
        for sample in SYNTHESIS['blocked']:
            title = evidence_token(sample['title'])
            with self.subTest(title=title.text):
                target = [*self.frame('need-b'), title]
                preview = self.assert_observations_only(self.cli([target] * 8))
                self.assertEqual((preview['state'], preview['suggestion_reason']), ('unverified', 'no_current_evidence'))
                detail = [*self.material(), self.route('城郊雪原', .50), title]
                self.assertNotIn('draft', self.draft_cli([detail] * 8, code=1)['build_target'])


class QuantityEvidenceDataTests(unittest.TestCase):
    def test_source_fields_are_bounded_and_observed_samples_stay_distinct(self):
        self.assertEqual(DATA['schema_version'], 1)
        self.assertEqual(len(FRAMES), len(DATA['frames']))
        for frame in FRAMES.values():
            self.assertRegex(frame['source']['redacted_frame_sha256'], r'^[a-f0-9]{64}$')
            for token in frame['tokens']:
                x1, y1, x2, y2 = token['box']
                self.assertTrue(0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1)
                self.assertFalse(re.search(r'UID|^[0-9]{8,}$', token['t'], re.I))
        records = DATA['observed_loot']
        identities = [r['source'].get('original_image_sha256', r['source'].get('redacted_frame_sha256')) for r in records]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertEqual({r['basis'] for r in records}, {'observed_total'})
        self.assertEqual({r['scope']['bonus'] for r in records}, {'unknown'})
        single = [r for r in records if r['rounds'] == 1 and r['scope']['target'] == '回忆之蕾']
        self.assertEqual({r['items']['虚数残叶'] for r in single}, {2, 3})
        self.assertEqual({r['items']['漫游指南'] for r in single}, {1})
        red = next(r for r in records if r['id'] == 'red-vi-oct20')
        self.assertIsNone(red['items']['《绒绒号》典藏版合集'])

    def test_public_chain_and_measured_yield_never_publish_an_estimate(self):
        result = replay_fixture(DATA, 60)
        replay = result['replayed']
        self.assertEqual((replay['before'], replay['after'], replay['observed_total'], replay['observed_rounds']),
                         (90, 72, 1, 18))
        self.assertIsNone(replay['estimate']['required_rounds'])
        self.assertEqual(replay['estimate']['state'], 'unverified_per_round_minimum')
        synthetic = result['synthetic_examples']
        self.assertEqual(synthetic['positive']['required_rounds'], 3)
        self.assertEqual(synthetic['positive']['required_stamina'], 30)
        self.assertEqual(synthetic['capped']['required_rounds'], 7)
        self.assertEqual(synthetic['capped']['state'], 'beyond_draft_limit')
        self.assertEqual(synthetic['zero']['required_rounds'], 0)
        self.assertIsNone(synthetic['mismatched']['required_rounds'])
        corrupted = deepcopy(DATA)
        measured = next(row for row in corrupted['observed_loot'] if row['id'] == 'red-vi-oct20')
        corrupted['public_chain'].update(settlement_id=measured['id'], material='《绒绒号》连载纪念刊')
        measured['scope']['bonus'] = 'base'
        measured['basis'] = 'guaranteed_minimum'
        with self.assertRaisesRegex(ValueError, 'observed_total'):
            replay_fixture(corrupted, 60)

    def test_estimate_rejects_other_material_location_difficulty_and_bonus(self):
        scope = Scope('calyx_crimson', '智识之蕾', '海原电视塔', 6, 'synthetic', 'base')
        minimum = Yield('银河沙盘', scope, 'guaranteed_minimum', 1, 2)
        for item in (
            replace(minimum, material='星系框架'),
            replace(minimum, scope=replace(scope, location='匹诺康尼大剧院')),
            replace(minimum, scope=replace(scope, version='other')),
            replace(minimum, scope=replace(scope, difficulty=5)),
            replace(minimum, scope=replace(scope, bonus='double')),
            replace(minimum, basis='observed_total'),
            replace(minimum, rounds=2),
            replace(minimum, units=0),
        ):
            with self.subTest(item=item):
                self.assertIsNone(estimate('银河沙盘', 7, scope, item, 60)['required_rounds'])
        bounded = estimate('银河沙盘', 5, scope, minimum, 20)
        self.assertEqual((bounded['state'], bounded['required_rounds'], bounded['max_draft_rounds_by_config']),
                         ('beyond_draft_limit', 3, 2))
        self.assertEqual(estimate('银河沙盘', 5, scope, minimum, 240)['max_draft_rounds_by_config'], 6)
