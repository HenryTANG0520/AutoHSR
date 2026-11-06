"""Station rerolls through the DU workflow, Context and fake Win32."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow, classify_page
from autohsr.du_station_reroll import CONFIRM, LEDGER, REQUEST, retention_confirmation, station_round
from autohsr.models import AutomationError, RunReport, Scene, Token
from autohsr.policy import guard_differential_universe_click
from autohsr.weekly_plan import CHINA


GEO = windows.Geometry(0, 0, 960, 540)
WEEK = datetime(2026, 11, 2, 4, 30, tzinfo=CHINA)
OLD = ('事件', '铸造', '空白')
NEW = ('精英', '事件', '铸造')
UID = Token('UID:100000000', .99, (.012, .960, .142, .986))


def station(count=2, names=OLD, *, gray=False, selected=False):
    image = np.full((540, 960, 3), (72, 75, 78), np.uint8)
    image[469:497, 281:465] = (111, 98, 44) if gray else 245
    if selected:
        image[469:497, 488:668] = (61, 235, 232)
    tokens = [UID, Token('差分宇宙', .99, (.050, .029, .106, .053)),
              Token('选择下一站', .99, (.052, .060, .118, .089)),
              Token('选择一张站点卡', .99, (.427, .232, .580, .266)),
              Token('确定', .99, (.585, .881, .616, .913)),
              Token(f'重抽{count}', .99, (.361, .881, .410, .913))]
    for left, name in zip((292, 421, 556), names):
        image[218:403, left:left+116] = 240
        tokens.append(Token(name, .99, (left/960+.082, .681, left/960+.113, .716)))
    return Scene(tokens, image, GEO)


def dialog(body='部分区域会被保留，是否继续？'):
    image = np.full((540, 960, 3), (47, 57, 67), np.uint8)
    image[181:313, 240:720] = 232
    image[326:352, 286:466] = 240
    image[326:352, 495:677] = 240
    return Scene([UID, Token('提示', .99, (.480,.362,.520,.404)),
                  Token(body,.99,(.412,.475,.585,.502)), Token('取消',.99,(.366,.606,.417,.640)),
                  Token('确认',.99,(.583,.602,.634,.640))], image, GEO)


class ReachedStation(Exception):
    pass


@contextmanager
def harness(directory, frames, *, enabled=True, resume=False, disabled=OLD):
    runner = SimpleNamespace(settings=Settings(differential_universe_station_custom=True,
        differential_universe_station_disabled=list(disabled), differential_universe_station_reroll=enabled),
        report=RunReport(operation='differential_universe', run_dir=str(directory)), input_epoch=0,
        inactive_duration=0, stop_requested=False, checkpoint=Mock(), log=Mock())
    game = windows.GameWindow.__new__(windows.GameWindow)
    game.hwnd = 53
    vision = Mock()
    context = Context(runner, game, vision)
    now, wall, latest, pending = 100., [WEEK], None, iter(frames)

    def capture():
        nonlocal latest
        scene = next(pending, None)
        if scene is None:
            raise AssertionError('fake capture sequence exhausted')
        latest = replace(scene, tokens=list(scene.tokens), image=scene.image.copy())
        return latest.image, GEO

    def sleep(seconds):
        nonlocal now
        now += seconds

    game.capture = capture
    context.sleep = sleep
    vision.read.side_effect = lambda *_: latest
    user32 = Mock()
    user32.IsWindow.return_value = 1
    user32.IsIconic.return_value = 0
    user32.GetForegroundWindow.return_value = 53
    user32.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__
    user32.GetAsyncKeyState.return_value = 0
    user32.SendInput.side_effect = lambda count, *_: count
    clock = SimpleNamespace(monotonic=lambda: now, time=lambda: wall[0].timestamp())
    with (patch.object(windows, 'user32', user32), patch.object(windows, 'geometry', return_value=GEO),
          patch('autohsr.app.time', clock), patch('autohsr.differential_universe.time', clock),
          patch('autohsr.du_station_reroll.time', clock),
          patch('autohsr.currency_wars_points.local_now', side_effect=lambda: wall[0])):
        flow = DifferentialUniverseWorkflow(context, 1, resume_active=resume)
        flow.report['current_run'] = 1
        first = str(context.evidence(station(), 'first_station'))
        flow.report['run_results'].append(dict(run=1, run_id='run-one', origin='fresh', status='running',
            mode='周期演算', started_at=WEEK.timestamp(), difficulty_verified=True,
            difficulty_rank=5, difficulty_evidence=dict(verified=True, requested_rank=5, displayed_rank_after=5),
            started_page='station_choice', started_evidence=first))
        flow.report['page_history'].append(dict(run=1, page_kind='station_choice', evidence=first))
        flow.report['actions'].append(dict(index=1, run=1, intent='periodic_start', status='sent',
            action='启动「差分宇宙」', after_page='station_choice', after_evidence=first))
        flow._action_no = 1
        flow._persist_ledger()
        yield flow, user32, wall


class StationRerollFlowTests(unittest.TestCase):
    def run_flow(self, flow):
        scene = flow.ctx.snapshot()
        return flow._progress_run(scene, classify_page(scene, flow.ctx))

    def records(self, directory):
        return json.loads((Path(directory)/LEDGER).read_text(encoding='utf-8'))['actions'][1:]

    def test_scope_and_receipt_return_to_normal_allowed_selection(self):
        pages = [station(), station(), dialog(), dialog(), station(1, NEW), station(1, NEW)]
        with tempfile.TemporaryDirectory() as directory, harness(directory, pages) as (flow, native, _):
            def send(count, *_):
                self.assertFalse(flow.ctx.last_scene.image.flags.writeable)
                if os.name == 'nt':
                    original = self.records(directory)[-1]['source_frames'][-1]['path']
                    for path in (Path(directory)/LEDGER, Path(original)):
                        with self.assertRaises(PermissionError), path.open('r+b'):
                            pass
                return count
            native.SendInput.side_effect = send
            with patch.object(flow, '_click', side_effect=ReachedStation) as next_click, self.assertRaises(ReachedStation):
                self.run_flow(flow)
            self.assertEqual(next_click.call_args.args[1].text, '精英')
            self.assertEqual([call.args[0] for call in native.SendInput.call_args_list], [3,3])
            requested, confirmed = self.records(directory)
            self.assertEqual((requested['intent'], confirmed['intent'], confirmed['request_index']),
                             (REQUEST, CONFIRM, requested['index']))
            self.assertEqual((requested['status'], confirmed['status'], confirmed['feedback_status']),
                             ('sent', 'sent', 'verified'))
            self.assertEqual((confirmed['station_count'], confirmed['station_count_after']), (2,1))
            self.assertEqual(confirmed['station_cards_after'], list(NEW))
            self.assertEqual(len({item['path'] for item in confirmed['feedback_frames']}), 2)

    def test_wrong_prompt_or_bad_decrement_is_not_completed(self):
        for wrong in ('different_modal', 'same_count', 'same_cards', 'drop_two'):
            with self.subTest(wrong=wrong), tempfile.TemporaryDirectory() as directory:
                modal = dialog('是否消耗288宇宙碎片，购买所选祝福？') if wrong=='different_modal' else dialog()
                result = {'same_count': station(2, NEW), 'same_cards': station(1, OLD),
                          'drop_two': station(0, NEW)}.get(wrong, modal)
                pages = [station(), station(), modal, modal]+[result]*16
                with harness(directory, pages) as (flow, native, _), self.assertRaisesRegex(AutomationError, '双帧'):
                    self.run_flow(flow)
                records = self.records(directory)
                self.assertEqual(len(records), 1 if wrong=='different_modal' else 2)
                self.assertEqual(native.SendInput.call_count, len(records))
                self.assertTrue(all(item['feedback_status']=='unverified' for item in records))

    def test_no_request_with_gray_zero_unknown_or_unapproved_scope(self):
        incomplete = station()
        incomplete.tokens = [t for t in incomplete.tokens if t.text != '空白']
        for page, enabled, resume in ((station(gray=True),True,False), (station(0),True,False),
                                      (station(0, gray=True),True,False),
                                      (station(selected=True),True,False), (incomplete,True,False),
                                      (station(),False,False), (station(),True,True)):
            with self.subTest(enabled=enabled,resume=resume,page=page.tokens), tempfile.TemporaryDirectory() as directory:
                with harness(directory, [page], enabled=enabled, resume=resume) as (flow, native, _):
                    with self.assertRaises(AutomationError):
                        self.run_flow(flow)
                native.SendInput.assert_not_called()
                self.assertEqual(self.records(directory), [])

    def test_final_use_accepts_only_the_true_dark_zero_with_new_complete_cards(self):
        old = [station(1), station(1)]
        fresh = [station(0, ('事件','事件','精英'), gray=True) for _ in range(2)]
        self.assertEqual(station_round(fresh[0]).count, 0)
        self.assertIsNone(station_round(fresh[0]).target)
        pages = [*old, dialog(), dialog(), *fresh]
        with tempfile.TemporaryDirectory() as directory, harness(directory,pages) as (flow,native,_):
            with patch.object(flow,'_click',side_effect=ReachedStation), self.assertRaises(ReachedStation):
                self.run_flow(flow)
            self.assertEqual(native.SendInput.call_count,2)
            self.assertEqual(self.records(directory)[-1]['station_count_after'],0)

    def test_an_unknown_request_is_never_sent_a_second_time(self):
        pages = [station(),station()]+[dialog('当前无法重抽')]*16+[station()]
        with tempfile.TemporaryDirectory() as directory, harness(directory,pages) as (flow,native,_):
            with self.assertRaisesRegex(AutomationError,'双帧'):
                self.run_flow(flow)
            with self.assertRaisesRegex(AutomationError,'至多尝试一次'):
                self.run_flow(flow)
            native.SendInput.assert_called_once()
            self.assertEqual(len(self.records(directory)),1)

    def test_a_complete_weak_other_account_stops_after_the_request(self):
        other = dialog()
        other.tokens = [Token('UID:100000001',.74,t.box) if t is UID else t for t in other.tokens]
        with tempfile.TemporaryDirectory() as directory, harness(directory,[station(),station(),other]) as (flow,native,_):
            with self.assertRaisesRegex(AutomationError,'账号已改变'):
                self.run_flow(flow)
            native.SendInput.assert_called_once()
            self.assertEqual(self.records(directory)[-1]['feedback_status'],'unverified')

    def test_native_confirmation_is_vetoed_by_late_epoch_week_focus_and_f10(self):
        for fault in ('epoch','week','focus','f10'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                with harness(directory, [station(),station(),dialog(),dialog()]) as (flow, native, wall):
                    def emergency(_key):
                        if native.GetAsyncKeyState.call_count == 3 and fault=='focus':
                            native.GetForegroundWindow.return_value = 54
                        if native.GetAsyncKeyState.call_count == 4:
                            if fault=='epoch':
                                flow.ctx.runner.input_epoch += 1
                            elif fault=='week':
                                wall[0] += timedelta(days=7)
                            else:
                                return 0x8000
                        return 0
                    native.GetAsyncKeyState.side_effect = emergency
                    with self.assertRaises(AutomationError):
                        self.run_flow(flow)
                native.SendInput.assert_called_once()
                self.assertEqual([row['status'] for row in self.records(directory)], ['sent','not_sent'])

    def test_partial_native_submit_and_late_receipt_stop_keep_unverified(self):
        for fault in ('partial','receipt_f10'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                pages=[station(),station(),dialog(),dialog(),station(1,NEW),station(1,NEW)]
                with harness(directory,pages) as (flow,native,_):
                    if fault=='partial':
                        native.SendInput.side_effect=[3,2]
                    else:
                        native.GetAsyncKeyState.side_effect=[0,0,0,0,0x8000]
                    with self.assertRaises(AutomationError):
                        self.run_flow(flow)
                self.assertEqual(native.SendInput.call_count,2)
                record=self.records(directory)[-1]
                self.assertEqual(record['status'],'unknown' if fault=='partial' else 'sent')
                self.assertEqual(record['feedback_status'],'unverified')
                self.assertNotIn('feedback_frames',record)

    def test_confirm_cannot_borrow_a_replaced_request_image(self):
        pages = [station(),station(),dialog(),dialog()]
        with tempfile.TemporaryDirectory() as directory, harness(directory,pages) as (flow,native,_):
            def boundary(_key):
                if native.GetAsyncKeyState.call_count == 3:
                    original = Path(self.records(directory)[0]['source_frames'][0]['path'])
                    original.write_bytes(original.read_bytes() + b'changed bytes')
                return 0
            native.GetAsyncKeyState.side_effect = boundary
            with self.assertRaisesRegex(AutomationError,'原始画面已改变'):
                self.run_flow(flow)
            native.SendInput.assert_called_once()
            self.assertEqual([item['status'] for item in self.records(directory)],['sent','not_sent'])

    def test_generic_confirm_and_current_wrong_modal_are_never_authorized(self):
        scene = dialog()
        self.assertIsNotNone(retention_confirmation(scene))
        self.assertEqual(classify_page(scene), 'station_reroll_prompt')
        with self.assertRaisesRegex(AutomationError, '专用确认'):
            guard_differential_universe_click(scene, scene.find('确认', exact=True))
        self.assertIsNone(retention_confirmation(dialog('部分区域会被保留，是否使用1枚燃料？')))
        self.assertIsNone(station_round(replace(station(), image=None)))

    def test_cli_opt_in_preserves_saved_custom_and_disabled_without_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'config.json'
            Settings(weekly_enabled=True, differential_universe_station_custom=True,
                     differential_universe_station_disabled=list(OLD)).save(config)
            original = config.read_bytes()
            args = ['--differential-universe','--config',str(config),'--du-station-reroll']
            with (patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO())):
                runner.return_value.run.return_value = RunReport(status='success')
                self.assertEqual(main(args),0)
                settings = runner.call_args.args[0]
                self.assertTrue(settings.differential_universe_station_reroll)
                self.assertTrue(settings.differential_universe_station_custom)
                self.assertEqual(settings.differential_universe_station_disabled,list(OLD))
                runner.reset_mock()
                self.assertEqual(main([*args,'--resume-active-du']),2)
                self.assertEqual(main([*args,'--du-mode','normal']),2)
                runner.assert_not_called()
            with (patch('autohsr.plan_runner.PlanRunner') as plan, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO())):
                plan.return_value.run.return_value = RunReport(status='success')
                self.assertEqual(main(['--plan','--config',str(config),'--du-station-reroll']),0)
                self.assertTrue(plan.call_args.args[0].differential_universe_station_reroll)
            self.assertEqual(config.read_bytes(),original)
