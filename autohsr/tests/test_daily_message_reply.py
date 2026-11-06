from dataclasses import replace
from hashlib import sha256
from itertools import count
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import daily_message_reply as reply
from autohsr.daily_message_reply_store import ReplyStore
from autohsr.models import AutomationError, EmptyCapture, FocusLost, Token
from autohsr.storage import replace_file
from autohsr.tests.test_daily_message_observe import ACCOUNT, OTHER, STATE_FIXTURES, state_frame
from autohsr.windows import Geometry


FIXTURES = STATE_FIXTURES.with_name('daily_message_reply')
_SYNTHETIC_STARTER = '合成前置行'
_SYNTHETIC_OPTIONS = ('合成选项甲', '合成选项乙', '合成选项丙')
_SYNTHETIC_OUTGOING = _SYNTHETIC_OPTIONS[0] + '。'


def token(text, xyxy, score=.99):
    return Token(text, score, tuple(value / size for value, size in zip(xyxy, (1280, 720) * 2)))


def replay_frames():
    rows = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf8'))['frames']
    for row in rows:
        before = row['phase'] == 'before'
        fields = [ACCOUNT, token('甲乙', (275, 191, 313, 212)), token('甲乙', (531, 125, 576, 151)),
                  token(_SYNTHETIC_STARTER, (633, 260, 912, 283) if before else (634, 337, 911, 356))]
        if before:
            fields.extend(token(label, box) for label, box in zip(_SYNTHETIC_OPTIONS,
                          ((736, 471, 864, 497), (729, 517, 863, 539), (738, 560, 862, 582))))
        else:
            # The left list preview may repeat the new text. It is outside chat.
            fields.extend((token(_SYNTHETIC_OUTGOING, (819, 561, 946, 583)),
                           token(_SYNTHETIC_OUTGOING, (274, 210, 401, 233))))
        yield state_frame(row['file'], *fields, directory=FIXTURES)


class OfflineReplyContext:
    def __init__(self, frames, executable):
        self.frames = iter(frames)
        self.geometry = Geometry(0, 0, 1920, 1080)
        self.window = SimpleNamespace(guard=Mock(return_value=self.geometry),
                                      current_window_key=Mock(return_value='offline-window'),
                                      current_executable=Mock(return_value=executable),
                                      emergency_pressed=Mock(return_value=False))
        self.runner = SimpleNamespace(_foreground_only=True, input_epoch=0, stop_requested=False)
        self.report = SimpleNamespace(operation=reply.OPERATION)
        self.settings = SimpleNamespace(ocr_confidence=.85)
        self.vision = SimpleNamespace(confidence=.65)
        self.checkpoint, self.sleep = Mock(), Mock()
        self.last_scene = None
        self.scene_epoch = self.capture_sequence = self.capture_occlusion_count = 0

    def snapshot(self):
        frame = next(self.frames, None)
        if frame is None:
            raise EmptyCapture('offline sequence ended')
        self.capture_sequence += 1
        self.last_scene = replace(frame, geometry=self.geometry, captured_at=time.monotonic())
        return self.last_scene


