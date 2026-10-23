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
from dataclasses import asdict
from pathlib import Path

from .models import AutomationError, InputInterrupted, Scene, TaskResult, Token, normalize
from .du_card_effects import station_card_effect,preview_beacons
from .policy import has_du_field_plane_marker, du_miracle_target_labels, du_miracle_randomize_two, du_event_free_leave,du_event_free_choice,du_flea_market_choice,du_tutorial_close_prompt
from .workflows import DailyWorkflow
from .storage import replace_file


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
FINAL_RETURN_LABELS = ("返回差分宇宙", "返回差分宇宙主界面", "返回主界面", "返回", "确定")
FINAL_LABELS = ("模拟宇宙通关", "通关结算", "演算成功", "最终结算", "通关成功")
ROOM_TIMEOUT = 90
COMBAT_APPROACH_MS = 3000
RUN_TIMEOUT = 3600


def is_battle_scene(scene: Scene, context=None) -> bool:
    """Use the same calibrated battle-pause anchor as the existing battle flow."""
    if scene.has(("战斗失败", "挑战成功", "挑战失败", "退出关卡", "再来一次", "战斗设置", "战斗胜利")):
        return True
    if context is None:
        return False
    daily=DailyWorkflow(context)
    return (daily._in_battle(scene) or
            daily._icon(scene,"du_battle_pause",(.95,0,1,.10),threshold=.88) is not None)


def _text(scene: Scene) -> str:
    return normalize(scene.text)


def has_field_battle_marker(text: str) -> bool:
    """Recognize full battle labels or a truncated field label plus its live HUD."""
    context = normalize(text)
    if any(s in context for s in ("战斗","精英","首领")):
        return True
    return bool(has_du_field_plane_marker(context) and re.search(r"位面[-—]?战", context)
                and re.search(r"lv\s*\d+\s*/\s*20", context))


