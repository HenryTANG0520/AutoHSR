"""Independent strict-capture adapter and fake Win32 for the Odyssey coordinator."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from autohsr import daily_event_claim as claim, workflow_lease
from autohsr.daily_event_claim_flow import DailyEventClaim
from autohsr.models import AutomationError, FocusLost, Stopped, Token
from autohsr.tests import test_daily_event_claim as claim_cases
from autohsr.workflow_identity import account_scope


def frame(scene, *, account=claim_cases.ACCOUNT, quantity=None, step=1):
    return scene, account, quantity, step


class DailyEventClaimFlowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = claim_cases.DailyEventClaimTests()
        self.fixture.setUp()
        self.win32 = self.fixture.native
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.context = self.fixture.context
        self.context.report.run_dir = str(self.root / 'runs' / 'volatile-first')
        self.context.snapshot = Mock(side_effect=AssertionError('ordinary snapshot may wait for focus'))
        self.addCleanup(self.context.snapshot.assert_not_called)
        self.context.snapshot_foreground = Mock(side_effect=self.snapshot)
        self.context.daily_event_claim_input = lambda _, intent: intent.submit(self.context)
        self.context.vision._read_field = self.field
        self.context.sleep = Mock(side_effect=self.sleep)
        self.frames = iter(())
        self.amount = None
        self.enterContext(patch('autohsr.daily_event_claim_flow.time',
                                SimpleNamespace(monotonic=lambda: self.fixture.now)))
        self.enterContext(patch.object(workflow_lease, 'NAME', 'Local\\AutoHSR.OdysseyFlowQA.' + uuid4().hex))

    def sleep(self, seconds):
        self.fixture.now += seconds

    def snapshot(self):
        self.assertIsNotNone(workflow_lease._owner.get())
        context = self.context
        context.last_scene = None
        entry = next(self.frames)
        if isinstance(entry, BaseException):
            context.capture_sequence += 1
            raise entry
        scene, account, self.amount, step = entry
        context.capture_sequence += step
        scene.geometry, scene.captured_at = self.fixture.geometry, self.fixture.now
        self.fixture.now += .02
        if account is not None:
            scene.tokens.append(account)
        context.scene_epoch = context.runner.input_epoch
        context.last_scene = scene
        return scene

    def field(self, _image, pattern):
        if self.amount is not None and pattern == claim._NUMBER_PATTERN:
            return Token(str(self.amount), .97, (0, 0, 1, 1))
        return None

    def queue(self, *after, day=4):
        self.context.snapshot_foreground.reset_mock()
        self.context.sleep.reset_mock()
        before = tuple(frame(claim_cases.day_cards(set(range(1, day)))) for _ in range(2))
        self.frames = iter(before + after)

    def saved(self, root=None):
        directory = (root or self.root) / 'runs' / 'daily-event-claim'
        return {path.name: path.read_bytes() for path in directory.iterdir()} if directory.is_dir() else {}

    def states(self, root=None):
        return {json.loads(raw)['state'] for raw in self.saved(root).values()}

    def test_exact_open_card_clicks_once_and_observes_only_the_popup(self):
        self.queue(frame(claim_cases.popup(), quantity=2), frame(claim_cases.popup(), quantity=2), day=3)
        attempt = DailyEventClaim(self.context, root=self.root, day=3)

        def send_after_preflight(count, items, size):
            self.assertIsNotNone(workflow_lease._owner.get())
            self.assertEqual(self.context.snapshot_foreground.call_count, 2)
            self.assertEqual(self.states(), {'pending', 'reserved'})
            return self.fixture.send_input(count, items, size)

        self.win32.SendInput.side_effect = send_after_preflight
        result = attempt.run()
        self.assertEqual((result.task, result.status), (claim.OPERATION, 'partial'))
        self.assertEqual(attempt.record, dict(schema=1, activity=claim.ACTIVITY, day=3, client_version='4.6.0',
                                              state='pending', stage='return', submission='sent', popup='observed',
                                              quantity=2))
        self.assertEqual(self.states(), {'pending', 'reserved', 'submitted'})
        self.assertEqual(self.context.snapshot_foreground.call_count, 4)
        self.assertEqual([call.args[0] for call in self.context.sleep.call_args_list], [.15, .75, .15])
        self.assertEqual([event[0] for event in self.fixture.packets[0]], [0xC001, 2, 4])
        self.win32.SendInput.assert_called_once()
        self.assertIsNone(workflow_lease._owner.get())
        self.assertNotIn(self.context.report.run_dir, json.dumps(attempt.record, ensure_ascii=False))

    def test_missing_capability_and_outer_account_scope_cannot_capture(self):
        strict = self.context.snapshot_foreground
        del self.context.snapshot_foreground
        with self.assertRaisesRegex(AutomationError, '严格前台'):
            DailyEventClaim(self.context, root=self.root, day=4).run()
        self.context.snapshot_foreground = strict
        with account_scope(object()), self.assertRaisesRegex(AutomationError, '严格前台'):
            DailyEventClaim(self.context, root=self.root, day=4).run()
        for day in (1, 2, True):
            with self.subTest(day=day), self.assertRaises(AutomationError):
                DailyEventClaim(self.context, root=self.root, day=day)
        strict.assert_not_called()
        self.win32.SendInput.assert_not_called()
        self.assertFalse((self.root / 'runs').exists())

    def test_wrong_page_already_claimed_or_account_missing_before_intent_stops(self):
        for supplied in (frame(claim_cases.popup(), quantity=1), frame(claim_cases.day_cards({1, 2, 3, 4})),
                         frame(claim_cases.day_cards({1, 2, 3}), account=None), FocusLost('foreground gone')):
            with self.subTest(supplied=type(supplied)):
                self.frames = iter((supplied,))
                self.context.snapshot_foreground.reset_mock()
                with self.assertRaises(AutomationError):
                    DailyEventClaim(self.context, root=self.root, day=4).run()
                self.context.snapshot_foreground.assert_called_once()
                self.assertFalse((self.root / 'runs').exists())
                self.win32.SendInput.assert_not_called()

    def test_losing_the_strict_run_scope_between_source_frames_stops_before_intent(self):
        self.queue()

        def lose_scope(seconds):
            self.sleep(seconds)
            self.context.runner._foreground_only = False

        self.context.sleep.side_effect = lose_scope
        with self.assertRaises(AutomationError):
            DailyEventClaim(self.context, root=self.root, day=4).run()
        self.context.snapshot_foreground.assert_called_once()
        self.assertFalse((self.root / 'runs').exists())
        self.win32.SendInput.assert_not_called()

    def test_short_batch_only_releases_left_button_and_stops_before_observation(self):
        self.queue(day=4)
        self.fixture.accepted = 2
        attempt = DailyEventClaim(self.context, root=self.root, day=4)
        result = attempt.run()
        self.assertEqual((result.status, attempt.record['state'], attempt.record['submission']),
                         ('partial', 'pending', 'unconfirmed'))
        self.assertEqual(attempt.record['popup'], 'not_observed')
        self.assertEqual([len(packet) for packet in self.fixture.packets], [3, 1])
        self.assertEqual(self.fixture.packets[-1], ((4, 0, 0),))
        self.assertEqual(self.context.snapshot_foreground.call_count, 2)
        self.assertEqual(self.states(), {'pending', 'reserved'})
        with self.assertRaises(AutomationError):
            attempt.run()
        self.assertEqual(len(self.fixture.packets), 2)

    def test_missing_foreign_or_conflicting_popup_identity_stays_pending(self):
        for index, account in enumerate((None, claim_cases.OTHER, claim_cases.ACCOUNT)):
            with self.subTest(index=index):
                root = self.root / f'identity-{index}'
                root.mkdir()
                popup = claim_cases.popup()
                if index == 2:
                    popup.tokens.append(claim_cases.OTHER)
                self.queue(frame(popup, account=account, quantity=1), frame(claim_cases.popup(), quantity=1))
                attempt = DailyEventClaim(self.context, root=root, day=4)
                self.assertEqual(attempt.run().status, 'partial')
                self.assertEqual(attempt.record['state'], 'pending')
                self.assertEqual(attempt.record['submission'], 'sent')
                self.assertEqual(attempt.record['popup'], 'account_unverified' if account is None else 'unknown')
                self.assertIsNone(attempt.record['quantity'])
                self.assertEqual(self.context.snapshot_foreground.call_count, 3)
                self.assertEqual(self.states(root), {'pending', 'reserved', 'submitted'})
        self.assertEqual([len(packet) for packet in self.fixture.packets], [3, 3, 3])

    def test_one_popup_frame_never_becomes_an_observed_reward(self):
        self.queue(frame(claim_cases.popup(), quantity=1), frame(claim_cases.popup(), account=None, quantity=1))
        attempt = DailyEventClaim(self.context, root=self.root, day=4)
        self.assertEqual(attempt.run().status, 'partial')
        self.assertEqual((attempt.record['stage'], attempt.record['popup']), ('popup', 'account_unverified'))
        self.assertIsNone(attempt.record['quantity'])
        self.assertEqual(self.context.snapshot_foreground.call_count, 4)
        self.assertEqual(self.states(), {'pending', 'reserved', 'submitted'})
        self.win32.SendInput.assert_called_once()

    def test_transition_gap_wrong_amount_or_focus_loss_never_waits_for_a_later_popup(self):
        cases = (frame(claim_cases.day_cards({1, 2, 3, 4})), frame(claim_cases.popup(), quantity=1, step=2),
                 frame(claim_cases.popup(), quantity=2), FocusLost('capture lost foreground'))
        for index, supplied in enumerate(cases):
            with self.subTest(index=index):
                root = self.root / f'gap-{index}'
                root.mkdir()
                self.queue(supplied, frame(claim_cases.popup(), quantity=1))
                attempt = DailyEventClaim(self.context, root=root, day=4)
                self.assertEqual(attempt.run().status, 'partial')
                self.assertEqual((attempt.record['stage'], attempt.record['popup']), ('popup', 'unknown'))
                self.assertEqual(self.context.snapshot_foreground.call_count, 3)
                self.assertEqual([call.args[0] for call in self.context.sleep.call_args_list], [.15, .75])
                self.assertEqual(self.states(root), {'pending', 'reserved', 'submitted'})
        self.assertEqual([len(packet) for packet in self.fixture.packets], [3] * len(cases))

    def test_same_user_root_blocks_replay_across_different_run_directories(self):
        self.queue(frame(claim_cases.popup(), account=None, quantity=1))
        first = DailyEventClaim(self.context, root=self.root, day=4)
        self.assertEqual(first.run().status, 'partial')
        original = self.saved()
        self.context = SimpleNamespace(**{**vars(self.context), 'capture_sequence': 0, 'last_scene': None})
        self.context.report = SimpleNamespace(operation=claim.OPERATION, run_dir=str(self.root / 'runs' / 'volatile-second'))
        self.queue()
        second = DailyEventClaim(self.context, root=self.root, day=4)
        with self.assertRaisesRegex(AutomationError, '已有待核对'):
            second.run()
        self.assertEqual(second.record['submission'], 'not_sent')
        self.assertEqual(self.saved(), original)
        self.assertFalse(Path(self.context.report.run_dir).exists())
        self.win32.SendInput.assert_called_once()

    def test_stop_during_bounded_popup_delay_preserves_the_completed_submission(self):
        self.queue()

        def stop(seconds):
            if seconds == .75:
                raise Stopped('synthetic F10 during popup delay')
            self.sleep(seconds)

        self.context.sleep.side_effect = stop
        attempt = DailyEventClaim(self.context, root=self.root, day=4)
        with self.assertRaises(Stopped):
            attempt.run()
        self.assertEqual(self.context.snapshot_foreground.call_count, 2)
        self.assertEqual((attempt.record['state'], attempt.record['submission']), ('pending', 'sent'))
        self.assertEqual(self.states(), {'pending', 'reserved', 'submitted'})
        self.win32.SendInput.assert_called_once()


if __name__ == '__main__':
    unittest.main()
