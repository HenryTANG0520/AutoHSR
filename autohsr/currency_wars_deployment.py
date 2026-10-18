"""Single, reversible deployment diagnostic; no shop, battle or retry loop."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .currency_wars_match import read_match
from .models import AutomationError

# Fixed four front slots calibrated at 2560x1440; backend width can change.
SWAP_START = (1370 / 2560, 530 / 1440)
SWAP_END = (990 / 2560, 530 / 1440)
_FACES = ((.37, .33, .405, .39), (.52, .33, .555, .39))
_SLOTS = ((.35, .295, .425, .44), (.50, .295, .575, .44))
BENCH_START = (915 / 2560, 1210 / 1440)
_BENCH_FACE = (.344, .819, .371, .865)
_BENCH_CENTERS = tuple(x/2560 for x in (585,750,915,1082,1248,1415,1582,1750,1915))


def bench_face(slot):
    if type(slot) is not int or not 1 <= slot <= 9:
        raise AutomationError('备战槽位应为1到9。')
    cx = _BENCH_CENTERS[slot-1]
    return (cx-.0135,.819,cx+.0135,.865)


def _crop(image, roi):
    h, w = image.shape[:2]
    x1, y1, x2, y2 = roi
    return image[round(y1*h):round(y2*h), round(x1*w):round(x2*w)]


def _similarity(patch, area):
    import cv2
    value = float(cv2.matchTemplate(area, patch, cv2.TM_CCOEFF_NORMED).max())
    return value if math.isfinite(value) else 0.


def _texture(patch):
    # Spatial variation per channel; a flat blue slot is not a portrait.
    return float(patch.reshape(-1, 3).std(axis=0).mean()) if patch.size else 0.


@dataclass(frozen=True)
class DeploymentPlan:
    backend_slots: int
    target_slot: int
    start: tuple[float, float]
    end: tuple[float, float]
    source_slot: int = 3
    zone: str = 'back'


def backend_layout(image):
    """Recognize the observed six/seven-slot layouts, including Gemi's slot."""
    import cv2
    import numpy as np
    if image is None or image.ndim != 3 or min(image.shape[:2]) < 720:
        raise AutomationError('后台槽位图像不足，未执行部署。')
    height, width = image.shape[:2]
    edges = cv2.Canny(image, 50, 120)
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    horizontal_gradient=np.abs(cv2.Sobel(gray,cv2.CV_32F,1,0))
    vertical_gradient=np.abs(cv2.Sobel(gray,cv2.CV_32F,0,1))
    # Overflow paints diagonal red hatching inside empty slots. Count vertical
    # frame edges, so those diagonals cannot imitate the alternate layout.
    edges[horizontal_gradient<vertical_gradient*2.5]=0
    candidates = []
    for count, first in ((6, 805), (7, 710)):
        centers = [(first + 190 * i) / 2560 for i in range(count)]
        points = []
        for cx in centers:
            for y in np.linspace(.565, .675, 35):
                for side in (-1, 1):
                    x, py, pad = round((cx + side * .032) * width), round(y * height), round(width * .005)
                    points.append(bool(edges[py, max(0, x-pad):min(width, x+pad)].max()))
        candidates.append((sum(points) / len(points), count, centers))
    candidates.sort(reverse=True)
    best, other = candidates
    if best[0] < .8 or best[0] - other[0] < .25:
        raise AutomationError('后台布局无法区分，未执行部署。')
    return best[1], best[2]


def plan_bench_deployment(scene, confidence=.65, *, source_slot=3, zone='back'):
    """One explicit diagnostic: selected bench slot to an empty front/back slot.

    This is not a character selection policy. The GUI tells the operator to
    check the source character's positional eligibility before choosing the test.
    """
    state = read_match(scene, confidence)
    if (state is None or state.page != 'preparation' or not state.node
            or state.deployment is None or state.deployment[0] >= state.deployment[1]):
        raise AutomationError('需要无遮挡备战页、明确节点及剩余出战容量。')
    count, centers = backend_layout(scene.image)
    if zone not in ('front','back'):
        raise AutomationError('部署区域未核实。')
    if _texture(_crop(scene.image, bench_face(source_slot))) < 15:
        raise AutomationError(f'备战区第{source_slot}格没有可验证的角色图像。')
    start = (_BENCH_CENTERS[source_slot-1],1210/1440)
    if zone == 'front':
        for index,cx in enumerate(x/2560 for x in (990,1180,1370,1560)):
            if _texture(_crop(scene.image,(cx-.025,.33,cx+.025,.41))) < 8:
                return DeploymentPlan(count,index+1,start,(cx,530/1440),source_slot,zone)
        raise AutomationError('前台没有已确认的空格。')
    # In the seven-slot variant the final slot belongs to Gemi, never a target.
    for index, cx in enumerate(centers[:6]):
        if _texture(_crop(scene.image, (cx-.025, .58, cx+.025, .66))) < 8:
            return DeploymentPlan(count, index + 1, start, (cx, 890 / 1440),source_slot,zone)
    raise AutomationError('后台没有已确认的空格。')


