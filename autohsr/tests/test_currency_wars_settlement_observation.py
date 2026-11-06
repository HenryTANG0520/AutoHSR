"""Read-only Currency Wars settlement and points through the real CLI."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

import numpy as np

from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.currency_feedback import observation, result
from autohsr.currency_wars_settlement_observation import read_settlement
from autohsr.models import Scene, Token
from autohsr.tests import test_currency_wars as coordinator_tests
from autohsr.tests.test_currency_wars_standard_progress import loss_page


def token(text, box):
    return Token(text, .99, box)


def frame(fields, size=(852, 480)):
    width, height = size
    return Scene([token(text, box) for text, box in fields], np.zeros((height, width, 3), dtype=np.uint8))


def defeat_summary(hp=0):
    # Exact synthetic readings at the public A8-12 result's field positions.
    return frame((
        ('对局未完成', (.235, .203, .308, .232)),
        ('3-1战斗', (.402, .198, .486, .235)),
        ('小队生命值', (.720, .202, .788, .232)),
        (str(hp), (.813, .203, .837, .231)),
        ('我的阵容', (.403, .365, .453, .394)),
        ('标准博弈', (.193, .437, .250, .463)),
        ('A8财富造物主12', (.259, .437, .372, .465)),
        ('奖励信息', (.183, .485, .240, .523)),
        ('晋升等级170', (.162, .548, .240, .577)),
        ('积分', (.160, .602, .192, .633)),
        ('16800', (.339, .604, .383, .631)),
        ('投资环境', (.404, .641, .453, .667)),
        ('投资策略', (.583, .642, .632, .667)),
        ('晋升点', (.161, .652, .204, .681)),
        ('725', (.349, .652, .383, .682)),
        ('下一页', (.479, .785, .522, .815)),
    ), size=(768, 480))


def victory_summary(hp=100):
    # The header's new rank and the original match difficulty are separate fields.
    return frame((
        ('对局胜利', (.243, .171, .301, .202)),
        ('职级晋升', (.405, .169, .458, .202)),
        ('财富造物主50', (.488, .167, .569, .202)),
        (f'小队生命值{hp}', (.722, .169, .840, .202)),
        ('SSS', (.196, .248, .349, .392)),
        ('我的阵容', (.404, .354, .453, .381)),
        ('标准博弈', (.194, .431, .251, .458)),
        ('A8财富造物主47', (.260, .431, .370, .460)),
        ('奖励信息', (.184, .487, .239, .521)),
        ('晋升等级170', (.162, .554, .239, .582)),
        ('投资环境', (.404, .658, .454, .686)),
        ('投资策略', (.583, .658, .633, .686)),
        ('下一页', (.481, .819, .522, .848)),
    ))


def points_lobby():
    fixture = Path(__file__).with_name('fixtures') / 'currency_wars_points.json'
    tokens = json.loads(fixture.read_text(encoding='utf-8'))['pages']['lobby_full']['tokens']
    fields = [(item['text'], tuple(item['box'])) for item in tokens]
    fields.append(('奖励已全领取', (.695, .552, .764, .575)))
    return frame(fields)


def points_panel():
    return frame((
        ('积分奖励', (.040, .303, .102, .333)),
        ('规则说明', (.824, .305, .871, .330)),
        ('当前积分', (.0771, .6300, .1234, .6533)),
        ('16800/18000', (.0792, .6542, .2078, .6842)),
        ('1800', (.087, .730, .111, .752)),
    ))


class SettlementFieldTests(unittest.TestCase):
    def test_opposite_outcome_or_life_does_not_verify_the_summary(self):
        contradictory = defeat_summary()
        contradictory.tokens.append(token('对局胜利', (.242, .188, .300, .220)))
        for case, scene in (('positive_hp_on_defeat', defeat_summary(hp=16)),
                            ('zero_hp_on_victory', victory_summary(hp=0)), ('opposite_title', contradictory)):
            with self.subTest(case=case):
                self.assertIsNone(read_settlement(scene))

    def test_conflicting_node_or_duplicate_points_field_never_picks_one_reading(self):
        for field, extra in (
            ('node', token('3-2战斗', (.406, .199, .484, .234))),
            ('earned_points', token('16200', (.340, .603, .383, .631))),
            ('earned_points', token('积分', (.159, .602, .190, .632))),
        ):
            with self.subTest(field=field, extra=extra.text):
                scene = defeat_summary()
                scene.tokens.append(extra)
                data = read_settlement(scene)
                self.assertIsNone(getattr(data, field, None))


class SettlementCliTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.runs = self.root / 'runs'
        self.runs.mkdir()
        self.config = self.root / 'config.json'
        Settings(auto_launch=True, overlay_logs=False).save(self.config)
        self.originals = {
            self.config: self.config.read_bytes(),
            self.runs / 'currency-standard-session.json': b'{"status":"active","old_match":"retain"}\r\n',
            self.runs / 'currency-weekly-rewards-current.json': b'{"old_rewards":"retain"}\r\n',
        }
        for path, data in self.originals.items():
            if path != self.config:
                path.write_bytes(data)
        self.window, self.vision, _, daily, launch, budget = coordinator_tests.CoordinatorTests.fixture(self, self.root)
        self.user32 = self.enterContext(patch('autohsr.windows.user32'))
        self.no_game_input = (self.window.send, self.window.click, self.window.click_held, self.window.key,
                              self.window.key_hold, self.window.move, self.window.drag, self.window.scroll,
                              self.user32.SendInput, launch, budget, daily)
        self.enterContext(patch.object(Runner, '_arm_hotkeys'))
        self.enterContext(patch('autohsr.workflow_lease.NAME', 'Local\\AutoHSR-SettlementReadOnly-' + uuid.uuid4().hex))

    def run_cli(self, scene):
        self.window.capture.return_value = (scene.image, scene.geometry)
        self.vision.read.side_effect = lambda image, geometry: replace(scene, image=image, geometry=geometry)
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(main(['--currency-wars-check', '--config', str(self.config)]), 1, stderr.getvalue())
        report = json.loads(stdout.getvalue())
        self.assertEqual((report['operation'], report['status'], report['report_saved']), ('currency_wars', 'partial', True))
        path = Path(report['run_dir']) / 'report.json'
        self.assertTrue(path.resolve().is_relative_to(self.runs.resolve()))
        self.assertEqual(json.loads(path.read_bytes()), report)
        self.assertNotIn(path, self.originals)
        self.originals[path] = path.read_bytes()
        data = report['currency_wars']
        self.assertEqual(data['mode'], 'read_only_calibration')
        self.assertEqual(data['decision'], 'stop_without_input')
        self.assertEqual((report['stamina_spent'], report['stamina_pending'], report['battle_completed']), (0, 0, 0))
        for key in ('gameplay_enabled', 'completion_verified', 'node_verified', 'settlement_verified',
                    'defeat_settlement_verified', 'rewards_verified', 'weekly_rewards_verified', 'claimed_now',
                    'match_started'):
            self.assertIs(data.get(key, False), False, key)
        self.assertTrue(Path(data['screenshot']).is_file())
        self.assertTrue(Path(data['sample']).is_file())
        for method in self.no_game_input:
            method.assert_not_called()
        for original, raw in self.originals.items():
            self.assertEqual(original.read_bytes(), raw)
        return report

    def test_standard_defeat_summary_keeps_life_zero_and_this_match_points(self):
        report = self.run_cli(defeat_summary())
        data = report['currency_wars']
        self.assertEqual(data['settlement_observation'], dict(
            page='defeat_summary', outcome='defeat', node='3-1', remaining_hp=0, earned_points=16800, rank=8, wealth=12,
        ))
        self.assertNotIn('points_progress', data)
        _, detail = result(report)
        for text in (observation(data), detail):
            self.assertIn('生命 0', text)
            self.assertIn('本局积分 16800', text)
            self.assertNotIn('本期总积分', text)
        self.assertNotIn('开发局结算已核实', detail)

    def test_terminal_local_digits_need_two_agreeing_reads_per_field(self):
        scene = defeat_summary()
        scene.tokens = [replace(t, text='3-1X战斗') if t.text == '3-1战斗' else t
                        for t in scene.tokens if t.text != '0']
        node = token('3-1', (.402, .195, .430, .238))
        hp = token('0', (.811, .198, .847, .235))
        reads = {'currency_settlement.node': (node, node), 'currency_settlement.hp': (hp, hp)}
        report = self.run_cli(replace(scene, field_reads=reads))
        data = report['currency_wars']
        observed = data['settlement_observation']
        self.assertEqual((observed['node'], observed['remaining_hp'], observed['earned_points']), ('3-1', 0, 16800))
        sample = json.loads(Path(data['sample']).read_bytes())
        for key, variants in reads.items():
            self.assertEqual([row['text'] for row in sample['field_reads'][key]], [t.text for t in variants])

        conflicting = {'currency_settlement.node': (node, replace(node, text='3-2')),
                       'currency_settlement.hp': (hp, None)}
        observed = self.run_cli(replace(scene, field_reads=conflicting))['currency_wars']['settlement_observation']
        self.assertIsNone(observed['node'])
        self.assertIsNone(observed['remaining_hp'])
        self.assertEqual(observed['earned_points'], 16800)

    def test_standard_victory_summary_does_not_use_promotion_values_as_match_points(self):
        data = self.run_cli(victory_summary())['currency_wars']
        self.assertEqual(data['settlement_observation'], dict(
            page='match_summary', outcome='victory', node=None, remaining_hp=100, earned_points=None, rank=8, wealth=47,
        ))
        self.assertNotIn('points_progress', data)
        self.assertNotIn('本局积分 170', observation(data))
        self.assertNotIn('本局积分 50', observation(data))

    def test_repeated_full_lobby_and_points_panel_show_only_current_total(self):
        for scene, page, current in ((points_lobby(), 'lobby', 18000), (points_lobby(), 'lobby', 18000),
                                     (points_panel(), 'points_rewards', 16800)):
            with self.subTest(page=page, current=current):
                report = self.run_cli(scene)
                data = report['currency_wars']
                self.assertEqual(data['points_progress'], dict(page=page, current=current, limit=18000))
                self.assertNotIn('settlement_observation', data)
                _, detail = result(report)
                self.assertIn(f'本期总积分 {current}/18000', detail)
                self.assertNotIn('本局积分', detail)

    def test_node_continue_and_unrelated_task_reward_never_publish_settlement_or_points(self):
        challenge = frame((
            ('常规挑战', (.0376, .1271, .0915, .1542)),
            ('已完成', (.0376, .1583, .0939, .1896)),
            ('赢得一场敌人难度达到140的战斗', (.2606, .1521, .4472, .1792)),
            ('领取', (.9108, .1542, .9378, .1792)),
            ('20000', (.8192, .2979, .8533, .3229)),
        ))
        overlay = frame((
            ('获得物品', (.4730, .1500, .5270, .1833)),
            ('20', (.4425, .5375, .4601, .5583)),
            ('点击空白处关闭', (.4554, .7167, .5469, .7479)),
        ))
        for case, scene in (('survived_node', loss_page(life=60)), ('zero_life_node', loss_page(life=0)),
                            ('ordinary_challenge', challenge), ('ordinary_reward_overlay', overlay)):
            with self.subTest(case=case):
                report = self.run_cli(scene)
                data = report['currency_wars']
                self.assertNotIn('settlement_observation', data)
                self.assertNotIn('points_progress', data)
                self.assertNotIn('本局积分', observation(data))
