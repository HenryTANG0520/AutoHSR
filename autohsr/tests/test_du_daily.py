import json
from datetime import datetime,timezone
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from autohsr.config import Settings
from autohsr.du_daily import CHINA,DayJournal,account_key,game_day,after_win,_farm
from autohsr.models import AutomationError,InputInterrupted,RunReport,Scene,TaskResult,Token


def page():
    return Scene([Token('差分宇宙',.99,(.03,.03,.15,.08)),
                  Token('乐园漫记',.99,(.03,.10,.15,.15)),
                  Token('开始游戏',.99,(.75,.87,.90,.93)),
                  Token('UID:123456789',.99,(.01,.965,.20,.99))])


class DailyInterludeTests(unittest.TestCase):
    def flow(self):
        return SimpleNamespace(settings=Settings(differential_universe_daily=True),
            ctx=Mock(),_persist_ledger=Mock(),_open_differential_universe=Mock(return_value=(page(),'home')),
            report=dict(completed_runs=1,run_results=[dict(status='completed',run_id='verified-run',
                victory_evidence='victory',return_evidence='return')]))

    def free_context(self,folder):
        folder.mkdir(parents=True,exist_ok=True)
        return SimpleNamespace(report=RunReport(run_dir=str(folder)),wait=Mock())

    def test_game_day_resets_at_china_four_am_not_midnight_or_utc(self):
        self.assertEqual(game_day(datetime(2026,10,23,3,59,tzinfo=CHINA)),'2026-10-22')
        self.assertEqual(game_day(datetime(2026,10,23,4,0,tzinfo=CHINA)),'2026-10-23')
        self.assertEqual(game_day(datetime(2026,10,22,20,0,tzinfo=timezone.utc)),'2026-10-23')
        with self.assertRaises(ValueError):
            game_day(datetime(2026,10,23))

    def test_marker_is_per_account_durable_before_work_and_never_replays_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            key=account_key(page())
            self.assertNotIn('123456789',key)
            marker=DayJournal(directory,key,'2026-10-23')
            self.assertTrue(marker.begin('test-run'))
            with self.assertRaisesRegex(AutomationError,'中断记录'):
                DayJournal(directory,key,'2026-10-23').begin('another-run')
            marker.save(status='failed')
            with self.assertRaises(AutomationError):
                DayJournal(directory,key,'2026-10-23').begin('third-run')
            marker.save(status='complete')
            self.assertFalse(DayJournal(directory,key,'2026-10-23').begin('fourth-run'))
            self.assertTrue(DayJournal(directory,key,'2026-10-24').begin('next-day'))
            self.assertTrue(DayJournal(directory,'different-account','2026-10-23').begin('other-account'))
            marker.path.write_text('{broken',encoding='utf8')
            with self.assertRaises(AutomationError):
                DayJournal(directory,key,'2026-10-23').begin('corrupt')

    def test_off_is_noop_and_on_requires_success_and_same_day_skips_all_input(self):
        flow=SimpleNamespace(settings=Settings(),ctx=Mock(),report={})
        scene=page()
        self.assertEqual(after_win(flow,scene,'home'),(scene,'home'))
        flow.ctx.key.assert_not_called()
        flow.settings.differential_universe_daily=True
        with self.assertRaisesRegex(AutomationError,'胜利和返回'):
            after_win(flow,scene,'home')
        flow.report['run_results']=[dict(status='completed',victory_evidence='victory',return_evidence='return')]
        with tempfile.TemporaryDirectory() as directory:
            now=datetime(2026,10,23,9,tzinfo=CHINA)
            marker=DayJournal(directory,account_key(scene),game_day(now))
            marker.begin('prior');marker.save(status='complete')
            self.assertEqual(after_win(flow,scene,'home',root=directory,now=now),(scene,'home'))
            flow.ctx.key.assert_not_called()

    def test_farming_freezes_initial_resources_and_splits_over_240_into_unique_bills(self):
        with tempfile.TemporaryDirectory() as directory:
            state=dict(stamina=300,tokens=4)
            marker=DayJournal(directory,account_key(page()),'2026-10-23');marker.begin('run')
            reports=[]
            def context(flow,folder,settings,day):
                folder.mkdir(parents=True)
                result=SimpleNamespace(settings=settings,report=RunReport(run_dir=str(folder)),battle_budget=None)
                result.runner=SimpleNamespace(report=result.report,checkpoint=Mock(),log=Mock())
                reports.append(result)
                return result
            class Battle:
                def __init__(self,context): self.ctx=context
                def battle(self):
                    count=self.ctx.settings.challenge_count
                    tokens=min(count,state['tokens']);stamina=(count-tokens)*40
                    self.ctx.battle_budget.reserve(stamina,immersifiers=tokens)
                    self.ctx.report.battle_completed=count
                    self.ctx.battle_budget.confirm(stamina,immersifiers=tokens)
                    state['stamina']-=stamina;state['tokens']-=tokens
                    if len(reports)==1: state['stamina']+=40  # Regeneration must not extend the plan.
                    return TaskResult('battle','ok','verified')
            initial=SimpleNamespace(_open_calyx=Mock(return_value=page()),
                _disable_quick_refill=lambda s:s,_available=lambda s:state['stamina'],
                ctx=SimpleNamespace(evidence=Mock(return_value='preparation')))
            flow=SimpleNamespace(ctx=Mock())
            with patch('autohsr.planar_resources.inventory',side_effect=lambda _:state['tokens']), \
                 patch('autohsr.recovery.recovery_state',return_value={'pending':0,'corrupt':False,'blocked':False}), \
                 patch('autohsr.du_daily._context',side_effect=context), \
                 patch('autohsr.workflows.DailyWorkflow',Battle):
                _farm(flow,marker,initial,Settings(dungeon_category='planar',differential_universe_daily=True))
            self.assertEqual([v.report.battle_completed for v in reports],[6,5])
            self.assertEqual(sum(v.report.stamina_spent for v in reports),280)
            self.assertEqual(sum(v.report.immersifiers_spent for v in reports),4)
            self.assertEqual(state,dict(stamina=60,tokens=0))
            self.assertEqual(marker.data['planned_challenges'],11)
            for report in reports:
                bill=json.loads((Path(report.report.run_dir)/'battle-session.json').read_text('utf8'))
                self.assertEqual(bill['status'],'success')
                self.assertEqual((bill['pending'],bill['immersifiers_pending']),(0,0))

    def test_unknown_previous_payment_blocks_before_opening_dungeon(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=DayJournal(directory,'account','2026-10-23');marker.begin('run')
            initial=Mock()
            with patch('autohsr.recovery.recovery_state',return_value={'pending':0,'immersifiers_pending':2}):
                with self.assertRaisesRegex(AutomationError,'未核对'):
                    _farm(SimpleNamespace(ctx=Mock()),marker,initial,Settings())
            initial._open_calyx.assert_not_called()

    def test_no_resources_never_starts_a_battle(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=DayJournal(directory,account_key(page()),'2026-10-23');marker.begin('run')
            initial=SimpleNamespace(_open_calyx=lambda:page(),_disable_quick_refill=lambda s:s,
                _available=lambda s:24,ctx=SimpleNamespace(evidence=Mock(return_value='preparation')))
            with patch('autohsr.planar_resources.inventory',return_value=0), \
                 patch('autohsr.recovery.recovery_state',return_value={'pending':0,'corrupt':False}), \
                 patch('autohsr.du_daily._context') as context:
                _farm(SimpleNamespace(ctx=Mock()),marker,initial,Settings())
            context.assert_not_called()
            self.assertEqual(marker.data['farming_status'],'insufficient_resources')

    def test_interlude_failure_preserves_win_and_same_day_never_replays_spending(self):
        with tempfile.TemporaryDirectory() as directory:
            flow=self.flow();now=datetime(2026,10,23,9,tzinfo=CHINA)
            daily=self.free_context(Path(directory)/'free')
            with patch('autohsr.du_daily._context',return_value=daily), \
                 patch('autohsr.workflows.DailyWorkflow',return_value=Mock()), \
                 patch('autohsr.du_daily._free_task'), \
                 patch('autohsr.du_daily._farm',side_effect=AutomationError('receipt missing')) as farm:
                with self.assertRaisesRegex(AutomationError,'receipt missing'):
                    after_win(flow,page(),'home',root=directory,now=now)
                with self.assertRaisesRegex(AutomationError,'中断记录'):
                    after_win(flow,page(),'home',root=directory,now=now)
                farm.assert_called_once()
            self.assertEqual(flow.report['completed_runs'],1)
            self.assertEqual(flow.report['run_results'][0]['status'],'completed')
            self.assertEqual(flow.report['daily_interludes'][0]['status'],'failed')
            flow._open_differential_universe.assert_not_called()

    def test_focus_retry_reads_the_daily_bill_instead_of_du_zero_budget(self):
        from autohsr.du_daily import _step
        report=RunReport(immersifiers_pending=2)
        runner=SimpleNamespace(report=report,checkpoint=Mock(),log=Mock())
        action=Mock(side_effect=[InputInterrupted('focus'),TaskResult('battle','ok','done')])
        with self.assertRaisesRegex(AutomationError,'消耗待核对'):
            _step(SimpleNamespace(runner=runner),action,'battle')
        self.assertEqual(action.call_count,1)
        report.immersifiers_pending=0
        action=Mock(side_effect=[InputInterrupted('focus'),TaskResult('battle','ok','done')])
        self.assertEqual(_step(SimpleNamespace(runner=runner),action,'battle').status,'ok')
        self.assertEqual(action.call_count,2)

    def test_complete_interlude_returns_to_du_and_next_win_skips_all_daily_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            flow=self.flow();now=datetime(2026,10,23,9,tzinfo=CHINA)
            daily=self.free_context(Path(directory)/'free')
            def free_task(journal,workflow,name,**kwargs):
                if name=='daily': daily.report.daily_verified=True
                journal.data['free_tasks'].append({'task':name,'status':'ok'})
            with patch('autohsr.du_daily._context',return_value=daily), \
                 patch('autohsr.workflows.DailyWorkflow',return_value=Mock()), \
                 patch('autohsr.du_daily._free_task',side_effect=free_task) as free, \
                 patch('autohsr.du_daily._farm') as farm, \
                 patch('autohsr.differential_universe.classify_page',return_value='phone'):
                self.assertEqual(after_win(flow,page(),'home',root=directory,now=now)[1],'home')
                flow.ctx.key.assert_called_once_with('esc')
                self.assertEqual(free.call_count,5)
                self.assertEqual(flow.report['daily_interludes'][0]['status'],'complete')
                after_win(flow,page(),'home',root=directory,now=now)
                farm.assert_called_once()
                self.assertEqual(free.call_count,5)
            self.assertEqual(flow.report['completed_runs'],1)
