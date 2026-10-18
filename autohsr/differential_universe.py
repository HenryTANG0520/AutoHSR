"""Screen-driven, evidence-backed Differential Universe runner.

Only current on-screen text, packaged UI templates, and fresh screenshots authorize
input. Shop and synthesis areas can be visited and exited; no purchase or synthesis
action is taken. Unknown pages and power/refill prompts stop with evidence intact.
"""
from __future__ import annotations

import time
import re
import uuid
import json
from pathlib import Path

from .models import AutomationError, Scene, TaskResult, Token, normalize
from .policy import has_du_field_plane_marker
from .workflows import DailyWorkflow


TASK = "differential_universe"
BLOCKED_TERMS = ("补充开拓力", "兑换开拓力", "使用燃料", "使用星琼", "星琼不足", "开拓力不足")
RESOURCE_BLOCK_TERMS = ("补充开拓力", "兑换开拓力", "使用燃料", "使用星琼", "星琼不足", "开拓力不足")
FIELD_ENEMY_TEMPLATES = (
    "du_field_enemy", "du_field_enemy_2", "du_field_enemy_3", "du_field_enemy_4",
    "du_field_enemy_5",
)
AREA_KINDS = ("战斗", "随机", "休整", "商店", "合成", "冒险", "事件", "奖励", "首领")
NAVIGATION_LABELS = (
    "继续", "下一步", "进入下一位面", "继续探索", "继续演算", "开始探索", "进入战斗",
    "开始演算", "开始挑战", "开始模拟", "启动「差分宇宙」", "启动差分宇宙",
    "返回差分宇宙", "返回差分宇宙主界面", "离开", "离开商店", "返回", "关闭",
)
FINAL_RETURN_LABELS = ("返回差分宇宙", "返回差分宇宙主界面", "返回", "确定")
FINAL_LABELS = ("模拟宇宙通关", "通关结算", "演算成功", "最终结算", "通关成功")


def is_battle_scene(scene: Scene, context=None) -> bool:
    """Use the same calibrated battle-pause anchor as the existing battle flow."""
    if scene.has(("战斗失败", "挑战成功", "挑战失败", "退出关卡", "再来一次", "战斗设置", "战斗胜利")):
        return True
    return DailyWorkflow(context)._in_battle(scene) if context is not None else False


def _text(scene: Scene) -> str:
    return normalize(scene.text)


def has_field_battle_marker(text: str) -> bool:
    """Recognize full battle labels or a truncated field label plus its live HUD."""
    context = normalize(text)
    if "战斗" in context:
        return True
    return bool(re.search(r"第[一二三四五六1-6]位面[-—]?战", context)
                and re.search(r"lv\s*\d+\s*/\s*20", context))


def classify_page(scene: Scene, context=None) -> str:
    text = _text(scene)
    if any(normalize(term) in text for term in RESOURCE_BLOCK_TERMS):
        return "blocked"
    if "点击空白处关闭" in text:
        return "tutorial_overlay"
    if "敷衍面具" in text and "获得愿力" in text:
        return "mask_reward_overlay"
    if scene.has("星阶模式说明"):
        return "rules_modal"
    if any(normalize(term) in text for term in map(normalize, FINAL_LABELS)):
        return "victory"
    if "战斗失败" in text or "模拟失败" in text:
        return "defeat"
    if "挑战成功" in text or "战斗胜利" in text:
        return "node_victory"
    if any(term in text for term in map(normalize, ("选择祝福", "请选择祝福", "选择一次祝福", "选择1次祝福"))):
        return "blessing_choice"
    if any(term in text for term in map(normalize, ("选择方程", "请选择方程", "方程选择"))):
        return "equation_choice"
    if any(term in text for term in map(normalize, ("选择奇物", "请选择奇物", "奇物选择"))):
        return "curio_choice"
    if ("选择下一站" in text
            and any(term in text for term in map(normalize, ("战斗", "异常", "铸造")))):
        return "station_choice"
    if ("面具效果" in text
            and scene.find(("确认选择", "确认", "确定"), (0.56, 0.78, 0.99, 0.98)) is not None):
        return "mask_detail"
    if any(term in text for term in map(normalize,
            ("选择一张面具", "选择你的面具", "选择面具"))):
        return "mask_choice"
    if any(term in text for term in map(normalize, ("选择你的奇迹", "选择奇迹"))):
        return "miracle_choice"
    is_route_map = "位面地图" in text or "探索进度" in text or "当前区域" in text
    if is_route_map:
        return "route"
    if any(term in text for term in map(normalize, ("选择区域", "区域选择", "抽取区域", "选择一个区域", "区域待选择"))):
        return "area_choice"
    if any(term in text for term in map(normalize, ("黑塔的商店", "商店"))):
        return "shop"
    if "合成" in text:
        return "synthesis"
    if any(term in text for term in map(normalize, ("休整区", "休息区", "休整区域"))):
        return "rest"
    if any(term in text for term in map(normalize, ("事件", "遭遇", "随机事件"))) and "区域-随机" not in text:
        return "event"
    if is_battle_scene(scene, context):
        return "battle"
    if has_du_field_plane_marker(text) and has_field_battle_marker(text):
        return "field_combat"
    if has_du_field_plane_marker(text) and "异常" in text:
        return "field_anomaly"
    if ("星阶模式" in text and "拓星模式" in text and "练习模式" in text
            and ("启动差分宇宙" in text or "启动" in text)):
        return "star_rank_setup"
    if "继续游戏" in text or "继续演算" in text:
        return "active_save"
    if "差分宇宙" in text and "乐园漫记" in text and "难度" in text and "进入星阶模式" in text:
        return "difficulty_setup"
    if ("差分宇宙" in text and "周期演算" in text and "难度" in text
            and any(term in text for term in map(normalize, ("启动差分宇宙", "启动「差分宇宙」")))):
        return "periodic_setup"
    if "模式选择" in text and "常规演算" in text and "周期演算" in text:
        return "mode_select"
    if "差分宇宙" in text and "乐园漫记" in text and "开始游戏" in text:
        return "home"
    if ("位面地图" in text or "探索进度" in text or ("位面" in text and "区域" in text
            and any(term in text for term in ("战斗", "随机", "选择", "待选择")))):
        return "route"
    if (("队伍" in text or "编队" in text)
            and any(term in text for term in ("开始演算", "开始挑战", "开始模拟", "确认出战"))):
        return "team_setup"
    if "差分宇宙" in text and "开始游戏" not in text and ("星阶模式" in text or "常规演算" in text):
        return "du_page"
    return "unknown"