def verify_bench_deployment(before, after, plan, confidence=.65):
    import cv2
    import numpy as np
    previous, current = read_match(before, confidence), read_match(after, confidence)
    if (previous is None or current is None or current.page != 'preparation'
            or not previous.node or previous.node != current.node or after.image is None
            or before.image.shape != after.image.shape or current.deployment is None):
        return dict(status='unknown', reason='page_or_geometry_changed')
    cx = plan.end[0]
    target_roi = (cx-.039, .55, cx+.039, .69) if plan.zone == 'back' else (cx-.039,.295,cx+.039,.44)
    source_roi = bench_face(plan.source_slot)
    face = _crop(before.image, source_roi)
    source_x = plan.start[0]
    # Front portraits tilt and stretch near the board edge. Verify two spatial
    # features (eyes/face and upper portrait), rather than lower a whole-card
    # threshold. Native front-4 evidence: .917/.894; other portraits <= .679.
    features = ([face] if plan.zone == 'back' else
                [_crop(before.image,(source_x-.0075,.833,source_x+.0075,.858)),
                 _crop(before.image,(source_x-.008,.82,source_x+.008,.85))])
    if any(_texture(patch)<8 for patch in features):
        return dict(status='unknown',reason='insufficient_portrait_features')
    def score(image):
        area = _crop(image, target_roi)
        features_found=[]
        for feature in features:
            scores = []
            for scale in np.linspace(.8, 1.2, 17):
                patch = cv2.resize(feature, None, fx=float(scale), fy=float(scale))
                if all(a <= b for a, b in zip(patch.shape[:2], area.shape[:2])):
                    scores.append(_similarity(patch, area))
            features_found.append(max(scores, default=0.))
        return min(features_found)
    appeared, prior = score(after.image), score(before.image)
    source_empty = _texture(_crop(after.image, source_roi)) < 8
    increased = current.deployment == (previous.deployment[0] + 1, previous.deployment[1])
    unchanged = current.deployment == previous.deployment and _similarity(face, _crop(after.image, (source_x-.0275,.78,source_x+.0275,.91))) >= .92
    status = ('verified' if source_empty and increased and appeared >= .78 and appeared-prior >= .20
              and previous.gold is not None and current.gold == previous.gold else
              'unchanged' if unchanged else 'unknown')
    return dict(status=status, target_score=appeared, prior_target_score=prior,
                source_empty=source_empty, deployment_before=previous.deployment,
                deployment_after=current.deployment, gold_before=previous.gold, gold_after=current.gold)


def require_distinct_front_pair(scene, confidence=.65):
    state = read_match(scene, confidence)
    if state is None or state.page != 'preparation' or scene.image is None:
        raise AutomationError('拖动验证需要无遮挡的货币战争备战页。')
    faces = [_crop(scene.image, roi) for roi in _FACES]
    if any(_texture(face) < 12 for face in faces):
        raise AutomationError('前台第1/3格没有可验证的角色图像。')
    if _similarity(faces[0], _crop(scene.image, _SLOTS[1])) > .8:
        raise AutomationError('两格角色图像无法区分，未执行拖动。')
    return state


def verify_front_swap(before, after, confidence=.65):
    """Template search tolerates hover lift; deployment count alone is no proof."""
    previous = require_distinct_front_pair(before, confidence)
    current = read_match(after, confidence)
    if (current is None or current.page != 'preparation' or previous.node != current.node
            or after.image is None or before.image.shape != after.image.shape):
        return dict(status='unknown', reason='page_or_geometry_changed')
    face1, face3 = [_crop(before.image, roi) for roi in _FACES]
    slot1, slot3 = [_crop(after.image, roi) for roi in _SLOTS]
    cross = (_similarity(face3, slot1), _similarity(face1, slot3))
    same = (_similarity(face1, slot1), _similarity(face3, slot3))
    # Front cards have a perspective transform and the hovered card lifts.
    # Native 4K swap evidence scores .806/.829 vs .427/.467 for staying put.
    # Require BOTH crossed identities plus a margin over BOTH original slots.
    status = ('verified' if min(cross) >= .78 and min(cross) - max(same) >= .20 else
              'unchanged' if min(same) >= .92 else 'unknown')
    return dict(status=status, cross_scores=list(cross), unchanged_scores=list(same))


