"""Use pinned crops and synthetic layout in the real CLI, Runner and Context."""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
from itertools import count
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2
import numpy as np

from autohsr.__main__ import main
from autohsr import challenge_pages as pages
from autohsr.app import Context, Runner
from autohsr.challenge_result import ResultReader, observe_feedback
from autohsr.config import Settings
from autohsr.models import AutomationError, EmptyCapture, FocusLost, RunReport, Scene, Token
from autohsr.vision import Vision
from autohsr.windows import Geometry
from autohsr.workflow_lease import _kernel


FLAG = '--challenge-result'
LOCK = f'Local\\AutoHSR.HighResults.Tests.{os.getpid()}.{uuid4().hex}'
GEO = Geometry(4, 8, 960, 540)
FIXTURES = Path(__file__).parent / 'fixtures' / 'du_runtime'


def token(text, xyxy, score=.99):
    return Token(text, score, tuple(value / size for value, size in zip(xyxy, (960, 540, 960, 540))))


ACCOUNT = token('UID:123456789', (14, 514, 92, 532))
OTHER = token('UID:123456780', (14, 514, 92, 532), .74)
FICTION = ('purefiction/back.png', '返回虚构叙事', 689, 468)
FICTION_FINAL = (*FICTION[:2], 444, 495)
NEXT = ('apocalyptic/next_node.png', '前往节点二', 550, 468)
RETURN = ('apocalyptic/back.png', '返回末日幻影', 688, 468)
FAILURE = ('purefiction/fail.png', None, 461, 125)


def frame(*parts, uid=ACCOUNT, extra=()):
    image = np.full((GEO.height, GEO.width, 3), 24, dtype=np.uint8)
    tokens = [uid] if uid else []
    for filename, caption, x, y in parts:
        original = cv2.imread(str(pages.ASSET_ROOT / filename))
        width, height = round(original.shape[1] / 2), round(original.shape[0] / 2)
        image[y:y + height, x:x + width] = cv2.resize(original, (width, height), interpolation=cv2.INTER_AREA)
        if caption:
            tokens.append(token(caption, (x, y, x + width, y + height)))
    return Scene(tokens + list(extra), image, GEO, time.monotonic())


STAGE = token('取象为文其四', (448, 54, 512, 66))
SUCCESS = token('挑战成功', (414, 70, 546, 105))
TOTAL = token('积分65840', (431, 109, 528, 128))
NODE_ONE = token('节点一25840', (326, 160, 417, 174))
NODE_TWO = token('节点二40000', (544, 160, 635, 174))
FINAL_FIELDS = (STAGE, SUCCESS, TOTAL, NODE_ONE, NODE_TWO)
GOALS = (
    token('获得30000分', (293, 215, 369, 229)),
    token('获得40000分', (293, 264, 369, 278)),
    token('获得50000分', (293, 290, 369, 304)),
    token('获得60000分', (293, 316, 369, 330)),
)


def fiction_final(fields=FINAL_FIELDS, *, uid=ACCOUNT, extra=()):
    return frame(FICTION_FINAL, uid=uid, extra=(*fields, *GOALS, *extra))


def formatted_final():
    return fiction_final((
        token('取象为文·', (448, 54, 493, 66)), token('其四', (495, 54, 518, 66)),
        SUCCESS,
        token('积分：', (431, 109, 462, 128)), token('６５', (464, 109, 482, 128)),
        token('，', (483, 111, 488, 128)), token('８４０', (489, 109, 529, 128)),
        token('节点一', (326, 160, 364, 174)), token('25,840', (372, 160, 418, 174)),
        token('节点二', (544, 160, 580, 174)), token('４０，０００', (590, 160, 636, 174)),
    ), extra=(token('新纪录', (540, 109, 579, 128)),))


