"""The standard encounter continuation and its native input boundary."""
from contextlib import ExitStack
from dataclasses import replace
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_encounter import EncounterCard, EncounterObservation
from autohsr.currency_wars_identity import account_key, installed_client
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_session import StandardSession, require_session_access
from autohsr.currency_wars_standard_budget import StandardBudget
from autohsr.currency_wars_standard_encounter import CONFIRM, OFFER, SELECT, record_start
from autohsr.currency_wars_standard_encounter_battle import BINDING, START
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.models import AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, Token
from autohsr.tests.test_currency_wars_standard_node import current
from autohsr.tests.test_currency_wars_standard_progress import board, boss_arrival, loss_page
from autohsr.tests.test_currency_wars_standard_trading import hud
from autohsr.windows import GameWindow, Geometry


GEOMETRY = Geometry(0, 0, 1920, 1080)
UID = Token('UID:100000000', .99, (.01, .96, .10, .99))
CONTINUE = 'continue_standard_node'
LABEL_REGION = (.28, .07, .73, .105)


def preparation(node, *, known_type=False, shop=False, overlay=False):
    if shop:
        scene = boss_arrival(node, shop=True, gold=9)
    else:
        scene = hud(board(node), gold=9, level=6, deployment=(6, 6))
        if not known_type:
            scene.tokens = [token for token in scene.tokens if not token.within(LABEL_REGION)]
    scene.tokens = [token for token in scene.tokens if not token.text.startswith('UID')]
    scene.tokens.append(UID)
    if overlay:
        scene.tokens.append(Token('synthetic_encounter_overlay', .99, (.42, .43, .58, .46)))
    return scene


def modal(*, left=1, right=3, selected=0, complete=True, node=None):
    cards = (Token('遭遇其一', .99, (.31, .35, .39, .38)),
             Token('遭遇其三', .99, (.61, .35, .69, .38)))
    cue = Token(f'synthetic_encounter:{left}:{right}:{selected}:{int(complete)}', .99,
                (.10, .13, .22, .16))
    choose = Token('选择', .99, (.54, .78, .59, .81))
    tokens = [*cards, choose, cue, UID]
    if node:
        tokens.append(Token(node, .74, (.23, .055, .26, .085)))
    return Scene(tokens)


def fake_targets(scene, _confidence):
    cue = next((token for token in scene.tokens if token.text.startswith('synthetic_encounter:')), None)
    if cue is None:
        return None
    left, right, selected, complete = map(int, cue.text.split(':')[1:])
    names = tuple(token for token in scene.tokens if token.text.startswith('遭遇其'))
    observation = EncounterObservation(
        True, (EncounterCard(1, names[0].text, left, dict(kind='gold', quantity=2, character_cost=None)),
               EncounterCard(2, names[1].text, right,
                             dict(kind='random_character', quantity=2 if complete else None, character_cost=4))),
        selected or None, 'selected' if selected else 'unselected', 'enabled' if selected else 'disabled', 1,
    )
    return SimpleNamespace(observation=observation, cards=names,
                           choose=next(token for token in scene.tokens if token.text == '选择'))


def fake_observation(scene, confidence):
    current_targets = fake_targets(scene, confidence)
    return current_targets.observation if current_targets else None


