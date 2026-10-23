"""Visual landmarks for bounded Differential Universe field navigation."""
from functools import lru_cache

from .config import RESOURCE_ROOT
from .models import Scene, Token, normalize


def optional_device_prompt(scene, *, forge_console_used=False):
    """An optional machine prompt authorizes only moving away, never F."""
    import re
    from .policy import has_du_field_plane_marker
    if scene.image is None or not has_du_field_plane_marker(normalize(scene.text)):
        return None
    header=normalize('\n'.join(t.text for t in scene.tokens if t.within((0,0,.40,.12))))
    wealth='位面-财富' in header or '位面—财富' in header
    prompts=[]
    for token in scene.tokens:
        if not token.within((.60,.45,.85,.70)):
            continue
        label=normalize(token.text)
        if (label=='混沌药箱' or (forge_console_used and label=='造物调试台') or
                (wealth and re.fullmatch(r'游玩[「『“"]([^」』”"]{1,32})[」』”"]',label))):
            prompts.append(token)
    return prompts[0] if len(prompts)==1 and interaction_hint(scene.image,threshold=.85) else None


def field_frame_ready(scene):
    """Entrance fades dim the fixed white HUD too; a night scene does not."""
    if scene.image is None:
        return False
    import numpy as np
    letters=FieldMotionWatch._letters(FieldMotionWatch._header(scene.image))
    return np.count_nonzero(letters)>=60


class BackgroundProgress:
    """Detect a blocked translation using tracked world points, excluding HUD/avatar."""
    def __init__(self, seconds=2.0):
        self.seconds=seconds
        self.reference=None
        self.since=None

    def update(self, image, now):
        import cv2
        import numpy as np
        gray=cv2.cvtColor(cv2.resize(image,(480,270)),cv2.COLOR_BGR2GRAY)
        if self.reference is None:
            self.reference=gray
            self.since=now
            return None
        if now-self.since<self.seconds:
            return None
        mask=np.zeros_like(gray)
        mask[100:230,115:190]=255
        mask[100:230,305:400]=255
        points=cv2.goodFeaturesToTrack(self.reference,160,.03,8,mask=mask)
        result=None
        if points is not None and len(points)>=12:
            difference=cv2.absdiff(self.reference,gray)[mask>0]
            if float(np.percentile(difference,75))<2:
                self.reference=gray
                self.since=now
                return "background_stalled"
            moved,status,error=cv2.calcOpticalFlowPyrLK(self.reference,gray,points,None,
                                                      winSize=(15,15),maxLevel=2)
            if moved is not None:
                back,valid,_=cv2.calcOpticalFlowPyrLK(gray,self.reference,moved,None)
                good=(status.ravel()==1)&(valid.ravel()==1)&(error.ravel()<25)
                good &= np.linalg.norm(back-points,axis=2).ravel()<1.0
                distance=np.linalg.norm(moved-points,axis=2).ravel()[good]
                if len(distance)>=12 and float(np.percentile(distance,65))<1.5:
                    result="background_stalled"
        self.reference=gray
        self.since=now
        return result


def navigation_targets(scene,*,enemies=True):
    from .du_detector import detect,detect_enemies,_usable_enemies
    # A positively identified open-eyed door is the game's cleared-room state.
    # Background ornaments occasionally resemble a trained monster; they must
    # not pull navigation away from the now-available exit.
    awake=random_gate(scene,fast=True) if enemies else None
    enemies=enemies and not (awake is not None and awake.text=='差分宇宙随意门外观')
    learned_enemies=detect_enemies(scene) if enemies else []
    boss=(learned_enemies if learned_enemies is not None else aurumaton_landmark(scene))
    targets=detect(scene)
    if targets is not None:
        targets=[t for t in targets if t.text!='Enemy']+(
            _usable_enemies([t for t in targets if t.text=='Enemy']) if enemies else [])
        if not targets:
            # A distant door can briefly fall below 0.55 during reward/heal
            # effects. Require independent face geometry inside a lower-score
            # learned box, rather than discarding a visible target and turning.
            face=random_gate(scene,fast=True)
            if face is not None and face.text in ('差分宇宙随意门外观','差分宇宙睡眼门'):
                for candidate in detect(scene,.30) or []:
                    x1,y1,x2,y2=candidate.box
                    if (max(0,x1-.02)<=face.box[0] and max(0,y1-.03)<=face.box[1]
                            and face.box[2]<=min(1,x2+.02) and face.box[3]<=min(1,y2+.03)):
                        targets=[candidate]
                        break
        return boss+targets or (enemy_landmark(scene) if enemies else [])
    if boss:
        return boss
    if scene.image is not None:
        import cv2
        image=cv2.resize(scene.image,(960,round(scene.image.shape[0]*960/scene.image.shape[1])))
        panel=_pink_gate(image)
        if panel is not None:
            h,w=image.shape[:2]
            x1,y1,x2,y2=panel
            return [Token("GateLocked",.90,(x1/w,y1/h,x2/w,y2/h))]
        closed=_gate_closed(image)
        if closed is not None:
            h,w=image.shape[:2]
            x1,y1,x2,y2=closed
            return [Token("GateLocked",.92,(x1/w,y1/h,x2/w,y2/h))]
    # Until the optional model is installed, only a positive open-eye landmark
    # can guide travel. A back/closed-eye match never establishes a usable gate.
    gate=random_gate(scene,fast=True)
    if gate is not None:
        return [Token("GateLocked" if gate.text.endswith("背面") else "Target",gate.score,gate.box)]
    return []


@lru_cache(maxsize=1)
def _aurumaton_templates():
    import cv2
    import numpy as np
    return tuple(cv2.imdecode(np.fromfile(str(RESOURCE_ROOT/'assets/templates'/name),np.uint8),cv2.IMREAD_GRAYSCALE)
                 for name in ('du_aurumaton_roof.png','du_aurumaton_side.png'))


