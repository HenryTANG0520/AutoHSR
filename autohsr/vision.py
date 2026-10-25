from __future__ import annotations

import time
from pathlib import Path

from .models import AutomationError, Scene, Token


def helper_overlay(scene):
    """Reject the helper's own desktop UI even if the game regained focus."""
    anchors=('每日任务','运行日志','保存设置','OCR阈值','战斗超时','操作间隔','配置位置')
    return scene.has('AutoHSR') and sum(scene.has(label) for label in anchors)>=2


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
        template = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if template is None:
            raise AutomationError(f"无法读取图像模板：{path}")
        height, width = scene.image.shape[:2]
        x1, y1, x2, y2 = round(roi[0]*width), round(roi[1]*height), round(roi[2]*width), round(roi[3]*height)
        patch = scene.image[y1:y2, x1:x2]
        ratio = width / 1920
        template = cv2.resize(template, None, fx=ratio, fy=ratio)
        if template.shape[0] > patch.shape[0] or template.shape[1] > patch.shape[1]:
            return None
        if template.ndim==3 and template.shape[2]==4:
            mask=template[:,:,3]
            scores=cv2.matchTemplate(patch,template[:,:,:3],cv2.TM_CCORR_NORMED,mask=mask)
            scores=np.nan_to_num(scores,nan=-1,posinf=-1,neginf=-1)
        else:
            scores = cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED)
        _, confidence, _, point = cv2.minMaxLoc(scores)
        if confidence < threshold:
            return None
        return ((x1+point[0]+template.shape[1]/2)/width, (y1+point[1]+template.shape[0]/2)/height, confidence)

    def read_number(self,image):
        """Recognize one tightly bounded numeric field without text detection."""
        return self._read_field(image,r'[0-9]{1,2}')

    def refine_daily_synthesis(self, scene):
        from .daily_synthesis import selected, quantity
        if scene.image is None or not selected(scene) or quantity(scene) is not None:
            return
        if not scene.has('合成数量', (.56, .75, .64, .80)):
            return
        h, w = scene.image.shape[:2]
        box = (.637, .766, .660, .799)
        import cv2
        fields = []
        # A lone thin “1” is unstable on the animated purple background.
        # Native and thresholded crops must agree whenever both are readable.
        for region in (box, (.640, .772, .655, .797)):
            patch = scene.image[round(region[1]*h):round(region[3]*h), round(region[0]*w):round(region[2]*w)]
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
            binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)[1]
            for sample in (patch, binary):
                field = self._read_field(sample, r'\s*[1-9]\d{0,3}\s*')
                if field is not None:
                    fields.append(field)
        if fields and len({field.text.strip() for field in fields}) == 1:
            field = max(fields, key=lambda item: item.score)
            scene.tokens.append(Token(field.text.strip(), field.score, box))

    def planar_payment(self, scene):
        from .config import RESOURCE_ROOT
        from .models import normalize
        from .planar_team import preparation
        import re
        if not preparation(scene) or scene.image is None:
            raise AutomationError('未核实饰品提取价格所在页面。')
        h, w = scene.image.shape[:2]
        import cv2
        # Match at the template's native baseline; upscaling a small currency
        # glyph to 4K loses detail and differs from the game's own rendering.
        matched_scene = Scene(scene.tokens, cv2.resize(scene.image, (1920, round(h*1920/w))))
        prices = dict(stamina=0, immersifiers=0)
        for key, name in (('stamina', 'planar_stamina_cost'), ('immersifiers', 'planar_immersifier_cost')):
            match = self.template(matched_scene, RESOURCE_ROOT/'assets/templates'/(name+'.png'), (.73,.88,.84,.95), .90)
            if match is None and key == 'stamina':
                match = self.template(matched_scene, RESOURCE_ROOT/'assets/templates/planar_stamina_cost_single.png', (.73,.88,.84,.95), .90)
            if match is None and key == 'stamina':
                # The animated glow can lower either full-icon score. Accept
                # a marginal fit only when both calibrated layouts agree on
                # the same icon position; the caller still checks exact cost.
                weak=[self.template(matched_scene,RESOURCE_ROOT/'assets/templates'/(n+'.png'),
                                    (.73,.88,.84,.95),.88)
                      for n in ('planar_stamina_cost','planar_stamina_cost_single')]
                if all(weak) and abs(weak[0][0]-weak[1][0])<.004 and abs(weak[0][1]-weak[1][1])<.004:
                    match=max(weak,key=lambda value:value[2])
            if match is None:
                continue
            x, y, _ = match
            # Read both widths: a narrow crop clips three-digit prices, while
            # a wide crop can include the divider after a two-digit price.
            values=set()
            for right in ((.032,.043) if key=='stamina' else (.032,)):
                patch=scene.image[round((y-.017)*h):round((y+.017)*h),
                                  round((x+.010)*w):round((x+right)*w)]
                number=self._read_field(patch,r'[×xX*]?\s*\d{1,3}')
                value=re.fullmatch(r'[×x*]?(\d{1,3})',normalize(number.text)) if number else None
                if value:
                    values.add(int(value[1]))
            # The independently located full-frame price can disambiguate a
            # plausible clipped prefix (e.g. 24 versus 240); never invent it
            # from the requested count or accept conflicting observations.
            full=set()
            if key=='stamina':
                for token in scene.tokens:
                    if token.score>=.85 and token.within((x+.008,y-.025,min(.88,x+.060),y+.025)):
                        value=re.fullmatch(r'[×x*]?(\d{1,3})',normalize(token.text))
                        if value:
                            full.add(int(value[1]))
            if len(full)==1:
                values &= full
            if len(values)!=1:
                raise AutomationError('饰品提取资源图标旁的价格无法读取。')
            prices[key] = values.pop()
        return prices

    def refine_du_field_header(self,scene):
        """Read the fixed live-field header when full-frame detection misses it."""
        from .policy import has_du_field_plane_marker
        if scene.image is None or has_du_field_plane_marker(scene.text):
            return
        height,width=scene.image.shape[:2]
        box=(.015,.012,.17,.04)
        patch=scene.image[round(box[1]*height):round(box[3]*height),
                          round(box[0]*width):round(box[2]*width)]
        field=self._read_field(patch,r'.*(?:[1-9]|1[0-3])/13[)）]?第[一二三四五六1-6]位面[-—]?(?:战斗|精英|首领|异常|休整|奖励|事件|商店|财富|空白|铸造|冒险|奇遇[-—]?奇物合成).*')
        if field:
            scene.tokens.append(Token(field.text,field.score,box))

    def refine_du_reward_balance(self,scene):
        from .du_rewards import page_kind,moon_balance
        if scene.image is None or page_kind(scene)!='moon_rewards' or moon_balance(scene) is not None:
            return
        h,w=scene.image.shape[:2]
        box=(.885,.039,.925,.080)
        patch=scene.image[round(box[1]*h):round(box[3]*h),round(box[0]*w):round(box[2]*w)]
        field=self._read_field(patch,r'\d{1,5}')
        if field:
            scene.tokens.append(Token(field.text,field.score,box))
        else:
            # RapidOCR reads this lone zero with low confidence. An exact
            # observed glyph is sufficient only for zero (never to unlock).
            template=Path(__file__).resolve().parents[1]/'assets/templates/du_cassette_zero.png'
            match=self.template(scene,template,box,threshold=.94)
            if match:
                scene.tokens.append(Token('0',match[2],box))

    def refine_du_blessing_names(self,scene):
        """Retry missing card titles at native resolution, without body text."""
        import re
        if scene.image is None or not scene.has('选择祝福',(0,0,.32,.13),exact=True):
            return
        from .du_strategy import blessing_columns
        h,w=scene.image.shape[:2]
        for left,right in blessing_columns(scene):
            roi=(left,.445,right,.495)
            if any(t.within(roi) and re.search(r'[\u3400-\u9fff]',t.text) for t in scene.tokens):
                continue
            patch=scene.image[round(roi[1]*h):round(roi[3]*h),round(left*w):round(right*w)]
            local=self.read(patch)
            for token in local.tokens:
                if re.search(r'[\u3400-\u9fff]',token.text):
                    a,b,c,d=token.box
                    scene.tokens.append(Token(token.text,token.score,
                        (left+a*(right-left),roi[1]+b*(roi[3]-roi[1]),
                         left+c*(right-left),roi[1]+d*(roi[3]-roi[1]))))

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