def classify_page(scene: Scene, context=None) -> str:
    text = _text(scene)
    if any(normalize(term) in text for term in RESOURCE_BLOCK_TERMS):
        return "blocked"
    if DailyWorkflow._supply_overlay(scene):
        return "login_supply"
    from .policy import du_forge_console_menu
    if du_forge_console_menu(scene):
        return 'forge_console'
    if scene.has("星际和平指南",(0,0,.32,.13)):
        return "guide"
    from .policy import du_blessing_discard_prompt
    if du_blessing_discard_prompt(scene) is not None:
        return 'blessing_discard_prompt'
    if (scene.has('均衡等级大幅超过当前难度，无法获得解锁材料、拟合值和积分',(.27,.44,.73,.53))
            and scene.has('取消',(.29,.58,.49,.66),exact=True)
            and scene.has('确认',(.51,.58,.71,.66),exact=True)):
        return 'low_rank_warning'
    from .du_saves import management,rename_dialog
    if rename_dialog(scene):
        return "save_name"
    if management(scene):
        return "save_management"
    if all(term in text for term in ("当前存档非本周演算进度","确定继续进度吗")):
        return "resume_confirm"
    if (scene.has("下载角色",(0,0,.32,.13))
            and all(s in text for s in ("角色列表","预设编队"))):
        return "team_selection"
    if (scene.has("丢弃奇物",(0,0,.32,.13))
            and re.search(r"(?:需|须)舍弃1次奇物",text)):
        return "curio_discard"
    if (scene.has('丢弃祝福',(0,0,.32,.13),exact=True) and scene.has('请舍弃祝福')
            and scene.has('丢弃',(.56,.78,.99,.98),exact=True)):
        return 'blessing_discard'
    if all(s in text for s in ("分析报告","探索中断","返回主界面")):
        return "defeat"
    if (all(s in text for s in ("分析报告","探索成功","差分宇宙构筑内容","返回主界面"))
            and re.search(r"(?:周期|常规)演算[（(]?13/13",text)):
        return "victory"
    if du_tutorial_close_prompt(scene) is not None:
        return "tutorial_overlay"
    if du_miracle_target_labels(scene):
        # A selected station's detail can say “胜利后选择祝福时”.
        # Its fixed selector heading takes precedence over reward wording.
        return "miracle_target"
    if "敷衍面具" in text and "获得愿力" in text:
        return "mask_reward_overlay"
    if scene.has("星阶模式说明"):
        return "rules_modal"
    # Navigation pages contain links named 商店/合成. Their page title and
    # primary controls take precedence over incidental reward/link text.
    if "差分宇宙" in text and "乐园漫记" in text and "开始游戏" in text:
        return "home"
    if "模式选择" in text and "常规" in text and "周期" in text:
        return "mode_select"
    if ("星阶模式" in text and "拓星模式" in text and "练习模式" in text
            and ("启动差分宇宙" in text or "启动" in text)):
        return "star_rank_setup"
    if ("差分宇宙" in text and "乐园漫记" in text and "难度" in text
            and ("进入星阶模式" in text or ("常规演算" in text
                 and scene.has(("启动「差分宇宙」","启动差分宇宙"),(.72,.82,1,.98),exact=True)))):
        return "difficulty_setup"
    if ("差分宇宙" in text and "周期演算" in text and "难度" in text
            and any(term in text for term in map(normalize,("启动差分宇宙","启动「差分宇宙」")))):
        return "periodic_setup"
    if all(term in text for term in ('差分宇宙','乐园漫记','周期演算','难度','本周首领敌人')):
        # Setup's description contains “战斗胜利后”. During its entrance
        # animation the launch button may still be unreadable; this is loading,
        # not a node victory, and must be observed until controls are ready.
        return 'unknown'
    for title,kind in (("选择祝福","blessing_choice"),("选择方程","equation_choice"),
                       ("选择奇物","curio_choice")):
        if scene.has(title,(0,0,.32,.13),exact=True):
            return kind
    if any(normalize(term) in text for term in map(normalize, FINAL_LABELS)):
        return "victory"
    if "战斗失败" in text or "模拟失败" in text:
        return "defeat"
    if scene.has("事件",(0,0,.32,.13),exact=True):
        return "event"
    # Station descriptions can mention 战斗胜利; the page heading identifies
    # the selectable route before incidental result wording in its description.
    if (scene.has("选择下一站", (0,0,.32,.13)) and
            any(s in text for s in ("战斗","精英","首领","奖励","休整","异常","事件","冒险","空白","财富","铸造","商店"))):
        return "station_choice"
    if scene.has(('挑战成功','战斗胜利'),exact=True):
        return "node_victory"
    if any(term in text for term in map(normalize, ("选择祝福", "请选择祝福", "选择一次祝福", "选择1次祝福"))):
        return "blessing_choice"
    if any(term in text for term in map(normalize, ("选择方程", "请选择方程", "方程选择"))):
        return "equation_choice"
    if any(term in text for term in map(normalize, ("选择奇物", "请选择奇物", "奇物选择"))):
        return "curio_choice"
    if ("选择下一站" in text and ("选择一张站点卡" in text or
            any(s in text for s in ("战斗","精英","首领","异常","空白","财富","铸造")))):
        return "station_choice"
    if any(s in text for s in ("选择你的奇迹","选择惊世奇迹","选择奇迹")):
        return "miracle_choice"
    if ("面具效果" in text
            and scene.find(("确认选择", "确认", "确定"), (0.56, 0.78, 0.99, 0.98)) is not None):
        return "mask_detail"
    if any(term in text for term in map(normalize,
            ("选择一张面具", "选择你的面具", "选择面具"))):
        return "mask_choice"
    is_route_map = "位面地图" in text or "探索进度" in text or "当前区域" in text
    if is_route_map:
        return "route"
    if any(term in text for term in map(normalize, ("选择区域", "区域选择", "抽取区域", "选择一个区域", "区域待选择"))):
        return "area_choice"
    # A live world interaction label (for example 事件) is not a dialog page.
    if has_du_field_plane_marker(text):
        from .policy import du_encounter_field
        if du_encounter_field(scene):
            return 'field_anomaly'
        # The world-card title may contain another area name (for example
        # 商店街一番战 inside a 奖励 room). Prefer the fixed progress header.
        header=normalize(''.join(t.text for t in scene.tokens if t.within((0,0,.32,.065))))
        area=re.search(r'位面[-—]?(战斗|精英|首领|异常|休整|商店|财富|空白|铸造|冒险|奖励|事件)',header)
        if has_du_field_plane_marker(header) and area:
            return {'战斗':'field_combat','精英':'field_combat','首领':'field_combat',
                    '异常':'field_anomaly','休整':'field_rest','商店':'field_shop',
                    '财富':'field_wealth','空白':'field_blank','铸造':'field_forge',
                    '冒险':'field_adventure','奖励':'field_reward','事件':'field_event'}[area[1]]
        if has_field_battle_marker(text):
            return "field_combat"
        if "异常" in text:
            return "field_anomaly"
        if "休整" in text:
            return "field_rest"
        if "商店" in text:
            return "field_shop"
        if "财富" in text:
            return "field_wealth"
        if "空白" in text:
            return "field_blank"
        if "铸造" in text:
            return "field_forge"
        if "冒险" in text:
            return "field_adventure"
        if "奖励" in text:
            return "field_reward"
        if "事件" in text:
            return "field_event"
    if scene.has(("黑塔的商店","商店"),(0,0,.32,.13),exact=True):
        return "shop"
    if scene.has(("合成","奇物合成"),(0,0,.32,.13),exact=True):
        return "synthesis"
    if any(term in text for term in map(normalize, ("休整区", "休息区", "休整区域"))):
        return "rest"
    if scene.has(("事件","遭遇","随机事件"),(0,0,.32,.13),exact=True):
        return "event"
    if is_battle_scene(scene, context):
        return "battle"
    if "继续游戏" in text or "继续演算" in text:
        return "active_save"
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
        if isinstance(runs, bool) or not isinstance(runs, int) or not 1 <= runs <= 10:
            raise ValueError("差分宇宙局数必须是 1～10 的整数。")
        if type(resume_active) is not bool:
            raise ValueError("接续差分宇宙开关必须为布尔值。")
        if (periodic_rank is not None and
                (isinstance(periodic_rank, bool) or not isinstance(periodic_rank, int)
                 or not 1 <= periodic_rank <= 10 or not resume_active)):
            raise ValueError("周期演算接续难度必须是 1～10 的整数，且仅用于接续当前局。")
        if periodic_rank is not None and runs != 1:
            raise ValueError("周期演算接续仅完成当前 1 局。")
        self.ctx, self.settings, self.runs = context, context.settings, runs
        self.resume_active = resume_active
        self.periodic_rank = periodic_rank
        self.report = context.report.differential_universe
        self.report.update(requested_runs=runs, completed_runs=0, current_run=0,
                           mode="周期演算" if self.settings.differential_universe_mode=='periodic' else "常规演算", season="乐园漫记",
                           actions=[], page_history=[], run_results=[],
                           stamina_budget_used=False, premium_currency_used=False,
                           fuel_used=False)
        self.session_id = str(uuid.uuid4())
        self.report["session_id"] = self.session_id
        self._daily = DailyWorkflow(context)
        self._pages = 0
        self._action_no = 0
        self._fresh_field_entry = False
        self._resume_field_needs_target=resume_active
        self._field_cleared = False
        self._forge_console_used = False
        self._combat_chest_attempts = 0
        self.report["timeouts"] = dict(room_seconds=ROOM_TIMEOUT,run_seconds=RUN_TIMEOUT)
        run_dir=getattr(context.report,"run_dir",None)
        if isinstance(run_dir,(str,Path)) and run_dir:
            self.report["run_dir"]=str(run_dir)

    def _inactive(self):
        value=getattr(getattr(self.ctx,"runner",None),"inactive_duration",0)
        return value if isinstance(value,(int,float)) else 0

    def _check_deadline(self, started, inactive_before, seconds, label):
        if time.monotonic()-started-(self._inactive()-inactive_before) >= seconds:
            raise AutomationError(f"差分宇宙{label}超过{seconds}秒，停止输入并保留当前进度。")

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
            "reward_collection": self.report.get('reward_collection'),
            "navigation_observations": self.report.get('navigation_observations',[]),
            "device_detours": self.report.get('device_detours',[]),
            "team_selections": self.report.get('team_selections',[]),
            "daily_interludes": self.report.get('daily_interludes',[]),
        }
        temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(temp,path)
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

    def _wait_known(self, scene: Scene, kind: str, label: str,
                    timeout: float = 30) -> tuple[Scene, str]:
        """Observe loading/attack animations without replaying the last input."""
        started, inactive_before = time.monotonic(), self._inactive()
        while kind == "unknown":
            self._check_deadline(started, inactive_before, timeout, "画面过渡等待")
            self.ctx.sleep(.7)
            scene, kind = self._snapshot(label + "_transition")
        return scene, kind

    def _settle_supply(self, scene: Scene) -> tuple[Scene, str]:
        """A daily reset may put the owned login reward over an active battle."""
        claim = self._daily._supply_claim(scene)
        # A room-entry banner can overlap the remaining-day text behind this
        # popup. Re-read boundedly without input; keep the exact owned/free
        # checks instead of interpreting corrupted OCR as a day count.
        for _ in range(4):
            if claim is not None:
                break
            self.ctx.sleep(.5)
            scene,kind=self._snapshot('supply_header_recheck')
            if kind!='login_supply':
                return scene,kind
            claim=self._daily._supply_claim(scene)
        revealed = self._daily._supply_revealed(scene)
        if claim is None or (self._daily._login_supply_closed if revealed
                             else self._daily._login_supply_claimed):
            raise AutomationError('列车补给未核实免费领取入口，或同一阶段已经处理过，停止重复点击。')
        self._daily._login_supply_claimed = True
        if revealed:
            self._daily._login_supply_closed = True
        intent = 'du_supply_close' if revealed else 'du_supply_claim'
        self.ctx.log('已核实90星琼，关闭列车补给展示。' if revealed
                     else '领取已拥有的列车补给，随后继续当前演算。')
        scene, kind = self._click(scene, claim, intent=intent, label=intent)
        # The first post-input capture can still show the preceding animation.
        scene = self.ctx.wait(
            lambda page: (not self._daily._supply_overlay(page)
                          and classify_page(page, self.ctx) != 'unknown')
            or (not revealed and self._daily._supply_revealed(page)),
            timeout=45, description='核实跨天列车补给领取与关闭')
        return scene, self._observe(scene, intent + '_verified')

    def _close_tutorial(self,scene):
        def heading(page):
            name=next((name for name in ('获得物品','祝福强化','站点卡升级','信标已部署','失去站点卡','获得站点卡',
                                         '获得祝福','获得奇物','方程展开') if page.has(name,exact=True)),None)
            detail=None
            if name=='方程展开':
                names=[token for token in page.tokens if token.within((.38,.43,.62,.51))
                       and re.fullmatch(r'[\u3400-\u9fff·：:]{2,20}',normalize(token.text))]
                if len(names)==1:
                    detail=normalize(names[0].text)
            return (name,detail) if name is not None else None
        original_heading=heading(scene)
        def next_overlay(page):
            current=heading(page)
            if current is None:
                return False
            return (original_heading is None or current[0]!=original_heading[0]
                    or (current[1] is not None and original_heading[1] is not None
                        and current[1]!=original_heading[1]))
        for _ in range(3):
            target=du_tutorial_close_prompt(scene)
            if target is None:
                raise AutomationError('教学说明页没有识别到关闭提示，未点击。')
            scene,kind=self._click(scene,target,intent='du_tutorial_close',label='tutorial_closed')
            if kind!='tutorial_overlay' or next_overlay(scene):
                return scene,kind
            self.ctx.sleep(.35)
            scene,kind=self._snapshot('tutorial_close_recheck')
            scene,kind=self._wait_known(scene,kind,'tutorial_close_recheck')
            if kind!='tutorial_overlay' or next_overlay(scene):
                return scene,kind
        raise AutomationError('说明页三次实时关闭提示点击均未生效，停止并保留证据。')

    def _apply_miracle_target(self, scene: Scene) -> tuple[Scene, str]:
        effect=station_card_effect(scene)
        if effect is None:
            raise AutomationError("奇迹站点卡的完整指令未识别，停止选择。")
        deleting=effect.kind=='delete'
        sequential=du_miracle_randomize_two(scene) or deleting
        started,inactive_before=time.monotonic(),self._inactive()
        for _ in range(effect.count if deleting else 2 if sequential else 1):
            if deleting:
                self._check_deadline(started,inactive_before,ROOM_TIMEOUT,'逐张删卡')
            if effect.kind=='reroll_beacons':
                attempted=[]
                for attempt in range(20):
                    labels=effect.target_labels
                    candidates=sorted((t for t in scene.tokens if t.text in labels and t.within((.03,.24,.64,.78))),
                        key=lambda t:(labels.index(t.text),t.center[1],t.center[0]))
                    target=next((t for t in candidates if not any(
                        abs(t.center[0]-x)<.025 and abs(t.center[1]-y)<.025 for x,y in attempted)),None)
                    if target is None:
                        raise AutomationError('未在可见站点卡详情中找到带有信标的目标。')
                    attempted.append(target.center)
                    scene,kind=self._click(scene,target,intent='miracle_target',label='miracle_beacon_target_selected')
                    if kind!='miracle_target' or station_card_effect(scene)!=effect or preview_beacons(scene):
                        break
                else:
                    raise AutomationError('信标目标预览达到上限，停止重复选卡。')
            else:
                target=self._find(scene,du_miracle_target_labels(scene),(.03,.24,.64,.78))
                if target is None:
                    raise AutomationError("奇迹的站点卡目标页没有符合当前效果的可识别卡片。")
                scene,kind=self._click(scene,target,intent="miracle_target",label="miracle_target_selected")
            if kind != "miracle_target":
                return scene,kind
            if station_card_effect(scene) != effect:
                raise AutomationError("奇迹站点卡选中后指令改变，停止确认。")
            if effect.kind=='reroll_beacons' and not preview_beacons(scene):
                raise AutomationError('当前站点卡没有已核实信标，未确认重置。')
            confirm=self._find(scene,("确定","确认"),(.72,.82,.99,.96))
            if confirm is None:
                raise AutomationError("奇迹站点卡目标选中后没有确认按钮。")
            scene,kind=self._click(scene,confirm,intent="miracle_target_confirm",label="miracle_target_confirmed")
            self.ctx.sleep(1)
            scene,kind=self._snapshot("miracle_applied")
            if kind == "miracle_target":
                raise AutomationError("奇迹站点卡确认后未前进，停止重复确认。")
            if not sequential:
                return scene,kind
            # Each target has its own loss/gain pair. The instruction still
            # says 2 on the second selector, so only these receipts authorize
            # the next confirmation, with an absolute limit of two targets.
            receipts=(('失去站点卡','失去数量：1'),) if deleting else (
                ('失去站点卡','失去数量：1'),('获得站点卡','获得数量：1'))
            for heading,quantity in receipts:
                if (kind!='tutorial_overlay'
                        or not scene.has(heading,(.35,.10,.65,.18),exact=True)
                        or not scene.has(quantity,(.35,.18,.65,.25),exact=True)):
                    raise AutomationError('删卡未核实逐张失去1张站点卡，停止再次确认。' if deleting else
                        "双卡转换未核实逐张失去和获得各1张站点卡，停止再次确认。")
                scene,kind=self._close_tutorial(scene)
            if kind != 'miracle_target':
                return scene,kind
            if station_card_effect(scene) != effect:
                raise AutomationError('删卡后目标指令改变，停止重复确认。' if deleting else
                    "双卡转换后目标指令改变，停止重复确认。")
        raise AutomationError('删卡已达到指令数量仍未离开目标页，停止重复确认。' if deleting else
            "双卡转换已确认两张仍未离开目标页，停止重复确认。")

    def _click(self, scene: Scene, target: Token, *, intent="navigation", label="action") -> tuple[Scene, str]:
        self._action_no += 1
        record={"index": self._action_no, "run": self.report["current_run"],
            "action": target.text, "intent": intent, "status": "requested", "before_ocr": scene.text}
        if intent in ('miracle_target','miracle_target_confirm'):
            effect=station_card_effect(scene)
            record['card_effect']=asdict(effect) if effect is not None else None
        self.report["actions"].append(record)
        self._persist_ledger()
        self.ctx.click(scene, target, du_intent=intent)
        current = self.ctx.last_scene
        if current is None:
            raise AutomationError("差分宇宙操作后未获得新截图。")
        kind = self._observe(current, label)
        record.update(status="sent", after_ocr=current.text,
            after_evidence=self.report["page_history"][-1]["evidence"], after_page=kind)
        self._persist_ledger()
        return self._wait_known(current, kind, label, timeout=60)

    def _find(self, scene: Scene, labels, roi=(0, 0, 1, 1)) -> Token | None:
        for label in labels:
            found = scene.find(label, roi, exact=True)
            if found is not None:
                return found
        return None

    def _enter_gate(self, scene, portal, field_kind):
        scene=self.ctx.differential_universe_enter_random_gate(scene,portal)
        kind=self._observe(scene,'random_gate_interaction')
        scene,kind=self._wait_known(scene,kind,'random_gate_interaction')
        # F may begin an automatic approach that cannot finish beside a step
        # or door edge. Observe before returning to the bounded navigation loop;
        # only a freshly visible prompt may authorize another F.
        for _ in range(3):
            if kind!=field_kind:
                break
            self.ctx.sleep(.7)
            scene,kind=self._snapshot('random_gate_response')
            scene,kind=self._wait_known(scene,kind,'random_gate_response')
        return scene,kind

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
            if not match:
                from .du_navigation import lowest_difficulty
                match = lowest_difficulty(scene)
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

    def _guide_entry(self, scene):
        if not scene.has(("旷宇纷争","寰宇纷争"),(0,0,.32,.13)):
            match = self.ctx.template(scene,"du_guide_tab",(.28,.15,.35,.24),threshold=.85)
            if not match:
                raise AutomationError("未匹配指南旷宇纷争页签图标，未点击。")
            x,y,score=match
            scene,kind=self._click(scene,Token("差分宇宙指南页签",score,(x-.018,y-.018,x+.018,y+.018)),
                                   intent="du_guide_tab",label="guide_universe_tab")
        target=scene.find("差分宇宙",(.14,.26,.35,.82),exact=True)
        if target is None:
            raise AutomationError("指南旷宇纷争页未识别到差分宇宙分类。")
        scene,kind=self._click(scene,target,intent="du_guide_select",label="guide_du_selected")
        scene=self.ctx.wait(lambda s:s.has("乐园漫记",(.36,.26,.88,.80)) and
                            s.has("拟合等级",(.36,.26,.88,.80)),timeout=20,description="差分宇宙指南详情")
        target=scene.find("前往参与",(.70,.75,.88,.87),exact=True)
        if target is None:
            raise AutomationError("差分宇宙指南详情未识别到前往参与按钮。")
        return self._click(scene,target,intent="du_guide_enter",label="guide_du_entered")

    def _open_differential_universe(self, scene: Scene, kind: str) -> tuple[Scene, str]:
        from .du_rewards import page_kind as reward_page_kind,collect as collect_rewards
        if (self.settings.differential_universe_rewards and reward_page_kind(scene)
                in ('gallery_home','gallery_category','gallery_milestones')):
            scene=collect_rewards(self,scene)
            return scene,self._observe(scene,'interrupted_gallery_rewards_completed')
        if kind == "rules_modal":
            self._action_no += 1
            self.report["actions"].append({"index": self._action_no, "run": 0,
                "action": "close_star_rank_rules", "status": "sent", "before_ocr": scene.text})
            self.ctx.key("esc")
            scene, kind = self._snapshot("closed_rules")
        if kind in ("mode_select", "difficulty_setup", "star_rank_setup", "periodic_setup", "du_page", "home", "team_selection"):
            return scene, kind
        if kind == "guide":
            return self._guide_entry(scene)
        from .workflows import DailyWorkflow
        if not DailyWorkflow._phone(scene):
            scene = self._daily.ensure_main()
            kind = self._observe(scene, "phone_menu")
        if DailyWorkflow._phone(scene):
            target = scene.find("差分宇宙", (0.55, 0.25, 1, 1), exact=True)
            if target is None:
                guide=scene.find(("指南","星际和平指南"),(.55,.25,1,1),exact=True)
                if guide is None:
                    raise AutomationError("手机菜单未识别到差分宇宙或指南入口。")
                scene,kind=self._click(scene,guide,label="opened_guide")
                if kind != "guide":
                    raise AutomationError("打开指南后页面未核实。")
                return self._guide_entry(scene)
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
        team_verified=False
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
                if scene.has("继续进度",exact=True):
                    raise AutomationError("模式页存在进行中的演算；请使用接续当前进度，未重复点击新开局。")
                mode_label='周期演算' if self.settings.differential_universe_mode=='periodic' else '常规演算'
                scene=self.ctx.wait(lambda s:s.has(mode_label,exact=True),timeout=20,description=f"{mode_label}入口文字就绪")
                target = scene.find(mode_label, exact=True)
                if target is None:
                    raise AutomationError(f"模式选择页未识别到{mode_label}。")
                scene, kind = self._click(scene, target, intent='du_mode_select', label="selected_run_mode")
                continue
            if kind in ('difficulty_setup','star_rank_setup','periodic_setup','team_selection'):
                # A remembered setup is mode-specific; never silently launch it
                # when the requested mode differs.
                mode_periodic=scene.has('周期演算')
                if mode_periodic != (self.settings.differential_universe_mode=='periodic'):
                    raise AutomationError('当前备战页与所选演算模式不一致，请返回模式选择；未启动其他模式。')
                if not team_verified:
                    scene,kind=self._select_preset_team(scene)
                    team_verified=True
            if kind == "difficulty_setup":
                scene = self._select_lowest_difficulty(scene)
                target = scene.find("进入星阶模式", exact=True)
                if target is not None:
                    scene, kind = self._click(scene, target, label="star_rank_setup")
                    continue
                start=self._find(scene,("启动「差分宇宙」","启动差分宇宙"),(.72,.82,1,.98))
                if start is None or self._displayed_difficulty_rank(scene)!=1:
                    raise AutomationError("常规难度 I 的启动按钮未核实。")
                self.report['mode']='常规演算'
                scene,kind=self._click(scene,start,label='normal_run_started')
                if kind=='low_rank_warning':
                    target=scene.find('确认',(.51,.58,.71,.66),exact=True)
                    scene,kind=self._click(scene,target,intent='du_low_rank_confirm',label='normal_low_rank_confirmed')
                if kind in ('blocked','unknown','difficulty_setup','mode_select'):
                    raise AutomationError(f"启动常规演算后页面未进入已知运行流程（{kind}）。")
                return scene,kind
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
                # Preserve the selected periodic rank; choose the named preset
                # independently because this page remembers its own old team.
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

    def _select_preset_team(self,scene):
        from .du_team import select
        return select(self,scene)

    def _collect_rewards(self,scene,kind,label):
        # A completed run may return to the mode page. Walk back through known
        # setup pages before red-dot collection; never Escape from a live run.
        for _ in range(2):
            if kind=='home':
                break
            if kind not in ('mode_select','periodic_setup','difficulty_setup','star_rank_setup'):
                raise AutomationError('领奖前未回到已识别的差分宇宙菜单，未退出当前场景。')
            before=kind
            self.ctx.key('esc')
            scene=self.ctx.wait(lambda page:classify_page(page,self.ctx)!=before,
                                timeout=12,description='返回差分宇宙领奖主页')
            kind=self._observe(scene,'rewards_home_navigation')
        from .du_rewards import collect
        scene=collect(self,scene)
        return scene,self._observe(scene,label)

    def _after_completed_run(self,scene,kind,label):
        if self.settings.differential_universe_rewards:
            scene,kind=self._collect_rewards(scene,kind,label)
        from .du_daily import after_win
        return after_win(self,scene,kind)

    def _choice_target(self, scene: Scene, kind: str) -> Token | None:
        if kind in ("blessing_choice","equation_choice","curio_choice","miracle_choice","curio_discard"):
            # The three blessing names share a stable row. Body text can wrap
            # farther left than the name and is a poor selection anchor.
            names=[]
            for left,right in ((.14,.36),(.39,.61),(.64,.87)):
                card_names=[t for t in scene.tokens if t.within((left,.35,right,.54))
                            and re.search(r"[\u3400-\u9fff]{2}",t.text)]
                if card_names:
                    names.append(min(card_names,key=lambda t:t.center[1]))
            if names:
                if kind=="blessing_choice":
                    from .du_strategy import blessing_score
                    return max(names,key=lambda t:blessing_score(scene,t)[0])
                if kind=='miracle_choice':
                    # Prefer a free effect which resolves without choosing a
                    # shop card. Combat/elite buffs then suit the route plan.
                    def miracle_priority(target):
                        x=target.center[0]
                        body=normalize(''.join(t.text for t in scene.tokens
                            if t.within((x-.115,.52,x+.115,.78))))
                        combat=any(term in body for term in ('【战斗】','【精英】','【首领】'))
                        random_gain='随机' in body and '等级+' in body
                        costly=any(term in body for term in ('花费','消耗','失去','购买','兑换'))
                        return (not costly,combat,random_gain,'【商店】' not in body,-x)
                    return max(names,key=miracle_priority)
                def priority(t):
                    x=t.center[0]
                    elation=any("欢愉" in v.text for v in scene.tokens
                                if v.within((x-.11,.73,x+.11,.80)))
                    return (not elation,x,t.center[1])
                return min(names,key=priority)
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

    def _select_blessing(self, scene, *, discard=False):
        """Compare reversible card previews, keeping the pointer off their titles."""
        from difflib import SequenceMatcher
        from .du_strategy import blessing_score,blessing_discard_score,same_blessing_titles
        expected='blessing_discard' if discard else 'blessing_choice'
        intent='blessing_discard_select' if discard else 'choice'
        columns=((.14,.36),(.39,.61),(.64,.87))
        def title(page,left,right):
            names=[t for t in page.tokens if t.within((left,.35,right,.54))
                   and re.search(r"[\u3400-\u9fff]",t.text)]
            return min(names,key=lambda t:t.center[1]) if names else None
        scene=self._settle_blessing_titles(scene,kind=expected)
        identity=self._choice_identity(scene,expected)
        ranked=[]
        selected=None
        for index,(left,right) in enumerate(columns):
            current=title(scene,left,right)
            if current is None:
                continue
            # The observed card extends above its title; select its central
            # icon so the mouse cursor does not hide the last title character.
            x=(left+right)/2
            target=Token("祝福候选卡片",current.score,(x-.02,.30,x+.02,.34))
            before=scene
            scene,kind=self._click(scene,target,intent=intent,label="blessing_preview")
            fresh_identity=self._choice_identity(scene,kind)
            equivalent=(len(identity)==len(fresh_identity) and all(
                SequenceMatcher(None,old,new).ratio()>=.66 for old,new in zip(identity,fresh_identity)))
            equivalent=equivalent or (len(identity)==len(fresh_identity)==3
                                      and same_blessing_titles(before,scene))
            if kind!=expected or not equivalent:
                raise AutomationError("祝福预览未保持同一组选项，未确认奖励。")
            identity=fresh_identity
            selected=index
            fresh=title(scene,left,right)
            if fresh is None:
                raise AutomationError("祝福预览后标题尚未加载，未确认。")
            score,reason=(blessing_discard_score if discard else blessing_score)(scene,fresh,preview=True)
            ranked.append((score,index,normalize(fresh.text),reason))
        if not ranked:
            raise AutomationError("祝福候选尚未加载，未预览或确认。")
        _,index,name,reason=max(ranked,key=lambda item:item[0])
        if selected!=index:
            left,right=columns[index];x=(left+right)/2
            target=Token("祝福候选卡片",.99,(x-.02,.30,x+.02,.34))
            before=scene
            scene,kind=self._click(scene,target,intent=intent,label="blessing_best_selected")
            fresh_identity=self._choice_identity(scene,kind)
            equivalent=(len(identity)==len(fresh_identity) and all(
                SequenceMatcher(None,old,new).ratio()>=.66 for old,new in zip(identity,fresh_identity)))
            equivalent=equivalent or (len(identity)==len(fresh_identity)==3
                                      and same_blessing_titles(before,scene))
            if kind!=expected or not equivalent:
                raise AutomationError("最佳祝福选中后页面改变，未重复确认。")
        self.report.setdefault("reward_decisions",[]).append({"selected":name,"reason":reason,'discard':discard,
            "candidates":[{"name":row[2],**row[3]} for row in ranked]})
        self.ctx.log(("祝福舍弃：" if discard else "祝福选择：")+name+"；"+json.dumps(reason,ensure_ascii=False))
        self._persist_ledger()
        return scene,expected

    def _settle_blessing_titles(self, scene, *, kind='blessing_choice'):
        # The heading appears before the three cards finish sliding in. Even
        # three OCR fragments can look like valid titles during that animation.
        expected=kind
        previous=self._choice_identity(scene,expected)
        started,inactive_before=time.monotonic(),self._inactive()
        while True:
            self._check_deadline(started,inactive_before,15,"祝福三列标题加载")
            self.ctx.sleep(.5)
            scene,kind=self._snapshot("blessing_titles_settled")
            if kind!=expected:
                raise AutomationError("祝福卡牌加载时页面改变，未选择奖励。")
            current=self._choice_identity(scene,kind)
            if len(current)==3 and current==previous:
                return scene
            previous=current

    @staticmethod
    def _choice_identity(scene: Scene, kind: str) -> tuple[str, ...]:
        if kind in ("blessing_choice","blessing_discard","equation_choice","curio_choice","miracle_choice"):
            names=[]
            for left,right in ((.14,.36),(.39,.61),(.64,.87)):
                tokens=[t for t in scene.tokens if t.within((left,.35,right,.54))
                        and re.search(r"[\u3400-\u9fff]",t.text)]
                if tokens:
                    names.append(normalize(min(tokens,key=lambda t:t.center[1]).text))
            return tuple(names)
        return ()

    def _confirm_choice(self, scene: Scene, kind: str) -> tuple[Scene, str]:
        before = self._choice_identity(scene, kind)
        target = self._find(scene,("确认选择","确认","确定"),(.56,.78,.99,.98))
        if target is None:
            raise AutomationError(f"{kind}选中后未识别到确认按钮。")
        scene, after_kind = self._click(scene,target,intent="choice_confirm",label=kind+"_confirmed")
        started,inactive_before=time.monotonic(),self._inactive()
        candidate_identity=None
        while after_kind == kind:
            after = self._choice_identity(scene, kind)
            if before and after and before != after:
                # A bonus reward is a new choice, even though the page class
                # and its confirm button are the same. Require two matching
                # observations so a half-slid card is not another reward.
                if after == candidate_identity:
                    return scene,after_kind
                candidate_identity=after
            else:
                candidate_identity=None
            self._check_deadline(started,inactive_before,15,"奖励确认等待")
            self.ctx.sleep(.7)
            scene,after_kind=self._snapshot(kind+"_confirmation_settled")
        return scene,after_kind

    @staticmethod
    def _area_choice_target(scene: Scene) -> Token | None:
        import re
        from .policy import du_recruitment_candidates
        recruitment=du_recruitment_candidates(scene)
        if recruitment:
            labels=('战斗','精英','首领','奖励','空白','休整','异常','事件','财富','冒险','铸造','商店')
            return min(recruitment,key=lambda t:labels.index(normalize(t.text)))
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
        for label in ("战斗","精英","首领","奖励","空白","休整","异常","事件","财富","冒险","铸造","商店"):
            target=scene.find(label,(.20,.54,.73,.82),exact=True)
            if target is not None:
                return target
        return None

    def _loaded_area_choice(self,scene):
        target=self._area_choice_target(scene)
        if target is None:
            # The recruitment heading appears while all three cards still
            # have blank titles. Observe loading without choosing a blank.
            scene=self.ctx.wait(lambda page:classify_page(page,self.ctx)=='area_choice'
                and self._area_choice_target(page) is not None,
                timeout=15,description='区域候选卡片加载')
            self._observe(scene,'area_candidates_loaded')
            target=self._area_choice_target(scene)
        if target is None:
            raise AutomationError('区域抽取页未识别到完整且可核对的候选区域。')
        return scene,target

    @staticmethod
    def _field_interaction_target(scene: Scene) -> Token | None:
        from .policy import du_named_field_interaction
        named=du_named_field_interaction(scene)
        if named is not None:
            return named
        prompts = tuple(map(normalize, ("交互", "调查", "触碰", "阅读", "对话", "启动", "开启", "拾取", "领取",
                                        "卡牌", "区域卡", "查看卡牌", "交互卡牌", "卡牌交互", "事件")))
        candidates = [token for token in scene.tokens
                      if token.within((0.18, 0.18, 0.86, 0.86))
                      and any(normalize(token.text) == prompt or normalize(token.text).endswith(prompt)
                              for prompt in prompts)]
        return candidates[0] if candidates else None

    def _station_target(self,scene):
        text_target=self._station_choice_target(scene)
        if text_target is not None and normalize(text_target.text)=="战斗":
            return text_target,"station_select"
        match=self.ctx.template(scene,"du_station_combat",(.20,.32,.73,.73),threshold=.90)
        if isinstance(match,(tuple,list)) and len(match)==3 and match[2]>=.90:
            x,y,score=match
            return Token("差分宇宙战斗站点卡图标",score,(x-.02,y-.02,x+.02,y+.02)),"station_icon_select"
        return (text_target,"station_select") if text_target is not None else None

    @staticmethod
    def _station_hazard(scene):
        from .policy import du_station_hazard
        return du_station_hazard(scene)

    def _safer_station_preview(self,scene,target):
        """Inspect the selected card before committing a dangerous beacon."""
        visited=[target.center[0]]
        labels=('战斗','精英','首领','奖励','空白','休整','异常','事件','财富','冒险','铸造','商店')
        for _ in range(6):
            if scene.image is not None:
                previous=None
                for _ in range(6):
                    self.ctx.sleep(.35)
                    scene,kind=self._snapshot('station_beacon_preview')
                    if kind!='station_choice':
                        raise AutomationError('站点预览时页面改变，未确认进入。')
                    text=normalize(''.join(t.text for t in scene.tokens if t.within((.08,.14,.92,.33))))
                    if text and text==previous and '选择一张站点卡' not in text:
                        break
                    previous=text
                else:
                    raise AutomationError('站点效果预览未稳定，未确认进入。')
            hazard=self._station_hazard(scene)
            if hazard is None:
                return scene,'station_choice'
            self.report.setdefault('station_decisions',[]).append({'run':self.report['current_run'],
                'action':'avoid','hazard':hazard,'card_x':visited[-1]})
            candidates=[t for t in scene.tokens if normalize(t.text) in labels
                        and t.within((.20,.54,.73,.82))
                        and all(abs(t.center[0]-x)>.065 for x in visited)]
            if not candidates:
                raise AutomationError('可识别站点均带有敌人死亡伤害全队的危险信标，未强行进入。')
            target=min(candidates,key=lambda t:(labels.index(normalize(t.text)),-t.score))
            self.ctx.log('避开敌人死亡自爆信标，检查其他站点：'+target.text)
            visited.append(target.center[0])
            scene,kind=self._click(scene,target,intent='station_select',label='station_hazard_alternative')
            if kind!='station_choice':
                raise AutomationError('切换站点预览后页面改变，未确认进入。')
        raise AutomationError('站点危险效果检查达到上限，未确认进入。')

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

    def _auto_state(self,scene):
        state,target=self._daily._auto_state(scene)
        if state in ("on","off"):
            return state,target
        from .du_navigation import auto_state
        return auto_state(scene)

    def _battle(self, scene: Scene) -> tuple[Scene, str]:
        state, target = self._auto_state(scene)
        started,inactive_before=time.monotonic(),self._inactive()
        while state not in ("on","off"):
            self._check_deadline(started,inactive_before,20,"自动战斗开关等待")
            self.ctx.sleep(.7)
            scene,kind=self._snapshot("battle_controls_settling")
            scene,kind=self._wait_known(scene,kind,"battle_controls")
            if kind != "battle":
                return scene,kind
            state,target=self._auto_state(scene)
        if state == "off" and target is not None:
            scene = self.ctx.differential_universe_auto_click(scene, target, self)
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
            if kind == "unknown":
                scene,kind=self._wait_known(scene,kind,"battle_animation",timeout=120)
            text = _text(scene)
            if "战斗失败" in text or "挑战失败" in text:
                raise AutomationError("差分宇宙战斗失败；未确认胜利，已停止。")
            if kind in ("node_victory", "victory"):
                return scene, kind
            if kind != "battle":
                return scene, kind
            elapsed += max(0, time.monotonic() - started)
            self.ctx.sleep(2)
            elapsed += 2
        raise AutomationError(f"差分宇宙战斗超过 {self.settings.battle_timeout} 秒，未确认结算。")

    def _field_attack_target(self, scene: Scene) -> tuple[Token, str] | None:
        text = _text(scene)
        if not has_du_field_plane_marker(text) or not has_field_battle_marker(text):
            return None
        # The field's centered enemy information bar is shared by enemy
        # families. Bind the basic attack to that bar and the observed mouse
        # hint, rather than requiring a template for every 3-D enemy pose.
        enemy_bars=[t for t in scene.tokens if t.within((.38,.01,.64,.10))
                    and re.match(r"等级\d{1,3}[\u4e00-\u9fff]",normalize(t.text))]
        from .du_navigation import attack_reticle
        ring=attack_reticle(scene)
        if ring is not None and scene.has('等级',(.38,.01,.64,.10)):
            return ring,'field_ring_attack'
        if len(enemy_bars)==1:
            anchor=self._daily._icon(scene,"du_attack_mouse",(.878,.825,.901,.867),threshold=.88)
            if anchor is not None:
                x,y=anchor[0]-.014,anchor[1]+.030
                return Token("差分宇宙基础攻击",.99,(x-.012,y-.012,x+.012,y+.012)),"field_attack"
        # The 0/1 HUD beside two cards counts station cards, not live enemies.
        # It must never authorize an attack after the battle group is cleared.
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

    def _event_target(self, scene: Scene):
        if not scene.has("事件",(0,0,.32,.13),exact=True):
            return None
        # Narration retains earlier choices as dialogue history. A visible
        # continuation arrow belongs to the current step and outranks that text.
        match=self.ctx.template(scene,"du_event_next",(.75,.55,.90,.84),threshold=.88)
        if match is None:
            from .du_navigation import event_next
            match=event_next(scene)
        if isinstance(match,(tuple,list)) and len(match)==3 and match[2]>=.88:
            x,y,score=match
            return Token("事件对话继续",score,(x-.008,y-.008,x+.008,y+.008)),"event_advance"
        leave=[t for t in scene.tokens if t.within((.68,.18,.99,.90)) and du_event_free_choice(scene,t)]
        if leave:
            confirm=scene.find(("确定","确认"),(.75,.18,.99,.94),exact=True)
            if confirm is not None and any(.02<confirm.center[1]-t.center[1]<.16 for t in leave):
                return confirm,"event_confirm"
            return min(leave,key=lambda t:t.center[1]),"event_leave"
        trade=[t for t in scene.tokens if du_flea_market_choice(scene,t)]
        if trade:
            confirm=scene.find(('确定','确认'),(.75,.18,.99,.94),exact=True)
            if confirm is not None and any(.02<confirm.center[1]-t.center[1]<.16 for t in trade):
                return confirm,'event_flea_confirm'
            return min(trade,key=lambda t:t.center[1]),'event_flea_select'
        from .du_events import action as event_star_action
        visual=event_star_action(scene)
        if visual is not None:
            return visual
        selection=scene.find("选择",(.70,.58,.99,.84),exact=True)
        if selection is not None:
            return selection,"event_open_selection"
        return None

    def _event(self, scene: Scene) -> tuple[Scene,str]:
        started,inactive_before=time.monotonic(),self._inactive()
        for _ in range(24):
            self._check_deadline(started,inactive_before,ROOM_TIMEOUT,"事件对话")
            action=self._event_target(scene)
            if action is None:
                scene=self.ctx.wait(lambda page:classify_page(page,self.ctx)!="event"
                    or self._event_target(page) is not None,timeout=15,description="事件文字与免费离开选项加载")
                kind=self._observe(scene,"event_loaded")
                if kind!="event":
                    return scene,kind
                action=self._event_target(scene)
            before=_text(scene)
            if action[1]=="event_advance":
                scene=self.ctx.differential_universe_dialogue(scene,action[0])
                kind=self._observe(scene,"event_dialogue_burst")
                scene,kind=self._wait_known(scene,kind,"event_dialogue_burst")
            else:
                if action[1]=='event_star_select':
                    from .du_events import option_stars,description
                    body=description(scene,action[0],option_stars(scene))
                    self.report.setdefault('event_decisions',[]).append({'run':self.report['current_run'],
                        'strategy':'conservative','star_y':action[0].center[1],
                        'star_score':action[0].score,'description':body})
                    self.ctx.log('事件星标选择：'+(body or '效果文字未读出，按上方选项继续'))
                scene,kind=self._click(scene,action[0],intent=action[1],label=action[1])
            if kind!="event":
                return scene,kind
            if action[1]!="event_advance" and _text(scene)==before:
                scene=self.ctx.wait(lambda page:_text(page)!=before,timeout=10,description="事件对话响应")
                kind=self._observe(scene,"event_response")
                if kind!="event":
                    return scene,kind
        raise AutomationError("事件对话达到步骤上限；停止并保留进度。")

    def _combat_chest(self,scene):
        from .policy import DU_CHEST_INTERACTIONS
        target=self._field_interaction_target(scene)
        if target is None or target.text not in DU_CHEST_INTERACTIONS:
            return None
        if self._combat_chest_attempts>=3:
            raise AutomationError('战斗区域三次宝箱交互后仍未前进，停止重复操作。')
        self._combat_chest_attempts+=1
        scene=self.ctx.differential_universe_interact(scene,target)
        kind=self._observe(scene,'combat_chest_interaction')
        scene,kind=self._wait_known(scene,kind,'combat_chest_interaction')
        for _ in range(2):
            if kind!='field_combat':
                break
            self.ctx.sleep(.35)
            scene,kind=self._snapshot('combat_chest_settled')
            scene,kind=self._wait_known(scene,kind,'combat_chest_settled')
        # Opening a chest keeps the heading; resume the bounded forward probe
        # after its rewards, rather than attacking the obstacle twice.
        self._fresh_field_entry=not self._field_cleared
        return scene,kind

    def _field_combat(self, scene: Scene, *, fresh_entry=False) -> tuple[Scene, str]:
        chest=self._combat_chest(scene)
        if chest is not None:
            return chest
        if scene.image is not None:
            from .du_navigation import navigation_targets,verified_attack_reticle as attack_reticle
            range_seen=False
            forward_ready=False
            resume_search=self._resume_field_needs_target and not fresh_entry and not self._field_cleared
            self._resume_field_needs_target=False
            if resume_search and attack_reticle(scene) is None:
                scene=self.ctx.differential_universe_motion(scene,'scan_right',8000,profile='seek_attack')
                kind=self._observe(scene,'resumed_enemy_reacquired')
                scene,kind=self._wait_known(scene,kind,'resumed_enemy_reacquired')
                if kind!='field_combat':
                    return scene,kind
                result=getattr(self.ctx,'_du_motion_result',{})
                reason=result.get('reason') if isinstance(result,dict) else None
                range_seen=reason=='attack_reticle'
                if not range_seen and reason!='enemy_landmark' and attack_reticle(scene) is None:
                    raise AutomationError('接续战斗现场原地搜索后仍未找到怪物，停止并保留位置。')
                return self._field_visual(scene,range_seen=range_seen,prefer_enemy=True)
            if fresh_entry and attack_reticle(scene) is None:
                # A newly confirmed station restores the game's forward-facing
                # entrance camera. Let spawn effects settle before one bounded
                # forward probe. The enemy name bar can still be absent here;
                # a resumed field has no equivalent heading guarantee.
                scene,kind=self._snapshot('fresh_station_entry_settled')
                scene,kind=self._wait_known(scene,kind,'fresh_station_entry_settled')
                if kind!='field_combat':
                    return scene,kind
                if attack_reticle(scene) is None:
                    scene=self.ctx.differential_universe_motion(scene,'w',COMBAT_APPROACH_MS,profile='engage')
                    result=getattr(self.ctx,'_du_motion_result',{})
                    range_seen=isinstance(result,dict) and result.get('reason')=='attack_reticle'
                    forward_ready=isinstance(result,dict) and result.get('reason') in ('duration','attack_reticle')
                    kind=self._observe(scene,'fresh_station_forward_probe')
                    scene,kind=self._wait_known(scene,kind,'fresh_station_forward_probe')
                    if kind!='field_combat':
                        return scene,kind
            return self._field_visual(scene,range_seen=range_seen,forward_ready=forward_ready)
        # New rooms put their objective ahead. Preserve that heading: no blind
        # orbit, lateral search or retreat before interacting with the target.
        started,inactive_before=time.monotonic(),self._inactive()
        attacks=0
        advances=0
        approached=False
        for step in range(20):
            self.ctx.checkpoint()
            self._check_deadline(started,inactive_before,ROOM_TIMEOUT,"位面目标接近")
            attack=self._field_attack_target(scene)
            enemy_visible=any(re.search(r"等级\d{1,3}[\u3400-\u9fff]",normalize(t.text))
                              for t in scene.tokens if t.within((.38,.01,.64,.10)))
            enemy_visible=enemy_visible or any(name in _text(scene) for name in ("惊梦剧团","幻造生物"))
            if attack is not None:
                target,intent=attack
                if intent!="field_target_attack" and not approached:
                    scene=self.ctx.differential_universe_motion(scene,"w",1200,profile="enemy")
                    kind=self._observe(scene,"field_enemy_forward")
                    scene,kind=self._wait_known(scene,kind,"field_enemy_forward")
                    if kind!="field_combat":
                        return scene,kind
                    approached=True
                    continue
                if attacks>=2:
                    raise AutomationError("两次接战后仍未进入战斗，停止并保留进度。")
                scene=self.ctx.differential_universe_attack(scene,target,intent)
                attacks+=1
                kind=self._observe(scene,"field_attack")
                scene,kind=self._wait_known(scene,kind,"field_attack",timeout=120)
                if kind!="field_combat":
                    return scene,kind
                for _ in range(5):
                    self.ctx.sleep(.7)
                    scene,kind=self._snapshot("field_attack_settled")
                    scene,kind=self._wait_known(scene,kind,"field_attack",timeout=120)
                    if kind!="field_combat":
                        return scene,kind
                approached=False
                continue
            if not enemy_visible:
                portal=self._find(scene,("随意门",),(.25,.30,.78,.75))
                if portal is not None:
                    scene=self.ctx.differential_universe_enter_random_gate(scene,portal)
                    kind=self._observe(scene,"random_gate_interaction")
                    scene,kind=self._wait_known(scene,kind,"random_gate_interaction")
                    if kind=="field_combat":
                        scene=self.ctx.wait(lambda page:classify_page(page,self.ctx)!="field_combat",
                                            timeout=12,description="随意门切换位面")
                        kind=self._observe(scene,"random_gate_transition")
                    return scene,kind
            if advances>=8:
                break
            scene=self.ctx.differential_universe_motion(scene,"w",COMBAT_APPROACH_MS,
                profile="enemy" if enemy_visible else "forward")
            advances+=1
            kind=self._observe(scene,"field_straight_approach")
            scene,kind=self._wait_known(scene,kind,"field_straight_approach")
            if kind!="field_combat":
                return scene,kind
        raise AutomationError("位面目标直行接近达到上限，仍未核实交互或接战；停止并保留进度。")

    def _field_visual(self, scene, *, field_kind="field_combat",range_seen=False,forward_ready=False,prefer_enemy=False):
        from .du_navigation import navigation_targets,verified_attack_reticle as attack_reticle,random_gate,optional_device_prompt,interaction_hint
        from .du_detector import forward_barrier,detect_recovery_enemies
        started,inactive_before=time.monotonic(),self._inactive()
        scans=attacks=recoveries=sweeps=attack_aims=attack_searches=0
        close_backoffs=side_routes=0
        side_route_forward=False
        aligned_enemy_steps=0
        ring_waits=0
        element_checked=False
        last_range_bearing=None
        portal_attempts=0
        device_detours=unread_interaction_checks=0
        cleared=self._field_cleared
        for step in range(36):
            self.ctx.checkpoint()
            self._check_deadline(started,inactive_before,ROOM_TIMEOUT,"视觉目标定位与接近")
            if field_kind=='field_combat':
                chest=self._combat_chest(scene)
                if chest is not None:
                    return chest
            device=optional_device_prompt(scene,forge_console_used=self._forge_console_used)
            if device is not None:
                if device_detours:
                    raise AutomationError('已绕行一次，但可选设备仍占据交互范围；停止重复横移。')
                device_detours+=1
                scene,kind=self._avoid_optional_device(scene,field_kind,device)
                if kind!=field_kind:
                    return scene,kind
                range_seen=forward_ready=False
                aligned_enemy_steps=0
                continue
            if (scene.image is not None and interaction_hint(scene.image)
                    and self._find(scene,('随意门',),(.25,.30,.78,.75)) is None
                    and (field_kind!='field_combat' or cleared or attack_reticle(scene) is None)):
                if unread_interaction_checks>=2:
                    raise AutomationError('F提示已出现，但交互名称尚未核实；停止重复前进并保留当前位置。')
                self.ctx.sleep(.2)
                scene,kind=self._snapshot('combat_interaction_caption_recheck')
                unread_interaction_checks+=1
                scene,kind=self._wait_known(scene,kind,'combat_interaction_caption_recheck')
                if kind!=field_kind:
                    return scene,kind
                continue
            unread_interaction_checks=0
            face=random_gate(scene,fast=True) if field_kind=='field_combat' and not cleared else None
            cleared=cleared or (face is not None and face.text=='差分宇宙随意门外观')
            if cleared:
                self._field_cleared=True
            targets=navigation_targets(scene,enemies=field_kind=='field_combat' and not cleared)
            if (attacks or prefer_enemy) and field_kind=='field_combat' and not cleared and not any(t.text=='Enemy' for t in targets):
                targets=detect_recovery_enemies(scene)+targets
            enemies=[t for t in targets if t.text=="Enemy"]
            locked=[t for t in targets if t.text=="GateLocked"]
            gates=[t for t in targets if t.text=="Target"] if not locked else []
            # The pink gate anchors the room's forward heading. Enemies can
            # stand off to the side while the entrance already faces the group.
            candidates=(enemies or locked or gates) if attacks or prefer_enemy else (locked or gates or enemies)
            goal=min(candidates,key=lambda t:abs(t.center[0]-.5),default=None)
            if goal is not None:
                sweeps=0
            goal_height=goal.box[3]-goal.box[1] if goal is not None else 0
            heading_tolerance=.055 if goal is not None and goal.text=='Enemy' else (.025 if cleared or field_kind!='field_combat' or goal_height>.5 else .055)
            attack=self._field_attack_target(scene) if field_kind=="field_combat" and not cleared else None
            reticle=attack_reticle(scene) if field_kind=='field_combat' and not cleared else None
            if reticle is not None:
                range_seen=True
                last_range_bearing=reticle
            attack_ready=range_seen or forward_ready
            self.report.setdefault('navigation_observations',[]).append({
                'run':self.report['current_run'],'page':self._pages,'field_kind':field_kind,
                'targets':[{'label':t.text,'score':float(t.score),'box':[float(v) for v in t.box]} for t in targets],
                'selected':goal.text if goal is not None else None})
            if attack_ready and reticle is None and field_kind=='field_combat' and not cleared:
                # A bounded forward approach or a just-seen ring is enough
                # for one left click. A switch/glow must not trigger camera
                # searches that turn the character away from an in-range foe.
                attack=(Token('差分宇宙直行接战',.99,(.48,.45,.52,.49)),'field_forward_attack')
            if goal is None and aligned_enemy_steps>0 and reticle is None and not attack_ready:
                # Centering can hide the enemy behind the avatar and also
                # remove its name bar. Retain only that just-verified heading.
                scene=self.ctx.differential_universe_motion(scene,'w',600,profile='engage')
                aligned_enemy_steps-=1
                result=getattr(self.ctx,'_du_motion_result',{})
                if isinstance(result,dict) and result.get('reason')=='attack_reticle':
                    range_seen=True
                kind=self._observe(scene,'visual_enemy_occlusion_approach')
                scene,kind=self._wait_known(scene,kind,'visual_enemy_occlusion_approach')
                if kind!=field_kind:
                    return scene,kind
                continue
            if attack is not None and not attack_ready:
                if reticle is None and goal is None:
                    if ring_waits<2:
                        self.ctx.sleep(.2)
                        scene,kind=self._snapshot('visual_reticle_animation_recheck')
                        ring_waits+=1
                        if kind!=field_kind:
                            return scene,kind
                        continue
                    # The name bar can persist while looking away from the enemy.
                    # It is not enough evidence to walk in the current heading.
                    attack=None
                elif reticle is None:
                    if abs(goal.center[0]-.5)>heading_tolerance:
                        delta=max(-.12,min(.12,(goal.center[0]-.5)*.65))
                        if goal.text=='Enemy' and abs(goal.center[0]-.5-1.6*delta)<.07:
                            aligned_enemy_steps=2
                        scene=self.ctx.differential_universe_look(scene,delta,0,220)
                        label="visual_combat_heading_aligned"
                    else:
                        if goal.text=='Enemy':
                            aligned_enemy_steps=2
                        scene=self.ctx.differential_universe_motion(scene,"w",COMBAT_APPROACH_MS,profile="engage")
                        label="visual_enemy_range_approach"
                    kind=self._observe(scene,label)
                    scene,kind=self._wait_known(scene,kind,label)
                    if kind!=field_kind:
                        return scene,kind
                    result=getattr(self.ctx,"_du_motion_result",{})
                    if label=="visual_enemy_range_approach" and isinstance(result,dict):
                        forward_ready=result.get('reason') in ('duration','attack_reticle')
                    if label=="visual_enemy_range_approach" and isinstance(result,dict) and result.get("reason")=="background_stalled":
                        if recoveries>=2:
                            raise AutomationError("接近敌人时两次脱困无效，已停止顶墙。")
                        scene=self.ctx.differential_universe_move(scene,"s",650)
                        recoveries+=1
                    continue
            if attack is not None:
                if attacks>=2:
                    raise AutomationError("可见敌人两次接战未进入战斗，停止保留进度。")
                # Keep the requested straight approach and first click. If it
                # misses, a side range ring supplies a bounded corrective
                # bearing; repeating the same door-facing swing cannot help.
                bearing=reticle
                if attacks and bearing is None and not attack_aims and range_seen:
                    bearing=last_range_bearing
                    result=getattr(self.ctx,'_du_motion_result',{})
                    observed=result.get('attack_target') if isinstance(result,dict) else None
                    box=observed.get('box') if isinstance(observed,dict) else None
                    if (bearing is None and isinstance(result,dict) and result.get('reason')=='attack_reticle'
                            and isinstance(box,(list,tuple)) and len(box)==4):
                        bearing=Token('已观测攻击圆环',float(observed.get('score',0)),tuple(box))
                if attacks and bearing is not None and abs(bearing.center[0]-.5)>.12:
                    if attack_aims>=2:
                        raise AutomationError('接战校正两次后目标仍偏离正前方，停止重复空挥。')
                    delta=max(-.12,min(.12,(bearing.center[0]-.5)*.65))
                    scene=self.ctx.differential_universe_look(scene,delta,0,220)
                    attack_aims+=1
                    element_checked=False
                    kind=self._observe(scene,'missed_attack_ring_aligned')
                    scene,kind=self._wait_known(scene,kind,'missed_attack_ring_aligned')
                    if kind!=field_kind:
                        return scene,kind
                    continue
                if attacks and bearing is None and not range_seen and not attack_aims:
                    if attack_searches:
                        raise AutomationError('首击未接战，原地搜索后仍未重新核实攻击圆环，停止前进。')
                    attack_searches+=1
                    scene=self.ctx.differential_universe_motion(scene,'scan_right',8000,profile='seek_attack')
                    kind=self._observe(scene,'missed_attack_stationary_search')
                    scene,kind=self._wait_known(scene,kind,'missed_attack_stationary_search')
                    if kind!=field_kind:
                        return scene,kind
                    result=getattr(self.ctx,'_du_motion_result',{})
                    forward_ready=False
                    range_seen=isinstance(result,dict) and result.get('reason')=='attack_reticle'
                    enemy_found=(isinstance(result,dict) and result.get('reason')=='enemy_landmark'
                                 and (any(t.text=='Enemy' for t in navigation_targets(scene))
                                      or bool(detect_recovery_enemies(scene))))
                    if not range_seen and attack_reticle(scene) is None and not enemy_found:
                        raise AutomationError('首击未接战，原地搜索后仍未重新核实攻击圆环，停止前进。')
                    continue
                # The first click retains the game's selected range target.
                if not element_checked:
                    scene,kind=self._choose_attack_character(scene)
                    element_checked=True
                    if kind!=field_kind:
                        return scene,kind
                    continue
                scene=self.ctx.differential_universe_attack(scene,*attack)
                attacks+=1
                kind=self._observe(scene,"visual_enemy_attacked")
                scene,kind=self._wait_known(scene,kind,"visual_enemy_attacked",timeout=120)
                if kind!=field_kind:
                    return scene,kind
                self.ctx.sleep(1)
                scene,kind=self._snapshot("visual_attack_response")
                if kind!=field_kind:
                    return scene,kind
                continue
            portal=self._find(scene,("随意门",),(.25,.30,.78,.75))
            if portal is not None:
                cleared=self._field_cleared=True
                if portal_attempts>=2:
                    raise AutomationError('两次已核实随意门交互未完成切换，停止保留位置。')
                portal_attempts+=1
                scene,kind=self._enter_gate(scene,portal,field_kind)
                if kind!=field_kind:
                    return scene,kind
                continue
            if side_route_forward:
                # The preceding sidestep cleared a visually verified gate back.
                scene=self.ctx.differential_universe_move(scene,"w",850)
                side_route_forward=False
                kind=self._observe(scene,"visual_gate_side_cleared")
                scene,kind=self._wait_known(scene,kind,"visual_gate_side_cleared")
                if kind!=field_kind:
                    return scene,kind
                continue
            if goal is not None and goal.text!='Enemy' and goal_height>.65 and close_backoffs<2:
                # A clipped panel gives an unreliable steering center. Increase
                # distance before trying to aim at its visible fragment.
                scene=self.ctx.differential_universe_move(scene,"s",700)
                close_backoffs+=1
                kind=self._observe(scene,"visual_close_gate_backoff")
                scene,kind=self._wait_known(scene,kind,"visual_close_gate_backoff")
                if kind!=field_kind:
                    return scene,kind
                continue
            landmark=random_gate(scene,fast=True) if goal is not None else None
            if (goal is not None and goal.text!='Enemy' and landmark is not None and landmark.text.endswith("背面")
                    and goal_height>.35 and abs(goal.center[0]-.5)<.10 and side_routes<1):
                scene=self.ctx.differential_universe_move(scene,"a",750)
                side_routes+=1
                side_route_forward=True
                kind=self._observe(scene,"visual_gate_back_sidestep")
                scene,kind=self._wait_known(scene,kind,"visual_gate_back_sidestep")
                if kind!=field_kind:
                    return scene,kind
                continue
            if goal is None:
                if sweeps>=2:
                    raise AutomationError("原地镜头搜索达到上限，未找到可用门或怪物；没有继续移动角色。")
                if sweeps==1:
                    scene=self.ctx.differential_universe_look(scene,0,-.04,250)
                    kind=self._observe(scene,'visual_search_pitch_checked')
                    scene,kind=self._wait_known(scene,kind,'visual_search_pitch_checked')
                    if kind!=field_kind:
                        return scene,kind
                scene=self.ctx.differential_universe_motion(scene,'scan_right',8000,
                    profile='seek_gate' if field_kind!='field_combat' or cleared else 'seek')
                sweeps+=1
                label="visual_stationary_search"
            elif abs(goal.center[0]-.5)>heading_tolerance:
                delta=max(-.12,min(.12,(goal.center[0]-.5)*.65))
                if goal.text=='Enemy' and abs(goal.center[0]-.5-1.6*delta)<.07:
                    aligned_enemy_steps=2
                scene=self.ctx.differential_universe_look(scene,delta,0,220)
                label="visual_target_aligned"
            else:
                barrier=forward_barrier(scene.image)
                if goal.text=="Target" and barrier is not None and abs(barrier.center[0]-goal.center[0])<.12:
                    if scans>=12:
                        raise AutomationError("目标方向仍被红色警戒边界阻挡，未继续前行。")
                    scene=self.ctx.differential_universe_look(scene,.16,0,400)
                    scans+=1
                    label="visual_barrier_avoided"
                else:
                    prompt=self._find(scene,("调查","交互","事件","卡牌"),(.47,.30,.79,.76))
                    if prompt is not None:
                        raise AutomationError("遇到非随意门的场景交互，停止前行并保留位置。")
                    # Keep holding near a target too: the live watcher releases
                    # immediately on the F hint, range ring, drift or stalled
                    # background. Short timed pulses add OCR pauses at the door.
                    duration=COMBAT_APPROACH_MS if field_kind=='field_combat' and not cleared else 4000
                    if goal.text=='Enemy':
                        aligned_enemy_steps=2
                    scene=self.ctx.differential_universe_motion(scene,"w",duration,
                        profile="engage" if field_kind=='field_combat' and not cleared else "exit")
                    label="visual_target_approach"
                    result=getattr(self.ctx,"_du_motion_result",{})
                    if field_kind=='field_combat' and not cleared and isinstance(result,dict):
                        forward_ready=result.get('reason') in ('duration','attack_reticle')
                    if isinstance(result,dict) and result.get("reason")=="background_stalled":
                        if recoveries>=2:
                            raise AutomationError("两次脱困后背景仍无位移，停止顶墙并保留位置。")
                        scene=self.ctx.differential_universe_move(scene,"s",650)
                        recoveries+=1
                        label="visual_stall_backed_out"
            kind=self._observe(scene,label)
            scene,kind=self._wait_known(scene,kind,label)
            if kind!=field_kind:
                return scene,kind
        raise AutomationError("视觉导航达到步骤上限，停止并保留进度。")

    def _choose_attack_character(self,scene):
        from .du_elements import visible_elements
        from .du_navigation import verified_attack_reticle as attack_reticle
        initial,weaknesses=visible_elements(scene)
        selected=None
        active=initial
        if active is not None and weaknesses and active not in weaknesses:
            for slot in (1,3,2,4):
                if attack_reticle(scene) is None:
                    break
                scene=self.ctx.differential_universe_switch_character(scene,slot)
                self.ctx.sleep(.35)
                scene,kind=self._snapshot("attack_character_checked")
                scene,kind=self._wait_known(scene,kind,"attack_character_checked")
                if kind!="field_combat":
                    return scene,kind
                active,current_weaknesses=visible_elements(scene)
                selected=slot
                if active in current_weaknesses:
                    weaknesses=current_weaknesses
                    break
        matched=active is not None and active in weaknesses
        self.report.setdefault("attack_elements",[]).append({"current_element":active,
            "weaknesses":sorted(weaknesses),"matched":matched,"selected_slot":selected})
        self._persist_ledger()
        return scene,"field_combat"

    def _field_anomaly(self, scene: Scene, *, fresh_entry=False) -> tuple[Scene, str]:
        card_fields=('field_anomaly','field_reward','field_event','field_forge','field_shop','field_wealth','field_adventure')
        if scene.image is not None:
            if fresh_entry and self._field_interaction_target(scene) is None:
                from .du_navigation import event_targets
                scene,kind=self._snapshot('fresh_card_station_settled')
                scene,kind=self._wait_known(scene,kind,'fresh_card_station_settled')
                if kind not in card_fields:
                    return scene,kind
                if (self._field_interaction_target(scene) is None
                        and self._find(scene,('随意门',),(.25,.30,.78,.75)) is None
                        and not event_targets(scene)):
                    scene=self.ctx.differential_universe_motion(scene,'w',4000,profile='forward')
                    kind=self._observe(scene,'fresh_card_station_forward_probe')
                    scene,kind=self._wait_known(scene,kind,'fresh_card_station_forward_probe')
                    if kind not in card_fields:
                        return scene,kind
            return self._field_anomaly_visual(scene,field_kind=classify_page(scene,self.ctx))
        started,inactive_before=time.monotonic(),self._inactive()
        for step in range(9):
            self.ctx.checkpoint()
            self._check_deadline(started,inactive_before,ROOM_TIMEOUT,"异常区域目标接近")
            prompt=self._field_interaction_target(scene)
            if prompt is not None and prompt.text=='造物调试台' and self._forge_console_used:
                prompt=None
            portal=self._find(scene,("随意门",),(.25,.30,.78,.75))
            if prompt is not None or portal is not None:
                if prompt is not None:
                    scene=self.ctx.differential_universe_interact(scene,prompt)
                else:
                    scene=self.ctx.differential_universe_enter_random_gate(scene,portal)
                kind=self._observe(scene,"anomaly_interaction")
                scene,kind=self._wait_known(scene,kind,"anomaly_interaction")
                if kind=="field_anomaly":
                    scene=self.ctx.wait(lambda page:classify_page(page,self.ctx)!="field_anomaly",
                                        timeout=12,description="异常区域交互响应")
                    kind=self._observe(scene,"anomaly_interaction_settled")
                return scene,kind
            if step==8:
                break
            scene=self.ctx.differential_universe_motion(scene,"w",4000,profile="forward")
            kind=self._observe(scene,"anomaly_straight_approach")
            scene,kind=self._wait_known(scene,kind,"anomaly_straight_approach")
            if kind!="field_anomaly":
                return scene,kind
        raise AutomationError("异常区域直行接近达到上限，仍无可见交互提示；停止并保留进度。")

    def _avoid_optional_device(self,scene,field_kind,device):
        self.ctx.log('已识别可选设备挡路，后退并沿左侧有限绕行，再重新定位目标。')
        record={'run':self.report['current_run'],'device':device.text,
                'before':str(self.ctx.evidence(scene,'optional_device_before_detour'))}
        self.report.setdefault('device_detours',[]).append(record)
        self._persist_ledger()
        for direction,duration in (('s',500),('a',1100),('w',1100)):
            scene=self.ctx.differential_universe_move(scene,direction,duration)
            kind=self._observe(scene,'optional_device_detour_'+direction)
            scene,kind=self._wait_known(scene,kind,'optional_device_detour_'+direction)
            if kind!=field_kind:
                return scene,kind
        record['after']=str(self.ctx.evidence(scene,'optional_device_after_detour'))
        self._persist_ledger()
        return scene,kind

    def _field_anomaly_visual(self,scene,*,field_kind='field_anomaly'):
        from .du_navigation import event_targets,navigation_targets,random_gate,interaction_hint,optional_device_prompt
        from .du_detector import forward_barrier
        started,inactive_before=time.monotonic(),self._inactive()
        scans=recoveries=close_backoffs=0
        aligned_object_steps=0
        exit_ready=False
        interactions=0
        interaction_recovery=False
        unread_interaction_checks=0
        side_routes=0
        side_route_forward=False
        device_detours=0
        for step in range(64):
            self.ctx.checkpoint()
            prompt=self._field_interaction_target(scene)
            ignored_device=prompt is not None and prompt.text=='造物调试台' and self._forge_console_used
            if ignored_device:
                prompt=None
            portal=self._find(scene,("随意门",),(.25,.30,.78,.75))
            if prompt is not None or portal is not None:
                if interactions>=3:
                    raise AutomationError('三次实时交互提示操作后仍未离开场景，停止并保留位置。')
                interactions+=1
                scene=(self.ctx.differential_universe_interact(scene,prompt) if prompt is not None
                       else self.ctx.differential_universe_enter_random_gate(scene,portal))
                kind=self._observe(scene,"anomaly_visual_interaction")
                scene,kind=self._wait_known(scene,kind,"anomaly_visual_interaction")
                for _ in range(2):
                    if kind!=field_kind:
                        return scene,kind
                    self.ctx.sleep(.35)
                    scene,kind=self._snapshot('anomaly_visual_interaction_settled')
                    scene,kind=self._wait_known(scene,kind,'anomaly_visual_interaction_settled')
                if kind!=field_kind:
                    return scene,kind
                interaction_recovery=True
                continue
            # A just-reached live F prompt is observed progress, even when its
            # final movement/OCR frame straddled the search deadline. The
            # independent three-interaction cap still prevents repeating F.
            self._check_deadline(started,inactive_before,ROOM_TIMEOUT,"异常区域视觉接近")
            device=optional_device_prompt(scene,forge_console_used=self._forge_console_used)
            if device is not None:
                if device_detours:
                    raise AutomationError('已绕行一次，但可选设备仍占据交互范围；停止重复横移。')
                device_detours+=1
                scene,kind=self._avoid_optional_device(scene,field_kind,device)
                if kind!=field_kind:
                    return scene,kind
                aligned_object_steps=0
                continue
            if not ignored_device and interaction_hint(scene.image):
                if unread_interaction_checks>=2:
                    raise AutomationError('F提示已出现，但交互名称尚未核实；停止并保留当前位置。')
                # A reached interaction takes precedence over further travel.
                # Retry fresh OCR without stepping into the object or treating
                # the released movement as a blocked path to sidestep.
                self.ctx.sleep(.2)
                scene,kind=self._snapshot('anomaly_interaction_caption_recheck')
                unread_interaction_checks+=1
                scene,kind=self._wait_known(scene,kind,'anomaly_interaction_caption_recheck')
                if kind!=field_kind:
                    return scene,kind
                continue
            unread_interaction_checks=0
            landmark=random_gate(scene,fast=True)
            if landmark is not None:
                if landmark.text=='差分宇宙随意门外观':
                    exit_ready=True
                elif landmark.text=='差分宇宙睡眼门':
                    exit_ready=False
            # An awake door proves the required card is complete. Background
            # posters may look like cards; never let them steal the exit route.
            targets=(navigation_targets(scene,enemies=False) if exit_ready else
                     [target for target in event_targets(scene)
                      if target.text!='Device' or not self._forge_console_used])
            if side_route_forward:
                scene=self.ctx.differential_universe_move(scene,'w',850)
                side_route_forward=False
                kind=self._observe(scene,'anomaly_gate_side_cleared')
                scene,kind=self._wait_known(scene,kind,'anomaly_gate_side_cleared')
                if kind!=field_kind:
                    return scene,kind
                continue
            if (landmark is not None and landmark.text.endswith('背面')
                    and landmark.box[3]-landmark.box[1]>.35 and (exit_ready or not targets)):
                # This only repositions to inspect the face. A back never
                # establishes readiness or authorizes F; allow one side route.
                aligned_object_steps=0
                if abs(landmark.center[0]-.5)>.10:
                    delta=max(-.12,min(.12,(landmark.center[0]-.5)*.65))
                    scene=self.ctx.differential_universe_look(scene,delta,0,220)
                    label='anomaly_gate_back_aligned'
                elif side_routes<1:
                    scene=self.ctx.differential_universe_move(scene,'a',750)
                    side_routes+=1
                    side_route_forward=True
                    label='anomaly_gate_back_sidestep'
                else:
                    scene=self.ctx.differential_universe_look(scene,.16,0,400)
                    scans+=1
                    label='anomaly_gate_back_face_search'
                kind=self._observe(scene,label)
                scene,kind=self._wait_known(scene,kind,label)
                if kind!=field_kind:
                    return scene,kind
                continue
            if interaction_recovery and not targets and close_backoffs<2:
                # The just-approached frame can fill the view while its F hint
                # disappears. Undo a small part of that approach before seeking
                # a new live prompt; never replay F from the previous frame.
                scene=self.ctx.differential_universe_move(scene,'s',650)
                close_backoffs+=1
                interaction_recovery=False
                aligned_object_steps=0
                kind=self._observe(scene,'anomaly_interaction_backoff')
                scene,kind=self._wait_known(scene,kind,'anomaly_interaction_backoff')
                if kind!=field_kind:
                    return scene,kind
                continue
            if not targets and aligned_object_steps:
                # A card or confirmed awake gate just centred by the camera
                # can be hidden by the avatar or lose its angled detector box.
                # Permit at most 1.2 seconds with live HUD/barrier/F checks.
                aligned_object_steps-=1
                scene=self.ctx.differential_universe_motion(scene,'w',600,profile='occluded_card')
                kind=self._observe(scene,'anomaly_aligned_card_occlusion')
                scene,kind=self._wait_known(scene,kind,'anomaly_aligned_card_occlusion')
                if kind!=field_kind:
                    return scene,kind
                continue
            if targets:
                aligned_object_steps=0
            if exit_ready or not targets:
                doors=targets if exit_ready else navigation_targets(scene,enemies=False)
                nearby=min(doors,key=lambda t:abs(t.center[0]-.5),default=None)
                if nearby is not None and nearby.box[3]-nearby.box[1]>.65 and close_backoffs<2:
                    if abs(nearby.center[0]-.5)>.15:
                        delta=max(-.12,min(.12,(nearby.center[0]-.5)*.65))
                        scene=self.ctx.differential_universe_look(scene,delta,0,220)
                    else:
                        scene=self.ctx.differential_universe_move(scene,'s',700)
                        close_backoffs+=1
                    kind=self._observe(scene,'anomaly_near_gate_backoff')
                    scene,kind=self._wait_known(scene,kind,'anomaly_near_gate_backoff')
                    if kind!=field_kind:
                        return scene,kind
                    continue
            self.report.setdefault('navigation_observations',[]).append({
                'run':self.report['current_run'],'page':self._pages,'field_kind':field_kind,
                'gate_state':('awake' if exit_ready else 'sleeping' if landmark is not None
                              and landmark.text=='差分宇宙睡眼门' else 'back' if landmark is not None
                              and landmark.text.endswith('背面') else 'unknown'),
                'card_candidates':len(targets) if not exit_ready else 0,
                'targets':[{'label':t.text,'score':float(t.score),'box':[float(v) for v in t.box]} for t in targets]})
            goal=min(targets,key=(lambda t:abs(t.center[0]-.5)) if exit_ready else
                     (lambda t:(-t.score,abs(t.center[0]-.5))),default=None)
            if goal is None:
                if scans>=32:
                    raise AutomationError("异常区域原地搜索达到上限；未找到卡牌或门，未继续前进。")
                # A missing world target may be above a downward-tilted camera.
                # Adjust pitch once, then inspect a bounded horizontal sweep.
                scene=(self.ctx.differential_universe_look(scene,0,-.04,350) if scans==16
                       else self.ctx.differential_universe_look(scene,.16,0,400))
                scans+=1
                label="anomaly_stationary_search"
            elif abs(goal.center[0]-.5)>.05:
                delta=max(-.12,min(.12,(goal.center[0]-.5)*.65))
                if (goal.text in ('Card','Device') or exit_ready) and abs(goal.center[0]-.5-1.6*delta)<.07:
                    aligned_object_steps=2
                scene=self.ctx.differential_universe_look(scene,delta,0,220)
                label="anomaly_target_aligned"
            else:
                barrier=forward_barrier(scene.image)
                if barrier is not None and abs(barrier.center[0]-goal.center[0])<.12:
                    scene=self.ctx.differential_universe_look(scene,.16,0,400)
                    scans+=1
                    kind=self._observe(scene,'anomaly_barrier_avoided')
                    scene,kind=self._wait_known(scene,kind,'anomaly_barrier_avoided')
                    if kind!=field_kind:
                        return scene,kind
                    continue
                duration=400 if goal.score==.86 else 4000
                scene=self.ctx.differential_universe_motion(scene,"w",duration,profile="anomaly")
                label="anomaly_target_approach"
                result=getattr(self.ctx,"_du_motion_result",{})
                if isinstance(result,dict) and result.get("reason")=="background_stalled":
                    if recoveries>=2:
                        raise AutomationError("异常区域两次脱困无进展，停止顶墙并保留位置。")
                    scene=self.ctx.differential_universe_move(scene,"s",650)
                    recoveries+=1
                    label="anomaly_stall_backed_out"
                    kind=self._observe(scene,label)
                    scene,kind=self._wait_known(scene,kind,label)
                    if kind!=field_kind:
                        return scene,kind
                    scene=self.ctx.differential_universe_move(scene,'d' if recoveries==1 else 'a',650 if recoveries==1 else 1300)
                    label='anomaly_stall_side_cleared'
            kind=self._observe(scene,label)
            scene,kind=self._wait_known(scene,kind,label)
            if kind!=field_kind:
                return scene,kind
        raise AutomationError("异常区域视觉导航达到上限，已停止并保留进度。")

    def _save_victory(self,scene):
        from .du_saves import next_name,empty_slot,management,rename_dialog
        entry=self.report['run_results'][-1]
        target=scene.find('记录本次存档',(.50,.85,.75,.97),exact=True)
        if target is None:
            raise AutomationError('通关页没有核实到记录本次存档按钮。')
        scene,kind=self._click(scene,target,intent='du_save_open',label='save_management')
        if not management(scene):
            raise AutomationError('记录存档后未进入存档管理。')
        name=next_name(scene)
        slot=empty_slot(scene)
        if slot is None:
            entry.update(save_status='skipped_full',save_name=None)
            self.ctx.log('存档槽已满，本局跳过保存。')
        else:
            scene,kind=self._click(scene,slot,intent='du_save_slot',label='save_empty_slot')
            target=scene.find('保存本轮数据',(.46,.62,.70,.74),exact=True)
            if target is None:
                raise AutomationError('空存档槽未显示保存本轮数据按钮。')
            scene,kind=self._click(scene,target,intent='du_save_create',label='save_name_dialog')
            if not rename_dialog(scene):
                raise AutomationError('未核实更改存档名窗口。')
            target=Token('存档名输入框',1,(.31,.47,.69,.50))
            scene,kind=self._click(scene,target,intent='du_save_focus',label='save_name_focused')
            scene=self.ctx.differential_universe_save_name(scene,name)
            scene=self.ctx.wait(lambda page:rename_dialog(page) and page.has(name,(.30,.46,.70,.51),exact=True),
                                timeout=15,description='存档名输入核实')
            confirm=scene.find('确认',(.51,.58,.72,.67),exact=True)
            scene,kind=self._click(scene,confirm,intent='du_save_confirm',label='save_name_confirmed')
            scene=self.ctx.wait(lambda page:management(page) and page.has(name,(.01,.14,.18,.65),exact=True)
                                and page.has(name,(.21,.09,.60,.15),exact=True),
                                timeout=20,description='存档列表与详情名称核实')
            entry.update(save_status='saved',save_name=name,save_evidence=str(self.ctx.evidence(scene,'du_archive_saved')))
        self.ctx.key('esc')
        scene,kind=self._snapshot('save_management_closed')
        scene,kind=self._wait_known(scene,kind,'save_management_closed')
        if kind!='victory':
            raise AutomationError('关闭存档管理后未回到通关结算。')
        return scene,kind

    def _settled_field_entry(self,scene,kind):
        from .du_navigation import field_frame_ready
        if scene.image is None:
            return scene,kind
        stable=0
        for _ in range(8):
            stable=stable+1 if field_frame_ready(scene) else 0
            if stable>=2:
                return scene,kind
            self.ctx.sleep(.2)
            scene,current=self._snapshot('field_entry_fade_recheck')
            scene,current=self._wait_known(scene,current,'field_entry_fade_recheck')
            if current!=kind:
                return scene,current
        raise AutomationError('进场画面仍在淡入，未转动镜头或移动角色。')

    def _progress_run(self, scene: Scene, kind: str) -> tuple[Scene, str, bool]:
        victory_seen = False
        started,inactive_before=time.monotonic(),self._inactive()
        for step in range(1, 241):
            try:
                self.ctx.checkpoint()
                self._check_deadline(started,inactive_before,RUN_TIMEOUT,"单局演算")
                kind = classify_page(scene, self.ctx)
                if kind == "unknown":
                    scene, kind = self._wait_known(scene, kind, "run")
                if kind == "blocked":
                    raise AutomationError("识别到商店、合成或体力/星琼提示，差分宇宙运行已停止。")
                if kind == "defeat":
                    raise AutomationError("差分宇宙已失败，未将本局计为完成。")
                if kind == 'login_supply':
                    scene, kind = self._settle_supply(scene)
                    continue
                if kind == 'forge_console':
                    scene=self.ctx.differential_universe_close_forge(scene)
                    card_fields=('field_anomaly','field_reward','field_event','field_forge',
                                 'field_shop','field_wealth','field_adventure')
                    scene=self.ctx.wait(lambda page:classify_page(page,self.ctx) in card_fields,
                                        timeout=15,description='关闭造物调试台返回当前位面')
                    self._forge_console_used=True
                    scene=self.ctx.differential_universe_move(scene,'s',1000)
                    kind=self._observe(scene,'forge_console_left')
                    scene,kind=self._wait_known(scene,kind,'forge_console_left')
                    continue
                if kind == "curio_discard":
                    target=self._choice_target(scene,kind)
                    if target is None:
                        raise AutomationError("强制舍弃奇物页未识别到卡片候选，未操作。")
                    scene,kind=self._click(scene,target,intent="curio_discard_select",label="curio_discard_selected")
                    if kind != "curio_discard":
                        continue
                    confirm=self._find(scene,("丢弃","丢弃·"),(.78,.85,.99,.96))
                    if confirm is None:
                        raise AutomationError("强制舍弃奇物选中后未识别到丢弃按钮。")
                    scene,kind=self._click(scene,confirm,intent="curio_discard_confirm",label="curio_discard_confirmed")
                    if kind == "curio_discard":
                        scene=self.ctx.wait(lambda s:classify_page(s,self.ctx)!="curio_discard",
                                            timeout=15,description="强制舍弃奇物完成")
                        kind=self._observe(scene,"curio_discard_applied")
                    continue
                if kind=='blessing_discard':
                    scene,kind=self._select_blessing(scene,discard=True)
                    target=self._find(scene,('丢弃',),(.56,.78,.99,.98))
                    if target is None:
                        raise AutomationError('舍弃祝福未核实丢弃按钮。')
                    scene,kind=self._click(scene,target,intent='blessing_discard_confirm',label='blessing_discarded')
                    if kind=='blessing_discard':
                        scene=self.ctx.wait(lambda page:classify_page(page,self.ctx)!='blessing_discard',
                            timeout=15,description='核实一星祝福舍弃完成')
                        kind=self._observe(scene,'blessing_discard_applied')
                    continue
                if kind=='blessing_discard_prompt':
                    from .policy import du_blessing_discard_prompt
                    expected=(self.report.get('reward_decisions') or [{}])[-1]
                    if not expected.get('discard') or expected.get('selected')!=du_blessing_discard_prompt(scene):
                        raise AutomationError('未找到本次一星祝福预览与同名舍弃证据，未确认弹窗。')
                    confirm=scene.find('确认',(.51,.58,.71,.67),exact=True)
                    scene,kind=self._click(scene,confirm,intent='blessing_discard_prompt_confirm',label='blessing_discard_prompt_confirmed')
                    if kind=='blessing_discard_prompt':
                        scene=self.ctx.wait(lambda page:classify_page(page,self.ctx)!='blessing_discard_prompt',
                            timeout=15,description='核实一星祝福提交完成')
                        kind=self._observe(scene,'blessing_trade_completed')
                    continue
                if kind == "victory":
                    victory_seen = True
                    self.report["run_results"][-1]["victory_evidence"] = str(self.ctx.evidence(scene, f"du_{self.report['current_run']:02d}_victory"))
                    if (self.settings.differential_universe_save and not scene.has('本局已存档')
                            and not self.report['run_results'][-1].get('save_attempted')):
                        self.report['run_results'][-1]['save_attempted']=True
                        scene,kind=self._save_victory(scene)
                        continue
                    target = self._find(scene, FINAL_RETURN_LABELS, (0.28, 0.65, 1, 1))
                    if target is None:
                        raise AutomationError("最终胜利页未识别到返回差分宇宙按钮。")
                    scene, kind = self._click(scene, target, label="victory_return")
                    continue
                if kind == "battle":
                    scene, kind = self._battle(scene)
                    if kind in ('field_combat','node_victory','victory','blessing_choice',
                                'equation_choice','curio_choice','miracle_choice','mask_reward_overlay'):
                        self._field_cleared=True
                    continue
                if kind.startswith('field_') and self._fresh_field_entry:
                    scene,current=self._settled_field_entry(scene,kind)
                    if current!=kind:
                        kind=current
                        continue
                if kind == "field_combat":
                    fresh_entry=self._fresh_field_entry
                    self._fresh_field_entry=False
                    scene, kind = self._field_combat(scene,fresh_entry=fresh_entry)
                    continue
                if kind in ("field_anomaly","field_reward","field_event","field_shop","field_wealth","field_forge","field_adventure"):
                    fresh_entry=self._fresh_field_entry
                    self._fresh_field_entry=False
                    scene, kind = self._field_anomaly(scene,fresh_entry=fresh_entry)
                    continue
                if kind in ("field_rest","field_blank"):
                    self._fresh_field_entry=False
                    scene, kind = self._field_visual(scene,field_kind=kind)
                    continue
                if kind == "shop":
                    scene, kind = self._leave_area(scene, "shop")
                    continue
                if kind == "synthesis":
                    scene, kind = self._leave_area(scene, "synthesis")
                    continue
                if kind == "event":
                    scene,kind=self._event(scene)
                    continue
                if kind == "rest":
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
                if kind == "miracle_target":
                    effect=station_card_effect(scene)
                    if effect is not None and effect.entry_triggered:
                        self._fresh_field_entry=True
                        self._field_cleared=False
                    scene,kind=self._apply_miracle_target(scene)
                    continue
                if kind == "area_choice":
                    scene,target = self._loaded_area_choice(scene)
                    scene, kind = self._click(scene, target, intent="area_select", label="area_selected")
                    if kind == "area_choice":
                        confirm = self._find(scene, ("确认选择", "确认", "确定", "进入区域"),
                                             (0.48, 0.66, 1, 1))
                        if confirm is None:
                            raise AutomationError("区域候选点选后仍停留在选择页且没有确认按钮。")
                        from .policy import du_recruitment_candidates
                        intent='area_recruit_confirm' if du_recruitment_candidates(scene) else 'navigation'
                        scene, kind = self._click(scene, confirm, intent=intent, label="area_confirmed")
                    continue
                if kind == "station_choice":
                    action=self._station_target(scene)
                    if action is None:
                        scene=self.ctx.wait(lambda page:classify_page(page,self.ctx)=="station_choice"
                            and self._station_target(page) is not None,timeout=15,description="站点卡动画与候选加载")
                        action=self._station_target(scene)
                    target,intent=action
                    station_name = normalize(target.text)
                    scene, kind = self._click(scene, target, intent=intent,
                                              label=station_name + "_station_selected")
                    self._fresh_field_entry=True
                    self._field_cleared=False
                    self._forge_console_used=False
                    self._combat_chest_attempts=0
                    if kind != "station_choice":
                        continue
                    scene,kind=self._safer_station_preview(scene,target)
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
                        scene,kind=self._confirm_choice(scene,choice_kind)
                        continue
                    target = self._choice_target(scene, kind)
                    if target is None:
                        # Reward headings can appear before cards finish sliding
                        # in. Observe their contents before selecting a candidate.
                        scene=self.ctx.wait(lambda s:classify_page(s,self.ctx)==choice_kind
                            and self._choice_target(s,choice_kind) is not None,
                            timeout=15,description=choice_kind+"候选加载")
                        target=self._choice_target(scene,choice_kind)
                    if choice_kind=="blessing_choice":
                        scene,kind=self._select_blessing(scene)
                    else:
                        scene, kind = self._click(scene, target, intent="choice", label=kind + "_selected")
                    if kind == choice_kind:
                        scene,kind=self._confirm_choice(scene,choice_kind)
                    continue
                if kind == "tutorial_overlay":
                    scene, kind = self._close_tutorial(scene)
                    continue
                if kind == "mask_reward_overlay":
                    target = Token("点击空白处关闭", 1.0, (0.47, 0.80, 0.56, 0.88))
                    scene, kind = self._click(scene, target, intent="dismiss_mask_reward", label="mask_reward_closed")
                    continue
                if kind == "team_setup":
                    raise AutomationError("此队伍页尚未核实预设编队入口，未直接确认出战；所有选角必须从预设编队完成。")
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
            except InputInterrupted:
                self.ctx.checkpoint()
                scene, kind = self._snapshot("input_interrupted_refresh")
                self.ctx.log("操作被暂停或焦点切换中断，已重新识别当前页面。")
        raise AutomationError("差分宇宙单局超过 240 个已识别步骤，已停止。")

    def run(self) -> TaskResult:
        scene, kind = self._snapshot("initial")
        if self.resume_active and kind == "home":
            target=scene.find("开始游戏",(.68,.72,1,1),exact=True)
            if target is None:
                raise AutomationError("接续前未核实差分宇宙主页入口。")
            scene,kind=self._click(scene,target,label="resume_mode_menu")
        if self.resume_active and kind == "mode_select":
            scene=self.ctx.wait(lambda s:s.has("继续进度",exact=True),timeout=15,description="已有进度入口就绪")
            target=scene.find("继续进度",(.18,.64,.42,.76),exact=True)
            if target is None or not scene.has("进行中"):
                raise AutomationError("模式页没有核实到进行中的继续进度按钮，未接续。")
            scene,kind=self._click(scene,target,intent="du_resume_menu",label="resumed_existing_save")
        if self.resume_active and kind == "resume_confirm":
            target=scene.find("确认",(.51,.58,.71,.67),exact=True)
            if target is None:
                raise AutomationError("过期演算接续提示没有核实到确认按钮。")
            scene,kind=self._click(scene,target,intent="du_resume_confirm",label="resume_expired_confirmed")
        resumable = {"battle", "route", "team_setup", "equation_choice", "blessing_choice",
                     "curio_choice", "mask_choice", "mask_detail", "miracle_choice", "station_choice",
                     "tutorial_overlay", "field_combat", "field_anomaly", "node_victory", "victory", "area_choice"}
        resumable.add("mask_reward_overlay")
        resumable.add("miracle_target")
        resumable.add("curio_discard")
        resumable.add("blessing_discard")
        resumable.add("event")
        resumable.add("field_rest")
        resumable.add("field_shop")
        resumable.add("field_wealth")
        resumable.update(('field_blank','field_forge','field_adventure'))
        resumable.add("field_reward")
        resumable.add("field_event")
        resumable.add('login_supply')
        resumable.add('forge_console')
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
            scene,kind=self._after_completed_run(scene,kind,'rewards_after_resumed_run')
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
        if self.settings.differential_universe_rewards and kind=='home':
            scene,kind=self._collect_rewards(scene,kind,'rewards_before_runs')
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
            # The initial room has the same guaranteed entrance heading as a
            # selected station; mask/tutorial overlays do not invalidate it.
            self._fresh_field_entry = True
            self._field_cleared = False
            self._forge_console_used = False
            self._combat_chest_attempts = 0
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
            scene,kind=self._after_completed_run(scene,kind,'rewards_after_run')
            if run_no < self.runs:
                # Do not continue an in-progress run; a fresh, completed return
                # to the mode page is required before the next start.
                scene, kind = self._snapshot("between_runs")
        if self.report.get("mode") == "周期演算":
            self.report["last_message"] = f"{self.runs} 局周期演算均确认胜利结算并返回。"
        else:
            self.report["last_message"] = f"{self.runs} 局新开难度 I 均确认胜利结算并返回。"
        return TaskResult(TASK, "ok", self.report["last_message"])
