"""A read-only gate for one visually supported Odyssey dismissal transition."""
import cv2
import numpy as np

from .vision import helper_overlay


# Boxes are fixed in a 640×360 view. Compare structure and retained contrast,
# using the actual pre-claim page and the actual same-run reward as references.
_PAGE = (
    ((536, 54, 614, 76), .62, .18, .85),  # Odyssey title
    ((20, 98, 79, 125), .90, .30, .85),  # selected left event row
    ((368, 134, 383, 197), .88, .30, .85),  # top card divider
)
_POPUP = (
    ((306, 23, 334, 61), .30, .10, 1.15),  # obtain-item emblem and caption
    ((299, 155, 341, 203), .76, .45, 1.10),  # same reward tile
    ((314, 193, 327, 202), .60, .28, 1.10),  # its quantity glyph
)
_BLOCKERS = ('确认购买', '确认支付', '切换账号', '退出登录', '账号登录', '登录中',
             '重新连接', '网络连接失败', '连接中断', '加载中', '正在加载')


def _gradient(image, box):
    left, top, right, bottom = box
    gray = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
    return np.concatenate(tuple(
        cv2.Sobel(gray, cv2.CV_32F, dx, dy)[1:-1, 1:-1].ravel() for dx, dy in ((1, 0), (0, 1))))


def _matches(reference, current, regions):
    for box, minimum, minimum_ratio, maximum_ratio in regions:
        first, second = _gradient(reference, box), _gradient(current, box)
        first_norm, second_norm = np.linalg.norm(first), np.linalg.norm(second)
        if first_norm == 0 or not minimum_ratio * first_norm <= second_norm <= maximum_ratio * first_norm:
            return False
        if np.dot(first, second) < minimum * first_norm * second_norm:
            return False
    return True


def observed_return_fade(before, popup, candidate):
    """Recognize only overlap of this page and reward, never a return result."""
    if candidate.page is not None or candidate.tickets is not None or candidate.button is not None:
        return False
    scene = candidate.scene
    if (helper_overlay(scene) or scene.has(_BLOCKERS, exact=True)
            or scene.has('活动说明', (.25, .06, .75, .88), exact=True)):
        return False
    images = before.image, popup.image, candidate.image
    if any(not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3
           or image.shape != images[0].shape or image.shape[2] != 3
           or image.shape[0] < 360 or abs(image.shape[1] / image.shape[0] - 16 / 9) > .04 for image in images):
        return False
    before_view, popup_view, current_view = (
        cv2.resize(image, (640, 360), interpolation=cv2.INTER_AREA) for image in images)
    return _matches(before_view, current_view, _PAGE) and _matches(popup_view, current_view, _POPUP)
