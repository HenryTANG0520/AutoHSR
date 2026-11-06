"""Bind a station preview to the live card body and its selection marker."""

from dataclasses import dataclass, replace
import re

from .config import RESOURCE_ROOT
from .du_station_policy import CARD_LABELS, LABELS
from .models import normalize

EFFECT_REGION=(.08,.14,.92,.33)
_STATION_HEADER = (0, 0, .32, .13)
_STATION_CONFIRM = (.51, .86, .71, .94)
_STATION_BODY = (.10, .14, .38, .33)
_STATION_BEACON_CAPTION = (.58, .21, .69, .28)
# Coordinates in the 960 × 540 view, inside the coloured panel edges.
_BEACON_PANEL = (390, 83, 856, 168)
_EMPTY_BEACON_GLYPHS = (574, 117, 645, 144)
_CONFIRM_SEARCH = (465, 458, 695, 514)
_REROLL_SEARCH = (263, 458, 492, 513)  # 960 × 540 view of the next-station control row.
_REROLL_FIELD = re.compile(r'重[ 　]*抽[ 　]*([0-9０-９]+)?')
_REROLL_NUMBER = re.compile(r'[0-9０-９]+')


def _reroll_button(image, *, exhausted=False):
    import cv2
    import numpy as np

    if not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        return None
    height, width = image.shape[:2]
    left, top, right, bottom = _REROLL_SEARCH
    patch = image[round(top*height/540):round(bottom*height/540), round(left*width/960):round(right*width/960)]
    if not patch.size:
        return None
    crop_width, crop_height = right-left, bottom-top
    crop = cv2.resize(patch, (crop_width, crop_height), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    # The exhausted 4.6 control has a dark cyan silhouette. This appearance
    # can corroborate a zero reading, never a positive usable count.
    limits = ((85, 70, 42), (111, 255, 155)) if exhausted else ((0, 0, 205), (179, 65, 255))
    mask = cv2.inRange(hsv, *limits)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 5), np.uint8))
    _, _, components, _ = cv2.connectedComponentsWithStats(mask)
    buttons = [(x, y, w, h) for x, y, w, h, area in components[1:]
               if 172 <= w <= 205 and 24 <= h <= 34 and area >= .85*w*h
               and 0 < x < x+w < crop_width and 0 < y < y+h < crop_height]
    if len(buttons) != 1:
        return None
    x, y, w, h = buttons[0]
    return ((left+x)/960, (top+y)/540, (left+x+w)/960, (top+y+h)/540)


def station_reroll_observation(scene, confidence=.85):
    """Read a displayed count from the current next-station control."""
    unread = dict(status='unverified', displayed_count=None)
    trusted = [token for token in scene.tokens if confidence <= token.score <= 1]
    headings = {token.text.strip() for token in trusted if token.within(_STATION_HEADER)}
    confirms = [token for token in trusted if token.text.strip() == '确定' and token.within(_STATION_CONFIRM)]
    if not {'差分宇宙', '选择下一站'} <= headings or len(confirms) != 1:
        return dict(unread, reason='layout_unverified')
    button = _reroll_button(scene.image)
    exhausted = button is None
    if exhausted:
        control_region = (.30, .87, .48, .93)
        if not any(t.within(control_region) and re.fullmatch(r'(?:重[ 　]*抽[ 　]*)?[0０]', t.text.strip())
                   for t in trusted):
            return dict(unread, reason='control_unverified')
        button = _reroll_button(scene.image, exhausted=True)
    if button is None or abs(confirms[0].center[1] - (button[1]+button[3])/2) > .016:
        return dict(unread, reason='control_unverified')

    left, top, right, bottom = button
    margin_x, margin_y = .20*(right-left), .12*(bottom-top)
    fields = [token for token in trusted if left+margin_x <= token.box[0] < token.box[2] <= right-margin_x
              and top+margin_y <= token.box[1] < token.box[3] <= bottom-margin_y]
    labels = [(token, match.group(1)) for token in fields
              if (match := _REROLL_FIELD.fullmatch(token.text.strip()))]
    if not labels:
        return dict(unread, reason='count_unverified')
    if len(labels) > 1 or len(fields) > 2:
        return dict(unread, reason='conflicting_fields')
    (label, count), = labels
    if count is not None and len(fields) != 1:
        return dict(unread, reason='conflicting_fields')
    if count is None:
        if len(fields) != 2:
            return dict(unread, reason='count_unverified')
        value, = (token for token in fields if token is not label)
        count = value.text.strip()
        gap = value.box[0] - label.box[2]
        overlap = min(label.box[3], value.box[3]) - max(label.box[1], value.box[1])
        height = min(label.box[3]-label.box[1], value.box[3]-value.box[1])
        if not _REROLL_NUMBER.fullmatch(count) or not -.004 <= gap <= .035 or overlap < .60*height:
            return dict(unread, reason='count_unverified')
    try:
        count = int(count)
        if exhausted and count != 0:
            return dict(unread, reason='control_unverified')
        return dict(status='observed', displayed_count=count)
    except ValueError:
        return dict(unread, reason='count_unverified')


