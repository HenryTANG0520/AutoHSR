"""Score visible DU rewards; no blessing-name database or implicit spending."""
import re
from functools import lru_cache
from .config import RESOURCE_ROOT
from .models import normalize


def blessing_columns(scene):
    """Infer the centred one/two/three-card layout from visible card frames.

    Missing OCR alone must not turn a sliding three-card page into two choices.
    Fewer cards require matching frame geometry, with no title outside it.
    """
    default=((.14,.36),(.39,.61),(.64,.87))
    if scene.image is None:
        return default
    import cv2
    gray=cv2.cvtColor(cv2.resize(scene.image,(960,540)),cv2.COLOR_BGR2GRAY)
    contours,_=cv2.findContours(cv2.Canny(gray,35,100),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    centers=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if not (150<w<250 and 260<h<350 and 92<y<157):
            continue
        center=(x+w/2)/960
        if not any(abs(center-old)<.025 for old in centers):
            centers.append(center)
    for count in (1,2):
        expected=[.5+(i-(count-1)/2)*.25 for i in range(count)]
        if (len(centers)!=count or not all(any(abs(x-c)<.025 for c in centers) for x in expected)):
            continue
        columns=tuple((x-.11,x+.11) for x in expected)
        titles=[t for t in scene.tokens if t.within((.10,.445,.90,.495))
                and re.search(r'[\u3400-\u9fff]',t.text)]
        if all(any(t.within((a,.445,b,.495)) for a,b in columns) for t in titles):
            return columns
    return default


def same_blessing_titles(before,after):
    """Corroborate short OCR variations with every visible card's glyph row."""
    if before.image is None or after.image is None:
        return False
    import cv2
    import numpy as np
    if before.image.shape!=after.image.shape:
        return False
    columns=blessing_columns(before)
    if columns!=blessing_columns(after):
        return False
    h,w=before.image.shape[:2]
    for left,right in columns:
        x=(left+right)/2
        edges=[]
        for page in (before,after):
            patch=page.image[round(.45*h):round(.495*h),round((x-.095)*w):round((x+.095)*w)]
            if not patch.size:
                return False
            # White title ink stays fixed while card artwork/glow changes
            # during a reversible preview. Do not compare those decorations.
            hsv=cv2.cvtColor(cv2.resize(patch,(320,64)),cv2.COLOR_BGR2HSV)
            edge=(hsv[:,:,1]<65)&(hsv[:,:,2]>180)
            if np.count_nonzero(edge)<30:
                return False
            edges.append(edge)
        for source,target in (edges,edges[::-1]):
            near=cv2.dilate(target.astype(np.uint8),np.ones((3,3),np.uint8))>0
            if np.count_nonzero(source&near)/np.count_nonzero(source)<.93:
                return False
    return True


def rarity(scene, x):
    """Count gold star components in the observed card's fixed star row."""
    if scene.image is None:
        return 0
    import cv2
    import numpy as np
    h,w=scene.image.shape[:2]
    patch=scene.image[round(.485*h):round(.545*h),round((x-.045)*w):round((x+.045)*w)]
    if not patch.size:
        return 0
    hsv=cv2.cvtColor(cv2.resize(patch,(180,68)),cv2.COLOR_BGR2HSV)
    mask=((hsv[:,:,0]>=15)&(hsv[:,:,0]<=42)&(hsv[:,:,1]>95)&(hsv[:,:,2]>160)).astype(np.uint8)*255
    n,_,stats,centers=cv2.connectedComponentsWithStats(mask)
    stars=[(s,c) for s,c in zip(stats[1:],centers[1:])
           if 12<=s[4]<=900 and 3<=s[2]<=75 and 3<=s[3]<=40 and .45<=s[2]/s[3]<=5]
    # Gold words outside the central star line cannot determine rarity.
    stars=[(s,c) for s,c in stars if 45<=c[0]<=135]
    count=sum(max(1,round(s[2]/21)) for s,_ in stars)
    if 1<=count<=3:
        return count
    # Gold card backgrounds join the ordinary gold mask into one large blob.
    # Isolate the darker star outlines against their local background instead.
    color=cv2.resize(patch,(180,68))
    gray=cv2.cvtColor(color,cv2.COLOR_BGR2GRAY)
    contrast=cv2.morphologyEx(gray,cv2.MORPH_BLACKHAT,np.ones((9,9),np.uint8))
    outline=((contrast>12)&(hsv[:,:,0]>=15)&(hsv[:,:,0]<=42)&(hsv[:,:,1]>60)).astype(np.uint8)*255
    outline=cv2.morphologyEx(outline,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    n,_,stats,centers=cv2.connectedComponentsWithStats(outline)
    count=sum(min(3,max(1,round(s[2]/24))) for s,c in zip(stats[1:],centers[1:])
        if 60<=s[4]<=900 and 8<=s[2]<=85 and 10<=s[3]<=40
        and 45<=c[0]<=135 and 15<=c[1]<=45)
    return count if 1<=count<=3 else 0


def preview_progress(scene):
    """Use the game's own before->after equation preview, regardless of icon shape."""
    completions=0
    progress=0.0
    for token in scene.tokens:
        if not token.within((0,.87,1,.99)):
            continue
        text=normalize(token.text)
        for before,after,need in re.findall(r"(\d+)\D{1,4}?(\d+)/(\d+)",text):
            before,after,need=map(int,(before,after,need))
            if 0<=before<after<=30 and 1<=need<=20 and after-before==1 and before<need:
                completions+=after>=need
                progress+=1/(need-before)
    return completions,round(progress,3)


@lru_cache(maxsize=1)
def _recommendation_template():
    import cv2,numpy as np
    return cv2.imdecode(np.fromfile(RESOURCE_ROOT/'assets/templates/du_blessing_recommended.png',np.uint8),0)


def blessing_recommendation(scene,x):
    """Match the user's green badge only at this card's upper-right corner."""
    if scene.image is None:
        return 0.0
    import cv2,numpy as np
    h,w=scene.image.shape[:2]
    patch=scene.image[round(.20*h):round(.30*h),round((x+.06)*w):round((x+.115)*w)]
    if not patch.size:
        return 0.0
    patch=cv2.resize(patch,(106,108))
    gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    template=_recommendation_template()
    if template is None:
        return 0.0
    best=0.0
    for size in range(28,47,2):
        scaled=cv2.resize(template,(size,size),interpolation=cv2.INTER_AREA)
        _,score,_,(left,top)=cv2.minMaxLoc(cv2.matchTemplate(gray,scaled,cv2.TM_CCOEFF_NORMED))
        if not np.isfinite(score) or score<.82:
            continue
        icon=hsv[top:top+size,left:left+size]
        green=((icon[:,:,0]>=55)&(icon[:,:,0]<=95)&(icon[:,:,1]>80)&(icon[:,:,2]>130))
        dark=icon[:,:,2]<75
        if green.mean()>=.15 and dark.mean()>=.12:
            best=max(best,float(score))
    return round(best,3)


def blessing_score(scene,target,*,preview=False):
    x=target.center[0]
    text="\n".join(t.text for t in scene.tokens if t.within((x-.11,.35,x+.11,.80)))
    path="\n".join(t.text for t in scene.tokens if t.within((x-.11,.73,x+.11,.80)))
    complete,progress=preview_progress(scene) if preview else (0,0)
    dealer=int("发牌员" in text)
    elation=int("欢愉" in path)
    survival=int(any(word in text for word in ("免死","抵挡致命","复活","受到的伤害降低")))
    stars=rarity(scene,x)
    marker=blessing_recommendation(scene,x)
    # The user's explicit preference comes first. Existing strategy resolves
    # ties between marked cards, or choices with no visible recommendation.
    score=(bool(marker),complete,progress,dealer,elation,stars,survival)
    return score,{"recommended":bool(marker),"recommendation_confidence":marker,
                  "equations_completed":complete,"equation_progress":progress,
                  "dealer":bool(dealer),"elation":bool(elation),"stars":stars,
                  "survival":bool(survival)}


def blessing_discard_score(scene,target,*,preview=False):
    """Prefer losing an excess path over disabling or delaying an equation."""
    broken=0;setback=0.0
    if preview:
        for token in scene.tokens:
            if not token.within((0,.87,1,.99)):
                continue
            for before,after,need in re.findall(r'(\d+)\D{1,4}?(\d+)/(\d+)',normalize(token.text)):
                before,after,need=map(int,(before,after,need))
                if before-after==1 and 1<=need<=20:
                    broken+=before>=need>after
                    if after<need:
                        setback+=1/(need-after)
    _,benefit=blessing_score(scene,target)
    score=(-broken,-round(setback,3),-int(benefit['dealer']),-int(benefit['elation']),
           -benefit['stars'],-int(benefit['survival']))
    return score,{'equations_disabled':broken,'equation_setback':round(setback,3),**benefit}
