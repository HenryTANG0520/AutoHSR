"""Result fields from historical captures, kept separate from the weekly goal."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow
from autohsr.du_periodic_points import periodic_settlement_observation
from autohsr.models import RunReport, Scene, Token
from autohsr.tests.test_currency_wars_weekly_rewards import overlay, panel


SOURCES = Path(__file__).parent / 'fixtures/du_runtime/periodic_settlement_fields.json'


def original(name):
    case = json.loads(SOURCES.read_bytes())['cases'][name]
    tokens = [Token(t['text'], t['score'], tuple(t['box'])) for t in case['tokens']]
    return Scene(tokens)


class PeriodicSettlementTests(unittest.TestCase):
    def test_report_and_ledger_keep_each_fitting_read_separate_from_weekly_points(self):
        context = Mock(settings=Settings(), report=RunReport(operation='differential_universe'))
        flow = DifferentialUniverseWorkflow(context, 1, until_points=True)
        cases = (
            ('bonus-fresh', 'victory', '探索成功', 13, 2000, [1000, 1000], 200),
            ('standard-fit-1000', 'victory', '探索成功', 13, 1000, [1000], None),
            ('interrupted-fit-300', 'defeat', '探索中断', 5, 300, [300], 30),
            ('x2-old-ocr-omitted', 'victory', '探索成功', 13, None, None, 200),
            ('max-reward-text', 'victory', '探索成功', 13, None, None, None),
        )
        with TemporaryDirectory() as folder:
            flow.report['run_dir'] = folder
            context.evidence.return_value = Path(folder) / 'source.png'
            for name, kind, outcome, area, value, terms, materials in cases:
                with self.subTest(name=name):
                    self.assertEqual(flow._observe(original(name)), kind)
                    result = flow.report['page_history'][-1]['periodic_settlement']
                    self.assertEqual((result['outcome'], result['area_index'], result['area_total']), (outcome, area, 13))
                    self.assertEqual((result['fitting_value_gained'], result['fitting_value_terms']), (value, terms))
                    self.assertIsNone(result['weekly_points_gained'])
                    self.assertEqual(result['unlock_materials_gained'], materials)
                    self.assertIs(result.get('reward_limit_message'), True if name == 'max-reward-text' else None)
            ledger = json.loads(Path(flow.report['ledger_path']).read_bytes())
            self.assertEqual(ledger['page_history'], flow.report['page_history'])
            self.assertEqual(ledger['completed_runs'], 0)
            self.assertFalse(ledger['periodic_points']['verified'])
            self.assertEqual(ledger['periodic_points_goal']['observations'], [])
        context.click.assert_not_called()
        context.wait.assert_not_called()

    def test_public_results_separate_point_amounts_and_preserve_the_execution_page(self):
        context = Mock(settings=Settings(), report=RunReport(operation='differential_universe'))
        flow = DifferentialUniverseWorkflow(context, 1, until_points=True)
        page = original('public-separate-points')
        self.assertEqual(flow._observe(page), 'victory')
        observation = flow.report['page_history'][-1]['periodic_settlement']
        self.assertEqual(observation['weekly_points_gained'], 15300)
        self.assertEqual(observation['fitting_value_terms'], [1000, 850])
        self.assertEqual(observation['fitting_value_gained'], 1850)
        self.assertIsNone(observation['unlock_materials_gained'])

        partial = replace(page, tokens=[t for t in page.tokens if t.text != '15300'])
        observed = periodic_settlement_observation(partial)
        self.assertIsNone(observed['weekly_points_gained'])
        self.assertEqual(observed['fitting_value_gained'], 1850)

        fitting = page.find('获得拟合值', exact=True)
        points = page.find('获得积分', exact=True)
        overlap = replace(page, tokens=[
            replace(t, box=points.box) if t is fitting else t for t in page.tokens
        ])
        observed = periodic_settlement_observation(overlap)
        self.assertIsNone(observed['weekly_points_gained'])
        self.assertIsNone(observed['fitting_value_gained'])

        self.assertEqual(flow._observe(original('public-20-of-20')), 'unknown')
        observation = flow.report['page_history'][-1]['periodic_settlement']
        self.assertEqual((observation['area_index'], observation['area_total']), (20, 20))
        self.assertIs(observation['reward_limit_message'], True)
        self.assertIsNone(observation['weekly_points_gained'])
        self.assertEqual(flow.report['completed_runs'], 0)
        self.assertEqual(flow.report['periodic_points_goal']['observations'], [])
        context.click.assert_not_called()

    def test_transitional_and_other_mode_pages_never_publish_settlement(self):
        complete = original('bonus-fresh')
        progress = complete.find('周期演算（13/13）', exact=True)
        normal = replace(complete, tokens=[
            replace(t, text='常规演算（13/13）') if t is progress else t for t in complete.tokens
        ])
        for page in (
            original('x1-anim'),
            original('before-defeat-confirmation'),
            original('regular-low-rank-warning'),
            normal,
        ):
            with self.subTest(text=page.text):
                self.assertIsNone(periodic_settlement_observation(page))

    def test_split_plus_and_ambiguous_number_fields(self):
        complete = original('bonus-fresh')
        value = complete.find('1000+1000', exact=True)
        background = [token for token in complete.tokens if token is not value]
        first = Token('１，０００', .99, (.225, .730, .260, .755))
        plus = Token('＋', .99, (.265, .734, .274, .752))
        second = Token('1000', .99, (.278, .730, .315, .755))

        def terms(*fields):
            page = replace(complete, tokens=[*background, *fields])
            return periodic_settlement_observation(page)['fitting_value_terms']

        self.assertEqual(terms(first, plus, second), [1000, 1000])
        for fields in ((first, second), (first, plus), (value, second),
                       (first, plus, replace(second, score=.60)),
                       (replace(value, text='18000/18000'),),
                       (replace(value, text='1000 1000'),),
                       (replace(value, text='1000+1000+300'),)):
            with self.subTest(fields=fields):
                self.assertIsNone(terms(*fields))

    def test_limit_message_keeps_amounts_unverified_on_a_mixed_frame(self):
        capped = original('max-reward-text')
        rewards = [t for t in original('bonus-fresh').tokens
                   if t.text in ('获得拟合值', '1000+1000', '获得解锁材料', '200')]
        scene = replace(capped, tokens=[*capped.tokens, *rewards])
        observation = periodic_settlement_observation(scene)
        self.assertIs(observation['reward_limit_message'], True)
        self.assertIsNone(observation['unlock_materials_gained'])
        self.assertIsNone(observation['fitting_value_gained'])

    def test_shared_panel_reads_available_control_but_missing_control_never_proves_claim(self):
        context = Mock(settings=Settings(), report=RunReport(operation='differential_universe'))
        flow = DifferentialUniverseWorkflow(context, 1, until_points=True)
        for current, enabled, missing, expected in (
            (18000, True, False, 'available'),
            (18000, False, False, 'unavailable'),
            (0, False, True, 'unverified'),
            (18000, True, True, 'unverified'),
            (0, True, False, 'unverified'),
        ):
            with self.subTest(current=current, enabled=enabled, missing=missing):
                page = panel(current, enabled)
                if missing:
                    page = replace(page, tokens=[t for t in page.tokens if t.text != '一键领取'])
                self.assertEqual(flow._observe(page), 'unknown')
                row = flow.report['page_history'][-1]
                self.assertEqual(row['shared_periodic_rewards'],
                                 dict(current=current, cap=18000, claim_control=expected))
                self.assertNotIn('periodic_settlement', row)
        flow._observe(overlay())
        self.assertNotIn('shared_periodic_rewards', flow.report['page_history'][-1])
        self.assertEqual(flow.report['periodic_points_goal']['observations'], [])
        self.assertEqual(flow.report['actions'], [])
        self.assertFalse(flow.report['periodic_points']['verified'])
        context.click.assert_not_called()
