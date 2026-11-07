"""Synthetic material layouts with released catalogue fields and the native runner."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr import build_target_compose, build_target_draft
from autohsr.build_target_preview import BuildTargetSelection, SHADOW_TARGETS
from autohsr.config import RESOURCE_ROOT, Settings, SettingsError
from autohsr.desktop_daily import DailyPanel, _preview_text
from autohsr.dungeons import load_catalogue
from autohsr.models import AutomationError, EmptyCapture, Scene
from autohsr.power_plan import items
from autohsr.tests import test_build_target_read as fixtures


token = fixtures.token


class BuildTargetPreviewTests(unittest.TestCase):
    runtime = fixtures.BuildTargetReadTests.runtime

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(overlay_logs=False, stamina_limit=20)
        fields = fixtures.directory_fields('_calyx_golden_00.json')
        self.entry = next(field for field in fields if field.text == '培养目标')
        self.guide = [*fixtures.HEADERS, fixtures.ACCOUNT, self.entry]
        self.catalogue = [*fixtures.HEADERS, fixtures.ACCOUNT, *fields]

    def material(self, name='漫游指南', *, score=.99, in_target=True):
        panel = [token('培养还需获取资源', .46, .273, width=.13)] if in_target else []
        return [*self.guide, *panel, token(name, .48, .322, score=score, width=.13),
                token('获得途径', .48, .42, width=.06)]

    def route(self, location, y, *, score=.99):
        return token(f'拟造花萼〖{location}〗', .57, y, score=score, width=.18)

    def shadow_route(self, location, y=.52):
        return token(f'凝滞虚影〖{location}〗', .57, y, width=.20)

    def native(self, frames):
        with self.runtime(frames) as window:
            runner = Runner(self.settings, operation='build_target_preview')
            report = runner.run()
        self.assertEqual(window.clicks, [])
        self.assertIsNone(runner.battle_budget)
        self.assertEqual((report.stamina_spent, report.stamina_pending, report.battle_completed), (0, 0, 0))
        return report

    def cli(self, frames, *, args=('--preview-build-target',), operation='build_target_preview', code=1):
        config = self.root / 'config.json'
        self.settings.save(config)
        original = config.read_bytes()
        runs = self.root / 'runs'
        runs.mkdir(exist_ok=True)
        ledger = runs / 'battle-session.json'
        ledger.write_bytes(b'existing payment evidence')
        output, logs = io.StringIO(), io.StringIO()
        with (self.runtime(frames) as window, patch('autohsr.notify_runtime.hooks') as notify,
              patch('autohsr.recovery.BattleBudget') as budget,
              redirect_stdout(output), redirect_stderr(logs)):
            self.assertEqual(main([*args, '--config', str(config)]), code, logs.getvalue())
        notify.assert_not_called()
        budget.assert_not_called()
        self.assertEqual(window.clicks, [])
        report = json.loads(output.getvalue())
        self.assertEqual(report['operation'], operation)
        self.assertEqual(report['build_target']['entry_input'], 'not_sent')
        self.assertEqual(report['power_plan'], {})
        self.assertEqual((report['stamina_spent'], report['stamina_pending'], report['battle_completed']), (0, 0, 0))
        self.assertNotIn('123456789', output.getvalue() + logs.getvalue())
        self.assertNotIn('123456780', output.getvalue() + logs.getvalue())
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(ledger.read_bytes(), b'existing payment evidence')
        return report

    def draft_cli(self, frames, *, material='漫游指南', location='城郊雪原', count=1, code=0):
        args = ('--build-target', '--material', material, '--location', location, '--count', str(count))
        return self.cli(frames, args=args, operation='build_target_plan', code=code)

    def calyx(self, rounds, cost, *, title='回忆之蕾·拟造花萼（金）', difficulty='V'):
        return [
            fixtures.ACCOUNT, token(title, .73, .128, width=.19), token(f'难度{difficulty}', .66, .17),
            token('可能遭遇', .656, .227), token('可能获取', .656, .582),
            token(f'挑战次数{rounds}', .806, .80), token('24', .92, .825), token(f'×{cost}', .67, .91, score=.82),
            token('挑战', .831, .91),
        ]

    def test_held_reads_explicit_zero_and_split_inventory_without_counting_as_shortfall(self):
        base = [*self.material(), self.route('城郊雪原', .50), token('需要65', .45, .91)]
        for fields, held in (
            ([token('当前持有：0', .31, .684, width=.07)], 0),
            ([token('当前持有：', .30, .684, width=.046), token('1,234', .349, .684, width=.036)], 1234),
        ):
            with self.subTest(held=held):
                frame = [*base, *fields]
                report = self.cli([frame, frame])
                preview = report['build_target']['preview']
                self.assertEqual(preview['held'], held)
                self.assertEqual(preview['state'], 'catalogue_candidates')
                self.assertTrue(all(preview[field] is None for field in
                                    ('shortfall', 'craftable', 'units_per_challenge', 'count', 'effective_limit')))
                self.assertNotIn('draft', report['build_target'])

    def test_missing_conflicting_or_changed_inventory_never_guesses_amount(self):
        base = [*self.material(), self.route('城郊雪原', .50)]
        label = token('当前持有：2', .31, .683, width=.07)
        for fields in (
            [token('2', .34, .683)],
            [replace(label, text='当前持有：O')],
            [label, token('当前持有：7', .31, .716, width=.07, score=.70)],
            [label, token('7', .362, .684, width=.025, score=.70)],
            [label, token('当前', .278, .716, width=.035), token('持有：7', .324, .716, width=.05)],
            [label, token('法吉娜之酒', .582, .326, width=.043, score=.78)],
            [replace(label, box=(.40, .668, .47, .698))],
        ):
            with self.subTest(fields=fields):
                frame = [*base, *fields]
                preview = self.cli([frame, frame])['build_target']['preview']
                self.assertIsNone(preview['held'])
                self.assertEqual(preview['state'], 'catalogue_candidates')

        two, three = [*base, label], [*base, replace(label, text='当前持有：3')]
        preview = self.cli([two, three])['build_target']['preview']
        self.assertEqual(preview['state'], 'catalogue_candidates')
        self.assertEqual(preview['source_locations'], ['城郊雪原'])
        self.assertIsNone(preview['held'])

    def test_wider_held_card_layout_supplies_inventory_without_a_route(self):
        frame = [
            *self.guide, token('《绒绒号》典藏版合集', .499, .322, width=.16),
            token('获得途径', .435, .672, width=.05), token('当前持有：2', .31, .686, width=.07),
            token('需要65', .46, .89),
        ]
        preview = self.cli([frame, frame])['build_target']['preview']
        self.assertEqual((preview['state'], preview['material'], preview['held']),
                         ('material_observed', '《绒绒号》典藏版合集', 2))
        self.assertEqual(preview['candidates'], [])
        self.assertEqual(preview['source_locations'], [])
        self.assertIsNone(preview['shortfall'])
        conflict = [*frame, token('法吉娜之酒', .582, .326, width=.043, score=.78)]
        preview = self.cli([conflict, conflict])['build_target']['preview']
        self.assertEqual(preview['state'], 'unverified')
        self.assertIsNone(preview['held'])

    def test_target_materials_sufficient_is_a_page_state_without_an_item_count(self):
        base = [*self.guide, token('角色培养', .45, .29),
                token('遗器推荐', .44, .50), token('培养设置', .24, .89)]
        enough = [*base, token('已获得足够的等级和行迹材料', .50, .40, width=.23)]
        data = self.cli([enough, enough])['build_target']
        preview = data['preview']
        self.assertTrue(data['page_verified'])
        self.assertEqual(preview['state'], 'target_materials_sufficient')
        self.assertEqual(preview['candidates'], [])
        self.assertIsNone(preview['shortfall'])

        calculator = [*base, token('需要获取的材料', .50, .40), token('材料总计', .51, .44),
                      token('需通过背包内多余材料合成的高稀有度材料', .50, .48)]
        preview = self.cli([calculator, calculator])['build_target']['preview']
        self.assertEqual(preview['state'], 'unverified')
        self.assertIsNone(preview['craftable'])
        for frame in (
            [*base, token('已获得足够的等级和行迹材料', .50, .74, width=.23)],
            [*enough, token('培养还需', .42, .42, width=.054), token('获取资源', .481, .42, width=.054)],
        ):
            with self.subTest(frame=frame):
                preview = self.cli([frame, frame])['build_target']['preview']
                self.assertEqual(preview['state'], 'unverified')

    def test_calyx_preview_cost_and_difficulty_are_separate_from_possible_rewards(self):
        for title, difficulty, rounds, cost, category, target, level in (
            ('回忆之蕾·拟造花萼（金）', 'V', 1, 10, 'calyx_golden', '回忆之蕾', 5),
            ('欢愉之蕾·拟造花萼（赤）', 'Ⅵ', 2, 20, 'calyx_crimson', '欢愉之蕾', 6),
            ('回忆之蕾·拟造花萼（金）', 'V', 24, 240, 'calyx_golden', '回忆之蕾', 5),
        ):
            with self.subTest(rounds=rounds):
                frame = self.calyx(rounds, cost, title=title, difficulty=difficulty)
                report = self.cli([frame, frame])
                preview = report['build_target']['preview']
                self.assertEqual(preview['state'], 'calyx_reward_preview')
                self.assertEqual(preview['calyx_reward_preview'], dict(
                    category=category, target=target, difficulty=level, selected_rounds=rounds,
                    shown_total_stamina=cost, rewards='possible_items', stamina_per_challenge=10,
                    selected_stamina_within_config=cost <= 20, max_draft_challenges_by_config=2))
                _, detail = _preview_text(preview)
                self.assertIn('单份草稿按配置最多 2 次', detail)
                self.assertIn('单轮保底待核对', detail)
                self.assertEqual('画面费用超过配置上限' in detail, cost > 20)
                self.assertEqual(preview['candidates'], [])
                self.assertTrue(all(preview[field] is None for field in
                                    ('held', 'shortfall', 'craftable', 'units_per_challenge', 'count', 'effective_limit')))
                self.assertNotIn('draft', report['build_target'])

    def test_calyx_preview_requires_count_cost_agreement_and_rejects_result_overlay(self):
        correct = self.calyx(1, 10)
        for frame in (
            self.calyx(1, 20),
            [*correct, token('挑战成功', .50, .21), token('上轮挑战波次1', .63, .77)],
            [*correct, token('×20', .69, .91, score=.70)],
            [*correct, token('×2O', .69, .91, score=.86)],
            [*correct, token('挑战次数', .74, .80), token('2', .852, .80)],
            [*correct, token('2', .861, .80)],
            [*correct, token('挑战', .694, .80, width=.04), token('次数2', .738, .80, width=.04)],
            [replace(t, text='10') if t.text == '×10' else t for t in correct],
            [t for t in correct if t.text != '可能获取'],
        ):
            with self.subTest(frame=frame):
                preview = self.cli([frame] * 8)['build_target']['preview']
                self.assertEqual(preview['state'], 'unverified')
                self.assertNotIn('calyx_reward_preview', preview)
        report = self.draft_cli([correct] * 8, code=1)
        self.assertNotIn('draft', report['build_target'])
        self.assertFalse((Path(report['run_dir']) / 'power-plan.json').exists())

    def test_preview_does_not_pair_across_a_discarded_capture(self):
        calyx = self.calyx(1, 10)
        overlay = [token('助手遮挡', .50, .50)]
        following = self.calyx(2, 20)
        frames = [calyx, overlay, calyx, following, calyx, following, calyx, following, calyx]
        with patch('autohsr.app.helper_overlay', side_effect=lambda scene: scene.has('助手遮挡', exact=True)):
            preview = self.cli(frames)['build_target']['preview']
        self.assertEqual(preview['state'], 'unverified')
        self.assertNotIn('calyx_reward_preview', preview)

    def test_explicit_draft_persists_one_selected_power_item_without_input_or_spend(self):
        self.settings.allow_stamina_spend = False
        frame = [*self.material(), self.route('流云渡', .46), self.route('城郊雪原', .50),
                 token('129', .45, .60), token('10', .70, .51)]
        report = self.draft_cli([frame, frame], count=2)
        self.assertEqual(report['status'], 'success')
        self.assertTrue(report['report_saved'])
        preview = report['build_target']['preview']
        self.assertTrue(all(preview[field] is None for field in ('shortfall', 'units_per_challenge', 'count', 'effective_limit')))
        draft = report['build_target']['draft']
        self.assertEqual((draft['state'], draft['mode'], draft['material'], draft['stamina_required']),
                         ('prepared', 'dry_run', '漫游指南', 20))
        self.assertEqual(draft['count_source'], 'manual')
        path = Path(report['run_dir']) / draft['file']
        self.assertEqual(path.name, 'power-plan.json')
        selected, = items(json.loads(path.read_text(encoding='utf-8')))
        self.assertEqual((selected.category, selected.target, selected.location, selected.count),
                         ('calyx_golden', '回忆之蕾', '城郊雪原', 2))
        self.assertEqual(draft['items'], [selected.to_dict()])

    def test_manual_round_cap_is_separate_from_config_capacity_and_source_availability(self):
        valid = [*self.material(), self.route('城郊雪原', .50)]
        truncated = token('拟造花萼〖城郊', .56, .56, width=.14)
        repeated = self.route('城郊雪原', .56)
        for limit, extra, capacity, cap, blocker in (
            (20, [], 2, 2, None),
            (240, [], 24, 6, None),
            (240, [truncated], 24, 6, 'incomplete_source'),
            (240, [repeated], 24, 6, 'repeated_location'),
        ):
            with self.subTest(limit=limit, blocker=blocker):
                self.settings.stamina_limit = limit
                frame = [*valid, *extra]
                report = self.cli([frame, frame])
                preview = report['build_target']['preview']
                source, = preview['candidates']
                self.assertEqual(source['max_challenges_by_config'], capacity)
                self.assertEqual(source['max_draft_challenges_by_config'], cap)
                self.assertEqual(source['manual_draft_blocker'], blocker)
                self.assertIsNone(preview['count'])

                panel = SimpleNamespace(**{name: Mock() for name in (
                    'build_title', 'build_detail', 'count', 'draft_detail', '_show_sources',
                    'source', 'open_target', 'times', 'count_hint', 'generate', 'add_draft', 'start')},
                    busy=False, ui=SimpleNamespace(busy=False, settings=self.settings))
                DailyPanel._present_preview(panel, report)
                self.assertEqual(panel.candidates, [] if blocker else [source])
                panel.source.current.return_value = -1 if blocker else 0
                DailyPanel._controls(panel)
                if blocker:
                    panel.generate.configure.assert_called_with(state='disabled')
                    self.assertIn('草稿待核对', panel.draft_detail.set.call_args.args[0])
                else:
                    panel.count_hint.configure.assert_called_with(text=f'手填 1～{cap} 次')
                    panel.times.configure.assert_called_with(to=cap, state='normal')
                    if cap < 6:
                        panel.count.get.return_value = str(cap + 1)
                        DailyPanel._generate(panel)
                        panel.start.assert_not_called()
                        self.assertIn(f'最多 {cap} 次', panel.draft_detail.set.call_args.args[0])
                    panel.count.get.return_value = str(cap)
                    DailyPanel._generate(panel)
                    self.assertEqual(panel.start.call_args.kwargs['build_target_selection'].count, cap)

    def test_draft_supports_exact_crimson_material_and_location(self):
        material, location = '法吉娜之心', '「辉痕圣林」神悟树庭'
        frame = [*self.material(material), self.route('流云渡', .46), self.route(location, .52)]
        report = self.draft_cli([frame, frame], material=material, location=location)
        self.assertEqual(report['build_target']['draft']['items'],
                         [dict(category='calyx_crimson', target='虚无之蕾', location=location, count=1)])

    def compose_sources(self, *, shadow=False):
        golden = [*self.material(), self.route('城郊雪原', .50)]
        if shadow:
            material, location = '海妖残鳍', '「酣歌海垠」斯缇科西亚'
            second = [*self.material(material), self.shadow_route(location)]
        else:
            material, location = '法吉娜之心', '「辉痕圣林」神悟树庭'
            second = [*self.material(material), self.route(location, .52)]
        drafts = (self.draft_cli([golden, golden], count=2),
                  self.draft_cli([second, second], material=material, location=location))
        receipts = [self.root / f'receipt-{index}.json' for index in range(len(drafts))]
        for path, report in zip(receipts, drafts):
            path.write_text(json.dumps(report, ensure_ascii=False), encoding='utf8')
        return drafts, receipts

    def compose_cli(self, receipts, *, stamina, output=None, code=0):
        args = ['--compose-build-target', *map(str, receipts), '--stamina', str(stamina)]
        if output is not None:
            args += ['--build-target-output', str(output)]
        with (patch('autohsr.build_target_compose.ROOT', self.root), patch.object(Settings, 'load') as load,
              patch('autohsr.app.find_game') as find, redirect_stdout(io.StringIO()) as stdout):
            self.assertEqual(main(args), code, stdout.getvalue())
        load.assert_not_called()
        find.assert_not_called()
        return json.loads(stdout.getvalue())

    def test_compose_preserves_manual_order_and_previews_a_shared_budget_before_publication(self):
        drafts, receipts = self.compose_sources()
        before = {path: path.read_bytes() for path in receipts}
        result = self.compose_cli(receipts[::-1], stamina=40)
        self.assertEqual((result['mode'], result['materials'], result['stamina_required'], result['stamina_remaining']),
                         ('preview', ['法吉娜之心', '漫游指南'], 30, 10))
        self.assertIs(result['game_accessed'], False)
        self.assertNotIn('output', result)
        output = self.root / 'new-plan.json'
        original_link = build_target_compose._link

        def publish_with_read_locks(staged, destination):
            for path in (*receipts, *(Path(draft['run_dir']) / 'power-plan.json' for draft in drafts)):
                with self.assertRaises(PermissionError), path.open('ab'):
                    pass
            original_link(staged, destination)

        with patch.object(build_target_compose, '_link', side_effect=publish_with_read_locks) as publish:
            prepared = self.compose_cli(receipts[::-1], stamina=30, output=output)
        publish.assert_called_once()
        self.assertEqual((prepared['mode'], prepared['stamina_remaining']), ('prepared', 0))
        self.assertEqual(hashlib.sha256(output.read_bytes()).hexdigest(), prepared['sha256'])
        self.assertEqual(items(json.loads(output.read_bytes())), items(result['items']))
        self.assertEqual(result['items'], [draft['build_target']['draft']['items'][0] for draft in drafts[::-1]])
        self.assertEqual({path: path.read_bytes() for path in receipts}, before)

    def test_compose_refuses_duplicates_over_budget_and_an_existing_output(self):
        _, receipts = self.compose_sources()
        output = self.root / 'new-plan.json'
        alternate = self.root / 'alternate-receipt.json'
        alternate.write_bytes(receipts[0].read_bytes())
        for selected, stamina in ((receipts, 20), ([receipts[0], receipts[0]], 40), ([receipts[0], alternate], 40)):
            with self.subTest(stamina=stamina):
                self.compose_cli(selected, stamina=stamina, output=output, code=1)
                self.assertFalse(output.exists())
        output.write_bytes(b'existing user plan')
        self.compose_cli(receipts, stamina=40, output=output, code=1)
        self.assertEqual(output.read_bytes(), b'existing user plan')

    def test_compose_refuses_staged_receipts_and_changed_original_evidence(self):
        drafts, receipts = self.compose_sources()
        run_dir = Path(drafts[0]['run_dir'])
        output = self.root / 'new-plan.json'
        self.compose_cli([run_dir / 'report.json', receipts[1]], stamina=40, output=output, code=1)
        evidence = run_dir / drafts[0]['build_target']['preview']['evidence']
        evidence.write_bytes(evidence.read_bytes() + b'changed')
        self.compose_cli(receipts, stamina=40, output=output, code=1)
        self.assertFalse(output.exists())

    def test_shadow_materials_match_bundled_dungeons_and_disambiguate_shared_locations(self):
        catalogue = load_catalogue(RESOURCE_ROOT / 'assets' / 'dungeons.json')
        for material, target in SHADOW_TARGETS.items():
            with self.subTest(material=material):
                self.assertEqual(sum(row.category == 'stagnant_shadow' and row.name == target for row in catalogue), 1)
        self.settings.stamina_limit = 60
        for material, target in (('铁狼碎齿', '锋芒之形'), ('过热钢刃', '燔灼之形')):
            frame = [*self.material(material), self.shadow_route('大矿区')]
            report = self.draft_cli([frame, frame], material=material, location='大矿区', count=2)
            draft = report['build_target']['draft']
            self.assertEqual(draft['stamina_required'], 60)
            self.assertEqual(draft['items'], [dict(category='stagnant_shadow', target=target,
                                                   location='大矿区', count=2)])

    def test_shadow_location_must_be_unique_unlocked_and_match_the_material(self):
        material, location = '海妖残鳍', '「酣歌海垠」斯缇科西亚'
        wrong = '「龙骸古城」斯缇科西亚'
        self.settings.stamina_limit = 60
        valid = [*self.material(material), self.shadow_route(location)]
        for frame in (
            [*self.material(material), self.shadow_route(wrong)],
            [*self.material(material), self.route(location, .52)],
            [*valid, token('未解锁', .73, .52, width=.065)],
            [*valid, self.shadow_route(wrong, .58)],
            [*valid, self.shadow_route(location, .58)],
            [*valid, self.route(location, .58)],
        ):
            with self.subTest(tokens=[field.text for field in frame[4:]]):
                report = self.draft_cli([frame, frame], material=material, location=location, code=1)
                self.assertNotIn('draft', report['build_target'])
        budget = self.draft_cli([valid, valid], material=material, location=location, count=3, code=1)
        self.assertIn('最多 2 次', budget['error'])

    def test_compose_supports_a_calyx_and_shadow_with_their_distinct_costs(self):
        self.settings.stamina_limit = 60
        _, receipts = self.compose_sources(shadow=True)
        result = self.compose_cli(receipts, stamina=50, output=self.root / 'mixed-plan.json')
        self.assertEqual(result['stamina_required'], 50)
        self.assertEqual([(row['category'], row['count']) for row in result['items']],
                         [('calyx_golden', 2), ('stagnant_shadow', 1)])

    def test_draft_refuses_unproven_source_and_out_of_budget_request(self):
        valid = [*self.material(), self.route('城郊雪原', .50)]
        locked = token('未解锁', .73, .50, width=.065)
        cases = {
            'different_material': [*self.material('凝缩以太'), self.route('城郊雪原', .50)],
            'different_location': [*self.material(), self.route('流云渡', .50)],
            'no_target_anchor': [*self.material(in_target=False), self.route('城郊雪原', .50)],
            'locked': [*valid, locked],
            'conflicting_same_location': [*valid, self.route('城郊雪原', .56), token('未解锁', .73, .56, width=.065)],
            'truncated_source': [*valid, token('拟造花萼〖城郊', .56, .56, width=.14)],
            'second_account': [*valid, token(fixtures.OTHER.text, .14, .97, score=.80)],
            'above_configured_limit': valid,
        }
        for name, frame in cases.items():
            with self.subTest(name=name):
                report = self.draft_cli([frame, frame], code=1, count=3 if name == 'above_configured_limit' else 1)
                self.assertEqual(report['status'], 'failed')
                self.assertNotIn('draft', report['build_target'])
                self.assertFalse((Path(report['run_dir']) / 'power-plan.json').exists())
                if name == 'above_configured_limit':
                    self.assertIn('本份草稿最多 2 次', report['error'])

    def test_draft_needs_two_consecutive_new_frames(self):
        frame = [*self.material(), self.route('城郊雪原', .50)]
        other = [*self.material(), self.route('流云渡', .50)]
        for frames in ([frame, EmptyCapture(), frame, []], [frame, other, frame, []]):
            with self.subTest(frames=len(frames)):
                report = self.draft_cli(frames, code=1)
                self.assertNotIn('draft', report['build_target'])

    def test_draft_cannot_pair_across_a_capture_discarded_by_context(self):
        frame = [*self.material(), self.route('城郊雪原', .50)]
        other = [*self.material('提纯以太'), self.route('城郊雪原', .50)]
        overlay = [token('助手遮挡', .50, .50)]
        frames = [frame, overlay, frame, other, frame, other, frame, other, frame]
        with patch('autohsr.app.helper_overlay', side_effect=lambda scene: scene.has('助手遮挡', exact=True)):
            report = self.draft_cli(frames, code=1)
        self.assertEqual(report['build_target']['preview']['state'], 'unverified')
        self.assertFalse((Path(report['run_dir']) / 'power-plan.json').exists())

    def test_draft_needs_saved_current_evidence_and_preserves_existing_file(self):
        frame = [*self.material(), self.route('城郊雪原', .50)]
        with patch.object(Context, 'evidence', return_value=None):
            report = self.draft_cli([frame, frame], code=1)
        self.assertNotIn('draft', report['build_target'])
        self.assertFalse((Path(report['run_dir']) / 'power-plan.json').exists())

        evidence = Context.evidence
        def collision(context, scene, label, **kwargs):
            if label == 'build_target_preview':
                (Path(context.report.run_dir) / 'power-plan.json').write_bytes(b'prior evidence')
            return evidence(context, scene, label, **kwargs)

        with patch.object(Context, 'evidence', collision):
            report = self.draft_cli([frame, frame], code=1)
        self.assertEqual(report['build_target']['draft']['state'], 'publication_failed')
        self.assertNotIn('file', report['build_target']['draft'])
        self.assertEqual((Path(report['run_dir']) / 'power-plan.json').read_bytes(), b'prior evidence')

    def test_draft_publishes_only_after_audit_and_holds_originals_during_each_link(self):
        frame = [*self.material(), self.route('城郊雪原', .50)]
        link = os.link
        publications = []

        def observe(source, destination):
            with self.assertRaises(PermissionError):
                Path(source).read_bytes()
            directory = destination.parent
            evidence, = directory.glob('*_build_target_preview.png')
            with self.assertRaises(PermissionError):
                evidence.unlink()
            plan = directory / 'power-plan.json'
            self.assertFalse(plan.exists())
            if destination == plan:
                report = directory / 'report.json'
                audit = json.loads(report.read_bytes())
                self.assertEqual(audit['status'], 'partial')
                self.assertEqual(audit['build_target']['draft']['state'], 'staged')
                self.assertNotIn('file', audit['build_target']['draft'])
                with self.assertRaises(PermissionError):
                    report.unlink()
            publications.append(destination.name)
            return link(source, destination)

        with patch('autohsr.build_target_draft.os.link', side_effect=observe):
            report = self.draft_cli([frame, frame])
        directory = Path(report['run_dir'])
        self.assertEqual(publications, ['report.json', 'power-plan.json'])
        self.assertEqual(report['build_target']['draft']['state'], 'prepared')
        self.assertEqual(hashlib.sha256((directory / 'power-plan.json').read_bytes()).hexdigest(),
                         report['build_target']['draft']['sha256'])
        self.assertEqual(list(directory.glob('.build-target-*.tmp')), [])

    def test_draft_does_not_publish_if_original_png_or_audit_changes_between_links(self):
        frame = [*self.material(), self.route('城郊雪原', .50)]
        hold = build_target_draft.hold_read_sources
        for original in ('screenshot', 'report'):
            with self.subTest(original=original):
                changed = []

                @contextmanager
                def race(paths):
                    if len(paths) == 2:
                        victim = paths[0] if original == 'screenshot' else paths[1]
                        replacement = victim.with_suffix('.replacement')
                        replacement.write_bytes(victim.read_bytes() + b' ')
                        replacement.replace(victim)
                        changed.append(victim)
                    with hold(paths):
                        yield

                with patch.object(build_target_draft, 'hold_read_sources', side_effect=race):
                    report = self.draft_cli([frame, frame], code=1)
                directory = Path(report['run_dir'])
                self.assertEqual(len(changed), 1)
                self.assertTrue(changed[0].read_bytes().endswith(b' '))
                self.assertEqual(report['build_target']['draft']['state'], 'publication_failed')
                self.assertFalse((directory / 'power-plan.json').exists())
                self.assertEqual(list(directory.glob('.build-target-*.tmp')), [])

    def test_draft_preserves_a_report_or_plan_appearing_at_its_exclusive_link(self):
        frame = [*self.material(), self.route('城郊雪原', .50)]
        link = os.link
        for filename in ('report.json', 'power-plan.json'):
            with self.subTest(filename=filename):
                def race(source, destination):
                    if destination.name == filename:
                        destination.write_bytes(b'earlier report or plan')
                        with build_target_draft.hold_read_sources((destination,)):
                            return link(source, destination)
                    return link(source, destination)

                with patch('autohsr.build_target_draft.os.link', side_effect=race):
                    report = self.draft_cli([frame, frame], code=1)
                directory = Path(report['run_dir'])
                self.assertEqual(report['report_saved'], filename == 'power-plan.json')
                self.assertEqual((directory / filename).read_bytes(), b'earlier report or plan')
                self.assertEqual((directory / 'power-plan.json').exists(), filename == 'power-plan.json')
                self.assertNotIn('file', report['build_target']['draft'])
                self.assertEqual(list(directory.glob('.build-target-*.tmp')), [])

    def test_draft_f10_epoch_or_link_failure_after_audit_does_not_publish(self):
        frame = [*self.material(), self.route('城郊雪原', .50)]
        link = os.link
        guard = build_target_draft.DraftSource.guard
        for failure in ('f10', 'epoch', 'write'):
            with self.subTest(failure=failure):
                def interrupt(source):
                    if (source.directory / 'report.json').exists() and failure == 'epoch':
                        runner = source.reader.ctx.runner
                        runner.toggle_pause()
                        runner.toggle_pause()
                    return guard(source)

                def fail_link(source, destination):
                    if destination.name == 'power-plan.json' and failure == 'write':
                        raise OSError('simulated plan publication failure')
                    return link(source, destination)

                with (patch.object(fixtures.Window, 'emergency_pressed', side_effect=[False, failure == 'f10']),
                      patch.object(build_target_draft.DraftSource, 'guard', interrupt),
                      patch('autohsr.build_target_draft.os.link', side_effect=fail_link)):
                    report = self.draft_cli([frame, frame], code=1)
                directory = Path(report['run_dir'])
                self.assertEqual(report['status'], 'stopped' if failure == 'f10' else 'failed')
                self.assertTrue(report['report_saved'])
                self.assertEqual(report['build_target']['draft']['state'], 'publication_failed')
                self.assertNotIn('file', report['build_target']['draft'])
                self.assertFalse((directory / 'power-plan.json').exists())
                self.assertEqual(list(directory.glob('.build-target-*.tmp')), [])

    def test_draft_rechecks_window_and_controls_after_account_read_before_each_link(self):
        from autohsr.build_target_read import account_key
        from autohsr.models import FocusLost

        frame = [*self.material(), self.route('城郊雪原', .50)]
        guard = build_target_draft.DraftSource.guard
        for audit_exists in (False, True):
            for failure in ('focus', 'f10', 'stop', 'epoch'):
                with self.subTest(audit_exists=audit_exists, failure=failure):
                    changed = []

                    def interrupt(source):
                        if (source.directory / 'report.json').exists() != audit_exists:
                            return guard(source)
                        ctx = source.reader.ctx

                        def lost(expected):
                            raise FocusLost('fixture window lost focus during account read')

                        def read_account(scene, confidence):
                            key = account_key(scene, confidence)
                            if confidence >= source.reader.confidence:
                                changed.append(True)
                                if failure == 'focus':
                                    ctx.window.guard = lost
                                elif failure == 'f10':
                                    ctx.window.emergency_pressed = lambda: True
                                elif failure == 'stop':
                                    ctx.runner.stop()
                                else:
                                    ctx.runner.input_epoch += 1
                            return key

                        with patch('autohsr.build_target_read.account_key', side_effect=read_account):
                            return guard(source)

                    with patch.object(build_target_draft.DraftSource, 'guard', interrupt):
                        report = self.draft_cli([frame, frame], code=1)
                    directory = Path(report['run_dir'])
                    self.assertEqual(changed, [True])
                    self.assertEqual(report['status'], 'stopped' if failure in ('f10', 'stop') else 'failed')
                    self.assertEqual(report['report_saved'], audit_exists)
                    self.assertEqual(report['build_target']['draft']['state'], 'publication_failed')
                    self.assertNotIn('file', report['build_target']['draft'])
                    audit = directory / 'report.json'
                    self.assertEqual(audit.is_file(), audit_exists)
                    if audit_exists:
                        self.assertEqual(json.loads(audit.read_bytes())['build_target']['draft']['state'], 'staged')
                    self.assertFalse((directory / 'power-plan.json').exists())
                    self.assertEqual(list(directory.glob('.build-target-*.tmp')), [])

    def test_draft_stop_or_epoch_in_final_key_poll_prevents_publication(self):
        frame = [*self.material(), self.route('城郊雪原', .50)]
        guard = build_target_draft.DraftSource.guard
        for failure in ('stop', 'epoch'):
            with self.subTest(failure=failure):
                def interrupt(source):
                    if (source.directory / 'report.json').is_file():
                        ctx = source.reader.ctx

                        def poll():
                            if failure == 'stop':
                                ctx.runner.stop()
                            else:
                                ctx.runner.input_epoch += 1
                            return False

                        ctx.window.emergency_pressed = poll
                    return guard(source)

                with patch.object(build_target_draft.DraftSource, 'guard', interrupt):
                    report = self.draft_cli([frame, frame], code=1)
                self.assertTrue(report['report_saved'])
                self.assertEqual(report['status'], 'stopped' if failure == 'stop' else 'failed')
                self.assertEqual(report['build_target']['draft']['state'], 'publication_failed')
                self.assertFalse((Path(report['run_dir']) / 'power-plan.json').exists())

    def test_draft_requires_explicit_scoped_arguments_before_loading_settings(self):
        valid = ['--build-target', '--material', '漫游指南', '--location', '城郊雪原', '--count', '1']
        cases = (valid[:-2], ['--run', *valid], [*valid, '--stamina', '240'],
                 [*valid, '--power-plan'], [*valid, '--output-plan', 'battle-session.json'],
                 ['--preview-build-target', '--material', '漫游指南'],
                 [*valid[:-1], '0'], [*valid[:-1], '7'])
        for argv in cases:
            with (self.subTest(argv=argv), patch.object(Settings, 'load') as load,
                  redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error):
                main(argv)
            self.assertEqual(error.exception.code, 2)
            load.assert_not_called()

    def test_draft_context_blocks_gameplay_input_and_budget_options(self):
        request = BuildTargetSelection('漫游指南', '城郊雪原', 1)
        with self.assertRaises(ValueError):
            Runner(self.settings, operation='build_target_plan')
        with self.assertRaises(ValueError):
            Runner(self.settings, operation='build_target_plan', build_target_selection=request, new_battle_run=True)
        runner = Runner(self.settings, operation='build_target_plan', build_target_selection=request)
        context = Context(runner, object(), None)
        for action in (lambda: context.key('esc'), lambda: context.click(None, self.entry),
                       lambda: context.move(None, self.entry.center), lambda: context.scroll(120),
                       lambda: context.drag(None, (.2,.2), (.3,.3))):
            with self.assertRaisesRegex(AutomationError, '只观察'):
                action()

    def test_generated_file_can_be_explicitly_run_by_the_existing_power_plan_entry(self):
        from autohsr.power_plan_store import read, validate
        from autohsr.tests.test_power_plan import World, row
        from autohsr.tests.test_power_plan_entry import runtime

        frame = [*self.material(), self.route('城郊雪原', .50)]
        draft = self.draft_cli([frame, frame])
        path = Path(draft['run_dir']) / draft['build_target']['draft']['file']
        original = path.read_bytes()
        settings = Settings(assignments=False, daily=False, daily_synthesis=False, use_support=False,
                            overlay_logs=False, stamina_limit=20, target_location='绘世学院',
                            power_plan=[row('cavern', 1, '侵蚀隧洞', '残响回廊')], echo_of_war_enabled=True)
        config = self.root / 'battle-config.json'
        settings.save(config)
        saved = config.read_bytes()
        for owned, completed in ((20, 1), (9, 0)):
            with self.subTest(owned=owned):
                root = self.root / f'run-{owned}'
                world = World(stamina=owned)
                output, logs = io.StringIO(), io.StringIO()
                with (runtime(root, settings, world) as (window, _), redirect_stdout(output), redirect_stderr(logs)):
                    def create(*args, **kwargs):
                        runner = Runner(*args, **kwargs)
                        window.owner = runner
                        return runner

                    with patch('autohsr.app.Runner', side_effect=create):
                        self.assertEqual(main(['--run', '--config', str(config), '--power-plan', '--power-plan-file',
                                               str(path), '--keep-power-plan', '--no-fill-power-plan',
                                               '--no-echo-of-war']), 0, logs.getvalue())
                report = json.loads(output.getvalue())
                ledger = read(root / 'runs' / 'battle-session.json')
                validate(root / 'runs', ledger, settled=True)
                self.assertEqual(report['operation'], 'daily')
                self.assertEqual(report['build_target'], {})
                self.assertEqual(ledger['power_plan']['items'], json.loads(original))
                self.assertEqual(ledger['power_plan']['before'], [0])
                self.assertEqual(ledger['power_plan']['done'], [completed])
                self.assertEqual(ledger['power_plan']['goal_complete'], bool(completed))
                self.assertEqual([charge['row'] for charge in ledger['power_plan']['charges']], [0] * completed)
                self.assertEqual((ledger['spent'], ledger['completed'], ledger['pending']), (10 * completed, completed, 0))
                self.assertEqual(world.paid, [('回忆之蕾', 1, 10)] * completed)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(config.read_bytes(), saved)

    def test_explicitly_running_a_prepared_file_preserves_an_old_pending_payment(self):
        from autohsr.tests.test_power_plan_entry import runtime

        frame = [*self.material(), self.route('城郊雪原', .50)]
        draft = self.draft_cli([frame, frame])
        path = Path(draft['run_dir']) / draft['build_target']['draft']['file']
        plan = path.read_bytes()
        config = self.root / 'config.json'
        saved = config.read_bytes()
        ledger = self.root / 'runs' / 'battle-session.json'
        pending = b'{"version":1,"spent":0,"pending":10,"limit":20,"status":"active"}'
        ledger.write_bytes(pending)
        args = ['--run', '--power-plan', '--power-plan-file', str(path), '--config', str(config)]
        for options in ([], ['--new-battle-run']):
            with self.subTest(options=options):
                output, logs = io.StringIO(), io.StringIO()
                with (runtime(self.root, self.settings) as (window, find),
                      patch.object(Runner, '_prepare_daily_game') as prepare,
                      redirect_stdout(output), redirect_stderr(logs)):
                    self.assertEqual(main([*args, *options]), 1, logs.getvalue())
                prepare.assert_not_called()
                find.assert_not_called()
                self.assertEqual(window.world.paid, [])
                self.assertIn('上次刷本支付仍待核对', json.loads(output.getvalue())['error'])
                self.assertEqual(ledger.read_bytes(), pending)
        self.assertEqual(path.read_bytes(), plan)
        self.assertEqual(config.read_bytes(), saved)

    def test_cli_preserves_every_exact_location_without_claiming_a_plan_or_quantity(self):
        frame = [*self.material(), self.route('流云渡', .46), self.route('城郊雪原', .50),
                 self.route('筑梦边境', .55), token('129', .45, .60), token('10', .70, .51)]
        report = self.cli([frame, frame])
        self.assertEqual(report['status'], 'partial')
        preview = report['build_target']['preview']
        self.assertEqual(preview['material'], '漫游指南')
        self.assertTrue(preview['target_section_visible'])
        self.assertEqual(preview['configured_limit'], 20)
        for field in ('shortfall', 'units_per_challenge', 'count', 'effective_limit'):
            self.assertIsNone(preview[field])
        self.assertEqual([(row['category'], row['target'], row['location'], row['stamina_cost'],
                           row['max_challenges_by_config']) for row in preview['candidates']],
                         [('calyx_golden', '回忆之蕾', site, 10, 2)
                          for site in ('流云渡', '城郊雪原', '筑梦边境')])
        self.assertTrue((Path(report['run_dir']) / preview['evidence']).is_file())
        with self.assertRaises(SettingsError):
            items(preview['candidates'])

    def test_cli_second_complete_footer_uid_blocks_at_collection_confidence(self):
        frame = [*self.material(), self.route('流云渡', .48), token(fixtures.OTHER.text, .14, .97, score=.80)]
        report = self.cli([frame, frame])
        self.assertEqual(report['build_target']['preview']['candidates'], [])
        self.assertEqual(report['build_target']['preview']['state'], 'unverified')
        self.assertEqual(report['status'], 'failed')

    def test_cli_second_exact_material_title_blocks_at_collection_confidence(self):
        frame = self.material()
        frame[-2] = token('漫游指南', .45, .322, width=.07)
        frame.extend((token('提纯以太', .528, .322, score=.78, width=.065), self.route('流云渡', .48)))
        report = self.cli([frame, frame])
        self.assertEqual(report['build_target']['preview']['candidates'], [])
        self.assertEqual(report['build_target']['preview']['state'], 'unverified')
        self.assertEqual(report['status'], 'failed')

    def test_cli_complete_catalogue_row_with_weak_entry_keeps_detail_only(self):
        fields = [field for field in self.catalogue if .58 <= field.center[1] <= .66 and field.center[0] > .4]
        row = [replace(field, score=.80) if field.text == '进入' else field for field in fields]
        frame = [*self.material(), self.route('绘世学院', .48), *row]
        report = self.cli([frame, frame])
        preview = report['build_target']['preview']
        self.assertEqual(preview['candidates'], [])
        self.assertEqual(preview['state'], 'material_observed')
        self.assertEqual(preview['source_locations'], ['绘世学院'])
        self.assertFalse(preview['target_section_visible'])

    def test_cli_source_heading_within_catalogue_row_cannot_prove_detail(self):
        row = [token('回忆之蕾', .48, .42, width=.06), token('进入', .81, .44),
               token('绘世学院', .49, .46, width=.06)]
        for y in (.42, .46):
            with self.subTest(heading_y=y):
                frame = [*self.material()[:-1], token('获得途径', .55, y, width=.06),
                         *row, self.route('流云渡', .52)]
                report = self.cli([frame, frame])
                preview = report['build_target']['preview']
                self.assertEqual(preview['candidates'], [])
                self.assertEqual(preview['state'], 'unverified')
                self.assertEqual(preview['source_locations'], [])

    def test_cli_weak_uid_alone_cannot_bind_the_account(self):
        frame = [*self.material(), self.route('流云渡', .48)]
        frame = [replace(field, score=.80) if field == fixtures.ACCOUNT else field for field in frame]
        report = self.cli([frame, frame])
        self.assertEqual(report['build_target']['preview']['state'], 'unverified')
        self.assertEqual(report['build_target']['preview']['candidates'], [])

    def test_cli_incomplete_or_out_of_position_fields_do_not_veto_detail(self):
        frame = [*self.material(), self.route('流云渡', .48),
                 token('UID:1234567', .14, .97, score=.80), token(fixtures.OTHER.text, .14, .91, score=.80),
                 token('提纯以太', .595, .322, score=.78, width=.08),
                 token('回忆之蕾', .48, .60), token('绘世学院', .49, .64),
                 token('进入', .81, .56, score=.80)]
        preview = self.cli([frame, frame])['build_target']['preview']
        self.assertEqual(preview['state'], 'catalogue_candidates')
        self.assertEqual([row['location'] for row in preview['candidates']], ['流云渡'])

    def test_material_family_and_exact_location_are_both_required_for_red_calyx(self):
        for name, location, target in (
            ('《绒绒号》手绘分镜稿', '「世界尽头」酒馆', '欢愉之蕾'),
            ('法吉娜之心', '「辉痕圣林」神悟树庭', '虚无之蕾'),
        ):
            with self.subTest(material=name):
                frame = [*self.material(name), self.route('城郊雪原', .47), self.route(location, .55),
                         token('万能合成机-等量置换', .53, .50, width=.18)]
                preview = self.native([frame, frame]).build_target['preview']
                self.assertEqual(preview['material'], name)
                self.assertEqual(preview['unmatched_calyx_rows'], 1)
                self.assertEqual([(row['category'], row['target'], row['location']) for row in preview['candidates']],
                                 [('calyx_crimson', target, location)])

    def test_observes_ordinary_target_panel_without_assigning_materials_or_counts(self):
        frame = [*self.guide, token('培养还需获取资源', .46, .29, width=.13), token('28', .38, .39),
                 token('10', .71, .39), token('进入', .84, .39)]
        report = self.native([frame, frame])
        self.assertTrue(report.build_target['page_verified'])
        preview = report.build_target['preview']
        self.assertEqual(preview['state'], 'panel_observed')
        self.assertEqual(preview['candidates'], [])
        self.assertIsNone(preview['shortfall'])

    def test_visible_detail_without_cultivation_context_keeps_observation_only(self):
        modal = self.material(in_target=False)[len(self.guide):]
        for background in (self.guide, self.catalogue,
                           [*self.catalogue, token('培养还需获取资源', .46, .273, width=.13)]):
            frame = [*background, *modal, self.route('绘世学院', .48)]
            preview = self.native([frame, frame]).build_target['preview']
            self.assertEqual(preview['state'], 'material_observed')
            self.assertEqual(preview['material'], '漫游指南')
            self.assertFalse(preview['target_section_visible'])
            self.assertEqual(preview['source_locations'], ['绘世学院'])
            self.assertEqual(preview['candidates'], [])

    def test_weak_truncated_or_displaced_fields_do_not_bind_material_source(self):
        for frame in (
            [*self.material('《绒绒号》典'), self.route('「世界尽头」酒馆', .48)],
            [*self.material(score=.79), self.route('城郊雪原', .48)],
            [*self.material()[:-1], token('获得途径', .48, .75), self.route('城郊雪原', .48)],
            [*self.material(), token('获得途径', .48, .43), self.route('城郊雪原', .48)],
            [*self.material(), token('获得途径', .48, .75), self.route('城郊雪原', .48)],
            [*self.material(), token('遗失碎金', .525, .323), self.route('城郊雪原', .48)],
            [*self.material('未知晋阶材料'), token('凝滞虚影〖「龙骸古城」斯缇科西亚〗', .57, .48)],
            self.catalogue,
        ):
            with self.subTest(fields=[field.text for field in frame[4:]]):
                report = self.native([frame, frame])
                self.assertEqual(report.status, 'failed')
                self.assertEqual(report.build_target['preview']['state'], 'unverified')
                self.assertEqual(report.build_target['preview']['candidates'], [])

    def test_material_survives_unreadable_and_conflicting_source_rows(self):
        frame = [*self.material(), self.route('城郊雪原', .445), self.route('流云渡', .45),
                 token('拟造花萼〖筑梦边境', .56, .50), self.route('流云渡', .55, score=.72),
                 self.route('未知地点', .59)]
        preview = self.native([frame, frame]).build_target['preview']
        self.assertEqual(preview['state'], 'material_observed')
        self.assertEqual(preview['material'], '漫游指南')
        self.assertEqual(preview['unmatched_calyx_rows'], 5)
        self.assertEqual(preview['candidates'], [])

    def test_split_secondary_source_heading_blocks_projection(self):
        frame = [*self.material(), self.route('城郊雪原', .48),
                 token('获得', .46, .73, width=.039), token('途径', .506, .73, width=.039)]
        preview = self.native([frame, frame]).build_target['preview']
        self.assertEqual(preview['state'], 'unverified')
        self.assertEqual(preview['candidates'], [])

    def test_split_calyx_prefix_blocks_manual_draft_but_preserves_visible_source(self):
        original = [*self.material(), self.route('城郊雪原', .48)]
        for fragments in (
            [token('拟造', .45, .56, width=.036), token('花萼〖城郊雪原〗', .545, .56, width=.144)],
            [token('拟', .434, .56, width=.02), token('造花', .467, .56, width=.036),
             token('萼〖流云渡〗', .548, .56, width=.112)],
        ):
            with self.subTest(parts=[part.text for part in fragments]):
                frame = [*original, *fragments]
                report = self.draft_cli([frame, frame], code=1)
                self.assertNotIn('draft', report['build_target'])
                self.assertFalse((Path(report['run_dir']) / 'power-plan.json').exists())
                preview = self.native([frame, frame]).build_target['preview']
                self.assertEqual(preview['source_locations'], ['城郊雪原'])
                self.assertEqual(preview['unmatched_calyx_rows'], 1)
                self.assertEqual(preview['candidates'][0]['manual_draft_blocker'], 'incomplete_source')
                self.assertIsNone(preview['count'])
        off_row = [*original, token('拟造', .45, .55, width=.036),
                   token('花萼〖城郊雪原〗', .545, .60, width=.144)]
        report = self.draft_cli([off_row, off_row])
        self.assertEqual(report['build_target']['draft']['items'][0]['location'], '城郊雪原')

    def test_source_with_same_line_lock_marker_is_excluded(self):
        for marker in ([token('尚未解锁', .74, .48, width=.06)],
                       [token('尚未', .72, .48, width=.039), token('解锁', .766, .48, width=.039)]):
            frame = [*self.material(), self.route('城郊雪原', .48), self.route('流云渡', .54), *marker]
            preview = self.native([frame, frame]).build_target['preview']
            self.assertEqual(preview['lock_marker_rows'], 1)
            self.assertEqual([row['location'] for row in preview['candidates']], ['流云渡'])

    def test_material_preview_obeys_split_authentication_and_conflicting_overlay_guard(self):
        frame = [*self.material(), self.route('城郊雪原', .48)]
        for overlay in ([token('账号', .46, .57, width=.039), token('登录', .506, .57, width=.039)],
                        [token('选择角色', .49, .60)]):
            with self.subTest(overlay=[field.text for field in overlay]):
                report = self.native([[*frame, *overlay]])
                self.assertEqual(report.build_target['preview']['state'], 'unverified')

    def test_requires_two_consecutive_same_account_observations_with_same_sources(self):
        first = [*self.material(), self.route('城郊雪原', .48)]
        second = [*self.material(), self.route('流云渡', .48)]
        switched = [fixtures.OTHER if field == fixtures.ACCOUNT else field for field in first]
        for frames in ([first, switched], [first, EmptyCapture(), first, EmptyCapture()], [first, second] * 4):
            report = self.native(frames)
            self.assertEqual(report.build_target['preview']['state'], 'unverified')
            self.assertEqual(report.build_target['preview']['candidates'], [])

    def test_evidence_saved_during_epoch_change_remains_unverified(self):
        frame = [*self.material(), self.route('城郊雪原', .48)]
        original = Context.evidence

        def save(ctx, scene, label, **kwargs):
            path = original(ctx, scene, label, **kwargs)
            if label == 'build_target_preview':
                ctx.runner.input_epoch += 1
            return path

        with patch.object(Context, 'evidence', save):
            report = self.native([frame, frame])
        preview = report.build_target['preview']
        self.assertEqual(preview['state'], 'unverified')
        self.assertTrue((Path(report.run_dir) / preview['evidence']).is_file())

    def test_preview_publication_rejects_changed_or_replaced_original_even_if_bytes_match(self):
        from autohsr.build_target_preview import run_preview

        frame = [*self.material(), self.route('城郊雪原', .48), token('当前持有：2', .31, .684, width=.07)]
        for same_bytes in (False, True):
            with self.subTest(same_bytes=same_bytes):
                def replace_original(ctx, **kwargs):
                    result = run_preview(ctx, **kwargs)
                    preview = ctx.report.build_target['preview']
                    self.assertEqual(preview['held'], 2)
                    original = Path(ctx.report.run_dir) / preview['evidence']
                    temporary = original.with_suffix('.replacement')
                    temporary.write_bytes(original.read_bytes() + (b'' if same_bytes else b' changed'))
                    temporary.replace(original)
                    return result

                with patch('autohsr.build_target_preview.run_preview', side_effect=replace_original):
                    report = self.cli([frame, frame])
                self.assertEqual(report['status'], 'failed')
                self.assertTrue(report['report_saved'])
                preview = report['build_target']['preview']
                self.assertEqual(preview['state'], 'unverified')
                self.assertEqual(preview['candidates'], [])
                self.assertIsNone(preview['held'])
                self.assertTrue((Path(report['run_dir']) / preview['evidence']).is_file())
                audit = json.loads((Path(report['run_dir']) / 'report.json').read_text(encoding='utf-8'))
                self.assertEqual(audit['build_target']['preview'], preview)

    def test_preview_cannot_send_input_or_open_a_new_budget(self):
        with self.assertRaises(ValueError):
            Runner(self.settings, operation='build_target_preview', new_battle_run=True)
        with self.assertRaises(SettingsError):
            Settings(stamina_limit=25).validate('build_target_preview')
        window = fixtures.Window([])
        ctx = Context(Runner(self.settings, operation='build_target_preview'), window, window)
        scene = Scene(self.material())
        for action, args in ((ctx.click, (scene, self.entry)), (ctx.key, ('esc',)),
                             (ctx.move, (scene, (.2, .3))), (ctx.scroll, (100,)),
                             (ctx.drag, (scene, (.2, .3), (.3, .4))), (ctx.build_target_entry_input, (scene,))):
            with self.subTest(action=action.__name__), self.assertRaises(AutomationError):
                action(*args)
        self.assertEqual(window.clicks, [])

    def test_preview_cli_rejects_run_and_file_based_plan_arguments(self):
        for args in (['--run'], ['--read-build-target'], ['--power-plan-file', 'manual.json'], ['--stamina', '10']):
            with (self.subTest(args=args), patch('autohsr.app.Runner') as native,
                  redirect_stderr(io.StringIO()), self.assertRaises(SystemExit)):
                main(['--preview-build-target', *args])
            native.assert_not_called()
