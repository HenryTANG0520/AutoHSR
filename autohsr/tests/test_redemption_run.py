"""Formal redemption flow and Context against synthetic pages and fake IO."""
from copy import deepcopy
from itertools import count
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.models import AutomationError, InputInterrupted, RunReport, TaskResult, Token
from autohsr.redemption_codes import from_values
from autohsr.redemption_run import RedemptionWorkflow, run_redemption
from autohsr.redemption_store import RedemptionStore
from autohsr.windows import Geometry
from autohsr.tests import test_redemption_pages as pages

CODE = 'AbC2026中文'


def sequence(code=CODE, status='redeemed', *, inline=False):
    return [pages.phone_scene(), pages.phone_scene(), pages.phone_scene(), pages.phone_scene(),
            pages.more_scene(), pages.form_scene(), pages.form_scene(), pages.form_scene(code), pages.form_scene(code),
            pages.result_scene(status, inline=inline), pages.result_scene(status, inline=inline), pages.phone_scene()]


def context(folder, scenes, *, duplicate_at=()):
    run = Path(folder) / ('attempt-' + str(len(list(Path(folder).glob('attempt-*')))))
    run.mkdir()
    c = SimpleNamespace(settings=Settings(redemption_enabled=True, redemption_source='manual',
        redemption_codes=[CODE], redemption_claim_mail=False), report=RunReport(operation='redemption', run_dir=str(run)),
        runner=SimpleNamespace(input_epoch=0, inactive_duration=0, wait_for_focus=Mock()),
        last_scene=None, scene_epoch=0, window=Mock(), checkpoint=Mock(), log=Mock())
    c.clock = SimpleNamespace(value=1000.)
    c.sleep = lambda seconds: setattr(c.clock, 'value', c.clock.value + seconds)
    pending = iter(scenes)
    numbers, captures = count(), count()
    def snapshot():
        scene = deepcopy(next(pending))
        c.clock.value += .1
        index = next(captures)
        scene.captured_at = c.last_scene.captured_at if index in duplicate_at else c.clock.value
        scene.geometry = Geometry(0, 0, scene.image.shape[1], scene.image.shape[0])
        scene.tokens.append(Token('UID:100000000', .99, (.01, .96, .10, .99)))
        c.last_scene, c.scene_epoch = scene, c.runner.input_epoch
        return scene
    c.snapshot = snapshot
    def evidence(scene, label):
        path = run / (str(next(numbers)) + '-' + label + '.png')
        Image.fromarray(scene.image[:, :, ::-1]).save(path)
        return path
    c.evidence = evidence
    c._focus_interrupted = lambda: Context._focus_interrupted(c)
    c.redemption_input = lambda scene, action: Context.redemption_input(c, scene, action)
    return c


