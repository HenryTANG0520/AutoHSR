"""Visually identified event choices with a conservative in-run preference."""
from functools import lru_cache
import re
from .config import RESOURCE_ROOT
from .models import Token,normalize


@lru_cache(maxsize=1)
def _star_template():
    import cv2,numpy as np
    return cv2.imdecode(np.fromfile(RESOURCE_ROOT/'assets/templates/du_event_option_star.png',np.uint8),0)


def option_stars(scene):
    if (scene.image is None or not scene.has('事件',(0,0,.32,.13),exact=True)
            or not scene.has('差分宇宙',(0,0,.32,.13))):
        return []
    import cv2,numpy as np
    image=scene.image
    image=cv2.resize(image,(1920,round(image.shape[0]*1920/image.shape[1])))
    h,w=image.shape[:2]
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
    left,top=round(.695*w),round(.18*h)
    patch=gray[top:round(.90*h),left:round(.735*w)]
    template=_star_template()
    th,tw=template.shape
    if patch.shape[0]<th or patch.shape[1]<tw:
        return []
    scores=cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED)
    found=[]
    for _ in range(6):
        _,score,_,point=cv2.minMaxLoc(scores)
        if not np.isfinite(score) or score<.90:
            break
        x,y=point
        cx=(left+x+tw/2)/w;cy=(top+y+th/2)/h
        hsv=cv2.cvtColor(image[top+y:top+y+th,left+x:left+x+tw],cv2.COLOR_BGR2HSV)
        core=hsv[template>120]
        gold=np.mean((core[:,0]>=12)&(core[:,0]<=45)&(core[:,1]>30)&(core[:,2]>75)) if len(core) else 0
        if gold>.35:
            found.append(Token('差分宇宙事件选项',float(score),(cx-.008,cy-.012,cx+.008,cy+.012)))
        scores[max(0,y-round(.05*h)):min(scores.shape[0],y+round(.05*h)),:]=-1
    return sorted(found,key=lambda t:t.center[1])


def description(scene,star,stars):
    y=star.center[1]
    bottom=min([t.center[1]-.018 for t in stars if t.center[1]>y+.04]+[min(.90,y+.15)])
    return normalize(''.join(t.text for t in scene.tokens if t.within((.70,y+.018,.98,bottom))
                             and normalize(t.text) not in ('确认','确定')))


def preferred_option(scene):
    stars=option_stars(scene)
    balances=[int(normalize(t.text)) for t in scene.tokens if t.within((.89,.025,.97,.095))
              and re.fullmatch(r'\d{1,6}',normalize(t.text))]
    balance=balances[0] if len(balances)==1 else None
    candidates=[]
    for star in stars:
        body=description(scene,star,stars)
        if any(word in body for word in ('星琼','开拓力','燃料','充值','续购','兑换')):
            continue
        costs=re.findall(r'(?:花费|消耗|支付|扣除|失去)(\d+)宇宙碎片',body)
        cost=sum(map(int,costs))
        if cost and (balance is None or cost>balance):
            continue
        negative=re.findall(r'(\d+)个(?:随机)?负面奇物',body)
        negative=sum(map(int,negative)) if negative else (10 if '负面奇物' in body else 0)
        losses=sum(body.count(word) for word in ('失去','消耗','花费','扣除','降低'))
        rarity=max([int(v) for v in re.findall(r'([1-3])星(?:祝福|方程|奇物)',body)]+[0])
        # User-authorized star fallback still works when OCR cannot read a
        # caption/body. Known adverse effects rank below lower-risk options.
        score=(negative,losses,cost,-rarity,not bool(body),star.center[1])
        candidates.append((score,star))
    return min(candidates,key=lambda item:item[0])[1] if candidates else None


def action(scene):
    star=preferred_option(scene)
    if star is None:
        return None
    stars=option_stars(scene)
    y=star.center[1]
    bottom=min([t.center[1]-.015 for t in stars if t.center[1]>y+.04]+[.94,y+.18])
    confirm=scene.find(('确定','确认'),(.75,y+.025,.99,bottom),exact=True)
    if confirm is not None:
        return confirm,'event_star_confirm'
    # Clicking the star itself leaves the pointer/glow over its next-frame
    # pixels. Select within the same caption row so all stars stay observable.
    x=min(.94,star.center[0]+.10)
    return Token(star.text,star.score,(x-.008,y-.012,x+.008,y+.012)),'event_star_select'


def guard(scene,target,intent):
    from .models import AutomationError
    expected=action(scene)
    if expected is None or expected!=(target,intent):
        raise AutomationError('未核实当前事件选项星标、保守选择或相邻确认按钮，未提交。')


def reward_bundle_size(scene,target,intent):
    """An explicitly confirmed N-reward option bounds identical receipt closes."""
    if intent!='event_star_confirm' or action(scene)!=(target,intent):
        return 0
    star=preferred_option(scene)
    if star is None:
        return 0
    body=description(scene,star,option_stars(scene))
    match=re.match(r'获得(?:(\d+)-)?(\d+)次随机奖励',body)
    if match is None:
        return 0
    low=int(match[1] or match[2]);high=int(match[2])
    return high if 0<=low<=high<=20 else 0
