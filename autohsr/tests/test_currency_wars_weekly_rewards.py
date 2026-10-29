"""Real reward Runner and Context dispatch with simulated OS, OCR and images."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_weekly_rewards import OPERATION, RewardAction, fuel_limit, kind, next_action, panel_control
from autohsr.currency_wars_weekly_reward_store import RewardStore
from autohsr.models import AutomationError, Scene, Stopped, Token
from autohsr.tests import test_currency_wars_loop as loops
from autohsr.tests import test_currency_wars_points as points
from autohsr.tests import test_currency_wars_navigation as nav

CHECKPOINT=Runner.checkpoint

def panel(current=18000,enabled=True):
    state=nav.points_rewards()
    state.tokens=[Token(t.text,t.score,(.08,.64,.14,.666)) if t.text=='当前积分' else t for t in state.tokens]
    state.tokens.extend((Token(f'{current}/18000',.99,(.08,.68,.23,.71)),
                         Token('一键领取',.99,(.78,.69,.90,.72))))
    state.field_reads['synthetic_reward_button']=enabled
    return paint(state)


def paint(state):
    if state.image is None:
        import numpy as np
        state.image=np.full((1080,1920,3),80,dtype=np.uint8)
    if 'synthetic_reward_button' in state.field_reads:
        enabled=state.field_reads['synthetic_reward_button']
        state.image[round(.67*1080):round(.75*1080),round(.73*1920):round(.95*1920)]=(35,190,235) if enabled else (145,145,145)
    return state


def overlay():
    return Scene([Token('获得物品',.99,(.40,.10,.60,.15)),Token('100',.99,(.43,.48,.49,.51)),
                  Token('点击空白处关闭',.99,(.40,.78,.60,.82))])


def limit():
    return Scene([Token('背包内助燃券持有数量已达上限',.99,(.30,.40,.70,.46)),Token('清理',.99,(.35,.63,.43,.67))])


def stages(current=18000,available=True):
    result=[points.lobby(current) for _ in range(3)]
    result.extend(panel(current,available) for _ in range(2))
    if available:
        result.extend(overlay() for _ in range(2))
        result.extend(panel(current,False) for _ in range(4))
    else:result.extend(panel(current,False) for _ in range(2))
    result.extend(points.lobby(current) for _ in range(2))
    return result


@contextmanager
def runtime(root):
    with loops.real_runtime(root) as window:
        original=Context.snapshot
        def snapshot(c):return paint(original(c))
        with patch.object(Context,'snapshot',snapshot),patch.object(Runner,'checkpoint',CHECKPOINT), \
             patch.object(Context,'sleep',lambda c,seconds:time.sleep(.02)), \
             patch.object(Runner,'wait_for_focus'),patch('autohsr.currency_wars_weekly_reward_run.local_now',return_value=points.NOW), \
             patch('autohsr.currency_wars_weekly_reward_store.local_now',return_value=points.NOW):
            yield window


def runner(states,**kwargs):
    child=Runner(Settings(overlay_logs=False),operation=OPERATION,**kwargs)
    child._loop_test_scenes=states
    return child


class WeeklyRewardTests(unittest.TestCase):
    def test_available_and_disabled_controls_have_distinct_pixel_proof(self):
        self.assertEqual(panel_control(panel())[0],'available')
        self.assertEqual(panel_control(panel(enabled=False))[0],'settled')
        for case in ('missing','duplicate','low','unknown_fill','wrong_page','modal'):
            with self.subTest(case=case):
                state=panel()
                if case=='missing':state.tokens=[t for t in state.tokens if t.text!='一键领取']
                elif case=='duplicate':state.tokens.append(Token('一键领取',.4,(.79,.69,.91,.72)))
                elif case=='low':state.tokens=[Token(t.text,.4,t.box) if t.text=='一键领取' else t for t in state.tokens]
                elif case=='unknown_fill':state.image[:]=5
                elif case=='wrong_page':state=points.lobby(18000)
                else:state.tokens.append(Token('确认购买',.99,(.40,.50,.60,.55)))
                with self.assertRaises(AutomationError):panel_control(state)

    def test_fuel_limit_split_lines_is_separate_from_reward_delivery(self):
        state=Scene([Token('已达上限',.99,(.49,.47,.61,.51)),Token('助燃券',.99,(.42,.40,.50,.44)),
                     Token('背包内',.99,(.30,.40,.41,.44)),Token('持有数量',.99,(.32,.47,.48,.51))])
        self.assertTrue(fuel_limit(state));self.assertEqual(kind(state),'fuel_ticket_limit')
        state.tokens=[Token(t.text,.4,t.box) if t.text=='助燃券' else t for t in state.tokens]
        self.assertFalse(fuel_limit(state))

    def test_missing_button_is_unknown_while_explicit_state_is_local_to_control(self):
        for box,valid in (((.75,.69,.96,.73),True),((.35,.40,.60,.45),False)):
            state=panel();state.tokens=[t for t in state.tokens if t.text!='一键领取']
            state.tokens.append(Token('奖励已全部领取',.99,box))
            if valid:self.assertEqual(panel_control(state)[0],'settled')
            else:
                with self.assertRaises(AutomationError):panel_control(state)

    def test_real_runner_claims_once_closes_once_returns_and_commits_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);child=runner(stages());events=[];child._emit=events.append
            with runtime(root) as window:report=child.run()
            self.assertEqual(report.status,'success',report.error);self.assertTrue(report.report_saved)
            self.assertEqual(window.click.call_count,3);self.assertEqual(window.key.call_count,1)
            self.assertEqual([a['intent'] for a in report.currency_wars['actions']],
                ['open_points_rewards','claim_weekly_rewards','dismiss_weekly_rewards','return_weekly_lobby'])
            self.assertTrue(report.currency_wars['claimed_now']);self.assertTrue(report.currency_wars['weekly_rewards_verified'])
            self.assertFalse(report.currency_wars['completion_verified'])
            store=RewardStore(root/'runs');store.load();store.check_receipt()
            self.assertEqual(len([e for e in events if e['type']=='finished']),1)

    def test_disabled_zero_and_full_points_never_claim_and_do_not_invent_weekly_full(self):
        for score in (0,18000):
            with self.subTest(score=score),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);child=runner(stages(score,False))
                with runtime(root) as window:report=child.run()
                self.assertEqual(report.status,'success',report.error)
                self.assertEqual(window.click.call_count,1);self.assertEqual(window.key.call_count,1)
                self.assertFalse(report.currency_wars['claimed_now']);self.assertTrue(report.currency_wars['rewards_verified'])
                self.assertEqual(report.currency_wars['weekly_rewards_verified'],score==18000)

    def test_fuel_limit_is_verified_rejection_not_delivered_or_repeated_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);states=[points.lobby(18000) for _ in range(3)]+[panel() for _ in range(2)]+[limit(),limit()]
            child=runner(states)
            with runtime(root) as window:report=child.run()
            self.assertEqual(report.status,'partial',report.error);self.assertEqual(window.click.call_count,2)
            self.assertFalse(report.currency_wars['rewards_verified']);self.assertFalse(report.currency_wars['claimed_now'])
            self.assertEqual(report.currency_wars['phase'],'blocked')
            self.assertEqual(report.currency_wars['actions'][-1]['result'],'fuel_ticket_limit')
            self.assertTrue(all(a['status']=='verified' for a in report.currency_wars['actions']))

    def test_unknown_claim_is_preserved_and_resume_denied_before_game(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);states=[points.lobby(18000) for _ in range(3)]+[panel() for _ in range(2)]+[panel() for _ in range(40)]
            with runtime(root) as window:report=runner(states).run()
            self.assertEqual(report.status,'failed');self.assertEqual(window.click.call_count,2)
            self.assertIn('领奖',report.safe_next)
            store=RewardStore(root/'runs');store.load();before=store.path.read_bytes()
            self.assertEqual(store.data['actions'][-1]['status'],'unknown')
            child=runner([],currency_rewards_resume=True)
            with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare:denied=child.run()
            self.assertEqual(denied.status,'failed');prepare.assert_not_called();window.focus.assert_not_called()
            self.assertEqual(store.path.read_bytes(),before)

    def test_unfinished_reward_blocks_other_runners_before_game_preparation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with runtime(root):runner([points.lobby(18000) for _ in range(3)]+[panel() for _ in range(2)]+[limit(),limit()]).run()
            for operation in ('daily','differential_universe','currency_wars_points','currency_wars_standard'):
                with self.subTest(operation=operation):
                    child=Runner(Settings(overlay_logs=False),operation=operation)
                    with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare:report=child.run()
                    self.assertEqual(report.status,'failed');prepare.assert_not_called();window.focus.assert_not_called()

    def test_post_claim_stop_resumes_after_verified_step_without_second_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);child=runner(stages())
            def emit(event):
                if event['type']=='currency_wars' and event['data'].get('phase')=='overlay':child.stop()
            child._emit=emit
            with runtime(root) as window:report=child.run()
            self.assertEqual(report.status,'stopped',report.error);self.assertEqual(window.click.call_count,2)
            states=[overlay()]+[panel(enabled=False) for _ in range(4)]+[points.lobby(18000) for _ in range(2)]
            child=runner(states,currency_rewards_resume=True)
            with runtime(root) as window:report=child.run()
            self.assertEqual(report.status,'success',report.error);self.assertEqual(window.click.call_count,1)
            self.assertEqual(window.key.call_count,1)

    def test_saved_report_failure_can_finalize_readonly_without_game_or_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);child=runner(stages())
            with runtime(root),patch('autohsr.app.replace_file',side_effect=OSError('simulated report failure')):report=child.run()
            self.assertFalse(report.report_saved)
            store=RewardStore(root/'runs');store.load();self.assertEqual(store.data['phase'],'returned')
            original=Path(report.run_dir)/'report.tmp';before=original.read_bytes()
            child=runner([],currency_rewards_resume=True)
            with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare:report=child.run()
            self.assertEqual(report.status,'success',report.error);prepare.assert_not_called();window.focus.assert_not_called()
            self.assertEqual(original.read_bytes(),before)
            store.load();store.check_receipt()

    def test_receipt_write_failure_keeps_failed_original_and_allows_readonly_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);child=runner(stages())
            with runtime(root) as window,patch('autohsr.currency_wars_weekly_reward_store._immutable',side_effect=OSError('receipt write blocked')):
                report=child.run()
            self.assertEqual(report.status,'partial',report.error);self.assertEqual(window.click.call_count,3)
            original=Path(report.run_dir)/'report.json';raw=original.read_bytes()
            self.assertEqual(json.loads(raw)['status'],'partial')
            child=runner([],currency_rewards_resume=True)
            with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare:report=child.run()
            self.assertEqual(report.status,'success',report.error);prepare.assert_not_called();window.focus.assert_not_called()
            self.assertEqual(original.read_bytes(),raw)
            store=RewardStore(root/'runs');store.load();store.check_receipt()

    def test_epoch_change_or_source_write_failure_prevents_claim_input(self):
        for case in ('epoch','write','account','version'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);child=runner(stages())
                with runtime(root) as window:
                    original_input=Context.currency_weekly_reward_input
                    def interrupted(c,scene,choice):
                        if choice.intent=='claim_weekly_rewards':
                            if case=='epoch':c.runner.input_epoch+=1
                            elif case=='account':scene.tokens=[Token(t.text.replace('100000000','100000001'),t.score,t.box) for t in scene.tokens]
                            elif case=='version':(root/'fake-game/config.ini').write_text('[General]\ngame_version=4.7.0\n',encoding='utf-8')
                        return original_input(c,scene,choice)
                    from autohsr import currency_wars_weekly_reward_store as storage
                    original_write=storage._write
                    def write(path,data):
                        if (case=='write' and data.get('actions') and data['actions'][-1]['intent']=='claim_weekly_rewards'
                                and data['actions'][-1]['status']=='pending'):raise OSError('intent blocked')
                        return original_write(path,data)
                    with patch.object(Context,'currency_weekly_reward_input',interrupted),patch.object(storage,'_write',side_effect=write):
                        report=child.run()
                self.assertNotEqual(report.status,'success');self.assertEqual(window.click.call_count,1)
                self.assertFalse(report.currency_wars['rewards_verified'])

    def test_missing_delivery_or_reenabled_button_cannot_count_as_completed_rewards(self):
        for case in ('no_quantity','no_close','button_still_available'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);states=stages()
                if case in ('no_quantity','no_close'):
                    bad=overlay();bad.tokens=[t for t in bad.tokens if t.text!=('100' if case=='no_quantity' else '点击空白处关闭')]
                    states=states[:5]+[deepcopy(bad) for _ in range(40)]
                else:states=states[:7]+[panel() for _ in range(42)]
                with runtime(root) as window:report=runner(states).run()
                self.assertNotEqual(report.status,'success');self.assertFalse(report.currency_wars['rewards_verified'])
                self.assertEqual(sum(a['intent']=='claim_weekly_rewards' for a in report.currency_wars['actions']),1)
                self.assertLessEqual(window.click.call_count,3)

    def test_original_evidence_or_report_changes_block_future_navigation(self):
        for case in ('source','report','receipt'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                with runtime(root):report=runner(stages()).run()
                self.assertEqual(report.status,'success',report.error)
                store=RewardStore(root/'runs');store.load()
                target=(Path(store.data['initial']['evidence']['path']) if case=='source' else
                        Path(report.run_dir)/'report.json' if case=='report' else store.path.parent/'receipt.json')
                target.write_bytes(b'changed')
                child=runner([])
                with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare:report=child.run()
                self.assertEqual(report.status,'failed');prepare.assert_not_called();window.focus.assert_not_called()

    def test_evidence_replay_rejects_forged_state_quantities_or_duplicate_frames(self):
        for case in ('button','quantities','duplicate','complete_flag','confidence','phase','delivery','other_run'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                with runtime(root):report=runner(stages()).run()
                self.assertEqual(report.status,'success',report.error)
                store=RewardStore(root/'runs');store.load()
                if case=='button':store.data['actions'][1]['before']['panel_state']='settled'
                elif case=='quantities':store.data['actions'][1]['after'][0]['quantities']=[999]
                elif case=='duplicate':store.data['actions'][1]['after'][1]=deepcopy(store.data['actions'][1]['after'][0])
                elif case=='complete_flag':store.data['actions']=[]
                elif case=='confidence':store.data['actions'][1]['before']['confidence']=.84
                elif case=='phase':store.data['phase']='overlay'
                elif case=='delivery':store.data['claimed_now']=False
                else:
                    source=store.data['actions'][1]['before'];other=root/'runs/other-attempt';other.mkdir()
                    target=other/'source.png';target.write_bytes(Path(source['path']).read_bytes());source['path']=str(target)
                with self.assertRaises(AutomationError):store.check_evidence()

    def test_verified_return_atomically_persists_flags_before_report_only_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            from autohsr import currency_wars_weekly_reward_store as storage
            original=storage._write
            def interrupted(path,data):
                original(path,data)
                if data.get('phase')=='returned':raise Stopped('simulated process stop after final durable feedback')
            with runtime(root),patch.object(storage,'_write',side_effect=interrupted):report=runner(stages()).run()
            self.assertEqual(report.status,'stopped',report.error)
            store=RewardStore(root/'runs');store.load()
            self.assertEqual(store.data['status'],'complete');self.assertTrue(store.data['rewards_verified'])
            self.assertTrue(store.data['claimed_now']);self.assertEqual(store.data['phase'],'returned')
            child=runner([],currency_rewards_resume=True)
            with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare:report=child.run()
            self.assertEqual(report.status,'success',report.error);prepare.assert_not_called();window.focus.assert_not_called()

    def test_old_week_blocks_input_resume_but_returned_report_recovery_remains_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with runtime(root):report=runner([points.lobby(18000) for _ in range(3)]+[panel() for _ in range(2)]+[limit(),limit()]).run()
            self.assertEqual(report.status,'partial',report.error)
            child=runner([],currency_rewards_resume=True)
            with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare, \
                 patch('autohsr.currency_wars_weekly_reward_store.local_now',return_value=points.NOW+timedelta(days=7)):
                report=child.run()
            self.assertEqual(report.status,'failed');self.assertIn('跨游戏周',report.error)
            prepare.assert_not_called();window.focus.assert_not_called()

    def test_active_standard_game_is_never_left_for_rewards(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);store=loops.StandardSession(root/'runs/currency-standard-session.json');store.begin(root/'old',{})
            before=store.path.read_bytes();child=runner([])
            with runtime(root) as window,patch.object(child,'_prepare_daily_game') as prepare:report=child.run()
            self.assertEqual(report.status,'failed');prepare.assert_not_called();window.focus.assert_not_called()
            self.assertEqual(store.path.read_bytes(),before)

    def test_cli_scope_dispatch_and_no_settings_save(self):
        from autohsr.__main__ import main
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(['--run','--resume-currency-rewards'])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings().save(path);before=path.read_bytes()
            with patch('autohsr.app.Runner') as factory,patch('autohsr.gui.main',side_effect=AssertionError('CLI must not open GUI')), \
                 redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                factory.return_value.run.return_value=dict(status='partial')
                main(['--currency-wars-rewards','--resume-currency-rewards','--config',str(path)])
            self.assertEqual(factory.call_args.kwargs['operation'],OPERATION)
            self.assertIs(factory.call_args.kwargs['currency_rewards_resume'],True);self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