class FictionScoreObservationTests(unittest.TestCase):
    def test_merged_and_split_comma_fields_read_the_same_total(self):
        for scene in (fiction_final(), formatted_final()):
            observed = observe_feedback(scene)
            self.assertEqual(observed.mode, 'pure_fiction')
            score = observed.score
            self.assertEqual((score.total, score.node_one, score.node_two), (65840, 25840, 40000))
        equal_parts = (STAGE, SUCCESS, replace(TOTAL, text='积分80000'),
                       replace(NODE_ONE, text='节点一40000'), NODE_TWO)
        self.assertEqual(observe_feedback(fiction_final(equal_parts)).score.total, 80000)

    def test_title_success_and_three_labeled_reads_are_independently_required(self):
        variants = [FINAL_FIELDS[:i] + FINAL_FIELDS[i + 1:] for i in range(len(FINAL_FIELDS))]
        variants.extend((
            (replace(STAGE, text='立界开篇其四'), *FINAL_FIELDS[1:]),
            (replace(STAGE, text='取象为文其三'), *FINAL_FIELDS[1:]),
            (STAGE, replace(SUCCESS, text='挑战成功积分65840'), NODE_ONE, NODE_TWO),
            (STAGE, replace(SUCCESS, text='挑战结束'), TOTAL, NODE_ONE, NODE_TWO),
            (STAGE, SUCCESS, replace(TOTAL, text='获得65840分'), NODE_ONE, NODE_TWO),
            (STAGE, SUCCESS, replace(TOTAL, text='当前积分65840'), NODE_ONE, NODE_TWO),
            (STAGE, SUCCESS, TOTAL, replace(NODE_ONE, text='25840'), NODE_TWO),
            (STAGE, SUCCESS, TOTAL, replace(NODE_ONE, text='节点—25840'), NODE_TWO),
            (STAGE, SUCCESS, TOTAL, NODE_ONE, replace(NODE_TWO, score=.79)),
        ))
        for fields in variants:
            with self.subTest(fields=fields):
                observed = observe_feedback(fiction_final(fields))
                self.assertEqual(observed.mode, 'pure_fiction')
                self.assertIsNone(observed.score)

    def test_exact_numeric_grammar_and_printed_total(self):
        for text in ('积分6,5840', '积分65，84', '积分65 840', '积分65\n840', '积分65840.0',
                     '积分+65840', '积分65840分', '积分65841'):
            with self.subTest(text=text):
                fields = (STAGE, SUCCESS, replace(TOTAL, text=text), NODE_ONE, NODE_TWO)
                self.assertIsNone(observe_feedback(fiction_final(fields)).score)
        split = (token('积分', (431, 109, 456, 128)), token('65', (462, 109, 482, 128)),
                 token('840', (491, 109, 528, 128)))
        self.assertIsNone(observe_feedback(fiction_final((STAGE, SUCCESS, *split, NODE_ONE, NODE_TWO))).score)
        large = (STAGE, SUCCESS, replace(TOTAL, text='积分200000'),
                 replace(NODE_ONE, text='节点一100000'), replace(NODE_TWO, text='节点二100000'))
        self.assertIsNone(observe_feedback(fiction_final(large)).score)
        over_cap = (STAGE, SUCCESS, replace(TOTAL, text='积分65841'),
                    NODE_ONE, replace(NODE_TWO, text='节点二40001'))
        self.assertIsNone(observe_feedback(fiction_final(over_cap)).score)

    def test_overlaps_separate_rows_and_displaced_reads_are_ambiguous(self):
        total_label = token('积分', (431, 109, 464, 126))
        variants = (
            (STAGE, SUCCESS, total_label, token('65840', (460, 109, 528, 128)), NODE_ONE, NODE_TWO),
            (STAGE, SUCCESS, token('积分', (431, 104, 461, 113)),
             token('65840', (465, 119, 528, 132)), NODE_ONE, NODE_TWO),
            (STAGE, SUCCESS, token('积分65840', (431, 109, 549, 128)), NODE_ONE, NODE_TWO),
            (STAGE, SUCCESS, token('积分65840', (431, 190, 528, 204)), NODE_ONE, NODE_TWO),
            (STAGE, SUCCESS, TOTAL, replace(NODE_ONE, text='节点二40000'), replace(NODE_TWO, text='节点一25840')),
            (STAGE, SUCCESS, TOTAL, token('节点一25840节点二40000', (326, 160, 635, 174))),
            (*FINAL_FIELDS, token('1000', (464, 160, 499, 174))),
            (*FINAL_FIELDS, token('999', (522, 109, 550, 126), .70)),
            (*FINAL_FIELDS, token('积分70000', (547, 109, 630, 128))),
            (STAGE, SUCCESS, TOTAL,
             token('节点一', (326, 156, 363, 178)), token('25840', (371, 157, 417, 163)),
             token('节点二', (544, 156, 580, 178)), token('40000', (591, 170, 635, 176))),
        )
        for fields in variants:
            with self.subTest(fields=fields):
                self.assertIsNone(observe_feedback(fiction_final(fields)).score)

    def test_other_modes_and_uncalibrated_returns_keep_only_local_feedback(self):
        for scene in (frame(NEXT, RETURN, extra=FINAL_FIELDS),
                      frame(NEXT, RETURN, extra=(replace(SUCCESS, text='挑战结束'), TOTAL, NODE_ONE, NODE_TWO)),
                      frame(FICTION, extra=FINAL_FIELDS),
                      frame(FICTION_FINAL, FAILURE, extra=FINAL_FIELDS),
                      fiction_final(extra=(token('前往节点三', (641, 478, 727, 495)),)),
                      fiction_final(extra=(token('星启模式', (715, 41, 784, 58)),)),
                      fiction_final(extra=(token('通关详情', (695, 41, 768, 58)),))):
            with self.subTest(words=scene.text):
                self.assertIsNone(observe_feedback(scene).score)


