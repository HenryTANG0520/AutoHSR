"""Environment effect grammar, semantic ranking and observed selection feedback."""
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from autohsr.currency_wars_environment import (CENTERS, ENVIRONMENT_CONFLICTS, parse_environment_effect,
    standard_environment_options, standard_environment_choice, standard_environment_confirm)
from autohsr.currency_wars_standard_flow import next_action, transition_ready
from autohsr.models import AutomationError, Scene, Token
from autohsr.ocr_isolation import _field_reads, _ocr_job, _tokens
from autohsr.vision import Vision


def environment(selected=(), enabled=False):
    fixture = json.loads((Path(__file__).parent/'fixtures/currency_wars_standard_environment.json').read_text(encoding='utf-8'))
    image = np.zeros((1080,1920,3), dtype=np.uint8)
    for slot in selected:
        cx = CENTERS[slot]
        image[round(.20*1080):round(.79*1080),round((cx-.123)*1920):round((cx-.121)*1920)] = 240
    if enabled:
        image[round(.895*1080):round(.925*1080),round(.50*1920):round(.62*1920)] = 230
    return Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in fixture['tokens']], image)


def change_text(scene, original, replacement):
    token = next(t for t in scene.tokens if original in t.text)
    scene.tokens[scene.tokens.index(token)] = replace(token, text=token.text.replace(original, replacement))
    return scene


def read_ocr(scene, isolated):
    height, width = scene.image.shape[:2]
    results = []
    for token in scene.tokens:
        x1, y1, x2, y2 = token.box
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        results.append(([(x * width, y * height) for x, y in corners], token.text, token.score))

    def configure(reader, confidence):
        reader.confidence = confidence
        reader.engine = Mock(return_value=(results, None))

    if not isolated:
        reader = Vision.__new__(Vision)
        configure(reader, .65)
        return reader.read(scene.image, scene.geometry)
    with tempfile.TemporaryDirectory() as folder:
        source, output = Path(folder) / 'frame.npy', Path(folder) / 'ocr.json'
        np.save(source, scene.image, allow_pickle=False)
        with patch.object(Vision, '__init__', configure):
            _ocr_job(str(source), str(output), .65)
        result = json.loads(output.read_text(encoding='utf-8'))
        return Scene(_tokens(result), scene.image, scene.geometry, field_reads=_field_reads(result))


