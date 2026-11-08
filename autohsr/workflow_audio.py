"""Bounded local audio playback for one task-tree step."""

from dataclasses import dataclass
import ctypes as C
import os
from pathlib import Path
import stat
from struct import unpack, unpack_from
from threading import Lock
from time import monotonic, sleep

from .models import AutomationError, Stopped
from .storage import file_revision, hold_read_sources


MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_DURATION_SECONDS = 120
AUDIO_SUFFIXES = frozenset(('.wav', '.mp3'))
_DRIVER_GRACE = 2
_POLL_INTERVAL = .025
_MAX_CHUNKS = 1024
_BAD_SOURCE = '请选择可读取的本地 PCM WAV 或 MP3，文件最多 32 MiB，时长最多 120 秒。'
_BAD_DEVICE = 'Windows 音频设备未能播放本次文件。'
_RELEASE_FAILED = 'Windows 音频设备未确认释放。'
_output_lock = Lock()
_unreleased_output = None


def _local_drive(anchor):
    if os.name != 'nt':
        return False
    get_type = C.WinDLL('kernel32').GetDriveTypeW
    get_type.argtypes = [C.c_wchar_p]
    get_type.restype = C.c_uint
    return get_type(anchor) in (2, 3, 5, 6)  # Removable, fixed, optical, RAM disk.


def _source(path):
    candidate = Path(path)
    drive = candidate.drive
    if (not candidate.is_absolute() or len(drive) != 2 or drive[1] != ':'
            or candidate.suffix.casefold() not in AUDIO_SUFFIXES or not _local_drive(candidate.anchor)):
        raise AutomationError(_BAD_SOURCE)
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        if part == '..' or ':' in part or part.endswith(('.', ' ')) or Path(part).is_reserved():
            raise AutomationError(_BAD_SOURCE)
        current /= part
        info = current.lstat()
        if getattr(info, 'st_file_attributes', 0) & (stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_OFFLINE):
            raise AutomationError(_BAD_SOURCE)
    if not stat.S_ISREG(info.st_mode):
        raise AutomationError(_BAD_SOURCE)
    return current


@dataclass(frozen=True)
class _Clip:
    channels: int
    width: int
    rate: int
    frames: int
    pcm: bytes

    @property
    def duration(self):
        return self.frames / self.rate


def _read_clip(path, size):
    if not 44 <= size <= MAX_FILE_BYTES:
        raise AutomationError(_BAD_SOURCE)
    with path.open('rb') as stream:
        header = stream.read(12)
        if (len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE'
                or unpack_from('<I', header, 4)[0] + 8 != size):
            raise AutomationError(_BAD_SOURCE)
        format_info = clip = None
        for _ in range(_MAX_CHUNKS):
            if stream.tell() == size and clip is not None:
                return clip
            chunk = stream.read(8)
            if len(chunk) != 8:
                break
            kind, length = unpack('<4sI', chunk)
            end = stream.tell() + length
            if end > size:
                raise AutomationError(_BAD_SOURCE)
            if kind == b'fmt ':
                if format_info is not None or length < 16:
                    raise AutomationError(_BAD_SOURCE)
                format_info = _pcm_format(stream.read(16))
            elif kind == b'data':
                if format_info is None or clip is not None:
                    raise AutomationError(_BAD_SOURCE)
                channels, width, rate = format_info
                frames, tail = divmod(length, channels * width)
                if tail or not 0 < frames <= rate * MAX_DURATION_SECONDS:
                    raise AutomationError(_BAD_SOURCE)
                pcm = stream.read(length)
                if len(pcm) != length:
                    raise AutomationError(_BAD_SOURCE)
                clip = _Clip(channels, width, rate, frames, pcm)
            # RIFF pads interior chunks to a word. Some writers omit the last pad.
            stream.seek(end + (length % 2 if end < size else 0))
    raise AutomationError(_BAD_SOURCE)


def read_media_clip(path, size, checkpoint):
    if path.suffix.casefold() == '.wav':
        return _read_clip(path, size)
    if path.suffix.casefold() != '.mp3' or not 0 < size <= MAX_FILE_BYTES:
        raise AutomationError(_BAD_SOURCE)
    from .workflow_mp3 import decode

    try:
        return decode(path, checkpoint=checkpoint, max_seconds=MAX_DURATION_SECONDS)
    except (OSError, AttributeError):
        raise AutomationError('当前 Windows 环境未能加载 MP3 解码组件。') from None


def _pcm_format(raw):
    if len(raw) != 16:
        raise AutomationError(_BAD_SOURCE)
    tag, channels, rate, bytes_per_second, alignment, bits = unpack('<HHIIHH', raw)
    width = bits // 8
    if (tag != 1 or channels not in (1, 2) or bits not in (8, 16) or not 8000 <= rate <= 48000
            or alignment != channels * width or bytes_per_second != rate * alignment):
        raise AutomationError(_BAD_SOURCE)
    return channels, width, rate


class _WaveFormat(C.Structure):
    _pack_ = 1
    _fields_ = [('tag', C.c_uint16), ('channels', C.c_uint16), ('rate', C.c_uint32),
                ('bytes_per_second', C.c_uint32), ('alignment', C.c_uint16),
                ('bits', C.c_uint16), ('extra', C.c_uint16)]


class _WaveHeader(C.Structure):
    _fields_ = [('data', C.c_void_p), ('length', C.c_uint32), ('recorded', C.c_uint32),
                ('user', C.c_size_t), ('flags', C.c_uint32), ('loops', C.c_uint32),
                ('next', C.c_void_p), ('reserved', C.c_size_t)]


