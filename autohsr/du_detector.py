"""Optional ONNX world detector. Training dependencies stay outside AutoHSR."""
from functools import lru_cache
import os
from pathlib import Path

from .config import RESOURCE_ROOT
from .models import Token

NAMES=("Target","GateLocked","Enemy")


def model_path():
    return Path(os.environ.get("AUTOHSR_DU_DETECTOR",str(RESOURCE_ROOT/"assets/models/du_target.onnx")))


@lru_cache(maxsize=4)
def _session(path):
    import onnxruntime as ort
    options=ort.SessionOptions()
    options.intra_op_num_threads=2
    options.inter_op_num_threads=1
    return ort.InferenceSession(path,sess_options=options,providers=["CPUExecutionProvider"])


def decode(prediction,width,height,size,scale,pad,threshold=.55,names=NAMES):
    import cv2
    import numpy as np
    rows=np.asarray(prediction)[0]
    if rows.shape[0]==4+len(names):
        rows=rows.T
    if rows.ndim!=2 or rows.shape[1]!=4+len(names):
        raise ValueError("DU detector must export YOLO11 raw xywh + class scores")
    classes=rows[:,4:].argmax(axis=1)
    scores=rows[np.arange(len(rows)),classes+4]
    tokens=[]
    px,py=pad
    for cls,name in enumerate(names):
        selected=rows[(classes==cls)&(scores>=threshold)]
        if not len(selected):
            continue
        confidence=selected[:,4+cls]
        boxes=[]
        for x,y,w,h in selected[:,:4]:
            x1=(x-w/2-px)/scale;y1=(y-h/2-py)/scale
            boxes.append([float(x1),float(y1),float(w/scale),float(h/scale)])
        keep=cv2.dnn.NMSBoxes(boxes,confidence.tolist(),threshold,.45)
        for i in np.asarray(keep).ravel():
            x,y,w,h=boxes[int(i)]
            box=(max(0,x/width),max(0,y/height),min(1,(x+w)/width),min(1,(y+h)/height))
            if box[0]<box[2] and box[1]<box[3]:
                tokens.append(Token(name,float(confidence[int(i)]),box))
    return sorted(tokens,key=lambda t:t.score,reverse=True)


def detect(scene,threshold=.55):
    """None means no installed model; [] means observed but no target found."""
    return _detect(scene,model_path(),threshold,NAMES)


def detect_cards(scene,threshold=.80):
    """Separate learned world-card model; no gate/artwork color fallback."""
    found=_detect(scene,RESOURCE_ROOT/'assets/models/du_cards.onnx',threshold,('Card',))
    return None if found is None else [t for t in found if t.within((.04,.08,.92,.85))]


def detect_enemies(scene,threshold=.70):
    """Coarse visible enemy bearing, never an attack-range signal."""
    found=_detect(scene,RESOURCE_ROOT/'assets/models/du_enemies.onnx',threshold,('Enemy',))
    primary=found
    found=_usable_enemies(found or [])
    if not found:
        # Keep the preceding calibrated fit for occluded appearances forgotten
        # by an incremental fit. Run it only when the primary has no bearing.
        previous=_detect(scene,RESOURCE_ROOT/'assets/models/du_enemies_fallback.onnx',threshold,('Enemy',))
        if previous is not None:
            return _usable_enemies(previous)
    return None if primary is None else found


def detect_recovery_enemies(scene,threshold=.70):
    """Additional bearings for missed-attack or explicit resumed-field recovery."""
    found=_detect(scene,RESOURCE_ROOT/'assets/models/du_enemies_recovery.onnx',threshold,('Enemy',))
    return _usable_enemies(found or [])


def _usable_enemies(found):
    return [t for t in found if t.within((.04,.06,.95,.90))
        # A small lower-centre box wholly inside the avatar is not a usable
        # enemy bearing. Real close-range enemies are handled by their ring;
        # verified headings have a separate, bounded occlusion allowance.
        and not (.38<=t.box[0] and .42<=t.box[1] and t.box[2]<=.62
                 and .60<t.box[3]<=.94)]


def _detect(scene,path,threshold,allowed_names):
    if scene.image is None or not path.is_file():
        return None
    import cv2
    import numpy as np
    session=_session(str(path.resolve()))
    import ast
    labels=ast.literal_eval(session.get_modelmeta().custom_metadata_map["names"])
    names=tuple(labels[i] for i in range(len(labels)))
    if not names or any(name not in allowed_names for name in names):
        raise ValueError("Unexpected DU detector class metadata")
    size=session.get_inputs()[0].shape[-1]
    if type(size) is not int:
        raise ValueError("DU detector requires a static square input")
    image=scene.image
    h,w=image.shape[:2]
    scale=min(size/w,size/h)
    nw,nh=round(w*scale),round(h*scale)
    px,py=(size-nw)//2,(size-nh)//2
    # The identifier is also masked in the locally reviewed training samples.
    source=image.copy()
    source[round(.963*h):]=0
    frame=np.full((size,size,3),114,np.uint8)
    frame[py:py+nh,px:px+nw]=cv2.resize(source,(nw,nh))
    tensor=np.ascontiguousarray(frame[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255
    output=session.run(None,{session.get_inputs()[0].name:tensor})[0]
    return decode(output,w,h,size,scale,(px,py),threshold,names)


def forward_barrier(image):
    """A red triangular world warning blocks forward travel, not side scenery."""
    if image is None:
        return None
    import cv2
    import numpy as np
    h,w=image.shape[:2]
    sample=cv2.resize(image,(960,round(h*960/w)))
    hsv=cv2.cvtColor(sample,cv2.COLOR_BGR2HSV)
    red=(((hsv[:,:,0]<12)|(hsv[:,:,0]>170))&(hsv[:,:,1]>155)&(hsv[:,:,2]>170)).astype(np.uint8)*255
    red=cv2.morphologyEx(red,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
    contours,_=cv2.findContours(red,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    sh,sw=red.shape
    for contour in contours:
        x,y,cw,ch=cv2.boundingRect(contour)
        if not (.32*sw<x+cw/2<.68*sw and .12*sh<y+.5*ch<.58*sh
                and ch>.12*sh and .65<cw/ch<1.6):
            continue
        hull=cv2.convexHull(contour)
        vertices=cv2.approxPolyDP(hull,.06*cv2.arcLength(hull,True),True)
        if len(vertices)==3 and cv2.contourArea(contour)>.12*cw*ch:
            return Token("红色警戒边界",.95,(x/sw,y/sh,(x+cw)/sw,(y+ch)/sh))
    return None
