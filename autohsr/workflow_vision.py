"""Workflow observations that expose only the selected match flag."""
from contextlib import ExitStack, contextmanager
import math
import os
from pathlib import Path
import stat
from struct import error as StructError
from warnings import catch_warnings, simplefilter

import cv2
import numpy as np
from PIL import Image

from .models import Stopped, normalize
from .screenshot_tool import MAX_BYTES, open_image
from .storage import file_revision, hold_read_sources
from .vision import Vision


class WorkflowVisionError(ValueError):
    """A local source or observation could not be verified."""


_SUFFIXES = ('.png', '.jpg', '.jpeg')
_PNG_HEADER = b'\x89PNG\r\n\x1a\n'
_PNG_END = b'\0\0\0\0IEND\xaeB`\x82'
_MAX_TEMPLATE_PIXELS = 1_048_576


def _local_file(value):
    try:
        path = Path(value)
        if (path.suffix.lower() not in _SUFFIXES or path.drive.startswith(('\\\\', '//'))
                or (path.drive and not path.is_absolute()) or ':' in path.name):
            raise ValueError
        path = path.resolve(strict=True)
        if path.drive.startswith(('\\\\', '//')) or not path.is_file():
            raise ValueError
        return path
    except (OSError, ValueError, TypeError, RuntimeError):
        raise WorkflowVisionError('请明确选择本地 PNG 或 JPEG 图片。') from None


def game_template_path(value, base):
    """Check the volume and path components before reading a game template."""
    try:
        from .workflow_audio import _local_drive

        path = Path(value)
        if (str(value).replace('\\', '/').startswith('//')
                or (path.drive and not path.is_absolute())
                or (os.name == 'nt' and path.root and not path.drive)
                or path.suffix.lower() not in _SUFFIXES):
            raise ValueError
        path = Path(os.path.abspath(Path(base) / path))
        if os.name == 'nt' and (len(path.drive) != 2 or not _local_drive(path.anchor)):
            raise ValueError
        current = Path(path.anchor)
        for index, part in enumerate(path.parts[1:], 1):
            if ':' in part or part.endswith(('.', ' ')) or Path(part).is_reserved():
                raise ValueError
            current /= part
            info = current.lstat()
            expected = stat.S_ISREG if index == len(path.parts) - 1 else stat.S_ISDIR
            if not expected(info.st_mode) or getattr(info, 'st_file_attributes', 0) & (
                    stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_OFFLINE):
                raise ValueError
        return current
    except (OSError, ValueError, TypeError, RuntimeError):
        raise WorkflowVisionError('游戏画面模板须为普通本地 PNG 或 JPEG 文件。') from None