def aurumaton_landmark(scene):
    """The observed boss roof supplies a bearing independently of the door."""
    if scene.image is None or not (scene.has('首领',(0,0,.25,.06))
            or scene.has('金人司',(.38,.01,.64,.10))):
        return []
    import cv2
    import numpy as np
    source=scene.image
    image=cv2.resize(source,(960,round(source.shape[0]*960/source.shape[1])))
    h,w=image.shape[:2]
    left,top=round(.15*w),round(.10*h)
    gray=cv2.cvtColor(image[top:round(.70*h),left:round(.85*w)],cv2.COLOR_BGR2GRAY)
    best=None
    for template in _aurumaton_templates():
        for index in range(-5,13):
            factor=1.09**index
            sample=cv2.resize(template,None,fx=factor,fy=factor)
            th,tw=sample.shape
            if th>gray.shape[0] or tw>gray.shape[1]:
                continue
            _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(gray,sample,cv2.TM_CCOEFF_NORMED))
            if score<.84 or (best is not None and score<=best.score):
                continue
            x,y=point[0]+left,point[1]+top
            best=Token('Enemy',float(score),(x/w,y/h,(x+tw)/w,(y+th)/h))
    return [best] if best is not None else []


@lru_cache(maxsize=1)
def _boss_head_template():
    import cv2
    import numpy as np
    path=RESOURCE_ROOT/'assets/templates/du_boss_head.png'
    return cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_GRAYSCALE)


def enemy_landmark(scene):
    """A locally observed boss silhouette supplies a bearing, never range."""
    if scene.image is None:
        return []
    import cv2
    import numpy as np
    image=cv2.resize(scene.image,(960,round(scene.image.shape[0]*960/scene.image.shape[1])))
    h,w=image.shape[:2]
    patch=cv2.cvtColor(image[round(.12*h):round(.75*h),round(.15*w):round(.85*w)],cv2.COLOR_BGR2GRAY)
    template=_boss_head_template()
    best=None
    for index in range(-5,14):
        factor=.5*1.10**index
        anchor=cv2.resize(template,None,fx=factor,fy=factor)
        th,tw=anchor.shape
        if th>patch.shape[0] or tw>patch.shape[1]:
            continue
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(patch,anchor,cv2.TM_CCOEFF_NORMED))
        if score<.80 or (best is not None and score<=best.score):
            continue
        x=point[0]+round(.15*w);y=point[1]+round(.12*h)
        body=image[y:y+th,x:x+tw].astype(np.float32)
        if np.mean((body[:,:,2]>body[:,:,1]*1.3)&(body[:,:,2]>body[:,:,0]*1.1))>.2:
            best=Token('Enemy',score,(x/w,y/h,(x+tw)/w,(y+th)/h))
    if best is not None:
        return [best]
    return []


