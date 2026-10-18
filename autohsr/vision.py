from __future__ import annotations

import time
from pathlib import Path

from .models import AutomationError, Scene, Token


class Vision:
    def __init__(self, confidence: float = 0.65):
        from rapidocr_onnxruntime import RapidOCR
        # Models bundled by RapidOCR keep AutoHSR independently installable.
        self.engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
        self.confidence = confidence

    def read(self, image, geometry=None) -> Scene:
        captured_at = time.monotonic()
        import cv2
        height, width = image.shape[:2]
        scale = min(1.0, 1920 / width)
        sample = cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image
        results, _ = self.engine(sample, use_cls=False)
        tokens = []
        for box, text, score in results or []:
            if float(score) < self.confidence:
                continue
            xs, ys = zip(*box)
            tokens.append(Token(str(text), float(score), (min(xs)/(width*scale), min(ys)/(height*scale), max(xs)/(width*scale), max(ys)/(height*scale))))
        return Scene(tokens, image, geometry, captured_at)

    def template(self, scene: Scene, path: Path, roi=(0, 0, 1, 1), threshold=0.88):
        """Optional local UI anchor matching, resized to the 1080p baseline."""
        import cv2
        import numpy as np
        template = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if template is None:
            raise AutomationError(f"无法读取图像模板：{path}")
        height, width = scene.image.shape[:2]
        x1, y1, x2, y2 = round(roi[0]*width), round(roi[1]*height), round(roi[2]*width), round(roi[3]*height)
        patch = scene.image[y1:y2, x1:x2]
        ratio = width / 1920
        template = cv2.resize(template, None, fx=ratio, fy=ratio)
        if template.shape[0] > patch.shape[0] or template.shape[1] > patch.shape[1]:
            return None
        scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, point = cv2.minMaxLoc(scores)
        if confidence < threshold:
            return None
        return ((x1+point[0]+template.shape[1]/2)/width, (y1+point[1]+template.shape[0]/2)/height, confidence)

    def read_number(self,image):
        """Recognize one tightly bounded numeric field without text detection."""
        return self._read_field(image,r'[0-9]{1,2}')

    def read_node(self,image):
        return self._read_field(image,r'[1-3]-[1-9][0-9]?')

    def _read_field(self,image,pattern):
        import math
        import re
        results,_=self.engine(image,use_det=False,use_cls=False)
        if results and len(results)==1:
            value,score=results[0]
            if re.fullmatch(pattern,value) and math.isfinite(float(score)) and max(.85,self.confidence)<=float(score)<=1:
                return Token(value,float(score),(0,0,1,1))
        return None


def save_scene(scene: Scene, directory: Path, name: str) -> Path:
    import cv2
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.png"
    ok, data = cv2.imencode(".png", scene.image)
    if not ok:
        raise AutomationError("保存截图失败。")
    path.write_bytes(data.tobytes())
    path.with_suffix(".txt").write_text(scene.text, encoding="utf-8")
    return path
