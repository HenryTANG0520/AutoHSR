import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock,patch
from autohsr.config import Settings
from autohsr.du_saves import empty_slot,next_name,guard_save_click,guard_name
from autohsr.models import Scene,Token,AutomationError,RunReport
from autohsr.differential_universe import DifferentialUniverseWorkflow,classify_page


def t(text,x,y):
    return Token(text,.99,(x-.01,y-.01,x+.01,y+.01))


class DuSaveTests(unittest.TestCase):
    def test_optional_saving_is_off_in_existing_and_default_settings(self):
        self.assertFalse(Settings().differential_universe_save)
        with self.assertRaises(ValueError):
            Settings(differential_universe_save=1).validate('differential_universe')

    def test_names_ignore_spacing_and_advance_past_highest_visible_number(self):
        page=Scene([t('差分宇宙',.08,.04),t('存档管理',.08,.075),
                    t('AutoHSR-1',.06,.20),t('AutoHSR - 3',.06,.32),
                    t('AutoHSR-99',.5,.5),t('暂无存档',.06,.46)])
        self.assertEqual(next_name(page),'AutoHSR - 4')
        self.assertEqual(next_name(Scene([])),'AutoHSR-1')
        self.assertEqual(empty_slot(page),page.tokens[-1])
        guard_save_click(page,page.tokens[-1],'du_save_slot')
        with self.assertRaises(AutomationError):
            guard_save_click(page,page.tokens[2],'du_save_slot')

    def test_create_requires_empty_details_and_confirmation_requires_generated_name(self):
        page=Scene([t('差分宇宙',.08,.04),t('存档管理',.08,.075),
                    t('暂无存档',.58,.53),t('保存本轮数据',.58,.68)])
        guard_save_click(page,page.tokens[-1],'du_save_create')
        page.tokens[2]=t('已有存档',.58,.53)
        with self.assertRaises(AutomationError):
            guard_save_click(page,page.tokens[-1],'du_save_create')
        dialog=Scene([t('更改存档名',.50,.38),t('取消',.40,.62),t('确认',.62,.62)])
        guard_name(dialog,'AutoHSR - 2')
        with self.assertRaises(AutomationError):
            guard_save_click(dialog,dialog.tokens[-1],'du_save_confirm')
        dialog.tokens.append(t('AutoHSR-1',.4,.48))
        guard_save_click(dialog,dialog.tokens[2],'du_save_confirm')
        with self.assertRaises(AutomationError):
            guard_name(dialog,'arbitrary text')

    def test_save_flow_verifies_numbered_name_and_abandons_when_no_empty_slot_is_verified(self):
        # Use the real Flow/Context boundary, rather than a click mock that
        # could bypass durable intent, account checks and the generic-input gate.
        from pathlib import Path
        from autohsr.du_archive_store import preflight
        from autohsr.tests.test_du_archive_workflow import make_context, normal_pages, scene
        for no_empty in (False, True):
            with self.subTest(no_empty=no_empty), tempfile.TemporaryDirectory() as folder:
                prototype = scene('victory')
                home = Scene([t('差分宇宙',.08,.04),t('乐园漫记',.5,.3),t('开始游戏',.8,.9)],
                             prototype.image.copy(),prototype.geometry)
                pending, ctx, first = make_context(folder, normal_pages(no_empty=no_empty)+[home])
                entry = dict(pending.report['run_results'][-1])
                flow = DifferentialUniverseWorkflow(ctx, 1, resume_active=True)
                flow.report['current_run'] = 1
                flow.report['run_results'].append(entry)
                result, kind, victory = flow._progress_run(first, 'victory')
                self.assertTrue(victory)
                self.assertEqual(kind, 'home')
                self.assertIs(result, ctx.last_scene)
                record = preflight(folder)
                self.assertEqual(record['run_id'], entry['run_id'])
                self.assertTrue(record['return_verified'])
                self.assertEqual(flow.report['completed_runs'], 0)
                if no_empty:
                    self.assertEqual(entry['save_status'], 'no_verified_empty_slot')
                    self.assertEqual(ctx.window.click.call_count, 2)  # Open, then final victory return.
                    ctx.window.type_du_save_name.assert_not_called()
                else:
                    self.assertEqual(entry['save_name'], 'AutoHSR - 2')
                    self.assertEqual(entry['save_status'], 'saved')
                    self.assertTrue(Path(entry['save_evidence']).is_file())
                    self.assertEqual(ctx.window.click.call_count, 6)
                    ctx.window.type_du_save_name.assert_called_once()
                    self.assertEqual(ctx.window.type_du_save_name.call_args.args[0], 'AutoHSR - 2')
                self.assertEqual(classify_page(scene('named')), 'save_name')
                self.assertEqual(classify_page(scene('saved')), 'save_management')

    def test_default_off_returns_from_victory_without_opening_archive(self):
        victory=Scene([t(s,.1,.1) for s in ('探索成功','分析报告','差分宇宙构筑内容','周期演算（13/13）')]
                      +[t('返回主界面',.40,.91),t('记录本次存档',.62,.91)])
        home=Scene([t('差分宇宙',.08,.04),t('乐园漫记',.5,.3),t('开始游戏',.8,.9)])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow.report['run_results'].append({})
        flow._save_victory=Mock(side_effect=AssertionError('saving defaults off'))
        flow._click=Mock(return_value=(home,'home'))
        self.assertTrue(flow._progress_run(victory,'victory')[2])
        self.assertEqual(flow._click.call_args.args[1].text,'返回主界面')

    def test_name_input_releases_select_all_when_native_send_fails(self):
        from autohsr.windows import GameWindow,Geometry
        window=SimpleNamespace(send=Mock(side_effect=AutomationError('interrupted')))
        with patch('autohsr.windows.user32.SendInput',return_value=2) as release:
            with self.assertRaises(AutomationError):
                GameWindow.type_du_save_name(window,'AutoHSR-1',Geometry(0,0,1920,1080),checkpoint=Mock())
        self.assertEqual(release.call_args.args[0],2)