def event_cards(scene):
    """Find dark rectangular frames around the green/purple world card faces."""
    if scene.image is None:
        return []
    import cv2
    import numpy as np
    source=scene.image
    image=cv2.resize(source,(960,round(source.shape[0]*960/source.shape[1])))
    h,w=image.shape[:2]
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    edges=cv2.Canny(gray,45,130)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    boxes=[]
    for contour in contours:
        polygon=cv2.approxPolyDP(contour,.018*cv2.arcLength(contour,True),True)
        if len(polygon)!=4 or not cv2.isContourConvex(polygon):
            continue
        x,y,cw,ch=cv2.boundingRect(polygon)
        if (45<ch<.86*h and 22<cw and .38<cw/ch<.9 and .18*w<x+cw/2<.82*w
                and .12*h<y+ch/2<.70*h and cv2.contourArea(polygon)>.85*cw*ch):
            boxes.append((x,y,cw,ch))
    candidates=[]
    crest=card_crest(image)
    if crest is not None:
        candidates.append(crest)
    for x,y,cw,ch in boxes:
        hsv=cv2.cvtColor(image[y:y+ch,x:x+cw],cv2.COLOR_BGR2HSV)
        # The ornate frame has dark vertical rails and a saturated inner face.
        rail=max(2,round(cw*.07))
        dark=lambda a:float(np.mean(a<135))
        face=(hsv[:,:,0]>=40)&(hsv[:,:,0]<=170)
        face &= (hsv[:,:,1]>65)&(hsv[:,:,2]>40)
        if (dark(hsv[:,:rail,2])<.30 or dark(hsv[:,-rail:,2])<.30
                or dark(hsv[:rail,:,2])<.30 or float(np.mean(face))<.30):
            continue
        candidates.append(Token('Card',.9,(x/w,y/h,(x+cw)/w,(y+ch)/h)))
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    # A centered card can lose a frame corner behind the avatar. Its purple
    # face, pale swirl and remaining dark rails still establish a bearing.
    # Pale artwork and multiple dark rails exclude a flat pink locked panel.
    purple=((hsv[:,:,0]>=122)&(hsv[:,:,0]<=165)&(hsv[:,:,1]>65)&(hsv[:,:,2]>55)).astype(np.uint8)*255
    purple[:round(.12*h)]=0
    purple[round(.72*h):]=0
    purple[:,:round(.24*w)]=0
    purple[:,round(.84*w):]=0
    purple=cv2.morphologyEx(purple,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    for x,y,cw,ch,area in cv2.connectedComponentsWithStats(purple)[2][1:]:
        if not (45<ch<.65*h and 22<cw<.25*w and .38<cw/ch<1.0 and area>.45*cw*ch):
            continue
        face=hsv[y:y+ch,x:x+cw]
        pale=np.mean((face[:,:,1]<80)&(face[:,:,2]>185))
        rails=(hsv[y:y+ch,max(0,x-4):x+2,2],hsv[y:y+ch,x+cw-2:x+cw+4,2],
               hsv[max(0,y-5):y+2,x:x+cw,2])
        if pale>.025 and sum(float(np.mean(rail<135))>.38 for rail in rails)>=2:
            candidates.append(Token('Card',.87,(x/w,y/h,(x+cw)/w,(y+ch)/h)))
    # Abnormal-event cards have a bright cyan frame rather than dark rails.
    # Require the cyan face plus its purple ornament and pale eye, which
    # distinguishes this card from the room's ordinary blue banners.
    cyan=((hsv[:,:,0]>=85)&(hsv[:,:,0]<=103)&(hsv[:,:,1]>95)&(hsv[:,:,2]>110)).astype(np.uint8)*255
    cyan[:round(.12*h)]=0;cyan[round(.72*h):]=0
    cyan[:,:round(.22*w)]=0;cyan[:,round(.84*w):]=0
    cyan=cv2.morphologyEx(cyan,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    for x,y,cw,ch,area in cv2.connectedComponentsWithStats(cyan)[2][1:]:
        if not (45<ch<.65*h and 22<cw<.25*w and .25<cw/ch<.85 and area>.35*cw*ch):
            continue
        face=hsv[y:y+ch,x:x+cw]
        pale=np.mean((face[:,:,1]<80)&(face[:,:,2]>185))
        ornament=np.mean((face[:,:,0]>=122)&(face[:,:,0]<=165)&(face[:,:,1]>60)&(face[:,:,2]>65))
        rails=(hsv[y:y+ch,max(0,x-4):x+2,2],hsv[y:y+ch,x+cw-2:x+cw+4,2],hsv[max(0,y-5):y+2,x:x+cw,2])
        if pale>.025 and ornament>.03 and any(float(np.mean(rail<135))>.40 for rail in rails):
            candidates.append(Token('Card',.89,(x/w,y/h,(x+cw)/w,(y+ch)/h)))
    gold=((hsv[:,:,0]>=15)&(hsv[:,:,0]<=42)&(hsv[:,:,1]>80)&(hsv[:,:,2]>80)).astype(np.uint8)*255
    gold[:round(.12*h)]=0;gold[round(.72*h):]=0
    gold[:,:round(.22*w)]=0;gold[:,round(.84*w):]=0
    gold=cv2.morphologyEx(gold,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    for x,y,cw,ch,area in cv2.connectedComponentsWithStats(gold)[2][1:]:
        if not (45<ch<.65*h and 22<cw<.25*w and .40<cw/ch<1.0 and .40<area/(cw*ch)<.85):
            continue
        face=hsv[y:y+ch,x:x+cw]
        pale=np.mean((face[:,:,1]<80)&(face[:,:,2]>185))
        if pale>.06 and np.mean(face[:,:,2]<125)>.20:
            candidates.append(Token('Card',.88,(x/w,y/h,(x+cw)/w,(y+ch)/h)))
    dark=(hsv[:,:,2]<85).astype(np.uint8)*255
    dark[:,round(.865*w):]=0
    dark=cv2.morphologyEx(dark,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    count,_,stats,_=cv2.connectedComponentsWithStats(dark)
    for x,y,cw,ch,area in stats[1:]:
        if not (70<ch<.85*h and 25<cw<.25*w and .45<cw/ch<1.1 and area>.88*cw*ch
                and .20*w<x+cw/2<.92*w and .20*h<y+ch/2<.7*h):
            continue
        candidates.append(Token('Card',.88,(x/w,y/h,(x+cw)/w,(y+ch)/h)))
    result=[]
    for candidate in sorted(candidates,key=lambda t:(t.box[2]-t.box[0])*(t.box[3]-t.box[1]),reverse=True):
        if all(abs(candidate.center[0]-other.center[0])>.035 for other in result):
            result.append(candidate)
    return result


@lru_cache(maxsize=1)
def _card_crest_template():
    import cv2
    import numpy as np
    path=RESOURCE_ROOT/'assets/templates/du_card_crest.png'
    return cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_GRAYSCALE)


def card_crest(image):
    import cv2
    import numpy as np
    h,w=image.shape[:2]
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    template=_card_crest_template()
    patch=gray[round(.04*h):round(.65*h),round(.22*w):round(.87*w)]
    best=None
    for index in range(-10,17):
        factor=.5*1.08**index
        sample=cv2.resize(template,None,fx=factor,fy=factor)
        th,tw=sample.shape
        if th<7 or tw<8 or th>patch.shape[0] or tw>patch.shape[1]:
            continue
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(patch,sample,cv2.TM_CCOEFF_NORMED))
        if score<.78 or (best is not None and score<=best.score):
            continue
        x=point[0]+round(.22*w)+tw/2;y=point[1]+round(.04*h)+th*.7
        x1,x2=max(0,round(x-1.4*tw)),min(w,round(x+1.4*tw))
        y1,y2=max(0,round(y)),min(h,round(y+4*tw))
        body=gray[y1:y2,x1:x2]
        if body.size and np.mean(body<135)>.5:
            best=Token('Card',score,(x1/w,y1/h,x2/w,y2/h))
    return best


def event_targets(scene):
    from .du_detector import detect_cards
    learned=detect_cards(scene)
    if learned is None and scene.image is not None:
        from .models import AutomationError
        raise AutomationError('缺少场景卡牌模型 assets/models/du_cards.onnx，停止卡牌导航。')
    # A reviewed world-card title provides a coarse bearing when that card's
    # artwork is outside the learned appearances. It never authorizes F.
    from .policy import has_du_field_plane_marker
    header=''.join(t.text for t in scene.tokens if t.within((0,0,.32,.065)))
    if not has_du_field_plane_marker(header):
        return learned or []
    title=scene.find(('商店街一番战','维护市容（区域）'),(.20,.07,.80,.55),exact=True)
    if title is None:
        # Region cards can be almost edge-on while their floating caption is
        # still readable. Parenthesised world-card qualifiers supply a coarse
        # bearing, not permission to interact. HUD labels and ordinary prose
        # lack this caption form or lie outside the world-title area.
        import re
        candidates=[token for token in scene.tokens if token.within((.24,.07,.80,.55))
                    and re.fullmatch(r'[\u3400-\u9fff·]{2,16}[（(][\u3400-\u9fff]{1,8}[）)]',
                                     re.sub(r'\s+','',token.text))]
        title=min(candidates,key=lambda token:abs(token.center[0]-.5),default=None)
    if title is None and learned:
        return learned
    if title is None and scene.image is not None:
        # A bare floating name can corroborate a weak edge-on card box. Keep
        # the normal detector threshold and require both sources to agree;
        # ordinary HUD text or a caption without a learned body is no target.
        import re
        captions=[t for t in scene.tokens if t.score>=.90 and t.within((.24,.07,.80,.46))
                  and .012<=t.box[3]-t.box[1]<=.055
                  and re.fullmatch(r'[\u3400-\u9fff·]{2,20}',re.sub(r'\s+','',t.text))]
        if captions:
            for body in detect_cards(scene,.30) or []:
                if body.box[3]-body.box[1]<.12:
                    continue
                matched=[t for t in captions if body.box[0]-.03<=t.center[0]<=body.box[2]+.03
                         and -.02<=body.box[1]-t.box[3]<=.14]
                if matched:
                    title=min(matched,key=lambda t:abs(t.center[0]-body.center[0]))
                    break
    if title is None:
        title=scene.find('造物调试台',(.20,.07,.80,.55),exact=True)
    if title is None:
        return []
    x,y=title.center
    return [Token('Device' if normalize(title.text)=='造物调试台' else 'Card',.86,(max(.02,x-.04),min(.85,y+.04),
                             min(.98,x+.04),min(.90,y+.16)))]


@lru_cache(maxsize=1)
def _interaction_hint_template():
    import cv2
    import numpy as np
    path=RESOURCE_ROOT/'assets/templates/du_interaction_f.png'
    return cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_GRAYSCALE)


def interaction_hint(image,*,threshold=.90):
    """A cheap stop signal; the caller must subsequently OCR the interaction."""
    import cv2
    h,w=image.shape[:2]
    sample=cv2.resize(image,(960,round(h*960/w)))
    patch=cv2.cvtColor(sample[round(.45*sample.shape[0]):round(.66*sample.shape[0]),
                                     round(.52*960):round(.62*960)],cv2.COLOR_BGR2GRAY)
    template=cv2.resize(_interaction_hint_template(),None,fx=.5,fy=.5)
    _,score,_,_=cv2.minMaxLoc(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED))
    return score>=threshold


