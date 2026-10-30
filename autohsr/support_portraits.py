"""Card-local template identity with a separate corner-badge retry."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .models import AutomationError
from .support_profiles import catalogue


SCALES=(.90,.95,1.,1.05,1.10)
THRESHOLD=.90
MARGIN=.025


@dataclass(frozen=True)
class Portrait:
    character: str
    score: float
    box: tuple[float,float,float,float]
    masked: bool
    mask_mode: str


@lru_cache(maxsize=1)
def references():
    result={};root=RESOURCE_ROOT/'assets/upstream/March7thAssistant/support'
    for name,row in catalogue().items():
        raw=(root/row['file']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row['sha256']:raise AutomationError('支援头像参考文件与原清单不同。')
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)
        if image is None or [image.shape[1],image.shape[0]]!=row['size']:raise AutomationError('支援头像参考文件无法核实。')
        result[name]=tuple(cv2.resize(image,None,fx=s,fy=s,interpolation=cv2.INTER_AREA if s<1 else cv2.INTER_LINEAR) for s in SCALES)
    return result


def _best(patch,images,masked):
    best=(-1.,None)
    for image in images:
        h,w=image.shape[:2]
        if h>patch.shape[0] or w>patch.shape[1]:continue
        mask=None
        if masked:
            mask=np.full((h,w),255,np.uint8);mask[:round(h*.26),w-round(w*.26):]=0
            if masked==2:mask[round(h*.22):round(h*.65),:round(w*.26)]=0
        values=cv2.matchTemplate(patch,image,cv2.TM_CCOEFF_NORMED,mask=mask)
        values=np.nan_to_num(values,nan=-1.,posinf=-1.,neginf=-1.)
        _,score,_,point=cv2.minMaxLoc(values)
        if score>best[0]:best=(score,(point[0],point[1],w,h))
    return best


def identify(scene,row,wanted):
    """A role match is only candidate evidence, never click authorization."""
    if scene.image is None or not wanted:return None
    bank=references();wanted=set(wanted)
    if not wanted.issubset(bank):raise AutomationError('支援偏好包含未校准角色。')
    image=scene.image;h,w=image.shape[:2]
    if w!=1920:image=cv2.resize(image,(1920,round(h*1920/w)));h,w=image.shape[:2]
    y=row[0].center[1]
    left,right=round(.017*w),round(.090*w)
    top,bottom=round(max(.15,y-.04)*h),round(min(.91,y+.085)*h)
    patch=image[top:bottom,left:right]
    if not patch.size or patch.std()<4:return None
    for masked in (0,1,2):
        candidates={name:_best(patch,bank[name],masked) for name in wanted}
        character,(score,box)=max(candidates.items(),key=lambda item:item[1][0])
        if score<THRESHOLD:continue
        rivals=max((_best(patch,values,masked)[0] for name,values in bank.items() if name!=character),default=-1)
        if score-rivals<MARGIN:
            if rivals>score+MARGIN:return None
            continue
        x1,y1,tw,th=box;cx,cy=(left+x1+tw/2)/w,(top+y1+th/2)/h
        if not .025<=cx<=.080 or not y-.005<=cy<=y+.060:return None
        return Portrait(character,score,((left+x1)/w,(top+y1)/h,(left+x1+tw)/w,(top+y1+th)/h),bool(masked),
                        ('original','corner_badge','card_badges')[masked])
    return None