class _WaveOut:
    def __init__(self, clip):
        api = C.WinDLL('winmm')
        handle = C.c_void_p
        header_args = [handle, C.POINTER(_WaveHeader), C.c_uint]
        signatures = {
            'waveOutOpen': [C.POINTER(handle), C.c_uint, C.POINTER(_WaveFormat), C.c_size_t, C.c_size_t, C.c_uint32],
            'waveOutPrepareHeader': header_args, 'waveOutWrite': header_args, 'waveOutUnprepareHeader': header_args,
            'waveOutPause': [handle], 'waveOutRestart': [handle], 'waveOutReset': [handle], 'waveOutClose': [handle],
        }
        for name, arguments in signatures.items():
            function = getattr(api, name)
            function.argtypes, function.restype = arguments, C.c_uint
        self.api = api
        self.handle = handle()
        alignment = clip.width * clip.channels
        self.format = _WaveFormat(1, clip.channels, clip.rate, clip.rate * alignment, alignment, clip.width * 8, 0)
        self.buffer = C.create_string_buffer(clip.pcm, len(clip.pcm))
        self.header = _WaveHeader(C.addressof(self.buffer), len(clip.pcm))
        self.prepared = self.submitted = False

    @staticmethod
    def _check(code):
        if code != 0:
            raise AutomationError(_BAD_DEVICE)

    def _header_call(self, function):
        return function(self.handle, C.byref(self.header), C.sizeof(self.header))

    def prepare(self):
        # WAVE_MAPPER, CALLBACK_NULL. A synchronous device cannot be paused.
        self._check(self.api.waveOutOpen(C.byref(self.handle), 0xffffffff, C.byref(self.format), 0, 0, 0))
        self._check(self._header_call(self.api.waveOutPrepareHeader))
        self.prepared = True
        self.pause()

    def submit(self):
        self.submitted = True
        self._check(self._header_call(self.api.waveOutWrite))

    def pause(self):
        self._check(self.api.waveOutPause(self.handle))

    def resume(self):
        self._check(self.api.waveOutRestart(self.handle))

    def done(self):
        return bool(self.header.flags & 1)  # WHDR_DONE

    def close(self):
        if not self.handle:
            return
        # Reset can also set WHDR_DONE, so completion is only read before cleanup.
        if self.submitted and not self.done() and self.api.waveOutReset(self.handle):
            self.api.waveOutPause(self.handle)
        if self.prepared:
            self._header_call(self.api.waveOutUnprepareHeader)
        self._check(self.api.waveOutClose(self.handle))
        self.handle.value = None


def _stop_if_requested(stopped):
    if stopped():
        raise Stopped('任务音频已停止。')


def _wait_for_output(player, duration, stopped, paused):
    remaining = duration + _DRIVER_GRACE
    previous = monotonic()
    output_paused = True
    started = False
    while True:
        _stop_if_requested(stopped)
        now = monotonic()
        if not output_paused:
            remaining -= now - previous
        previous = now
        if started and player.done():
            return
        if remaining <= 0:
            raise AutomationError('等待音频播放完成超时。')
        should_pause = bool(paused())
        if should_pause != output_paused:
            if should_pause:
                player.pause()
            else:
                _stop_if_requested(stopped)
                player.resume()
                started = True
            output_paused = should_pause
        sleep(_POLL_INTERVAL)


def play(path, *, checkpoint, stopped, paused):
    """Play one pinned local audio file. Callbacks read the owning workflow's state."""
    global _unreleased_output

    def decode_checkpoint():
        _stop_if_requested(stopped)
        checkpoint()

    _stop_if_requested(stopped)
    if not _output_lock.acquire(blocking=False):
        raise AutomationError('已有任务音频正在播放。')
    player = None
    stopping = False
    try:
        if _unreleased_output is not None:
            raise AutomationError(_RELEASE_FAILED)
        checkpoint()
        try:
            source = _source(path)
            with hold_read_sources((source,)):
                revision = file_revision(source)
                clip = read_media_clip(source, revision[2], decode_checkpoint)
                _stop_if_requested(stopped)
                try:
                    player = _WaveOut(clip)
                    player.prepare()
                except (OSError, AttributeError):
                    raise AutomationError(_BAD_DEVICE) from None
                checkpoint()
                if _source(source) != source or file_revision(source) != revision:
                    raise AutomationError('音频文件在播放前已变更。')
                _stop_if_requested(stopped)
                player.submit()  # The device is paused until the workflow allows output.
                if file_revision(source) != revision:
                    raise AutomationError('音频文件在播放前已变更。')
            _wait_for_output(player, clip.duration, stopped, paused)
        except Stopped:
            stopping = True
            raise
        except AutomationError:
            raise
        except (OSError, RuntimeError, TypeError, ValueError):
            raise AutomationError(_BAD_SOURCE) from None
        finally:
            if player is not None:
                try:
                    player.close()
                except Exception:
                    # Keep the native buffer alive if its release was never acknowledged.
                    _unreleased_output = player
                    if stopping:
                        raise Stopped('任务音频已停止。' + _RELEASE_FAILED) from None
                    raise AutomationError(_RELEASE_FAILED) from None
        checkpoint()
        _stop_if_requested(stopped)
        return dict(status='success', playback_status='completed', duration_seconds=clip.duration)
    finally:
        _output_lock.release()