class ResultObservationTests(unittest.TestCase):
    def test_pinned_caption_and_glyph_need_same_frame_and_mode(self):
        observed = observe_feedback(frame(FICTION, FAILURE))
        self.assertEqual(observed.mode, 'pure_fiction')
        self.assertEqual([a.text for a in observed.anchors], ['fiction_result_return', 'result_failure'])
        self.assertIsNone(observe_feedback(frame(FAILURE)))
        self.assertIsNone(observe_feedback(frame(FICTION, NEXT, FAILURE)))
        self.assertIsNone(observe_feedback(frame(FICTION, (NEXT[0], None, *NEXT[2:]), FAILURE)))
        self.assertIsNone(observe_feedback(frame(NEXT, (FICTION[0], None, *FICTION[2:]))))
        self.assertEqual([a.text for a in observe_feedback(frame(FICTION)).anchors], ['fiction_result_return'])

    def test_caption_fragments_are_local_and_complete(self):
        scene = frame(FICTION)
        first = token('返回', (689, 468, 711, 479))
        second = token('虚构叙事', (713, 468, 759, 479))
        scene.tokens = [ACCOUNT, first, second]
        self.assertIsNotNone(observe_feedback(scene))
        for bad in (token('虚构叙事', (700, 468, 759, 479)), token('虚构叙事', (713, 454, 759, 466)),
                    token('虚构叙事', (713, 468, 759, 479), .79), token('虚构', (713, 468, 746, 479))):
            with self.subTest(bad=bad):
                scene.tokens = [ACCOUNT, first, bad]
                self.assertIsNone(observe_feedback(scene))

    def test_caption_pixels_are_unique_and_required(self):
        original = frame(FICTION)
        text_only = frame(extra=original.tokens[1:])
        self.assertIsNone(observe_feedback(text_only))
        duplicate = frame(FICTION, (*FICTION[:2], 537, 433))
        self.assertIsNone(observe_feedback(duplicate))
        distant_text = frame((FICTION[0], None, 689, 468), extra=[token('返回虚构叙事', (125, 300, 197, 311))])
        self.assertIsNone(observe_feedback(distant_text))

    def test_guide_details_and_split_modal_do_not_become_results(self):
        for fragments in ((token('星际和平指南', (20, 20, 88, 33)),),
                          (token('更换编队', (812, 412, 904, 426)),),
                          (token('将清空当前', (234, 222, 285, 236), .76),
                           token('挑战队伍和对应节点积分', (286, 222, 439, 236), .74)),
                          (token('获得奖励', (420, 180, 500, 195)),),
                          (token('支付100星琼', (420, 180, 520, 195)),),
                          (token('购买材料', (420, 180, 500, 195)),),
                          (token('确认领取', (420, 180, 488, 195)),),
                          (token('确认', (420, 180, 450, 195)), token('领取', (452, 180, 488, 195)))):
            with self.subTest(fragments=fragments):
                self.assertIsNone(observe_feedback(frame(NEXT, RETURN, extra=fragments)))

    def test_public_redacted_neighbors_are_wrong_pages(self):
        fixtures = {
            'adventure_hanu_result': '594c52965e8ff312623698062b7ef77bbf7fb6cc871c7383361699b0b7db318c',
            'curio_discard_generic_prompt': '4388f4af3981c0be8f1609c2d9434c4f5050b1cd9fa01c93fecb1cf149a59cae',
            'planar_preset_enabled': '0c245a79e29a4f6568e6f349b4e3872d193d7a18cb388f3e617645d4151323b2',
        }
        for name, sha256 in fixtures.items():
            with self.subTest(name=name):
                fixture = FIXTURES / name
                metadata = json.loads(fixture.with_suffix('.json').read_text(encoding='utf-8'))
                raw = fixture.with_suffix('.png').read_bytes()
                self.assertTrue(metadata['masked_identifiers'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), sha256)
                image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                scene = Scene([Token(**t) for t in metadata['tokens']], image, captured_at=time.monotonic())
                self.assertIsNone(observe_feedback(scene))


