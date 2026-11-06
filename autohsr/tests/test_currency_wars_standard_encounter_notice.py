"""Observed reward notice is independent of combat, points and wallet."""
from dataclasses import replace
import unittest

import cv2
import numpy as np

from autohsr.currency_wars_encounter_notice import (
    GREEN_FIELD, QUANTITY_FIELD, TITLE, TITLE_FIELD, _GREEN, _GREEN_NUMBER, _ICON,
    _QUANTITY, _TITLE, read_green, read_notice,
)
from autohsr.currency_wars_standard_encounter import CONFIRM, SELECT
from autohsr.currency_wars_standard_encounter_battle import START
from autohsr.currency_wars_standard_encounter_notice import RECORD
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.models import AutomationError, EmptyCapture, Stopped, Token
from autohsr.tests import test_currency_wars_standard_encounter as fixture
from autohsr.tests import test_currency_wars_standard_encounter_battle as battle_fixture
from autohsr.tests.test_currency_wars_standard_node import current
from autohsr.tests.test_currency_wars_standard_progress import loss_page


NODE, PREVIOUS, NEXT = '1-7', '1-6', '1-8'
INPUTS = [fixture.CONTINUE, SELECT, CONFIRM, START, fixture.CONTINUE]


def put(scene, region, patch):
    height, width = scene.image.shape[:2]
    x1, y1, x2, y2 = (round(value * size) for value, size in zip(region, (width, height, width, height)))
    scene.image[y1:y2, x1:x2] = cv2.resize(patch, (x2-x1, y2-y1), interpolation=cv2.INTER_NEAREST)


def next_board(*, node=NEXT, green=None, notice=False, title=TITLE, icon=True):
    scene = fixture.preparation(node, known_type=True)
    if green is not None:
        chip = np.zeros((30, 62, 3), np.uint8)
        cv2.rectangle(chip, (4, 4), (47, 21), (120, 225, 135), -1)
        cv2.circle(chip, (17, 13), 5, (22, 172, 235), -1)
        put(scene, _GREEN, chip)
        scene.field_reads[GREEN_FIELD] = (Token(str(green), .99, _GREEN_NUMBER),)
    if notice:
        tile = np.zeros((30, 33, 3), np.uint8)
        outline = np.array(((3, 11), (7, 4), (14, 3), (23, 5), (28, 10), (27, 19), (23, 25), (12, 26), (4, 20)))
        if icon:
            cv2.fillPoly(tile, [outline], (22, 172, 235))
        put(scene, _ICON, tile)
        scene.field_reads[TITLE_FIELD] = tuple(Token(title, .98, roi) for roi in _TITLE)
        scene.field_reads[QUANTITY_FIELD] = (Token('2', .99, _QUANTITY),)
    return scene


def failed_node():
    scene = loss_page(NODE, 76)
    scene.tokens = [replace(token, text=NODE+'遭遇') if token.text == NODE+'战斗' else token
                    for token in scene.tokens]
    return scene


