"""P5 crossfade crops and one-capture allowance through the public CLI."""
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import cv2

from autohsr import workflow_lease
from autohsr.daily_event_claim_fade import _PAGE, _POPUP, observed_return_fade
from autohsr.models import Scene, Token
from autohsr.tests import test_daily_event_claim as cases
from autohsr.tests import test_daily_event_claim_cli as cli_cases


FIXTURES = Path(__file__).parent / 'fixtures' / 'daily_event_claim_fade'


def _pixels(index, size):
    image = cv2.imread(str(FIXTURES / f'p5-{index}.png'))
    return cv2.resize(image, size, interpolation=cv2.INTER_CUBIC)


def _frame(index, size):
    image = _pixels(index, size)
    return SimpleNamespace(scene=Scene([], image), image=image, page=None, tickets=None, button=None)


def _blend(scene, index, regions):
    image = _pixels(index, (960, 540))
    for (left, top, right, bottom), *_ in regions:
        x0, y0, x1, y1 = (round(v * 1.5) for v in (left - 2, top - 2, right + 2, bottom + 2))
        scene.image[y0:y1, x0:x1] = image[y0:y1, x0:x1]
    return scene


class ReturnFadeEvidenceTests(unittest.TestCase):
    def test_real_page_and_popup_overlap_remains_distinguishable_at_supported_sizes(self):
        manifest = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))
        for entry in manifest['frames'].values():
            self.assertEqual(sha256((FIXTURES / entry['fixture']).read_bytes()).hexdigest(),
                             entry['fixture_sha256'])
        groups = ((3735, 3763, (3779,), (3785,)),
                  (3795, 3837, (3842,), (3420, 3844, 3855, 4140, 7014)),
                  (3870, 3903, (3908, 3910), (3912,)),
                  (3930, 3966, (3982,), ()),
                  (4005, 4044, (4068,), ()))
        for size in ((640, 360), (960, 540), (1280, 720), (1920, 1080)):
            for before, popup, positive, negative in groups:
                source, reward = _frame(before, size), _frame(popup, size)
                for index in (*positive, *negative, before, popup):
                    with self.subTest(size=size, frame=index):
                        self.assertEqual(observed_return_fade(source, reward, _frame(index, size)),
                                         index in positive)

    def test_conflicting_modal_or_recognized_page_is_not_a_fade(self):
        source, reward = _frame(3795, (960, 540)), _frame(3837, (960, 540))
        for change in ('确认支付', '切换账号', '活动说明', 'page', 'tickets'):
            with self.subTest(change=change):
                fade = _frame(3842, (960, 540))
                if change == 'page':
                    fade.page = object()
                elif change == 'tickets':
                    fade.tickets = 1
                else:
                    fade.scene.tokens.append(Token(change, .99, (.42, .44, .55, .55)))
                self.assertFalse(observed_return_fade(source, reward, fade))


class ReturnFadeCliTests(unittest.TestCase):
    def setUp(self):
        self.cli = cli_cases.DailyEventClaimCliTests()
        self.cli.setUp()
        self.addCleanup(self.cli.doCleanups)
        self.enterContext(patch.object(workflow_lease, 'NAME', 'Local\\AutoHSR.OdysseyFadeQA.' + uuid4().hex))

    def run_fade(self, *indices, claimed=(1, 2, 3, 4), extra_tokens=()):
        before = [(_blend(cases.day_cards({1, 2, 3}), 3795, _PAGE), None) for _ in range(2)]
        popup = [(_blend(cases.popup(), 3837, _POPUP), 1) for _ in range(2)]
        waiting = [(Scene(list(extra_tokens), _pixels(index, (960, 540))), None) for index in indices]
        returned = [(cases.day_cards(set(claimed)), None) for _ in range(2)]
        self.cli.frames = iter(before + popup + waiting + returned)
        code, report = self.cli.invoke('--observe-daily-event-return')
        self.cli.fixture.native.SendInput.assert_called_once()
        return code, report['daily_event_claim']

    def test_one_fade_allows_two_new_return_frames_without_a_close_input(self):
        code, claim = self.run_fade(3842)
        self.assertEqual((code, claim['state'], claim['submission']), (0, 'verified', 'sent'))
        self.assertEqual(self.cli.window.capture.call_count, 7)

    def test_second_fade_does_not_admit_the_later_return_frames(self):
        code, claim = self.run_fade(3842, 3842)
        self.assertEqual((code, claim['state'], claim['stage']), (1, 'pending', 'return_unverified'))
        self.assertEqual(self.cli.window.capture.call_count, 6)

    def test_other_event_never_enables_a_return_recheck(self):
        code, claim = self.run_fade(4140)
        self.assertEqual((code, claim['state'], claim['stage']), (1, 'pending', 'return_unverified'))
        self.assertEqual(self.cli.window.capture.call_count, 5)

    def test_fade_cannot_prove_an_extra_claimed_day(self):
        code, claim = self.run_fade(3842, claimed=(1, 2, 3, 4, 5))
        self.assertEqual((code, claim['state'], claim['stage']), (1, 'pending', 'return_unverified'))
        self.assertEqual(self.cli.window.capture.call_count, 7)

    def test_foreign_account_on_real_fade_does_not_admit_a_recheck(self):
        code, claim = self.run_fade(3842, extra_tokens=(cases.OTHER,))
        self.assertEqual((code, claim['state'], claim['stage']), (1, 'pending', 'return_unverified'))
        self.assertEqual(self.cli.window.capture.call_count, 5)
