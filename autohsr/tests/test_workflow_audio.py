import ctypes
import os
from pathlib import Path
from struct import pack_into
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
import wave

from autohsr import workflow_audio as audio
from autohsr.models import AutomationError, Stopped


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds


class FakePlayer:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.started_at = None
        self.played = 0.0
        self.hang = False

    def prepare(self):
        self.calls.append('prepare')

    def submit(self):
        self.calls.append('submit')

    def pause(self):
        self.calls.append('pause')
        self.played += self.clock.now - self.started_at
        self.started_at = None

    def resume(self):
        self.calls.append('resume')
        self.started_at = self.clock.now

    def done(self):
        current = 0 if self.started_at is None else self.clock.now - self.started_at
        return not self.hang and self.played + current >= .1

    def close(self):
        self.calls.append('close')


@unittest.skipUnless(os.name == 'nt', 'Windows local source rules')
class WorkflowAudioTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='autohsr-audio-')
        self.addCleanup(temporary.cleanup)
        self.source = Path(temporary.name) / '本地 音频.WAV'
        with wave.open(str(self.source), 'wb') as stream:
            stream.setparams((1, 2, 8000, 800, 'NONE', 'not compressed'))
            stream.writeframes(bytes(1600))
        self.clock = FakeClock()
        self.player = FakePlayer(self.clock)
        self.factory = Mock(return_value=self.player)
        for member, value in dict(_WaveOut=self.factory, monotonic=lambda: self.clock.now,
                                  sleep=self.clock.sleep, _unreleased_output=None).items():
            mocked = patch.object(audio, member, value)
            mocked.start()
            self.addCleanup(mocked.stop)

    def play(self, path=None, *, checkpoint=None, stopped=None, paused=None):
        return audio.play(self.source if path is None else path,
                          checkpoint=checkpoint or (lambda: None), stopped=stopped or (lambda: False),
                          paused=paused or (lambda: False))

    def test_one_clip_reports_native_completion_and_decoded_duration(self):
        self.assertEqual(self.play(), dict(status='success', playback_status='completed', duration_seconds=.1))
        self.assertEqual(self.player.calls, ['prepare', 'submit', 'resume', 'close'])
        clip = self.factory.call_args.args[0]
        self.assertEqual((clip.channels, clip.width, clip.rate, clip.frames, len(clip.pcm)), (1, 2, 8000, 800, 1600))

    def test_pause_polls_and_restarts_existing_queue_without_counting_paused_time(self):
        def checkpoint():
            self.assertTrue(self.player.started_at is None or self.player.calls[-1] == 'close')

        result = self.play(checkpoint=checkpoint, paused=lambda: .025 <= self.clock.now < 4)
        self.assertEqual(result['playback_status'], 'completed')
        self.assertGreaterEqual(self.clock.now, 4)
        self.assertEqual(self.player.calls, ['prepare', 'submit', 'resume', 'pause', 'resume', 'close'])

    def test_stop_during_pause_releases_output_without_resuming(self):
        with self.assertRaises(Stopped):
            self.play(stopped=lambda: self.clock.now >= .1, paused=lambda: self.clock.now >= .025)
        self.assertEqual(self.player.calls, ['prepare', 'submit', 'resume', 'pause', 'close'])

    def test_stop_at_submit_keeps_prepaused_device_silent(self):
        with self.assertRaises(Stopped):
            self.play(stopped=lambda: 'submit' in self.player.calls)
        self.assertEqual(self.player.calls, ['prepare', 'submit', 'close'])

    def test_stopped_before_preflight_never_creates_player(self):
        with self.assertRaises(Stopped):
            self.play(stopped=lambda: True)
        self.factory.assert_not_called()

    def test_driver_without_completion_times_out_and_releases(self):
        self.player.hang = True
        with self.assertRaisesRegex(AutomationError, '超时'):
            self.play()
        self.assertLess(self.clock.now, 2.2)
        self.assertEqual(self.player.calls, ['prepare', 'submit', 'resume', 'close'])

    def test_local_source_is_write_and_delete_held_through_submit(self):
        submit = self.player.submit

        def attempt_change():
            with self.assertRaises(OSError):
                self.source.open('r+b').close()
            with self.assertRaises(OSError):
                self.source.rename(self.source.with_name('replacement.wav'))
            submit()

        self.player.submit = attempt_change
        self.assertEqual(self.play()['status'], 'success')
        self.assertEqual(self.source.read_bytes()[:4], b'RIFF')

    def test_changed_source_after_submit_cannot_be_audible(self):
        original = audio.file_revision(self.source)
        changed = (*original[:-1], original[-1] + 1)
        with patch.object(audio, 'file_revision', side_effect=[original, original, changed]):
            with self.assertRaisesRegex(AutomationError, '已变更'):
                self.play()
        self.assertEqual(self.player.calls, ['prepare', 'submit', 'close'])

    def test_malformed_remote_and_over_limit_sources_never_open_player(self):
        wrong = self.source.with_name('private-invalid.wav')
        wrong.write_bytes(self.source.read_bytes()[:-4])
        for candidate in (wrong, self.source.with_name('private-missing.wav'),
                          r'\\remote-host\private-share\audio.wav', self.source.with_suffix('.mp3')):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(AutomationError, '本地 PCM WAV') as error:
                self.play(candidate)
            self.assertNotIn('private', str(error.exception))
        with patch.object(audio, 'MAX_FILE_BYTES', 44), self.assertRaises(AutomationError):
            self.play()
        with patch.object(audio, 'MAX_DURATION_SECONDS', .05), self.assertRaises(AutomationError):
            self.play()
        self.factory.assert_not_called()

    def test_riff_padding_allows_metadata_and_keeps_exact_pcm(self):
        original = self.source.read_bytes()
        payload = b'JUNK\x03\x00\x00\x00tag\x00'
        with_metadata = bytearray(original[:12] + payload + original[12:])
        pack_into('<I', with_metadata, 4, len(with_metadata) - 8)
        self.source.write_bytes(with_metadata)
        self.assertEqual(self.play()['duration_seconds'], .1)
        self.assertEqual(self.factory.call_args.args[0].pcm, bytes(1600))

    def test_rounded_sample_width_and_wrong_byte_rate_are_rejected(self):
        original = self.source.read_bytes()
        for offset, format_, value in ((34, '<H', 9), (28, '<I', 8000), (20, '<H', 3)):
            damaged = bytearray(original)
            pack_into(format_, damaged, offset, value)
            self.source.write_bytes(damaged)
            with self.assertRaisesRegex(AutomationError, '本地 PCM WAV'):
                self.play()
        self.factory.assert_not_called()

    def test_concurrent_or_unreleased_output_never_opens_a_second_player(self):
        with audio._output_lock, self.assertRaisesRegex(AutomationError, '正在播放'):
            self.play()
        self.factory.assert_not_called()
        self.player.close = Mock(side_effect=OSError(str(self.source)))
        with self.assertRaisesRegex(Stopped, '未确认释放') as error:
            self.play(stopped=lambda: 'submit' in self.player.calls)
        self.assertNotIn(str(self.source), str(error.exception))
        with self.assertRaisesRegex(AutomationError, '未确认释放'):
            self.play()
        self.factory.assert_called_once()