class RedemptionRunTests(unittest.TestCase):
    def execute(self, c, store, codes=(CODE,)):
        clock = SimpleNamespace(monotonic=lambda: c.clock.value)
        with patch('autohsr.redemption_run.time', clock), patch('autohsr.redemption_pages.time', clock):
            return run_redemption(c, batch=from_values(list(codes), 'cn'), store=store)

    def test_real_page_contracts_and_context_submit_once_then_save_distinct_result(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, sequence())
            store = RedemptionStore(Path(folder) / 'ledger.json')
            self.assertEqual(self.execute(c, store).status, 'ok')
            data = c.report.redemption
            self.assertEqual((data['submitted'], data['redeemed']), (1, 1))
            self.assertEqual(data['results'][0]['status'], 'redeemed')
            self.assertEqual([a['intent'] for a in data['actions']],
                             ['open_more', 'open_form', 'focus_code', 'type_code', 'submit_code', 'close_result'])
            self.assertTrue(all(a['status'] == 'verified' for a in data['actions']))
            entry = store.lookup(data['account_key'], 'cn', CODE)
            self.assertEqual(entry['status'], 'redeemed')
            self.assertEqual(len(entry['result']['evidence']), 2)
            c.window.type_redemption_code.assert_called_once()
            self.assertEqual(c.window.type_redemption_code.call_args.args[0], CODE)
            self.assertEqual(c.window.click.call_count, 5)
            c.window.key.assert_not_called()

    def test_all_explicit_rejections_and_inline_errors_keep_reason_without_redeemed_count(self):
        for status, inline in (('expired', False), ('invalid', False), ('already_used', False), ('invalid', True)):
            with self.subTest(status=status, inline=inline), tempfile.TemporaryDirectory() as folder:
                c = context(folder, sequence(status=status, inline=inline))
                store = RedemptionStore(Path(folder) / 'ledger.json')
                self.assertEqual(self.execute(c, store).status, 'ok')
                self.assertEqual(c.report.redemption['redeemed'], 0)
                self.assertEqual(c.report.redemption['results'][0]['status'], status)
                if inline:
                    c.window.key.assert_called_once_with('esc')

    def test_case_preserved_code_and_chinese_echo_are_separate_from_submit(self):
        for value in ('lowerCase7', '恭喜发财好运来'):
            with self.subTest(code=value), tempfile.TemporaryDirectory() as folder:
                c = context(folder, sequence(code=value))
                store = RedemptionStore(Path(folder) / 'ledger.json')
                self.execute(c, store, [value])
                self.assertEqual(c.window.type_redemption_code.call_args.args[0], value)
                self.assertEqual(store.lookup(c.report.redemption['account_key'], 'cn', value)['code'], value)

    def test_repeated_capture_cannot_supply_second_echo_or_second_result(self):
        states = sequence()
        states.insert(9, pages.form_scene(CODE))
        states.insert(12, pages.result_scene('redeemed'))
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, states, duplicate_at=(8, 11))
            store = RedemptionStore(Path(folder) / 'ledger.json')
            self.execute(c, store)
            echo = c.report.redemption['current_echo']
            self.assertLess(echo[0]['captured_at'], echo[1]['captured_at'])
            receipt = store.lookup(c.report.redemption['account_key'], 'cn', CODE)['result']
            self.assertLess(*receipt['basis']['captures'])
            self.assertEqual(c.window.type_redemption_code.call_count, 1)

    def test_failed_claim_write_never_clicks_submit(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, sequence())
            store = RedemptionStore(Path(folder) / 'ledger.json')
            with patch('autohsr.redemption_store.replace_file', side_effect=OSError('simulated lock')):
                with self.assertRaises(AutomationError):
                    self.execute(c, store)
            self.assertEqual(c.window.click.call_count, 3)
            self.assertNotIn('submit_code', [a['intent'] for a in c.report.redemption['actions']])

    def test_unrelated_submit_png_cannot_authorize_the_current_form(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, sequence())
            store = RedemptionStore(Path(folder) / 'ledger.json')
            evidence = c.evidence
            def altered(scene, label):
                path = evidence(scene, label)
                if label == 'redemption_before_submit':
                    Image.new('RGB', (scene.image.shape[1], scene.image.shape[0]), 'black').save(path)
                return path
            c.evidence = altered
            with self.assertRaises(AutomationError):
                self.execute(c, store)
            self.assertEqual(c.window.click.call_count, 3)
            self.assertEqual(store.lookup(c.report.redemption['account_key'], 'cn', CODE)['status'], 'pending')

    def test_old_result_is_never_adopted_and_empty_batch_never_touches_game(self):
        with tempfile.TemporaryDirectory() as folder:
            store = RedemptionStore(Path(folder) / 'ledger.json')
            c = context(folder, [pages.phone_scene()] * 3 + [pages.result_scene()])
            with self.assertRaises(AutomationError):
                self.execute(c, store)
            c.window.click.assert_not_called()
            c = context(folder, [])
            c.snapshot = Mock(side_effect=AssertionError('empty batch must not capture'))
            self.assertEqual(self.execute(c, store, []).status, 'ok')
            c.snapshot.assert_not_called()

    def test_pause_or_account_switch_during_entry_does_not_submit(self):
        for change in ('epoch', 'account'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                c = context(folder, sequence())
                store = RedemptionStore(Path(folder) / 'ledger.json')
                if change == 'epoch':
                    c.window.type_redemption_code.side_effect = lambda *a, **kw: setattr(c.runner, 'input_epoch', 1)
                else:
                    snapshot = c.snapshot
                    def wrong_account():
                        scene = snapshot()
                        if c.window.type_redemption_code.called:
                            scene.tokens[-1] = Token('UID:200000000', .99, (.01, .96, .10, .99))
                        return scene
                    c.snapshot = wrong_account
                with self.assertRaises(AutomationError):
                    self.execute(c, store)
                self.assertEqual(c.window.click.call_count, 3)
                self.assertNotIn('submit_code', [a['intent'] for a in c.report.redemption['actions']])

    def test_typing_checkpoint_discards_remaining_characters_after_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, sequence())
            store = RedemptionStore(Path(folder) / 'ledger.json')
            completed = []
            def partial_input(code, geometry, *, checkpoint):
                checkpoint()
                completed.append(code[0])
                c.runner.input_epoch += 1
                checkpoint()
                completed.append(code[1:])
            c.window.type_redemption_code.side_effect = partial_input
            with self.assertRaises(InputInterrupted):
                self.execute(c, store)
            self.assertEqual(completed, [CODE[0]])
            self.assertEqual(c.window.click.call_count, 3)
            self.assertNotIn('submit_code', [a['intent'] for a in c.report.redemption['actions']])

    def test_saved_result_survives_close_failure_and_next_run_deduplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, sequence())
            def click(*args):
                if c.redemption_workflow.request.intent == 'close_result':
                    raise InputInterrupted('synthetic close interruption')
            c.window.click.side_effect = click
            store = RedemptionStore(Path(folder) / 'ledger.json')
            with self.assertRaises(InputInterrupted):
                self.execute(c, store)
            self.assertEqual(c.report.redemption['redeemed'], 1)
            self.assertEqual(store.lookup(c.report.redemption['account_key'], 'cn', CODE)['status'], 'redeemed')
            later = context(folder, [pages.phone_scene()] * 3)
            self.assertEqual(self.execute(later, store).status, 'ok')
            self.assertTrue(later.report.redemption['results'][0]['reused'])
            self.assertEqual(later.report.redemption['redeemed'], 0)
            later.window.click.assert_not_called()
            later.window.type_redemption_code.assert_not_called()

    def test_unverified_submit_stays_pending_and_is_not_repeated_next_run(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, sequence()[:9] + [pages.form_scene(CODE)])
            def after_submit(*args):
                if c.redemption_workflow.request.intent == 'submit_code':
                    c.sleep = lambda seconds: setattr(c.clock, 'value', c.clock.value + 31)
            c.window.click.side_effect = after_submit
            store = RedemptionStore(Path(folder) / 'ledger.json')
            with self.assertRaises(AutomationError):
                self.execute(c, store)
            self.assertEqual(c.report.redemption['actions'][-1]['intent'], 'submit_code')
            self.assertEqual(c.report.redemption['actions'][-1]['status'], 'unknown')
            self.assertEqual(store.lookup(c.report.redemption['account_key'], 'cn', CODE)['status'], 'pending')
            later = context(folder, [pages.phone_scene()] * 3)
            with self.assertRaises(AutomationError):
                self.execute(later, store)
            later.window.click.assert_not_called()
            later.window.type_redemption_code.assert_not_called()

    def test_new_success_claims_mail_once_and_daily_can_defer_to_selected_mail_task(self):
        for operation, selected in (('redemption', False), ('daily', True)):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                c = context(folder, sequence())
                c.settings.redemption_claim_mail = True
                c.settings.mail = selected
                c.report.operation = operation
                store = RedemptionStore(Path(folder) / 'ledger.json')
                with patch('autohsr.workflows.DailyWorkflow.mail', return_value=TaskResult('mail', 'ok', 'synthetic claimed')) as mail:
                    self.execute(c, store)
                if selected:
                    mail.assert_not_called()
                    self.assertEqual(c.report.redemption['mail'], 'deferred_to_daily_mail')
                else:
                    mail.assert_called_once()
                    self.assertEqual(c.report.redemption['mail']['status'], 'ok')

    def test_context_requires_own_scope_and_durable_session_before_typing(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, [pages.form_scene()])
            store = RedemptionStore(Path(folder) / 'ledger.json')
            clock = SimpleNamespace(monotonic=lambda: c.clock.value)
            with patch('autohsr.redemption_run.time', clock), patch('autohsr.redemption_pages.time', clock):
                workflow = RedemptionWorkflow(c, batch=from_values([CODE], 'cn'), store=store)
                scene = c.snapshot()
                from autohsr.currency_wars_identity import account_key
                workflow.account, workflow.code = account_key(scene), CODE
                action = workflow._derive(scene, 'focus_code')
                workflow.request = action
                with self.assertRaises(AutomationError):
                    Context.redemption_input(c, scene, action)
                c.report.operation = 'reward_only'
                with self.assertRaises(AutomationError):
                    Context.redemption_input(c, scene, action)
            c.window.click.assert_not_called()

    def test_session_write_failure_after_durable_terminal_preserves_confirmed_success(self):
        with tempfile.TemporaryDirectory() as folder:
            c = context(folder, sequence())
            store = RedemptionStore(Path(folder) / 'ledger.json')
            from autohsr.storage import replace_file
            def save(source, target):
                if store.path.exists():
                    data = json.loads(store.path.read_text(encoding='utf-8'))
                    if data['entries'][0]['status'] == 'redeemed':
                        raise OSError('synthetic session save failure after receipt')
                return replace_file(source, target)
            with patch('autohsr.redemption_run.replace_file', side_effect=save), self.assertRaises(OSError):
                self.execute(c, store)
            self.assertEqual(c.report.redemption['redeemed'], 1)
            self.assertEqual(c.report.redemption['results'][0]['status'], 'redeemed')
            self.assertEqual(store.lookup(c.report.redemption['account_key'], 'cn', CODE)['status'], 'redeemed')
            self.assertEqual(c.report.redemption['actions'][-1]['intent'], 'submit_code')

    def test_already_open_form_or_more_menu_is_reused_without_toggling_it_closed(self):
        for start in ('form', 'more'):
            with self.subTest(start=start), tempfile.TemporaryDirectory() as folder:
                first = pages.form_scene if start == 'form' else pages.more_scene
                states = [first(), first(), first(), first()]
                if start == 'more':
                    states.append(pages.form_scene())
                states += [pages.form_scene(), pages.form_scene(CODE), pages.form_scene(CODE),
                           pages.result_scene(), pages.result_scene(), pages.phone_scene()]
                c = context(folder, states)
                store = RedemptionStore(Path(folder) / 'ledger.json')
                self.assertEqual(self.execute(c, store).status, 'ok')
                intents = [a['intent'] for a in c.report.redemption['actions']]
                self.assertNotIn('open_more', intents)
                self.assertEqual('open_form' in intents, start == 'more')