class StandardEnvironmentTests(unittest.TestCase):
    def test_real_three_effects_separate_price_star_count_and_refreshes(self):
        choices = standard_environment_options(environment())
        self.assertEqual(len(choices),3)
        self.assertEqual([choice.kind for choice in choices],
                         ['fixed_investment_tiers','growing_unit','random_environment_gold'])
        self.assertEqual(dict(choices[0].parameters), dict(extra_refreshes=2))
        self.assertEqual(dict(choices[1].parameters), dict(count=1,star=2,tier=2))
        self.assertEqual(dict(choices[2].parameters), dict(gold=6))
        self.assertEqual(standard_environment_choice(environment()).name.text,'战力飙升')

    def test_number_variations_are_parsed_as_fields_without_repeated_clicks(self):
        for count in (1,2,3):
            for star in (1,2,3):
                effect=f'获得{count}个随机{star}星4费角色，进入新节点时，这位角色永久获得随机属性加成。'
                kind, params, score, reason = parse_environment_effect(effect)
                self.assertEqual(dict(params),dict(count=count,star=star,tier=4))
        kind, params, score, reason = parse_environment_effect('本局在固定节点进行投资策略选择时左、中、右的选项分别为银金彩品质，并且投资策略刷新次数+3。')
        self.assertEqual(dict(params),dict(extra_refreshes=3))

    def test_missing_or_conflicting_effect_text_never_becomes_known(self):
        for effect in ('获得1个随机2星2费角色', '获得1个随机5星2费角色，进入新节点时这位角色永久获得随机属性加成',
                       '进入到一个随机投资环境中，开局额外获得6金币，消耗100金币',
                       '所有首领节点前都加入一个额外补给阶段并扣除生命'):
            self.assertIsNone(parse_environment_effect(effect)[0])
        state = environment()
        state.tokens = [t for t in state.tokens if not .38<=t.center[1]<=.47]
        with self.assertRaises(AutomationError):
            standard_environment_choice(state)
        state = environment()
        state.tokens.append(Token('但每节点扣除生命',.99,(.43,.60,.57,.63)))
        self.assertIsNone(standard_environment_options(state)[1].kind)

    def test_card_reordering_does_not_change_semantic_preference(self):
        state = environment()
        shifted=[]
        for token in state.tokens:
            if .34 <= token.center[1] <= .47:
                slot=min(range(3),key=lambda i:abs(token.center[0]-CENTERS[i]))
                offset=CENTERS[(slot+1)%3]-CENTERS[slot]
                token=replace(token,box=(token.box[0]+offset,token.box[1],token.box[2]+offset,token.box[3]))
            shifted.append(token)
        state.tokens=shifted
        choice=standard_environment_choice(state)
        self.assertEqual(choice.name.text,'战力飙升')
        self.assertEqual(choice.slot,2)

    def test_incomplete_or_ambiguous_body_cannot_confirm_selected_card(self):
        prior_selection = next_action(environment())
        for case in ('detached_row', 'detached_body', 'cross_column', 'overlaid_row', 'weak_tail', 'crossing_tail'):
            with self.subTest(case=case):
                state = environment((1,), True)
                first, last = [t for t in state.tokens if t.within((.385,.38,.615,.47))]
                if case == 'detached_body':
                    for token in (first, last):
                        x1, y1, x2, y2 = token.box
                        state.tokens[state.tokens.index(token)] = replace(token, box=(x1,y1+.18,x2,y2+.18))
                elif case == 'weak_tail':
                    state.tokens.append(Token('开局时扣除6金币',.50,(.394,.440,.557,.464)))
                elif case == 'crossing_tail':
                    state.tokens.append(Token('但每节点扣除生命',.92,(.601,.444,.654,.465)))
                else:
                    x1, y1, x2, y2 = last.box
                    box = {
                        'detached_row': (x1,.642,x2,.669),
                        'cross_column': (.380,y1,x2,y2),
                        'overlaid_row': (x1,.394,x2,.433),
                    }[case]
                    state.tokens[state.tokens.index(last)] = replace(last, box=box)
                self.assertIsNone(standard_environment_options(state)[1].kind)
                self.assertFalse(transition_ready(prior_selection,state))
                self.assertEqual(next_action(state).intent,'select_standard_environment_0')

    def test_split_body_uses_same_column_order_with_one_two_or_three_cards(self):
        prior_selection = next_action(environment())
        for missing in ((), (0,), (0,2)):
            with self.subTest(missing=missing):
                state = environment((1,), True)
                last = next(t for t in state.tokens if '永久获得' in t.text)
                state.tokens.remove(last)
                state.tokens += [
                    Token('永久获得随机属性加成。', .99, (.465,.417,.584,.442)),
                    Token('时，这位角色', .99, (.395,.412,.466,.437)),
                    Token('栏外提示', .50, (.635,.448,.649,.467)),
                ]
                state.tokens = [t for t in state.tokens if not any(
                    t.within((CENTERS[i]-.115,.34,CENTERS[i]+.115,.79)) for i in missing)]
                self.assertEqual(len(standard_environment_options(state)), 3-len(missing))
                self.assertTrue(transition_ready(prior_selection, state))
                self.assertEqual(next_action(state).intent, 'confirm_standard_environment_1')

    def test_far_apart_fragments_of_one_ocr_line_are_not_joined(self):
        state = environment((1,), True)
        last = next(t for t in state.tokens if '永久获得' in t.text)
        state.tokens.remove(last)
        state.tokens += [
            Token('时，这位角色', .99, (.395,.413,.439,.439)),
            Token('永久获得随机属性加成。', .99, (.491,.417,.584,.442)),
        ]
        self.assertIsNone(standard_environment_options(state)[1].kind)
        self.assertEqual(next_action(state).intent,'select_standard_environment_0')

    def test_confirmation_needs_single_selected_border_and_enabled_button(self):
        for slots, enabled in (((),False),((1,),False),((0,),True),((0,1),True)):
            state = environment(slots,enabled)
            with self.assertRaises(AutomationError):
                standard_environment_confirm(state, standard_environment_choice(state))
        state = environment((1,),True)
        self.assertEqual(standard_environment_confirm(state,standard_environment_choice(state)).text,'确认')

    def test_click_and_confirm_are_separate_feedback_steps_without_rerolling(self):
        select=next_action(environment())
        self.assertEqual(select.intent,'select_standard_environment_1')
        self.assertFalse(transition_ready(select,environment()))
        self.assertTrue(transition_ready(select,environment((1,),True)))
        confirm=next_action(environment((1,),True))
        self.assertEqual(confirm.intent,'confirm_standard_environment_1')
        self.assertEqual(confirm.target.text,'确认')
        self.assertEqual(dict(confirm.details[3]),dict(count=1,star=2,tier=2))
        state=environment()
        state.image=None
        with self.assertRaises(AutomationError):
            next_action(state)

    def test_selection_feedback_rejects_different_known_cards_in_same_slot(self):
        select = next_action(environment())
        for original, replacement in (('随机2星2费', '随机3星2费'), ('1个随机', '2个随机'),
                                      ('2星2费', '2星3费'), ('战力飙升', '另一张卡')):
            with self.subTest(replacement=replacement):
                selected = change_text(environment((1,), True), original, replacement)
                self.assertEqual(next_action(selected).intent, 'confirm_standard_environment_1')
                self.assertFalse(transition_ready(select, selected))

    def test_weak_engine_text_is_only_negative_evidence_for_verified_cards(self):
        for isolated in (False, True):
            for case in ('inside', 'crossing', 'outside', 'unverified_page', 'weak_effect'):
                with self.subTest(isolated=isolated, case=case):
                    raw = environment((1,), True)
                    if case == 'weak_effect':
                        last = next(t for t in raw.tokens if '永久获得' in t.text)
                        raw.tokens[raw.tokens.index(last)] = replace(last, score=.58)
                    else:
                        box = {'crossing': (.605, .442, .655, .464), 'outside': (.635, .442, .649, .464)}
                        raw.tokens.append(Token('但开局时扣除6金币', .58, box.get(case, (.397, .442, .568, .464))))
                    if case == 'unverified_page':
                        raw.tokens = [replace(t, score=.58) if t.text == '投资环境' else t for t in raw.tokens]
                    scene = read_ocr(raw, isolated)
                    self.assertTrue(all(t.score >= .65 for t in scene.tokens))
                    blocked = case in ('inside', 'crossing', 'weak_effect')
                    self.assertEqual(ENVIRONMENT_CONFLICTS in scene.field_reads, blocked)
                    if blocked:
                        witness, = scene.field_reads[ENVIRONMENT_CONFLICTS]
                        self.assertEqual(witness.score, .58)
                        self.assertIsNone(standard_environment_options(scene, .55)[1].kind)
                        self.assertEqual(next_action(scene).intent, 'select_standard_environment_0')
                    elif case == 'outside':
                        self.assertEqual(next_action(scene).intent, 'confirm_standard_environment_1')
                    else:
                        with self.assertRaises(AutomationError):
                            standard_environment_options(scene)


if __name__ == '__main__':
    unittest.main()