class FakeWindow:
    hwnd = 1

    def __init__(self, frames, geometry):
        self.frames = iter(frames)
        self.geometry = geometry
        self.capture_count = 0
        self.foreground = True
        self.focus = Mock(side_effect=AssertionError('focus'))
        self.click = Mock(side_effect=AssertionError('click'))
        self.key = Mock(side_effect=AssertionError('key'))

    def capture(self):
        self.capture_count += 1
        self.current = next(self.frames, EmptyCapture('fixture transition'))
        if isinstance(self.current, Exception):
            raise self.current
        return self.current.image.copy(), self.geometry

    def guard(self, expected=None):
        if not self.foreground:
            raise FocusLost('fixture background')
        if expected is not None and expected != self.geometry:
            raise AssertionError('unexpected window geometry')
        return self.geometry

    def read(self, image, geometry):
        return Scene(list(self.current.tokens), image, geometry)


class ResultEntryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / 'config.json'
        Settings(game_path=str(self.root / 'StarRail.exe'), overlay_logs=True, battle=True,
                 allow_stamina_spend=True).save(self.config)

    @contextmanager
    def runtime(self, frames, *, use_vision=False, geometry=GEO):
        window = FakeWindow(frames, geometry)
        ticks = count(100, .01)
        clock = SimpleNamespace(monotonic=lambda: next(ticks))
        native = _kernel()
        mutex = Mock(side_effect=lambda security, owner, _name: native.CreateMutexW(security, owner, LOCK))
        with ExitStack() as stack:
            patches = {
                'autohsr.app.ROOT': self.root,
                'autohsr.app.time': clock,
                'autohsr.challenge_result.time': clock,
                'autohsr.challenge_pages.time': clock,
                'autohsr.app.threading.Thread': Mock(),
                'autohsr.app.is_elevated': Mock(return_value=False),
                'autohsr.app.find_game': Mock(return_value=window),
                'autohsr.windows.kernel32': SimpleNamespace(CreateMutexW=mutex, CloseHandle=native.CloseHandle),
                'autohsr.workflow_lease.NAME': LOCK + '.Workflow',
                'autohsr.windows.user32': Mock(),
            }
            if not use_vision:
                patches['autohsr.app.Vision'] = Mock(return_value=window)
            for name, value in patches.items():
                stack.enter_context(patch(name, value))
            forbidden = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in (
                'autohsr.app.Runner._prepare_daily_game', 'autohsr.app.Runner.wait_for_focus',
                'autohsr.notify_runtime.hooks', 'autohsr.workflow_identity.prepare',
                'autohsr.du_reward_store.preflight', 'autohsr.du_archive_store.preflight',
                'autohsr.currency_wars_weekly_reward_store.RewardStore', 'autohsr.overlay.OverlayService',
                'autohsr.recovery.BattleBudget')]
            stack.enter_context(patch.object(Runner, '_arm_hotkeys'))
            stack.enter_context(patch.object(Context, 'sleep', lambda ctx, _seconds: ctx.checkpoint()))
            yield window
            mutex.assert_called_once()
            for mock in (*forbidden, window.focus, window.click, window.key):
                mock.assert_not_called()
            self.assertEqual(patches['autohsr.windows.user32'].mock_calls, [])

    def run_cli(self, frames, **runtime):
        stdout, stderr = io.StringIO(), io.StringIO()
        with self.runtime(frames, **runtime), redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(main([FLAG, '--config', str(self.config)]), 1, stderr.getvalue())
        output = stdout.getvalue()
        self.assertNotIn('123456789', output + stderr.getvalue())
        self.assertNotIn('123456780', output + stderr.getvalue())
        report = json.loads(output)
        self.assertTrue(report['report_saved'])
        self.assertEqual(json.loads((Path(report['run_dir']) / 'report.json').read_bytes()), report)
        self.assertEqual(report['operation'], 'challenge_result')
        self.assertEqual((report['challenge'], report['currency_wars'], report['differential_universe']), ({}, {}, {}))
        self.assertEqual((report['battle_completed'], report['stamina_spent'], report['stamina_pending']), (0, 0, 0))
        return report

    def test_cli_waits_for_complete_feedback_after_the_score_animation(self):
        intro = frame(extra=(STAGE, SUCCESS, replace(TOTAL, text='积分25840')))
        animating = frame(extra=(STAGE, SUCCESS, TOTAL))
        report = self.run_cli([intro, animating, fiction_final(), formatted_final()])
        data = report['challenge_result']
        self.assertEqual((report['status'], data['status'], data['total_score']), ('partial', 'feedback_verified', 65840))
        self.assertIn('已核实本次虚构叙事总分', report['results'][0]['detail'])
        self.assertEqual([row['capture_sequence'] for row in data['evidence']], [3, 4])
        for field in ('level', 'half', 'node', 'upper_half_score', 'lower_half_score',
                      'node_one_score', 'node_two_score', 'stars'):
            self.assertIsNone(data[field])
        self.assertEqual((data['outcome'], data['settlement_status']), ('unknown', 'unknown'))
        self.assertFalse(data['completion_verified'])
        self.assertFalse(data['rewards_verified'])
        self.assertEqual(json.loads((Path(report['run_dir']) / 'challenge-result.json').read_bytes()), data)

    def test_missing_changed_or_displaced_number_retains_the_old_pair(self):
        same_label = token('节点一', (326, 157, 365, 177))
        left_number = token('25840', (371, 161, 417, 165))
        right_node = token('节点二40000', (544, 157, 635, 177))
        first = fiction_final((STAGE, SUCCESS, TOTAL, same_label, left_number, right_node))
        moved = fiction_final((STAGE, SUCCESS, TOTAL, same_label, token('25840', (371, 169, 417, 173)), right_node))
        self.assertEqual(observe_feedback(first).score.total, 65840)
        self.assertEqual(observe_feedback(moved).score.total, 65840)
        changed_parts = (STAGE, SUCCESS, TOTAL, replace(NODE_ONE, text='节点一27000'),
                         replace(NODE_TWO, text='节点二38840'))
        changed_total = (STAGE, SUCCESS, replace(TOTAL, text='积分65841'),
                         replace(NODE_ONE, text='节点一25841'), NODE_TWO)
        for second in (fiction_final((STAGE, SUCCESS, TOTAL, NODE_ONE)), fiction_final(changed_parts),
                       fiction_final(changed_total), moved):
            with self.subTest(words=second.text):
                report = self.run_cli([first, second, EmptyCapture('page left after legacy pair')])
                data = report['challenge_result']
                self.assertEqual(data['status'], 'feedback_verified')
                self.assertIsNone(data['total_score'])
                self.assertEqual([row['capture_sequence'] for row in data['evidence']], [1, 2])

    def test_total_pair_cannot_cross_an_unidentified_frame(self):
        good = fiction_final()
        report = self.run_cli([good, fiction_final(uid=None), good, good])
        data = report['challenge_result']
        self.assertEqual(data['total_score'], 65840)
        self.assertEqual([row['capture_sequence'] for row in data['evidence']], [3, 4])

    def test_score_fields_are_rechecked_at_receipt_and_final_report_retries(self):
        original_snapshot = Context.snapshot
        replace_path = Path.replace
        for target in ('challenge-result.json', 'report.json'):
            with self.subTest(target=target):
                attempts = []
                captured = []

                def snapshot(context):
                    scene = original_snapshot(context)
                    captured.append(scene)
                    return scene

                def share(source, destination):
                    if destination.name == target and not attempts:
                        attempts.append(destination)
                        scene = captured[-1]
                        index = scene.tokens.index(TOTAL)
                        scene.tokens[index] = replace(TOTAL, text='积分65841')
                        raise PermissionError('simulated sharing lock')
                    return replace_path(source, destination)

                with patch.object(Context, 'snapshot', snapshot), patch.object(Path, 'replace', share):
                    report = self.run_cli([fiction_final(), fiction_final()])
                self.assertEqual(len(attempts), 1)
                data = report['challenge_result']
                self.assertEqual(data['status'], 'unknown')
                self.assertIsNone(data['total_score'])
                receipt = Path(report['run_dir']) / 'challenge-result.json'
                if target == 'report.json':
                    self.assertEqual(json.loads(receipt.read_bytes())['total_score'], 65840)
                else:
                    self.assertFalse(receipt.exists())

    def test_formal_cli_preserves_old_roster_and_reports_only_verified_feedback(self):
        historical = self.root / 'runs' / 'old-preparation' / 'challenge-preparation.json'
        historical.parent.mkdir(parents=True)
        historical.write_bytes(b'{"completion_verified":true,"stars":3,"total_score":99999}')
        config = self.config.read_bytes()
        feedback = frame(FICTION, FAILURE, extra=(token('上半', (380, 220, 405, 232)),
                         token('总分99999', (475, 233, 542, 248)), token('12/12', (758, 30, 794, 46))))
        report = self.run_cli([feedback, feedback])
        data = report['challenge_result']
        directory = Path(report['run_dir'])
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(data['status'], 'feedback_verified')
        self.assertEqual(data['mode'], 'pure_fiction')
        self.assertTrue(data['failure_marker_observed'])
        self.assertEqual(data['visible_controls'], ['返回虚构叙事'])
        self.assertEqual(data['outcome'], 'unknown')
        self.assertEqual(data['settlement_status'], 'unknown')
        self.assertFalse(data['completion_verified'])
        self.assertFalse(data['rewards_verified'])
        for field in ('level', 'half', 'upper_half_score', 'lower_half_score', 'total_score', 'stars'):
            self.assertIsNone(data[field])
        self.assertEqual(data, json.loads((directory / 'challenge-result.json').read_text(encoding='utf-8')))
        self.assertEqual([row['capture_sequence'] for row in data['evidence']], [1, 2])
        for row in data['evidence']:
            raw = (directory / row['screenshot']).read_bytes()
            self.assertEqual(row['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertTrue(np.array_equal(feedback.image, cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)))
        self.assertEqual(historical.read_bytes(), b'{"completion_verified":true,"stars":3,"total_score":99999}')
        self.assertEqual(self.config.read_bytes(), config)

    def test_node_destination_is_independent_of_actual_node_and_scores(self):
        feedback = frame(NEXT, RETURN, extra=(token('节点一', (540, 186, 580, 198)),
                         token('节点二', (540, 336, 580, 348)), token('总分6621', (470, 95, 530, 111))))
        data = self.run_cli([feedback, feedback])['challenge_result']
        self.assertEqual(data['status'], 'feedback_verified')
        self.assertEqual(data['mode'], 'apocalyptic_shadow')
        self.assertEqual(data['destination_node_in_caption'], 2)
        self.assertEqual(data['visible_controls'], ['前往节点二', '返回末日幻影'])
        for field in ('node', 'node_one_score', 'node_two_score', 'total_score', 'stars', 'failure_marker_observed'):
            self.assertIsNone(data[field])
        self.assertEqual(data['settlement_status'], 'unknown')

    def test_only_destination_caption_leaves_mode_and_failure_unknown(self):
        feedback = frame(NEXT, FAILURE)
        data = self.run_cli([feedback, feedback])['challenge_result']
        self.assertEqual(data['status'], 'caption_verified')
        self.assertEqual(data['destination_node_in_caption'], 2)
        self.assertIsNone(data['mode'])
        self.assertIsNone(data['node'])
        self.assertIsNone(data['failure_marker_observed'])

    def test_occlusion_empty_and_missing_identity_break_pairing(self):
        good = frame(FICTION)
        overlay = frame(FICTION, extra=(token('AutoHSR', (25, 31, 85, 44)), token('每日任务', (41, 75, 85, 90)),
                        token('运行日志', (41, 103, 85, 116))))
        for gap in (overlay, EmptyCapture(), frame(FICTION, uid=None)):
            with self.subTest(gap=type(gap).__name__):
                data = self.run_cli([good, gap, good, good])['challenge_result']
                self.assertEqual([row['capture_sequence'] for row in data['evidence']], [3, 4])

    def test_complete_lower_confidence_conflict_blocks_publication(self):
        good = frame(FICTION)
        for conflict in (frame(FICTION, uid=OTHER), frame(FICTION, extra=[OTHER])):
            with self.subTest(conflict=conflict.tokens):
                report = self.run_cli([good, conflict, good])
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['challenge_result']['status'], 'unknown')
                self.assertFalse((Path(report['run_dir']) / 'challenge-result.json').exists())

    def test_raw_uid_veto_is_scoped_to_result_and_survives_high_ocr_threshold(self):
        settings = Settings.load(self.config)
        settings.ocr_confidence = .80
        settings.save(self.config)
        noise = [token('UID:12345', (100, 514, 160, 532), .74), token('确认', (500, 210, 540, 230), .74)]
        good = frame(FICTION, extra=noise)
        conflict = frame(FICTION, extra=[*noise, OTHER])

        def raw(scene):
            return [([(t.box[0] * GEO.width, t.box[1] * GEO.height),
                      (t.box[2] * GEO.width, t.box[3] * GEO.height)], t.text, t.score)
                    for t in scene.tokens]

        ordinary = Vision.__new__(Vision)
        ordinary.confidence = .80
        ordinary.engine = lambda *_args, **_kwargs: (raw(conflict), None)
        scene = ordinary.read(conflict.image, GEO)
        self.assertEqual(scene.tokens, good.tokens[:2])
        self.assertEqual(scene.field_reads, {})

        for last, expected in ((good, 'feedback_verified'), (conflict, 'unknown')):
            with self.subTest(expected=expected):
                frames = iter((good, last))

                def init(vision, confidence):
                    vision.confidence = confidence
                    vision.engine = lambda *_args, **_kwargs: (raw(next(frames)), None)

                with patch.object(Vision, '__init__', init):
                    report = self.run_cli([good, last], use_vision=True)
                self.assertEqual(report['challenge_result']['status'], expected)

    def test_real_rapidocr_still_verifies_a_rendered_uid_and_fixed_caption(self):
        geometry = Geometry(GEO.left, GEO.top, 1920, 1080)
        image = np.full((geometry.height, geometry.width, 3), 24, dtype=np.uint8)
        crop = cv2.imread(str(pages.ASSET_ROOT / FICTION[0]))
        x, y = round(.72 * geometry.width), round(.862 * geometry.height)
        image[y:y + crop.shape[0], x:x + crop.shape[1]] = crop
        cv2.putText(image, 'UID:123456789', (29, 1059), cv2.FONT_HERSHEY_SIMPLEX, .94,
                    (245, 245, 245), 2, cv2.LINE_AA)
        scene = Scene([], image, geometry)
        data = self.run_cli([scene, scene], use_vision=True, geometry=geometry)['challenge_result']
        self.assertEqual((data['status'], data['mode'], data['visible_controls']),
                         ('feedback_verified', 'pure_fiction', ['返回虚构叙事']))

    def test_repeated_capture_time_requires_new_pair(self):
        good = frame(FICTION)
        snapshot = Context.snapshot
        stamps = []

        def repeat_time(ctx):
            scene = snapshot(ctx)
            stamps.append(scene.captured_at)
            if len(stamps) == 2:
                scene.captured_at = stamps[0]
            return scene

        with patch.object(Context, 'snapshot', repeat_time):
            data = self.run_cli([good] * 4)['challenge_result']
        self.assertEqual([row['capture_sequence'] for row in data['evidence']], [3, 4])

    def test_unknown_and_focus_loss_do_not_publish_receipt(self):
        good = frame(FICTION)
        unknown = self.run_cli([good, EmptyCapture(), good])
        self.assertEqual(unknown['status'], 'partial')
        self.assertEqual(unknown['challenge_result']['status'], 'unknown')
        self.assertEqual(unknown['challenge_result']['evidence'], [])
        self.assertTrue((Path(unknown['run_dir']) / unknown['challenge_result']['diagnostic_screenshot']).is_file())
        lost = self.run_cli([good, FocusLost('fixture background')])
        self.assertEqual(lost['status'], 'failed')
        self.assertEqual(lost['challenge_result']['status'], 'unknown')

    def test_late_epoch_change_or_wrong_png_keeps_result_unknown(self):
        good = frame(FICTION, FAILURE)
        evidence = Context.evidence
        for fault in ('epoch', 'pixels', 'first_png'):
            with self.subTest(fault=fault):
                def corrupt(ctx, scene, name):
                    path = evidence(ctx, scene, name)
                    if name == 'challenge_result_2':
                        if fault == 'epoch':
                            ctx.runner.input_epoch += 1
                        elif fault == 'pixels':
                            path.write_bytes(cv2.imencode('.png', frame().image)[1].tobytes())
                        else:
                            first = next(path.parent.glob('*_challenge_result_1.png'))
                            first.write_bytes(first.read_bytes() + b'changed')
                    return path

                with patch.object(Context, 'evidence', corrupt):
                    report = self.run_cli([good, good])
                self.assertEqual(report['challenge_result']['status'], 'unknown')
                self.assertFalse((Path(report['run_dir']) / 'challenge-result.json').exists())

    def test_sources_stay_read_locked_during_receipt_and_report_retries(self):
        good = frame(FICTION)
        original_replace = Path.replace
        attempts = {'challenge-result.json': 0, 'report.json': 0}
        originals = {}

        def sharing(source, destination):
            if destination.name in attempts:
                paths = sorted(destination.parent.glob('*_challenge_result_*.png'))
                self.assertEqual(len(paths), 2)
                if destination.name == 'report.json':
                    paths.append(destination.with_name('challenge-result.json'))
                for path in paths:
                    raw = path.read_bytes()
                    self.assertEqual(raw, originals.setdefault(path, raw))
                    with self.assertRaises(PermissionError):
                        path.write_bytes(raw + b'changed')
                attempts[destination.name] += 1
                if attempts[destination.name] == 1:
                    raise PermissionError('simulated sharing lock')
            return original_replace(source, destination)

        with patch.object(Path, 'replace', sharing):
            report = self.run_cli([good, good])
        self.assertEqual(attempts, {'challenge-result.json': 2, 'report.json': 2})
        self.assertEqual(report['challenge_result']['status'], 'feedback_verified')
        for path, raw in originals.items():
            self.assertEqual(path.read_bytes(), raw)
            path.write_bytes(raw)  # The read handles have been released.

    def test_report_downgrades_if_png_or_receipt_changed_before_final_lock(self):
        good = frame(FICTION)
        original_save = Runner._save_run_report
        for changed in ('png', 'receipt'):
            with self.subTest(changed=changed):
                modified = {}

                def save(runner, directory, *args, **kwargs):
                    path = directory / 'challenge-result.json'
                    if changed == 'png':
                        path = next(directory.glob('*_challenge_result_1.png'))
                    modified[path] = path.read_bytes() + b'changed'
                    path.write_bytes(modified[path])
                    return original_save(runner, directory, *args, **kwargs)

                with patch.object(Runner, '_save_run_report', save):
                    report = self.run_cli([good, good])
                self.assertIn('报告发布未核实', report['error'])
                self.assertEqual(report['challenge_result']['status'], 'unknown')
                self.assertIsNone(report['challenge_result']['mode'])
                self.assertEqual(report['challenge_result']['evidence'], [])
                self.assertEqual(report['challenge_result']['visible_controls'], [])
                self.assertTrue(modified)
                for path, raw in modified.items():
                    self.assertEqual(path.read_bytes(), raw)

    def test_receipt_and_report_check_foreground_after_last_png_read(self):
        good = frame(FICTION)
        read = ResultReader._read_png
        for lose_at in (4, 6):
            with self.subTest(lose_at=lose_at):
                reads = count(1)

                def lose(reader, path):
                    raw = read(reader, path)
                    if next(reads) == lose_at:
                        reader.c.window.foreground = False
                    return raw

                with patch.object(ResultReader, '_read_png', lose):
                    report = self.run_cli([good, good])
                self.assertEqual(report['challenge_result']['status'], 'unknown')
                self.assertEqual((Path(report['run_dir']) / 'challenge-result.json').exists(), lose_at == 6)

    def test_report_retry_keeps_stop_and_pause_observable(self):
        good = frame(FICTION)
        save_report = ResultReader.save_report
        replace_path = Path.replace
        for interrupt, status in ((Runner.stop, 'stopped'), (Runner.toggle_pause, 'partial')):
            with self.subTest(interrupt=interrupt.__name__):
                attempted = False

                def save(reader, temporary, write_report):
                    def share(source, destination):
                        nonlocal attempted
                        if destination.name == 'report.json' and not attempted:
                            attempted = True
                            runner = reader.c.runner
                            self.assertFalse(runner._monitor_end.is_set())
                            interrupt(runner)
                            raise PermissionError('simulated sharing lock')
                        return replace_path(source, destination)

                    with patch.object(Path, 'replace', share):
                        return save_report(reader, temporary, write_report)

                with patch.object(ResultReader, 'save_report', save):
                    report = self.run_cli([good, good])
                self.assertTrue(attempted)
                self.assertEqual(report['status'], status)
                self.assertEqual(report['challenge_result']['status'], 'unknown')
                receipt = Path(report['run_dir']) / 'challenge-result.json'
                self.assertEqual(json.loads(receipt.read_bytes())['status'], 'feedback_verified')

    def test_cli_rejects_input_flags_before_config_load(self):
        for flag in ('--challenge-prepare', '--preview-build-target', '--currency-wars-configure-overclock',
                     '--currency-wars-standard', '--differential-universe', '--du-until-points',
                     '--new-battle-run', '--notify', '--resume-active-currency', '--admin-task'):
            with self.subTest(flag=flag), redirect_stderr(io.StringIO()), patch.object(Settings, 'load') as load:
                with self.assertRaises(SystemExit) as exit_code:
                    main([FLAG, flag])
                self.assertEqual(exit_code.exception.code, 2)
                load.assert_not_called()

    def test_result_operation_cannot_use_generic_or_preparation_input(self):
        ctx = SimpleNamespace(report=RunReport(operation='challenge_result'))
        with self.assertRaises(AutomationError):
            Context._require_gameplay_input(ctx)
        with self.assertRaises(AutomationError):
            Context.challenge_prepare_input(ctx, None, None)
