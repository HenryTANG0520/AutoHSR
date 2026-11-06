"""Observed-score grammar, weekly boundaries and the real reporting lifecycle."""
from contextlib import redirect_stderr,redirect_stdout
from copy import deepcopy
from datetime import datetime
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import numpy as np
from PIL import Image

from autohsr.app import Context,Runner
from autohsr.config import Settings
from autohsr.currency_wars_defeat import archive_proof
from autohsr.currency_wars_identity import account_key
from autohsr.currency_wars_loop_store import LoopStore
from autohsr.currency_wars_navigation import next_action
from autohsr.currency_wars_points import game_week,period_evidence,proof_tokens,read_points
from autohsr.currency_wars_points_run import OPERATION,latest,require_no_active_match,validate_observation
from autohsr.currency_wars_replay import save_sample
from autohsr.currency_wars_session import StandardSession
from autohsr.models import AutomationError,Scene,Token
from autohsr.weekly_plan import CHINA
from autohsr.tests import test_currency_wars_defeat as defeat_helpers
from autohsr.tests import test_currency_wars_loop as loop_helpers
from autohsr.tests import test_currency_wars_navigation as nav
from autohsr.tests import test_currency_wars_standard as ranks
from autohsr.tests.test_currency_wars_node import screen

NOW=datetime(2026,10,26,10,tzinfo=CHINA)


def lobby(current=0,timer='6天18小时'):
    state=nav.lobby()
    state.tokens.extend((Token('积分',.99,(.18,.875,.22,.902)),
        Token(f'{current}/18000',.99,(.08,.908,.22,.939)),
        Token('本期剩余时间：'+timer,.99,(.035,.84,.25,.864))))
    return state


def runner(states):
    result=Runner(Settings(overlay_logs=False),operation=OPERATION)
    result._loop_test_scenes=states
    return result


