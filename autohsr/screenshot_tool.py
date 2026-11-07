"""Local image snapshots, selection OCR and exclusive crop export."""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import time

from PIL import Image

from .models import AutomationError, FocusLost, Stopped
from .storage import file_revision, hold_read_sources
from .warp_fetch import WarpStopped
from .warp_records import WarpError
from .warp_service import publish_new


MAX_PIXELS = 16_777_216
MAX_BYTES = 64 * 1024 * 1024
FOREGROUND_WAIT = 8


class ScreenshotError(ValueError):
    pass


@dataclass(frozen=True)
class TemplateCapture:
    path: Path
    relative_path: str
    sha256: str


def _checkpoint(cancel):
    if cancel():
        raise Stopped('截图工具已停止。')


def _check_size(width, height):
    if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
        raise ScreenshotError('图片尺寸超出截图工具的处理范围。')


def open_image(path, cancel):
    _checkpoint(cancel)
    path = Path(path).resolve(strict=True)
    with hold_read_sources((path,)):
        raw = _read_image_bytes(path)
    return _decode_image(raw, cancel)


def open_template_image(path, cancel):
    """Read a workflow capture source from a stable ordinary local path."""
    from .workflow_bundle import _path as bundle_path

    _checkpoint(cancel)
    try:
        path = Path(path)
        if not path.is_absolute() or path.suffix.casefold() not in ('.png', '.jpg', '.jpeg'):
            raise ValueError()
        source = bundle_path(path)
        with hold_read_sources((source,)):
            if bundle_path(path) != source:
                raise OSError()
            revision = file_revision(source)
            _checkpoint(cancel)
            raw = _read_image_bytes(source)
            if bundle_path(path) != source or file_revision(source) != revision:
                raise OSError()
    except (OSError, TypeError, ValueError):
        raise ScreenshotError('请选择可稳定读取的本地普通 PNG 或 JPEG 图片。') from None
    return _decode_image(raw, cancel)


def _read_image_bytes(path):
    with path.open('rb') as source:
        return source.read(MAX_BYTES + 1)


def _decode_image(raw, cancel):
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


def _foreground_geometry(window, checkpoint):
    deadline = time.monotonic() + FOREGROUND_WAIT
    while True:
        checkpoint()
        try:
            geometry = window.guard()
        except FocusLost:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(.10, remaining))
        else:
            if time.monotonic() <= deadline:
                return geometry
            break
    raise AutomationError('等待游戏前台已超时，请重试并手动切回游戏。')


def capture_game(settings, cancel, *, foreground_only=False):
    """Reserve the native foreground capture slot and capture only the game client."""
    from .windows import find_game
    from .workflow_lease import NATIVE_NAME, _kernel, workflow_lease

    _checkpoint(cancel)
    settings.validate('check')
    with workflow_lease():
        kernel = _kernel()
        C.set_last_error(0)
        slot = kernel.CreateMutexW(None, False, NATIVE_NAME)
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
            if foreground_only:
                geometry = _foreground_geometry(window, current)
            else:
                window.focus(checkpoint=current)
                current()
                geometry = window.guard()
            _checkpoint(cancel)
            window_key = window.current_window_key()
            if not window_key or window.guard(geometry) != geometry:
                raise AutomationError('游戏窗口来源无法核实，请重新截取。')
            _check_size(geometry.width, geometry.height)
            current()
            bgr, captured = window.capture()
            if captured != geometry:
                raise AutomationError('游戏客户区已变化，请重新截取。')
            if window.current_window_key() != window_key or window.guard(geometry) != geometry:
                raise AutomationError('游戏窗口来源已变化，请重新截取。')
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
    return _save_png(selection(image, box), path, cancel)


def _save_png(crop, path, cancel):
    crop.info.clear()
    try:
        return publish_new(path, lambda stream: crop.save(stream, format='PNG'), cancel=cancel, limit=MAX_BYTES)
    except WarpStopped as error:
        raise Stopped('截图导出已停止。') from error
    except WarpError as error:
        raise ScreenshotError(str(error)) from error


def save_template(image, box, target, base_dir, cancel):
    """Publish a matcher-ready template at an explicit new path inside the workflow folder."""
    from .workflow_bundle import BundleError, _path as bundle_path
    from .workflow_vision import _prepare_template

    _checkpoint(cancel)
    try:
        target = Path(target)
        if not target.is_absolute() or target.suffix.lower() != '.png':
            raise ValueError()
        base = Path(base_dir).resolve(strict=True)
        path = bundle_path(target, new=True)
        relative = path.relative_to(base).as_posix()
        parent = path.parent.stat()
    except BundleError as error:
        raise ScreenshotError(str(error)) from error
    except (OSError, TypeError, ValueError):
        raise ScreenshotError('请选择流程目录内的新 PNG 文件。') from None

    crop = selection(image, box)
    _prepare_template(crop)

    def check_destination():
        if cancel():
            return True
        try:
            current = bundle_path(path, new=True).parent.stat()
            if (current.st_dev, current.st_ino) == (parent.st_dev, parent.st_ino):
                return cancel()
        except BundleError as error:
            raise ScreenshotError(str(error)) from error
        except OSError:
            pass
        raise ScreenshotError('所选 PNG 目录已变化，请重新选择。')

    digest = _save_png(crop, path, check_destination)
    try:
        with hold_read_sources((path,)):
            checked = bundle_path(path)
            current = checked.parent.stat()
            if (current.st_dev, current.st_ino) != (parent.st_dev, parent.st_ino):
                raise OSError()
            with checked.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES or sha256(raw).hexdigest() != digest:
                raise OSError()
    except (BundleError, OSError):
        raise ScreenshotError(f'PNG 已发布，文件待核对 · {path}') from None
    return TemplateCapture(path, relative, digest)
