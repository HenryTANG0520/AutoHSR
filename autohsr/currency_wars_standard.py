"""Standard rank selection is separate from the historical overclock A0 start.

The numeric row, blue selected background and white numeral must agree. A
nearby visible row is not evidence that it is selected. No start action here.
"""
import re

from .currency_wars_prepare import trusted
from .models import AutomationError, normalize

SELECTED_FIELD = (.108, .342, .19, .443)


def difficulty_page(scene, confidence=.65):
    scene = trusted(scene, confidence)
    return (scene.has('货币战争', (0, 0, .2, .1), exact=True)
            and scene.has('标准博弈', (0, .78, .2, .86), exact=True)
            and any(re.fullmatch(r'a8财富造物主', normalize(t.text))
                    for t in scene.tokens if t.within((.02, .24, .25, .33)))
            and scene.has('当前职级难度效果', (.34, .24, .70, .34))
            and scene.has('开始对局', (.75, .82, .99, .97), exact=True))


def visible_ranks(scene, confidence=.65):
    scene = trusted(scene, confidence)
    if not difficulty_page(scene, confidence):
        raise AutomationError('当前不是已核实的标准A8职级配置页。')
    rows = []
    for token in scene.tokens:
        if token.within((.09, .31, .22, .80)) and re.fullmatch(r'[1-9][0-9]?', normalize(token.text)):
            value = int(normalize(token.text))
            if 1 <= value <= 50 and token.box[3]-token.box[1] >= .035:
                rows.append((value, token))
    if not rows or len({n for n, _ in rows}) != len(rows):
        raise AutomationError('职级数字缺失或不唯一。')
    ordered = sorted(rows, key=lambda row: row[1].center[1])
    if any(a[0]-b[0] != 1 for a, b in zip(ordered, ordered[1:])):
        raise AutomationError('职级列表数字顺序不一致。')
    return tuple(ordered)


def selected_rank(scene, confidence=.65):
    rows = visible_ranks(scene, confidence)
    if scene.image is None:
        raise AutomationError('职级选择缺少当前图像，未仅凭数字推测高亮。')
    import cv2
    import numpy as np
    height, width = scene.image.shape[:2]
    selected = []
    for value, token in rows:
        y = token.center[1]
        patch = scene.image[round((y-.025)*height):round((y+.025)*height),
                            round(.005*width):round(.035*width)]
        digit = scene.image[round(token.box[1]*height):round(token.box[3]*height),
                            round(token.box[0]*width):round(token.box[2]*width)]
        if not patch.size or not digit.size:
            continue
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        blue = ((hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 125) &
                (hsv[:, :, 1] >= 70) & (hsv[:, :, 2] >= 130)).mean()
        white = np.all(digit[:, :, :3] >= 215, axis=2).mean()
        if blue >= .55 and white >= .15:
            selected.append(value)
    if len(selected) != 1:
        raise AutomationError('职级高亮与数字不一致，未猜测当前等级。')
    return selected[0]


def rank_target(scene, confidence=.65):
    current = selected_rank(scene, confidence)
    if current == 40:
        return None
    rows = visible_ranks(scene, confidence)
    # Move toward 40 only through a visible, explicitly read row. Never count
    # blind wheel pulses or infer a hidden row's coordinates.
    options = [(value, token) for value, token in rows if
               40 <= value < current or current < value <= 40]
    if not options:
        raise AutomationError('目标方向没有可见职级行，需要核实列表滚动控件。')
    return min(options, key=lambda row: abs(row[0]-40))


def supplement_rank(scene, reader):
    """Run inside the OCR child; do not create an OCR runtime in the parent."""
    if scene.image is None or not difficulty_page(scene):
        return scene
    current = [t for t in trusted(scene).tokens if t.within(SELECTED_FIELD) and
               re.fullmatch(r'[1-9][0-9]?', normalize(t.text))]
    if current:
        return scene
    import cv2
    from .models import Token, Scene
    height, width = scene.image.shape[:2]
    x1, y1, x2, y2 = SELECTED_FIELD
    patch = scene.image[round(y1*height):round(y2*height), round(x1*width):round(x2*width)]
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    variants = (patch, cv2.threshold(gray, 210, 255, cv2.THRESH_BINARY)[1])
    fields = [reader.read_number(image) for image in variants]
    if (any(t is None or not .9 <= t.score <= 1 or not re.fullmatch(r'[1-9][0-9]?', t.text)
            or not 1 <= int(t.text) <= 50 for t in fields) or len({t.text for t in fields}) != 1):
        return scene
    token = Token(fields[0].text, min(t.score for t in fields), SELECTED_FIELD)
    return Scene(scene.tokens+[token], scene.image, scene.geometry, scene.captured_at,scene.field_reads)
