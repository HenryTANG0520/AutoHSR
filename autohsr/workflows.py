from __future__ import annotations

import re
import time
from .models import AutomationError, FocusLost, ROI, Scene, Stopped, TaskResult, Token, normalize
from .policy import replenishment_dialog
from .dungeons import category_for


TITLE: ROI = (0.015, 0.015, 0.32, 0.13)
BOTTOM: ROI = (0, 0.68, 1, 1)
REWARDS: ROI = (0.20, 0.22, 0.94, 0.40)
REWARD_SLOTS: tuple[ROI, ...] = tuple((a, 0.22, b, 0.40) for a, b in
    ((0.20, 0.36), (0.36, 0.51), (0.51, 0.65), (0.65, 0.79), (0.79, 0.94)))
TABS: ROI = (0.15, 0.14, 0.55, 0.25)


class DailyWorkflow:
    """Observed UI transitions; no process memory access or unconditional clicks.

    OCR and packaged icon templates verify each transition. Missing icon evidence
    stops that transition instead of assuming a click or a reward succeeded.
    """

    def __init__(self, context):
        self.ctx = context
        self.settings = context.settings
        self._calyx_location: str | None = None
        self._login_supply_claimed = False
        self._login_supply_closed = False

    def _snapshot(self) -> Scene:
        self.ctx.checkpoint()
        return self.ctx.snapshot()

    def _result(self, task: str, status: str, detail: str, scene=None) -> TaskResult:
        self.ctx.log(detail)
        if scene is not None:
            self.ctx.evidence(scene, f"{task}_{status}")
        return TaskResult(task, status, detail)

    def _pause(self):
        self.ctx.sleep(self.settings.action_delay)

    def _click(self, scene: Scene, target: Token | tuple[float, float]) -> Scene:
        self.ctx.click(scene, target)
        self._pause()
        return self._snapshot()

    def _press(self, key: str) -> Scene:
        self.ctx.key(key)
        self._pause()
        return self._snapshot()

    def _wait(self, predicate, timeout=30, description="等待页面") -> Scene:
        return self.ctx.wait(predicate, timeout=timeout, description=description)

    def _matches(self, scene: Scene, name: str, roi: ROI, threshold=0.90):
        """Separate milestone slots prevent one match proving five rewards."""
        found = []
        regions = REWARD_SLOTS if name in ("daily_completed", "daily_reward") else (roi,)
        for region in regions:
            match = self.ctx.template(scene, name, region, threshold=threshold)
            if (isinstance(match, (tuple, list)) and len(match) == 3
                    and region[0] <= match[0] <= region[2]
                    and region[1] <= match[1] <= region[3]
                    and match[2] >= threshold):
                found.append(match)
        return sorted(found, key=lambda match: match[0])

    def _icon(self, scene: Scene, name: str, roi: ROI, threshold=0.88):
        matches = self._matches(scene, name, roi, threshold=threshold)
        return max(matches, key=lambda match: match[2])[:2] if matches else None

    @staticmethod
    def _phone(scene: Scene) -> bool:
        return scene.has("开拓等级", (0.55, 0.05, 0.99, 0.35)) and scene.has(
            ("委托", "星际和平指南", "指南", "无名勋礼"), (0.55, 0.25, 1, 1)
        )

    @staticmethod
    def _guide(scene: Scene) -> bool:
        return scene.has(("星际和平指南", "指南"), TITLE)

    @staticmethod
    def _tab(scene: Scene, name: str) -> bool:
        return DailyWorkflow._guide(scene) and scene.has(name, TITLE)

    @staticmethod
    def _login(scene: Scene) -> bool:
        return scene.has(("点击进入", "开始游戏", "账号登录", "扫码登录", "验证码", "用户协议", "资源下载"))

    def _in_battle(self, scene: Scene) -> bool:
        if scene.has(("战斗失败", "挑战成功", "退出关卡", "再来一次", "撤退", "战斗设置")):
            return True
        return (self._icon(scene, "battle_pause", (0.93, 0, 1, 0.12)) is not None or
                self._icon(scene, "du_battle_pause", (.95,0,1,.10)) is not None)

    @staticmethod
    def _supply_overlay(scene: Scene) -> bool:
        return scene.has("列车补给", exact=True)

    @staticmethod
    def _login_reward_overlay(scene: Scene) -> bool:
        return scene.has("获得物品", (0.25, 0.04, 0.75, 0.50), exact=True)

    @staticmethod
    def _supply_claim(scene: Scene) -> Token | None:
        if not scene.has("列车补给", (0.32, 0.025, 0.68, 0.20), exact=True):
            return None
        if scene.has(("购买", "续购", "续费", "订购", "支付", "付款")):
            return None
        days = []
        for token in scene.tokens:
            if token.within((0.35, 0.085, 0.65, 0.22)):
                match = re.fullmatch(r"剩余(\d{1,3})天", normalize(token.text))
                if match:
                    days.append(int(match.group(1)))
        if len(days) != 1 or days[0] <= 0:
            return None
        return scene.find("点击领取今日补给", (0.32, 0.75, 0.68, 0.93), exact=True)

    @staticmethod
    def _supply_revealed(scene: Scene) -> bool:
        if DailyWorkflow._supply_claim(scene) is None:
            return False
        labels = [t for t in scene.tokens if t.within((0.45, 0.57, 0.55, 0.62))
                  and normalize(t.text) == "星琼"]
        amounts = [t for t in scene.tokens if t.within((0.465, 0.53, 0.535, 0.57))
                   and normalize(t.text) in ("90", "90°")]
        return (len(labels) == 1 and len(amounts) == 1
                and abs(labels[0].center[0] - amounts[0].center[0]) < 0.025
                and 0.012 < labels[0].center[1] - amounts[0].center[1] < 0.05)

    def _world(self, scene: Scene) -> bool:
        # A smooth modal background can correlate with the small world icon.
        # Recognized login/reward overlays always take precedence over it.
        if (self._login(scene) or self._supply_overlay(scene) or self._login_reward_overlay(scene)
                or scene.has(("点击空白处关闭", "点击任意位置关闭", "点击空白处继续"),
                             (0.25, 0.65, 0.75, 0.97), exact=True)):
            return False
        return self._icon(scene, "world_character", (0.93, 0, 1, 0.09), threshold=0.65) is not None

    def _settle_login_overlays(self, scene: Scene) -> Scene:
        for _ in range(4):
            if self._supply_overlay(scene):
                claim = self._supply_claim(scene)
                if self._supply_revealed(scene):
                    if self._login_supply_closed:
                        raise AutomationError("列车补给奖励展示已关闭过一次，尚未核实退出；已停止。")
                    self._login_supply_claimed = True
                    self._login_supply_closed = True
                    self.ctx.log("已核实列车补给中央90星琼奖励卡，关闭已有奖励展示。")
                    self._click(scene, claim)
                    scene = self._wait(lambda s: not self._supply_overlay(s) and
                                       (self._phone(s) or self._world(s) or self._login_reward_overlay(s)),
                                       timeout=45, description="验证列车补给奖励展示已关闭")
                    continue
                if self._login_supply_claimed or claim is None:
                    raise AutomationError("列车补给未能核实已有剩余天数和今日免费领取入口，或已领取过一次；已停止。")
                if any(t.within((0.40, 0.45, 0.60, 0.68))
                       and (normalize(t.text) in ("星琼", "90°", "90x")
                            or re.fullmatch(r"\d{1,4}", normalize(t.text)))
                       for t in scene.tokens):
                    raise AutomationError("列车补给中心奖励内容尚未核实为已有90星琼展示，已停止。")
                self._login_supply_claimed = True
                self.ctx.log("领取已拥有的列车补给今日登录奖励。")
                self._click(scene, claim)
                scene = self._wait(lambda s: self._supply_revealed(s) or
                                   (not self._supply_overlay(s) and
                                    (self._phone(s) or self._world(s) or self._login_reward_overlay(s))),
                                   timeout=45, description="验证列车补给领奖后界面")
                continue
            if self._login_reward_overlay(scene):
                close = scene.find(("点击空白处关闭", "点击任意位置关闭", "点击空白处继续"),
                                   (0.25, 0.65, 0.75, 0.97), exact=True)
                if close is None or scene.has(("购买", "续购", "续费", "订购", "支付", "付款")):
                    raise AutomationError("登录获得物品弹窗未识别到安全关闭提示，已停止。")
                self._click(scene, close)
                scene = self._wait(lambda s: self._phone(s) or self._world(s),
                                   timeout=45, description="验证登录奖励弹窗已关闭")
                continue
            return scene
        raise AutomationError("登录奖励界面连续变化超过已知流程，已停止。")

    def ensure_main(self) -> Scene:
        """Establish the phone menu as a verified navigation hub."""
        scene = self._snapshot()
        for _ in range(6):
            scene = self._settle_login_overlays(scene)
            if self._phone(scene):
                return scene
            if self._login(scene):
                enter = scene.find(("点击进入", "点击进入游戏", "开始游戏"), exact=True)
                if enter is None or scene.has(("密码", "验证码", "用户协议", "资源下载")):
                    raise AutomationError("游戏需要手动完成账号登录、验证或更新。")
                self._click(scene, enter)
                scene = self._wait(lambda s: self._supply_overlay(s) or self._login_reward_overlay(s)
                                   or self._world(s) or self._phone(s),
                                   timeout=120, description="等待进入游戏场景或已有登录奖励")
                scene = self._settle_login_overlays(scene)
                if self._phone(scene):
                    return scene
            if self._settlement(scene) and scene.has("退出关卡", BOTTOM, exact=True):
                self.ctx.log("已核实遗留结算与退出按钮，清理结算后继续导航。")
                self._exit_result(scene)
                scene = self._snapshot()
                continue
            if self._in_battle(scene):
                raise AutomationError("当前在战斗或结算界面，无法安全返回手机菜单。")
            known_page = scene.has(
                ("委托", "星际和平指南", "每日实训", "生存索引", "邮件", "无名勋礼", "角色", "队伍", "背包", "拟造花萼",
                 "凝滞虚影", "侵蚀隧洞", "历战余响", "饰品提取", "支援列表"),
                TITLE,
            )
            if not known_page and not self._world(scene):
                self.ctx.evidence(scene, "unknown_navigation")
                raise AutomationError("无法确认当前页面；请打开手机菜单，或采集大世界角色图标模板。")
            if _ == 5:
                break
            scene = self._press("esc")
        raise AutomationError("五次返回后仍未识别到手机菜单，已停止导航。")

    def _open_phone_item(self, labels, title: str, icon_name: str | None = None) -> Scene:
        scene = self.ensure_main()
        target = scene.find(labels, (0.55, 0.25, 1, 1), exact=True)
        if target is None and icon_name:
            target = self._icon(scene, icon_name, (0.55, 0.2, 1, 1))
        if target is None:
            raise AutomationError(f"手机菜单中未识别到{title}入口。")
        self._click(scene, target)
        return self._wait(lambda s: s.has(title, TITLE), description=f"等待{title}")

    def _open_guide(self, name: str) -> Scene:
        scene = self._snapshot()
        if not self._guide(scene):
            scene = self._open_phone_item(("星际和平指南", "指南"), "指南", "phone_guide")
        if self._tab(scene, name):
            return scene
        target = scene.find(name, TABS, exact=True)
        if target is None:
            icon_name = "daily_tab" if name == "每日实训" else "survival_tab"
            target = self._icon(scene, icon_name, TABS)
        if target is None:
            raise AutomationError(f"指南已打开，但未识别到{name}页签；需要采集对应图标模板。")
        self._click(scene, target)
        return self._wait(lambda s: self._tab(s, name), description=f"等待{name}页签")

    def _dismiss_reward(self, scene: Scene) -> Scene:
        target = scene.find(("点击空白处关闭", "点击任意位置关闭", "点击空白处继续"), exact=True)
        if target is not None:
            return self._click(scene, target)
        return scene

    @staticmethod
    def _assignment_count(scene: Scene) -> tuple[int, int] | None:
        label = scene.find("进行中的委托", (0.05, 0.65, 0.65, 0.85), exact=True)
        if label is None:
            return None
        candidates = []
        for token in scene.tokens:
            if not token.within((0.05, 0.65, 0.65, 0.85)) or abs(token.center[1] - label.center[1]) > 0.035:
                continue
            match = re.fullmatch(r"(\d{1,2})\s*/\s*(\d{1,2})", token.text.strip())
            if match:
                current, total = map(int, match.groups())
                if 0 <= current <= total <= 4 and total > 0:
                    candidates.append((current, total))
        return candidates[0] if len(candidates) == 1 else None

    @staticmethod
    def _persistent_assignments(scene: Scene) -> bool:
        return (scene.has("委托", TITLE)
                and DailyWorkflow._assignment_count(scene) is not None
                and scene.has("每小时奖励", (0.10, 0.15, 0.65, 0.75))
                and scene.has("已进行", (0.65, 0.45, 0.96, 0.70)))

    @staticmethod
    def _assignment_claim_enabled(scene: Scene, claim: Token) -> bool | None:
        """The 4.6 claim control keeps its label when disabled; inspect its fill."""
        if scene.image is None:
            return None
        import cv2
        import numpy as np

        image = scene.image
        height, width = image.shape[:2]
        x, y = claim.center
        left, right = round((x - 0.075) * width), round((x + 0.075) * width)
        top, bottom = round((y - 0.022) * height), round((y + 0.022) * height)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            return None
        patch = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2HSV)
        gold = ((patch[:, :, 0] >= 12) & (patch[:, :, 0] <= 40)
                & (patch[:, :, 1] >= 100) & (patch[:, :, 2] >= 170))
        fraction = float(np.mean(gold))
        if fraction > 0.35:
            return True
        # A disabled control has a neutral fill. A dark/occluded screenshot is
        # inconclusive rather than proof that rewards were already claimed.
        neutral = (patch[:, :, 1] < 60) & (patch[:, :, 2] >= 70)
        if fraction < 0.05 and float(np.mean(neutral)) > 0.45:
            return False
        return None

    def _assignment_settled(self, scene: Scene) -> bool:
        if not self._persistent_assignments(scene):
            return False
        count = self._assignment_count(scene)
        if count is None or count[0] != count[1]:
            return False
        if scene.has(("暂无可领取奖励", "暂无奖励", "无可领取奖励", "没有可领取的奖励", "奖励已领取"), (0.62, 0.4, 0.98, 0.95)):
            return True
        claim = scene.find("领取奖励", (0.65, 0.78, 0.97, 0.96), exact=True)
        if (claim is None and scene.has("委托派遣中", (0.62, 0.65, 0.98, 0.96))
                and scene.has("每小时可持续获得奖励", (0.62, 0.65, 0.98, 0.96))):
            return True
        return claim is not None and self._assignment_claim_enabled(scene, claim) is False

    def assignments(self) -> TaskResult:
        scene = self._snapshot()
        if not scene.has("委托", TITLE):
            scene = self._open_phone_item("委托", "委托", "phone_assignments")
        claimed = 0
        persistent = self._persistent_assignments(scene)
        # New continuous assignments aggregate all dispatched rewards into one
        # claim. Keep the existing selections; never open material tabs or the
        # change-assignment control to make the task appear complete.
        for _ in range(12):
            scene = self._snapshot()
            dismissed = self._dismiss_reward(scene)
            if dismissed is not scene:
                continue
            if not scene.has("委托", TITLE):
                return self._result("assignments", "partial", "委托奖励弹窗的关闭按钮未识别，已停止。", scene)
            if persistent:
                if self._assignment_settled(scene):
                    current, total = self._assignment_count(scene)
                    detail = "已收取持续委托奖励" if claimed else "持续委托暂无可收取奖励"
                    return self._result("assignments", "ok", f"{detail}；复核{current}/{total}委托持续进行中。", scene)
                if claimed:
                    # A still-yellow button may be a delayed animation. Observe
                    # again, never issue a second collection click in this run.
                    try:
                        scene = self._wait(self._assignment_settled, timeout=15, description="复核持续委托奖励已收取")
                    except (Stopped, FocusLost):
                        raise
                    except AutomationError:
                        return self._result("assignments", "partial", "已点击一次持续委托领奖，但尚未核实无可领取奖励；保留原委托。", scene)
                    continue
                claim = scene.find("领取奖励", (0.65, 0.78, 0.97, 0.96), exact=True)
                if claim is None or self._assignment_claim_enabled(scene, claim) is not True:
                    return self._result("assignments", "partial", "未能确认持续委托领奖按钮已启用，保留原委托。", scene)
                self._click(scene, claim)
                claimed += 1
                continue
            claim = scene.find(("领取奖励", "全部领取", "一键领取"), BOTTOM, exact=True)
            if claim is not None and claimed == 0:
                after = self._click(scene, claim)
                if normalize(after.text) == normalize(scene.text):
                    after = self._wait(lambda s: normalize(s.text) != normalize(scene.text), description="确认委托领奖结果")
                claimed += 1
                continue
            ongoing = scene.find(("委托派遣中", "派遣中"), BOTTOM, exact=True)
            if ongoing is not None:
                return self._result("assignments", "ok", f"委托派遣中；已领奖{claimed}次，保留原委托。", scene)
            if scene.has(("派遣", "选择角色", "再次派遣", "重新派遣", "变更委托"), BOTTOM, exact=True):
                return self._result("assignments", "partial", "委托需要派遣配置或尚未核实奖励状态，保留原委托。", scene)
            return self._result("assignments", "partial", "未识别到可领奖或派遣中状态，无法确认委托完成。", scene)
        return self._result("assignments", "partial", "委托界面连续变化超过重试上限，保留截图等待检查。", scene)

    def _calyx(self, scene: Scene) -> bool:
        category = category_for(self.settings)
        title = "拟造花萼" if category.key.startswith("calyx_") else category.label
        button = "开始挑战" if category.key == "planar" else "挑战"
        return scene.has(title, TITLE) and scene.has(button, BOTTOM, exact=True)

    def _team_page(self, scene: Scene) -> bool:
        if category_for(self.settings).key == "planar":
            return self._calyx(scene) and scene.has("下载角色", (.30,.60,.55,.78), exact=True)
        return scene.has("队伍", TITLE) and scene.has("开始挑战", BOTTOM, exact=True)

    def _calyx_target(self, scene: Scene) -> bool:
        location = getattr(self.settings, "target_location", "").strip()
        if not self._calyx(scene) or not scene.has(self.settings.target_name):
            return False
        # Current details omit the map name. Only a map observed beside the
        # clicked guide entry may supply that missing part of the identity.
        if self._calyx_location is not None:
            return not location or normalize(location) in normalize(self._calyx_location)
        return bool(location and scene.has(location))

    def _guide_target_row(self, scene: Scene):
        """Bind name, map and entry control to one complete visible mission row."""
        target = normalize(self.settings.target_name)
        location = normalize(getattr(self.settings, "target_location", ""))
        names = sorted([t for t in scene.tokens if t.within((0.35, 0.25, 0.72, 0.84))
                        and target in normalize(t.text)], key=lambda t: t.center[1])
        buttons = [t for t in scene.tokens if t.within((0.72, 0.25, 0.89, 0.84))
                   and normalize(t.text) in ("进入", "传送", "前往")]
        rows = []
        for name in names:
            entries = [t for t in buttons if t.center[0] > name.center[0]
                       and abs(t.center[1] - name.center[1]) < 0.04]
            places = [t for t in scene.tokens if t.within((0.40, 0.25, 0.72, 0.84))
                      and 0.012 < t.center[1] - name.center[1] < 0.065
                      and re.search(r"[\u4e00-\u9fff]", t.text)
                      and normalize(t.text) not in (target, "基础掉落", "进入", "前往", "传送")]
            if location:
                places = [t for t in places if location in normalize(t.text)]
            if len(entries) == 1 and len(places) == 1:
                rows.append((name, places[0], entries[0]))
        if location and len(rows) != 1:
            return None
        if not location and len(rows) > 1:
            raise AutomationError("同名花萼有多个地点，请填写明确地点后再开始；未消耗开拓力。")
        return rows[0] if rows else None

    def _open_calyx(self) -> Scene:
        if self.settings.dungeon_category != "auto":
            from .dungeon_workflow import open_dungeon
            return open_dungeon(self)
        scene = self._snapshot()
        if self._calyx_target(scene):
            return scene
        self._calyx_location = None
        scene = self._open_guide("生存索引")
        category = "拟造花萼（金）" if self.settings.target_name in ("回忆之蕾", "以太之蕾", "藏珍之蕾") else "拟造花萼（赤）"
        category_token = scene.find(category, (0.13, 0.25, 0.36, 0.84), exact=True)
        if category_token is None:
            raise AutomationError(f"生存索引中未识别到{category}分类。")
        scene = self._click(scene, category_token)
        for _ in range(8):
            if not self._tab(scene, "生存索引"):
                raise AutomationError("选择分类后未确认仍在生存索引。")
            row = self._guide_target_row(scene)
            if row is not None:
                break
            self.ctx.move(scene, (0.72, 0.56))
            self.ctx.scroll(-360)
            self._pause()
            scene = self._snapshot()
        else:
            raise AutomationError(f"滚动后仍未找到目标花萼：{self.settings.target_name}。")
        self.ctx.log(f"选择花萼：{row[0].text}，地点：{row[1].text}。")
        self._click(scene, row[2])
        scene = self._wait(lambda s: self._calyx(s) and s.has(self.settings.target_name),
                           timeout=45, description="验证指南所选花萼关卡")
        self._calyx_location = row[1].text
        self.ctx.evidence(scene, "calyx_guide_target_verified")
        return scene

    @staticmethod
    def _cost(scene: Scene) -> int | None:
        # The cost is next to the challenge button, distinct from the top-right
        # available stamina counter and the challenge-count slider.
        values = []
        for token in scene.tokens:
            if token.within((0.61, 0.87, 0.79, 0.97)):
                text = normalize(token.text)
                match = re.fullmatch(r"(?:[×x*]|消耗|预计消耗|开拓力)*\s*(\d{1,3})", text)
                if match:
                    value = int(match.group(1))
                    if 10 <= value <= 240 and value % 10 == 0:
                        values.append(value)
        return values[0] if len(values) == 1 else None

    @staticmethod
    def _available(scene: Scene) -> int | None:
        values = []
        for token in scene.tokens:
            if token.within((0.70, 0, 0.94, 0.14)):
                match = re.fullmatch(r"(\d{1,3})\s*/\s*(\d{2,3})\s*[|丨+＋]*", token.text.strip())
                if match and 100 <= int(match.group(2)) and 0 <= int(match.group(1)) <= int(match.group(2)):
                    values.append(int(match.group(1)))
        return values[0] if len(values) == 1 else None

    @staticmethod
    def _round_count(scene: Scene) -> int | None:
        values = []
        for token in scene.tokens:
            if not token.within((0.58, 0.70, 0.94, 0.87)):
                continue
            text = normalize(token.text)
            match = re.fullmatch(r"(?:挑战次数|挑战轮数)(\d{1,2})", text)
            if match and 1 <= int(match.group(1)) <= 24:
                values.append(int(match.group(1)))
        if values:
            return values[0] if len(values) == 1 else None
        label = scene.find(("挑战次数", "挑战轮数"), (0.58, 0.70, 0.94, 0.87), exact=True)
        if label is None:
            return None
        # The selected-count control is above the cost and challenge buttons.
        # Never reuse the cost's OCR text as a second piece of evidence.
        for token in scene.tokens:
            if (token.within((0.79, 0.75, 0.89, 0.84))
                    and abs(token.center[1] - label.center[1]) < 0.04
                    and token.center[0] > label.center[0]):
                match = re.fullmatch(r"\d{1,2}", token.text.strip())
                if match and 1 <= int(match.group()) <= 24:
                    values.append(int(match.group()))
        return values[0] if len(values) == 1 else None

    def _limit_batch(self, scene: Scene, remaining: int) -> tuple[Scene, int]:
        category = category_for(self.settings)
        unit = category.cost
        desired = min(remaining, min(self.settings.rounds, category.batch) * unit)
        if category.weekly_limit and getattr(self, "_weekly_rewards", None) is not None:
            desired = min(desired, self._weekly_rewards * unit)
        available = self._available(scene)
        if available is not None:
            desired = min(desired, available // unit * unit)
        if desired < unit:
            return scene, 0
        if self._round_count(scene) is None and not category.key.startswith("calyx_"):
            if not self._calyx(scene) or self._cost(scene) != unit:
                raise AutomationError(f"未核实{category.label}单次消耗{unit}开拓力，未开始挑战。")
            if available is None:
                raise AutomationError("未能独立核实当前开拓力，未开始挑战。")
            return scene, unit
        for _ in range(24):
            if not self._calyx(scene):
                raise AutomationError("调整次数前未识别到目标副本挑战页。")
            cost = self._cost(scene)
            if cost is None:
                raise AutomationError("未能唯一识别副本预计消耗开拓力，已禁止开始挑战。")
            rounds = self._round_count(scene)
            if rounds is None or cost != rounds * unit:
                raise AutomationError(f"副本挑战次数与预计消耗未能独立核对为每次{unit}开拓力，已禁止开始挑战。")
            if cost == desired:
                return scene, cost
            if cost < desired:
                plus = scene.find(("+", "＋"), (0.93, 0.74, 0.99, 0.85), exact=True)
                if plus is None:
                    self.ctx.log(f"未确认增加次数按钮，按已核实{rounds}轮、{cost}开拓力挑战。")
                    return scene, cost
                self._click(scene, plus)
                scene = self._wait(lambda s: self._calyx(s) and self._cost(s) == cost + unit
                                   and self._round_count(s) == rounds + 1,
                                   description="双重验证挑战次数增加")
                continue
            minus_roi = (.74,.78,.80,.86) if category.key == "planar" else (0.61, 0.74, 0.69, 0.85)
            minus = scene.find(("−", "-", "－"), minus_roi, exact=True)
            if minus is None:
                minus = self._icon(scene, "count_minus", minus_roi)
            if minus is None:
                raise AutomationError("本次挑战消耗超过限制，且未识别到减少次数按钮。")
            before = cost
            self._click(scene, minus)
            scene = self._wait(lambda s: self._calyx(s) and self._cost(s) == before - unit
                               and self._round_count(s) == rounds - 1,
                               description="双重验证挑战次数减少")
        raise AutomationError("调整挑战次数超过上限。")

    @staticmethod
    def _insufficient(scene: Scene) -> bool:
        return replenishment_dialog(scene)

    def _quick_refill_state(self, scene: Scene):
        if not self._calyx(scene):
            return None, None
        label = scene.find("快捷补充开拓力", (0.80, 0.69, 0.97, 0.82), exact=True)
        if label is None or scene.image is None:
            return None, None
        import cv2
        import numpy as np

        # Bind the switch to its observed page and label. Its interior is
        # translucent and varies with the animated background, so the track
        # outline and a single round knob establish the disabled state.
        height, width = scene.image.shape[:2]
        y = label.center[1]
        x1, x2 = label.box[2] + 0.007, label.box[2] + 0.039
        if not (0.93 <= x1 < x2 <= 0.99 and 0.69 < y - 0.014 < y + 0.014 < 0.82):
            return None, None
        patch = cv2.cvtColor(scene.image[round((y - 0.014) * height):round((y + 0.014) * height),
                                             round(x1 * width):round(x2 * width)], cv2.COLOR_BGR2HSV)
        if patch.size == 0:
            return None, None
        gold = ((patch[:, :, 0] >= 12) & (patch[:, :, 0] <= 40)
                & (patch[:, :, 1] >= 100) & (patch[:, :, 2] >= 170))
        white = (patch[:, :, 1] < 65) & (patch[:, :, 2] >= 180)
        neutral_border = ((patch[:, :, 1] < 100) & (patch[:, :, 2] >= 45)
                          & (patch[:, :, 2] < 180))
        half = patch.shape[1] // 2
        left_knob = float(np.mean(white[:, :half]))
        right_knob = float(np.mean(white[:, half:]))
        gold_fraction = float(np.mean(gold))
        center = ((x1 + x2) / 2, y)
        _, _, blobs, centroids = cv2.connectedComponentsWithStats(white.astype(np.uint8))
        candidates = [(blob, centroid) for blob, centroid in zip(blobs[1:], centroids[1:])
                      if blob[cv2.CC_STAT_AREA] > patch.shape[0] * patch.shape[1] * 0.06]
        if len(candidates) != 1:
            return None, center
        blob, centroid = candidates[0]
        knob_width, knob_height = blob[cv2.CC_STAT_WIDTH], blob[cv2.CC_STAT_HEIGHT]
        roundness = blob[cv2.CC_STAT_AREA] / (knob_width * knob_height)
        if (not 0.75 <= knob_width / knob_height <= 1.25 or not 0.55 <= roundness <= 0.88
                or not 0.35 <= centroid[1] / patch.shape[0] <= 0.65):
            return None, center
        knob_x = centroid[0] / patch.shape[1]
        if gold_fraction > 0.30 and right_knob > 0.25 and left_knob < 0.20 and knob_x > 0.55:
            return "on", center
        rows = np.mean(neutral_border[:, half:], axis=1)
        third = max(1, patch.shape[0] // 3)
        outline = (float(np.mean(neutral_border[:, half:])) > 0.04
                   and float(np.max(rows[:third])) > 0.35
                   and float(np.max(rows[-third:])) > 0.35)
        if (gold_fraction < 0.08 and outline and left_knob > 0.25
                and right_knob < 0.20 and knob_x < 0.45):
            return "off", center
        return None, center

    def _disable_quick_refill(self, scene: Scene) -> Scene:
        state, switch = self._quick_refill_state(scene)
        self.ctx.log(f"快捷补充开拓力识别状态：{state or '未确认'}。")
        if state == "off":
            return scene
        if state != "on" or switch is None:
            raise AutomationError("无法独立核实快捷补充开拓力已关闭，已禁止开始挑战。")
        self._click(scene, switch)
        scene = self._wait(lambda s: self._calyx(s) and self._quick_refill_state(s)[0] == "off",
                           timeout=15, description="验证快捷补充开拓力已关闭")
        self.ctx.log("已核实关闭快捷补充开拓力，后续只使用现有开拓力。")
        return scene

    def _cancel_insufficient(self, scene: Scene) -> Scene:
        target = scene.find("取消", BOTTOM, exact=True)
        if target is not None:
            self._click(scene, target)
            return self._wait(lambda s: not self._insufficient(s), description="关闭开拓力补充提示")
        raise AutomationError("已发现开拓力补充提示，但取消按钮无法识别，已停止操作。")

    @staticmethod
    def _support_picker(scene: Scene) -> bool:
        return (scene.has("角色列表", (0.015, 0.045, 0.30, 0.11), exact=True)
                and scene.has("支援角色", (0.015, 0.045, 0.30, 0.11), exact=True)
                and scene.has("确认", (0.70, 0.85, 0.99, 1), exact=True))

    @staticmethod
    def _support_friend_rows(scene: Scene):
        rows = []
        badges = sorted([t for t in scene.tokens if t.within((0.235, 0.16, 0.29, 0.86))
                         and normalize(t.text) == "好友"], key=lambda t: t.center[1])
        for badge in badges:
            levels = [t for t in scene.tokens if t.within((0.02, 0.22, 0.085, 0.89))
                      and 0.06 < t.center[1] - badge.center[1] < 0.095
                      and re.fullmatch(r"等级[1-9]\d?", normalize(t.text))]
            if len(levels) != 1:
                continue
            # Bind the card's nickname to the badge row; never use it as an
            # input target. The filter label is outside this card region.
            names = [t for t in scene.tokens if t.within((0.08, 0.16, 0.235, 0.86))
                     and abs(t.center[1] - badge.center[1]) < 0.025
                     and re.search(r"[\w\u4e00-\u9fff]", t.text)]
            if len(names) != 1:
                continue
            nickname = names[0].text.strip("★ ")
            rows.append((badge, levels[0], nickname))
        return rows

    @staticmethod
    def _support_marker(scene: Scene) -> bool:
        if scene.image is None:
            return False
        region = (.31,.70,.52,.81) if scene.has("位面饰品提取", TITLE) else (0.32, 0.12, 0.98, 0.80)
        labels = [t for t in scene.tokens if t.within(region)
                  and normalize(t.text) == "支援"]
        if len(labels) != 1:
            return False
        import cv2
        import numpy as np

        height, width = scene.image.shape[:2]
        token = labels[0]
        x1, y1, x2, y2 = token.box
        if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
            return False
        patch = cv2.cvtColor(scene.image[round(y1 * height):round(y2 * height),
                                        round(x1 * width):round(x2 * width)], cv2.COLOR_BGR2HSV)
        if patch.size == 0:
            return False
        green = ((patch[:, :, 0] >= 35) & (patch[:, :, 0] <= 95)
                 & (patch[:, :, 1] >= 65) & (patch[:, :, 2] >= 80))
        return float(np.mean(green)) > 0.15

    @staticmethod
    def _support_full(scene: Scene) -> bool:
        return scene.has("队伍角色已满", (0.25, 0.20, 0.75, 0.40), exact=True)

    def _support(self, scene: Scene) -> Scene:
        if category_for(self.settings).key == "planar":
            return self._planar_support(scene)
        if not self._team_page(scene):
            raise AutomationError("支援入口前未验证队伍页和开始挑战按钮，已停止。")
        support = scene.find("支援", BOTTOM, exact=True)
        if support is None:
            raise AutomationError("启用了支援角色，但未识别到队伍页的支援按钮。")
        self._click(scene, support)
        scene = self._wait(self._support_picker, description="等待新版支援角色页")
        self.ctx.evidence(scene, "support_picker_initial")
        if self._support_marker(scene):
            raise AutomationError("支援页已有支援标记，但未核实其对应的好友卡片，已停止确认。")
        rows = self._support_friend_rows(scene)
        if not rows:
            raise AutomationError("未识别到好友徽标、昵称与等级对应的完整支援卡片，已停止本次挑战。")
        if self._support_full(scene):
            raise AutomationError("支援页已有未归属本次选择的满员提示，已停止选择。")
        candidates = rows[:6]
        for index, candidate in enumerate(candidates, 1):
            scene = self._snapshot()
            if not self._support_picker(scene) or self._support_marker(scene) or self._support_full(scene):
                raise AutomationError("好友选择前页面或反馈发生未验证变化，已停止本次挑战。")
            current = [row for row in self._support_friend_rows(scene)
                       if abs(row[0].center[1] - candidate[0].center[1]) < 0.02
                       and normalize(row[1].text) == normalize(candidate[1].text)
                       and normalize(row[2]) == normalize(candidate[2])]
            if len(current) != 1:
                raise AutomationError("下一张好友卡片的昵称、等级或位置已变化，已停止选择。")
            selected = current[0]
            self.ctx.log(f"选择已核实好友卡片{index}/{len(candidates)}，昵称：{selected[2]}。")
            # The badge is part of this card, not a tab or friend-only filter.
            scene = self._click(scene, selected[0])
            self.ctx.evidence(scene, f"support_picker_candidate_{index}_after_select")
            feedback = lambda s: self._support_picker(s) and (self._support_marker(s) or self._support_full(s))
            # _click already captured the first post-input frame. A transient
            # full-team toast may disappear during OCR of a second capture.
            if not feedback(scene):
                scene = self._wait(feedback, timeout=15, description="验证好友支援或明确队伍满员反馈")
            if self._support_marker(scene) and not self._support_full(scene):
                break
            if self._support_marker(scene):
                raise AutomationError("支援与满员反馈同时出现，无法核实本次选择，已停止。")
            self.ctx.evidence(scene, f"support_picker_candidate_{index}_team_full")
            self.ctx.log(f"好友卡片{index}反馈队伍角色已满。")
            if index == len(candidates):
                raise AutomationError("可见好友卡片均反馈队伍角色已满；请手动预留一个队伍空位后重试。")
            # A lingering toast cannot authorize skipping a subsequent card.
            scene = self._wait(lambda s: self._support_picker(s) and not self._support_full(s),
                               timeout=10, description="等待本张好友的满员提示消失")
            if self._support_marker(scene):
                raise AutomationError("满员提示后出现未归属下一选择的支援标记，已停止。")
        else:
            raise AutomationError("未能验证好友支援，已停止本次挑战。")
        self.ctx.evidence(scene, "support_picker_selection_verified")
        confirm = scene.find("确认", (0.7, 0.85, 0.99, 1), exact=True)
        if confirm is None:
            raise AutomationError("未识别到支援入队确认，已停止本次挑战。")
        self._click(scene, confirm)
        scene = self._wait(lambda s: self._team_page(s)
                           and self._support_marker(s), timeout=15, description="验证队伍中的绿色支援标记")
        self.ctx.evidence(scene, "support_team_verified")
        return scene

    @staticmethod
    def _planar_picker(scene):
        return (scene.has("支援列表", TITLE, exact=True)
                and scene.has("刷新列表", BOTTOM, exact=True)
                and scene.has("下载角色", (.30,.60,.55,.78), exact=True)
                and scene.has("开始挑战", BOTTOM, exact=True))

    def _planar_support(self, scene):
        if not self._team_page(scene):
            raise AutomationError("饰品提取支援前未核实已有存档准备页。")
        self.ctx.move(scene,(.60,.60))
        self._pause()
        scene = self._snapshot()
        support = scene.find("支援", BOTTOM, exact=True)
        if support is None:
            remove = scene.find("解除支援", BOTTOM, exact=True)
            if remove is not None and self._planar_marker(scene):
                # Clear only the borrowed role, then bind a freshly observed
                # friend card. The saved own-team and build are not edited.
                scene = self._click(scene, remove)
                self.ctx.move(scene,(.60,.60))
                self._pause()
                scene = self._wait(lambda s:self._team_page(s) and s.has("支援",BOTTOM,exact=True)
                                   and not self._planar_marker(s),description="核实旧借用支援已解除")
                support = scene.find("支援",BOTTOM,exact=True)
        if support is None:
            raise AutomationError("未识别到饰品提取支援入口。")
        self._click(scene, support)
        scene = self._wait(self._planar_picker, description="等待饰品提取支援列表")
        rows = self._support_friend_rows(scene)
        if not rows:
            raise AutomationError("饰品提取未核实完整好友卡片，未选择支援。")
        if self._planar_marker(scene):
            selected = []
            for row in rows:
                slot = self.ctx.planar_friend_slot(scene,row[0]) if hasattr(self.ctx,"planar_friend_slot") else None
                if slot:
                    center = (.337,.3865,.437,.4855)[slot-1]
                    if scene.has("支援",(center-.012,.78,center+.012,.805),exact=True):
                        selected.append(row)
            if len(selected) != 1:
                raise AutomationError("已有支援标记，但未核实其对应的好友卡片槽位。")
            self.ctx.evidence(scene,"planar_selected_friend_verified")
            scene = self._press("esc")
            return self._wait(lambda s:self._team_page(s) and self._planar_marker(s),description="核实已有好友支援")
        for candidate in rows[:6]:
            if not self._planar_picker(scene):
                raise AutomationError("饰品提取支援列表已变化。")
            current = [row for row in self._support_friend_rows(scene)
                       if abs(row[0].center[1]-candidate[0].center[1]) < .02
                       and normalize(row[1].text) == normalize(candidate[1].text)
                       and normalize(row[2]) == normalize(candidate[2])]
            if len(current) != 1:
                raise AutomationError("饰品提取好友卡片发生变化，未继续选择。")
            self.ctx.evidence(scene, "planar_friend_before")
            scene = self._click(scene, current[0][0])
            feedback = lambda s: (self._team_page(s) and self._planar_marker(s)) or (self._planar_picker(s) and (self._planar_marker(s) or self._support_full(s)))
            if not feedback(scene):
                scene = self._wait(feedback, timeout=15, description="核实饰品提取好友支援反馈")
            if self._support_full(scene):
                continue
            if self._planar_picker(scene):
                scene = self._press("esc")
            scene = self._wait(lambda s: self._team_page(s) and self._planar_marker(s),
                               timeout=15, description="核实饰品提取已借用支援")
            self.ctx.evidence(scene, "planar_friend_verified")
            return scene
        raise AutomationError("可见好友均反馈队伍已满，饰品提取未开始。")

    def _planar_marker(self, scene):
        if hasattr(self.ctx,"refine_planar_support"):
            self.ctx.refine_planar_support(scene)
        return self._support_marker(scene)

    def _auto_state(self, scene: Scene):
        roi = (0.85, 0, 0.94, 0.13)
        on = self._icon(scene, "auto_battle_on", roi)
        if on is not None:
            return "on", on
        off = self._icon(scene, "auto_battle_off", roi)
        if off is not None:
            return "off", off
        anchor = self._icon(scene, "auto_anchor", roi, threshold=0.82)
        if anchor is None or scene.image is None:
            from .du_navigation import auto_state
            return auto_state(scene)
        # The auto control has a lit rectangular frame when active. Evaluate
        # that frame only after matching the icon, never its position alone.
        import cv2
        import numpy as np

        image = scene.image
        height, width = image.shape[:2]
        x, y = anchor
        half_w, half_h = width * 35 / 1280, height * 18 / 720
        left, right = round(x * width - half_w), round(x * width + half_w)
        top, bottom = round(y * height - half_h), round(y * height + half_h)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            return None, None
        patch = cv2.cvtColor(image[top:bottom, left:right], cv2.COLOR_BGR2GRAY)
        inset = max(1, patch.shape[1] // 12)
        row_values = np.mean(patch[:, inset:-inset], axis=1)
        quarter = max(2, len(row_values) // 4)
        middle = float(np.median(row_values[quarter:-quarter]))
        top_edge = float(np.max(row_values[:quarter])) - middle
        bottom_edge = float(np.max(row_values[-quarter:])) - middle
        if min(top_edge, bottom_edge) >= 25:
            return "on", anchor
        if max(top_edge, bottom_edge) < 14:
            return "off", anchor
        return None, anchor

    def _enable_auto(self, scene: Scene) -> bool:
        state, target = self._auto_state(scene)
        if state == "on":
            return True
        if state != "off" or target is None:
            return False
        self._click(scene, target)
        self._wait(lambda s: self._auto_state(s)[0] == "on" or s.has(("挑战成功", "战斗失败")), timeout=15, description="验证自动战斗已开启")
        return True

    def _battle_result(self) -> Scene:
        elapsed = 0.0
        unknown_auto = 0.0
        while elapsed < self.settings.battle_timeout:
            started = time.monotonic()
            inactive_before = getattr(getattr(self.ctx, "runner", None), "inactive_duration", 0)
            scene = self._snapshot()
            if self._settlement(scene):
                return scene
            if self._insufficient(scene):
                return scene
            if self._enable_auto(scene):
                unknown_auto = 0.0
            elif self._in_battle(scene):
                unknown_auto += 2
                if unknown_auto >= 30:
                    raise AutomationError("无法核实自动战斗开关状态，已停止自动输入；请查看本次战斗截图。")
            elapsed += max(0, time.monotonic() - started -
                           (getattr(getattr(self.ctx, "runner", None), "inactive_duration", 0) - inactive_before))
            self.ctx.sleep(2)
            elapsed += 2
        raise AutomationError("等待战斗超时；未确认挑战成功，已停止后续挑战。")

    def _enter_planar_battle(self):
        from .planar_entry import field_ready, require_field, incomplete_team
        ready = lambda s: field_ready(s) or self._in_battle(s) or self._settlement(s) or incomplete_team(s)
        scene = self._wait(ready,timeout=60,description="等待饰品首领现场或战斗")
        if incomplete_team(scene):
            self.ctx.evidence(scene,'planar_incomplete_team')
            self._click(scene,scene.find('取消',(.28,.58,.49,.67),exact=True))
            self._wait(self._team_page,description='取消空位队伍出战')
            raise AutomationError('饰品提取队伍有空位，已取消出战；请补齐队伍后继续。')
        for attempt in range(4):
            if not field_ready(scene):
                return
            self.ctx.log(f"饰品提取接战：第{attempt+1}次短距离接近首领。")
            self.ctx.planar_approach(scene)
            scene = self._snapshot()
            if not field_ready(scene):
                return
            require_field(scene)
            anchor = self._icon(scene,"planar_attack_mouse",(.85,.80,.92,.90),threshold=.85)
            if anchor is None:
                raise AutomationError("未匹配饰品首领现场普通攻击的鼠标提示，未攻击。")
            target = (anchor[0]-.014,anchor[1]+.030)
            self._click(scene,target)
            for _ in range(5):
                self.ctx.sleep(1)
                scene = self._snapshot()
                if self._in_battle(scene) or self._settlement(scene):
                    self.ctx.evidence(scene,"planar_battle_entered")
                    return
                if not field_ready(scene):
                    scene = self._wait(ready,timeout=30,description="核实饰品接战转换")
                    if not field_ready(scene):
                        return
        raise AutomationError("饰品首领接战达到四次上限，保留待核对预算，不重放开始挑战。")

    @staticmethod
    def _settlement(scene: Scene) -> bool:
        return scene.has(("挑战成功", "战斗失败"), (0.25, 0.10, 0.75, 0.50), exact=True)

    @staticmethod
    def _settlement_count(scene: Scene) -> int | None:
        values = []
        for token in scene.tokens:
            if token.within((.20,.40,.80,.90)):
                match = re.fullmatch(r"(?:上轮挑战波次|本次挑战波次|挑战波次)([1-6])", normalize(token.text))
                if match:
                    values.append(int(match.group(1)))
        return values[0] if len(values) == 1 else None

    def _exit_result(self, scene: Scene) -> None:
        if not self._settlement(scene):
            raise AutomationError("未核实成功或失败结算页面，已停止退出输入。")
        target = scene.find("退出关卡", BOTTOM, exact=True)
        if target is None:
            self.ctx.log("已核实战斗结算，等待退出关卡按钮就绪。")

            def exit_ready(current: Scene) -> bool:
                if not self._settlement(current):
                    raise AutomationError("等待退出按钮时结算页面已无法核实，已停止输入。")
                return current.has("退出关卡", BOTTOM, exact=True)

            scene = self._wait(exit_ready, timeout=30, description="等待结算退出关卡按钮就绪")
            target = scene.find("退出关卡", BOTTOM, exact=True)
        self.ctx.evidence(scene, "battle_result_exit_ready")
        self._click(scene, target)
        self._wait(lambda s: not s.has(("挑战成功", "战斗失败", "退出关卡", "再来一次")), description="确认退出关卡")

    def battle(self) -> TaskResult:
        if not getattr(self.settings, "allow_stamina_spend", False):
            return self._result("battle", "skipped", "尚未授权消耗开拓力，刷本任务已跳过。")
        if not self._snapshot().tokens:
            raise AutomationError("画面中没有可识别文字，无法选择花萼。")
        category = category_for(self.settings)
        requested = self.settings.challenge_count
        if category.weekly_limit:
            requested = min(requested or category.weekly_limit, category.weekly_limit)
        self.ctx.report.battle_requested = requested
        completed = self.ctx.report.battle_completed
        while (self.ctx.report.stamina_spent + category.cost <= self.settings.stamina_limit
               and (requested is None or completed < requested)):
            scene = self._open_calyx()
            scene = self._disable_quick_refill(scene)
            remaining = self.settings.stamina_limit - self.ctx.report.stamina_spent
            if requested is not None:
                remaining = min(remaining, (requested - completed) * category.cost)
            scene, cost = self._limit_batch(scene, remaining)
            if cost == 0:
                return self._result("battle", "partial", f"可用开拓力不足{category.cost}，停止刷本；已完成{completed}次，确认消耗{self.ctx.report.stamina_spent}。", scene)
            self.ctx.log(f"挑战前复核：消耗{cost}，轮数{self._round_count(scene)}，可用开拓力{self._available(scene)}。")
            if category.key != "planar":
                challenge = scene.find("挑战", BOTTOM, exact=True)
                if challenge is None:
                    raise AutomationError("未识别到副本挑战按钮。")
                self._click(scene, challenge)
                scene = self._wait(lambda s: self._insufficient(s) or s.has("开始挑战", BOTTOM, exact=True) or s.has(("阵亡", "无法挑战")), description="等待挑战队伍页")
            if self._insufficient(scene):
                self._cancel_insufficient(scene)
                return self._result("battle", "partial", f"开拓力不足，已取消补充；已确认消耗{self.ctx.report.stamina_spent}。", scene)
            if scene.has(("阵亡", "无法挑战")):
                return self._result("battle", "partial", "存在阵亡角色或无法挑战提示，需要手动调整队伍。", scene)
            if self.settings.use_support:
                scene = self._support(scene)
            if category.key == "planar":
                scene = self._disable_quick_refill(scene)
                scene, cost = self._limit_batch(scene, remaining)
                if not cost or (self.settings.use_support and not self._planar_marker(scene)):
                    raise AutomationError("饰品提取支援后的费用、次数或支援标记发生未核实变化。")
            start = scene.find("开始挑战", BOTTOM, exact=True)
            if start is None or not self._team_page(scene):
                raise AutomationError("未验证队伍页与开始挑战按钮。")
            budget = getattr(self.ctx, "battle_budget", None)
            if budget is not None:
                budget.reserve(cost)
            self._click(scene, start)
            if category.key == "planar":
                self._enter_planar_battle()
            scene = self._battle_result()
            if self._insufficient(scene):
                self._cancel_insufficient(scene)
                return self._result("battle", "partial", "开始挑战时开拓力不足，已取消补充。", scene)
            if scene.has("战斗失败", (0.25, 0.10, 0.75, 0.50)):
                self._exit_result(scene)
                return self._result("battle", "partial", "战斗失败，停止后续刷本；仅计入此前已确认成功的开拓力。", scene)
            if self.settings.dungeon_category != "auto" and cost > category.cost:
                if self._settlement_count(scene) is None:
                    self.ctx.log("已看到挑战成功，等待结算动画显示本批完成波次。")
                    scene = self._wait(lambda s: self._settlement(s) and self._settlement_count(s) is not None,
                                       timeout=30, description="结算波次显示")
                if self._settlement_count(scene) != cost // category.cost:
                    raise AutomationError("成功结算未独立核实本批完成波次，保留待核对消耗，不重复挑战。")
            # Accounting happens once, only after a visible success screen.
            completed += cost // category.cost
            self.ctx.report.battle_completed = completed
            if budget is not None:
                budget.confirm(cost)
            else:
                self.ctx.report.stamina_spent += cost
            self.ctx.evidence(scene, f"battle_success_{completed}")
            self.ctx.log(f"挑战成功，累计确认消耗{self.ctx.report.stamina_spent}开拓力。")
            self._exit_result(scene)
        status = "ok" if requested is None or completed == requested else "partial"
        return self._result("battle", status, f"已确认完成{completed}次{category.label}，消耗{self.ctx.report.stamina_spent}开拓力。")

    def _activity(self, scene: Scene) -> int | None:
        # Do not mistake the 500-point milestone label for current activity.
        if self._tab(scene, "每日实训"):
            badge_values = []
            for token in scene.tokens:
                if token.within((0.15, 0.30, 0.205, 0.36)):
                    match = re.fullmatch(r"\d{1,3}", token.text.strip())
                    if match and int(match.group()) <= 500:
                        badge_values.append(int(match.group()))
            if len(badge_values) == 1:
                value = badge_values[0]
                full_text = value == 500 and scene.has("本日活跃度已满", (0.14, 0.68, 0.89, 0.87))
                badge_icon = self._icon(scene, "daily_activity_badge", (0.13, 0.23, 0.225, 0.37), threshold=0.85)
                if full_text or badge_icon is not None:
                    return value
        for token in scene.tokens:
            if not token.within((0.12, 0.24, 0.91, 0.46)):
                continue
            text = normalize(token.text)
            match = re.fullmatch(r"(?:今日)?(?:活跃度|活跃值|活跃点数|活跃|实训活跃度)(\d{1,3})(?:/500)?", text)
            if not match:
                match = re.fullmatch(r"(\d{1,3})/500", text)
            if match:
                value = int(match.group(1))
                if 0 <= value <= 500:
                    return value
        # Some layouts split the label and its value into separate OCR tokens.
        label = scene.find(("活跃度", "活跃值", "活跃点数", "今日活跃", "实训活跃度"), (0.12, 0.24, 0.91, 0.46), exact=True)
        if label:
            candidates = []
            for token in scene.tokens:
                if token.center[0] >= label.center[0] and abs(token.center[1] - label.center[1]) < 0.025 and token.center[0] - label.center[0] < 0.14:
                    match = re.fullmatch(r"(\d{1,3})(?:\s*/\s*500)?", token.text.strip())
                    if match and int(match.group(1)) <= 500:
                        candidates.append(int(match.group(1)))
            if len(candidates) == 1:
                return candidates[0]
        return None

    def _rewards_complete(self, scene: Scene) -> bool:
        # Task-card "已领取" text below the reward bar is not milestone proof.
        text_marks = [t for t in scene.tokens if t.within(REWARDS) and normalize(t.text) == "已领取"]
        if (len(text_marks) == 5 and all(sum(t.within(slot) for t in text_marks) == 1 for slot in REWARD_SLOTS)
                and max(t.center[0] for t in text_marks) - min(t.center[0] for t in text_marks) > 0.4):
            return True
        matches = self._matches(scene, "daily_completed", REWARDS)
        return len(matches) == 5 and matches[-1][0] - matches[0][0] > 0.4

    def daily(self) -> TaskResult:
        self.ctx.report.daily_verified = False
        scene = self._open_guide("每日实训")
        for _ in range(12):
            scene = self._snapshot()
            dismissed = self._dismiss_reward(scene)
            if dismissed is not scene:
                continue
            if not self._tab(scene, "每日实训"):
                return self._result("daily", "partial", "实训奖励弹窗未识别，无法继续核实。", scene)
            claim = scene.find("领取", (0.14, 0.41, 0.88, 0.90), exact=True)
            if claim is None:
                break
            previous = normalize(scene.text)
            self._click(scene, claim)
            scene = self._wait(lambda s: normalize(s.text) != previous, description="确认领取实训任务点数")
            scene = self._dismiss_reward(scene)
        activity = self._activity(scene)
        self.ctx.report.engagement = activity
        if activity != 500:
            detail = "未能识别当前实训活跃值" if activity is None else f"实训活跃值为{activity}/500"
            return self._result("daily", "partial", f"{detail}，尚未确认每日任务完成。", scene)
        for _ in range(6):
            scene = self._snapshot()
            dismissed = self._dismiss_reward(scene)
            if dismissed is not scene:
                continue
            if self._tab(scene, "每日实训") and self._activity(scene) == 500 and self._rewards_complete(scene):
                self.ctx.report.daily_verified = True
                return self._result("daily", "ok", "已复核每日实训500活跃，五档奖励均已领取。", scene)
            if not self._tab(scene, "每日实训"):
                break
            gifts = self._matches(scene, "daily_reward", REWARDS)
            claim = scene.find(("领取", "领取奖励", "一键领取"), REWARDS, exact=True)
            target = gifts[-1][:2] if gifts else claim
            if target is None:
                break
            before = normalize(scene.text)
            after = self._click(scene, target)
            if normalize(after.text) == before and not self._rewards_complete(after):
                after = self._wait(lambda s: normalize(s.text) != before or self._rewards_complete(s), description="确认实训里程碑领奖")
            self._dismiss_reward(after)
        return self._result("daily", "partial", "已识别500活跃，但五档奖励的领取状态尚未核实；请采集奖励礼盒和完成图标模板。", scene)

    def mail(self) -> TaskResult:
        scene = self._open_phone_item("邮件", "邮件", "phone_mail")
        claim = scene.find("全部领取", BOTTOM, exact=True)
        if claim is None:
            if scene.has(("暂无邮件", "无可领取附件", "没有可领取的奖励")):
                return self._result("mail", "ok", "邮件没有可领取的附件。", scene)
            return self._result("mail", "partial", "未识别到全部领取按钮或无附件状态。", scene)
        after = self._click(scene, claim)
        after = self._dismiss_reward(after)
        if after.has(("暂无邮件", "无可领取附件", "没有可领取的奖励", "附件已领取")):
            return self._result("mail", "ok", "已核实邮件附件领取状态。", after)
        return self._result("mail", "partial", "已点击邮件全部领取，但尚未核实全部附件领取状态。", after)

    def battlepass(self) -> TaskResult:
        scene = self._open_phone_item("无名勋礼", "无名勋礼")
        if scene.has("开启无名勋礼"):
            return self._result("battlepass", "partial", "无名勋礼尚未开启，需要手动确认。", scene)
        claimed = 0
        for _ in range(6):
            scene = self._snapshot()
            if scene.has(("解锁无名客的荣勋", "购买", "支付", "选择奖励")):
                return self._result("battlepass", "partial", "勋礼出现购买或奖励选择界面，已停止。", scene)
            dismissed = self._dismiss_reward(scene)
            if dismissed is not scene:
                continue
            target = scene.find("一键领取", BOTTOM, exact=True)
            if target is None:
                if claimed and scene.has(("全部已领取", "无可领取奖励")):
                    return self._result("battlepass", "ok", "已核实当前勋礼页奖励领取完成。", scene)
                return self._result("battlepass", "partial", "未识别到勋礼可领取按钮或全部领取状态。", scene)
            after = self._click(scene, target)
            if normalize(after.text) == normalize(scene.text):
                return self._result("battlepass", "partial", "勋礼领取后画面没有确认变化，已停止重复点击。", after)
            claimed += 1
        return self._result("battlepass", "partial", "勋礼领取达到重试上限，尚未确认全部完成。", scene)
