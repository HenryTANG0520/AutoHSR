"""Exercise the original three-card switches through the fake-window workflow."""
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr.du_station_preview import card_for_label, station_cards, three_card_station_row
from autohsr.models import AutomationError, InputInterrupted, Scene, Token
from autohsr.tests import test_du_runtime
from autohsr.tests.test_du_team import fixture
from autohsr.windows import Geometry


class ReachedStation(Exception):
    pass


class EmptyBeaconStationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / 'fixtures/du_runtime/station_empty_beacon_replay'
        data = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        raster = cv2.imdecode(np.fromfile(path.with_suffix('.png'), np.uint8), cv2.IMREAD_COLOR)
        cls.episodes = data['episodes']
        cls.scenes = {
            row['index']: Scene([Token(t['text'], t['score'], tuple(t['box'])) for t in row['tokens']],
                                raster[i*540:(i+1)*540], Geometry(0, 0, 960, 540))
            for i, row in enumerate(data['frames'])
        }

    def frame(self, index):
        return replace(self.scenes[index])

    def test_real_switches_confirm_once_and_reach_the_recorded_room(self):
        for episode, target, column, receiver, title in (
                ('elite', '精英', 0, '_field_combat', '（2/13）第一位面-精英'),
                ('forge', '铸造', 2, '_field_anomaly', '（11/13）第三位面-铸造')):
            with self.subTest(episode=episode):
                frames = [self.frame(i) for i in self.episodes[episode]]
                old_cards = station_cards(frames[3])
                token, = [t for t in frames[3].tokens if t.text == target
                          and card_for_label(frames[3], old_cards, t) == old_cards[column]]
                with test_du_runtime.DuRuntimeTests().captured_du_flow(frames) as (flow, window):
                    with patch.object(flow, receiver, side_effect=ReachedStation) as arrival:
                        start = flow.ctx.snapshot()
                        with self.assertRaises(ReachedStation):
                            flow._progress_run(start, 'station_choice')
                    room, = arrival.call_args.args
                    self.assertTrue(room.has(title, exact=True))
                    self.assertEqual(arrival.call_args.kwargs, {'fresh_entry': True})
                    self.assertEqual([call.args[:2] for call in window.click.call_args_list],
                                     [start.find('战斗', exact=True).center, token.center,
                                      frames[6].find('确定', exact=True).center])
                    actions = [row for row in flow.report['actions'] if 'intent' in row]
                    self.assertEqual([(row['intent'], row['status']) for row in actions],
                                     [('station_select', 'sent'), ('station_select', 'sent'),
                                      ('station_confirm', 'sent')])
                    self.assertEqual(actions[-1]['after_page'], 'unknown')
                    self.assertEqual([row['page_kind'] for row in flow.report['page_history'][-3:]],
                                     ['unknown', 'field_combat' if episode == 'elite' else 'field_forge',
                                      'field_combat' if episode == 'elite' else 'field_forge'])

    def rejected_switch(self, feedback, *, column=2, mode='periodic'):
        before = self.frame(450)
        cards = station_cards(before)
        target, = [t for t in before.tokens if t.text == '铸造'
                   and card_for_label(before, cards, t) == cards[column]]
        frames = [before, self.frame(451), *feedback]
        frames.extend(self.frame(454) for _ in range(8-len(frames)))
        with test_du_runtime.DuRuntimeTests().captured_du_flow(frames) as (flow, window):
            flow.settings.differential_universe_mode = mode
            current = flow.ctx.snapshot()
            with self.assertRaisesRegex(AutomationError, '未核实替代站点选中及新效果'):
                flow._select_station_alternative(current, target)
            self.assertEqual([call.args[:2] for call in window.click.call_args_list], [target.center])

    def test_right_hand_forge_does_not_satisfy_a_middle_forge_selection(self):
        self.rejected_switch([self.frame(452), self.frame(453)], column=1)

    def test_normal_mode_keeps_the_previous_effect_gate(self):
        self.rejected_switch([self.frame(452), self.frame(453)], mode='normal')

    def test_an_incomplete_four_card_row_cannot_use_the_three_card_layout(self):
        cards = station_cards(fixture('station_explosion_beacon'))
        self.assertEqual(len(cards), 4)
        for column in range(len(cards)):
            with self.subTest(missing_column=column):
                self.assertFalse(three_card_station_row(cards[:column]+cards[column+1:]))

    def test_loading_frame_breaks_the_two_current_previews(self):
        self.rejected_switch([self.frame(452), self.frame(454), self.frame(453)])

    def test_empty_beacon_panel_alone_does_not_replace_the_old_description(self):
        source = self.scenes[450]
        body = (.10, .14, .38, .33)
        old_lines = [t for t in source.tokens if t.within(body)]
        pages = []
        for index in (452, 453):
            page = self.frame(index)
            image = page.image.copy()
            image[76:178, 96:365] = source.image[76:178, 96:365]
            tokens = [t for t in page.tokens if not t.within(body)] + old_lines
            pages.append(replace(page, tokens=tokens, image=image))
        self.rejected_switch(pages)

    def test_glyphs_right_panel_and_available_confirmation_are_each_required(self):
        for reason, source, bounds in (
                ('dimmed button', 447, (458, 514, 465, 695)),
                ('unread glyphs', 454, (117, 144, 574, 645)),
                ('remaining danger fragment', 450, (91, 112, 402, 521)),
        ):
            with self.subTest(reason=reason):
                top, bottom, left, right = bounds
                pages = []
                for index in (452, 453):
                    page = self.frame(index)
                    image = page.image.copy()
                    image[top:bottom, left:right] = self.scenes[source].image[top:bottom, left:right]
                    pages.append(replace(page, image=image))
                self.rejected_switch(pages)

    def test_enabled_button_must_be_the_target_the_workflow_would_click(self):
        other = Token('确认', .99, (.76, .878, .80, .913))
        pages = [replace(self.frame(index), tokens=[*self.scenes[index].tokens, other]) for index in (452, 453)]
        self.rejected_switch(pages)

    def test_confirmation_revalidates_after_saving_the_current_image(self):
        for fault in ('stale', 'epoch'):
            with self.subTest(fault=fault):
                frames = [self.frame(index) for index in self.episodes['forge']]
                with test_du_runtime.DuRuntimeTests().captured_du_flow(frames) as (flow, window):
                    sent = []

                    def evidence(_scene, label):
                        if label == 'du_before_确定':
                            if fault == 'stale':
                                flow.ctx.sleep(9)
                            else:
                                flow.ctx.runner.input_epoch += 1
                        return 'fixture.png'

                    def send(x, y, _geometry, *, before_send=None):
                        if before_send is not None:
                            before_send()
                        sent.append((x, y))

                    flow.ctx.evidence.side_effect = evidence
                    window.click.side_effect = send
                    start = flow.ctx.snapshot()
                    with self.assertRaisesRegex(AutomationError, '替代站点确认中断') as raised:
                        flow._progress_run(start, 'station_choice')
                    self.assertIsInstance(raised.exception.__cause__, InputInterrupted)
                    self.assertIn('选站确认画面已改变或过期', str(raised.exception.__cause__))
                    self.assertEqual(len(sent), 2)
                    self.assertEqual(flow.report['actions'][-1]['status'], 'not_sent')
