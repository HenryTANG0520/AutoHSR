"""Bind a station preview to the live card body and its selection marker."""

from dataclasses import dataclass
import re

from .du_station_policy import CARD_LABELS, LABELS
from .models import normalize

EFFECT_REGION=(.08,.14,.92,.33)


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