@dataclass(frozen=True)
class StationCard:
    bounds: tuple[float, float, float, float]
    selected: bool

    @property
    def center_x(self):
        return (self.bounds[0]+self.bounds[2])/2

    def holds_label(self, token):
        left,top,right,bottom=self.bounds
        x1,y1,x2,y2=token.box
        return left<=x1<x2<=right and top+.70*(bottom-top)<=y1<y2<=bottom


def station_cards(scene):
    """Find card bodies in the station row, independent of their column count."""
    if scene.image is None:
        return ()
    import cv2
    import numpy as np
    hsv=cv2.cvtColor(cv2.resize(scene.image,(960,540)),cv2.COLOR_BGR2HSV)
    left,top,right,bottom=173,180,795,443
    white=cv2.inRange(hsv[top:bottom,left:right],(0,0,210),(179,70,255))
    white=cv2.morphologyEx(white,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    _,_,stats,_=cv2.connectedComponentsWithStats(white)
    cards=[]
    for x,y,width,height,area in stats[1:]:
        if not (80<=width<=185 and 1.4*width<=height<=1.85*width and area>=.55*width*height):
            continue
        x,y=int(x+left),int(y+top)
        width,height=int(width),int(height)
        if x<=left or y<=top or x+width>=right or y+height>=bottom:
            continue
        bounds=(x/960,y/540,(x+width)/960,(y+height)/540)
        cards.append(StationCard(bounds,_selection_marker(hsv,x,y,width)))
    return tuple(sorted(cards,key=lambda card:card.center_x))


def _selection_marker(hsv,x,y,width):
    """Read the aligned, green-outlined dark cores above a selected card."""
    import cv2
    import numpy as np
    center=x+width/2
    left,right=round(center-.11*width),round(center+.11*width)
    top,bottom=round(y-.15*width),round(y+.05*width)
    patch=hsv[top:bottom,left:right]
    dark=cv2.inRange(patch,(0,0,0),(179,255,70))
    green=cv2.inRange(patch,(50,70,120),(96,255,255))>0
    _,labels,stats,centers=cv2.connectedComponentsWithStats(dark)
    cores=[]
    for index,(_,_,w,h,area) in enumerate(stats[1:],1):
        cx,cy=centers[index]
        if (not .025*width<=w<=.12*width or not .04*width<=h<=.11*width
                or area<.001*width*width or abs(cx-(center-left))>.038*width):
            continue
        core=labels==index
        outline=(cv2.dilate(core.astype(np.uint8),np.ones((3,3),np.uint8))>0)&~core
        if np.count_nonzero(green&outline)>=.60*np.count_nonzero(outline):
            cores.append((cx,cy,w))
    if len(cores)!=2:
        return False
    upper,lower=sorted(cores,key=lambda core:core[1])
    return bool(abs(upper[0]-lower[0])<=.03*width and .025*width<=lower[1]-upper[1]<=.07*width
                and lower[2]>=1.3*upper[2])


def card_for_label(scene,cards,target):
    """Use the exact observed title in the card footer, never a nearby label."""
    matches=[]
    for card in cards:
        if not card.holds_label(target):
            continue
        titles=[token for token in scene.tokens if token.within(CARD_LABELS) and card.holds_label(token)
                and normalize(token.text) in LABELS]
        if titles==[target]:
            matches.append(card)
    return matches[0] if len(matches)==1 else None


@dataclass(frozen=True)
class StationEffectInk:
    screen: object
    ink: object
    danger_rows: tuple


def station_effect_ink(scene):
    """Collect supported effect glyphs inside the current OCR line boxes."""
    if scene.image is None:
        return None
    import cv2
    import numpy as np
    left,top,right,bottom=EFFECT_REGION
    ox,oy=round(left*960),round(top*540)
    crop=cv2.resize(scene.image,(960,540))[oy:round(bottom*540),ox:round(right*960)]
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    screen=cv2.inRange(hsv,(0,0,155),(179,70,255))>0
    observed=np.zeros_like(screen)
    parts=[]
    rows=[]
    offset=0
    for token in scene.tokens:
        if not token.within(EFFECT_REGION):
            continue
        part=normalize(token.text)
        start,offset=offset,offset+len(part)
        parts.append(part)
        if not re.search(r'[\u3400-\u9fff]',part):
            continue
        x1,y1,x2,y2=token.box
        if not (left<=x1<x2<=right and top<=y1<y2<=bottom):
            return None
        row=(slice(round(y1*540)-oy,round(y2*540)-oy),slice(round(x1*960)-ox,round(x2*960)-ox))
        ink=screen[row]
        count=np.count_nonzero(ink)
        if count<16 or count>.55*ink.size or np.count_nonzero(np.any(ink,axis=0))<.4*ink.shape[1]:
            return None
        _,_,stats,_=cv2.connectedComponentsWithStats(ink.astype(np.uint8))
        areas=stats[1:,4]
        if np.count_nonzero(areas>=2)<2 or areas.max()>.55*count:
            return None
        observed[row]=ink
        rows.append((start,offset,row))
    if not rows:
        return None
    # Use the same reading order as the hazard parser. A phrase can cross
    # OCR boxes without turning unrelated rows into danger evidence.
    spans=[match.span() for match in re.finditer(r'跟你爆了|敌人被消灭时自爆',''.join(parts))]
    danger=tuple(row for start,end,row in rows if any(start<last and first<end for first,last in spans))
    return StationEffectInk(screen,observed,danger)


def station_effect_covered(source,target):
    """Whether almost all source glyph pixels exist in the other preview."""
    import cv2
    import numpy as np
    near=cv2.dilate(target.astype(np.uint8),np.ones((3,3),np.uint8))>0
    return np.count_nonzero(source&near)>=.93*np.count_nonzero(source)


def three_card_station_row(cards):
    """Distinguish the observed centered row from an incomplete four-card row."""
    return len(cards) == 3 and all(abs(card.center_x-center) <= .03
                                   for card, center in zip(cards, (.36, .50, .64)))


def _inside(token, region):
    left, top, right, bottom = region
    x1, y1, x2, y2 = token.box
    return left <= x1 < x2 <= right and top <= y1 < y2 <= bottom


def _highlighted_confirm(hsv, target):
    import cv2

    left, top, right, bottom = _CONFIRM_SEARCH
    yellow = cv2.inRange(hsv[top:bottom, left:right], (23, 92, 184), (47, 255, 255))
    _, _, stats, _ = cv2.connectedComponentsWithStats(yellow)
    controls = [(x, y, w, h) for x, y, w, h, area in stats[1:]
                if 185 <= w <= 208 and 26 <= h <= 32 and area >= .83*w*h
                and 0 < x < x+w < right-left and 0 < y < y+h < bottom-top]
    if len(controls) != 1:
        return False
    (x, y, width, height), = controls
    return _inside(target, ((left+x+.18*width)/960, (top+y+.08*height)/540,
                            (left+x+.82*width)/960, (top+y+.92*height)/540))


def station_empty_beacon_effect_ink(scene, confirm, confidence=.85):
    """Verify the three-card layout's dim no-beacon panel and enabled control."""
    if (scene.image is None or confirm is None or confirm.text.strip() != '确定'
            or not confidence <= confirm.score <= 1):
        return None
    trusted = [token for token in scene.tokens if confidence <= token.score <= 1]
    headings = {token.text.strip() for token in trusted if _inside(token, _STATION_HEADER)}
    if not {'差分宇宙', '选择下一站'} <= headings:
        return None
    lines = [token for token in scene.tokens if token.within(EFFECT_REGION)]
    body = [token for token in lines if _inside(token, _STATION_BODY)]
    caption = [token for token in lines if _inside(token, _STATION_BEACON_CAPTION)
               and token.text.strip() == '暂无信标']
    if (len(caption) != 1 or len(lines) != len(body)+1
            or any(token not in trusted for token in lines)):
        return None

    import cv2
    import numpy as np

    hsv = cv2.cvtColor(cv2.resize(scene.image, (960, 540)), cv2.COLOR_BGR2HSV)
    if not _highlighted_confirm(hsv, confirm):
        return None
    left, top, right, bottom = _EMPTY_BEACON_GLYPHS
    if not _inside(caption[0], (left/960, top/540, right/960, bottom/540)):
        return None
    glyphs = cv2.inRange(hsv[top:bottom, left:right], (0, 0, 55), (179, 70, 154)) > 0
    left, top, right, bottom = _BEACON_PANEL
    if np.count_nonzero(hsv[top:bottom, left:right, 2] >= 55) != np.count_nonzero(glyphs):
        return None
    try:
        raw = (RESOURCE_ROOT/'assets/templates/du_station_empty_beacon_ink.png').read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    reference = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
    if (reference is None or reference.shape != glyphs.shape or not np.any(reference)
            or not station_effect_covered(glyphs, reference > 0)
            or not station_effect_covered(reference > 0, glyphs)):
        return None
    return station_effect_ink(replace(scene, tokens=body))


def station_preview_observation(scene, confidence=.85):
    """Describe the observed card and description for page history."""
    import numpy as np

    image = scene.image
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.ndim != 3 or image.shape[2] != 3 or not image.size):
        return None
    trusted = [token for token in scene.tokens if confidence <= token.score <= 1]
    headings = {token.text.strip() for token in trusted if token.within(_STATION_HEADER)}
    confirms = [token for token in trusted if token.text.strip() == '确定' and token.within(_STATION_CONFIRM)]
    if not {'差分宇宙', '选择下一站'} <= headings or len(confirms) != 1:
        return None
    cards = station_cards(scene)
    if len(cards) not in (3, 4):
        return None
    marked = [(column, card) for column, card in enumerate(cards, 1) if card.selected]
    choosing = any(token.text.strip() == '选择一张站点卡' and token.within(EFFECT_REGION) for token in trusted)
    if not marked and choosing:
        return dict(status='awaiting_selection', visible_card_count=len(cards))
    if len(marked) != 1 or choosing:
        return None
    (column, selected), = marked
    titles = [token for token in trusted if token.within(CARD_LABELS)
              and normalize(token.text) in LABELS and card_for_label(scene, cards, token) == selected]
    if len(titles) != 1:
        return None

    # The left description has white glyphs. The right panel can show a
    # dim “暂无信标” caption which is a separate OCR observation.
    body = [token for token in trusted if _inside(token, _STATION_BODY)]
    observation = dict(status='selected', visible_card_count=len(cards),
                       selected_column=column, selected_label=titles[0].text.strip(),
                       body_text=None, beacon_caption=None)
    if station_effect_ink(replace(scene, tokens=body)) is not None:
        observation['body_text'] = [token.text.strip() for token in body]
    captions = [token for token in trusted if _inside(token, _STATION_BEACON_CAPTION)]
    if len(captions) == 1 and captions[0].text.strip() == '暂无信标':
        observation['beacon_caption'] = captions[0].text.strip()
    return observation
