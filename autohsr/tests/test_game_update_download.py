"""Launcher controls with synthetic OCR and a fake guarded foreground window."""

from threading import Event
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import game_update_download as download
from autohsr.models import Scene, Token
from autohsr.windows import Geometry


AREA = Geometry(0, 0, 1200, 750)


def token(text, x, y):
    return Token(text, .98, (x - .06, y - .02, x + .06, y + .02))


def frame(*tokens, title=None):
    return Scene([title or token('崩坏：星穹铁道', .38, .45), *tokens], geometry=AREA)


class DownloadTests(TestCase):
    def execute(self, frames, *, action='update', changed=False, stop_after_click=False):
        self.window = window = Mock()
        window.capture.return_value = None, AREA
        window.emergency_pressed.return_value = False
        window.current_window_key.return_value = 'fixture-window'
        stop = Mock(wraps=Event())
        stop.wait.return_value = False

        def click(*_args, before_send, before_submit):
            before_send()
            before_submit()
            if stop_after_click:
                stop.set()

        window.click.side_effect = click
        source = SimpleNamespace(client=dict(executable='fixture'), launcher='fixture')
        offer = SimpleNamespace(action=action, channel='cn', target='4.7.0', source=source)
        package = dict(update='available', release_version=offer.target, pre_download='advertised',
                       pre_download_version=offer.target)
        with (patch.object(download, 'Vision', return_value=Mock(read=Mock(side_effect=frames))),
              patch.object(download, '_foreground', return_value=window),
              patch.object(download, 'native_idle_lease'),
              patch.object(download, 'check_game_update', return_value=package),
              patch.object(download, '_verify_publisher'),
              patch.object(download, '_source', side_effect=[source, object()] if changed else None,
                           return_value=source)):
            return download.request_download(offer, stop=stop)

    def test_update_has_one_submission_and_two_progress_reads(self):
        ready = frame(token('更新游戏', .83, .88))
        progress = frame(token('正在下载', .81, .87))
        result = self.execute([ready, ready, progress, progress])
        self.assertEqual(result['submissions'], ['update'])
        self.assertTrue(result['progress_observed'])
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(self.window.click.call_count, 1)

    def test_pre_download_requires_exact_dialogue_and_progress(self):
        ready = frame(token('预下载', .73, .86))
        confirm = frame(token('游戏预下载', .50, .28), token('确认下载', .57, .73))
        progress = frame(token('正在预下载', .82, .84))
        result = self.execute([ready, ready, confirm, confirm, progress, progress], action='pre_download')
        self.assertEqual(result['submissions'], ['pre_download', 'confirm'])
        self.assertTrue(result['progress_observed'])
        generic = frame(token('确认下载', .57, .73))
        result = self.execute([ready, ready] + [generic] * 6, action='pre_download')
        self.assertEqual(result['submissions'], ['pre_download'])
        self.assertFalse(result['progress_observed'])
        self.assertEqual(self.window.click.call_count, 1)

    def test_incorrect_game_or_duplicate_button_sends_no_input(self):
        update = token('更新游戏', .83, .88)
        for screen in (frame(update, title=token('绝区零', .38, .45)),
                       frame(update, title=token('崩坏：星穹铁道', .10, .31)),
                       frame(update, token('绝区零', .53, .51)),
                       frame(update, token('更新游戏', .71, .86)),
                       frame(update, token('正在预下载', .75, .87))):
            with self.subTest(text=screen.text):
                result = self.execute([screen] * 6)
                self.assertEqual(result['submissions'], [])
                self.window.click.assert_not_called()

    def test_installation_change_at_submission_stops_before_native_send(self):
        ready = frame(token('更新游戏', .83, .88))
        result = self.execute([ready, ready], changed=True)
        self.assertEqual(result['submissions'], [])
        self.assertIn('来源已变化', result['message'])

    def test_stop_after_pre_download_open_does_not_submit_confirmation(self):
        ready = frame(token('预下载', .73, .86))
        result = self.execute([ready, ready], action='pre_download', stop_after_click=True)
        self.assertEqual(result['status'], 'stopped')
        self.assertEqual(result['submissions'], ['pre_download'])
        self.assertFalse(result['progress_observed'])
