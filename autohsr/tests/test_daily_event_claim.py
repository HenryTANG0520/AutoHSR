"""4.6 single-day contract tests using fake Win32 and append-only receipts."""
import ctypes as C
from dataclasses import replace
from hashlib import sha256
import json
import mmap
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr import daily_event_claim as claim, windows
from autohsr.currency_wars_identity import UID_COUNTEREVIDENCE
from autohsr.daily_event_pages import _CENTERS
from autohsr.models import AutomationError, Scene, Stopped, Token
from autohsr.tests.test_daily_event_observe import ACCOUNT, OTHER
from autohsr.tests.test_daily_event_pages import _odyssey, _paint


def page(*, before=False, extra_claim=False):
    scene = _odyssey()
    if before:
        scene.tokens = [replace(token, text='领取') if token.text == '已领取' else token for token in scene.tokens]
        _paint(scene.image, (.512, .754, .590, .793), (208, 227, 246))
    if extra_claim:
        scene.tokens = [replace(token, text='已领取') if token.text == '领取' and .60 < token.center[0] < .68
                        else token for token in scene.tokens]
        _paint(scene.image, (.600, .754, .677, .793), (72, 98, 115))
    return scene


def day_cards(claimed):
    scene = _odyssey()
    scene.tokens = [token for token in scene.tokens if token.text not in ('领取', '已领取')]
    for day, (x, y) in enumerate(_CENTERS, 1):
        checked = day in claimed
        _paint(scene.image, (x - .039, y - .017, x + .039, y + .017),
               (72, 98, 115) if checked else (208, 227, 246))
        scene.tokens.append(Token('已领取' if checked else '领取', .97,
                                  (x - .018, y - .012, x + .018, y + .012)))
    return scene


def card_glyph(scene, day, kind):
    x, y = _CENTERS[day - 1][0], claim._MARK_Y[day - 1]
    target = claim._crop(scene.image, (x - .029, y - .031, x + .029, y + .031))
    tile = np.full((24, 36, 3), (72, 98, 115), np.uint8)
    white = (230, 230, 230)
    if kind == 'stripe':
        cv2.line(tile, (14, 14), (22, 8), white, 2)
    elif kind in ('check', 'mirror'):
        cv2.line(tile, (14, 12), (17, 14), white, 2)
        cv2.line(tile, (17, 14), (22, 8), white, 2)
        if kind == 'mirror':
            tile = tile[:, ::-1]
    target[:] = cv2.resize(tile, (target.shape[1], target.shape[0]), interpolation=cv2.INTER_NEAREST)


def popup():
    image = np.full((540, 960, 3), (45, 56, 61), np.uint8)
    _paint(image, (.480, .443, .520, .535), (112, 167, 204))
    _paint(image, (.498, .541, .503, .556), (209, 225, 242))
    return Scene([
        Token('获得物品', .98, (.473, .144, .527, .178)),
        Token('星轨专票', .94, (.480, .563, .522, .589)),
        Token('点击空白处关闭', .94, (.455, .718, .546, .745)),
    ], image)


def digits(first, second=None):
    return Mock(side_effect=(Token(str(first), .94, (0, 0, 1, 1)),
                             Token(str(first if second is None else second), .95, (0, 0, 1, 1))))


class DailyEventClaimTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.
        clock = SimpleNamespace(monotonic=lambda: self.now)
        for module in ('autohsr.daily_event_claim', 'autohsr.challenge_pages'):
            self.enterContext(patch(module + '.time', clock))
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.folder = self.root / 'private-ledger'
        self.folder.mkdir()
        self.exe = self.root / 'StarRail.exe'
        self.exe.write_bytes(b'fixture only')
        self.config = self.exe.with_name('config.ini')
        self.config.write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        self.geometry = windows.Geometry(20, 30, 960, 540)
        self.window = windows.GameWindow.__new__(windows.GameWindow)
        self.window.hwnd, self.window.identity = 41, 'synthetic-private-window-key'
        self.window.current_window_key = Mock(side_effect=lambda: self.window.identity)
        self.window.current_executable = Mock(return_value=str(self.exe))
        self.packets = []
        self.accepted = 3
        self.native = SimpleNamespace(IsWindow=Mock(return_value=True), IsIconic=Mock(return_value=False),
                                      GetForegroundWindow=Mock(return_value=self.window.hwnd),
                                      GetAsyncKeyState=Mock(return_value=0), SendInput=Mock(side_effect=self.send_input),
                                      GetSystemMetrics={76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__)
        self.enterContext(patch.object(windows, 'user32', self.native))
        self.enterContext(patch.object(windows, 'geometry', return_value=self.geometry))
        self.runner = SimpleNamespace(_foreground_only=True, input_epoch=3, stop_requested=False)
        self.context = SimpleNamespace(window=self.window, runner=self.runner, capture_sequence=0, scene_epoch=3,
                                       capture_occlusion_count=0,
                                       report=SimpleNamespace(operation=claim.OPERATION),
                                       last_scene=None, _scroll_anchor=object(), settings=SimpleNamespace(ocr_confidence=.65),
                                       vision=SimpleNamespace(confidence=.65),
                                       checkpoint=Mock())
        self.checkpoint = Mock()
        for name in ('focus', 'capture', 'key', 'move', 'drag', 'scroll'):
            action = Mock(side_effect=AssertionError('the candidate must use only its native click'))
            setattr(self.window, name, action)
            self.addCleanup(action.assert_not_called)

    def send_input(self, count, items, size):
        self.assertEqual(size, C.sizeof(windows.INPUT))
        events = C.cast(items, C.POINTER(windows.INPUT))
        self.packets.append(tuple((events[index].mi.dwFlags, events[index].mi.dx, events[index].mi.dy)
                                  for index in range(count)))
        return self.accepted if count == 3 else count

    def bind(self, scene, *, day=4, account=ACCOUNT, quantity_reader=None, text_reader=None):
        self.now += .15
        scene.geometry = self.geometry
        scene.captured_at = self.now - .01
        if account is not None:
            scene.tokens.append(account)
        self.context.capture_sequence += 1
        self.context.scene_epoch = self.runner.input_epoch
        self.context.last_scene = scene
        return claim.bind_current_claim_frame(self.context, day=day, quantity_reader=quantity_reader,
                                              text_reader=text_reader)

    def before(self):
        return self.bind(page(before=True)), self.bind(page(before=True))

    def prepare(self, before=None):
        return claim.prepare_claim(self.folder, before or self.before(), day=4, checkpoint=self.checkpoint)

    def submitted(self):
        before = self.before()
        intent = self.prepare(before)
        intent.submit(self.context)
        return intent

    def receipt_pair(self, amount=1, *, day=4, account=ACCOUNT):
        return tuple(self.bind(popup(), day=day, account=account, quantity_reader=digits(amount)) for _ in range(2))

    def after(self, *, extra_claim=False, before=False):
        return tuple(self.bind(page(before=before, extra_claim=extra_claim)) for _ in range(2))

    def files(self):
        return {path.name: path.read_bytes() for path in self.folder.iterdir()}

    def bind_cards(self, day, claimed):
        return tuple(self.bind(day_cards(claimed), day=day) for _ in range(2))

    def test_real_click_consumes_one_reservation_with_sources_held(self):
        before = self.before()
        intent = self.prepare(before)
        pending_path, = self.folder.iterdir()
        pending = pending_path.read_bytes()
        config = self.config.read_bytes()

        def send_with_locks(count, items, size):
            reserved, = self.folder.glob('*.reserved.json')
            self.assertEqual({json.loads(raw)['state'] for raw in self.files().values()}, {'pending', 'reserved'})
            self.assertTrue(all(not frame.image.flags.writeable for frame in before))
            for source in (pending_path, reserved, self.config):
                with self.assertRaises(OSError):
                    source.write_bytes(b'forbidden while the exact click is in flight')
            with self.assertRaises(AutomationError):
                intent.submit(self.context)
            return self.send_input(count, items, size)

        self.native.SendInput.side_effect = send_with_locks
        intent.submit(self.context)
        x, y = before[-1].button.center
        px, py = self.geometry.left + round(x * 959), self.geometry.top + round(y * 539)
        self.assertEqual(self.packets, [((0xC001, round(px * 65535 / 1919), round(py * 65535 / 1079)),
                                         (2, 0, 0), (4, 0, 0))])
        self.assertEqual(pending_path.read_bytes(), pending)
        self.assertEqual(self.config.read_bytes(), config)
        self.assertTrue(all(frame.image.flags.writeable for frame in before))
        reserved, = self.folder.glob('*.reserved.json')
        sent, = self.folder.glob('*.submitted.json')
        self.assertEqual(json.loads(sent.read_bytes())['authorization_sha256'], sha256(reserved.read_bytes()).hexdigest())
        self.assertIsNone(self.context.last_scene)
        self.assertIsNone(self.context._scroll_anchor)
        with self.assertRaises(AutomationError):
            intent.submit(self.context)
        self.native.SendInput.assert_called_once()

    def test_caller_cannot_supply_an_ack_or_replace_the_native_sender(self):
        intent = self.prepare()
        original = self.files()
        self.assertFalse(hasattr(intent, 'note_submission'))
        with self.assertRaises(TypeError):
            intent.submit(self.context, accepted_count=3)
        with self.assertRaises(AutomationError):
            intent.submit(SimpleNamespace())
        with patch.object(self.window, 'send', return_value=None) as pretend_send:
            with self.assertRaises(AutomationError):
                intent.submit(self.context)
            pretend_send.assert_not_called()
        self.native.SendInput.assert_not_called()
        self.assertEqual(self.files(), original)
        with patch.object(self.window, 'click', return_value=None) as pretend_click:
            intent.submit(self.context)
            pretend_click.assert_not_called()
        self.native.SendInput.assert_called_once()

    def test_writable_mapping_on_installation_or_intent_prevents_submission(self):
        intent = self.prepare()
        original = self.files()
        pending, = self.folder.iterdir()
        for source in (pending, self.config):
            with self.subTest(source=source.name):
                with source.open('r+b') as stream:
                    writable = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_WRITE)
                with writable, self.assertRaises(OSError):
                    intent.submit(self.context)
        self.assertEqual(self.files(), original)
        self.native.SendInput.assert_not_called()

    def test_intent_replaced_with_identical_bytes_is_not_the_original(self):
        intent = self.prepare()
        pending, = self.folder.iterdir()
        raw = pending.read_bytes()
        substitute = self.root / 'substitute.json'
        substitute.write_bytes(raw)
        os.replace(substitute, pending)
        with self.assertRaisesRegex(AutomationError, '原意图文件已变化'):
            intent.submit(self.context)
        self.assertEqual(self.files(), {pending.name: raw})
        self.native.SendInput.assert_not_called()

    def test_receipt_appearing_after_reservation_vetoes_the_actual_native_hook(self):
        intent = self.prepare()
        pending, = self.folder.iterdir()
        external = pending.with_suffix('.submitted.json')
        competing = b'existing unverified submission receipt'
        with patch.object(windows, 'require_followup_week', side_effect=lambda: external.write_bytes(competing)):
            with self.assertRaises(AutomationError):
                intent.submit(self.context)
        self.assertEqual(external.read_bytes(), competing)
        self.native.SendInput.assert_not_called()

    def test_short_zero_or_move_only_leaves_pending_without_release(self):
        for count in (0, 1):
            with self.subTest(count=count):
                self.folder = self.root / str(count)
                self.folder.mkdir()
                self.accepted = count
                native_before = len(self.packets)
                intent = self.prepare()
                with self.assertRaisesRegex(AutomationError, 'Windows 拒绝'):
                    intent.submit(self.context)
                self.assertEqual([len(packet) for packet in self.packets[native_before:]], [3])
                self.assertEqual({json.loads(raw)['state'] for raw in self.files().values()}, {'pending', 'reserved'})

    def test_actual_last_window_check_cannot_hide_a_changed_generation_or_frame(self):
        for changed in ('generation', 'old_frame'):
            with self.subTest(changed=changed):
                self.folder = self.root / changed
                self.folder.mkdir()
                before = self.before()
                intent = self.prepare(before)
                armed = False
                checks = 0

                def enters_native_hook():
                    nonlocal armed
                    armed = True

                def foreground():
                    nonlocal checks
                    if armed:
                        checks += 1
                        if checks == 3:
                            if changed == 'generation':
                                self.runner.input_epoch += 1
                            else:
                                before[0].scene.tokens.append(OTHER)
                    return self.window.hwnd

                self.native.GetForegroundWindow.side_effect = foreground
                try:
                    with patch.object(windows, 'require_followup_week', side_effect=enters_native_hook):
                        with self.assertRaises(AutomationError):
                            intent.submit(self.context)
                finally:
                    self.native.GetForegroundWindow.side_effect = None
                self.assertEqual(checks, 3)
                self.native.SendInput.assert_not_called()
                self.assertEqual({json.loads(raw)['state'] for raw in self.files().values()}, {'pending', 'reserved'})

    def test_late_f10_before_native_sends_nothing_and_consumed_intent_is_never_replayed(self):
        intent = self.prepare()
        with patch.object(windows, 'require_followup_week',
                          side_effect=lambda: setattr(self.native.GetAsyncKeyState, 'return_value', 1)):
            with self.assertRaises(Stopped):
                intent.submit(self.context)
        self.native.GetAsyncKeyState.return_value = 0
        self.native.SendInput.assert_not_called()
        original = self.files()
        self.assertEqual({json.loads(raw)['state'] for raw in original.values()}, {'pending', 'reserved'})
        with self.assertRaises(AutomationError):
            intent.submit(self.context)
        self.assertEqual(self.files(), original)
        self.native.SendInput.assert_not_called()

    def test_receipt_publication_failure_after_full_batch_keeps_the_one_attempt_pending(self):
        intent = self.prepare()
        rename = os.rename

        def fail_submission(source, destination):
            if Path(destination).name.endswith('.submitted.json'):
                raise OSError('synthetic receipt publication failure')
            return rename(source, destination)

        with patch('autohsr.warp_service.os.rename', side_effect=fail_submission), self.assertRaises(OSError):
            intent.submit(self.context)
        self.native.SendInput.assert_called_once()
        self.assertIsNone(self.context.last_scene)
        original = self.files()
        self.assertEqual({json.loads(raw)['state'] for raw in original.values()}, {'pending', 'reserved'})
        with self.assertRaises(AutomationError):
            intent.submit(self.context)
        self.assertEqual(self.files(), original)
        self.native.SendInput.assert_called_once()

    def test_each_supported_day_keeps_its_own_amount_and_receipt(self):
        expected = ((3, 2), (4, 1), (5, 1), (6, 1), (7, 3))
        for day, quantity in expected:
            with self.subTest(day=day):
                earlier = self.files()
                old_cards = set(range(1, day))
                before = self.bind_cards(day, old_cards)
                intent = claim.prepare_claim(self.folder, before, day=day, checkpoint=self.checkpoint)
                intent.submit(self.context)
                reward = self.receipt_pair(quantity, day=day)
                after = self.bind_cards(day, old_cards | {day})
                result = intent.verify(reward, after, checkpoint=self.checkpoint)
                self.assertEqual((result['day'], result['quantity'], result['state']), (day, quantity, 'verified'))
                files = self.files()
                self.assertEqual({name: files[name] for name in earlier}, earlier)
                self.assertEqual(len(files) - len(earlier), 4)

    def test_first_two_days_and_non_integer_choices_are_outside_scope(self):
        before = self.before()
        scene = day_cards(())
        scene.captured_at = self.now
        for day in (1, 2, 8, 4.0, True, '4', None):
            with self.subTest(day=day):
                self.assertIsNone(claim.read_day_button(scene, day=day, client_version='4.6.0'))
                with self.assertRaises(AutomationError):
                    claim.prepare_claim(self.folder, before, day=day, checkpoint=self.checkpoint)
        self.assertEqual(self.files(), {})

    def test_same_amount_cannot_borrow_another_selected_day_or_card(self):
        for wrong in ('modal_scope', 'claimed_card', 'both_cards'):
            with self.subTest(wrong=wrong):
                self.folder = self.root / wrong
                self.folder.mkdir()
                day = 5
                old_cards = {1, 2, 3, 4}
                before = self.bind_cards(day, old_cards)
                intent = claim.prepare_claim(self.folder, before, day=day, checkpoint=self.checkpoint)
                intent.submit(self.context)
                original = self.files()
                reward = self.receipt_pair(1, day=6 if wrong == 'modal_scope' else day)
                extra = {day} if wrong == 'modal_scope' else {6} if wrong == 'claimed_card' else {day, 6}
                after = self.bind_cards(day, old_cards | extra)
                with self.assertRaises(AutomationError):
                    intent.verify(reward, after, checkpoint=self.checkpoint)
                self.assertEqual(self.files(), original)

    def test_anchored_dark_card_requires_the_check_shape_or_an_exact_label(self):
        before = self.bind_cards(3, {1, 2})
        intent = claim.prepare_claim(self.folder, before, day=3, checkpoint=self.checkpoint)
        intent.submit(self.context)
        reward = self.receipt_pair(2, day=3)

        def day_three(kind, conflicting=False):
            scene = day_cards({1, 2, 3})
            selected = next(token for token in scene.tokens if token.text == '已领取'
                            and token.within((.70, .52, .75, .58)))
            scene.tokens.remove(selected)
            if conflicting:
                scene.tokens.append(replace(selected, text='领取', score=.68))
            card_glyph(scene, 3, kind)
            return scene

        after = tuple(self.bind(day_three('check'), day=3) for _ in range(2))
        result = intent.verify(reward, after, checkpoint=self.checkpoint)
        self.assertEqual((result['day'], result['quantity']), (3, 2))
        for kind, conflicting in (('none', False), ('stripe', False), ('mirror', False), ('check', True)):
            with self.subTest(kind=kind, conflicting=conflicting):
                frame = self.bind(day_three(kind, conflicting), day=3)
                self.assertIn(3, frame.page.unknown_days)
        active = day_cards({1, 2})
        card_glyph(active, 3, 'check')
        frame = self.bind(active, day=3)
        self.assertIsNone(frame.button)
        self.assertIn(3, frame.page.unknown_days)

    def test_a_local_other_card_read_does_not_supply_a_claim_target(self):
        def low_active():
            scene = day_cards({1, 2, 3, 4})
            scene.tokens = [replace(token, score=.72) if token.text == '领取'
                            and token.within((.60, .75, .67, .80)) else token for token in scene.tokens]
            return scene

        reader = Mock(return_value=Token('领取', .92, (0, 0, 1, 1)))
        before = tuple(self.bind(low_active(), day=5, text_reader=reader) for _ in range(2))
        self.assertTrue(all(5 in frame.page.claimable_days and frame.button is None for frame in before))
        with self.assertRaises(AutomationError):
            claim.prepare_claim(self.folder, before, day=5, checkpoint=self.checkpoint)
        contradictory = low_active()
        card_glyph(contradictory, 5, 'check')
        frame = self.bind(contradictory, day=5, text_reader=reader)
        self.assertIn(5, frame.page.unknown_days)
        self.assertEqual(self.files(), {})

    def test_compressed_popup_needs_both_local_suffix_reads_and_the_same_item(self):
        scene = popup()
        scene.captured_at = self.now
        scene.tokens = [replace(token, score=.73) if token.text == claim.ITEM else
                        replace(token, text='点出登白处关闭', score=.81) if token.text == '点击空白处关闭' else token
                        for token in scene.tokens]

        def local(_image, text):
            return Token(text, .94, (0, 0, 1, 1))

        reader = Mock(side_effect=local)
        self.assertEqual(claim.read_ticket_popup(scene, quantity_reader=digits(1), text_reader=reader), 1)
        self.assertEqual([call.args[1] for call in reader.call_args_list], [claim.ITEM, '白处关闭', '白处关闭'])
        self.assertIsNone(claim.read_ticket_popup(scene, quantity_reader=digits(1)))
        mixed = Mock(side_effect=(local(None, claim.ITEM), local(None, '白处关闭'), local(None, '白处继续')))
        self.assertIsNone(claim.read_ticket_popup(scene, quantity_reader=digits(1), text_reader=mixed))
        wrong = replace(scene, tokens=[replace(token, text='潮玩礼券') if token.text == claim.ITEM else token
                                       for token in scene.tokens])
        self.assertIsNone(claim.read_ticket_popup(wrong, quantity_reader=digits(1), text_reader=local))
        scene.tokens.append(Token('点击空白处关闭', .89, (.455, .718, .546, .745)))
        self.assertIsNone(claim.read_ticket_popup(scene, quantity_reader=digits(1), text_reader=local))

    def test_exact_card_and_item_produce_a_separate_verified_receipt(self):
        intent = self.submitted()
        pending_files = self.files()
        self.assertEqual(len(pending_files), 3)
        reward = self.receipt_pair()
        after = self.after()
        result = intent.verify(reward, after, checkpoint=self.checkpoint)
        self.assertEqual(result, dict(schema=1, state='verified', activity=claim.ACTIVITY, client_version='4.6.0',
                                      day=4, button_observed=True, submission_acknowledged=True,
                                      item='星轨专票', quantity=1, same_card_claimed=True))
        files = self.files()
        self.assertEqual({name: files[name] for name in pending_files}, pending_files)
        self.assertEqual(len(files), 4)
        self.assertEqual(json.loads(next(raw for name, raw in files.items() if '.verified.' in name)), result)
        for raw in files.values():
            for private in (ACCOUNT.text, str(self.exe), self.window.identity):
                self.assertNotIn(private.encode(), raw)

    def test_pure_popup_requires_exact_quantity_and_single_visible_tile(self):
        valid = popup()
        valid.captured_at = self.now
        read = digits(1)
        self.assertEqual(claim.read_ticket_popup(valid, quantity_reader=read), 1)
        self.assertTrue(all(call.args[0].shape == (60, 84, 3) for call in read.call_args_list))
        self.assertEqual(claim.read_ticket_popup(valid, quantity_reader=digits(3)), 3)
        self.assertIsNone(claim.read_ticket_popup(valid, quantity_reader=digits(1, 3)))
        other = Token('潮玩礼券', .98, (.480, .563, .522, .589))
        wrong = replace(valid, tokens=[other if token.text == claim.ITEM else token for token in valid.tokens])
        self.assertIsNone(claim.read_ticket_popup(wrong, quantity_reader=digits(1)))
        _paint(valid.image, (.344, .445, .375, .536), (112, 167, 204))
        self.assertIsNone(claim.read_ticket_popup(valid, quantity_reader=digits(1)))

    def test_wrong_day_or_absent_enabled_button_creates_no_intent(self):
        before = self.before()
        with self.assertRaises(AutomationError):
            claim.prepare_claim(self.folder, before, day=5, checkpoint=self.checkpoint)
        frames = self.after()
        with self.assertRaises(AutomationError):
            self.prepare(frames)
        self.assertEqual(self.files(), {})

    def test_high_collection_floor_cannot_hide_weak_conflicting_account_evidence(self):
        self.context.vision.confidence = .85
        with self.assertRaises(AutomationError):
            self.bind(page(before=True))
        self.assertEqual(self.files(), {})

    def test_unknown_submission_and_restart_do_not_allow_another_intent(self):
        frames = self.before()
        intent = self.prepare(frames)
        original = self.files()
        self.accepted = 2
        with self.assertRaisesRegex(AutomationError, 'Windows 拒绝'):
            intent.submit(self.context)
        self.assertEqual([len(packet) for packet in self.packets], [3, 1])
        self.assertEqual(self.packets[-1], ((4, 0, 0),))
        self.assertIsNone(self.context.last_scene)
        self.assertTrue(all(frame.image.flags.writeable for frame in frames))
        pending = self.files()
        self.assertEqual({name: pending[name] for name in original}, original)
        self.assertEqual({json.loads(raw)['state'] for raw in pending.values()}, {'pending', 'reserved'})
        with self.assertRaises(AutomationError):
            intent.submit(self.context)
        with self.assertRaises(AutomationError):
            intent.verify(self.receipt_pair(), self.after(), checkpoint=self.checkpoint)
        self.context = SimpleNamespace(**{**vars(self.context), 'capture_sequence': 0, 'last_scene': None})
        self.window.identity = 'new-synthetic-window'
        with self.assertRaises(AutomationError):
            self.prepare()
        self.assertEqual(len(self.packets), 2)
        self.assertEqual(self.files(), pending)

    def test_wrong_quantity_multiple_changed_cards_and_unchanged_card_stay_pending(self):
        for reason in ('quantity', 'more_cards', 'unchanged'):
            with self.subTest(reason=reason):
                self.folder = self.root / reason
                self.folder.mkdir()
                intent = self.submitted()
                original = self.files()
                reward = self.receipt_pair(3 if reason == 'quantity' else 1)
                after = self.after(extra_claim=reason == 'more_cards', before=reason == 'unchanged')
                with self.assertRaises(AutomationError):
                    intent.verify(reward, after, checkpoint=self.checkpoint)
                self.assertEqual(self.files(), original)

    def test_account_change_or_missing_uid_never_finishes_an_existing_intent(self):
        intent = self.submitted()
        original = self.files()
        with self.assertRaises(AutomationError):
            self.bind(popup(), account=None, quantity_reader=digits(1))
        conflict = popup()
        conflict.field_reads[UID_COUNTEREVIDENCE] = (replace(OTHER, score=.74),)
        with self.assertRaises(AutomationError):
            self.bind(conflict, quantity_reader=digits(1))
        reward = self.receipt_pair(account=OTHER)
        after = self.after()
        with self.assertRaises(AutomationError):
            intent.verify(reward, after, checkpoint=self.checkpoint)
        self.assertEqual(self.files(), original)

    def test_an_intervening_capture_cannot_reuse_a_later_single_ticket_popup(self):
        intent = self.submitted()
        original = self.files()
        self.bind(page())
        reward = self.receipt_pair()
        with self.assertRaises(AutomationError):
            intent.verify(reward, self.after(), checkpoint=self.checkpoint)
        self.assertEqual(self.files(), original)

    def test_modified_intent_is_preserved_without_submitted_marker(self):
        frames = self.before()
        intent = self.prepare(frames)
        path, = self.folder.iterdir()
        path.write_bytes(b'external-original-bytes')
        with self.assertRaises(AutomationError):
            intent.submit(self.context)
        self.native.SendInput.assert_not_called()
        self.assertEqual(self.files(), {path.name: b'external-original-bytes'})

    def test_late_stop_or_installation_rewrite_cannot_verify(self):
        for state in ('stopped', 'installation'):
            with self.subTest(state=state):
                self.folder = self.root / state
                self.folder.mkdir()
                intent = self.submitted()
                original = self.files()
                reward = self.receipt_pair()
                after = self.after()
                if state == 'stopped':
                    self.native.GetAsyncKeyState.return_value = 1
                    error = Stopped
                else:
                    self.config.write_text('[General]\ngame_version=4.6.0\nchanged=1\n', encoding='utf8')
                    error = AutomationError
                try:
                    with self.assertRaises(error):
                        intent.verify(reward, after, checkpoint=self.checkpoint)
                finally:
                    self.native.GetAsyncKeyState.return_value = 0
                self.assertEqual(self.files(), original)

    def test_last_window_guard_cannot_hide_generation_or_source_changes(self):
        for drift in ('epoch', 'occlusion', 'pixels'):
            with self.subTest(drift=drift):
                self.folder = self.root / drift
                self.folder.mkdir()
                intent = self.submitted()
                original = self.files()
                reward = self.receipt_pair()
                after = self.after()
                guard = self.window.guard
                explicit_checks = 0

                def change(expected=None):
                    nonlocal explicit_checks
                    result = guard(expected)
                    if expected is not None:
                        explicit_checks += 1
                    if expected is not None and explicit_checks == 6:
                        if drift == 'epoch':
                            self.runner.input_epoch += 1
                        elif drift == 'occlusion':
                            self.context.capture_occlusion_count += 1
                        else:
                            reward[0].scene.image[0, 0] = 0
                    return result

                with patch.object(self.window, 'guard', side_effect=change), self.assertRaises(AutomationError):
                    intent.verify(reward, after, checkpoint=self.checkpoint)
                self.assertEqual(explicit_checks, 6)
                self.assertEqual(self.files(), original)

    def test_pending_publication_race_keeps_the_competing_bytes(self):
        before = self.before()
        rename = os.rename

        def compete(source, destination):
            Path(destination).write_bytes(b'existing-pending')
            return rename(source, destination)

        with patch('autohsr.warp_service.os.rename', side_effect=compete), self.assertRaises(AutomationError):
            self.prepare(before)
        raw, = self.files().values()
        self.assertEqual(raw, b'existing-pending')


if __name__ == '__main__':
    unittest.main()