def test_front_swap(context):
    """GUI-selected experiment, exactly one drag, always records partial goal."""
    from .currency_wars import CurrencyWarsWorkflow, TASK
    from .models import TaskResult
    import json
    from pathlib import Path
    c = context
    c.checkpoint()
    before = c.snapshot()
    require_distinct_front_pair(before, c.settings.ocr_confidence)
    before_path = c.evidence(before, 'currency_front_swap_before')
    guard = CurrencyWarsWorkflow(c)
    guard._require_current_scene(before)
    data = dict(mode='single_drag_test', completion_verified=False, gameplay_enabled=False,
                action='drag_front_3_to_1', action_status='pending', screenshot=str(before_path),
                before=str(before_path), start=list(SWAP_START), end=list(SWAP_END))
    c.report.currency_wars = data
    # Durable intent before input. An exception never resumes/replays this test.
    journal = Path(c.report.run_dir) / 'currency-drag.json'
    journal.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    c.checkpoint()
    guard._require_current_scene(before)
    c.drag(before, SWAP_START, SWAP_END)
    after = c.snapshot()
    c.checkpoint()
    guard._require_current_scene(after)
    after_path = c.evidence(after, 'currency_front_swap_after')
    c.checkpoint()
    guard._require_current_scene(after)
    feedback = verify_front_swap(before, after, c.settings.ocr_confidence)
    data.update(action_status=feedback['status'], feedback=feedback, after=str(after_path), screenshot=str(after_path))
    journal.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    c.runner.emit(dict(type='currency_wars', data=data))
    detail = {'verified': '前台第1、3格角色图像已互换，单次拖动验证通过。',
              'unchanged': '角色图像未互换，拖动未生效；未重复执行。',
              'unknown': '拖动结果尚未确认；请核对前后截图，未重复执行。'}[feedback['status']]
    c.log(detail)
    c.report.safe_next = '仅完成一次拖动实验；自动阵容、商店与整局流程仍待验证。'
    return TaskResult(TASK, 'partial', detail)


def test_bench_deployment(context):
    """Exactly one reversible placement; durable intent, no automatic replay."""
    import json
    from pathlib import Path
    from .currency_wars import CurrencyWarsWorkflow, TASK
    from .models import TaskResult
    c = context
    c.checkpoint()
    before = c.snapshot()
    plan = plan_bench_deployment(before, c.settings.ocr_confidence,
        source_slot=getattr(c.runner,'currency_source_slot',3),zone=getattr(c.runner,'currency_zone','back'))
    before_path = c.evidence(before, 'currency_bench_deploy_before')
    guard = CurrencyWarsWorkflow(c)
    guard._require_current_scene(before)
    data = dict(mode='single_deployment_test', completion_verified=False, gameplay_enabled=False,
                action=f'deploy_bench_{plan.source_slot}_to_{plan.zone}', action_status='pending',
                before=str(before_path), screenshot=str(before_path), start=list(plan.start),
                end=list(plan.end), backend_slots=plan.backend_slots, target_slot=plan.target_slot,
                source_slot=plan.source_slot,zone=plan.zone)
    c.report.currency_wars = data
    journal = Path(c.report.run_dir) / 'currency-drag.json'
    journal.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    c.checkpoint()
    guard._require_current_scene(before)
    c.drag(before, plan.start, plan.end)
    after = c.snapshot()
    c.checkpoint()
    guard._require_current_scene(after)
    after_path = c.evidence(after, 'currency_bench_deploy_after')
    c.checkpoint()
    guard._require_current_scene(after)
    feedback = verify_bench_deployment(before, after, plan, c.settings.ocr_confidence)
    data.update(action_status=feedback['status'], feedback=feedback, after=str(after_path), screenshot=str(after_path))
    journal.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    c.runner.emit(dict(type='currency_wars', data=data))
    detail = {'verified': f'备战区第{plan.source_slot}格角色已进入空'+('前台' if plan.zone=='front' else '后台')+'格，出战人数增加且金币未变。',
              'unchanged': '部署未改变；未重复执行。',
              'unknown': '部署结果尚未确认；核对前后截图，未重复执行。'}[feedback['status']]
    c.log(detail)
    c.report.safe_next = '单次部署结束；继续核实角色适配、装备与完整对局。'
    return TaskResult(TASK, 'partial', detail)