def _read(path, checkpoint):
    def check_cancel():
        checkpoint()
        return False

    checkpoint()
    try:
        with catch_warnings():
            simplefilter('error', Image.DecompressionBombWarning)
            with path.open('rb') as stream:
                size = stream.seek(0, 2)
                if not 4 <= size <= MAX_BYTES:
                    raise ValueError
                stream.seek(0)
                header = stream.read(len(_PNG_HEADER))
                if header == _PNG_HEADER and size >= len(_PNG_END):
                    stream.seek(-len(_PNG_END), 2)
                    if stream.read() != _PNG_END:
                        raise ValueError
                    stream.seek(0)
                    with Image.open(stream, formats=['PNG']) as image:
                        image.verify()
                elif header.startswith(b'\xff\xd8\xff'):
                    stream.seek(-2, 2)
                    if stream.read() != b'\xff\xd9':
                        raise ValueError
                else:
                    raise ValueError
            return open_image(path, check_cancel)
    except (OSError, SyntaxError, ValueError, StructError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise WorkflowVisionError('所选图片无法完整读取，或超过图片处理上限。') from None


def _normalized_region(region):
    if region is None:
        return (0, 0, 1, 1)
    if (not isinstance(region, (list, tuple)) or len(region) != 4
            or any(type(value) not in (int, float) or not 0 <= value <= 1 for value in region)
            or region[0] >= region[2] or region[1] >= region[3]):
        raise WorkflowVisionError('图片选区须为有面积的归一化矩形。')
    return region


def _pixels(image):
    if image.mode == 'RGBA':
        image = Image.alpha_composite(Image.new('RGBA', image.size, 'white'), image).convert('RGB')
    return np.asarray(image)


def _prepare_template(template):
    width, height = template.size
    if min(width, height) < 8 or width * height > _MAX_TEMPLATE_PIXELS:
        raise WorkflowVisionError('模板须至少 8×8 像素，且总像素不超过 1048576。')
    needle = _pixels(template)
    median = np.median(needle.reshape(-1, 3), axis=0)
    marks = np.max(np.abs(needle - median), axis=2) >= 16
    if (np.count_nonzero(marks) < max(8, math.ceil(width * height * .015))
            or np.count_nonzero(marks.any(axis=0)) < 2 or np.count_nonzero(marks.any(axis=1)) < 2):
        raise WorkflowVisionError('模板缺少可区分的图像细节。')
    spread = cv2.meanStdDev(needle)[1]
    tolerance = min(28., .72 * float(np.sqrt(np.mean(spread ** 2))))
    return needle, tolerance


def _template_found(source, needle, tolerance, minimum, checkpoint):
    if any(required > available for required, available in zip(needle.shape[:2], source.shape[:2])):
        return False
    checkpoint()
    scores = cv2.matchTemplate(source, needle, cv2.TM_CCOEFF_NORMED)
    candidates = np.isfinite(scores) & (scores >= minimum - 1e-6)
    del scores
    if not candidates.any():
        return False
    checkpoint()
    # A normalized correlation alone also accepts the same shape in faint noise.
    distances = cv2.matchTemplate(source, needle, cv2.TM_SQDIFF)
    closest = np.min(distances, where=candidates, initial=np.inf)
    return bool(np.isfinite(closest) and closest <= needle.size * tolerance ** 2)


def _text_found(vision, pixels, wanted, minimum, contains):
    try:
        tokens = vision.read(pixels).tokens
        for token in tokens:
            left, top, right, bottom = token.box
            if not (minimum <= token.score <= 1 and 0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                continue
            actual = normalize(token.text)
            if actual == wanted or contains and wanted in actual:
                return True
        return False
    except Stopped:
        raise
    except Exception:
        raise WorkflowVisionError('文字识别未能返回有效结果。') from None


@contextmanager
def _stable_sources(paths):
    with ExitStack() as sources:
        try:
            sources.enter_context(hold_read_sources(paths))
            revisions = {path: file_revision(path) for path in paths}
        except OSError:
            raise WorkflowVisionError('无法稳定读取所选图片。') from None
        yield
        try:
            if any(file_revision(path) != revision for path, revision in revisions.items()):
                raise OSError
        except OSError:
            raise WorkflowVisionError('所选图片在观察期间发生变化。') from None


def _prepare_query(template, text, region, threshold, contains):
    image_match = template is not None
    if image_match == (text is not None) or type(contains) is not bool or image_match and contains:
        raise WorkflowVisionError('请选择一种图片模板或文字判断。')
    if not image_match:
        if (not isinstance(text, str) or len(text) > 120
                or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in text)
                or not (wanted := normalize(text))):
            raise WorkflowVisionError('目标文字为空、过长或包含控制字符。')
    if threshold is None:
        threshold = .88 if image_match else .65
    if type(threshold) not in (int, float) or not .50 <= threshold <= 1:
        raise WorkflowVisionError('识别阈值须为 0.50 到 1 之间的数值。')
    return image_match, None if image_match else wanted, _normalized_region(region), threshold


@contextmanager
def prepare_observation(*, template=None, text=None, region=None, threshold=None, contains=False, checkpoint):
    """Lock a template once and yield its boolean matcher for file or native BGR frames."""
    checkpoint()
    image_match, wanted, region, minimum = _prepare_query(template, text, region, threshold, contains)
    template_path = _local_file(template) if image_match else None
    with _stable_sources((template_path,) if image_match else ()):
        prepared = _prepare_template(_read(template_path, checkpoint)) if image_match else None
        vision = None

        def match(picture, *, native_bgr=False):
            nonlocal vision
            if native_bgr:
                height, width = picture.shape[:2]
            else:
                width, height = picture.size
            box = tuple(round(value * size) for value, size in zip(region, (width, height, width, height)))
            left, top, right, bottom = box
            if left >= right or top >= bottom:
                raise WorkflowVisionError('图片选区小于一个像素。')
            if not image_match and min(right - left, bottom - top) < 16:
                raise WorkflowVisionError('文字识别选区须至少 16×16 像素。')
            pixels = picture[top:bottom, left:right] if native_bgr else _pixels(picture.crop(box))
            # The template is RGB; RapidOCR expects BGR.
            if native_bgr == image_match:
                pixels = pixels[:, :, ::-1]
            pixels = np.ascontiguousarray(pixels)
            checkpoint()
            if image_match:
                try:
                    return _template_found(pixels, *prepared, minimum, checkpoint)
                except cv2.error:
                    raise WorkflowVisionError('图像模板识别失败。') from None
            try:
                if vision is None:
                    vision = Vision(minimum)
            except Stopped:
                raise
            except Exception:
                raise WorkflowVisionError('文字识别初始化失败。') from None
            checkpoint()
            return _text_found(vision, pixels, wanted, minimum, contains)

        yield ('image_found' if image_match else 'text_found'), match
        checkpoint()


def observe(image, *, template=None, text=None, region=None, threshold=None, contains=False, checkpoint):
    """Return a success receipt and one boolean for a valid local observation."""
    checkpoint()
    image_path = _local_file(image)
    with (_stable_sources((image_path,)),
          prepare_observation(template=template, text=text, region=region, threshold=threshold,
                              contains=contains, checkpoint=checkpoint) as (field, match)):
        found = match(_read(image_path, checkpoint))
    checkpoint()
    return {'status': 'success', field: found}
