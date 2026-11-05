"""Read-only candidate evidence in the real preparation flow with fake IO."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autohsr.tests import test_challenge_prepare as fixtures


class ChallengeCandidateEvidenceTests(unittest.TestCase):
    def test_saved_candidates_never_prove_a_selected_team_or_add_input(self):
        candidates = dict(schema=1, status='observed', candidates=[
            dict(asset_id='Firefly', box=[.04, .15, .09, .24])],
            ambiguities=[], ownership='unknown', availability='unknown',
            selected='unknown', complete='unknown', execution_supported=False)
        with tempfile.TemporaryDirectory() as folder:
            c = fixtures.context(folder, [fixtures.lobby(), fixtures.lobby(),
                                          fixtures.setup(), fixtures.setup()])
            with patch('autohsr.challenge_roster.observe_candidates',
                       side_effect=lambda *a, **k: deepcopy(candidates)) as scan:
                result = fixtures.ChallengePreparationTests().execute(c)
            self.assertEqual(result.status, 'ok')
            self.assertEqual(scan.call_count, 2)
            self.assertTrue(all(call.kwargs == {'mode': 'memory_of_chaos'}
                                for call in scan.call_args_list))
            data = json.loads((Path(c.report.run_dir) /
                               'challenge-preparation.json').read_text(encoding='utf-8'))
            self.assertFalse(data['team_verified'])
            self.assertFalse(data['battle_started'])
            self.assertFalse(data['completion_verified'])
            self.assertTrue(all('candidate_list' not in frame['basis']
                                for frame in data['actions'][0]['lobby_frames']))
            for frame in data['preparation_frames']:
                self.assertEqual(frame['basis']['candidate_list'], candidates)
                self.assertEqual(frame['basis']['team_feedback'], 'unknown')
                self.assertFalse(frame['basis']['execution_supported'])
                slot_evidence = frame['basis']['team_slots']
                self.assertEqual(slot_evidence['reason'], 'missing_slot_calibration')
                self.assertIsNone(slot_evidence['eight_slots_occupied'])
                self.assertIsNone(slot_evidence['team_members_match'])
            c.window.click.assert_called_once()
            c.window.key.assert_not_called()
            # Each observation owns its data, including after persistence.
            c.report.challenge['preparation_frames'][0]['basis']['candidate_list']['candidates'].clear()
            self.assertEqual(len(c.report.challenge['preparation_frames'][1]
                                 ['basis']['candidate_list']['candidates']), 1)
            self.assertEqual(len(data['preparation_frames'][0]
                                 ['basis']['candidate_list']['candidates']), 1)

    def test_unavailable_candidate_read_preserves_preparation_only_result(self):
        unknown = dict(schema=1, status='unknown', reason='unverified_reference',
                       candidates=[], ambiguities=[], selected='unknown',
                       complete='unknown', execution_supported=False)
        with tempfile.TemporaryDirectory() as folder:
            c = fixtures.context(folder, [fixtures.setup(), fixtures.setup()])
            with patch('autohsr.challenge_roster.observe_candidates',
                       side_effect=lambda *a, **k: deepcopy(unknown)):
                self.assertEqual(fixtures.ChallengePreparationTests().execute(c).status, 'ok')
            self.assertEqual(c.report.challenge['actions'], [])
            self.assertFalse(c.report.challenge['team_verified'])
            self.assertFalse(c.report.challenge['completion_verified'])
            self.assertTrue(all(frame['basis']['candidate_list']['status'] == 'unknown'
                                for frame in c.report.challenge['preparation_frames']))
            c.window.click.assert_not_called()
            c.window.key.assert_not_called()


if __name__ == '__main__':
    unittest.main()