class StandardEncounterTests(unittest.TestCase):
    def run_path(self, node, scenes, *, original=True, stale=(), native_failure=None, stop_at_arrival=True,
                 actual_readers=False, battle_node=None):
        sandbox = TemporaryDirectory(prefix='cw-enc-')
        self.addCleanup(sandbox.cleanup)
        root = Path(sandbox.name)
        run_dir = root / 'r'
        run_dir.mkdir()
        client_dir = root / 'client'
        client_dir.mkdir()
        executable, version_file = client_dir / 'StarRail.exe', client_dir / 'config.ini'
        executable.touch()
        version_file.write_text('[General]\ngame_version=4.6.0\n', encoding='utf-8')
        client = dict(installed_client(executable), verified_run=str(run_dir), input_epoch=0)
        store = StandardSession(root / 'currency-standard-session.json')
        store.begin(run_dir, dict(rank_verified=True, rank=8, wealth=40))
        store.data.update(status='active', start_verified=True, account_key=account_key(Scene([UID])),
                          account_verified_run=str(run_dir), account_verified_epoch=0, rules_version='4.6',
                          client=client)
        if battle_node is not None:
            store.data['shop_observed_nodes'] = [battle_node]

        runner = Runner(Settings(ocr_confidence=.78), operation='currency_wars_standard', currency_resume=True)
        runner.report.run_dir = str(run_dir)
        runner.wait_for_focus = Mock()
        window = object.__new__(GameWindow)
        window.hwnd, window.path = 43021, str(executable)
        c = Context(runner, window, Mock())
        now, last_stamp, frame_id = 100., 99., 0

        def capture(scene, stamp, tone):
            if actual_readers and scene.image is not None:
                image = scene.image
            elif battle_node is not None and isinstance(scene.image, np.ndarray):
                image = scene.image[::2, ::2].copy()
                image[0, 0] = tone
            else:
                image = np.full((270, 480, 3), tone, dtype=np.uint8)
            return replace(scene, tokens=list(scene.tokens), geometry=GEOMETRY,
                           image=image, captured_at=stamp)

        before = capture(preparation(node, known_type=True), 98., 40)
        entered = capture(current('battle', node), 99., 41)
        first_path = c.evidence(before, 'original_start_before')
        action = store.pending('start_standard_node', 0, first_path, 'standard_node_entered')
        action.update(status='verified', target=[node, 9, 80, 6], after=str(c.evidence(entered, 'original_start_after')))
        store.data['node_attempt'] = dict(node=node, start_action_id=action['id'], status='observing',
                                         node_verified=False, battle_observed=False)
        if original:
            record_start(store.data, action, before, 'before', str(run_dir), 0, .78)
            record_start(store.data, action, entered, 'after', str(run_dir), 0, .78)
        store.persist()
        budget = StandardBudget(store.data)
        observed_windows = []

        def checkpoint():
            active = getattr(c, 'currency_standard_session', None)
            if stop_at_arrival and active is not None and active.data.get('node_history'):
                raise Stopped('synthetic verified arrival')

        def log(_message):
            active = c.currency_standard_session.data['node_attempt']
            if battle_node == active['node'] and active.get('status') == 'verified':
                raise Stopped('synthetic encounter result verified')

        def snapshot():
            nonlocal frame_id, now, last_stamp
            now += .01
            frame_id += 1
            if frame_id > len(scenes) or isinstance(scenes[frame_id-1], EmptyCapture):
                c.last_scene = None
                raise EmptyCapture('synthetic blank')
            if frame_id not in stale:
                last_stamp = now
            c.last_scene = capture(scenes[frame_id-1], last_stamp, 42 + frame_id)
            c.scene_epoch = runner.input_epoch
            durable = c.currency_standard_session.data
            observed_windows.append((frame_id, budget.window(durable), durable['actions'][-1]['action']))
            return c.last_scene

        def sleep(seconds):
            nonlocal now
            now += 65. if frame_id >= len(scenes) else seconds

        c.checkpoint, c.snapshot, c.sleep = checkpoint, snapshot, sleep
        if battle_node is not None:
            c.log = log
        calls, injected = [], []
        guards = {}
        native = Mock()
        native.IsWindow.return_value = 1
        native.IsIconic.return_value = 0
        native.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__

        def active_intent():
            return c.currency_standard_session.data['actions'][-1]['action']

        def foreground():
            intent = active_intent()
            guards[intent] = guards.get(intent, 0) + 1
            if guards[intent] == 3 and intent == SELECT:
                if native_failure == 'epoch':
                    injected.append('epoch')
                    runner.input_epoch += 1
                if native_failure == 'focus':
                    injected.append('focus')
                    return 112
                if native_failure == 'intent':
                    injected.append('intent')
                    c.currency_standard_session.data['actions'][-1]['target'][-1] = 2
            if guards[intent] == 3 and intent == START and native_failure == 'start_epoch':
                injected.append('start_epoch')
                runner.input_epoch += 1
            if guards[intent] == 3 and intent == START and native_failure == 'start_focus':
                injected.append('start_focus')
                return 112
            return window.hwnd

        def confirmed_files():
            durable = StandardSession(store.path).data
            index = durable['node_history'][-1]['encounter_arrival_action_id']
            return [Path(frame['source']['path']) for frame in durable['actions'][index]['encounter_frames']]

        def key_state(_key):
            intent = active_intent()
            if intent == SELECT and guards[intent] == 2 and native_failure == 'evidence':
                injected.append('evidence')
                first_path.write_bytes(b'replaced synthetic PNG')
            if intent == CONFIRM and guards[intent] == 2 and native_failure == 'selected_evidence':
                injected.append('selected_evidence')
                selected = c.currency_standard_session.data['actions'][-2]
                Path(selected['after']).write_bytes(b'replaced synthetic selection PNG')
            if intent == SELECT and guards[intent] == 3 and native_failure == 'f10':
                injected.append('f10')
                return 0x8001
            if intent == START and guards[intent] == 2:
                if native_failure in ('arrival_first', 'arrival_last'):
                    index = 0 if native_failure == 'arrival_first' else 1
                    confirmed_files()[index].write_bytes(b'replaced original arrival PNG')
                    injected.append(native_failure)
                if native_failure == 'version':
                    version_file.write_text('[General]\ngame_version=4.7.0\n', encoding='utf-8')
                    injected.append(native_failure)
            if intent == START and guards[intent] == 3 and native_failure == 'start_f10':
                injected.append('start_f10')
                return 0x8001
            return 0

        def send(count, events, _size):
            intent = active_intent()
            durable = StandardSession(store.path).data
            self.assertEqual(durable['actions'][-1]['status'], 'pending')
            self.assertEqual(count, 3)
            calls.append((intent, tuple((item.mi.dx, item.mi.dy, item.mi.dwFlags) for item in events)))
            if native_failure == 'holds' and intent == CONFIRM:
                paths = (first_path, store.path, Path(durable['actions'][-2]['after']))
                for path in paths:
                    expected = path.read_bytes()
                    with self.assertRaises(PermissionError):
                        path.write_bytes(b'tampered while sending')
                    self.assertEqual(path.read_bytes(), expected)
                self.assertFalse(c.last_scene.image.flags.writeable)
                injected.append('holds')
            if native_failure == 'battle_holds' and intent == START:
                for path in [*confirmed_files(), version_file, store.path]:
                    expected = path.read_bytes()
                    with self.assertRaises(PermissionError):
                        path.write_bytes(b'tampered while sending')
                    self.assertEqual(path.read_bytes(), expected)
                self.assertFalse(c.last_scene.image.flags.writeable)
                injected.append('battle_holds')
            if native_failure == 'partial_start' and intent == START:
                injected.append('partial_start')
                return 1
            return count

        native.GetForegroundWindow.side_effect = foreground
        native.GetAsyncKeyState.side_effect = key_state
        native.SendInput.side_effect = send
        clock = SimpleNamespace(monotonic=lambda: now)
        persist = StandardSession.persist

        def save(instance):
            active = instance.data['actions']
            blocked = {'publish': CONFIRM, 'battle_publish': START}.get(native_failure)
            if (blocked is not None and active and active[-1]['action'] == blocked and active[-1]['status'] == 'verified'
                    and (blocked != START or BINDING in active[-1])):
                injected.append(native_failure)
                raise PermissionError('synthetic locked receipt')
            if (native_failure == 'publish_holds' and active and active[-1]['action'] == CONFIRM
                    and active[-1]['status'] == 'verified'):
                for frame in active[-1]['encounter_frames']:
                    path = Path(frame['source']['path'])
                    expected = path.read_bytes()
                    with self.assertRaises(PermissionError):
                        path.write_bytes(b'tampered during receipt publication')
                    self.assertEqual(path.read_bytes(), expected)
                injected.append('publish_holds')
            persist(instance)

        error = None
        with (ExitStack() as strategy, patch('autohsr.windows.user32', native), patch('autohsr.windows.geometry', return_value=GEOMETRY),
              patch('autohsr.currency_wars.time', clock), patch('autohsr.currency_wars_standard_flow.time', clock),
              patch('autohsr.currency_wars_standard_node.time', clock),
              patch.object(StandardSession, 'persist', save)):
            if not actual_readers:
                strategy.enter_context(patch('autohsr.currency_wars_encounter.read_encounter', fake_observation))
                strategy.enter_context(patch('autohsr.currency_wars_encounter.read_encounter_targets', fake_targets))
                strategy.enter_context(patch('autohsr.currency_wars_encounter.encounter_overlay_present',
                                      lambda scene, _: any(token.text == 'synthetic_encounter_overlay' for token in scene.tokens)))
            if battle_node is not None:
                for item in ('standard_flow._preparation_probe', 'standard_sale.proposal', 'standard_exchange.exchange_proposal',
                             'standard_reorder.proposal', 'standard_deployment.standard_deployment',
                             'standard_trading.experience_action', 'standard_equipment.proposal',
                             'standard_consumables.proposal'):
                    strategy.enter_context(patch('autohsr.currency_wars_'+item, return_value=None))
            try:
                run_standard(c)
            except (AutomationError, PermissionError) as caught:
                error = caught
        return SimpleNamespace(data=StandardSession(store.path).data, calls=calls, injected=injected,
                               windows=observed_windows, budget=budget, error=error, report=c.report.currency_wars)

    def complete(self, source, target, *, slot=1, shop=False, native_failure=None, loss=False):
        def offer(selected=0):
            return modal(left=1 if slot == 1 else 3, right=3 if slot == 1 else 1, selected=selected)

        result = [loss_page(source), loss_page(source)] if loss else [current('node_result', source)]
        scenes = [*result, preparation(target), preparation(target), offer(), offer(), offer(slot), offer(slot),
                  preparation(target, overlay=True), preparation(target, shop=shop), preparation(target, shop=shop)]
        return self.run_path(source, scenes, native_failure=native_failure)

    def test_continue_two_card_choice_and_confirm_bind_an_arbitrary_adjacent_board(self):
        result = self.complete('1-3', '1-4', native_failure='holds')
        self.assertIsInstance(result.error, Stopped)
        self.assertEqual([intent for intent, _ in result.calls], [CONTINUE, SELECT, CONFIRM])
        self.assertEqual(result.injected, ['holds'])
        actions = result.data['actions']
        self.assertEqual(actions[1]['feedback']['page_kind'], OFFER)
        self.assertNotIn('node', actions[1]['feedback'])
        self.assertEqual(actions[2]['target'][-1], 1)
        self.assertEqual(actions[3]['feedback'], dict(page_kind='preparation', node='1-4', gold=9,
                                                      level=6, hp=100, deployment=[6, 6]))
        self.assertNotIn('reward_verified', actions[3])
        self.assertEqual(ledger_status(actions), 'clear')
        self.assertEqual(result.budget.window(result.data)['phase_node'], '1-4')
        self.assertTrue(all(window['phase_node'] is None for _, window, _ in result.windows))
        self.assertFalse(result.data['completion_verified'])

    def test_native_send_uses_current_readers_and_holds_both_arrival_images(self):
        from autohsr.tests.test_currency_wars_encounter import encounter

        source, target = '1-6', '1-7'
        modal_states = [encounter(selected=slot) for slot in (None, None, 1, 1)]
        for scene in modal_states:
            scene.tokens.append(UID)
        scenes = [current('node_result', source), preparation(target), *modal_states,
                  preparation(target), preparation(target)]
        result = self.run_path(source, scenes, actual_readers=True, native_failure='publish_holds')
        self.assertIsInstance(result.error, Stopped)
        self.assertEqual([intent for intent, _ in result.calls], [CONTINUE, SELECT, CONFIRM])
        self.assertEqual(result.injected, ['publish_holds'])
        self.assertEqual(result.data['actions'][-1]['feedback']['node'], target)

    def test_right_lower_after_loss_can_arrive_in_the_automatic_shop(self):
        result = self.complete('2-4', '2-5', slot=2, shop=True, loss=True)
        self.assertIsInstance(result.error, Stopped)
        self.assertEqual([intent for intent, _ in result.calls], [CONTINUE, SELECT, CONFIRM])
        attempt, = result.data['node_history']
        self.assertIs(attempt['node_loss_verified'], True)
        self.assertIs(attempt['node_verified'], False)
        self.assertEqual(result.data['actions'][2]['target'][-1], 2)
        self.assertEqual(result.data['actions'][3]['feedback']['page_kind'], 'shop')
        self.assertEqual(result.budget.window(result.data)['phase_node'], '2-5')
        self.assertEqual(next_action(preparation('2-5', shop=True), session=result.data).intent,
                         'close_standard_arrival_shop')

    def test_unknown_tied_changed_or_wrong_node_cards_do_not_select(self):
        for offer in (modal(left=2, right=2), modal(complete=False), modal(selected=1), modal(node='2-6')):
            with self.subTest(tokens=offer.tokens):
                result = self.run_path('2-4', [current('node_result', '2-4'), offer, offer])
                self.assertEqual([intent for intent, _ in result.calls], [CONTINUE])
                self.assertNotIn('node_history', result.data)
                with self.assertRaises(AutomationError):
                    require_session_access(result.data, True)

    def test_visible_encounter_without_current_original_receipt_does_not_click_a_card(self):
        result = self.run_path('1-6', [current('node_result', '1-6'), modal(), modal()], original=False)
        self.assertEqual([intent for intent, _ in result.calls], [CONTINUE])
        self.assertEqual(result.data['actions'][-1]['status'], 'unknown')
        self.assertNotIn('encounter', result.data['node_attempt'])
        orphan = self.run_path('1-6', [modal()])
        self.assertEqual(orphan.calls, [])
        self.assertNotIn('encounter', orphan.data['node_attempt'])

    def test_selected_frames_must_be_fresh_uninterrupted_and_match_the_frozen_cards(self):
        for interruption, stale in ((EmptyCapture('blank'), ()), (modal(left=2, selected=1), ()),
                                    (modal(selected=2), ()), (modal(selected=1), (6,))):
            with self.subTest(interruption=interruption, stale=stale):
                scenes = [current('node_result', '1-6'), modal(), modal(),
                          modal(selected=1), interruption]
                # The gap must leave only one fresh qualifying selection frame.
                if stale:
                    scenes.insert(3, EmptyCapture('blank'))
                result = self.run_path('1-6', [*scenes, modal(selected=1)] if not stale else scenes, stale=stale)
                self.assertEqual([intent for intent, _ in result.calls], [CONTINUE, SELECT])
                self.assertEqual(result.data['actions'][-1]['status'], 'unknown')
                self.assertNotIn('node_history', result.data)

    def test_confirm_does_not_accept_an_early_overlay_or_one_clean_frame(self):
        scenes = [current('node_result', '1-6'), modal(), modal(), modal(selected=1), modal(selected=1),
                  preparation('1-7'), preparation('1-7', overlay=True), preparation('1-7')]
        result = self.run_path('1-6', scenes)
        self.assertEqual([intent for intent, _ in result.calls], [CONTINUE, SELECT, CONFIRM])
        self.assertEqual(result.data['actions'][-1]['status'], 'unknown')
        self.assertNotIn('node_history', result.data)
        with self.assertRaises(AutomationError):
            require_session_access(result.data, True)

    def test_low_conflict_and_wrong_account_cannot_confirm(self):
        wrong = replace(UID, text='UID:200000000')
        conflict = modal(selected=1)
        conflict.tokens.append(replace(wrong, score=.74))
        other = modal(selected=1)
        other.tokens = [wrong if token == UID else token for token in other.tokens]
        for identity in (conflict, other):
            with self.subTest(identity=identity.tokens):
                scenes = [current('node_result', '1-6'), modal(), modal(), modal(selected=1),
                          identity, modal(selected=1)]
                result = self.run_path('1-6', scenes)
                self.assertEqual([intent for intent, _ in result.calls], [CONTINUE, SELECT])
                self.assertNotIn('node_history', result.data)

    def test_late_native_faults_preserve_the_single_pending_selection(self):
        for failure, error in (('epoch', InputInterrupted), ('focus', InputInterrupted),
                               ('f10', Stopped), ('evidence', AutomationError), ('intent', AutomationError)):
            with self.subTest(failure=failure):
                result = self.complete('1-6', '1-7', native_failure=failure)
                self.assertIsInstance(result.error, error)
                self.assertEqual(result.injected, [failure])
                self.assertEqual([intent for intent, _ in result.calls], [CONTINUE])
                self.assertEqual(result.data['actions'][-1]['status'], 'pending')
                self.assertEqual(result.data['actions'][-1]['target'][-1], 1)
                self.assertNotIn('node_history', result.data)

    def test_original_selection_file_replacement_blocks_confirm_and_receipt_write_never_replays(self):
        changed = self.complete('1-6', '1-7', native_failure='selected_evidence')
        self.assertEqual(changed.injected, ['selected_evidence'])
        self.assertEqual([intent for intent, _ in changed.calls], [CONTINUE, SELECT])
        self.assertEqual(changed.data['actions'][-1]['status'], 'pending')
        self.assertNotIn('node_history', changed.data)

        failed = self.complete('1-6', '1-7', native_failure='publish')
        self.assertIsInstance(failed.error, PermissionError)
        self.assertEqual([intent for intent, _ in failed.calls], [CONTINUE, SELECT, CONFIRM])
        self.assertEqual(failed.data['actions'][-1]['status'], 'pending')
        self.assertEqual(failed.report['actions'][-1]['status'], 'pending')
        self.assertNotIn('node_history', failed.data)
        with self.assertRaises(AutomationError):
            require_session_access(failed.data, True)

    def test_ordinary_exact_type_arrival_and_old_source_keep_the_original_progress(self):
        scene = preparation('3-4', known_type=True)
        self.assertEqual(read_match(scene).node, '3-4')
        result = self.run_path('3-3', [current('node_result', '3-3'), scene], original=False)
        self.assertIsInstance(result.error, Stopped)
        self.assertEqual([intent for intent, _ in result.calls], [CONTINUE])
        self.assertEqual(result.data['actions'][-1]['feedback'], dict(page_kind='preparation', node='3-4'))