@unittest.skipUnless(os.name == 'nt', 'WinMM API binding')
class WinMMBindingTests(unittest.TestCase):
    def test_pause_restart_reset_and_release_only_own_handle(self):
        api = Mock()
        names = ('Open', 'PrepareHeader', 'Pause', 'Write', 'Restart', 'Reset', 'UnprepareHeader', 'Close')
        for name in names:
            getattr(api, 'waveOut' + name).return_value = 0

        def open_device(handle, device_id, format_ptr, callback, instance, flags):
            ctypes.cast(handle, ctypes.POINTER(ctypes.c_void_p))[0] = 1729
            form = ctypes.cast(format_ptr, ctypes.POINTER(audio._WaveFormat)).contents
            self.assertEqual((device_id, callback, instance, flags), (0xffffffff, 0, 0, 0))
            self.assertEqual((form.tag, form.channels, form.rate, form.alignment, form.bits), (1, 1, 8000, 2, 16))
            return 0

        api.waveOutOpen.side_effect = open_device
        pcm = b'\x01\x02\x03\x04'
        with patch.object(audio.C, 'WinDLL', return_value=api):
            player = audio._WaveOut(audio._Clip(1, 2, 8000, 2, pcm))
        player.prepare()
        player.submit()
        self.assertEqual(ctypes.string_at(player.header.data, player.header.length), pcm)
        player.resume()
        player.pause()
        player.resume()
        player.close()
        self.assertEqual([call[0] for call in api.mock_calls], ['waveOut' + name for name in (
            'Open', 'PrepareHeader', 'Pause', 'Write', 'Restart', 'Pause', 'Restart', 'Reset', 'UnprepareHeader', 'Close')])
        self.assertFalse(player.handle)


if __name__ == '__main__':
    unittest.main()
