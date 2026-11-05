"""Synthetic material layouts with released catalogue fields and the native runner."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings, SettingsError
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

    def native(self, frames):
        with self.runtime(frames) as window:
            runner = Runner(self.settings, operation='build_target_preview')
            report = runner.run()
        self.assertEqual(window.clicks, [])
        self.assertIsNone(runner.battle_budget)
        self.assertEqual((report.stamina_spent, report.stamina_pending, report.battle_completed), (0, 0, 0))
        return report

    def cli(self, frames):
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
            self.assertEqual(main(['--preview-build-target', '--config', str(config)]), 1)
        notify.assert_not_called()
        budget.assert_not_called()
        self.assertEqual(window.clicks, [])
        report = json.loads(output.getvalue())
        self.assertEqual(report['operation'], 'build_target_preview')
        self.assertEqual(report['build_target']['entry_input'], 'not_sent')
        self.assertEqual(report['power_plan'], {})
        self.assertEqual((report['stamina_spent'], report['stamina_pending'], report['battle_completed']), (0, 0, 0))
        self.assertNotIn('123456789', output.getvalue() + logs.getvalue())
        self.assertNotIn('123456780', output.getvalue() + logs.getvalue())
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(ledger.read_bytes(), b'existing payment evidence')
        return report

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
            [*self.material('侵略凝块'), token('凝滞虚影〖「龙骸古城」斯缇科西亚〗', .57, .48)],
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

        def save(ctx, scene, label):
            path = original(ctx, scene, label)
            if label == 'build_target_preview':
                ctx.runner.input_epoch += 1
            return path

        with patch.object(Context, 'evidence', save):
            report = self.native([frame, frame])
        preview = report.build_target['preview']
        self.assertEqual(preview['state'], 'unverified')
        self.assertTrue((Path(report.run_dir) / preview['evidence']).is_file())

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