class DifferentialUniverseWorkflow:
    def __init__(self, context, runs: int = 3, *, resume_active: bool = False,
                 periodic_rank: int | None = None):
        if isinstance(runs, bool) or not isinstance(runs, int) or not 1 <= runs <= 3:
            raise ValueError("差分宇宙局数必须是 1～3 的整数。")
        if type(resume_active) is not bool:
            raise ValueError("接续差分宇宙开关必须为布尔值。")
        if (periodic_rank is not None and
                (isinstance(periodic_rank, bool) or not isinstance(periodic_rank, int)
                 or not 1 <= periodic_rank <= 10 or not resume_active)):
            raise ValueError("周期演算接续难度必须是 1～10 的整数，且仅用于接续当前局。")
        self.ctx, self.settings, self.runs = context, context.settings, runs
        self.resume_active = resume_active
        self.periodic_rank = periodic_rank
        self.report = context.report.differential_universe
        self.report.update(requested_runs=runs, completed_runs=0, current_run=0,
                           mode="拓星模式 / 常规演算", season="乐园漫记",
                           actions=[], page_history=[], run_results=[],
                           stamina_budget_used=False, premium_currency_used=False,
                           fuel_used=False)
        self.session_id = str(uuid.uuid4())
        self.report["session_id"] = self.session_id
        self._daily = DailyWorkflow(context)
        self._pages = 0
        self._action_no = 0

    def _persist_ledger(self) -> None:
        root = self.report.get("run_dir")
        if not root:
            return
        path = Path(root) / "differential-universe-ledger.json"
        payload = {
            "schema_version": 1,
            "session_id": self.session_id,
            "updated_at": time.time(),
            "requested_runs": self.report["requested_runs"],
            "completed_runs": self.report["completed_runs"],
            "current_run": self.report["current_run"],
            "run_results": self.report["run_results"],
            "actions": self.report["actions"],
            "page_history": self.report["page_history"],
        }
        temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        self.report["ledger_path"] = str(path)

    def _observe(self, scene: Scene, label="page") -> str:
        self._pages += 1
        kind = classify_page(scene, self.ctx)
        evidence = self.ctx.evidence(scene, f"du_{self.report['current_run']:02d}_{self._pages:03d}_{label}")
        self.report["page_history"].append({"index": self._pages, "run": self.report["current_run"],
            "page_kind": kind, "evidence": str(evidence), "ocr_text": scene.text})
        self._persist_ledger()
        return kind

    def _snapshot(self, label="page") -> tuple[Scene, str]:
        self.ctx.checkpoint()
        scene = self.ctx._snapshot_after_du_input(timeout=20)
        return scene, self._observe(scene, label)

    def _click(self, scene: Scene, target: Token, *, intent="navigation", label="action") -> tuple[Scene, str]:
        self._action_no += 1
        self.report["actions"].append({"index": self._action_no, "run": self.report["current_run"],
            "action": target.text, "intent": intent, "status": "requested", "before_ocr": scene.text})
        self._persist_ledger()
        self.ctx.click(scene, target, du_intent=intent)
        current = self.ctx.last_scene
        if current is None:
            raise AutomationError("差分宇宙操作后未获得新截图。")
        kind = self._observe(current, label)
        self.report["actions"][-1].update(status="sent", after_ocr=current.text,
            after_evidence=self.report["page_history"][-1]["evidence"], after_page=kind)
        self._persist_ledger()
        if kind == "unknown":
            # The first entry can show a long loading animation and a tutorial.
            # Keep observing fresh frames; never guess a control during this wait.
            deadline = time.monotonic() + 60
            while kind == "unknown" and time.monotonic() < deadline:
                self.ctx.sleep(.7)
                current = self.ctx._snapshot_after_du_input(timeout=max(1, deadline - time.monotonic()))
                kind = self._observe(current, label + "_transition")
        return current, kind

    def _find(self, scene: Scene, labels, roi=(0, 0, 1, 1)) -> Token | None:
        for label in labels:
            found = scene.find(label, roi, exact=True)
            if found is not None:
                return found
        return None

    @staticmethod
    def _difficulty_options(scene: Scene) -> list[tuple[int, Token]]:
        roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
                 "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
        options = []
        for token in scene.tokens:
            value = normalize(token.text).replace("難度", "难度")
            match = re.fullmatch(r"难度([ivx]+|10|[1-9])", value)
            if not match:
                continue
            suffix = match.group(1).upper()
            rank = roman.get(suffix)
            if rank is None and suffix.isdigit():
                rank = int(suffix)
            if rank is not None and 1 <= rank <= 10:
                options.append((rank, token))
        # Duplicate OCR tokens for one card are collapsed by rank and position.
        unique = {}
        for rank, token in options:
            unique.setdefault(rank, token)
        return sorted(unique.items(), key=lambda item: item[0])

    @staticmethod
    def _displayed_difficulty_rank(scene: Scene) -> int | None:
        text = normalize(scene.text).replace(" ", "")
        matches = re.findall(r"难度([ivx]+|10|[1-9])", text)
        roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
                 "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
        if not matches:
            return None
        value = matches[-1].upper()
        return roman.get(value, int(value) if value.isdigit() else None)

    def _select_lowest_difficulty(self, scene: Scene) -> Scene:
        current = self._displayed_difficulty_rank(scene)
        before = self.ctx.evidence(scene, f"du_{self.report['current_run']:02d}_difficulty_before")
        if current != 1:
            match = self.ctx.template(scene, "du_difficulty_i", (0.015, 0.08, 0.12, 0.23), threshold=0.82)
            if not match or len(match) != 3 or match[2] < 0.82:
                raise AutomationError("未能通过最低难度 I 的专用界面图标模板定位该选项；未启动本局。")
            x, y, confidence = match
            target = Token("差分宇宙难度I", float(confidence), (x - 0.02, y - 0.02, x + 0.02, y + 0.02))
            scene, kind = self._click(scene, target, intent="difficulty_selection", label="minimum_difficulty")
            selected = self._displayed_difficulty_rank(scene)
            if selected != 1 or kind != "difficulty_setup":
                after = self.ctx.evidence(scene, f"du_{self.report['current_run']:02d}_difficulty_unverified")
                self.report["difficulty_selection"] = {
                    "requested_rank": 1, "verified": False, "before": str(before), "after": str(after),
                    "displayed_rank_after": selected, "template_confidence": confidence,
                }
                self._persist_ledger()
                raise AutomationError("选择最低难度后，页面未明确显示难度 I；本局未启动。")
        else:
            confidence = None
        after = self.ctx.evidence(scene, f"du_{self.report['current_run']:02d}_difficulty_i_verified")
        self.report["difficulty_selection"] = {
            "requested_rank": 1, "displayed_rank_before": current, "displayed_rank_after": 1,
            "verified": True, "before": str(before), "after": str(after),
            "template_confidence": confidence,
        }
        self._persist_ledger()
        return scene

    def _open_differential_universe(self, scene: Scene, kind: str) -> tuple[Scene, str]:
        if kind == "rules_modal":
            self._action_no += 1
            self.report["actions"].append({"index": self._action_no, "run": 0,
                "action": "close_star_rank_rules", "status": "sent", "before_ocr": scene.text})
            self.ctx.key("esc")
            scene, kind = self._snapshot("closed_rules")
        if kind in ("mode_select", "difficulty_setup", "star_rank_setup", "periodic_setup", "du_page", "home"):
            return scene, kind
        from .workflows import DailyWorkflow
        if not DailyWorkflow._phone(scene):
            scene = self._daily.ensure_main()
            kind = self._observe(scene, "phone_menu")
        if DailyWorkflow._phone(scene):
            target = scene.find("差分宇宙", (0.55, 0.25, 1, 1), exact=True)
            if target is None:
                raise AutomationError("手机菜单中未识别到差分宇宙入口。")
            scene, kind = self._click(scene, target, label="opened_du")
            deadline = time.monotonic() + 45
            while kind not in ("mode_select", "difficulty_setup", "star_rank_setup", "periodic_setup", "home", "du_page"):
                if time.monotonic() >= deadline:
                    raise AutomationError("打开差分宇宙后未识别到本赛季模式页。")
                self.ctx.sleep(.6)
                scene, kind = self._snapshot("open_transition")
        return scene, kind

    def _prepare_and_start(self, scene: Scene, kind: str) -> tuple[Scene, str]:
        scene, kind = self._open_differential_universe(scene, kind)
        for _ in range(8):
            self.ctx.checkpoint()
            if kind == "active_save":
                raise AutomationError("检测到未完成的差分宇宙存档；为保护现有进度，本次未继续。")
            if kind == "home":
                if scene.has(("继续", "继续游戏", "继续演算"), exact=True):
                    raise AutomationError("差分宇宙已有可继续进度，本次未触碰该存档。")
                start = self._find(scene, ("开始游戏", "开始演算"), (0.68, 0.72, 1, 1))
                if start is None:
                    raise AutomationError("差分宇宙主页没有已识别的开始按钮。")
                scene, kind = self._click(scene, start, label="mode_select")
                continue
            if kind == "mode_select":
                target = scene.find("常规演算", exact=True)
                if target is None:
                    raise AutomationError("模式选择页未识别到常规演算。")
                scene, kind = self._click(scene, target, label="normal_mode")
                continue
            if kind == "difficulty_setup":
                scene = self._select_lowest_difficulty(scene)
                target = scene.find("进入星阶模式", exact=True)
                if target is None:
                    raise AutomationError("常规演算配置页未识别到进入星阶模式按钮。")
                scene, kind = self._click(scene, target, label="star_rank_setup")
                continue
            if kind == "star_rank_setup":
                # Selecting 拓星模式 is a reversible tab choice; never select 练习模式.
                tab = scene.find("拓星模式", exact=True)
                if tab is None:
                    raise AutomationError("星阶模式页未识别到拓星模式标签。")
                scene, kind = self._click(scene, tab, label="expansion_mode")
                if kind != "star_rank_setup":
                    raise AutomationError("拓星模式选择后页面发生未知变化，未启动差分宇宙。")
                start = self._find(scene, ("启动「差分宇宙」", "启动差分宇宙"), (0.72, 0.82, 1, 0.98))
                if start is None:
                    raise AutomationError("拓星模式页未识别到启动按钮。")
                scene, kind = self._click(scene, start, label="run_started")
                if kind in ("blocked", "unknown", "star_rank_setup", "difficulty_setup", "mode_select"):
                    raise AutomationError(f"启动差分宇宙后页面未进入已知运行流程（{kind}）。")
                return scene, kind
            if kind == "periodic_setup":
                # The user selected this periodic challenge and its team in
                # game. Preserve those settings and record the visible rank.
                rank = self._displayed_difficulty_rank(scene)
                if rank is None:
                    raise AutomationError("周期演算页未能核实当前显示的难度；未启动。")
                if self.periodic_rank is not None and rank != self.periodic_rank:
                    raise AutomationError("周期演算页难度与接续参数不一致；未启动。")
                before = self.ctx.evidence(scene, f"du_{self.report['current_run']:02d}_periodic_setup")
                self.report["mode"] = "周期演算"
                self.report["difficulty_selection"] = {
                    "requested_rank": rank, "displayed_rank_before": rank,
                    "displayed_rank_after": rank, "verified": True,
                    "user_selected": True, "before": str(before),
                }
                self._persist_ledger()
                start = self._find(scene, ("启动「差分宇宙」", "启动差分宇宙"), (0.72, 0.82, 1, 0.98))
                if start is None:
                    raise AutomationError("周期演算页未识别到启动差分宇宙按钮。")
                scene, kind = self._click(scene, start, intent="periodic_start", label="periodic_run_started")
                if kind in ("blocked", "unknown", "periodic_setup", "mode_select", "difficulty_setup"):
                    raise AutomationError(f"启动周期演算后页面未进入已知运行流程（{kind}）。")
                return scene, kind
            if kind == "du_page":
                raise AutomationError("差分宇宙当前页面尚未建立安全导航规则；未继续输入。")
            raise AutomationError(f"差分宇宙页面未识别（{kind}），未发送输入。")
        raise AutomationError("差分宇宙启动流程超过已知页面数，已停止。")

    def _choice_target(self, scene: Scene, kind: str) -> Token | None:
        excluded = tuple(map(normalize, (
            "祝福", "方程", "奇物", "选择", "效果", "说明", "获得", "返回", "继续", "跳过",
            "确定", "确认",
            "黑塔的商店", "商店", "合成", "购买", "强化", "升级", "使用燃料", "星琼", "开拓力")))
        candidates = [t for t in scene.tokens if t.within((0.16, 0.18, 0.96, 0.84))
                      and normalize(t.text) and normalize(t.text) not in excluded
                      and not any(word in normalize(t.text) for word in map(normalize,
                          ("选择", "获得", "返回", "继续", "说明", "点击", "效果", "剩余")))
                      and not any(term in normalize(t.text) for term in map(normalize, BLOCKED_TERMS))]
        unsafe_cost_words = tuple(map(normalize, ("消耗", "花费", "花费", "碎片", "宇宙碎片", "星琼", "燃料", "开拓力", "购买", "兑换")))
        candidates = [t for t in candidates if not any(word in normalize(t.text) for word in unsafe_cost_words)]
        if not candidates:
            return None
        # The leftmost visible choice is deterministic; its card text is the click anchor.
        return min(candidates, key=lambda t: (t.center[0], t.center[1], -t.score))

    @staticmethod
    def _area_choice_target(scene: Scene) -> Token | None:
        import re
        pattern = re.compile(r"(?:区域[-— ]?(?:战斗|随机|休整|商店|合成|冒险|事件|奖励|首领)|"
                             r"(?:战斗|随机|休整|商店|合成|冒险|事件|奖励|首领)区域)")
        candidates = [token for token in scene.tokens
                      if pattern.fullmatch(normalize(token.text))
                      and token.within((0.12, 0.16, 0.98, 0.88))]
        if not candidates:
            return None
        priority = {"区域-战斗": 0, "战斗区域": 0,
                    "区域-奖励": 1, "奖励区域": 1, "区域-休整": 2, "休整区域": 2,
                    "区域-事件": 3, "事件区域": 3, "区域-随机": 4, "随机区域": 4,
                    "区域-商店": 5, "商店区域": 5, "区域-合成": 6, "合成区域": 6}
        return min(candidates, key=lambda token: (priority.get(normalize(token.text), 7),
                                                  token.center[0], token.center[1]))

    @staticmethod
    def _station_choice_target(scene: Scene) -> Token | None:
        # Follow the user's battle-first preference. Anomaly is a fallback;
        # forging can consume run currency.
        target = scene.find("战斗", (0.20, 0.54, 0.45, 0.82), exact=True)
        if target is not None:
            return target
        return scene.find("异常", (0.38, 0.54, 0.65, 0.82), exact=True)

    @staticmethod
    def _field_interaction_target(scene: Scene) -> Token | None:
        prompts = tuple(map(normalize, ("交互", "调查", "触碰", "阅读", "对话", "启动", "开启", "拾取", "领取",
                                        "卡牌", "区域卡", "查看卡牌", "交互卡牌", "卡牌交互")))
        candidates = [token for token in scene.tokens
                      if token.within((0.18, 0.18, 0.86, 0.86))
                      and any(normalize(token.text) == prompt or normalize(token.text).endswith(prompt)
                              for prompt in prompts)]
        return candidates[0] if candidates else None

    def _leave_area(self, scene: Scene, kind: str) -> tuple[Scene, str]:
        target = self._find(scene, ("离开商店", "离开", "返回", "关闭", "跳过", "继续"),
                            (0.02, 0.02, 0.99, 0.98))
        if target is None:
            raise AutomationError(f"{kind}页面没有识别到安全的离开或继续按钮；未购买或合成。")
        return self._click(scene, target, intent="leave_area", label=kind + "_left")

    def _close_route_map(self, scene: Scene) -> tuple[Scene, str]:
        before = self.ctx.evidence(scene, f"du_{self.report['current_run']:02d}_route_map_before_close")
        self._action_no += 1
        record = {"index": self._action_no, "run": self.report["current_run"],
                  "run_id": self.report["run_results"][-1].get("run_id") if self.report["run_results"] else None,
                  "action": "close_route_map", "status": "requested", "before": str(before),
                  "before_text": scene.text}
        self.report["actions"].append(record)
        self._persist_ledger()
        self.ctx.key("esc")
        current, kind = self._snapshot("route_map_closed")
        after = self.report["page_history"][-1]["evidence"]
        record.update(status="observed", after=after, after_text=current.text, after_page=kind)
        self._persist_ledger()
        if kind == "route":
            raise AutomationError("关闭差分宇宙地图后仍停留在地图页；没有继续输入。")
        return current, kind

    def _battle(self, scene: Scene) -> tuple[Scene, str]:
        state, target = self._daily._auto_state(scene)
        if state == "off" and target is not None:
            scene = self.ctx.differential_universe_auto_click(scene, target, self._daily)
            kind = self._observe(scene, "auto_battle_on")
        elif state == "on":
            kind = "battle"
        else:
            raise AutomationError("战斗页已识别，但自动战斗开关状态未知；本次停止。")
        elapsed = 0.0
        while elapsed < self.settings.battle_timeout:
            self.ctx.checkpoint()
            started = time.monotonic()
            scene = self.ctx._snapshot_after_du_input(timeout=20)
            kind = self._observe(scene, "battle_observation") if elapsed == 0 or int(elapsed) % 20 < 2 else classify_page(scene, self.ctx)
            text = _text(scene)
            if "战斗失败" in text or "挑战失败" in text:
                raise AutomationError("差分宇宙战斗失败；未确认胜利，已停止。")
            if kind in ("node_victory", "victory"):
                return scene, kind
            if not self._daily._in_battle(scene):
                return scene, kind
            elapsed += max(0, time.monotonic() - started)
            self.ctx.sleep(2)
            elapsed += 2
        raise AutomationError(f"差分宇宙战斗超过 {self.settings.battle_timeout} 秒，未确认结算。")

    def _field_attack_target(self, scene: Scene) -> tuple[Token, str] | None:
        text = _text(scene)
        if not has_du_field_plane_marker(text) or not has_field_battle_marker(text):
            return None
        enemy = self._daily._icon(scene, "du_enemy_target", (0.07, 0.12, 0.88, 0.90), threshold=0.64)
        if enemy is not None:
            x, y = enemy
            return Token("差分宇宙已锁定敌方目标", 1.0,
                         (x - 0.024, y - 0.042, x + 0.024, y + 0.042)), "field_target_attack"
        # Some field enemies have no lock marker until approached. Match several
        # observed idle/alert poses of the visible enemy. Keep the OCR enemy label
        # and field HUD checks in the policy guard as independent evidence.
        roi = (0.06, 0.25, 0.82, 0.90)
        matches = []
        for template_name in FIELD_ENEMY_TEMPLATES:
            match = self.ctx.template(scene, template_name, roi, threshold=0.70)
            if (isinstance(match, (tuple, list)) and len(match) == 3
                    and roi[0] <= match[0] <= roi[2] and roi[1] <= match[1] <= roi[3]
                    and match[2] >= 0.70):
                matches.append((template_name, match))
        if not matches:
            return None
        _template_name, (x, y, confidence) = max(matches, key=lambda item: item[1][2])
        return Token("差分宇宙可见敌方目标", float(confidence),
                     (x - 0.042, y - 0.042, x + 0.042, y + 0.042)), "field_enemy_attack"

    def _field_combat(self, scene: Scene) -> tuple[Scene, str]:
        # Turn the camera in one direction to survey the full space, then
        # approach visible targets in short bursts. Battle targets take
        # priority over the exit.
        # Red overlays are treated only as scene artwork; only the dedicated
        # enemy-lock or visible-enemy template can authorize an attack.
        sweep = ((0.18, 0), (0.18, 0), (0.18, 0))
        move_pattern = (("a", 600), ("w", 600), ("d", 600), ("w", 600),
                        ("a", 600), ("w", 600), ("d", 600), ("w", 600),
                        ("a", 600), ("d", 600))
        attack_attempts = 0
        approach_count = 0
        forward_approach_count = 0
        last_attack_center = None
        for step in range(14):
            self.ctx.checkpoint()
            attack = self._field_attack_target(scene)
            if attack is not None:
                target, intent = attack
                x, _ = target.center
                # A small template match shows which enemy is visible but not
                # that it is within basic-attack range. Center that enemy with
                # short lateral steps before attempting the attack.
                if (intent == "field_enemy_attack" and not 0.38 <= x <= 0.62):
                    if approach_count >= 6:
                        raise AutomationError("可见敌人连续六次短距离接近后仍未进入安全接战位置；保留截图并停止输入。")
                    direction = "a" if x < 0.38 else "d"
                    scene = self.ctx.differential_universe_move(scene, direction, 600)
                    kind = self._observe(scene, "field_enemy_approach_" + direction)
                    if kind != "field_combat":
                        return scene, kind
                    approach_count += 1
                    continue
                # Never replay a failed attack against a stale target. Require
                # a fresh short approach and a new screenshot first.
                if last_attack_center is not None:
                    if approach_count >= 6:
                        raise AutomationError("接战后仍未进入战斗，且已达到短距离接近上限；保留截图并停止输入。")
                    direction = "w"
                    scene = self.ctx.differential_universe_move(scene, direction, 600)
                    kind = self._observe(scene, "field_enemy_approach_after_attack_forward")
                    if kind != "field_combat":
                        return scene, kind
                    approach_count += 1
                    last_attack_center = None
                    continue
                # A visible enemy template can match at a distance. Close the
                # gap in two short, separately observed forward steps before
                # the first basic attack; a true lock marker can attack now.
                if intent == "field_enemy_attack" and forward_approach_count < 2:
                    if approach_count >= 6:
                        raise AutomationError("可见敌人尚未接战且已达到短距离接近上限；保留截图并停止输入。")
                    scene = self.ctx.differential_universe_move(scene, "w", 600)
                    kind = self._observe(scene, "field_enemy_approach_forward")
                    if kind != "field_combat":
                        return scene, kind
                    approach_count += 1
                    forward_approach_count += 1
                    continue
                if attack_attempts >= 2:
                    raise AutomationError("两次基于新截图的接战尝试后仍未进入战斗；保留证据并停止输入。")
                scene, kind = self._click(scene, target, intent=intent, label="field_attack")
                if kind != "field_combat":
                    return scene, kind
                attack_attempts += 1
                last_attack_center = target.center
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    self.ctx.sleep(1)
                    scene, kind = self._snapshot("field_combat_transition")
                    if kind != "field_combat":
                        return scene, kind
                if attack_attempts >= 2:
                    raise AutomationError("两次基于新截图的接战尝试后仍未进入战斗；保留证据并停止输入。")
                continue
            # A gate is an exit. Do not use it to skip a visible battle group;
            # in particular, a failed target match is not evidence that the
            # OCR-labeled enemy has been cleared.
            enemy_group_visible = any(normalize(name) in _text(scene)
                                       for name in ("惊梦剧团", "幻造生物"))
            portal = self._find(scene, ("随意门",), (0.25, 0.30, 0.78, 0.75))
            if portal is not None and not enemy_group_visible:
                scene = self.ctx.differential_universe_enter_random_gate(scene, portal)
                kind = self._observe(scene, "random_gate_interaction")
                if kind != "field_combat":
                    return scene, kind
                self.ctx.sleep(1)
                scene, kind = self._snapshot("random_gate_transition")
                if kind != "field_combat":
                    return scene, kind
                if self._find(scene, ("随意门",), (0.25, 0.30, 0.78, 0.75)) is not None:
                    raise AutomationError("已按提示进入随意门，但交互提示仍在且区域未切换；未重复操作。")
                # The used gate can leave the next free-roam region in the same page class.
                continue
            if step < len(sweep):
                dx, dy = sweep[step]
                scene = self.ctx.differential_universe_look(scene, dx, dy, 300)
                kind = self._observe(scene, "field_camera_sweep")
                if kind != "field_combat":
                    return scene, kind
                continue
            move_index = step - len(sweep)
            if move_index >= len(move_pattern):
                break
            direction, duration = move_pattern[move_index]
            scene = self.ctx.differential_universe_move(scene, direction, duration)
            kind = self._observe(scene, "field_search_" + direction)
            if kind != "field_combat":
                return scene, kind
        raise AutomationError("已完成三段镜头搜索和十次有界探索移动，仍未发现可见敌方目标；保留逐步截图与输入记录。")

    def _field_anomaly(self, scene: Scene) -> tuple[Scene, str]:
        # Anomaly rooms can contain a world object without enemies. Approach it
        # with short, recorded movement bursts and interact only on a visible
        # OCR prompt; never infer an interaction from the scene artwork alone.
        approach = (("w", 1000), ("w", 1000), ("w", 1000), ("w", 1000))
        for step, (direction, duration) in enumerate(approach, 1):
            self.ctx.checkpoint()
            prompt = self._field_interaction_target(scene)
            if prompt is not None:
                scene = self.ctx.differential_universe_interact(scene, prompt)
                kind = self._observe(scene, "anomaly_interaction")
                if kind == "field_anomaly":
                    self.ctx.sleep(1.2)
                    scene, kind = self._snapshot("anomaly_interaction_settled")
                    if kind == "field_anomaly":
                        raise AutomationError("异常区域交互后场景未变化；未重复触发。")
                return scene, kind
            scene = self.ctx.differential_universe_move(scene, direction, duration)
            kind = self._observe(scene, f"anomaly_approach_{step}_{direction}")
            if kind != "field_anomaly":
                return scene, kind
        prompt = self._field_interaction_target(scene)
        if prompt is not None:
            scene = self.ctx.differential_universe_interact(scene, prompt)
            kind = self._observe(scene, "anomaly_interaction")
            return scene, kind
        raise AutomationError("异常区域完成四次正向短距离接近后仍无可见交互提示；保留截图并停止输入。")

    def _progress_run(self, scene: Scene, kind: str) -> tuple[Scene, str, bool]:
        victory_seen = False
        for step in range(1, 241):
            self.ctx.checkpoint()
            kind = classify_page(scene, self.ctx)
            if kind == "blocked":
                raise AutomationError("识别到商店、合成或体力/星琼提示，差分宇宙运行已停止。")
            if kind == "defeat":
                raise AutomationError("差分宇宙已失败，未将本局计为完成。")
            if kind == "victory":
                victory_seen = True
                self.report["run_results"][-1]["victory_evidence"] = self.ctx.evidence(scene, f"du_{self.report['current_run']:02d}_victory")
                target = self._find(scene, FINAL_RETURN_LABELS, (0.42, 0.65, 1, 1))
                if target is None:
                    raise AutomationError("最终胜利页未识别到返回差分宇宙按钮。")
                scene, kind = self._click(scene, target, label="victory_return")
                continue
            if kind == "battle":
                scene, kind = self._battle(scene)
                continue
            if kind == "field_combat":
                scene, kind = self._field_combat(scene)
                continue
            if kind == "field_anomaly":
                scene, kind = self._field_anomaly(scene)
                continue
            if kind == "shop":
                scene, kind = self._leave_area(scene, "shop")
                continue
            if kind == "synthesis":
                scene, kind = self._leave_area(scene, "synthesis")
                continue
            if kind in ("rest", "event"):
                target = self._choice_target(scene, kind)
                if target is not None:
                    scene, kind = self._click(scene, target, intent="choice", label=kind + "_choice")
                    continue
                target = self._find(scene, ("继续", "下一步", "返回", "离开", "跳过"),
                                    (0.45, 0.62, 1, 1))
                if target is not None:
                    scene, kind = self._click(scene, target, intent="leave_area", label=kind + "_continue")
                    continue
                raise AutomationError(f"{kind}页面没有识别到免费可选项或安全离开按钮。")
            if kind == "area_choice":
                target = self._area_choice_target(scene)
                if target is None:
                    raise AutomationError("区域抽取页未识别到完整且可核对的候选区域。")
                scene, kind = self._click(scene, target, intent="area_select", label="area_selected")
                if kind == "area_choice":
                    confirm = self._find(scene, ("确认选择", "确认", "确定", "进入区域"),
                                         (0.48, 0.66, 1, 1))
                    if confirm is None:
                        raise AutomationError("区域候选点选后仍停留在选择页且没有确认按钮。")
                    scene, kind = self._click(scene, confirm, label="area_confirmed")
                continue
            if kind == "station_choice":
                target = self._station_choice_target(scene)
                if target is None:
                    raise AutomationError("下一站页面未识别到位置受限的战斗/异常区域卡。")
                station_name = "battle" if normalize(target.text) == normalize("战斗") else "anomaly"
                scene, kind = self._click(scene, target, intent="station_select",
                                          label=station_name + "_station_selected")
                if kind != "station_choice":
                    continue
                confirm = self._find(scene, ("确认", "确定", "进入区域", "进入下一站"),
                                     (0.48, 0.78, 0.98, 0.99))
                if confirm is None:
                    raise AutomationError("异常区域卡选中后未识别到确认按钮。")
                scene, kind = self._click(scene, confirm, intent="station_confirm",
                                          label="station_confirmed")
                if kind == "station_choice":
                    self.ctx.sleep(1.5)
                    scene, kind = self._snapshot("station_confirmation_settled")
                    if kind == "station_choice":
                        raise AutomationError("确认站点卡后页面没有前进；已停止重复点击。")
                continue
            if kind in ("home", "mode_select", "periodic_setup"):
                if victory_seen:
                    return scene, kind, True
                raise AutomationError("差分宇宙在未识别最终胜利前返回主页；本局未计为成功。")
            if kind == "mask_detail":
                confirm = self._find(scene, ("确认选择", "确认", "确定"), (0.56, 0.78, 0.99, 0.98))
                if confirm is None:
                    raise AutomationError("面具说明页未识别到确认按钮。")
                scene, kind = self._click(scene, confirm, intent="choice_confirm", label="mask_confirmed")
                if kind == "mask_detail":
                    self.ctx.sleep(1.5)
                    scene, kind = self._snapshot("mask_confirmation_settled")
                    if kind == "mask_detail":
                        raise AutomationError("确认面具后页面没有前进；已停止重复点击。")
                continue
            if kind in ("blessing_choice", "equation_choice", "curio_choice", "mask_choice", "miracle_choice"):
                choice_kind = kind
                if any(term in _text(scene) for term in ("已选择", "已选中", "选择成功")):
                    confirm = self._find(scene, ("确认选择", "确认", "确定"),
                                         (0.56, 0.78, 0.99, 0.98))
                    if confirm is None:
                        raise AutomationError(f"{kind}页面显示已选中，但未识别到确认按钮。")
                    scene, kind = self._click(scene, confirm, intent="choice_confirm", label=kind + "_confirmed")
                    if kind == choice_kind:
                        self.ctx.sleep(1.5)
                        scene, kind = self._snapshot(choice_kind + "_confirmation_settled")
                        if kind == choice_kind:
                            raise AutomationError(f"{choice_kind}确认后页面没有前进；已停止重复点击。")
                    continue
                target = self._choice_target(scene, kind)
                if target is None:
                    raise AutomationError(f"{kind}页面未识别到安全候选项。")
                scene, kind = self._click(scene, target, intent="choice", label=kind + "_selected")
                if kind == choice_kind:
                    confirm = self._find(scene, ("确认选择", "确认", "确定"),
                                         (0.56, 0.78, 0.99, 0.98))
                    if confirm is None:
                        raise AutomationError(f"{choice_kind}选中后未识别到确认按钮。")
                    scene, kind = self._click(scene, confirm, intent="choice_confirm",
                                              label=choice_kind + "_confirmed")
                    if kind == choice_kind:
                        self.ctx.sleep(1.5)
                        scene, kind = self._snapshot(choice_kind + "_confirmation_settled")
                        if kind == choice_kind:
                            raise AutomationError(f"{choice_kind}确认后页面没有前进；已停止重复点击。")
                continue
            if kind == "tutorial_overlay":
                target = scene.find("点击空白处关闭", exact=True)
                if target is None:
                    raise AutomationError("教学说明页没有识别到关闭提示，未点击。")
                scene, kind = self._click(scene, target, label="tutorial_closed")
                continue
            if kind == "mask_reward_overlay":
                target = Token("点击空白处关闭", 1.0, (0.47, 0.80, 0.56, 0.88))
                scene, kind = self._click(scene, target, intent="dismiss_mask_reward", label="mask_reward_closed")
                continue
            if kind == "team_setup":
                target = self._find(scene, ("开始演算", "开始挑战", "开始模拟", "确认出战"), (0.45, 0.65, 1, 1))
                if target is None:
                    raise AutomationError("差分宇宙队伍页未识别到继续开始按钮。")
                scene, kind = self._click(scene, target, label="team_confirmed")
                continue
            if kind == "route":
                if any(term in _text(scene) for term in ("位面地图", "探索进度", "当前区域")):
                    scene, kind = self._close_route_map(scene)
                    continue
                target = self._area_choice_target(scene)
                if target is None:
                    raise AutomationError("差分宇宙路线页未识别到地图关闭锚点或完整区域候选。")
                scene, kind = self._click(scene, target, intent="area_select", label="route_area_selected")
                continue
            target = self._find(scene, NAVIGATION_LABELS, (0.45, 0.70, 1, 1))
            if target is not None:
                marker = _text(scene)
                if not any(word in marker for word in map(normalize,
                    ("差分宇宙", "位面", "方程", "祝福", "奇物", "面具", "拓星", "模拟"))):
                    raise AutomationError(f"未确认处于差分宇宙页面（{kind}），未点击继续按钮。")
                scene, kind = self._click(scene, target, label="advanced")
                continue
            if kind == "node_victory":
                raise AutomationError("位面胜利结算未识别到继续按钮。")
            if kind in ("unknown", "du_page", "active_save", "rules_modal"):
                raise AutomationError(f"差分宇宙运行页面未识别（{kind}），已停止并保存当前 OCR。")
            # One fresh observation can settle a loading transition; the second
            # unknown page fails closed instead of guessing a control location.
            scene, kind = self._snapshot("run_observation")
            if kind in ("unknown", "du_page"):
                raise AutomationError("未知差分宇宙画面；停止输入并保留前后截图与 OCR。")
        raise AutomationError("差分宇宙单局超过 240 个已识别步骤，已停止。")

    def run(self) -> TaskResult:
        scene, kind = self._snapshot("initial")
        resumable = {"battle", "route", "team_setup", "equation_choice", "blessing_choice",
                     "curio_choice", "mask_choice", "mask_detail", "miracle_choice", "station_choice",
                     "tutorial_overlay", "field_combat", "field_anomaly", "node_victory", "victory"}
        resumable.add("mask_reward_overlay")
        if self.resume_active and kind in resumable:
            resumed_no = len(self.report["run_results"]) + 1
            resumed_id = "resumed-" + uuid.uuid4().hex
            self.report["current_run"] = resumed_no
            self.report["resumed_active_run"] = True
            self.report["run_results"].append({"run": resumed_no, "run_id": resumed_id,
                                               "origin": "resumed_trial", "counted": False,
                                               "status": "resuming", "resumed_at": time.time(),
                                               "resume_page": kind})
            if self.periodic_rank is not None:
                self.report["mode"] = "周期演算"
                self.report["difficulty_selection"] = {
                    "requested_rank": self.periodic_rank,
                    "displayed_rank_before": self.periodic_rank,
                    "displayed_rank_after": self.periodic_rank,
                    "verified": True, "user_selected": True,
                    "source": "explicit_resume_context",
                }
            self._persist_ledger()
            scene, kind, returned = self._progress_run(scene, kind)
            if not returned:
                raise AutomationError("接续的差分宇宙运行未核实胜利结算与返回。")
            return_evidence = self.ctx.evidence(scene, f"du_{resumed_no:02d}_resumed_return")
            count_resumed_periodic = self.periodic_rank is not None
            self.report["run_results"][-1].update(
                status="completed" if count_resumed_periodic else "returned_uncounted",
                counted=count_resumed_periodic, finished_at=time.time(),
                return_page=kind, return_evidence=str(return_evidence),
                mode=self.report.get("mode"),
                difficulty_rank=self.periodic_rank if count_resumed_periodic else None,
                difficulty_verified=count_resumed_periodic)
            self.report["resumed_runs"] = self.report.get("resumed_runs", 0) + 1
            if count_resumed_periodic:
                self.report["completed_runs"] = 1
            self._persist_ledger()
            if count_resumed_periodic:
                self.ctx.log("周期演算接续局已核实胜利结算并计入本次请求局数。")
                if self.report["completed_runs"] >= self.runs:
                    self.report["last_message"] = "周期演算当前局已确认胜利结算并返回。"
                    return TaskResult(TASK, "ok", self.report["last_message"])
                scene, kind = self._snapshot("after_resumed_run")
            else:
                self.ctx.log("差分宇宙接续试运行已核实返回；按要求不计入新的低难度完成局数。")
                scene, kind = self._snapshot("after_resumed_run")
        elif self.resume_active:
            raise AutomationError(f"接续选项已启用，但当前页面不是已识别的运行中页面（{kind}）；未发送输入。")
        else:
            scene, kind = self._open_differential_universe(scene, kind)
        while self.report["completed_runs"] < self.runs:
            run_no = self.report["completed_runs"] + 1
            attempt_no = len(self.report["run_results"]) + 1
            run_id = str(uuid.uuid4())
            self.report["current_run"] = attempt_no
            self.report["run_results"].append({"run": attempt_no, "counted_run": run_no,
                "run_id": run_id, "origin": "fresh", "counted": False,
                "status": "starting", "started_at": time.time()})
            self._persist_ledger()
            scene, kind = self._prepare_and_start(scene, kind)
            start_evidence = self.report["page_history"][-1]["evidence"] if self.report["page_history"] else ""
            difficulty = dict(self.report.get("difficulty_selection", {}))
            periodic = self.report.get("mode") == "周期演算"
            expected_rank = difficulty.get("requested_rank") if periodic else 1
            if (difficulty.get("verified") is not True or expected_rank is None
                    or difficulty.get("displayed_rank_after") != expected_rank):
                raise AutomationError("本局启动前没有与所选模式匹配的已核实难度证据；不继续计数。")
            if not periodic and expected_rank != 1:
                raise AutomationError("常规演算本局启动前没有最低难度 I 证据；不继续计数。")
            self.report["run_results"][-1].update(status="running", started_page=kind,
                started_evidence=start_evidence, difficulty_rank=expected_rank, difficulty_verified=True,
                mode=self.report.get("mode"), difficulty_evidence=difficulty)
            self._persist_ledger()
            scene, kind, returned = self._progress_run(scene, kind)
            if not returned:
                raise AutomationError(f"第 {run_no} 局没有核实胜利结算与返回。")
            return_evidence = self.ctx.evidence(scene, f"du_{attempt_no:02d}_fresh_return")
            self.report["run_results"][-1].update(status="completed", counted=True,
                finished_at=time.time(), return_page=kind, return_evidence=str(return_evidence))
            self.report["completed_runs"] = run_no
            self._persist_ledger()
            mode_label = "周期演算" if periodic else "新开最低难度"
            self.ctx.log(f"差分宇宙{mode_label}第 {run_no}/{self.runs} 局已核实胜利结算并返回。")
            if run_no < self.runs:
                # Do not continue an in-progress run; a fresh, completed return
                # to the mode page is required before the next start.
                scene, kind = self._snapshot("between_runs")
        if self.report.get("mode") == "周期演算":
            self.report["last_message"] = f"{self.runs} 局周期演算均确认胜利结算并返回。"
        else:
            self.report["last_message"] = f"{self.runs} 局新开难度 I 均确认胜利结算并返回。"
        return TaskResult(TASK, "ok", self.report["last_message"])