class PointsTests(unittest.TestCase):
    def _settled_defeat(self, root):
        runs = root / 'runs'
        runs.mkdir(exist_ok=True)
        factory = defeat_helpers.ActualFactory(root, ['defeat'])
        child = factory(Settings(overlay_logs=False), None, operation='currency_wars_standard',
                        currency_loop_guard=None)
        child._loop_test_account = '100000000'
        session_path = runs / 'currency-standard-session.json'
        seeded = StandardSession(session_path)
        start = Path(seeded.data['actions'][0]['before'])
        with Image.open(start) as image:
            scene = Scene([Token('UID:' + child._loop_test_account, .99, (.01, .96, .10, .99))],
                          image=np.asarray(image))
            save_sample(scene, start, stage='entry')
        with loop_helpers.real_runtime(root) as window, \
             patch('autohsr.currency_wars_replay.save_sample', save_sample):
            report = child.run()
        self.assertEqual(report.status, 'partial', report.error)
        self.assertTrue(report.report_saved)
        self.assertEqual(window.click.call_count, 4)
        store = StandardSession(session_path)
        self.assertTrue(defeat_helpers.settled(store.data))
        self.assertEqual(store.data['match_outcome'], 'defeat')
        self.assertIs(store.data['node_attempt']['node_verified'], False)
        self.assertIs(store.data['completion_verified'], False)
        self.assertEqual(store.data['rules_version'], '4.6')
        self.assertEqual(store.data['client']['version'], '4.6')
        return store, Path(report.run_dir) / 'report.json'

    def _assert_independent_entries_blocked(self, root):
        from autohsr.currency_wars_weekly_rewards import OPERATION as REWARDS_OPERATION

        for operation in (OPERATION, REWARDS_OPERATION):
            with self.subTest(operation=operation), loop_helpers.real_runtime(root) as window, \
                 patch('autohsr.app.find_game', return_value=window) as find:
                child = Runner(Settings(overlay_logs=False), operation=operation)
                child._loop_test_scenes = []
                self.assertEqual(child.run().status, 'failed')
                find.assert_not_called()
                window.click.assert_not_called()
                window.key.assert_not_called()
        self.assertFalse(list((root / 'runs').glob('currency-points/*/*/*.json')))
        self.assertFalse((root / 'runs' / 'currency-weekly-rewards-current.json').exists())

    def test_exact_redacted_old_ocr_pages_have_separate_zero_and_full_results(self):
        fixture=json.loads((Path(__file__).parent/'fixtures/currency_wars_points.json').read_text(encoding='utf-8'))
        self.assertIs(fixture['independent_acceptance'],False)
        for name,data in fixture['pages'].items():
            with self.subTest(name=name):
                state=Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in data['tokens']])
                points=read_points(state)
                self.assertEqual((points.current,points.limit,points.page),(data['current'],18000,data['expected_page']))
                self.assertEqual(points.complete,data['current']==18000)
                self.assertEqual(proof_tokens(state,points.page),data['tokens'])
                self.assertNotIn('uid',json.dumps(data['tokens']).casefold())

    def test_one_two_three_fields_and_formatted_unicode_numbers(self):
        variants=[('18000/18000',),('18000/','18000'),('18000','/18000'),('18000','/','18000'),
                  ('１８，０００／１８，０００',),('12,600','/','18,000')]
        for parts in variants:
            with self.subTest(parts=parts):
                state=lobby();state.tokens=[t for t in state.tokens if '/' not in t.text]
                for index,text in enumerate(parts):
                    x=.05+index*.065;state.tokens.append(Token(text,.99,(x,.909,x+.06,.938)))
                points=read_points(state)
                self.assertEqual(points.current,12600 if parts[0]=='12,600' else 18000)

    def test_ambiguous_low_confidence_clipped_and_wrong_relation_do_not_become_zero_or_full(self):
        for case in ('missing','duplicate','low_conflict','clipped','row','gap','bad_cap','too_high','syntax','other_number'):
            with self.subTest(case=case):
                state=lobby();index=next(i for i,t in enumerate(state.tokens) if t.text=='0/18000')
                if case=='missing':state.tokens.pop(index)
                elif case in ('duplicate','low_conflict','other_number'):
                    state.tokens.append(Token('18000/18000' if case!='other_number' else '1800',.50 if case=='low_conflict' else .99,(.08,.909,.22,.939)))
                elif case=='clipped':state.tokens[index]=Token('0/18000',.99,(.01,.909,.22,.939))
                elif case in ('row','gap'):
                    state.tokens[index:index+1]=[Token('0/',.99,(.04,.903,.08,.925)),
                        Token('18000',.99,(.085 if case=='row' else .18,.923 if case=='row' else .903,.23,.944))]
                else:state.tokens[index]=Token(dict(bad_cap='0/24000',too_high='20000/18000',syntax='O/18000')[case],.99,(.08,.909,.22,.939))
                with self.assertRaises(AutomationError):read_points(state)

    def test_guides_tutorials_and_other_counts_cannot_stand_in_for_current_score(self):
        for state in (nav.universe(True),nav.mode(True),screen('battle')):
            state.tokens.append(Token('18000/18000',.99,(.08,.908,.22,.939)))
            with self.assertRaises(AutomationError):read_points(state)
        state=lobby();state.tokens=[t for t in state.tokens if t.text!='0/18000']
        state.tokens.append(Token('18000',.99,(.88,.53,.92,.56)))
        with self.assertRaises(AutomationError):read_points(state)

    def test_countdown_precision_splitting_and_calendar_boundary(self):
        self.assertEqual(game_week(datetime(2026,10,26,3,59,tzinfo=CHINA)),'2026-10-19')
        self.assertEqual(game_week(datetime(2026,10,26,4,tzinfo=CHINA)),'2026-10-26')
        self.assertIs(period_evidence(lobby(),NOW)['verified'],True)
        state=lobby();state.tokens=[t for t in state.tokens if '本期' not in t.text]
        state.tokens.extend([Token('本期剩余时间：',.99,(.035,.84,.13,.864)),Token('6天18小时',.99,(.135,.84,.24,.864))])
        self.assertIs(period_evidence(state,NOW)['verified'],True)
        state.tokens=[t for t in state.tokens if not t.within((.02,.825,.35,.875))]
        for index,text in enumerate(('本期','剩余时间：','6天','18小时','0分钟')):
            x=.035+.055*index;state.tokens.append(Token(text,.99,(x,.84,x+.05,.864)))
        self.assertIs(period_evidence(state,NOW)['verified'],True)
        sunday=datetime(2026,10,18,9,18,tzinfo=CHINA)
        self.assertIs(period_evidence(lobby(timer='18小时42分钟'),sunday)['verified'],True)
        for timer in ('0分钟','6天24小时','6天18','6天18小时60分钟'):
            with self.subTest(timer=timer):self.assertIs(period_evidence(lobby(timer=timer),NOW)['verified'],False)
        stale=lobby(18000,'0分钟')
        self.assertIs(period_evidence(stale,datetime(2026,10,26,4,tzinfo=CHINA))['verified'],False)
        self.assertIs(period_evidence(lobby(timer='7天'),datetime(2026,10,26,4,tzinfo=CHINA))['verified'],True)
        with self.assertRaises(ValueError):game_week(datetime(2026,10,26))

    def test_points_navigation_can_only_return_to_lobby_and_stops_there(self):
        c=Mock(settings=Settings());c.report.operation=OPERATION
        self.assertIsNone(next_action(lobby(),c))
        self.assertEqual(next_action(nav.mode(True),c).intent,'points_back_from_mode')
        self.assertEqual(next_action(ranks.rank_page(40,(40,39,38)),c).intent,'points_back_from_rank')
        with self.assertRaises(ValueError):Runner(Settings(),operation=OPERATION,currency_locate=True,currency_configure=True)
        with self.assertRaises(ValueError):Runner(Settings(),operation=OPERATION,currency_resume=True)

    def test_formal_runner_saves_account_week_receipt_for_zero_and_full_without_match_inputs(self):
        for current in (0,18000):
            with self.subTest(current=current),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);r=runner([lobby(current) for _ in range(3)])
                with loop_helpers.real_runtime(root) as window,patch('autohsr.currency_wars_points_run.local_now',return_value=NOW):
                    report=r.run()
                self.assertEqual(report.status,'success',report.error);self.assertIs(report.report_saved,True)
                data=report.currency_wars;self.assertEqual(data['current'],current)
                self.assertEqual(data['weekly_target_verified'],current==18000)
                self.assertIs(data['rewards_verified'],False);self.assertIs(data['completion_verified'],False)
                self.assertIs(data['match_started'],False);window.click.assert_not_called();window.key.assert_not_called()
                self.assertEqual(data['client']['full_version'],'4.6.0')
                self.assertEqual(set(data['client']),{'version','full_version','kind','sha256'})
                receipt=latest(root/'runs',data['account_key'],'2026-10-26')
                self.assertEqual(receipt['observation'],data)
                self.assertEqual(json.loads((Path(report.run_dir)/'report.json').read_text(encoding='utf-8'))['status'],'success')
                self.assertFalse((root/'runs/currency-standard-session.json').exists())
                self.assertEqual((report.stamina_spent,report.stamina_pending,report.battle_completed),(0,0,0))

    def test_missing_current_process_version_does_not_use_configured_installation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);other=root/'configured-game';other.mkdir()
            (other/'StarRail.exe').write_bytes(b'configured path only; never executed')
            (other/'config.ini').write_text('[General]\ngame_version=9.9.0\n',encoding='utf-8')
            r=runner([lobby() for _ in range(3)]);r.settings.game_path=str(other/'StarRail.exe')
            with loop_helpers.real_runtime(root) as window,patch('autohsr.currency_wars_points_run.local_now',return_value=NOW):
                (Path(window.path).parent/'config.ini').unlink()
                report=r.run()
            self.assertEqual(report.status,'failed');self.assertIn('版本未核实',report.error)
            self.assertFalse(list((root/'runs').glob('currency-points/*/*/*.json')))

    def test_new_observation_updates_latest_without_replacing_original_records(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);reports=[]
            for current in (0,18000):
                r=runner([lobby(current) for _ in range(3)])
                with loop_helpers.real_runtime(root),patch('autohsr.currency_wars_points_run.local_now',return_value=NOW):report=r.run()
                self.assertEqual(report.status,'success',report.error);reports.append(report)
            old,new=(r.currency_wars for r in reports)
            self.assertNotEqual(old['receipt_path'],new['receipt_path'])
            self.assertEqual(latest(root/'runs',new['account_key'],new['game_week'])['observation']['current'],18000)
            self.assertTrue(Path(old['receipt_path']).exists())
            old_receipt=json.loads(Path(old['receipt_path']).read_text(encoding='utf-8'))
            self.assertEqual(old_receipt['observation']['current'],0)

    def test_point_query_preserves_a_settled_match_and_all_of_its_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'runs').mkdir();loop_helpers.settled(root/'runs')
            path=root/'runs/currency-standard-session.json';raw=path.read_bytes()
            r=runner([lobby() for _ in range(3)])
            with loop_helpers.real_runtime(root),patch('autohsr.currency_wars_points_run.local_now',return_value=NOW):report=r.run()
            self.assertEqual(report.status,'success',report.error);self.assertEqual(path.read_bytes(),raw)

    def test_independent_points_and_rewards_accept_saved_settled_defeat_without_altering_it(self):
        from autohsr.tests import test_currency_wars_weekly_rewards as rewards

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store, _ = self._settled_defeat(root)
            originals = {p: p.read_bytes() for p in (root / 'runs').rglob('*') if p.is_file()}
            with self.assertRaises(AutomationError):
                require_no_active_match(store.data)

            score = 1800
            points_child = runner([lobby(score) for _ in range(3)])
            with loop_helpers.real_runtime(root) as window, \
                 patch('autohsr.currency_wars_points_run.local_now', return_value=NOW):
                points_report = points_child.run()
            self.assertEqual(points_report.status, 'success', points_report.error)
            self.assertEqual(points_report.currency_wars['current'], score)
            self.assertFalse(points_report.currency_wars['rewards_verified'])
            self.assertFalse(points_report.currency_wars['completion_verified'])
            window.click.assert_not_called()
            window.key.assert_not_called()
            data = points_report.currency_wars
            self.assertEqual(latest(root / 'runs', data['account_key'], data['game_week'])['observation'], data)

            with rewards.runtime(root) as window:
                rewards_report = rewards.runner(rewards.stages(score)).run()
            self.assertEqual(rewards_report.status, 'success', rewards_report.error)
            self.assertEqual([a['intent'] for a in rewards_report.currency_wars['actions']],
                             ['open_points_rewards', 'claim_weekly_rewards', 'dismiss_weekly_rewards',
                              'return_weekly_lobby'])
            self.assertEqual(window.click.call_count, 3)
            window.key.assert_called_once_with('esc')
            self.assertTrue(rewards_report.currency_wars['claimed_now'])
            self.assertFalse(rewards_report.currency_wars['weekly_rewards_verified'])
            self.assertFalse(rewards_report.currency_wars['completion_verified'])
            reward_store = rewards.RewardStore(root / 'runs')
            reward_store.load()
            reward_store.check_receipt()
            for path, raw in originals.items():
                self.assertEqual(path.read_bytes(), raw, str(path))

    def test_settled_defeat_does_not_widen_weekly_or_overclock_preflight(self):
        from autohsr.currency_wars_overclock import OPERATION as OVERCLOCK_OPERATION
        from autohsr.currency_wars_overclock_session import START_OPERATION
        from autohsr.currency_wars_weekly import preflight
        from autohsr.tests import test_currency_wars_overclock_start as opening

        legacy = opening.OverclockStartNativeTests()
        self.addCleanup(legacy.doCleanups)
        legacy.setUp()
        preview = opening.boss(account=0)
        started = legacy.native_cli(opening.frame('a0', account=0), preview, preview)
        legacy.assert_session(started, started=True)
        a0_receipt = legacy.session.read_bytes()
        legacy.session.unlink()

        store, _ = self._settled_defeat(legacy.root)
        original = store.path.read_bytes()
        with self.assertRaisesRegex(AutomationError, '未核实结束的标准对局'):
            preflight(legacy.runs)
        for operation in (OVERCLOCK_OPERATION, START_OPERATION):
            with self.subTest(operation=operation), loop_helpers.real_runtime(legacy.root) as window, \
                 patch('autohsr.app.find_game', return_value=window) as find:
                child = Runner(Settings(overlay_logs=False), operation=operation)
                result = child.run()
                self.assertEqual(result.status, 'failed')
                self.assertIn('未核实结束的标准对局', result.error)
                find.assert_not_called()

        legacy.session.write_bytes(a0_receipt)
        self.assertEqual(legacy.ledger()['account_key'], store.data['account_key'])
        blocked = legacy.legacy_runner(False, preview)
        legacy.assert_preflight_veto(blocked)
        self.assertIn('未核实结束的标准对局', blocked.report['error'])
        self.assertEqual(legacy.session.read_bytes(), a0_receipt)
        self.assertEqual(store.path.read_bytes(), original)

    def test_unproven_defeat_stops_both_independent_entries_before_window_enumeration(self):
        for case in ('missing_report', 'changed_report', 'missing_frame', 'missing_sample',
                     'wrong_sample_image', 'synthetic_sample', 'unknown', 'client_version', 'rules_version',
                     'conflicting_victory', 'changed_account'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                store, original_report = self._settled_defeat(root)
                report = json.loads(original_report.read_text(encoding='utf-8'))
                if case == 'missing_report':
                    original_report.unlink()
                elif case == 'changed_report':
                    report['currency_wars']['reason'] = 'changed original result'
                    original_report.write_text(json.dumps(report), encoding='utf-8')
                elif case == 'missing_frame':
                    Path(store.data['node_attempt']['defeat_frames'][0]).unlink()
                elif case in ('missing_sample', 'wrong_sample_image', 'synthetic_sample'):
                    first, second = (Path(path).with_suffix('.sample.json')
                                     for path in store.data['node_attempt']['defeat_frames'])
                    if case == 'missing_sample':
                        first.unlink()
                    elif case == 'wrong_sample_image':
                        first.write_bytes(second.read_bytes())
                    else:
                        sample = json.loads(first.read_text(encoding='utf-8'))
                        sample['origin'] = 'synthetic'
                        first.write_text(json.dumps(sample), encoding='utf-8')
                else:
                    if case == 'unknown':
                        store.data.update(status='active', defeat_settlement_verified=False,
                                          settlement_verified=False)
                        store.data['actions'][-1]['status'] = 'unknown'
                    elif case == 'client_version':
                        store.data['client']['version'] = '4.7'
                    elif case == 'rules_version':
                        store.data['rules_version'] = '4.7'
                    elif case == 'changed_account':
                        other = Scene([Token('UID:100000001', .99, (.01, .96, .10, .99))])
                        store.data['account_key'] = account_key(other)
                    else:
                        store.data['match_victory_observed'] = True
                    report['currency_wars'] = store.data
                    # Write deliberately invalid records without the fixture's validation.
                    store.path.write_text(json.dumps(store.data), encoding='utf-8')
                    original_report.write_text(json.dumps(report), encoding='utf-8')
                if case == 'changed_account':
                    archive_proof(LoopStore(root / 'runs'), store.data, original_report)

                originals = {p: p.read_bytes() for p in (root / 'runs').rglob('*') if p.is_file()}
                self._assert_independent_entries_blocked(root)
                for path, raw in originals.items():
                    self.assertEqual(path.read_bytes(), raw, str(path))

    def test_every_original_defeat_png_is_verified_before_independent_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store, report = self._settled_defeat(root)
            proof = archive_proof(LoopStore(root / 'runs'), store.data, report)
            self.assertEqual(len(proof['ending_evidence']), 11)
            originals = {p: p.read_bytes() for p in (root / 'runs').rglob('*') if p.is_file()}
            for image in map(Path, proof['ending_evidence']):
                with self.subTest(image=image.name):
                    with Image.open(image) as original:
                        changed = original.convert('RGB')
                    red, green, blue = changed.getpixel((0, 0))
                    changed.putpixel((0, 0), ((red + 1) % 256, green, blue))
                    try:
                        changed.save(image)
                        changed_bytes = image.read_bytes()
                        self.assertNotEqual(changed_bytes, originals[image])
                        self._assert_independent_entries_blocked(root)
                        self.assertEqual(image.read_bytes(), changed_bytes)
                    finally:
                        image.write_bytes(originals[image])
            for path, raw in originals.items():
                self.assertEqual(path.read_bytes(), raw, str(path))

    def test_period_recheck_uses_the_same_configured_confidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);states=[lobby(18000) for _ in range(3)]
            for state in states:
                state.tokens=[Token(t.text,.90,t.box) if '本期' in t.text else t for t in state.tokens]
            r=runner(states);r.settings.ocr_confidence=.95
            with loop_helpers.real_runtime(root),patch('autohsr.currency_wars_points_run.local_now',return_value=NOW):report=r.run()
            self.assertEqual(report.status,'success',report.error);self.assertFalse(report.currency_wars['weekly_target_verified'])
            receipt=latest(root/'runs',report.currency_wars['account_key'],report.currency_wars['game_week'])
            self.assertEqual(receipt['observation']['confidence'],.95)

    def test_changed_account_or_week_lookup_does_not_reuse_another_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);r=runner([lobby(18000) for _ in range(3)])
            with loop_helpers.real_runtime(root),patch('autohsr.currency_wars_points_run.local_now',return_value=NOW):report=r.run()
            self.assertEqual(report.status,'success',report.error);data=report.currency_wars
            with self.assertRaises(FileNotFoundError):latest(root/'runs','f'*64,data['game_week'])
            with self.assertRaises(FileNotFoundError):latest(root/'runs',data['account_key'],'2026-10-19')

    def test_mode_rank_and_points_panel_return_without_selecting_or_starting(self):
        entries=(nav.mode(True),ranks.rank_page(40,(40,39,38)),nav.points_rewards())
        for entry in entries:
            with self.subTest(entry=entry.text[:20]),tempfile.TemporaryDirectory() as folder:
                root=Path(folder)
                states=[deepcopy(entry),deepcopy(entry)]
                expected=1
                if entry is entries[1]:states.append(nav.mode(True));expected=2
                states.extend([lobby(),lobby()]);r=runner(states)
                with loop_helpers.real_runtime(root) as window,patch('autohsr.currency_wars_points_run.local_now',return_value=NOW):report=r.run()
                self.assertEqual(report.status,'success',report.error);window.click.assert_not_called()
                self.assertEqual(window.key.call_count,expected)
                self.assertTrue(all(call.args==('esc',) for call in window.key.call_args_list))

    def test_cross_week_stale_display_does_not_mark_weekly_target_verified(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);r=runner([lobby(18000,'0分钟') for _ in range(3)])
            with loop_helpers.real_runtime(root),patch('autohsr.currency_wars_points_run.local_now',return_value=datetime(2026,10,26,4,tzinfo=CHINA)):
                report=r.run()
            self.assertEqual(report.status,'success',report.error);self.assertIs(report.currency_wars['score_complete'],True)
            self.assertIs(report.currency_wars['weekly_target_verified'],False)
            self.assertEqual(report.currency_wars['period']['reason'],'period_countdown_conflicts_with_clock')

    def test_unreadable_score_account_or_changed_epoch_never_creates_a_completion_receipt(self):
        for case in ('score','account','epoch'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);r=runner([lobby() for _ in range(5)])
                with loop_helpers.real_runtime(root) as window:
                    original=Context.snapshot;original_evidence=Context.evidence
                    def changed(c):
                        state=original(c)
                        if case!='epoch' and len(c.runner._loop_test_scenes)<=2:
                            state.tokens=[t for t in state.tokens if not (t.text=='0/18000' if case=='score' else 'UID' in t.text)]
                        return state
                    def interrupted(c,state,label):
                        path=original_evidence(c,state,label)
                        if case=='epoch' and label=='currency_weekly_points':c.runner.input_epoch+=1
                        return path
                    with patch.object(Context,'snapshot',changed),patch.object(Context,'evidence',interrupted):report=r.run()
                self.assertEqual(report.status,'failed');window.click.assert_not_called();window.key.assert_not_called()
                self.assertFalse(list((root/'runs').glob('currency-points/*/*/*.json')))

    def test_existing_active_unknown_or_incomplete_standard_session_blocks_before_game_access(self):
        for status in ('start_pending','active','failed','settled'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);path=root/'runs/currency-standard-session.json';store=StandardSession(path)
                store.begin(root/'old',{});store.data['status']=status;store.persist();raw=path.read_bytes()
                r=runner([])
                with loop_helpers.real_runtime(root) as window,patch.object(r,'_prepare_daily_game') as prepare:
                    report=r.run()
                self.assertEqual(report.status,'failed');prepare.assert_not_called();window.focus.assert_not_called()
                self.assertEqual(path.read_bytes(),raw)

    def test_report_write_failure_never_creates_a_verified_points_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);r=runner([lobby() for _ in range(3)])
            with loop_helpers.real_runtime(root),patch('autohsr.currency_wars_points_run.local_now',return_value=NOW), \
                 patch('autohsr.app.replace_file',side_effect=OSError('report write blocked')):report=r.run()
            self.assertFalse(report.report_saved);self.assertNotEqual(report.status,'success')
            self.assertFalse(Path(report.currency_wars['receipt_path']).exists())

    def test_receipt_failure_stays_partial_and_releases_runtime_mutex(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);r=runner([lobby() for _ in range(3)])
            with loop_helpers.real_runtime(root),patch('autohsr.currency_wars_points_run.local_now',return_value=NOW), \
                 patch('autohsr.windows.kernel32') as kernel,patch('autohsr.currency_wars_points_run.finalize') as finalize:
                kernel.CreateMutexW.return_value=1
                def fail(report):
                    kernel.CloseHandle.assert_not_called();raise OSError('points receipt blocked')
                finalize.side_effect=fail;report=r.run();kernel.CloseHandle.assert_called_once_with(1)
            self.assertEqual(report.status,'partial');self.assertIs(report.report_saved,True)
            saved=json.loads((Path(report.run_dir)/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['status'],'partial');self.assertFalse(Path(report.currency_wars['receipt_path']).exists())

    def test_changed_source_report_score_or_week_never_validates_as_old_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);r=runner([lobby(18000) for _ in range(3)])
            with loop_helpers.real_runtime(root),patch('autohsr.currency_wars_points_run.local_now',return_value=NOW):report=r.run()
            self.assertEqual(report.status,'success',report.error);data=report.currency_wars
            for change in (dict(current=0),dict(game_week='2026-10-19'),dict(weekly_target_verified=False),
                           dict(weekly_target_verified=1),dict(schema=True),dict(period=dict(data['period'],verified=1)),
                           dict(source=str(root/'missing.png'))):
                with self.subTest(change=change),self.assertRaises(AutomationError):validate_observation(root/'runs',dict(data,**change))
            source=Path(data['source']);raw=source.read_bytes();source.write_bytes(raw+b'changed')
            with self.assertRaises(AutomationError):latest(root/'runs',data['account_key'],data['game_week'])
            source.write_bytes(raw);path=Path(report.run_dir)/'report.json';saved=path.read_bytes();path.write_bytes(saved+b' ')
            with self.assertRaises(AutomationError):latest(root/'runs',data['account_key'],data['game_week'])

    def test_cli_dispatches_independent_operation_and_preserves_configuration(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';Settings().save(path);raw=path.read_bytes()
            with patch('autohsr.app.Runner') as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                factory.return_value.run.return_value=dict(status='success')
                self.assertEqual(main(['--currency-wars-points','--config',str(path)]),0)
                self.assertEqual(factory.call_args.kwargs['operation'],OPERATION)
            self.assertEqual(path.read_bytes(),raw)
            for option in ('--resume-active-currency','--currency-fast-mode','--resume-currency-loop'):
                with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(['--currency-wars-points',option])


if __name__=='__main__':unittest.main()
