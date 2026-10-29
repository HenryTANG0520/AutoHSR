"""Bounded preferred-support selection with the native feedback gates."""
from dataclasses import asdict
import hashlib

from .models import AutomationError,normalize
from .support_profiles import validate
from .support_portraits import identify


class Selector:
    def __init__(self,workflow):
        self.flow=workflow;self.ctx=workflow.ctx;self.settings=workflow.settings
        self.preferences=validate(self.settings)
        from .dungeons import category_for
        self.planar=category_for(self.settings).key=='planar'
        self.picker=workflow._planar_picker if self.planar else workflow._support_picker
        self.marker=workflow._planar_marker if self.planar else workflow._support_marker
        self.record=dict(state='searching',mode='planar' if self.planar else 'standard',
            requested=[asdict(p) for p in self.preferences],fallback=self.settings.support_fallback,
            maximum_pages=self.settings.support_scroll_pages,pages_seen=0,attempts=0,selected=None,evidence=[])
        self.ctx.report.support_selections.append(self.record)
        self.tried=set();self.flow._support_skipped=False

    def evidence(self,scene,label):
        path=self.ctx.evidence(scene,label)
        if path is not None:self.record['evidence'].append(str(path))

    def rows(self,scene):
        threshold=max(.85,self.settings.ocr_confidence)
        return [r for r in self.flow._support_friend_rows(scene)
                if r[0].score>=threshold and r[1].score>=threshold
                and any(t.text.strip('★ ')==r[2] and t.score>=threshold
                        and abs(t.center[1]-r[0].center[1])<.025 and .08<t.center[0]<.235 for t in scene.tokens)]

    @staticmethod
    def signature(row):return row[2],normalize(row[1].text),round(row[0].center[1],3)

    @staticmethod
    def same_row(left,right):
        return (left[2]==right[2] and normalize(left[1].text)==normalize(right[1].text)
                and abs(left[0].center[1]-right[0].center[1])<.02)

    @staticmethod
    def card_key(scene,row):
        portrait=None
        if scene.image is not None:
            h,w=scene.image.shape[:2];y=row[0].center[1]
            patch=scene.image[round(y*h):round((y+.055)*h),round(.035*w):round(.070*w)]
            if patch.size:portrait=hashlib.sha256(patch.tobytes()).hexdigest()
        return row[2],normalize(row[1].text),portrait or round(row[0].center[1],3)

    def candidates(self,scene,rows,*,fallback=False):
        result=[];matches={}
        for index,pref in enumerate(self.preferences if not fallback else (None,)):
            for row in rows:
                if pref is not None and pref.friend and pref.friend!=row[2]:continue
                portrait=None
                if pref is not None and pref.character:
                    key=self.signature(row),pref.character
                    if key not in matches:matches[key]=identify(scene,row,{pref.character})
                    portrait=matches[key]
                    if portrait is None:continue
                key=self.card_key(scene,row)
                if key not in self.tried:result.append((index,row,portrait,key,pref))
        return result

    def open(self,scene):
        flow=self.flow
        if not flow._team_page(scene):raise AutomationError('支援偏好入口前未核实准备页。')
        if self.planar:
            self.ctx.move(scene,(.60,.60));flow._pause();scene=flow._snapshot()
        support=scene.find('支援',(0,.68,1,1),exact=True)
        if support is None and self.planar:
            remove=scene.find('解除支援',(0,.68,1,1),exact=True)
            if remove is not None and self.marker(scene):
                flow._click(scene,remove)
                scene=flow._wait(lambda s:flow._team_page(s) and s.has('支援',(0,.68,1,1),exact=True)
                    and not self.marker(s),description='核实旧借用支援已解除')
                support=scene.find('支援',(0,.68,1,1),exact=True)
        if support is None:raise AutomationError('未核实偏好支援入口，未更换自身编队。')
        flow._click(scene,support);scene=flow._wait(self.picker,description='等待偏好支援列表')
        if self.marker(scene) or flow._support_full(scene):
            raise AutomationError('支援列表已有未归属本次选择的反馈，未确认或替换自身角色。')
        self.evidence(scene,'support_preferences_open');return scene

    def scroll(self,scene,amount):
        if not self.picker(scene) or self.marker(scene) or self.flow._support_full(scene):
            raise AutomationError('支援滚动前页面或反馈未核实。')
        self.ctx.move(scene,(.16,.52));self.ctx.scroll(amount);self.flow._pause()
        return self.flow._wait(self.picker,description='核实支援列表滚动后页面')

    def choose(self,candidate):
        index,old,portrait,key,pref=candidate;flow=self.flow
        scene=flow._snapshot()
        if not self.picker(scene) or self.marker(scene) or flow._support_full(scene):
            raise AutomationError('支援偏好选择前出现未归属反馈，未使用旧候选。')
        current=[r for r in self.rows(scene) if self.same_row(r,old)]
        if len(current)!=1:raise AutomationError('偏好好友卡片的昵称、等级或位置已变化。')
        row=current[0]
        key=self.card_key(scene,row)
        if key in self.tried:return None
        if pref is not None and pref.character:
            portrait=identify(scene,row,{pref.character})
            if portrait is None:raise AutomationError('偏好角色头像已变化或不唯一，未选择旧目标。')
        self.evidence(scene,'support_preference_before')
        self.ctx.log('核对回退好友支援。' if pref is None else f'核对第{index+1}项支援偏好。')
        self.tried.add(key);self.record['attempts']+=1
        scene=flow._click(scene,row[0])
        feedback=lambda s: (self.picker(s) and (self.marker(s) or flow._support_full(s))) or (
            self.planar and flow._team_page(s) and self.marker(s))
        if not feedback(scene):scene=flow._wait(feedback,timeout=15,description='核实偏好支援选择反馈')
        if self.marker(scene) and flow._support_full(scene):raise AutomationError('偏好支援与满员反馈冲突。')
        if flow._support_full(scene):
            self.evidence(scene,'support_preference_full')
            cleared=flow._wait(lambda s:self.picker(s) and not flow._support_full(s),timeout=10,
                               description='等待本张偏好好友的满员提示消失')
            if self.marker(cleared):raise AutomationError('满员提示后支援来源不明，未选择下一张。')
            return None
        if self.picker(scene):
            selected=[r for r in self.rows(scene) if self.same_row(r,row)]
            if len(selected)!=1:raise AutomationError('选择后好友卡片来源已改变，未确认入队。')
            if pref is not None and pref.character and identify(scene,selected[0],{pref.character}) is None:
                raise AutomationError('选择后的角色头像未核实，未确认入队。')
            self.evidence(scene,'support_preference_selected')
            if self.planar:scene=flow._press('esc')
            else:
                confirm=scene.find('确认',(.70,.85,.99,1),exact=True)
                if confirm is None:raise AutomationError('偏好支援缺少实际入队确认。')
                scene=flow._click(scene,confirm)
        scene=flow._wait(lambda s:flow._team_page(s) and self.marker(s),timeout=15,description='核实偏好支援实际入队')
        self.evidence(scene,'support_preference_team')
        self.record.update(state='borrowed',selected=dict(preference=None if pref is None else index,
            character=None if portrait is None else portrait.character,friend=row[2],
            portrait=None if portrait is None else asdict(portrait)),fallback_used=pref is None)
        self.ctx.log('已核实好友支援入队。' if pref is None else '已核实偏好支援入队。')
        return scene

    def search(self,scene,*,fallback=False):
        previous=None;unchanged=0
        for page in range(self.settings.support_scroll_pages):
            if not self.picker(scene) or self.marker(scene) or self.flow._support_full(scene):
                raise AutomationError('支援查找页面或反馈未核实。')
            self.record['pages_seen']+=1;rows=self.rows(scene)
            self.ctx.log(f'查找支援：第{page+1}页，最多{self.settings.support_scroll_pages}页。')
            if not rows:
                if scene.has(('暂无好友','暂无支援角色','暂无可用支援')):return None
                raise AutomationError('未核实完整好友卡片，未把未知页面当作偏好不存在。')
            candidates=self.candidates(scene,rows,fallback=fallback)
            for candidate in candidates:
                selected=self.choose(candidate)
                if selected is not None:return selected
            scene=self.flow._snapshot()
            signature=tuple((r[2],normalize(r[1].text)) for r in self.rows(scene))
            unchanged=unchanged+1 if signature==previous else 0;previous=signature
            if page+1>=self.settings.support_scroll_pages or unchanged>=2:break
            scene=self.scroll(scene,-720)
        return None

    def run(self,scene):
        try:
            scene=self.open(scene);selected=self.search(scene)
            if selected is not None:return selected
            if self.settings.support_fallback=='friend':
                self.ctx.log('本次未核实可用偏好，按设置查找其他好友支援。')
                scene=self.scroll(self.flow._snapshot(),60000)
                selected=self.search(scene,fallback=True)
                if selected is not None:return selected
            if self.settings.support_fallback=='skip':
                scene=self.flow._snapshot()
                if not self.picker(scene) or self.marker(scene) or self.flow._support_full(scene):
                    raise AutomationError('退出支援前页面未核实，未执行跳过回退。')
                self.flow._press('esc')
                scene=self.flow._wait(lambda s:self.flow._team_page(s) and not self.marker(s),description='核实未借用支援返回准备页')
                self.flow._support_skipped=True;self.record.update(state='skipped',fallback_used=True)
                self.ctx.log('本次未核实可用偏好，按设置不借用支援。')
                return scene
            raise AutomationError('本次有界查找未核实可用偏好支援，未开始挑战或更换自身编队。')
        except Exception as error:
            self.record.update(state='unverified',error=str(error));raise


def select(workflow,scene):return Selector(workflow).run(scene)
