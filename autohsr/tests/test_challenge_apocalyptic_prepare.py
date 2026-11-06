"""Preparation recognition with synthetic OCR and the real CLI/Context on fake IO."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.challenge_apocalyptic_prepare import observe
from autohsr.challenge_prepare import ChallengePreparation
from autohsr.models import AutomationError, EmptyCapture, Scene, Token
from autohsr.tests.test_challenge_integration import PLAN, prepare_with_fake_window
from autohsr.vision import Vision


APOCALYPTIC_PLAN = dict(PLAN, mode='apocalyptic_shadow', levels=[3, 4])
UID = Token('UID:100000000', .99, (.012, .961, .106, .986))


def text(value, box, score=.99):
    return Token(value, score, box)


def frame(kind, *, level='03', node=1, include_uid=True):
    title = text('末日幻影', (.053, .032, .100, .061))
    if kind == 'lobby':
        tokens = [text('末日幻影', (.054, .047, .108, .077)),
                  text('支配遗忘', (.451, .506, .556, .543)),
                  text('前往挑战', (.475, .765, .527, .790)),
                  text('01', (.211, .877, .233, .907)),
                  text('尚未挑战', (.234, .882, .281, .909)),
                  text('02尚未挑战', (.358, .881, .428, .909)),
                  text('03尚未挑战', (.505, .880, .576, .909)),
                  text('04未解锁', (.650, .878, .711, .909))]
    elif kind == 'boss_info':
        label = ('节点一勾魂摄魄的支配者', '节点二|迷惘之渊的裁定者')[node - 1]
        tokens = [title, text('首领信息', (.053, .058, .106, .090)),
                  text(level, (.412, .118, .448, .159)), text('难度', (.411, .156, .444, .183)),
                  text(label, (.460, .119, .641, .149)),
                  text('等级80|建议属性', (.459, .154, .627, .186)),
                  text('本期不再提示', (.652, .890, .729, .917)),
                  text('下一步' if node == 1 else '前编队', (.816, .888, .868, .919))]
    else:
        tokens = [title, text('编队', (.052, .057, .082, .090)),
                  text('角色编队', (.392, .120, .469, .155)),
                  text('难度' + level, (.138, .191, .174, .213)),
                  text('支配遗忘', (.117, .223, .194, .260)),
                  text('节点一｜', (.511, .214, .570, .245)),
                  text('勾魂摄魄的支配者', (.568, .214, .689, .244)),
                  text('节点二迷惘之渊的裁定者', (.511, .478, .688, .508)),
                  text('前往挑战', (.795, .897, .849, .925))]
    return Scene(tokens + ([UID] if include_uid else []), np.full((1080, 1920, 3), 32, np.uint8),
                 captured_at=time.monotonic())


class ApocalypticPreparationPageTests(unittest.TestCase):
    def test_each_page_preserves_its_own_fields_and_never_has_a_target(self):
        for kind, node, level in (('lobby', None, None), ('boss_info', 1, 3),
                                  ('boss_info', 2, 3), ('node_setup', None, 3)):
            with self.subTest(kind=kind, node=node):
                page = observe(frame(kind, node=node))
                self.assertEqual((page.kind, page.level, page.basis.get('node')), (kind, level, node))
                self.assertEqual(page.targets, ())
                self.assertFalse(page.basis['execution_supported'])
                self.assertEqual(page.basis['button']['activation'], 'unknown')
                self.assertEqual(page.basis['button']['caption_verified'], node != 2)

    def test_exact_split_and_fullwidth_level_with_conflicting_or_weak_difficulty(self):
        scene = frame('node_setup')
        level = scene.tokens.pop(3)
        scene.tokens.extend([text('难度', (.137, .191, .156, .213)),
                             text('０２', (.156, .191, .174, .213))])
        self.assertEqual(observe(scene).level, 2)
        scene.tokens.append(replace(level, score=.76))
        self.assertEqual((observe(scene).kind, observe(scene).level), ('node_setup', None))
        scene.tokens[-3:] = [replace(level, score=.82), text('等级80', (.459, .154, .627, .186))]
        self.assertEqual((observe(scene).kind, observe(scene).level), ('node_setup', None))
        scene = frame('node_setup')
        scene.tokens.append(text('难度04', (.124, .187, .174, .213), .78))
        self.assertEqual((observe(scene).kind, observe(scene).level), ('node_setup', None))

    def test_wrong_page_or_modal_with_the_same_button_is_rejected(self):
        for base, extra in (
            ('lobby', [text('已更新', (.782, .367, .824, .396))]),
            ('lobby', [text('难度', (.475, .170, .500, .190), .78),
                       text('03', (.501, .170, .523, .190), .78),
                       text('新难等级解锁', (.466, .191, .533, .212), .91)]),
            ('lobby', [text('未', (.371, .40, .38, .42)), text('解锁', (.382, .40, .402, .42))]),
            ('lobby', [text('前往', (.847, .884, .870, .910)), text('挑战', (.871, .884, .901, .910))]),
            ('boss_info', [text('当前队伍', (.376, .721, .422, .746)),
                           text('不可更换', (.539, .820, .593, .845)),
                           text('前往挑战', (.847, .883, .901, .912))]),
            ('node_setup', [text('星启', (.819, .766, .855, .791), .77)]),
            ('node_setup', [text('节点３', (.511, .736, .570, .769), .77)]),
            ('node_setup', [text('前往节点二', (.794, .890, .869, .921))]),
            ('node_setup', [text('确认', (.455, .51, .480, .54), .72)]),
        ):
            with self.subTest(base=base, extra=extra):
                scene = frame(base)
                scene.tokens.extend(extra)
                self.assertEqual((observe(scene).kind, observe(scene).targets), ('unknown', ()))

    def test_page_cannot_borrow_wrong_row_or_tail(self):
        scene = frame('boss_info', node=2)
        scene.tokens[2] = replace(scene.tokens[2], box=(.458, .153, .486, .180))
        self.assertEqual(observe(scene).kind, 'unknown')
        scene = frame('boss_info', node=2)
        scene.tokens[7] = replace(scene.tokens[7], text='下一步', score=.74)
        self.assertEqual(observe(scene).kind, 'unknown')
        scene = frame('node_setup')
        scene.tokens[7] = replace(scene.tokens[7], text='节点一迷惘之渊的裁定者')
        self.assertEqual(observe(scene).kind, 'unknown')

    def test_boss_header_can_merge_difficulty_and_node_without_guessing_a_missing_field(self):
        scene = frame('boss_info', node=2)
        scene.tokens[2] = text('０３节点二｜迷惘之渊的裁定者', (.412, .110, .643, .160))
        del scene.tokens[4]
        page = observe(scene)
        self.assertEqual((page.kind, page.level, page.basis['node']), ('boss_info', 3, 2))
        del scene.tokens[3]
        self.assertEqual(observe(scene).kind, 'unknown')


class ApocalypticPreparationEntryTests(unittest.TestCase):
    def run_cli(self, scenes, *, foreground=True, vision=None, confidence=.65):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        code, report, window = prepare_with_fake_window(Path(directory.name), scenes,
            plan=APOCALYPTIC_PLAN, foreground=foreground, vision=vision, confidence=confidence)
        for method in (window.click, window.key, window.focus, window.drag, window.send):
            method.assert_not_called()
        self.assertEqual((report['battle_completed'], report['stamina_spent']), (0, 0))
        run = Path(report['run_dir'])
        self.assertTrue(report['report_saved'])
        self.assertEqual(json.loads((run / 'report.json').read_bytes()), report)
        return code, report, run, window

    def test_all_four_pages_write_reviewable_two_capture_receipts(self):
        for kind, node, expected in (('lobby', None, 'page_observed'), ('boss_info', 1, 'page_observed'),
                                      ('boss_info', 2, 'page_observed'), ('node_setup', None, 'prepared')):
            with self.subTest(kind=kind, node=node):
                source = frame(kind, node=node)
                code, report, run, _ = self.run_cli([source, source])
                data = report['challenge']
                self.assertEqual(code, int(kind != 'node_setup'))
                self.assertEqual((data['status'], data['actions'], data['selected_level']), (expected, [], None))
                self.assertEqual(data['preparation_page_verified'], kind == 'node_setup')
                for field in ('team_verified', 'battle_started', 'completion_verified'):
                    self.assertFalse(data[field])
                page = data['page_observation']
                self.assertEqual((page['kind'], page['node']), (kind, node))
                rows = page['frames']
                self.assertEqual([row['capture_sequence'] for row in rows], [1, 2])
                self.assertLess(rows[0]['captured_at'], rows[1]['captured_at'])
                self.assertNotEqual(rows[0]['path'], rows[1]['path'])
                for row in rows:
                    self.assertEqual(row['geometry'], [0, 0, 1920, 1080])
                    self.assertEqual(row['sha256'], hashlib.sha256(Path(row['path']).read_bytes()).hexdigest())
                self.assertEqual(json.loads((run / 'challenge-preparation.json').read_bytes()), data)

    def test_other_level_and_missing_level_are_observations_only(self):
        for level, value in (('02', 2), ('', None)):
            with self.subTest(level=level):
                scene = frame('node_setup', level=level)
                code, report, _, _ = self.run_cli([scene, scene])
                data = report['challenge']
                self.assertEqual((code, data['status'], data['page_observation']['level']), (1, 'page_observed', value))
                self.assertFalse(data['preparation_page_verified'])

    def test_blank_missing_uid_and_discarded_overlay_reset_continuity(self):
        scene = frame('node_setup')
        overlay = frame('node_setup')
        overlay.tokens.extend(text(label, (.72, .50, .84, .54)) for label in ('AutoHSR', '运行日志', '保存设置'))
        for gap in (EmptyCapture('blank'), frame('node_setup', include_uid=False), overlay):
            with self.subTest(gap=type(gap)):
                code, report, _, _ = self.run_cli([scene, gap, scene, scene])
                self.assertEqual(code, 0)
                self.assertEqual([row['capture_sequence'] for row in
                                  report['challenge']['preparation_frames']], [3, 4])

    def test_distinct_boss_pages_cannot_form_a_pair(self):
        one, two = frame('boss_info', node=1), frame('boss_info', node=2)
        code, report, _, _ = self.run_cli([one, two, two])
        page = report['challenge']['page_observation']
        self.assertEqual((code, page['node']), (1, 2))
        self.assertEqual([row['capture_sequence'] for row in page['frames']], [2, 3])

    def test_changed_or_ambiguous_uid_and_background_prevent_receipt(self):
        for conflict in (False, True):
            with self.subTest(conflict=conflict):
                scene = frame('node_setup')
                other = frame('node_setup', include_uid=conflict)
                other.tokens.append(text('UID:200000000', (.130, .961, .235, .986), .80 if conflict else .98))
                code, report, _, _ = self.run_cli([scene, other, scene, scene])
                self.assertEqual(code, 1)
                self.assertNotIn('page_observation', report['challenge'])
                self.assertIn('多个完整' if conflict else '账号改变', report['error'])
        code, report, _, window = self.run_cli([frame('node_setup')], foreground=False)
        self.assertEqual((code, report['status'], window.capture.call_count), (1, 'failed', 0))

    def test_uid_counterevidence_survives_a_raised_collection_threshold(self):
        first, second = frame('node_setup'), frame('node_setup')
        second.tokens.append(text('UID:200000000', (.131, .961, .232, .987), .74))
        batches = iter((first.tokens, second.tokens))

        def engine(_image, *, use_cls):
            raw = []
            for token in next(batches):
                x1, y1, x2, y2 = token.box
                points = [(x * 1920, y * 1080) for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
                raw.append((points, token.text, token.score))
            return raw, None

        vision = Vision.__new__(Vision)
        vision.confidence, vision.engine = .80, engine
        code, report, _, _ = self.run_cli([first, second], vision=vision, confidence=.80)
        self.assertEqual(code, 1)
        self.assertIn('多个完整', report['error'])
        self.assertNotIn('page_observation', report['challenge'])

    def test_replaced_runner_mode_cannot_turn_preparation_into_focused_observation(self):
        original = Runner.run

        def run(runner):
            runner.settings.challenge_plan = APOCALYPTIC_PLAN
            return original(runner)

        with tempfile.TemporaryDirectory() as folder, patch.object(Runner, 'run', run):
            code, report, window = prepare_with_fake_window(Path(folder), [])
        self.assertEqual((code, report['input_error_field']), (1, 'challenge_plan'))
        window.focus.assert_not_called()
        window.capture.assert_not_called()

    def test_changed_first_png_prevents_receipt_publication(self):
        original = ChallengePreparation._publish_apocalyptic

        def publish(workflow, pair, deadline):
            Path(pair[0].source['path']).write_bytes(b'changed fixture')
            return original(workflow, pair, deadline)

        with patch.object(ChallengePreparation, '_publish_apocalyptic', publish):
            scene = frame('node_setup')
            code, report, run, _ = self.run_cli([scene, scene])
        self.assertEqual((code, report['status']), (1, 'failed'))
        self.assertFalse(report['challenge']['preparation_page_verified'])
        self.assertEqual(json.loads((run / 'challenge-preparation.json').read_bytes()), report['challenge'])

    def test_same_png_cannot_supply_two_observations(self):
        original = Context.evidence
        saved = None

        def evidence(context, scene, name):
            nonlocal saved
            if name == 'challenge_apocalyptic_2':
                return saved
            value = original(context, scene, name)
            if name == 'challenge_apocalyptic_1':
                saved = value
            return value

        with patch.object(Context, 'evidence', evidence):
            scene = frame('node_setup')
            code, report, _, _ = self.run_cli([scene, scene])
        self.assertEqual(code, 1)
        self.assertIn('独立原图', report['error'])
        self.assertNotIn('page_observation', report['challenge'])

    def test_pixels_used_by_ocr_cannot_change_before_evidence_is_saved(self):
        original = Context.evidence

        def evidence(context, scene, name):
            if name.startswith('challenge_apocalyptic_'):
                scene.image[100:130, 100:130] = 79
            return original(context, scene, name)

        with patch.object(Context, 'evidence', evidence):
            scene = frame('node_setup')
            code, report, _, _ = self.run_cli([scene, scene])
        self.assertEqual(code, 1)
        self.assertIn('像素发生变化', report['error'])
        self.assertNotIn('page_observation', report['challenge'])

    def test_window_geometry_is_rechecked_after_reading_sources(self):
        original = ChallengePreparation._recheck_apocalyptic

        def check(workflow, pair, deadline):
            original_read = workflow._read_png

            def changed_geometry(expected=None):
                if expected is not None:
                    raise AutomationError('fixture window moved')

            def read(path):
                value = original_read(path)
                workflow.c.window.guard.side_effect = changed_geometry
                return value

            with patch.object(workflow, '_read_png', side_effect=read):
                original(workflow, pair, deadline)

        with patch.object(ChallengePreparation, '_recheck_apocalyptic', check):
            scene = frame('node_setup')
            code, report, _, _ = self.run_cli([scene, scene])
        self.assertEqual(code, 1)
        self.assertIn('fixture window moved', report['error'])
        self.assertNotIn('page_observation', report['challenge'])

    def test_pending_final_report_is_rechecked_on_sharing_retry(self):
        original = Path.replace
        attempts = []

        def replace_report(path, target):
            if path.name == 'report.tmp' and not attempts:
                attempts.append(1)
                path.write_bytes(b'changed pending report')
                raise PermissionError('fixture sharing violation')
            return original(path, target)

        with patch.object(Path, 'replace', replace_report):
            scene = frame('node_setup')
            code, report, run, _ = self.run_cli([scene, scene])
        self.assertEqual((code, report['status'], attempts), (1, 'partial', [1]))
        self.assertFalse(report['challenge']['preparation_page_verified'])
        self.assertNotIn('page_observation', report['challenge'])
        self.assertTrue(json.loads((run / 'challenge-preparation.json').read_bytes())['preparation_page_verified'])

    def test_parent_report_cannot_publish_different_fields_from_the_receipt(self):
        original = ChallengePreparation.save_report

        def save(workflow, temporary, write_report):
            workflow.data['page_observation']['level'] = 4
            original(workflow, temporary, write_report)

        with patch.object(ChallengePreparation, 'save_report', save):
            scene = frame('node_setup')
            code, report, run, _ = self.run_cli([scene, scene])
        self.assertEqual((code, report['status']), (1, 'partial'))
        self.assertNotIn('page_observation', report['challenge'])
        self.assertEqual(json.loads((run / 'challenge-preparation.json').read_bytes())['page_observation']['level'], 3)

    def test_stop_or_epoch_change_in_the_last_native_guard_blocks_report_success(self):
        original = ChallengePreparation.save_report
        for event, expected_status in (('stop', 'stopped'), ('epoch', 'partial')):
            with self.subTest(event=event):
                def save(workflow, temporary, write_report):
                    def guard(expected=None):
                        if expected is not None:
                            if event == 'stop':
                                workflow.c.runner.stop()
                            else:
                                workflow.c.runner.input_epoch += 1

                    workflow.c.window.guard.side_effect = guard
                    original(workflow, temporary, write_report)

                with patch.object(ChallengePreparation, 'save_report', save):
                    scene = frame('node_setup')
                    code, report, run, _ = self.run_cli([scene, scene])
                self.assertEqual((code, report['status']), (1, expected_status))
                self.assertFalse(report['challenge']['preparation_page_verified'])
                self.assertTrue(json.loads((run / 'challenge-preparation.json').read_bytes())['preparation_page_verified'])