def _pink_gate(image):
    """A pink upright panel with long gold trim supplies the initial heading."""
    import cv2
    import numpy as np
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    pink=((hsv[:,:,0]>=135)&(hsv[:,:,0]<=179)&(hsv[:,:,1]>45)&(hsv[:,:,2]>95)).astype(np.uint8)*255
    pink=cv2.morphologyEx(pink,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    n,_,stats,_=cv2.connectedComponentsWithStats(pink)
    candidates=[]
    for x,y,w,h,area in stats[1:]:
        if not (35<=h<image.shape[0]*.9 and 12<=w and .2<w/h<1.15 and area>.35*w*h
                and .08*image.shape[0]<y+h/2<.75*image.shape[0] and .05*image.shape[1]<x+w/2<.92*image.shape[1]):
            continue
        pad=max(3,w//12)
        region=hsv[max(0,y-pad):min(hsv.shape[0],y+h+pad),max(0,x-pad):min(hsv.shape[1],x+w+pad)]
        gold=((region[:,:,0]>=15)&(region[:,:,0]<=45)&(region[:,:,1]>70)&(region[:,:,2]>120)).astype(np.uint8)*255
        gold=cv2.morphologyEx(gold,cv2.MORPH_CLOSE,np.ones((5,3),np.uint8))
        count,_,bars,_=cv2.connectedComponentsWithStats(gold)
        if (np.count_nonzero(gold,axis=0).max()>max(16,.30*h)
                or any(bh>.35*h and bh>3*bw for bx,by,bw,bh,ba in bars[1:])):
            candidates.append((w*h,(int(x),int(y),int(x+w),int(y+h))))
    return max(candidates,default=(0,None))[1]


def _gate_closed(image):
    """Two pink eyes split by dark horizontal lids on a sleeping gate."""
    import cv2
    import numpy as np
    hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
    dark=(hsv[:,:,2]<100).astype(np.uint8)*255
    contours,hierarchy=cv2.findContours(dark,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return None
    eyes=[]
    for i,c in enumerate(contours):
        child=hierarchy[0][i][2]
        if child<0:
            continue
        x,y,w,h=cv2.boundingRect(c)
        if not (6<=h<=150 and .65<w/h<1.45 and .08*image.shape[0]<y<.7*image.shape[0]):
            continue
        children=0
        while child>=0:
            children+=1;child=hierarchy[0][child][0]
        patch=hsv[y:y+h,x:x+w]
        pink=(patch[:,:,0]>=130)&(patch[:,:,0]<=179)&(patch[:,:,1]>40)&(patch[:,:,2]>110)
        if children>=2 and np.mean(pink)>.30:
            eyes.append((x,y,w,h))
    for x,y,w,h in eyes:
        for xx,yy,ww,hh in eyes:
            if not (1.4<(xx+ww/2-x-w/2)/max(w,ww)<4.5
                    and .6<h/hh<1.6 and abs(y+h/2-yy-hh/2)<max(h,hh)*.4):
                continue
            middle=hsv[min(y,yy):max(y+h,yy+hh),x+w:xx]
            if middle.size and np.mean((middle[:,:,0]>=15)&(middle[:,:,0]<=45)&(middle[:,:,1]>70))>.015:
                return max(0,x-w//2),max(0,y-h//2),min(image.shape[1],xx+ww+ww//2),min(image.shape[0],yy+hh+hh//2)
    return None


@lru_cache(maxsize=1)
def _range_ring_template():
    import cv2,numpy as np
    return cv2.imdecode(np.fromfile(RESOURCE_ROOT/'assets/templates/du_range_ring.png',np.uint8),0)


@lru_cache(maxsize=1)
def _range_ring_shape_reference():
    import numpy as np
    template=_range_ring_template().astype(np.float32)
    yy,xx=np.ogrid[:41,:41]
    radius=(xx-20)**2+(yy-20)**2
    mask=(radius>=10**2)&(radius<20**2)
    reference=template[mask]
    reference=reference-reference.mean()
    return mask,reference,float(np.linalg.norm(reference))


def _range_ring_shape(excess,x,y,radius):
    """Compare the stable outer UI ring, excluding the pulsing inner fill."""
    import cv2,numpy as np
    mask,reference,norm=_range_ring_shape_reference()
    best=-1.0
    for factor in (1.1,1.2,1.3,1.4,1.5,1.6):
        span=round(2*radius*factor)
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                patch=cv2.getRectSubPix(excess,(span,span),(float(x+dx),float(y+dy)))
                values=cv2.resize(patch,(41,41)).astype(np.float32)[mask]
                values-=values.mean()
                score=float(np.dot(values,reference)/max(1e-6,np.linalg.norm(values)*norm))
                best=max(best,score)
    return best


def attack_reticle(scene):
    """The red/orange attack-range ring, distinct from an enemy's purple eye."""
    if scene.image is None:
        return None
    import cv2
    import numpy as np
    image=cv2.resize(scene.image,(960,round(scene.image.shape[0]*960/scene.image.shape[1])))
    h,w=image.shape[:2]
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    b,g,red=image.astype(np.int16).transpose(2,0,1)
    excess=np.clip((red-np.maximum(b,g))*2,0,255).astype(np.uint8)
    def candidates():
        # Motion/idle changes can weaken a real ring's edge votes even while
        # its red arc and bright core remain intact. Try the weaker edge pass
        # only if the ordinary candidates fail the same appearance checks.
        for votes in (25,20):
            circles=cv2.HoughCircles(gray,cv2.HOUGH_GRADIENT,1,20,param1=120,param2=votes,minRadius=10,maxRadius=24)
            if circles is not None:
                for x,y,r in circles[0]:
                    yield x,y,r,votes==20,False
        # Bright monster eyes can dominate the grayscale circle detector.
        # Red excess isolates the smaller warm interaction glow instead.
        circles=cv2.HoughCircles(excess,cv2.HOUGH_GRADIENT,1,12,param1=80,param2=16,minRadius=10,maxRadius=24)
        if circles is not None:
            for x,y,r in circles[0]:
                yield x,y,r,False,True
    angles=np.linspace(0,2*np.pi,96,endpoint=False)
    for x,y,r,weak_edge,red_edge in candidates():
        # A large close enemy can put its genuine range ring near the left
        # edge after switching party members. The glow/core tests still apply.
        if not (.025*w<x<.965*w and .15*h<y<.73*h):
            continue
        best=0
        for radius in (r-2,r-1,r,r+1,r+2):
            xx=np.clip(np.rint(x+radius*np.cos(angles)).astype(int),0,w-1)
            yy=np.clip(np.rint(y+radius*np.sin(angles)).astype(int),0,h-1)
            b,g,red=image[yy,xx].astype(np.int16).T
            bright=(red>190)&(g>90)&(red-g>50)&(red-b>35)
            strong=bright&(red-g>80)&(g-b<65)&(red-b>60)
            # Blonde hair and yellow shop digits also contain circular edges.
            # The attack glow must include a substantial warm-red arc, not
            # merely a yellow/orange boundary around a Hough circle.
            if float(np.mean(strong))>=.28:
                best=max(best,float(np.mean(bright)))
        yy,xx=np.ogrid[:h,:w]
        inside=(xx-x)**2+(yy-y)**2<(.75*r)**2
        b,g,red=image[inside].astype(np.int16).T
        yellow=np.mean((red>200)&(g>155)&(b<160))
        dark=np.mean(np.maximum.reduce([b,g,red])<100)
        glow=np.mean((red>210)&(red-g>60)&(red-b>20))
        core=(xx-x)**2+(yy-y)**2<(.5*r)**2
        hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)[core]
        hot=np.mean((hsv[:,1]<85)&(hsv[:,2]>220))
        # A printed white numeral inside an orange balloon can mimic the
        # outer circle. Real markers retain a small core under the red tint.
        if hot>=.35:
            continue
        # The inner fill pulses. A dimmer fill still needs a stronger red arc
        # and a distinct bright core; hair, trim and shop digits lack that mix.
        filled=glow>.55 and hot>.01
        pulsing=glow>.25 and hot>.04 and best>.60
        if weak_edge and not (best>.65 and glow>.65 and hot>.10):
            continue
        # Warning artwork can put white lettering inside a red circle. The
        # real range marker has a small bright core, not a broad white centre.
        if red_edge and (best<.50 or not filled or hot>=.20):
            continue
        if (best>=.42 and yellow<.35 and dark<.65 and (filled or pulsing)
                and _range_ring_shape(excess,x,y,r)>=.58):
            return Token("差分宇宙已锁定敌方目标",best,
                         tuple(float(v) for v in ((x-r)/w,(y-r)/h,(x+r)/w,(y+r)/h)))
    # Some monsters show a dim hollow marker rather than a bright filled
    # centre. Match its complete UI shape (notches, outer and inner rings)
    # in red excess, without relaxing the general circle/colour checks.
    left,top=round(.025*w),round(.15*h)
    template=_range_ring_template()
    patch=excess[top:round(.73*h),left:round(.965*w)]
    th,tw=template.shape
    if patch.shape[0]>=th and patch.shape[1]>=tw:
        _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED))
        if np.isfinite(score) and score>=.82:
            x=left+point[0]+tw/2;y=top+point[1]+th/2;r=16
            return Token('差分宇宙已锁定敌方目标',float(score),
                         ((x-r)/w,(y-r)/h,(x+r)/w,(y+r)/h))
    return None


def verified_attack_reticle(scene):
    """Require the game's enemy information bar as well as the warm ring."""
    if not scene.has('等级',(.38,.01,.64,.10)):
        return None
    return attack_reticle(scene)


@lru_cache(maxsize=1)
def _difficulty_template():
    import cv2
    import numpy as np
    path=RESOURCE_ROOT / "assets/templates/du_difficulty_i_idle.png"
    return cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_GRAYSCALE)


