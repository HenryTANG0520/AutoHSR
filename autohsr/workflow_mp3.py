"""Decode a local MP3 to the bounded PCM buffer used by workflow audio."""

from contextlib import contextmanager
import ctypes as C
from uuid import UUID

from .models import AutomationError


_P = C.c_void_p
_DWORD = C.c_uint32
_GUID = _DWORD * 4
_AUDIO_STREAM = 0xfffffffd  # MF_SOURCE_READER_FIRST_AUDIO_STREAM
_ALL_STREAMS = 0xfffffffe
_END_OF_STREAM = 0x02
_INVALID_STREAM = 0x01 | 0x10 | 0x20  # Error or changed native/output media type.
_ERROR = 'Windows 无法把本次 MP3 解码为受支持的 PCM 音频。'


def _guid(value):
    return _GUID.from_buffer_copy(UUID(value).bytes_le)


_MAJOR_TYPE = _guid('48eba18e-f8c9-4687-bf11-0a74c9f96a8f')
_SUBTYPE = _guid('f7e34c9a-42e8-4714-b74b-cb29d72c35e5')
_AUDIO = _guid('73647561-0000-0010-8000-00aa00389b71')
_PCM = _guid('00000001-0000-0010-8000-00aa00389b71')
_MP3 = _guid('00000055-0000-0010-8000-00aa00389b71')


def _checked(result):
    if result < 0:
        raise AutomationError(_ERROR)


def _api(library, name, *arguments, result=C.c_long):
    function = getattr(library, name)
    function.argtypes, function.restype = arguments, result
    return function


def _method(obj, index, *arguments, result=C.c_long):
    # Interface slots follow the Windows SDK COM vtables, including IUnknown.
    table = C.cast(obj, C.POINTER(C.POINTER(_P))).contents
    return C.WINFUNCTYPE(result, _P, *arguments)(table[index])


@contextmanager
def _owned(pointer):
    try:
        yield pointer
    finally:
        if pointer:
            _method(pointer, 2, result=C.c_ulong)(pointer)  # IUnknown::Release


@contextmanager
def _media_foundation():
    ole = C.WinDLL('ole32', winmode=0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32
    platform = C.WinDLL('mfplat', winmode=0x800)
    initialize = _api(ole, 'CoInitializeEx', _P, _DWORD)
    apartment = initialize(None, 0)  # COINIT_MULTITHREADED
    if apartment != -2147417850:  # RPC_E_CHANGED_MODE: use the caller's existing apartment.
        _checked(apartment)
    try:
        _checked(_api(platform, 'MFStartup', _DWORD, _DWORD)(0x00020070, 1))  # MF_VERSION, MFSTARTUP_NOSOCKET
        try:
            yield ole, platform
        finally:
            _api(platform, 'MFShutdown')()
    finally:
        if apartment >= 0:
            _api(ole, 'CoUninitialize', result=None)()


def _configure_reader(reader, platform):
    with _owned(_P()) as native, _owned(_P()) as requested:
        _checked(_method(reader, 5, _DWORD, _DWORD, _P)(reader, _AUDIO_STREAM, 0, C.byref(native)))
        subtype = _GUID()
        _checked(_method(native, 10, _P, _P)(native, _SUBTYPE, subtype))  # IMFAttributes::GetGUID
        if bytes(subtype) != bytes(_MP3):
            raise AutomationError(_ERROR)
        _checked(_api(platform, 'MFCreateMediaType', _P)(C.byref(requested)))
        set_guid = _method(requested, 24, _P, _P)
        _checked(set_guid(requested, _MAJOR_TYPE, _AUDIO))
        _checked(set_guid(requested, _SUBTYPE, _PCM))
        select = _method(reader, 4, _DWORD, C.c_int)
        _checked(select(reader, _ALL_STREAMS, False))
        _checked(select(reader, _AUDIO_STREAM, True))
        _checked(_method(reader, 7, _DWORD, _P, _P)(reader, _AUDIO_STREAM, None, requested))


def _output_format(reader, ole, platform):
    from .workflow_audio import _pcm_format

    with _owned(_P()) as media_type:
        _checked(_method(reader, 6, _DWORD, _P)(reader, _AUDIO_STREAM, C.byref(media_type)))
        wave_format, size = _P(), _DWORD()
        convert = _api(platform, 'MFCreateWaveFormatExFromMFMediaType', _P, _P, _P, _DWORD)
        _checked(convert(media_type, C.byref(wave_format), C.byref(size), 0))
        try:
            if not wave_format or size.value < 16:
                raise AutomationError(_ERROR)
            return _pcm_format(C.string_at(wave_format, 16))
        finally:
            _api(ole, 'CoTaskMemFree', _P, result=None)(wave_format)


def _append_sample(sample, pcm, limit):
    with _owned(_P()) as buffer:
        # IMFSample::ConvertToContiguousBuffer
        _checked(_method(sample, 41, _P)(sample, C.byref(buffer)))
        address, length = _P(), _DWORD()
        _checked(_method(buffer, 3, _P, _P, _P)(buffer, C.byref(address), None, C.byref(length)))
        try:
            if length.value > limit - len(pcm):
                raise AutomationError('音频时长超过 120 秒。')
            if length.value:
                if not address:
                    raise AutomationError(_ERROR)
                pcm.extend(C.string_at(address, length.value))
        finally:
            _checked(_method(buffer, 4)(buffer))


def decode(path, *, checkpoint, max_seconds):
    from .workflow_audio import _Clip

    checkpoint()
    with _media_foundation() as (ole, platform), _owned(_P()) as reader:
        readwrite = C.WinDLL('mfreadwrite', winmode=0x800)
        create = _api(readwrite, 'MFCreateSourceReaderFromURL', C.c_wchar_p, _P, _P)
        _checked(create(str(path), None, C.byref(reader)))
        _configure_reader(reader, platform)
        channels, width, rate = _output_format(reader, ole, platform)
        alignment = channels * width
        limit = int(max_seconds * rate) * alignment
        read = _method(reader, 9, _DWORD, _DWORD, _P, _P, _P, _P)
        pcm = bytearray()
        for _ in range(20_000):
            checkpoint()
            flags = _DWORD()
            with _owned(_P()) as sample:
                _checked(read(reader, _AUDIO_STREAM, 0, None, C.byref(flags), None, C.byref(sample)))
                if flags.value & _INVALID_STREAM:
                    raise AutomationError(_ERROR)
                if sample:
                    _append_sample(sample, pcm, limit)
                if flags.value & _END_OF_STREAM:
                    frames, tail = divmod(len(pcm), alignment)
                    if not frames or tail:
                        raise AutomationError(_ERROR)
                    return _Clip(channels, width, rate, frames, bytes(pcm))
        raise AutomationError(_ERROR)
