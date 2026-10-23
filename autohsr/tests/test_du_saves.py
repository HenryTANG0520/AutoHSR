import unittest
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

    def test_save_flow_verifies_numbered_name_and_never_overwrites_full_slots(self):
        victory=Scene([t(s,.1,.1) for s in ('探索成功','分析报告','差分宇宙构筑内容','常规演算（13/13）')]
                      +[t('返回主界面',.40,.91),t('记录本次存档',.62,.91)])
        slots=Scene([t('差分宇宙',.08,.04),t('存档管理',.08,.075),t('AutoHSR-1',.06,.20),
                     t('暂无存档',.06,.32),t('暂无存档',.58,.53),t('保存本轮数据',.58,.68)])
        dialog=Scene([t('更改存档名',.50,.38),t('取消',.40,.62),t('确认',.62,.62)])
        named=Scene(dialog.tokens+[t('AutoHSR - 2',.4,.48)])
        saved=Scene([t('差分宇宙',.08,.04),t('存档管理',.08,.075),
                     t('AutoHSR - 2',.06,.32),t('AutoHSR - 2',.35,.12)])
        ctx=Mock(settings=Settings(differential_universe_save=True),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow.report['run_results'].append({})
        pages=iter([slots,slots,dialog,dialog,saved])
        intents=[]
        def click(page,target,**kwargs):
            guard_save_click(page,target,kwargs['du_intent'])
            intents.append(kwargs['du_intent'])
            ctx.last_scene=next(pages)
        ctx.click.side_effect=click
        ctx.wait.side_effect=lambda predicate,**kw:next(p for p in (named,saved) if predicate(p))
        ctx._snapshot_after_du_input.return_value=victory
        flow._save_victory(victory)
        self.assertEqual(flow.report['run_results'][-1]['save_name'],'AutoHSR - 2')
        self.assertEqual(flow.report['run_results'][-1]['save_status'],'saved')
        self.assertEqual(intents,['du_save_open','du_save_slot','du_save_create','du_save_focus','du_save_confirm'])
        ctx.differential_universe_save_name.assert_called_once_with(dialog,'AutoHSR - 2')
        self.assertEqual(classify_page(named),'save_name')
        self.assertEqual(classify_page(saved),'save_management')
        # Full slots cause no slot/create/name input and preserve existing saves.
        full=Scene([v for v in slots.tokens if v.text!='暂无存档'])
        ctx.click.side_effect=lambda *a,**k:setattr(ctx,'last_scene',full)
        ctx.differential_universe_save_name.reset_mock()
        flow._save_victory(victory)
        self.assertEqual(flow.report['run_results'][-1]['save_status'],'skipped_full')
        ctx.differential_universe_save_name.assert_not_called()

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