@lru_cache(maxsize=1)
def _event_next_template():
    import cv2
    import numpy as np
    path=RESOURCE_ROOT / "assets/templates/du_event_next.png"
    return cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_GRAYSCALE)


def event_next(scene):
    """Match the arrow's top/left arc, excluding the game cursor on its center."""
    if scene.image is None:
        return None
    import cv2
    import numpy as np
    image=scene.image;h,w=image.shape[:2]
    left,top,right,bottom=round(.75*w),round(.55*h),round(.90*w),round(.84*h)
    patch=cv2.cvtColor(image[top:bottom,left:right],cv2.COLOR_BGR2GRAY)
    template=_event_next_template()
    y,x=np.ogrid[:35,:35]
    mask=(((x-17)**2+(y-17)**2<17**2)&((x<15)|(y<15))).astype(np.uint8)*255
    template=cv2.resize(template,None,fx=w/1920,fy=w/1920)
    mask=cv2.resize(mask,(template.shape[1],template.shape[0]),interpolation=cv2.INTER_NEAREST)
    scores=cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED,mask=mask)
    scores=np.nan_to_num(scores,nan=-1,posinf=-1,neginf=-1)
    _,score,_,point=cv2.minMaxLoc(scores)
    if score<.90:
        return None
    px,py=point;th,tw=template.shape[:2]
    return (left+px+tw/2)/w,(top+py+th/2)/h,float(score)


