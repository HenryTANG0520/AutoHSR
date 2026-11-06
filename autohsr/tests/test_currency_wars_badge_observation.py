import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars import CurrencyWarsWorkflow, observe
from autohsr.currency_wars_badge_observation import read_bundle_observation, supplement_bundle_observation
from autohsr.currency_wars_investment_policy import options
from autohsr.models import AutomationError, Scene, Token


def token(text, x, y, width=.07, score=.98):
    return Token(text, score, (x-width/2, y-.01, x+width/2, y+.01))


def energy_lines(y=.464, first='获得1个【能量星徽】，和2个', second='【星期日】，以及3个【胜利之'):
    return (Token(first, .96, (.418, y-.010, .578, y+.010)),
            Token(second, .94, (.418, y+.015, .580, y+.036)),
            Token('旗】。', .96, (.418, y+.043, .454, y+.061)))


def frame(*, inset=True, effect=None):
    columns = (.257, .5, .744) if inset else (.24, .5, .76)
    title, counter, button = (.425, .742, .853) if inset else (.455, .792, .910)
    words = [token('请选择投资策略', .5, .087, .105), token('攻略', .796, .050, .028),
             token('确认', .502, button, .04)]
    if inset:
        words.append(token('返回备战界面', .905, .05, .075))
    else:
        words.append(token('图例', .113, .092, .03))
    for name, x in zip(('着眼当下', '能量星徽套组', '保守派'), columns):
        words.append(token(name, x, title))
        words.append(token('刷新次数1', x+.009, counter, .061))
    words.extend(energy_lines(y=.464 if inset else .496) if effect is None else effect)
    return Scene(words, np.zeros((480, 852, 3), np.uint8), captured_at=time.monotonic())


def mark(scene, slot, *, inset=True, only_left=False, bright_button=True):
    centers = (.257, .5, .744) if inset else (.24, .5, .76)
    x = centers[slot]
    h, w = scene.image.shape[:2]
    for side in (-1,) if only_left else (-1, 1):
        at = round((x+side*.10)*w)
        scene.image[round(.536*h):round(.68*h), at:at+3] = 245
    y = .853 if inset else .910
    if bright_button:
        scene.image[round((y-.020)*h):round((y+.020)*h), round(.438*w):round(.569*w)] = 245


