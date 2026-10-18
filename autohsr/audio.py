"""Explicit Core Audio mute gate for user-authorized development launches.

Uses documented IMMDevice/IAudioEndpointVolume APIs, never UI keys, microphone
settings, permissions, or game internals. There is deliberately no unmute path.
"""
from __future__ import annotations

import argparse
import ctypes as C
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


class GUID(C.Structure):
    _fields_ = [("Data1", C.c_uint32), ("Data2", C.c_uint16), ("Data3", C.c_uint16), ("Data4", C.c_ubyte * 8)]


def _guid(value):
    return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def _call(pointer, index, arguments=(), values=()):
    table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
    function = C.WINFUNCTYPE(C.c_long, C.c_void_p, *arguments)(table[index])
    result = function(pointer, *values)
    if result < 0:
        raise OSError(f"Core Audio HRESULT 0x{result & 0xffffffff:08X}")


def _release(pointer):
    if pointer and pointer.value:
        table = C.cast(pointer, C.POINTER(C.POINTER(C.c_void_p))).contents
        C.WINFUNCTYPE(C.c_ulong, C.c_void_p)(table[2])(pointer)


class CoreAudio:
    def __enter__(self):
        self.ole = C.WinDLL("ole32")
        self.ole.CoInitializeEx.argtypes = [C.c_void_p, C.c_uint32]
        self.ole.CoInitializeEx.restype = C.c_long
        self.ole.CoCreateInstance.argtypes = [C.POINTER(GUID), C.c_void_p, C.c_uint32, C.POINTER(GUID), C.POINTER(C.c_void_p)]
        self.ole.CoCreateInstance.restype = C.c_long
        self.ole.CoTaskMemFree.argtypes = [C.c_void_p]
        self.ole.CoTaskMemFree.restype = None
        result = self.ole.CoInitializeEx(None, 2)
        if result < 0:
            raise OSError(f"Core Audio COM initialization failed: 0x{result & 0xffffffff:08X}")
        return self

    def __exit__(self, *_):
        self.ole.CoUninitialize()

    def _devices(self, mute_ids=None):
        enumerator, collection = C.c_void_p(), C.c_void_p()
        volumes = []
        try:
            clsid = _guid("BCDE0395-E52F-467C-8E3D-C4579291692E")
            iid = _guid("A95664D2-9614-4F35-A746-DE8DB63617E6")
            result = self.ole.CoCreateInstance(C.byref(clsid), None, 1, C.byref(iid), C.byref(enumerator))
            if result < 0:
                raise OSError(f"Core Audio enumerator failed: 0x{result & 0xffffffff:08X}")
            _call(enumerator, 3, (C.c_int, C.c_uint32, C.POINTER(C.c_void_p)), (0, 1, C.byref(collection)))
            count = C.c_uint32()
            _call(collection, 3, (C.POINTER(C.c_uint32),), (C.byref(count),))
            for index in range(count.value):
                device, volume, identifier = C.c_void_p(), C.c_void_p(), C.c_void_p()
                try:
                    _call(collection, 4, (C.c_uint32, C.POINTER(C.c_void_p)), (index, C.byref(device)))
                    _call(device, 5, (C.POINTER(C.c_void_p),), (C.byref(identifier),))
                    device_id = C.wstring_at(identifier)
                    interface = _guid("5CDF2C82-841E-4546-9722-0CF74078229A")
                    _call(device, 3, (C.POINTER(GUID), C.c_uint32, C.c_void_p, C.POINTER(C.c_void_p)),
                          (C.byref(interface), 23, None, C.byref(volume)))
                    volumes.append((device_id, volume))
                    volume = C.c_void_p()
                finally:
                    if identifier.value:
                        self.ole.CoTaskMemFree(identifier)
                    _release(volume)
                    _release(device)
            if mute_ids is not None:
                if {key for key, _ in volumes} != set(mute_ids):
                    raise OSError("播放设备已变化，未执行静音；请重新读取原状态。")
                for _, volume in volumes:
                    _call(volume, 14, (C.c_int, C.c_void_p), (1, None))
            states = []
            for device_id, volume in volumes:
                muted, level = C.c_int(), C.c_float()
                _call(volume, 15, (C.POINTER(C.c_int),), (C.byref(muted),))
                _call(volume, 9, (C.POINTER(C.c_float),), (C.byref(level),))
                states.append(dict(id=device_id, muted=bool(muted.value), volume_scalar=level.value))
            return states
        finally:
            for _, volume in volumes:
                _release(volume)
            _release(collection)
            _release(enumerator)

    def read(self):
        return self._devices()

    def mute(self, ids):
        self._devices(mute_ids=ids)


def _write_new(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def mute_verified(audio, directory: Path):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    before = audio.read()
    if not before or any(type(item.get("muted")) is not bool or not item.get("id") for item in before):
        raise OSError("没有可完整读取的活动播放设备，无法核实静音。")
    _write_new(directory / "audio-before.json", dict(recorded_at=datetime.now(timezone.utc).isoformat(), endpoints=before))
    audio.mute([item["id"] for item in before])
    after = audio.read()  # independent enumeration and GetMute read-back
    verified = (bool(after) and {item["id"] for item in before} == {item["id"] for item in after}
                and all(item.get("muted") is True for item in after))
    result = dict(recorded_at=datetime.now(timezone.utc).isoformat(), muted_verified=verified,
                  endpoints=after, original_state=str(directory / "audio-before.json"),
                  game_launched=False, unmuted=False)
    _write_new(directory / "audio-after.json", result)
    if not verified:
        raise OSError("静音复读未通过；禁止启动游戏。")
    return result


def main():
    parser = argparse.ArgumentParser(description="显式授权后的播放设备静音门禁；默认只读，不启动游戏，不解除静音。")
    parser.add_argument("--mute", action="store_true")
    parser.add_argument("--record-dir", type=Path)
    args = parser.parse_args()
    if args.mute and args.record_dir is None:
        parser.error("静音前必须指定原状态记录目录 --record-dir")
    try:
        with CoreAudio() as audio:
            result = mute_verified(audio, args.record_dir) if args.mute else dict(read_only=True, endpoints=audio.read(), game_launched=False)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        print(json.dumps(dict(error=str(error), muted_verified=False, game_launched=False), ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
