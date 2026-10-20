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

    def refine_planar_support(self, scene):
        if scene.image is None or getattr(scene, "_planar_badges_read", False):
            return
        scene._planar_badges_read = True
        height,width = scene.image.shape[:2]
        for center in (.337,.3865,.437,.4855):
            box = (center-.01,.782,center+.01,.800)
            x1,y1,x2,y2 = box
            patch = scene.image[round(y1*height):round(y2*height),round(x1*width):round(x2*width)]
            field = self._read_field(patch, r'支援')
            if field and not any(t.text == "支援" and t.within(box) for t in scene.tokens):
                scene.tokens.append(Token("支援",field.score,box))

    def planar_friend_slot(self, scene, badge):
        if scene.image is None:
            return None
        import cv2
        import numpy as np
        height,width = scene.image.shape[:2]
        y = badge.center[1]
        patch = scene.image[round((y-.026)*height):round((y-.004)*height),round(.018*width):round(.035*width)]
        if not patch.size:
            return None
        hsv = cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)
        if float(np.mean((hsv[:,:,1]<60)&(hsv[:,:,2]>190))) < .30:
            return None
        value = self.read_number(patch)
        return int(value.text) if value and value.text in ("1","2","3","4") else None

    def refine_dungeon_rows(self, scene, category):
        """Recognize mission fields at native resolution, excluding the map pin.

        Full-frame OCR is downsampled to 1920px; narrow field recognition avoids
        losing strokes in Chinese names on 4K clients. It uses the same captured
        pixels and preserves scene identity and input freshness checks.
        """
        from .dungeon_workflow import guide_rows
        from .dungeons import mission_name
        import re
        if scene.image is None:
            return
        height, width = scene.image.shape[:2]
        offset = .09 if category == "echo_of_war" else 0 if category == "planar" else .02
        for mission, button in guide_rows(scene, category, strict=False):
            names = [t for t in scene.tokens if t.within((.44,.26,.70,.82))
                     and abs(t.center[1]-(button.center[1]-offset)) < .018
                     and mission_name(category, t.text) == mission.name]
            if len(names) != 1:
                continue
            name = names[0]
            places = [t for t in scene.tokens if t.within((.45,.26,.72,.83))
                      and .015 < t.center[1]-name.center[1] < .055
                      and re.search(r"[\u4e00-\u9fff]", t.text)]
            if len(places) != 1 and category != "planar":
                continue
            fields = ((name,False),) if category == "planar" else ((name,False),(places[0],True))
            for original, is_place in fields:
                x1,y1,x2,y2 = original.box
                if is_place:
                    x1 = .477 if category == "echo_of_war" else .473
                else:
                    x1 = .464 if category == "echo_of_war" else .452
                    x2 = max(x2, .60)
                patch = scene.image[max(0,round((y1-.002)*height)):min(height,round((y2+.002)*height)),
                                    max(0,round((x1-.001)*width)):min(width,round((x2+.002)*width))]
                if patch.size:
                    field = self._read_field(patch, r'.*[一-鿿].*')
                    if field:
                        scene.tokens[scene.tokens.index(original)] = Token(field.text, field.score, original.box)

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
