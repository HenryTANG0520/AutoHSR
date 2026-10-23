import json
import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from autohsr.config import Settings
from autohsr.models import Scene,Token,AutomationError,RunReport
from autohsr.du_team import entry,preset,enabled,select,guard_click
from autohsr.differential_universe import DifferentialUniverseWorkflow,classify_page


def fixture(name):
    root=Path(__file__).parent/'fixtures/du_runtime'
    data=json.loads((root/f'{name}.json').read_text(encoding='utf8'))
    return Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in data['tokens']],
        cv2.imdecode(np.fromfile(root/f'{name}.png',np.uint8),1))


class PresetTeamTests(unittest.TestCase):
    def test_setup_animation_is_observed_before_opening_portrait(self):
        setup=fixture('periodic_setup');active=fixture('preset_enabled')
        fading=Scene([t for t in setup.tokens if '启动' not in t.text],setup.image)
        ctx=Mock(settings=Settings(),report=RunReport())
        def wait(predicate,**kwargs):
            page=setup if '就绪' in kwargs['description'] else active
            self.assertTrue(predicate(page))
            return page
        ctx.wait.side_effect=wait
        ctx.differential_universe_close_team.return_value=setup
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(side_effect=[(active,'team_selection'),(active,'team_selection'),(active,'team_selection')])
        self.assertEqual(select(flow,fading)[1],'periodic_setup')
        self.assertIs(flow._click.call_args_list[0].args[0],setup)

    def test_periodic_setup_description_is_not_a_battle_result_during_loading(self):
        from autohsr.tests.test_du_runtime import t
        page=Scene([t(s) for s in ('差分宇宙','乐园漫记','周期演算','难度V','本周首领敌人',
                                   '首领区域战斗胜利后，不会获得方程')])
        self.assertEqual(classify_page(page),'unknown')

    def test_enabled_marker_must_belong_to_requested_full_team(self):
        page=fixture('preset_enabled')
        self.assertTrue(enabled(page,'哈哈哈哈'))
        self.assertFalse(enabled(page,'追击'))
        self.assertFalse(enabled(fixture('preset_list'),'哈哈哈哈'))
        page.tokens=[t for t in page.tokens if t!=page.find('等级80',(.02,.27,.08,.33),exact=True)]
        self.assertFalse(enabled(page,'哈哈哈哈'))

    def test_entry_and_selection_reject_other_pages_or_other_teams(self):
        page=fixture('periodic_setup')
        guard_click(page,entry(page),'du_team_open','哈哈哈哈')
        chosen=fixture('preset_list')
        with self.assertRaises(AutomationError):
            guard_click(chosen,preset(chosen,'追击'),'du_team_select','哈哈哈哈')
        with self.assertRaises(AutomationError):
            entry(chosen)
        with self.assertRaises(AutomationError):
            entry(Scene([]))

    def test_every_launch_reselects_preset_then_verifies_enabled_before_close(self):
        setup=fixture('periodic_setup');listing=fixture('preset_list');active=fixture('preset_enabled')
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.wait.return_value=active
        ctx.differential_universe_close_team.return_value=setup
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(side_effect=[(listing,'team_selection'),(listing,'team_selection'),(active,'team_selection')]*2)
        for _ in range(2):
            result=select(flow,setup)
            self.assertEqual(result[1],'periodic_setup')
        intents=[call.kwargs['intent'] for call in flow._click.call_args_list]
        self.assertEqual(intents,['du_team_open','du_team_tab','du_team_select']*2)
        self.assertEqual(ctx.differential_universe_close_team.call_count,2)
        self.assertEqual(len(flow.report['team_selections']),2)

    def test_periodic_mode_cannot_launch_remembered_normal_setup(self):
        page=fixture('periodic_setup')
        page.tokens=[t for t in page.tokens if '周期演算' not in t.text]
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock()
        with self.assertRaisesRegex(AutomationError,'模式不一致'):
            flow._prepare_and_start(page,'difficulty_setup')
        flow._click.assert_not_called()

    def test_close_waits_for_overlay_animation_without_repeating_escape(self):
        setup=fixture('periodic_setup');active=fixture('preset_enabled')
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.wait.side_effect=[active,setup]
        ctx.differential_universe_close_team.return_value=active
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(side_effect=[(active,'team_selection'),(active,'team_selection')])
        self.assertEqual(select(flow,active)[1],'periodic_setup')
        ctx.differential_universe_close_team.assert_called_once_with(active)

    def test_mode_menu_selects_periodic_and_does_not_touch_normal(self):
        mode=Scene([Token('模式选择',.99,(.04,.04,.15,.09)),
                    Token('常规演算',.99,(.28,.28,.35,.32)),
                    Token('周期演算',.99,(.28,.47,.35,.51))])
        setup=fixture('periodic_setup')
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.wait.return_value=mode
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(side_effect=[(setup,'periodic_setup'),(Scene([]),'mask_choice')])
        flow._select_preset_team=Mock(return_value=(setup,'periodic_setup'))
        self.assertEqual(flow._prepare_and_start(mode,'mode_select')[1],'mask_choice')
        self.assertEqual(flow._click.call_args_list[0].args[1].text,'周期演算')
        self.assertEqual(flow.report['mode'],'周期演算')
        self.assertEqual(flow.report['difficulty_selection']['displayed_rank_after'],5)