class BadgeBundleObservationTests(unittest.TestCase):
    def test_three_counts_and_visible_selection_are_independent(self):
        for inset in (False, True):
            with self.subTest(inset=inset):
                scene = frame(inset=inset)
                self.assertEqual(observe(scene, .65).page_kind, 'unknown')
                with self.assertRaises(AutomationError):
                    options(scene)
                expected = dict(slot=1, title='能量星徽套组', badge='能量星徽', badge_count=1,
                                other_rewards=(('星期日', 2), ('胜利之旗', 3)), selection_state='unselected',
                                status='delivery_unverified', delivery_verified=False)
                self.assertEqual(read_bundle_observation(scene), [expected])
                mark(scene, 0, inset=inset)
                self.assertEqual(read_bundle_observation(scene)[0]['selection_state'], 'other_selected')
                scene.image[:] = 0
                mark(scene, 1, inset=inset)
                self.assertEqual(read_bundle_observation(scene)[0]['selection_state'], 'selected')

    def test_one_edge_dim_confirmation_duplicate_edges_or_flash_leave_selection_unknown(self):
        for variant in ('one_edge', 'disabled_button', 'two_cards', 'flash'):
            with self.subTest(variant=variant):
                scene = frame()
                mark(scene, 1, only_left=variant == 'one_edge', bright_button=variant != 'disabled_button')
                if variant == 'two_cards':
                    mark(scene, 0)
                elif variant == 'flash':
                    scene.image[120:180, 392:460] = 255
                self.assertEqual(read_bundle_observation(scene)[0]['selection_state'], 'unverified')

    def test_page_requires_scoped_guide_return_or_legend_and_one_counter_per_column(self):
        for variant in ('only_title', 'wrong_guide', 'no_return', 'duplicate_counter', 'authentication', 'wrong_page'):
            with self.subTest(variant=variant):
                scene = frame()
                if variant == 'only_title':
                    scene.tokens = [t for t in scene.tokens if t.text == '请选择投资策略']
                elif variant == 'wrong_guide':
                    scene.tokens = [replace(t, box=(.091,.068,.14,.094)) if t.text == '攻略' else t for t in scene.tokens]
                elif variant == 'no_return':
                    scene.tokens = [t for t in scene.tokens if t.text != '返回备战界面']
                elif variant == 'duplicate_counter':
                    scene.tokens.append(token('刷新次数0', .509, .742))
                elif variant == 'authentication':
                    scene.tokens.append(token('账号验证', .5, .303))
                else:
                    scene.tokens = [replace(t, text='请选择1个') if t.text == '请选择投资策略' else t for t in scene.tokens]
                reader = Mock(confidence=.65)
                self.assertIs(supplement_bundle_observation(scene, reader), scene)
                self.assertEqual(reader.mock_calls, [])
                self.assertEqual(read_bundle_observation(scene), [])

    def test_corroborated_local_reads_preserve_full_frame_and_reject_conflict(self):
        missing = energy_lines(first='获得1个【能量星微】，和2个')
        raw = frame(effect=missing)
        reader = Mock(confidence=.65)
        reader._read_field.side_effect = list(energy_lines()) * 2
        supplemented = supplement_bundle_observation(raw, reader)
        self.assertEqual(raw.field_reads, {})
        self.assertEqual(raw.tokens, supplemented.tokens)
        self.assertEqual(read_bundle_observation(raw), [])
        self.assertEqual(read_bundle_observation(supplemented)[0]['badge'], '能量星徽')
        self.assertEqual(reader._read_field.call_count, 6)
        variants = supplemented.field_reads
        one = replace(supplemented, field_reads={'cw_badge.s1.0': variants['cw_badge.s1.0']})
        self.assertEqual(read_bundle_observation(one), [])
        for conflict in (
            energy_lines(first='获得4个【能量星微】，和2个'),
            energy_lines(first='获得1个【狼狩星徽】，和2个'),
            energy_lines(second='【风堇】，以及3个【胜利之'),
            (*missing, token('同时额外损失生命', .49, .632, .12, .60)),
        ):
            with self.subTest(conflict=conflict):
                scene = frame(effect=conflict)
                scene.field_reads = variants
                self.assertEqual(read_bundle_observation(scene), [])

    def test_same_slot_and_complete_name_are_required(self):
        missing = energy_lines(first='获得1个【能量星微】，和2个')
        for variant in ('wrong_slot', 'wrong_y', 'missing_line', 'wrong_title', 'unlisted_bundle'):
            with self.subTest(variant=variant):
                scene = frame(effect=missing)
                parts = energy_lines()
                if variant == 'wrong_slot':
                    parts = tuple(replace(t, box=(t.box[0]-.245,t.box[1],t.box[2]-.245,t.box[3])) for t in parts)
                elif variant == 'wrong_y':
                    parts = tuple(replace(t, box=(t.box[0],t.box[1]-.20,t.box[2],t.box[3]-.20)) for t in parts)
                elif variant == 'missing_line':
                    parts = parts[:-1]
                elif variant in ('wrong_title', 'unlisted_bundle'):
                    wrong = '能量星微套组' if variant == 'wrong_title' else '狼狩星徽套组'
                    scene.tokens = [replace(t, text=wrong) if t.text == '能量星徽套组' else t for t in scene.tokens]
                scene.field_reads = {'cw_badge.s1.0': parts, 'cw_badge.s1.1': parts}
                self.assertEqual(read_bundle_observation(scene), [])

    def test_read_only_inspection_projects_declaration_without_an_input(self):
        scene = frame()
        mark(scene, 1)
        window = Mock()
        context = Context(Runner(Settings(), operation='currency_wars'), window, Mock())
        context.last_scene = scene
        context.snapshot = Mock(return_value=scene)
        context.evidence = Mock(return_value=Path('offline-bundle.png'))
        with patch('autohsr.currency_wars_replay.save_sample', return_value=Path('offline-bundle.sample.json')):
            CurrencyWarsWorkflow(context).inspect()
        result = context.report.currency_wars
        self.assertEqual(result['page_kind'], 'investment_selection')
        self.assertEqual(result['investment_badge_declarations'], read_bundle_observation(scene))
        self.assertEqual(result['decision'], 'stop_without_input')
        self.assertFalse(result['completion_verified'])
        self.assertEqual(window.mock_calls, [])
