"""Read-only next-station observation using the calibrated control."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from autohsr.config import Settings
from autohsr.du_station_preview import station_reroll_observation
from autohsr.models import AutomationError, Token
from autohsr.tests.test_du_station_policy import flow
from autohsr.tests.test_du_team import fixture


SOURCES = Path(__file__).parent / 'fixtures/du_runtime/station_reroll_fields.json'


class StationRerollObservationTests(unittest.TestCase):
    def setUp(self):
        self.page = fixture('station_explosion_beacon')
        self.original = self.page.find('重抽5', exact=True)
        self.background = [token for token in self.page.tokens if token is not self.original]

    def with_fields(self, *fields):
        return replace(self.page, tokens=[*self.background, *fields])

    def test_real_combined_and_historical_split_fields_on_the_same_control_layout(self):
        self.assertEqual(station_reroll_observation(self.page), dict(status='observed', displayed_count=5))
        for sample in json.loads(SOURCES.read_text(encoding='utf-8'))['samples']:
            with self.subTest(count=sample['count']):
                fields = [Token(row['text'], row['score'], tuple(row['box'])) for row in sample['tokens']]
                self.assertEqual(station_reroll_observation(self.with_fields(*fields)),
                                 dict(status='observed', displayed_count=sample['count']))

    def test_exact_full_width_and_zero_are_displayed_values(self):
        for text, value in (('重抽　３０', 30), ('重抽123', 123), ('重抽0', 0)):
            with self.subTest(text=text):
                self.assertEqual(station_reroll_observation(self.with_fields(replace(self.original, text=text))),
                                 dict(status='observed', displayed_count=value))

    def test_missing_malformed_or_unrelated_count_remains_unverified(self):
        label = Token('重抽', .99, (.362, .881, .390, .900))
        wrong_row = Token('8', .99, (.400, .902, .412, .911))
        wrong_column = Token('8', .99, (.340, .883, .353, .903))
        weak_number = Token('8', .45, (.399, .883, .410, .904))
        fields_by_case = [(), (label,), (label, wrong_row), (label, wrong_column), (label, weak_number)]
        fields_by_case.extend((replace(self.original, text=text),)
                              for text in ('重抽+3', '重抽-1', '重抽1/5', '重抽②', '重抽12次'))
        for fields in fields_by_case:
            with self.subTest(fields=fields):
                value = station_reroll_observation(self.with_fields(*fields))
                self.assertEqual((value['status'], value['displayed_count']), ('unverified', None))

    def test_conflicting_readings_are_not_resolved_by_confidence_or_position(self):
        other = replace(self.original, text='重抽8', score=.99)
        value = Token('8', .99, (.401, .883, .414, .906))
        for fields in ((self.original, other), (self.original, value)):
            with self.subTest(fields=fields):
                self.assertEqual(station_reroll_observation(self.with_fields(*fields)),
                                 dict(status='unverified', displayed_count=None, reason='conflicting_fields'))

    def test_visible_text_needs_the_current_supported_control_and_neighbour(self):
        gray = np.full_like(self.page.image, 145)
        missing_confirm = [token for token in self.page.tokens if token.text.strip() != '确定']
        cases = {'no_pixels': replace(self.page, image=None), 'gray_view': replace(self.page, image=gray),
                 'no_confirm': replace(self.page, tokens=missing_confirm)}
        for name, scene in cases.items():
            with self.subTest(name=name):
                self.assertIsNone(station_reroll_observation(scene)['displayed_count'])

    def test_other_station_pages_keep_their_own_observation_kind(self):
        current = flow()
        for name, kind in (('last_area_confirm', 'last_area_confirm'), ('beacon_reroll_target', 'miracle_target')):
            with self.subTest(name=name):
                self.assertEqual(current._observe(fixture(name)), kind)
                self.assertNotIn('station_reroll', current.report['page_history'][-1])
        current.ctx.click.assert_not_called()

    def test_history_keeps_each_read_and_disabled_stations_still_stop(self):
        settings = Settings(differential_universe_station_custom=True,
                            differential_universe_station_disabled=['战斗', '财富', '商店'])
        current = flow(settings)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current.report['run_dir'] = str(root)
            current.ctx.evidence.return_value = root/'fixture.png'
            next_read = self.with_fields(replace(self.original, text='重抽4'))
            missing = self.with_fields(replace(self.original, text='重抽'))
            for scene in (self.page, missing, next_read):
                self.assertEqual(current._observe(scene), 'station_choice')
            with self.assertRaisesRegex(AutomationError, '均已禁用'):
                current._progress_run(next_read, 'station_choice')
            history = current.report['page_history']
            self.assertEqual([row['station_reroll']['displayed_count'] for row in history], [5, None, 4])
            ledger = json.loads(Path(current.report['ledger_path']).read_bytes())
            self.assertEqual(ledger['page_history'], history)
        current.ctx.click.assert_not_called()
        current.ctx.wait.assert_not_called()