def lowest_difficulty(scene):
    """Find I's glyph inside its observed slot, excluding the moving backdrop."""
    if scene.image is None:
        return None
    import cv2
    image=scene.image
    h,w=image.shape[:2]
    x1,y1,x2,y2=round(.04*w),round(.125*h),round(.09*w),round(.205*h)
    patch=cv2.cvtColor(image[y1:y2,x1:x2],cv2.COLOR_BGR2GRAY)
    template=cv2.resize(_difficulty_template(),None,fx=w/1920,fy=w/1920)
    th,tw=template.shape[:2]
    if th>patch.shape[0] or tw>patch.shape[1]:
        return None
    _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED))
    if score<.90:
        return None
    x,y=point
    return (x1+x+tw/2)/w,(y1+y+th/2)/h,score


class FieldMotionWatch:
    """Stop continuous travel using fresh pixels; full OCR follows key release."""
    def __init__(self, scene, vision, *, profile="forward", watch_gate=True):
        import cv2
        self.vision=vision
        self.profile=profile
        self.watch_gate=watch_gate
        self.missing_gate=0
        self.header=self._header(scene.image)
        self.header_letters=self._letters(self.header)
        self.progress=BackgroundProgress() if profile in ("forward","enemy","target","exit","engage","anomaly","occluded_card") else None
        import time
        self.started_at=time.monotonic()
        self.attack_target=None
        self.attack_frame=None
        self.gate_target=None
        self.gate_frame=None
        self.label_approach=profile=='anomaly' and any(t.score==.86 for t in event_targets(scene))
        targets=(event_targets(scene) or navigation_targets(scene,enemies=False)) if profile=="anomaly" else navigation_targets(scene,enemies=False) if profile in ("target","exit") else []
        self.started_near=any(t.box[3]-t.box[1]>.5 for t in targets)

    @staticmethod
    def _header(image):
        import cv2
        h,w=image.shape[:2]
        return cv2.resize(image[round(.008*h):round(.040*h),round(.012*w):round(.19*w)],(340,36))

    @staticmethod
    def _letters(header):
        import cv2
        import numpy as np
        hsv=cv2.cvtColor(header,cv2.COLOR_BGR2HSV)
        gray=cv2.cvtColor(header,cv2.COLOR_BGR2GRAY)
        strokes=cv2.morphologyEx(gray,cv2.MORPH_TOPHAT,np.ones((5,5),np.uint8))
        return (hsv[:,:,1]<50)&(hsv[:,:,2]>175)&(strokes>25)

    def _attack_range(self, page):
        # Cartoon companions can contain the same red arc and white core.
        # Only OCR the small enemy bar when a visual candidate appears.
        target=attack_reticle(page)
        if target is None:
            return False
        import re
        h,w=page.image.shape[:2]
        bar=self.vision.read(page.image[round(.01*h):round(.10*h),round(.38*w):round(.64*w)])
        confirmed=any(re.search(r'等级\d{1,3}',normalize(t.text)) for t in bar.tokens)
        if confirmed:
            self.attack_target=target
            self.attack_frame=page.image
        return confirmed

    def __call__(self, image):
        import cv2
        import numpy as np
        letters=self._letters(self._header(image))
        letters=cv2.dilate(letters.astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
        retained=np.count_nonzero(letters & self.header_letters)/max(1,np.count_nonzero(self.header_letters))
        # Compare the fixed white HUD lettering, excluding the changing 3-D
        # background. Raw grayscale correlation stops on ordinary camera turns.
        if retained<.65:
            return "field_hud_changed"
        if self.progress is not None:
            import time
            stalled=self.progress.update(image,time.monotonic())
            if stalled:
                return stalled
        page=Scene([],image=image)
        if self.profile=='occluded_card':
            from .du_detector import forward_barrier
            if interaction_hint(image):
                return 'interaction_hint'
            barrier=forward_barrier(image)
            if barrier is not None and abs(barrier.center[0]-.5)<.15:
                return 'forward_barrier'
            return None
        if self.profile=='seek_attack':
            from .du_detector import detect_enemies,detect_recovery_enemies
            if detect_enemies(page) or detect_recovery_enemies(page):
                return 'enemy_landmark'
        if self.profile in ("engage","seek_attack"):
            if self._attack_range(page):
                return "attack_reticle"
            if interaction_hint(image):
                return 'interaction_hint'
            return None
        if self.profile in ("target","exit","anomaly"):
            from .du_detector import forward_barrier
            if interaction_hint(image):
                return "interaction_hint"
            if self.profile=='target' and self._attack_range(page):
                return 'attack_reticle'
            targets=(event_targets(page) or navigation_targets(page,enemies=False)) if self.profile=="anomaly" else navigation_targets(page,enemies=False)
            active=[t for t in targets if t.text in ("Enemy","Target","GateLocked","Card")]
            if not active:
                if self.label_approach:
                    import time
                    if time.monotonic()-self.started_at<.4:
                        return None
                return "target_lost"
            goal=min(active,key=lambda t:({"Enemy":0,"Card":0,"GateLocked":1,"Target":2}[t.text],abs(t.center[0]-.5)))
            barrier=forward_barrier(image)
            if goal.text=="Target" and barrier is not None and abs(barrier.center[0]-goal.center[0])<.12:
                return "forward_barrier"
            if abs(goal.center[0]-.5)>(.04 if self.profile=='exit' else .10):
                return "target_alignment"
            if not self.started_near and goal.box[3]-goal.box[1]>.5:
                return "target_near"
            # Full/region OCR can take longer than the remaining travel time
            # near a card. Keep this held-input loop purely visual; after it
            # stops for size/alignment/loss, the caller reads the live F label.
            return None
        gate=random_gate(page,fast=True) if self.watch_gate and self.profile in ("gate","seek","seek_gate") else None
        if self.profile=="forward":
            from .du_detector import forward_barrier
            if interaction_hint(image):
                return 'interaction_hint'
            if forward_barrier(image) is not None:
                return 'forward_barrier'
            h,w=image.shape[:2]
            prompt=self.vision.read(image[round(.30*h):round(.76*h),round(.47*w):round(.79*w)])
            if any(normalize(t.text) in ("事件","随意门","卡牌","调查","交互") for t in prompt.tokens):
                return "interaction_prompt"
            enemy=self.vision.read(image[:round(.10*h),round(.38*w):round(.64*w)])
            import re
            if any(re.search(r"等级\d{1,3}[\u3400-\u9fff]",normalize(t.text)) for t in enemy.tokens):
                return "enemy_label"
        if self.profile=="gate":
            h,w=image.shape[:2]
            prompt=self.vision.read(image[round(.30*h):round(.76*h),round(.47*w):round(.79*w)])
            if any("随意门" in normalize(t.text) for t in prompt.tokens):
                return "gate_prompt"
            if gate is None:
                self.missing_gate+=1
                if self.missing_gate>=2:
                    return "gate_occluded"
            else:
                self.missing_gate=0
                if abs(gate.center[0]-.5)>.06:
                    return "gate_alignment"
        elif self.profile in ("seek","seek_gate"):
            targets=navigation_targets(page,enemies=False)
            if gate is not None or targets:
                self.gate_target=next((t for t in targets if t.text in ('Target','GateLocked')),gate)
                self.gate_frame=image
                return "gate_landmark"
            if self.profile=='seek_gate':
                return None
            h,w=image.shape[:2]
            enemy=self.vision.read(image[:round(.10*h),round(.38*w):round(.64*w)])
            import re
            if any(re.search(r"等级\d{1,3}[\u3400-\u9fff]",normalize(t.text)) for t in enemy.tokens):
                return "enemy_label"
        return None


@lru_cache(maxsize=1)
def _gate_template():
    import cv2
    import numpy as np
    path=RESOURCE_ROOT / "assets/templates/du_random_gate.png"
    return cv2.imdecode(np.fromfile(str(path),np.uint8),1)


def random_gate(scene, *, fast=False):
    """Locate the observed pink door face at varying distances; never interact."""
    if scene.image is None:
        return None
    import cv2
    import numpy as np
    image=scene.image
    h,w=image.shape[:2]
    sample=cv2.resize(image,(960,round(h*960/w)))
    sh,sw=sample.shape[:2]
    left,top,right,bottom=round(.08*sw),round(.07*sh),round(.90*sw),round(.78*sh)
    patch=sample[top:bottom,left:right]
    eyes=_gate_eyes(patch)
    if eyes is not None:
        x1,y1,x2,y2=eyes
        return Token("差分宇宙随意门外观",.95,
                     ((left+x1)/sw,(top+y1)/sh,(left+x2)/sw,(top+y2)/sh))
    closed=_gate_closed(patch)
    if closed is not None:
        x1,y1,x2,y2=closed
        return Token('差分宇宙睡眼门',.94,
                     ((left+x1)/sw,(top+y1)/sh,(left+x2)/sw,(top+y2)/sh))
    if w>960:
        closed_native=_gate_closed(image)
        if closed_native is not None:
            x1,y1,x2,y2=closed_native
            return Token('差分宇宙睡眼门',.94,(x1/w,y1/h,x2/w,y2/h))
    partial=_learned_gate_eye(scene,sample)
    if partial is not None:
        return partial
    back=_gate_back(patch)
    if back is not None:
        x1,y1,x2,y2=back
        return Token("差分宇宙随意门背面",.94,
                     ((left+x1)/sw,(top+y1)/sh,(left+x2)/sw,(top+y2)/sh))
    if fast:
        return None
    gray=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
    template=_gate_template()
    template=cv2.cvtColor(template,cv2.COLOR_BGR2GRAY)
    best=None
    # Door eyes and trim are narrow. Coarse 20% scale gaps miss the same door
    # after a small change in distance; use a geometric 7% search instead.
    for scale,aspect in ((1.07**i,aspect) for aspect in (1.,.8,1.2) for i in range(-12,25)):
        anchor=cv2.resize(template,None,fx=scale*aspect/2,fy=scale/2)
        ah,aw=anchor.shape[:2]
        if ah>patch.shape[0] or aw>patch.shape[1]:
            continue
        scores=cv2.matchTemplate(gray,anchor,cv2.TM_CCOEFF_NORMED)
        _,score,_,point=cv2.minMaxLoc(scores)
        if score<.78 or (best is not None and score<=best.score):
            continue
        x,y=point
        hsv=cv2.cvtColor(patch[y:y+ah,x:x+aw],cv2.COLOR_BGR2HSV)
        pink=(hsv[:,:,0]>=135)&(hsv[:,:,0]<=179)&(hsv[:,:,1]>40)&(hsv[:,:,2]>100)
        if np.mean(pink)<.20:
            continue
        best=Token("差分宇宙随意门外观",score,
                   ((x+left)/sw,(y+top)/sh,(x+left+aw)/sw,(y+top+ah)/sh))
    return best


def _learned_gate_eye(scene,image):
    """A clipped/angled face needs one complete eye inside a learned door."""
    from .du_detector import detect
    import cv2
    import numpy as np
    ih,iw=image.shape[:2]
    for door in detect(scene) or []:
        x1,y1,x2,y2=door.box
        left,top=max(0,round(x1*iw)),max(0,round(y1*ih))
        right,bottom=min(iw,round(x2*iw)),min(ih,round(y2*ih))
        crop=image[top:bottom,left:right]
        if not crop.size:
            continue
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        pink=(hsv[:,:,0]>=130)&(hsv[:,:,0]<=179)&(hsv[:,:,1]>40)&(hsv[:,:,2]>80)
        if np.mean(pink)<.20:
            continue
        white=((hsv[:,:,1]<65)&(hsv[:,:,2]>185)).astype(np.uint8)*255
        contours,hierarchy=cv2.findContours(white,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is None:
            continue
        gold=((hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>80)&(hsv[:,:,2]>130)).astype(np.uint8)*255
        rails,_=cv2.findContours(gold,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for i,contour in enumerate(contours):
            child=hierarchy[0][i][2]
            if child<0:
                continue
            x,y,ew,eh=cv2.boundingRect(contour)
            area=cv2.contourArea(contour)
            inner=cv2.contourArea(contours[child])
            if not (6<=eh<=150 and 4<=ew<=120 and .35<ew/eh<1.5
                    and area>.4*ew*eh and .15<inner/max(1,area)<.90
                    and .20<(y+eh/2)/crop.shape[0]<.65):
                continue
            pupil=np.zeros(white.shape,np.uint8)
            cv2.drawContours(pupil,contours,child,255,-1)
            if np.mean(hsv[:,:,2][pupil>0]<110)<.60:
                continue
            for rail in rails:
                rx,ry,rw,rh=cv2.boundingRect(rail)
                if (rh>=2.5*eh and .015<rw/rh<.35 and ry<y and ry+rh>y+eh
                        and abs(rx+rw/2-x-ew/2)<3*ew):
                    return Token('差分宇宙随意门外观',.93,door.box)
    return None


def _gate_eyes(patch):
    """White eye rings with dark pupils, pink face and a gold central slit."""
    import cv2
    import numpy as np
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    white=((hsv[:,:,1]<65)&(hsv[:,:,2]>185)).astype(np.uint8)*255
    contours,hierarchy=cv2.findContours(white,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return None
    rings=[]
    for i,c in enumerate(contours):
        child=hierarchy[0][i][2]
        if child<0:
            continue
        x,y,w,h=cv2.boundingRect(c)
        area=cv2.contourArea(c)
        inner=cv2.contourArea(contours[child])
        if (6<=h<=150 and 4<=w<=120 and .35<w/h<1.5
                and area>.4*w*h and .15<inner/max(1,area)<.90):
            rings.append((x,y,w,h))
    for first in rings:
        for second in rings:
            x,y,w,h=first;xx,yy,ww,hh=second
            gap=(xx+ww/2)-(x+w/2)
            if not (1.3<gap/max(w,ww)<4.5 and .5<h/hh<2
                    and abs(y+h/2-yy-hh/2)<max(h,hh)*.45):
                continue
            x1=max(0,x-w//2);x2=min(patch.shape[1],xx+ww+ww//2)
            y1=max(0,min(y,yy)-max(h,hh)//2)
            y2=min(patch.shape[0],max(y+h,yy+hh)+max(h,hh)//2)
            face=hsv[y1:y2,x1:x2]
            pink=(face[:,:,0]>=130)&(face[:,:,0]<=179)&(face[:,:,1]>40)&(face[:,:,2]>80)
            middle=hsv[y1:y2,x+w:xx]
            if not middle.size:
                continue
            gold=(middle[:,:,0]>=15)&(middle[:,:,0]<=40)&(middle[:,:,1]>80)&(middle[:,:,2]>130)
            dark=middle[:,:,2]<110
            if np.mean(pink)>.20 and np.mean(gold)>.025 and np.mean(dark)>.20:
                return x1,y1,x2,y2
    return None


def _gate_back(patch):
    import cv2
    import numpy as np
    hsv=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
    gold=((hsv[:,:,0]>=15)&(hsv[:,:,0]<=50)&(hsv[:,:,1]>60)&(hsv[:,:,2]>110)).astype(np.uint8)*255
    gold=cv2.morphologyEx(gold,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,hierarchy=cv2.findContours(gold,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return None
    for i,c in enumerate(contours):
        x,y,w,h=cv2.boundingRect(c)
        if not (25<=h<=patch.shape[0] and .08<w/h<.35 and x-2*w>=0 and x+3*w<patch.shape[1]):
            continue
        inside=hsv[y+max(1,h//20):y+h-max(1,h//20),x+max(1,w//5):x+w-max(1,w//5)]
        if not inside.size or np.mean(inside[:,:,2]<120)<.5:
            continue
        valid=True
        for left,right in ((x-w,x),(x+w,x+2*w)):
            side=hsv[y+h//3:y+2*h//3,left:right]
            pink=(side[:,:,0]>=130)&(side[:,:,0]<=179)&(side[:,:,1]>40)&(side[:,:,2]>80)
            white=(side[:,:,1]<65)&(side[:,:,2]>185)
            if np.mean(pink)<.5 or np.mean(white)>.05 or np.mean(side[:,:,2]<100)>.15:
                valid=False
                break
        if valid:
            return x-2*w,y,x+3*w,y+h
    return None


@lru_cache(maxsize=1)
def _auto_template():
    import cv2
    import numpy as np
    path=RESOURCE_ROOT / "assets/templates/du_auto_anchor.png"
    return cv2.imdecode(np.fromfile(str(path),np.uint8),cv2.IMREAD_GRAYSCALE)


def auto_state(scene):
    """Read the calibrated DU auto glyph and its gold/white state."""
    if scene.image is None:
        return None,None
    import cv2
    import numpy as np
    image=scene.image
    h,w=image.shape[:2]
    x1,y1,x2,y2=round(.88*w),0,round(.95*w),round(.10*h)
    patch=image[y1:y2,x1:x2]
    template=cv2.resize(_auto_template(),None,fx=w/1920,fy=w/1920)
    th,tw=template.shape[:2]
    if th>patch.shape[0] or tw>patch.shape[1]:
        return None,None
    scores=cv2.matchTemplate(cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY),template,cv2.TM_CCOEFF_NORMED)
    _,score,_,point=cv2.minMaxLoc(scores)
    if score<.85:
        return None,None
    x,y=point
    hsv=cv2.cvtColor(patch[y:y+th,x:x+tw],cv2.COLOR_BGR2HSV)
    gold=(hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>80)&(hsv[:,:,2]>150)
    white=(hsv[:,:,1]<60)&(hsv[:,:,2]>180)
    center=((x1+x+tw/2)/w,(y1+y+th/2)/h)
    if np.mean(gold)>.08:
        return "on",center
    if np.mean(white)>.08:
        return "off",center
    return None,None