class SingleReplyTests(unittest.TestCase):
    def setUp(self):
        ticks = count(100., .01)
        self.enterContext(patch('time.monotonic', side_effect=lambda: next(ticks)))
        self.enterContext(patch.multiple(reply, _STARTER=reply._text_digest(_SYNTHETIC_STARTER),
                                        _CHOICES=tuple((item, reply._text_digest(label)) for (item, _), label in
                                                       zip(reply._CHOICES, _SYNTHETIC_OPTIONS)),
                                        _OUTGOING=reply._text_digest(_SYNTHETIC_OUTGOING)))
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.executable = self.root / 'StarRail.exe'
        self.executable.touch()
        self.executable.with_name('config.ini').write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        self.directory = self.root / 'reply-records'
        self.clicks = []

    def context(self, frames=None):
        return OfflineReplyContext(replay_frames() if frames is None else frames, self.executable)

    def records(self):
        return [json.loads(path.read_text(encoding='ascii')) for path in self.directory.glob('reply-*.json')]

    def submit(self, scene, point, *, before_submit):
        before_submit()
        self.assertEqual([row['status'] for row in self.records()], ['pending'])
        self.clicks.append((scene, point))

    def run_reply(self, context=None, *, submit=None, item_id=reply._ITEM):
        reply.reply_once(self.context() if context is None else context, ReplyStore(self.directory),
                         item_id=item_id, submit=self.submit if submit is None else submit)

    def test_reply_confirms_after_two_new_right_bubbles_and_cannot_replay(self):
        context = self.context()
        self.run_reply(context)
        self.assertEqual(context.capture_sequence, 4)
        self.assertEqual(len(self.clicks), 1)
        scene, point = self.clicks[0]
        self.assertEqual(point, scene.tokens[4].center)
        records = self.records()
        self.assertEqual([row['status'] for row in records], ['confirmed'])
        self.assertEqual(set(records[0]), {'schema', 'attempt', 'section', 'status'})
        with self.assertRaisesRegex(AutomationError, '已有回复记录'):
            self.run_reply()
        self.assertEqual(len(self.clicks), 1)

    def test_ambiguous_wrong_conversation_or_old_outgoing_never_submits(self):
        first, second, *_ = replay_frames()
        fields = second.tokens
        cases = (
            [*fields, replace(fields[4], score=.70)],
            [fields[0], fields[1], replace(fields[2], text='另一标题'), *fields[3:]],
            [*fields[:1], *(replace(t, text='另一标题') for t in fields[1:3]), *fields[3:]],
            [*fields[:4], replace(fields[4], text=_SYNTHETIC_OPTIONS[1]), *fields[5:]],
            [*fields, token(_SYNTHETIC_OUTGOING, (819, 380, 946, 405), score=.70)],
            [OTHER, *fields[1:]],
        )
        for index, labels in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(AutomationError):
                    self.run_reply(self.context((first, replace(second, tokens=labels))))
        self.assertEqual(self.clicks, [])
        self.assertEqual(self.records(), [])

    def test_other_item_and_unsupported_version_do_not_capture(self):
        context = self.context()
        for item in (None, True, 202490005):
            with self.assertRaisesRegex(AutomationError, '明确选择'):
                self.run_reply(context, item_id=item)
        self.executable.with_name('config.ini').write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
        with self.assertRaisesRegex(AutomationError, '尚未校准'):
            self.run_reply(context)
        self.assertEqual(context.capture_sequence, 0)
        self.assertEqual(self.records(), [])

    def test_option_echo_left_preview_or_missing_surface_leaves_pending_and_blocks_restart(self):
        first, second, after, final = replay_frames()
        echo = replace(after, tokens=[*after.tokens[:4], replace(after.tokens[4], text=_SYNTHETIC_OPTIONS[0]),
                                     after.tokens[-1]])
        preview = replace(final, tokens=[*final.tokens[:4], final.tokens[-1]])
        no_surface = replace(final, image=final.image.copy())
        no_surface.image[824:856, 1260:1408] = 210
        context = self.context([first, second, echo, preview, no_surface, final, preview, after])
        with self.assertRaisesRegex(AutomationError, '连续发出反馈'):
            self.run_reply(context)
        self.assertEqual([row['status'] for row in self.records()], ['pending'])
        with self.assertRaisesRegex(AutomationError, '已有回复记录'):
            self.run_reply()
        self.assertEqual(len(self.clicks), 1)

    def test_wrong_account_or_conversation_after_click_keeps_pending(self):
        first, second, after, _ = replay_frames()
        other_header = [replace(t, text='不同会话') for t in after.tokens[1:3]]
        for fields in ([OTHER, *after.tokens[1:]], [ACCOUNT, *other_header, *after.tokens[3:]]):
            with self.subTest(account_changed=fields[0] is OTHER):
                self.directory = self.root / ('other-account' if fields[0] is OTHER else 'other-conversation')
                with self.assertRaises(AutomationError):
                    self.run_reply(self.context((first, second, replace(after, tokens=fields))))
                self.assertEqual([row['status'] for row in self.records()], ['pending'])
        self.assertEqual(len(self.clicks), 2)

    def test_write_failure_prevents_click_and_partial_submit_keeps_pending(self):
        with patch('autohsr.daily_message_reply_store._publish', side_effect=OSError('offline disk error')):
            with self.assertRaisesRegex(AutomationError, '无法保存'):
                self.run_reply()
        self.assertEqual(self.clicks, [])

        def partial(scene, point, *, before_submit):
            self.submit(scene, point, before_submit=before_submit)
            raise AutomationError('offline partial click batch')

        with self.assertRaisesRegex(AutomationError, 'partial click'):
            self.run_reply(submit=partial)
        self.assertEqual([row['status'] for row in self.records()], ['pending'])
        with self.assertRaisesRegex(AutomationError, '已有回复记录'):
            self.run_reply()
        self.assertEqual(len(self.clicks), 1)

    def test_missing_callback_cannot_reserve_after_submission_returns(self):
        deferred = Mock()
        with self.assertRaisesRegex(AutomationError, '缺少本次'):
            self.run_reply(submit=deferred)
        hook = deferred.call_args.kwargs['before_submit']
        with self.assertRaises(AutomationError):
            hook()
        self.assertEqual(self.records(), [])

    def test_second_callback_cannot_record_another_click(self):
        def repeated(scene, point, *, before_submit):
            self.submit(scene, point, before_submit=before_submit)
            self.submit(scene, point, before_submit=before_submit)

        with self.assertRaisesRegex(AutomationError, '一次性'):
            self.run_reply(submit=repeated)
        self.assertEqual([row['status'] for row in self.records()], ['pending'])
        self.assertEqual(len(self.clicks), 1)

    def test_late_focus_loss_during_confirmation_preserves_pending(self):
        context = self.context()

        def lose_focus_on_final_replace(source, destination, **kwargs):
            if not kwargs['exclusive']:
                context.window.guard.side_effect = FocusLost('offline late focus loss')
            return replace_file(source, destination, **kwargs)

        with patch('autohsr.daily_message_reply_store.replace_file', side_effect=lose_focus_on_final_replace):
            with self.assertRaises(FocusLost):
                self.run_reply(context)
        self.assertEqual([row['status'] for row in self.records()], ['pending'])
        self.assertEqual(len(self.clicks), 1)

    def test_persisting_intent_does_not_allow_a_click_after_late_focus_loss(self):
        context = self.context()

        def reserve_then_lose_focus(store, account_key, section):
            reservation = reserve(store, account_key, section)
            context.window.guard.side_effect = FocusLost('offline focus loss after persisting')
            return reservation

        reserve = ReplyStore.reserve
        with patch.object(ReplyStore, 'reserve', reserve_then_lose_focus):
            with self.assertRaises(FocusLost):
                self.run_reply(context)
        self.assertEqual([row['status'] for row in self.records()], ['pending'])
        self.assertEqual(self.clicks, [])


class ReplyEvidenceTests(unittest.TestCase):
    def test_geometry_fixtures_preserve_distinct_before_and_after_evidence(self):
        manifest = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf8'))
        fixed = manifest['fixed_data']
        self.assertEqual((reply._SECTION, reply._ITEM), (fixed['section'], fixed['supported_item']))
        self.assertEqual(reply._STARTER, fixed['fields'][f"{fixed['starter']}.MainText"])
        self.assertEqual(reply._CHOICES, tuple((item, fixed['fields'][f'{item}.OptionText'])
                                             for item in fixed['ordered_options']))
        self.assertEqual(reply._OUTGOING, fixed['fields'][f'{reply._ITEM}.MainText'])
        for row, scene in zip(manifest['frames'], replay_frames()):
            with self.subTest(time=row['pts_seconds']):
                self.assertEqual(sha256((FIXTURES / row['file']).read_bytes()).hexdigest(), row['sha256'])
                panel = reply._selected_panel(scene)
                self.assertIsNotNone(panel)
                self.assertEqual(reply._outgoing_surface(panel), row['phase'] == 'after')
        self.assertNotEqual(reply._text_digest('字样'), reply._text_digest('字样。'))
