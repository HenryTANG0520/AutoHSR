"""Replay return scheduling with bounded OCR delay and a simulated handoff."""
import unittest
from unittest.mock import Mock

from autohsr.daily_event_claim_flow import DailyEventClaim
from autohsr.tests import test_daily_event_claim as cases
from autohsr.tests import test_daily_event_claim_flow as flow_cases


class DailyEventClaimCadenceTests(unittest.TestCase):
    def setUp(self):
        self.flow = flow_cases.DailyEventClaimFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)
        self.context = self.flow.context
        self.context.runner.emit = Mock()
        self.clock = self.flow.fixture
        self.start = self.clock.now
        self.return_reads = []

    def run_case(self, costs, *, ready, submit_delay=0):
        source_cost, popup_cost, return_cost = costs
        original = self.context.daily_event_claim_input

        def submit(attempt, intent):
            original(attempt, intent)
            self.clock.now += submit_delay

        def snapshot():
            sequence = self.context.capture_sequence
            started = self.clock.now
            elapsed = started - self.start
            if sequence < 2:
                entry = flow_cases.frame(cases.day_cards({1, 2, 3}))
                cost = source_cost
            elif sequence < 4 or elapsed < ready:
                entry = flow_cases.frame(cases.popup(), quantity=1)
                cost = popup_cost
            else:
                entry = flow_cases.frame(cases.day_cards({1, 2, 3, 4}))
                cost = return_cost
            self.flow.frames = iter((entry,))
            scene = self.flow.snapshot()
            if sequence >= 4:
                self.return_reads.append(round(elapsed, 3))
            self.clock.now = started + cost
            return scene

        self.context.daily_event_claim_input = submit
        self.context.snapshot_foreground.side_effect = snapshot
        attempt = DailyEventClaim(self.context, root=self.flow.root, day=4, observe_return=True)
        result = attempt.run()
        self.flow.win32.SendInput.assert_called_once()
        return result

    def test_late_handoff_still_allows_the_minimum_two_return_captures(self):
        # Shift the handoff near the deadline without adding another poll.
        result = self.run_case((.617, .407, .653), ready=6.61, submit_delay=3.122)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(self.return_reads, [6.62, 7.273])
        self.assertLess(self.clock.now - self.start, 8)

    def test_repeated_popup_polls_still_allow_two_return_frames_near_the_deadline(self):
        result = self.run_case((.617, .407, .610), ready=6.45)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(self.return_reads, [3.498, 4.305, 5.112, 5.919, 6.726, 7.336])
        self.assertLess(self.clock.now - self.start, 8)

    def test_genuine_late_return_does_not_extend_the_original_deadline(self):
        result = self.run_case((.617, .407, .653), ready=7.0, submit_delay=2.422)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(self.flow.states(), {'pending', 'reserved', 'submitted'})
        self.assertTrue(all(elapsed < 8 for elapsed in self.return_reads))

    def test_spare_budget_preserves_the_original_960_handoff_spacing(self):
        result = self.run_case((.340, .191, .336), ready=3.75)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(self.return_reads, [2.512, 3.103, 3.694, 4.285, 4.621])

    def test_faster_return_does_not_spend_an_extra_poll_before_the_user_closes(self):
        result = self.run_case((.617, .407, .500), ready=6.70, submit_delay=2.422)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(self.return_reads, [5.92, 6.727, 7.227])

    def test_fast_reads_keep_the_original_minimum_gap_between_capture_starts(self):
        result = self.run_case((.05, .03, .04), ready=1.50)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(self.return_reads, [1.61, 1.76])
