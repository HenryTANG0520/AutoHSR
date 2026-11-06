"""Page evidence for the observed ten-tier DU weekly rewards layout."""
from datetime import timedelta
import re
import time

from . import du_rewards
from .currency_wars_points import compact, game_week, local_now, read_points
from .currency_wars_prepare import trusted
from .currency_wars_weekly_rewards import (
    CLAIM_CAPTION, CLAIM_FRAGMENTS, OVERLAY_TITLE, PANEL_BLOCKERS, PANEL_MODAL,
    kind as shared_kind, panel_control,
)
from .du_periodic_points import GuidePointsUnverified, _horizontal_row, _require_countdown, read_home_points_panel
from .free_rewards import gold_fraction
from .models import AutomationError


CATEGORY = '周期积分'
PANEL = 'periodic_rewards'
OPEN = 'du_reward_periodic_open'
CLAIM = 'du_reward_periodic_claim'
DISMISS = 'du_reward_dismiss'
BACK = 'du_reward_back_home'
TIERS = tuple(range(1800, 18001, 1800))
LIMIT = TIERS[-1]
PANEL_TIME = (.04, .327, .228, .370)
BADGE = (.172, .860, .242, .925)
BUTTON = (.758, .631, .950, .704)
CONFLICTS = ('账号验证', '账号登录', '验证码', '用户协议', '资源下载', '继续进度', '结束并结算')


def current_week():
    return game_week(local_now())


def capture_time(scene, week):
    now = local_now()
    captured = now - timedelta(seconds=time.monotonic() - scene.captured_at)
    if game_week(now) != week or game_week(captured) != week:
        raise AutomationError('差分周期领奖游戏周已改变，保留原记录。')
    return captured


def home_control(scene, week, confidence):
    clean = trusted(scene, confidence)
    if du_rewards.home_signature(clean) is None or _blocked(scene):
        return None
    try:
        points = read_home_points_panel(scene, capture_time(scene, week), week, confidence)
    except GuidePointsUnverified:
        return None
    value = points.tokens[-1]
    dots = du_rewards.red_dots(scene, BADGE)
    if len(dots) > 1 or dots and not (
            -.006 <= dots[0].center[0] - value.box[2] <= .025
            and -.045 <= dots[0].center[1] - value.center[1] <= -.018):
        return None
    return points, value if dots else None


def _blocked(scene):
    return (scene.has(CONFLICTS)
            or scene.has(PANEL_BLOCKERS, PANEL_MODAL, exact=True)
            or scene.has('获得物品', OVERLAY_TITLE, exact=True)
            or scene.has('点击空白处关闭', (.25, .65, .75, .90), exact=True))


def panel_score(scene, week, confidence):
    if shared_kind(scene, confidence) != 'points_rewards' or _blocked(scene):
        return None
    captured = capture_time(scene, week)
    try:
        points = read_points(scene, confidence)
        if points.current != LIMIT or points.limit != LIMIT:
            return None
        parts = _horizontal_row(scene, PANEL_TIME, confidence, 'periodic_reward_panel_timer')
        text = compact(''.join(token.text for token in parts).lstrip().removeprefix('①'))
        match = re.fullmatch(r'本期剩余时间:?(.*)', text)
        if match is None:
            return None
        _require_countdown(match[1], captured, week)
    except (AutomationError, GuidePointsUnverified):
        return None
    return dict(current=points.current, cap=points.limit, game_week=week)


def _verified_tiers(scene, confidence, *, claimed):
    import cv2
    import numpy as np

    image = scene.image
    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        return False
    height, width = image.shape[:2]
    mark = np.zeros((21, 22), np.uint8)
    cv2.ellipse(mark, (10, 10), (9, 9), 0, 0, 320, 255, 1, cv2.LINE_AA)
    cv2.polylines(mark, [np.array([(5, 9), (9, 13), (18, 4)], np.int32)], False, 255, 2, cv2.LINE_AA)
    for index, threshold in enumerate(TIERS):
        x = .081 + index * .0906
        patch = image[round(.451 * height):round(.505 * height),
                      round((x - .0182) * width):round((x + .0182) * width)]
        if not patch.size:
            return False
        gray = cv2.cvtColor(cv2.resize(patch, (27, 25)), cv2.COLOR_BGR2GRAY)
        check = cv2.matchTemplate(gray, mark, cv2.TM_CCOEFF_NORMED).max()
        brightness = float(np.median(gray))
        # The post-claim labels darken. Bind the columns to the verified
        # pre-claim thresholds and read the ring and check mark on return.
        if claimed:
            if check < .58 or brightness > 85 or not .05 <= np.mean(gray >= 128) <= .30:
                return False
        else:
            labels = [token for token in scene.tokens if token.within((x-.036, .515, x+.036, .575))
                      and re.search(r'[0-9０-９]', token.text)]
            if (len(labels) != 1 or not confidence <= labels[0].score <= 1
                    or compact(labels[0].text) != str(threshold) or check >= .58 or brightness <= 85):
                return False
    return True


def claim_target(scene, week, confidence):
    if (panel_score(scene, week, confidence) is None
            or scene.has(CLAIM_FRAGMENTS, BUTTON, exact=True)
            or not _verified_tiers(scene, confidence, claimed=False)):
        return None
    try:
        state, target = panel_control(scene, confidence)
    except AutomationError:
        return None
    return target if state == 'available' and target is not None and target.within(BUTTON) else None


def claimed_panel(scene, week, confidence):
    score = panel_score(scene, week, confidence)
    if score is None or scene.has((CLAIM_CAPTION, *CLAIM_FRAGMENTS), BUTTON, exact=True):
        return None
    gold = gold_fraction(scene, BUTTON)
    if gold is None or gold >= .05 or not _verified_tiers(scene, confidence, claimed=True):
        return None
    return dict(**score, claimed_tiers=list(TIERS))
