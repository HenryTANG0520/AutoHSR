"""Local slot comparisons; callers must bind identity and input provenance."""
import base64
import zlib

import cv2
import numpy as np

from .currency_wars_deployment import _crop


def appearance(scene,roi):
    gray=cv2.cvtColor(cv2.resize(_crop(scene.image,roi),(32,48),interpolation=cv2.INTER_AREA),cv2.COLOR_BGR2GRAY)
    return base64.b64encode(zlib.compress(gray.tobytes())).decode('ascii')


def _decoded(value):
    if not isinstance(value,str) or not 0<len(value)<=4096:raise ValueError('槽位图像来源无效')
    decoder=zlib.decompressobj()
    try:raw=decoder.decompress(base64.b64decode(value,validate=True),1537)
    except (ValueError,zlib.error) as error:raise ValueError('槽位图像来源编码无效') from error
    if len(raw)!=1536 or not decoder.eof or decoder.unused_data:raise ValueError('槽位图像来源大小无效')
    return np.frombuffer(raw,dtype=np.uint8).reshape((48,32))


def same_appearance(a,b):
    left,right=_decoded(a),_decoded(b)
    if np.array_equal(left,right):return True
    score=float(cv2.matchTemplate(left,right,cv2.TM_CCOEFF_NORMED)[0,0])
    return bool(np.isfinite(score) and score>=.995 and np.mean(np.abs(left.astype(float)-right.astype(float)))<=2.)
