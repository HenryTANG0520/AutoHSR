"""Environment effect grammar, semantic ranking and observed selection feedback."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from autohsr.currency_wars_environment import (CENTERS, parse_environment_effect,
    standard_environment_options, standard_environment_choice, standard_environment_confirm)
from autohsr.currency_wars_standard_flow import next_action, transition_ready
from autohsr.models import AutomationError, Scene, Token


def environment(selected=(), enabled=False):
    fixture = json.loads((Path(__file__).parent/'fixtures/currency_wars_standard_environment.json').read_text(encoding='utf-8'))
    image = np.zeros((1080,1920,3), dtype=np.uint8)
    for slot in selected:
        cx = CENTERS[slot]
        image[round(.20*1080):round(.79*1080),round((cx-.123)*1920):round((cx-.121)*1920)] = 240
    if enabled:
        image[round(.895*1080):round(.925*1080),round(.50*1920):round(.62*1920)] = 230
    return Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in fixture['tokens']], image)


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


if __name__ == '__main__':
    unittest.main()
