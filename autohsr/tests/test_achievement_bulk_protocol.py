from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from autohsr.achievement_bulk_protocol import AchievementBulkReplay, ClaimFrame, ClaimScope
from autohsr.models import Scene
from autohsr.tests.test_achievement_pages import gold_controls, label, overview, receipt_rows, scrolled_receipt_rows


SCOPE = ClaimScope('a' * 64, 101, 4, '4.6.0')
FIXTURE = Path(__file__).parent / 'fixtures' / 'achievement_return' / 'bulk_reward_4_6.json'


class AchievementBulkProtocolTests(TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.replay = AchievementBulkReplay(self.directory, SCOPE)
        self.sequence = 0

    def frames(self, count, *tokens, gold=None, cleared=False, jade_icon=False, pixels=None):
        out = []
        for _ in range(count):
            self.sequence += 1
            image = pixels.copy() if pixels is not None else gold_controls(gold) if gold is not None else gold_controls()
            scene = Scene(list(tokens), image, captured_at=10 + self.sequence / 5)
            out.append(ClaimFrame(SCOPE, self.sequence, scene, cleared, jade_icon))
        return out

    def overview_frames(self, count=2, *, achievement_total=911, claim=False, cleared=True, duplicate=False):
        button = label('键领取奖励', .825, .898)
        tokens = [*overview(), label(str(achievement_total), .373, .91)]
        if claim:
            tokens.append(button)
        if duplicate:
            tokens.append(label('一键领取奖励', .833, .899, score=.78))
        return self.frames(count, *tokens, gold=button if claim else None, cleared=cleared and not claim)

    def receipt_frames(self, count=2, *, amount=20, category=True, modal=False, rows=True):
        tokens = [label('成就奖励', .50, .114), label('总计获得', .466, .836),
                  label(f'×{amount}', .55, .838, score=.84), label('确认', .502, .926)]
        if category:
            tokens.append(label('与你同行的回忆', .127, .193))
        pixels = None
        if rows:
            positions = (.258, .408) if category else (.206, .356)
            details = [label('东山再起', .176, positions[0]), label('超大杯', .166, positions[1])]
            tokens.extend(details)
            pixels = receipt_rows(*details) if category else scrolled_receipt_rows(details, (0, 1))
        if modal:
            tokens.append(label('确认', .5, .65))
        return self.frames(count, *tokens, pixels=pixels)

    def overlay_frames(self, amount=20, *, overview_behind=False, item='星琼'):
        tokens = [label('获得物品', .50, .16), label(str(amount), .50, .548),
                  label(item, .50, .578), label('点击空白处关闭', .50, .735)]
        if overview_behind:
            tokens.extend([*overview(), label('911', .373, .91)])
        return self.frames(2, *tokens)

    def wallet_frames(self, amount, *, banner='沧海萃珠', icon=True):
        return self.frames(2, label('跃迁', .066, .048), label(banner, .080, .075),
                           label('角色活动跃迁', .22, .175), label('131', .816, .060),
                           label(str(amount), .889, .060), jade_icon=icon)

    @staticmethod
    def reserve(prepare, frames):
        current = frames[-1]
        now = current.scene.captured_at + .01
        return prepare(frames[:2], current, now), now

    def send_claim(self, *, achievement_total=911):
        digest, at = self.reserve(self.replay.reserve_claim,
                                  self.overview_frames(3, claim=True, achievement_total=achievement_total))
        self.replay.record_send(digest, 'sent', at, scope=SCOPE)
        return digest

    def send_confirmation(self, amount=20):
        self.assertTrue(self.replay.observe_receipt(self.receipt_frames(amount=amount)))
        digest, at = self.reserve(self.replay.reserve_confirmation,
                                  self.receipt_frames(3, amount=amount, category=False))
        self.replay.record_send(digest, 'sent', at, scope=SCOPE)
        return digest

    def return_to_overview(self, *, amount=20, achievement_total=911, cleared=True):
        self.send_claim(achievement_total=achievement_total)
        self.send_confirmation(amount)
        self.assertTrue(self.replay.observe_overlay(self.overlay_frames(amount, overview_behind=True)))
        self.assertTrue(self.replay.observe_return(self.overview_frames(achievement_total=achievement_total,
                                                                       cleared=cleared)))

    def test_transcribed_current_video_with_attributed_balance(self):
        p2 = json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'][0]['expected']
        self.assertTrue(self.replay.observe_balance_before(self.wallet_frames(p2['stellar_jade_balance']['before'])))
        self.return_to_overview(amount=p2['receipt_total'], achievement_total=p2['achievement_total']['before'])
        self.assertTrue(self.replay.observe_balance_after(self.wallet_frames(p2['stellar_jade_balance']['after']),
                                                          isolated_wallet_interval=True))
        result = self.replay.result
        self.assertEqual((result.bulk_input, result.confirm_input), ('sent', 'sent'))
        self.assertEqual((result.receipt_total, result.overlay_quantity), (20, 20))
        self.assertTrue(result.overview_return_verified and result.overview_controls_cleared)
        self.assertEqual((result.jade_balance_delta, result.jade_attributed), (20, 20))
        claim = self.directory / 'achievement-bulk-intent.json'
        confirm = self.directory / 'achievement-bulk-confirm-intent.json'
        dispatch = json.loads((self.directory / 'achievement-bulk-send.json').read_text())
        self.assertEqual(json.loads(confirm.read_text())['previous_claim'], dispatch['intent'])
        self.assertEqual(json.loads(claim.read_text())['frames'][0]['sequence'], 3)

    def test_transcribed_multicategory_video_keeps_balance_unknown(self):
        p6 = json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'][1]['expected']
        self.return_to_overview(amount=p6['receipt_total'], achievement_total=p6['achievement_total']['before'])
        result = self.replay.result
        self.assertEqual(result.overlay_quantity, 50)
        self.assertTrue(result.overview_return_verified)
        self.assertIsNone(result.jade_attributed)
        self.assertIsNone(result.jade_balance_before)
        self.assertIsNone(result.jade_balance_after)

    def test_only_an_isolated_comparable_wallet_interval_attributes_the_delta(self):
        for amount, banner, isolated, cleared, delta in (
            (4528, '沧海萃珠', False, True, 20), (4528, '其他卡池', True, True, None),
            (4527, '沧海萃珠', True, True, 19), (4528, '沧海萃珠', True, False, 20),
        ):
            with self.subTest(amount=amount, banner=banner, isolated=isolated, cleared=cleared), TemporaryDirectory() as d:
                self.replay = AchievementBulkReplay(d, SCOPE)
                self.assertTrue(self.replay.observe_balance_before(self.wallet_frames(4508)))
                self.return_to_overview(cleared=cleared)
                self.assertTrue(self.replay.observe_balance_after(self.wallet_frames(amount, banner=banner),
                                                                  isolated_wallet_interval=isolated))
                self.assertEqual(self.replay.result.jade_balance_delta, delta)
                self.assertIsNone(self.replay.result.jade_attributed)

    def test_missing_or_ambiguous_controls_do_not_reserve(self):
        for frames in (self.overview_frames(3), self.overview_frames(3, claim=True, duplicate=True),
                       self.receipt_frames(3), self.frames(3, label('领取', .875, .63))):
            with self.subTest(sequence=frames[0].sequence), self.assertRaises(ValueError):
                self.reserve(self.replay.reserve_claim, frames)
        self.assertFalse(list(self.directory.iterdir()))

    def test_conflicting_scope_or_stale_third_frame_blocks_a_reservation(self):
        stale = self.overview_frames(3, claim=True)
        with self.assertRaises(ValueError):
            self.replay.reserve_claim(stale[:2], stale[-1], stale[-1].scene.captured_at + 10)
        frames = self.overview_frames(3, claim=True)
        frames[-1] = replace(frames[-1], scope=replace(SCOPE, account_key='b' * 64))
        with self.assertRaises(ValueError):
            self.reserve(self.replay.reserve_claim, frames)
        self.assertTrue(self.replay.result.stopped)
        self.assertFalse(list(self.directory.iterdir()))

    def test_exclusive_intent_blocks_competing_process_and_restarted_attempt(self):
        other = AchievementBulkReplay(self.directory, SCOPE)
        digest, at = self.reserve(self.replay.reserve_claim, self.overview_frames(3, claim=True))
        with self.assertRaises(FileExistsError):
            self.reserve(other.reserve_claim, self.overview_frames(3, claim=True))
        self.replay.record_send(digest, 'unknown', at, scope=SCOPE)
        with self.assertRaises(FileExistsError):
            AchievementBulkReplay(self.directory, SCOPE)
        with self.assertRaises(ValueError):
            self.replay.record_send(digest, 'sent', at, scope=SCOPE)
        self.assertTrue(self.replay.result.stopped)
        self.assertEqual(self.replay.result.bulk_input, 'unknown')
        self.assertEqual(self.replay.result.confirm_input, 'not_sent')

    def test_changed_source_and_failed_send_journal_keep_reserved_intent(self):
        frames = self.overview_frames(3, claim=True)
        digest, at = self.reserve(self.replay.reserve_claim, frames)
        frames[0].scene.image[0, 0] = 255
        with self.assertRaises(ValueError):
            self.replay.record_send(digest, 'sent', at, scope=SCOPE)
        self.assertEqual(self.replay.result.bulk_input, 'unknown')
        with self.assertRaises(FileExistsError):
            AchievementBulkReplay(self.directory, SCOPE)
        with TemporaryDirectory() as d:
            self.replay = AchievementBulkReplay(d, SCOPE)
            digest, at = self.reserve(self.replay.reserve_claim, self.overview_frames(3, claim=True))
            with patch('autohsr.achievement_bulk_protocol._write_once', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    self.replay.record_send(digest, 'sent', at, scope=SCOPE)
            self.assertEqual(self.replay.result.bulk_input, 'unknown')
            self.assertTrue((Path(d) / 'achievement-bulk-intent.json').exists())

    def test_intent_write_failure_blocks_the_attempt_before_any_send(self):
        frames = self.overview_frames(3, claim=True)
        with patch('autohsr.achievement_bulk_protocol._write_once', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.reserve(self.replay.reserve_claim, frames)
        self.assertEqual(self.replay.result.bulk_input, 'not_sent')
        self.assertTrue(self.replay.result.stopped)
        with self.assertRaises(ValueError):
            self.reserve(self.replay.reserve_claim, self.overview_frames(3, claim=True))

    def test_confirmation_checks_original_intent_and_freezes_total(self):
        self.send_claim()
        self.assertFalse(self.replay.observe_receipt(self.receipt_frames(category=False)))
        self.assertFalse(self.replay.observe_receipt(self.receipt_frames(rows=False)))
        self.assertTrue(self.replay.observe_receipt(self.receipt_frames()))
        for frames in (self.receipt_frames(3, amount=50), self.receipt_frames(3, modal=True)):
            with self.assertRaises(ValueError):
                self.reserve(self.replay.reserve_confirmation, frames)
        (self.directory / 'achievement-bulk-intent.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.reserve(self.replay.reserve_confirmation, self.receipt_frames(3))
        self.assertTrue(self.replay.result.stopped)
        self.assertEqual(self.replay.result.receipt_total, 20)

    def test_send_with_changed_window_epoch_stops_after_recording_intent(self):
        digest, at = self.reserve(self.replay.reserve_claim, self.overview_frames(3, claim=True))
        with self.assertRaises(ValueError):
            self.replay.record_send(digest, 'sent', at, scope=replace(SCOPE, input_epoch=5))
        self.assertEqual(self.replay.result.bulk_input, 'unknown')
        self.assertTrue(self.replay.result.stopped)
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_overlay_must_follow_confirmation_and_cannot_stand_in_for_return(self):
        self.send_claim()
        with self.assertRaises(ValueError):
            self.replay.observe_overlay(self.overlay_frames())
        self.send_confirmation()
        self.assertFalse(self.replay.observe_overlay(self.overlay_frames(50)))
        self.assertFalse(self.replay.observe_overlay(self.overlay_frames(item='信用点')))
        self.assertTrue(self.replay.observe_overlay(self.overlay_frames(overview_behind=True)))
        self.assertFalse(self.replay.observe_return(self.overlay_frames(overview_behind=True)))
        self.assertFalse(self.replay.observe_return(self.overview_frames(achievement_total=999)))
        self.assertEqual(self.replay.result.overlay_quantity, 20)
        self.assertFalse(self.replay.result.overview_return_verified)
        self.assertIsNone(self.replay.result.jade_attributed)

    def test_balance_requires_verified_jade_icon_and_ignores_adjacent_pass_count(self):
        self.assertFalse(self.replay.observe_balance_before(self.wallet_frames(4508, icon=False)))
        self.assertTrue(self.replay.observe_balance_before(self.wallet_frames(4508)))
        self.assertEqual(self.replay.result.jade_balance_before, 4508)
        with self.assertRaises(ValueError):
            self.replay.observe_balance_before(self.wallet_frames(4528))

    def test_late_generic_overlay_is_not_bound_to_confirmation(self):
        self.send_claim()
        self.send_confirmation()
        self.sequence += 50
        with self.assertRaises(ValueError):
            self.replay.observe_overlay(self.overlay_frames())
        self.assertTrue(self.replay.result.stopped)
        self.assertEqual(self.replay.result.confirm_input, 'sent')
        self.assertEqual(self.replay.result.receipt_total, 20)
        self.assertIsNone(self.replay.result.overlay_quantity)

    def test_missing_button_ocr_does_not_override_visible_gold_in_the_same_slot(self):
        self.send_claim()
        self.send_confirmation()
        self.assertTrue(self.replay.observe_overlay(self.overlay_frames()))
        gold = label('一键领取奖励', .825, .898)
        result = self.frames(2, *overview(), label('911', .373, .91), gold=gold, cleared=True)
        self.assertTrue(self.replay.observe_return(result))
        self.assertTrue(self.replay.result.overview_return_verified)
        self.assertFalse(self.replay.result.overview_controls_cleared)
