"""Short-lived visual continuity for an already detected world gate."""
import re
import time

from .models import Token


def track_gate(reference, current, target):
    if reference is None or current is None:
        return None
    import cv2
    import numpy as np
    if abs(reference.shape[1]/reference.shape[0]-current.shape[1]/current.shape[0])>.02:
        return None
    def gray(image):
        return cv2.cvtColor(cv2.resize(image,(960,540)),cv2.COLOR_BGR2GRAY)
    before,after=gray(reference),gray(current)
    x1,y1,x2,y2=[round(v*(960 if i%2==0 else 540)) for i,v in enumerate(target.box)]
    if not (0<x1<x2<960 and 0<y1<y2<540):
        return None
    mask=np.zeros(before.shape,np.uint8)
    mask[max(0,y1-8):min(540,y2+8),max(0,x1-8):min(960,x2+8)]=255
    points=cv2.goodFeaturesToTrack(before,maxCorners=160,qualityLevel=.01,minDistance=3,mask=mask)
    if points is None or len(points)<8:
        return None
    moved,status,error=cv2.calcOpticalFlowPyrLK(before,after,points,None,winSize=(31,31),maxLevel=4)
    if moved is None:
        return None
    back,valid,_=cv2.calcOpticalFlowPyrLK(after,before,moved,None,winSize=(31,31),maxLevel=4)
    if back is None:
        return None
    good=(status.ravel()==1)&(valid.ravel()==1)&(error.ravel()<30)
    good&=np.linalg.norm(back-points,axis=2).ravel()<1
    if np.count_nonzero(good)<8:
        return None
    matrix,inliers=cv2.estimateAffinePartial2D(points[good],moved[good],method=cv2.RANSAC,
        ransacReprojThreshold=2,maxIters=500)
    if matrix is None or inliers is None or np.count_nonzero(inliers)<8 or np.mean(inliers)<.7:
        return None
    scale=float(np.hypot(matrix[0,0],matrix[1,0]))
    if not .6<=scale<=1.6 or abs(matrix[1,0])>.25:
        return None
    corners=np.array([[[x1,y1]],[[x2,y1]],[[x1,y2]],[[x2,y2]]],np.float32)
    shifted=cv2.transform(corners,matrix).reshape(-1,2)
    a,b=shifted.min(axis=0);c,d=shifted.max(axis=0)
    box=(float(a/960),float(b/540),float(c/960),float(d/540))
    if not (.02<box[0]<box[2]<.98 and .08<box[1]<box[3]<.90):
        return None
    return Token('Target',min(target.score,float(np.mean(inliers))),box)


def recent_gate(context, scene):
    stored=getattr(context,'_du_gate_reference',None)
    if not isinstance(stored,tuple) or len(stored)!=3:
        return None
    reference,target,recorded=stored
    if not 0<=time.monotonic()-recorded<=12 or reference.geometry!=scene.geometry:
        return None
    def phase(page):
        text=''.join(t.text for t in page.tokens if t.within((0,0,.32,.07)))
        match=re.search(r'(\d{1,2})\s*/\s*13',text)
        return int(match[1]) if match else None
    previous,current=phase(reference),phase(scene)
    if previous is None or previous!=current:
        return None
    return track_gate(reference.image,scene.image,target)