class StandardEncounterNoticeTests(unittest.TestCase):
    def setUp(self):
        self.replay = fixture.StandardEncounterTests()
        self.addCleanup(self.replay.doCleanups)

    def run_reward(self, after, *, failure=None, win=False):
        result = [battle_fixture.result()] if win else [failed_node(), failed_node()]
        scenes = [current('node_result', PREVIOUS), fixture.modal(), fixture.modal(),
                  fixture.modal(selected=1), fixture.modal(selected=1), battle_fixture.ready(),
                  battle_fixture.ready(), current('battle', NODE), current('battle', NODE), *result, *after]
        return self.replay.run_path(PREVIOUS, scenes, battle_node=NODE, stop_at_arrival=False,
                                    observe_reward=True, native_failure=failure)

    def assert_existing_inputs(self, outcome):
        self.assertEqual([intent for intent, _ in outcome.calls], INPUTS, str(outcome.error))

    def test_only_the_complete_notice_and_ordered_green_change_are_recorded(self):
        for win in (False, True):
            with self.subTest(win=win):
                frames = [next_board(green=1), next_board(green=7), next_board(green=7, notice=True),
                          next_board(green=2), next_board(green=2)]
                outcome = self.run_reward(frames, win=win)
                self.assert_existing_inputs(outcome)
                self.assertIsInstance(outcome.error, Stopped)
                action = outcome.data['actions'][-1]
                receipt = action[RECORD]
                self.assertEqual(receipt['status'], 'reward_notice_observed')
                self.assertEqual((receipt['node'], receipt['next_node']), (NODE, NEXT))
                self.assertEqual(receipt['notice']['quantity'], 2)
                self.assertEqual(receipt['notice']['icon'], 'gold')
                self.assertEqual(receipt['hud_green_before']['quantity'], 7)
                self.assertEqual(receipt['hud_green_after']['quantity'], 2)
                self.assertIsNone(receipt['wallet_change'])
                self.assertEqual(receipt['result_kind'], 'node_result' if win else 'node_loss')
                self.assertEqual(outcome.data['node_history'][-1]['node_verified'], win)
                self.assertEqual(action['feedback'], dict(page_kind='preparation', node=NEXT))
                self.assertEqual(ledger_status(outcome.data['actions']), 'clear')
                self.assertNotIn('reward_verified', action)
                self.assertFalse(outcome.data['completion_verified'])

    def test_green_without_exact_title_icon_and_next_node_never_binds(self):
        wrong_title = next_board(green=7, notice=True, title='遇节点奖励')
        no_icon = next_board(green=7, notice=True, icon=False)
        wrong_node = next_board(node='1-9', green=7, notice=True)
        self.assertIsNone(read_notice(wrong_title, .65))
        self.assertIsNone(read_notice(no_icon, .65))
        self.assertEqual(read_green(next_board(green=1), .65), 1)
        self.assertEqual(read_green(next_board(green=7), .65), 7)
        self.assertEqual(read_notice(wrong_node, .65), 2)
        frames = [next_board(green=1), next_board(green=7), wrong_title, no_icon, wrong_node,
                  next_board(green=2), *[next_board()] * 23]
        outcome = self.run_reward(frames)
        self.assert_existing_inputs(outcome)
        self.assertIsInstance(outcome.error, Stopped)
        self.assertNotIn(RECORD, outcome.data['actions'][-1])
        self.assertEqual(outcome.data['node_history'][-1]['status'], 'advanced')

    def test_notice_alone_remains_independent_after_old_green_or_identity_gap(self):
        wrong_identity = next_board(green=2)
        wrong_identity.tokens.append(replace(fixture.UID, text='UID:200000000', score=.74))
        for frames in ([next_board(green=2, notice=True), next_board(green=2)],
                       [next_board(green=7, notice=True), EmptyCapture('gap'), next_board(green=2)],
                       [next_board(green=7, notice=True), wrong_identity, next_board(green=2)]):
            with self.subTest(case=type(frames[1]).__name__):
                outcome = self.run_reward([*frames, *[next_board()] * 23])
                self.assert_existing_inputs(outcome)
                self.assertIsInstance(outcome.error, Stopped)
                receipt = outcome.data['actions'][-1][RECORD]
                self.assertEqual(receipt['notice']['quantity'], 2)
                self.assertIsNone(receipt['hud_green_after'])
                self.assertIsNone(receipt['wallet_change'])

    def test_foreign_journal_and_failed_receipt_write_keep_pending(self):
        frames = [next_board(green=7, notice=True), next_board(green=2), next_board(green=2)]
        for failure in ('reward_journal', 'reward_replace_late', 'reward_publish'):
            with self.subTest(failure=failure):
                outcome = self.run_reward(frames, failure=failure)
                self.assert_existing_inputs(outcome)
                self.assertEqual(outcome.injected, [failure])
                self.assertEqual(outcome.data['actions'][-1]['status'], 'pending')
                self.assertNotIn(RECORD, outcome.data['actions'][-1])
                self.assertNotIn(RECORD, outcome.report['actions'][-1])
                if failure != 'reward_publish':
                    self.assertTrue(outcome.data['synthetic_foreign_revision'])
                    self.assertIsInstance(outcome.error, AutomationError)
                else:
                    self.assertIsInstance(outcome.error, PermissionError)
