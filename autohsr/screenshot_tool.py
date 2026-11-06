"""Local image snapshots, selection OCR and exclusive crop export."""
from __future__ import annotations

import ctypes as C
from io import BytesIO
from pathlib import Path

from PIL import Image

from .models import AutomationError, Stopped
from .storage import hold_read_sources
from .warp_fetch import WarpStopped
from .warp_records import WarpError
from .warp_service import publish_new


MAX_PIXELS = 16_777_216
MAX_BYTES = 64 * 1024 * 1024


class ScreenshotError(ValueError):
    pass


def _checkpoint(cancel):
    if cancel():
        raise Stopped('截图工具已停止。')


def _check_size(width, height):
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ScreenshotError('图片尺寸超出截图工具的处理范围。')


def open_image(path, cancel):
    _checkpoint(cancel)
    path = Path(path).resolve(strict=True)
    with hold_read_sources((path,)), path.open('rb') as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ScreenshotError('请选择小于 64 MiB 的 PNG 或 JPEG 图片。')
    _checkpoint(cancel)
    with Image.open(BytesIO(raw)) as image:
        if image.format not in ('PNG', 'JPEG') or getattr(image, 'n_frames', 1) != 1:
            raise ScreenshotError('请选择单张 PNG 或 JPEG 图片。')
        _check_size(*image.size)
        mode = 'RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB'
        result = image.convert(mode)
    _checkpoint(cancel)
    return result


def capture_game(settings, cancel):
    """Reserve the native foreground capture slot and capture only the game client."""
    from .windows import find_game
    from .workflow_lease import _kernel, workflow_lease

    _checkpoint(cancel)
    settings.validate('check')
    with workflow_lease():
        kernel = _kernel()
        C.set_last_error(0)
        slot = kernel.CreateMutexW(None, False, 'Local\\AutoHSR.DailyRunner')
        if not slot or C.get_last_error() == 183:
            if slot:
                kernel.CloseHandle(slot)
            raise AutomationError('另一个 AutoHSR 任务持有执行权，未截取游戏窗口。')
        try:
            _checkpoint(cancel)
            window = find_game(settings.game_path)

            def current():
                _checkpoint(cancel)
                if window.emergency_pressed():
                    raise Stopped('F10 已停止截取游戏窗口。')

            current()
            window.focus(checkpoint=current)
            current()
            geometry = window.guard()
            _check_size(geometry.width, geometry.height)
            current()
            bgr, captured = window.capture()
            if captured != geometry:
                raise AutomationError('游戏客户区已变化，请重新截取。')
            current()
        finally:
            kernel.CloseHandle(slot)
    _checkpoint(cancel)
    return Image.fromarray(bgr[:, :, ::-1])


def selection(image, box):
    left, top, right, bottom = box
    width, height = image.size
    if (any(type(value) is not int for value in box)
            or not (0 <= left < right <= width and 0 <= top < bottom <= height)):
        raise ScreenshotError('请在当前图片内框选有效区域。')
    return image.crop(box)


def read_selection(image, box, confidence, cancel):
    from numpy import asarray

    from .vision import Vision

    _checkpoint(cancel)
    crop = selection(image, box)
    if min(crop.size) < 16:
        raise ScreenshotError('选区过小，请框选至少 16×16 像素以识别文字。')
    result = Vision(confidence).read(asarray(crop.convert('RGB'))[:, :, ::-1].copy())
    _checkpoint(cancel)
    return tuple((token.text, token.score) for token in result.tokens)


def save_selection(image, box, target, cancel):
    _checkpoint(cancel)
    path = Path(target)
    if path.suffix.lower() != '.png':
        raise ScreenshotError('截图选区请另存为 PNG。')
    crop = selection(image, box)
    crop.info.clear()
    try:
        return publish_new(path, lambda stream: crop.save(stream, format='PNG'), cancel=cancel, limit=MAX_BYTES)
    except WarpStopped as error:
        raise Stopped('截图导出已停止。') from error
    except WarpError as error:
        raise ScreenshotError(str(error)) from error
