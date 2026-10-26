from __future__ import annotations

import ctypes as C
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
import time
from datetime import datetime

from .config import ROOT, RESOURCE_ROOT, Settings
from .models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, RunReport, Scene, Stopped, TaskResult, Token, normalize
from .vision import Vision, save_scene,helper_overlay
from .ocr_isolation import IsolatedVision
from .windows import find_game, is_admin, is_elevated, launch
from .storage import replace_file


def launch_game(settings: Settings) -> str:
    settings.validate("launch")
    return launch(settings.game_path)


def inspect_game(settings: Settings) -> dict:
    settings.validate("check")
    window = find_game(settings.game_path)
    window.focus()
    vision = Vision(settings.ocr_confidence)
    image, geometry = window.capture()
    scene = vision.read(image, geometry)
    output = ROOT / "runs" / ("check_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    screenshot = save_scene(scene, output, "screen")
    result = dict(window=window.hwnd, title=window.title, width=geometry.width, height=geometry.height,
                  administrator=is_admin(), game_elevated=is_elevated(window.hwnd), ocr_text=scene.text, screenshot=str(screenshot))
    from .ux import input_readiness
    result["input_ready"] = input_readiness(result["administrator"], result["game_elevated"])
    result["input_hint"] = ("游戏以管理员运行，请在设置启用管理员免重复确认启动后重开助手，或用管理员启动器。" if result["input_ready"] is False else
                            "游戏进程权限未能读取，输入条件尚未核实。" if result["input_ready"] is None else "权限匹配，输入效果仍未实测。")
    (output / "check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


class Context:
    def __init__(self, runner: Runner, window, vision):
        self.runner, self.window, self.vision = runner, window, vision
        self.settings, self.report = runner.settings, runner.report
        self.last_scene: Scene | None = None
        self.scene_epoch = 0
        self._scroll_anchor = None
        self._currency_deploy_request = None
        self._currency_equipment_request = None
        self._currency_position_request = None
        self._du_actions = []

    def log(self, message: str, level="info"):
        self.runner.log(message, level)

    def checkpoint(self):
        self.runner.checkpoint()

    def sleep(self, seconds: float):
        remaining = seconds
        while remaining > 0:
            self.checkpoint()
            interval = min(0.1, remaining)
            start = time.monotonic()
            time.sleep(interval)
            remaining -= time.monotonic() - start
        self.checkpoint()

    def snapshot(self) -> Scene:
        occluded_frames=0
        while True:
            self.checkpoint()
            self.last_scene = None
            self._scroll_anchor = None
            capture_epoch = self.runner.input_epoch
            captured_at = time.monotonic()
            try:
                image, geometry = self.window.capture()
                scene = self.vision.read(image, geometry)
                if helper_overlay(scene):
                    occluded_frames+=1
                    if occluded_frames==1:
                        self.evidence(scene,'helper_occlusion_discarded')
                        self.log('截图仍有助手界面遮挡，丢弃此帧并重新识别。')
                    if occluded_frames>=8:
                        raise AutomationError('连续截图被助手界面遮挡，未按游戏画面发送输入。')
                    self.sleep(.2)
                    continue
                if self.report.operation == "differential_universe":
                    self.vision.refine_du_field_header(scene)
                    self.vision.refine_du_blessing_names(scene)
                    if self.settings.differential_universe_rewards:
                        self.vision.refine_du_reward_balance(scene)
                elif self.report.operation == 'daily' and self.settings.daily_synthesis:
                    self.vision.refine_daily_synthesis(scene)
                scene.captured_at = captured_at
                self.checkpoint()
                if capture_epoch != self.runner.input_epoch:
                    self.last_scene = None
                    continue
                self.window.guard(geometry)
            except FocusLost:
                self.last_scene = None
                self.runner.wait_for_focus(self.window)
                continue
            self.last_scene = scene
            self.scene_epoch = capture_epoch
            return scene

    def _focus_interrupted(self):
        self.last_scene = None
        self._scroll_anchor = None
        self.runner.wait_for_focus(self.window)
        raise InputInterrupted("焦点恢复后须重新识别，旧输入目标已丢弃。")

    def _require_gameplay_input(self):
        if self.report.operation.startswith("currency_wars"):
            raise AutomationError("货币战争当前仅允许只读识别，禁止发送游戏输入。")

    def currency_prepare_click(self, scene, intent, target):
        if self.report.operation != 'currency_wars_prepare':
            raise AutomationError('当前任务不允许货币战争启动准备输入。')
        from .currency_wars import CurrencyWarsWorkflow
        from .currency_wars_prepare import click_target
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        if click_target(scene, self.settings.ocr_confidence) != (intent, target):
            raise AutomationError('启动准备目标已改变，未输入。')
        self.last_scene, self._scroll_anchor = None, None
        try:
            self.window.click(*target.center, scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_prepare_back(self, scene):
        if self.report.operation != 'currency_wars_prepare':
            raise AutomationError('当前任务不允许启动准备返回。')
        from .currency_wars import CurrencyWarsWorkflow
        from .currency_wars_prepare import key_allowed
        from .workflows import DailyWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        workflow = DailyWorkflow(self)
        if (not key_allowed(scene, self.settings.ocr_confidence) and not workflow._world(scene)
                or workflow._in_battle(scene)):
            raise AutomationError('当前不是可返回的已核实菜单。')
        self.last_scene, self._scroll_anchor = None, None
        try:
            self.window.key('esc')
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def click(self, scene: Scene, target: Token | tuple[float, float], *, du_intent="navigation"):
        self._require_gameplay_input()
        self.checkpoint()
        if self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("暂停恢复后须重新识别，未发送旧画面点击。")
        if scene is not self.last_scene or time.monotonic() - scene.captured_at > 8:
            raise AutomationError("识别画面已经过期，请重新识别后操作。")
        from .policy import guard_click, guard_differential_universe_click, replenishment_dialog
        if self.report.operation == "differential_universe":
            if du_intent=='blessing_discard_prompt_confirm':
                from .policy import du_blessing_discard_prompt
                expected=(self.report.differential_universe.get('reward_decisions') or [{}])[-1]
                if not expected.get('discard') or expected.get('selected')!=du_blessing_discard_prompt(scene):
                    raise AutomationError('舍弃确认框与本次预览选中的祝福不一致，未确认。')
            if du_intent.startswith('du_team_'):
                from .du_team import guard_click as guard_team_click
                guard_team_click(scene,target,du_intent,self.settings.differential_universe_team)
            if du_intent=='du_mode_select':
                expected='周期演算' if self.settings.differential_universe_mode=='periodic' else '常规演算'
                if normalize(target.text)!=normalize(expected):
                    raise AutomationError('演算入口与配置模式不一致，未选择。')
            guard_differential_universe_click(scene, target, intent=du_intent)
        elif du_intent.startswith('daily_synthesis_'):
            if self.report.operation != 'daily' or not self.settings.daily_synthesis:
                raise AutomationError('日常合成仅用于已开启的每日实训补足步骤。')
            from .daily_synthesis import guard_click as guard_synthesis_click
            guard_synthesis_click(scene, target, du_intent, self.report.daily_synthesis)
        elif du_intent.startswith('planar_team_'):
            if self.report.operation != 'daily' or self.settings.dungeon_category != 'planar':
                raise AutomationError('饰品提取预设选角仅用于该副本日常流程。')
            from .planar_team import guard_click as guard_planar_team_click
            guard_planar_team_click(scene, target, du_intent, self.settings.differential_universe_team)
        else:
            guard_click(scene, target, allow_differential_universe=self.report.operation == "differential_universe")
        coordinates = target.center if isinstance(target, Token) else target
        resource_dialog = replenishment_dialog(scene)
        if resource_dialog and (not isinstance(target, Token) or target.text.strip() != "取消"):
            self.evidence(scene, "resource_dialog")
            raise AutomationError("开拓力补充/兑换界面只允许取消，已禁止该操作。")
        label = target.text if isinstance(target, Token) else f"{coordinates[0]:.3f},{coordinates[1]:.3f}"
        self.log(f"点击：{label}")
        du_record = None
        if self.report.operation == "differential_universe":
            before = self.evidence(scene, "du_before_" + re.sub(r"[^\w\u3400-\u9fff-]", "_", label)[:32])
            du_record = {"action": label, "status": "sent", "before": str(before), "page_text": scene.text}
            self.report.differential_universe.setdefault("actions", []).append(du_record)
        try:
            self.window.click(*coordinates, scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.last_scene = None
        self.sleep(self.settings.action_delay)
        if du_record is not None:
            after = self._snapshot_after_du_input()
            after_path = self.evidence(after, "du_after_action")
            du_record["after"] = str(after_path)
            du_record["after_text"] = after.text

    def _snapshot_after_du_input(self, timeout=60):
        """Observe after a Differential Universe input, retrying blank transition frames."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return self.snapshot()
            except EmptyCapture:
                if time.monotonic() >= deadline:
                    raise AutomationError(f"差分宇宙操作后持续黑屏超过 {timeout} 秒，已停止输入。")
                self.sleep(.7)

    def key(self, name: str):
        self._require_gameplay_input()
        self.checkpoint()
        if self.report.operation == "differential_universe" and name != "esc":
            raise AutomationError("差分宇宙仅允许在启动前关闭已识别的规则弹窗；其他按键未授权。")
        if name not in ("esc", "f4"):
            raise AutomationError("日常流程仅允许返回键和指南快捷键；其他快捷键被禁止。")
        if self.last_scene is None or self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("按键前画面已失效，需要重新识别当前页面。")
        try:
            self.window.key(name)
        except FocusLost:
            self._focus_interrupted()
        self.last_scene = None
        self.sleep(self.settings.action_delay)

    def differential_universe_auto_click(self, scene: Scene, point: tuple[float, float], verifier):
        if self.report.operation != "differential_universe":
            raise AutomationError("自动战斗图标点击仅用于差分宇宙运行。")
        self.checkpoint()
        if scene is not self.last_scene or self.scene_epoch != self.runner.input_epoch or time.monotonic() - scene.captured_at > 8:
            raise InputInterrupted("自动战斗图标位置已过期，需要重新识别。")
        state, target = verifier._auto_state(scene)
        if state != "off" or target is None or tuple(target) != tuple(point):
            raise AutomationError("自动战斗开关没有在当前画面确认关闭，未发送点击。")
        before = self.evidence(scene, "du_before_auto_battle")
        self.last_scene = None
        try:
            self.window.click(*point, scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)
        after = self._snapshot_after_du_input()
        after_state, _ = verifier._auto_state(after)
        after_path = self.evidence(after, "du_after_auto_battle")
        record = {"action": "enable_auto_battle", "status": "verified" if after_state == "on" else "unknown",
                  "before": str(before), "after": str(after_path), "before_text": scene.text,
                  "after_text": after.text, "state": after_state}
        self.report.differential_universe.setdefault("actions", []).append(record)
        if after_state != "on":
            raise AutomationError("未能核实自动战斗已开启，已停止本轮。")
        return after

    def _persist_du_ledger(self):
        if self.report.operation != "differential_universe" or not self.report.run_dir:
            return
        import json
        root = Path(self.report.run_dir)
        ledger = root / "differential-universe-ledger.json"
        du = self.report.differential_universe
        payload = {
            "schema_version": 1,
            "session_id": du.get("session_id"),
            "updated_at": datetime.now().astimezone().isoformat(),
            "requested_runs": du.get("requested_runs", 0),
            "completed_runs": du.get("completed_runs", 0),
            "current_run": du.get("current_run", 0),
            "run_results": du.get("run_results", []),
            "actions": du.get("actions", []),
            "page_history": du.get("page_history", []),
            "team_selections": du.get("team_selections", []),
            "reward_collection": du.get("reward_collection"),
            "navigation_observations": du.get('navigation_observations',[]),
        }
        import uuid
        temp = ledger.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            replace_file(temp,ledger)
            du["ledger_path"] = str(ledger)
        except OSError as error:
            raise AutomationError(f"差分宇宙证据台账无法落盘，已禁止后续操作：{error}") from error

    def _du_observed_input(self, scene: Scene, action: str, perform, *, guard):
        if self.report.operation != "differential_universe":
            raise AutomationError("位面探索输入只用于差分宇宙。")
        self.checkpoint()
        if (self.scene_epoch != self.runner.input_epoch or scene is not self.last_scene
                or not 0 <= time.monotonic() - scene.captured_at <= 8):
            raise InputInterrupted("位面探索目标画面已过期，须重新识别后再操作。")
        guard(scene)
        before = self.evidence(scene, "du_before_" + action)
        record = {"action": action, "status": "requested", "before": str(before),
                  "before_text": scene.text, "run": self.report.differential_universe.get("current_run", 0),
                  "run_id": (self.report.differential_universe.get("run_results") or [{}])[-1].get("run_id")}
        self.report.differential_universe.setdefault("actions", []).append(record)
        self._persist_du_ledger()
        self.last_scene = None
        try:
            input_result=perform()
            if isinstance(input_result,dict):
                record["input_result"]=input_result
        except FocusLost:
            self._focus_interrupted()
        after = self._snapshot_after_du_input(timeout=20)
        after_path = self.evidence(after, "du_after_" + action)
        record.update(status="observed", after=str(after_path), after_text=after.text)
        self.report.differential_universe["actions"][-1] = record
        self._persist_du_ledger()
        return after

    def _du_field_input(self, scene: Scene, action: str, perform):
        from .policy import guard_differential_universe_field_input
        return self._du_observed_input(scene,action,perform,
            guard=lambda page:guard_differential_universe_field_input(page,action=action))

    def differential_universe_close_team(self, scene: Scene):
        from .du_team import enabled
        def guard(page):
            if not enabled(page,self.settings.differential_universe_team):
                raise AutomationError('指定预设编队未启用，未关闭选角。')
        return self._du_observed_input(scene,'preset_team_close',
            lambda:self.window.key('esc'),guard=guard)

    def differential_universe_close_forge(self, scene: Scene):
        from .policy import du_forge_console_menu
        def guard(page):
            if not du_forge_console_menu(page):
                raise AutomationError('未核实造物调试台装配菜单，未关闭。')
        return self._du_observed_input(scene,'forge_console_close',
            lambda:self.window.key('esc'),guard=guard)

    def differential_universe_close_coin_counter(self, scene: Scene):
        from .policy import du_coin_counter_menu
        def guard(page):
            if not du_coin_counter_menu(page):
                raise AutomationError('未核实乐园币柜台交易菜单，未关闭。')
        return self._du_observed_input(scene,'coin_counter_close',
            lambda:self.window.key('esc'),guard=guard)

    def differential_universe_dialogue(self, scene: Scene, target: Token):
        import cv2
        from .du_navigation import event_next
        from .policy import guard_differential_universe_click
        def header(image):
            h,w=image.shape[:2]
            return cv2.cvtColor(cv2.resize(image[round(.025*h):round(.10*h),round(.02*w):round(.12*w)],
                                          (200,85)),cv2.COLOR_BGR2GRAY)
        reference=header(scene.image)
        check=self._du_held_checkpoint(scene)
        def observe():
            pixels,geometry=self.window.capture()
            check()
            if geometry!=scene.geometry:
                raise InputInterrupted("对话连点期间窗口位置或大小改变。")
            score=float(cv2.matchTemplate(header(pixels),reference,cv2.TM_CCOEFF_NORMED)[0,0])
            if score<.90:
                return None
            match=event_next(Scene([],image=pixels))
            return match[:2] if match is not None else None
        return self._du_observed_input(scene,"event_dialogue_burst",
            lambda:self.window.dialogue_burst(scene.geometry,checkpoint=check,observe=observe),
            guard=lambda page:guard_differential_universe_click(page,target,intent="event_advance"))

    def differential_universe_move(self, scene: Scene, direction: str, duration_ms: int):
        if direction.casefold() not in ("w", "a", "s", "d"):
            raise AutomationError("差分宇宙移动方向只允许 W/A/S/D。")
        self._du_background_progress=None
        return self._du_field_input(
            scene, f"move_{direction.casefold()}_{duration_ms}ms",
            lambda: self.window.key_hold(direction, duration_ms, scene.geometry,
                                         checkpoint=self._du_held_checkpoint(scene)))

    def differential_universe_motion(self, scene: Scene, action: str, duration_ms: int,
                                     *, profile="forward", watch_gate=True):
        from .du_navigation import FieldMotionWatch
        watch=FieldMotionWatch(scene,self.vision,profile=profile,watch_gate=watch_gate)
        # Keep the two-second world-motion observation across short near-door
        # steps. A camera adjustment or explicit recovery move resets it.
        if watch.progress is not None:
            progress=getattr(self,"_du_background_progress",None)
            if progress is None:
                self._du_background_progress=watch.progress
            else:
                watch.progress=progress
        check=self._du_held_checkpoint(scene)
        frames=[]
        next_frame=0
        frame_id=datetime.now().strftime("%H%M%S_%f")
        def observe():
            nonlocal next_frame
            image,geometry=self.window.capture()
            check()
            if geometry!=scene.geometry:
                raise InputInterrupted("连续探索期间窗口位置或大小改变。")
            if action=="scan_right" and time.monotonic()>=next_frame:
                import cv2
                root=Path(self.report.run_dir)/"continuous-navigation"
                root.mkdir(exist_ok=True)
                sample=cv2.resize(image,(960,round(image.shape[0]*960/image.shape[1])))
                sample[-20:]=0  # Exclude the account identifier from scan samples.
                path=root/f"{frame_id}_{len(frames):02d}.png"
                cv2.imencode(".png",sample)[1].tofile(str(path))
                frames.append(str(path))
                next_frame=time.monotonic()+1
            return watch(image)
        def perform():
            result=self.window.field_motion(action,duration_ms,scene.geometry,
                                            checkpoint=check,observe=observe)
            result["scan_samples"]=frames
            if result.get('reason')=='gate_landmark' and watch.gate_target is not None:
                self._du_gate_reference=(Scene(scene.tokens,watch.gate_frame,scene.geometry),
                                         watch.gate_target,time.monotonic())
                result['gate_target']={'box':list(watch.gate_target.box),'score':float(watch.gate_target.score)}
            if result.get('reason')=='attack_reticle' and watch.attack_target is not None:
                result['attack_target']={'box':list(watch.attack_target.box),
                                         'score':float(watch.attack_target.score)}
                import cv2
                root=Path(self.report.run_dir)/'continuous-navigation'
                root.mkdir(exist_ok=True)
                sample=cv2.resize(watch.attack_frame,(960,round(watch.attack_frame.shape[0]*960/watch.attack_frame.shape[1])))
                sample[round(.963*sample.shape[0]):]=0
                path=root/f'{frame_id}_attack_range.png'
                cv2.imencode('.png',sample)[1].tofile(str(path))
                result['attack_evidence']=str(path)
            self._du_motion_result=result
            return result
        return self._du_field_input(scene,f"continuous_{action}_{duration_ms}ms",perform)

    def _du_held_checkpoint(self, scene):
        epoch = self.scene_epoch
        def check():
            if self.runner._stop.is_set():
                raise Stopped("任务已停止。")
            if self.runner._pause.is_set() or self.runner.input_epoch != epoch:
                raise InputInterrupted("差分宇宙探索输入已中断，恢复后需重新识别。")
            self.window.guard(scene.geometry)
        return check

    def differential_universe_look(self, scene: Scene, delta_x: float, delta_y: float = 0,
                                   duration_ms: int = 250):
        self._du_background_progress=None
        label = f"look_{delta_x:+.2f}_{delta_y:+.2f}"
        return self._du_field_input(
            scene, label,
            lambda: self.window.look(delta_x, delta_y, duration_ms, scene.geometry,
                                     checkpoint=self._du_held_checkpoint(scene)))

    def differential_universe_enter_random_gate(self, scene: Scene, target: Token):
        from .policy import guard_differential_universe_portal
        guard_differential_universe_portal(scene, target)
        return self._du_field_input(scene, "enter_random_gate_f", lambda: self.window.key("f"))

    def differential_universe_switch_character(self,scene: Scene,slot: int):
        from .du_navigation import attack_reticle
        if type(slot) is not int or slot not in (1,2,3,4):
            raise AutomationError("接战切换只允许当前队伍的 1–4 号角色。")
        if not scene.has("等级",(.38,.01,.64,.10)) or attack_reticle(scene) is None:
            raise AutomationError("未核实敌人信息条与攻击圆环，未切换接战角色。")
        return self._du_field_input(scene,f"switch_party_{slot}",lambda:self.window.key(str(slot)))

    def differential_universe_save_name(self,scene: Scene,name: str):
        from .du_saves import guard_name
        if not self.settings.differential_universe_save:
            raise AutomationError('保存通关存档开关未打开。')
        return self._du_observed_input(scene,'save_archive_name',
            lambda:self.window.type_du_save_name(name,scene.geometry,checkpoint=self._du_held_checkpoint(scene)),
            guard=lambda page:guard_name(page,name))

    def differential_universe_attack(self, scene, target, intent):
        from .policy import guard_differential_universe_click
        guard_differential_universe_click(scene,target,intent=intent)
        if (intent not in ('field_ring_attack','field_forward_attack')
                and self.template(scene,"du_attack_mouse",(.878,.825,.901,.867),threshold=.88) is None):
            raise AutomationError("未核实当前位面的普通攻击鼠标图标，未攻击。")
        return self._du_field_input(scene,"field_basic_attack",
            lambda:self.window.field_attack(scene.geometry,checkpoint=self._du_held_checkpoint(scene)))

    def differential_universe_interact(self, scene: Scene, target: Token):
        from .policy import guard_differential_universe_field_interact
        guard_differential_universe_field_interact(scene, target)
        return self._du_field_input(scene,"anomaly_interact_f",
            lambda:self.window.field_interact(scene.geometry,checkpoint=self._du_held_checkpoint(scene)))

    def wait(self, predicate, timeout=30, description="界面") -> Scene:
        elapsed = 0.0
        while elapsed < timeout:
            # Paused time is excluded from transition deadlines.
            self.checkpoint()
            start = time.monotonic()
            inactive_before = getattr(self.runner, "inactive_duration", 0)
            scene = self.snapshot()
            if predicate(scene):
                return scene
            elapsed += max(0, time.monotonic() - start -
                           (getattr(self.runner, "inactive_duration", 0) - inactive_before))
            self.sleep(0.7)
            elapsed += 0.7
        if self.last_scene:
            self.evidence(self.last_scene, "timeout")
        raise AutomationError(f"等待{description}超时（{timeout} 秒）。请查看本次运行截图。")

    def evidence(self, scene: Scene, name: str):
        stamp = datetime.now().strftime("%H%M%S_%f")
        return save_scene(scene, Path(self.report.run_dir), f"{stamp}_{name}")

    def refine_dungeon_rows(self, scene, category):
        self.checkpoint()
        if scene is not self.last_scene or self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("副本名称细读前画面已失效，需要重新识别。")
        self.vision.refine_dungeon_rows(scene, category)
        self.checkpoint()

    def refine_planar_support(self, scene):
        self.checkpoint()
        if scene is not self.last_scene or self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("支援标记细读前画面已失效。")
        self.vision.refine_planar_support(scene)
        self.checkpoint()

    def planar_friend_slot(self, scene, badge):
        self.checkpoint()
        if scene is not self.last_scene or self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("支援槽位细读前画面已失效。")
        return self.vision.planar_friend_slot(scene,badge)

    def planar_payment(self, scene):
        self.checkpoint()
        if scene is not self.last_scene or self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted('饰品价格细读前画面已失效。')
        return self.vision.planar_payment(scene)

    def planar_approach(self, scene):
        from .planar_entry import require_field
        self._require_gameplay_input()
        self.checkpoint()
        if (self.report.operation != "daily" or self.settings.dungeon_category != "planar"
                or self.report.stamina_pending + self.report.immersifiers_pending <= 0 or scene is not self.last_scene
                or self.scene_epoch != self.runner.input_epoch or time.monotonic()-scene.captured_at > 8):
            raise AutomationError("饰品提取接战缺少本次开始挑战与待核对预算，未移动。")
        require_field(scene)
        self.evidence(scene,"planar_before_approach")
        epoch = self.scene_epoch
        def held_checkpoint():
            # Release W before any blocking pause/focus wait.
            if self.runner._stop.is_set():
                raise Stopped("任务已停止。")
            if self.runner._pause.is_set() or self.runner.input_epoch != epoch:
                raise InputInterrupted("饰品接战移动已中断，恢复后需要重新识别。")
            self.window.guard(scene.geometry)
        self.last_scene, self._scroll_anchor = None, None
        try:
            self.window.key_hold("w",600,scene.geometry,checkpoint=held_checkpoint)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def scroll(self, amount: int):
        self._require_gameplay_input()
        if self.report.operation == "differential_universe":
            raise AutomationError("差分宇宙自动流程不滚动页面。")
        self.checkpoint()
        if self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("暂停后滚动目标已失效，需要重新识别。")
        if not self._scroll_anchor or self.scene_epoch != self.runner.input_epoch or self.last_scene is None:
            raise AutomationError("滚动前需要重新识别并定位列表区域。")
        point, geometry, epoch = self._scroll_anchor
        if epoch != self.runner.input_epoch or time.monotonic()-self.last_scene.captured_at > 8:
            raise AutomationError("滚动前定位已经过期。")
        try:
            self.window.move(*point, geometry)
            self.window.scroll(amount)
        except FocusLost:
            self._focus_interrupted()
        self.last_scene = None
        self.sleep(self.settings.action_delay)

    def move(self, scene: Scene, point: tuple[float, float]):
        self._require_gameplay_input()
        if self.report.operation == "differential_universe":
            raise AutomationError("差分宇宙自动流程不发送游标移动。")
        self.checkpoint()
        if self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("暂停后移动目标已失效，需要重新识别。")
        if scene is not self.last_scene or self.scene_epoch != self.runner.input_epoch or time.monotonic()-scene.captured_at > 8:
            raise AutomationError("移动前识别画面已经过期。")
        try:
            self.window.move(*point, scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self._scroll_anchor = (point, scene.geometry, self.scene_epoch)

    def drag(self, scene: Scene, start: tuple[float, float], end: tuple[float, float], *, du_intent=None):
        if self.report.operation == "differential_universe":
            if du_intent!='du_reward_gallery_pan' or not self.settings.differential_universe_rewards:
                raise AutomationError("差分宇宙仅允许已开启领奖时的画廊平移。")
            from .du_rewards import guard_pan
            guard_pan(scene,start,end)
        elif du_intent is not None:
            raise AutomationError("画廊平移意图不适用于当前运行类型。")
        route=()
        if self.report.operation=='currency_wars_flow_test' and self._currency_position_request is not None:
            requested_scene,field,profile=self._currency_position_request
            self._currency_position_request=None
            from .currency_wars_position import position_plan
            target=position_plan(scene,field,profile,self.settings.ocr_confidence)
            if scene is not requested_scene or start!=field.point or end!=target.point:
                raise AutomationError('位置纠正授权与拖动目标不一致。')
            route=((start[0],.495),(end[0],.495))
        elif self.report.operation=='currency_wars_flow_test' and self._currency_equipment_request is not None:
            requested_scene,field,item,profile_scene,item_name=self._currency_equipment_request
            self._currency_equipment_request=None
            from .currency_wars_equipment import equipment_plan
            if scene is not requested_scene or equipment_plan(scene,field,item,profile_scene,item_name,self.settings.ocr_confidence)!=(start,end):
                raise AutomationError('装备穿戴授权与本次源图像或目标不一致。')
            route=((start[0],.495),(end[0],.495))
        elif self.report.operation=='currency_wars_flow_test' and self._currency_deploy_request is not None:
            requested_scene,plan=self._currency_deploy_request
            self._currency_deploy_request=None
            if scene is not requested_scene or start!=plan.start or end!=plan.end:
                raise AutomationError('本次自动部署授权与拖动目标不一致。')
            from .currency_wars_deployment import plan_bench_deployment
            if plan_bench_deployment(scene,self.settings.ocr_confidence,source_slot=plan.source_slot,zone=plan.zone)!=plan:
                raise AutomationError('自动部署空格已改变。')
            if plan.zone=='back':
                route=((start[0],.735),(end[0],.735))
        elif self.report.operation == "currency_wars_deploy_test":
            from .currency_wars_deployment import plan_bench_deployment
            plan = plan_bench_deployment(scene, self.settings.ocr_confidence,
                source_slot=self.runner.currency_source_slot,zone=self.runner.currency_zone)
            if start != plan.start or end != plan.end:
                raise AutomationError("部署诊断只允许所选备战格到已识别的空场上格。")
        elif self.report.operation == "currency_wars_drag_test":
            from .currency_wars_deployment import SWAP_START, SWAP_END, require_distinct_front_pair
            if start != SWAP_START or end != SWAP_END:
                raise AutomationError("此诊断只允许一次前台第3格到第1格拖动。")
            require_distinct_front_pair(scene, self.settings.ocr_confidence)
        else:
            self._require_gameplay_input()
        self.checkpoint()
        if self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("暂停后拖动目标已失效，需要重新识别。")
        if scene is not self.last_scene or not 0 <= time.monotonic() - scene.captured_at <= 8:
            raise AutomationError("拖动前识别画面已过期。")
        epoch = self.scene_epoch
        def held_checkpoint():
            # Never enter a blocking pause/focus wait with a mouse button held.
            # Abort first; GameWindow.drag releases in finally, then the outer
            # workflow can wait for resume and take a new observation.
            if self.runner._stop.is_set():
                raise Stopped("任务已停止。")
            if self.runner._pause.is_set() or self.runner.input_epoch != epoch:
                raise InputInterrupted("拖动已因暂停中断，恢复后需要重新识别。")
            self.window.guard(scene.geometry)
        self.last_scene, self._scroll_anchor = None, None
        try:
            if route:
                self.window.drag(start,end,scene.geometry,checkpoint=held_checkpoint,waypoints=route)
            else:
                self.window.drag(start, end, scene.geometry, checkpoint=held_checkpoint)
            held_checkpoint()
            # Unity may consume button-up on its next frame and read the
            # current cursor then. Let that release reach the game before
            # moving away from the target for an unobscured feedback capture.
            self.sleep(.2)
            held_checkpoint()
            # Remove hover tint and the pointer from the portrait used for
            # post-drag identity verification. The left button is released.
            self.window.move(.5,.5,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_start_node(self, scene: Scene):
        if self.report.operation not in ('currency_wars_node_test','currency_wars_flow_test'):
            raise AutomationError('当前运行类型不允许货币战争出战。')
        from .currency_wars_node import start_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target = start_target(scene, self.settings.ocr_confidence)
        # Invalidate before dispatch, including unknown input outcomes.
        self.last_scene, self._scroll_anchor = None, None
        try:
            self.window.click(*target.center, scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_continue_node(self, scene: Scene):
        if self.report.operation != 'currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许推进货币战争结算。')
        from .currency_wars_flow import continue_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target = continue_target(scene,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor = None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_advance_plane(self, scene: Scene):
        if self.report.operation != 'currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许推进位面地图。')
        from .currency_wars_flow import plane_target, active_plane
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        active_plane(scene,self.settings.ocr_confidence)
        target=plane_target(scene,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_select_investment(self,scene: Scene,name: str,*,confirm=False):
        if self.report.operation != 'currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许选择投资策略。')
        from .currency_wars_choices import investment_choice,investment_confirm
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        selected,target=investment_choice(scene,self.settings.ocr_confidence)
        if selected!=name:
            raise AutomationError('投资策略候选已改变，未选择。')
        if confirm:
            target=investment_confirm(scene,name,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_equip_battery(self,scene: Scene,field,item,profile_scene):
        return self.currency_equip_item(scene,field,item,profile_scene,'battery')

    def currency_select_star(self,scene: Scene,*,confirm=False):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许选择盛会之星。')
        from .currency_wars_star import star_choice,star_confirm_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target=(star_confirm_target if confirm else star_choice)(scene,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_buy_offer(self,scene: Scene,offer):
        if self.report.operation!='currency_wars_flow_test' or not self.runner.currency_start_from_lobby:
            raise AutomationError('本次未请求整局购买策略。')
        from .currency_wars_market import purchase_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target=purchase_target(scene,offer,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_open_shop(self,scene: Scene):
        if self.report.operation!='currency_wars_flow_test' or not self.runner.currency_start_from_lobby:
            raise AutomationError('本次未请求整局购买策略。')
        from .currency_wars_market import open_shop_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target=open_shop_target(scene,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_correct_position(self,scene: Scene,field,profile):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许纠正货币战争位置。')
        from .currency_wars_position import position_plan
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target=position_plan(scene,field,profile,self.settings.ocr_confidence)
        self._currency_position_request=(scene,field,profile)
        try:
            self.drag(scene,field.point,target.point)
        finally:
            self._currency_position_request=None

    def currency_select_environment(self,scene: Scene,confirm=False):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许选择投资环境。')
        from .currency_wars_environment import environment_choice,environment_confirm
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target=environment_confirm(scene,self.settings.ocr_confidence) if confirm else environment_choice(scene,self.settings.ocr_confidence)[0]
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_advance_entry(self,scene: Scene,name):
        if self.report.operation!='currency_wars_flow_test' or not self.runner.currency_start_from_lobby:
            raise AutomationError('本次运行未请求从主页开始整局验证。')
        from .currency_wars_entry import entry_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        current,_,target=entry_target(scene,self.settings.ocr_confidence)
        if current!=name:
            raise AutomationError('开局页面与本次动作不一致。')
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_advance_ending(self,scene: Scene,kind):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许推进货币战争终局。')
        from .currency_wars_ending import ending_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        current,_,target=ending_target(scene,self.settings.ocr_confidence)
        if current!=kind:
            raise AutomationError('终局页面与本次动作不一致。')
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_equip_item(self,scene: Scene,field,item,profile_scene,item_name):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许穿戴货币战争装备。')
        from .currency_wars_equipment import equipment_plan
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        start,end=equipment_plan(scene,field,item,profile_scene,item_name,self.settings.ocr_confidence)
        self._currency_equipment_request=(scene,field,item,profile_scene,item_name)
        try:
            self.drag(scene,start,end)
        finally:
            self._currency_equipment_request=None

    def currency_open_field(self,scene: Scene,field):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许查看在场角色。')
        from .currency_wars_sale import validate_field_image
        from .currency_wars_match import read_match
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        validate_field_image(scene,field,self.settings.ocr_confidence)
        if read_match(scene,self.settings.ocr_confidence).page not in ('preparation','bench_full'):
            raise AutomationError('查看在场角色需要无遮挡备战页。')
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*field.point,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_open_sale_candidate(self,scene: Scene,candidate,field):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许整理备战副本。')
        from .currency_wars_sale import validate_field_image
        from .currency_wars_roster import validate_candidate,deployed_matches
        from .currency_wars_deployment import _BENCH_CENTERS
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        if not 1<=candidate.slot<=4:
            raise AutomationError('该备战格无法在角色面板下复核，未整理。')
        validate_candidate(scene,candidate,self.settings.ocr_confidence,require_vacancy=False)
        validate_field_image(scene,field,self.settings.ocr_confidence)
        if not any(score>=.90 and zone==field.zone and index==field.slot
                   for score,zone,index,_ in deployed_matches(scene,candidate)):
            raise AutomationError('备战副本与在场角色头像未匹配。')
        epoch=self.scene_epoch
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(_BENCH_CENTERS[candidate.slot-1],1210/1440,scene.geometry)
            # Let the game process the released click before moving off the
            # portrait; moving in the same frame can cancel the opening.
            self.sleep(.2)
            if self.runner._pause.is_set() or self.runner._stop.is_set() or self.runner.input_epoch!=epoch:
                raise InputInterrupted('已停止或暂停查看副本，未移动旧目标。')
            self.window.move(.5,.5,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_sell_duplicate(self,scene: Scene,candidate,field,field_profile):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许出售备战副本。')
        from .currency_wars_sale import sale_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        _,target=sale_target(scene,candidate,field,field_profile,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_advance_boss(self,scene: Scene):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许推进强敌介绍。')
        from .currency_wars_intro import boss_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target=boss_target(scene,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_open_reward(self,scene: Scene,slot):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许开启备战物品。')
        from .currency_wars_rewards import open_reward_target
        from .currency_wars_deployment import _BENCH_CENTERS
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        current,_=open_reward_target(scene,self.settings.ocr_confidence)
        if current!=slot:
            raise AutomationError('备战物品目标已改变。')
        epoch=self.scene_epoch
        self.last_scene,self._scroll_anchor=None,None
        def held_checkpoint():
            if self.runner._stop.is_set():
                raise Stopped('任务已停止。')
            if self.runner._pause.is_set() or self.runner.input_epoch!=epoch:
                raise InputInterrupted('物品点击已中断，需要重新识别。')
            self.window.guard(scene.geometry)
        try:
            # The card lifts on hover. Its bottom label can move out from
            # under the pointer; the calibrated card center remains inside.
            point=(_BENCH_CENTERS[slot-1],1210/1440)
            self.window.move(*point,scene.geometry)
            self.sleep(.2)
            if self.runner.input_epoch!=epoch or self.runner._pause.is_set() or self.runner._stop.is_set():
                raise InputInterrupted('物品悬停后状态已中断，未发送点击。')
            self.window.click_held(*point,scene.geometry,checkpoint=held_checkpoint)
            held_checkpoint()
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_choose_reward(self,scene: Scene,kind,name):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许选择货币战争奖励。')
        from .currency_wars_rewards import reward_choice
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        current,target=reward_choice(scene,self.settings.ocr_confidence)
        if current!=kind or target.text!=name:
            raise AutomationError('奖励候选已改变。')
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_close_shop(self,scene: Scene):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许收起商店。')
        from .currency_wars_shop import close_shop_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        target=close_shop_target(scene,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_open_bench(self,scene: Scene,candidate):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许自动查看备战角色。')
        from .currency_wars_roster import validate_candidate
        from .currency_wars_deployment import _BENCH_CENTERS
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        validate_candidate(scene,candidate,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(_BENCH_CENTERS[candidate.slot-1],1210/1440,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_close_character(self,scene: Scene):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许关闭角色面板。')
        from .currency_wars_roster import read_character
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        read_character(scene,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(.5,.5,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_deploy_candidate(self,scene: Scene,candidate,profile):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许自动部署。')
        from .currency_wars_roster import eligible_plan
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        plan=eligible_plan(scene,candidate,profile,self.settings.ocr_confidence)
        self._currency_deploy_request=(scene,plan)
        try:
            self.drag(scene,plan.start,plan.end)
        finally:
            self._currency_deploy_request=None

    def currency_select_supply(self,scene: Scene,expected,choice,*,confirm=False):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许选择货币战争补给。')
        from .currency_wars_supply import supply_choice,supply_options,supply_confirm
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        options=supply_options(scene,self.settings.ocr_confidence)
        if tuple(o[:3] for o in options)!=expected or choice not in expected:
            raise AutomationError('补给候选已改变。')
        if confirm:
            target=supply_confirm(scene,expected,self.settings.ocr_confidence)
        else:
            current=supply_choice(scene,self.settings.ocr_confidence)
            if current[:3]!=choice:
                raise AutomationError('补给选择与当前策略不一致。')
            target=current[3]
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_buy_experience(self,scene: Scene):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许购买货币战争经验。')
        from .currency_wars_experience import experience_target
        from .currency_wars_match import read_match
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        state=read_match(scene,self.settings.ocr_confidence)
        from .currency_wars_experience import target_level
        if state is None or not state.level or state.level>=target_level(scene,self.runner,self.settings.ocr_confidence):
            raise AutomationError('未设置更高的目标等级，未购买经验。')
        target=experience_target(scene,self.settings.ocr_confidence)
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target.center,scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_collect_loot(self,scene: Scene,target):
        if self.report.operation!='currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许领取货币战争晶矿。')
        from .currency_wars_loot import loot_target
        from .currency_wars import CurrencyWarsWorkflow
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        if target!=loot_target(scene,self.settings.ocr_confidence):
            raise AutomationError('奖励晶矿目标已改变。')
        self.last_scene,self._scroll_anchor=None,None
        try:
            self.window.click(*target[:2],scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def template(self, scene: Scene, name: str, roi=(0, 0, 1, 1), threshold=0.88):
        path = RESOURCE_ROOT / "assets" / "templates" / f"{name}.png"
        if not path.exists():
            return None
        return self.vision.template(scene, path, roi, threshold)


class Runner:
    def __init__(self, settings: Settings, emit=None, *, new_battle_run=False, operation="daily",
                 du_runs=None, du_resume_active=False, du_periodic_rank=None,
                 currency_source_slot=3,currency_zone='back',currency_target_level=0,currency_start_from_lobby=False,
                 currency_control_probe=False, currency_timeout_probe=False):
        self.settings = settings
        self._emit = emit or (lambda event: None)
        self._overlay = None
        self.report = RunReport()
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._resume_focus = False
        self._window = None
        self._monitor_end = threading.Event()
        self._logger = None
        self.input_epoch = 0
        self.inactive_duration = 0.0
        self.new_battle_run = new_battle_run
        self.currency_source_slot,self.currency_zone = currency_source_slot,currency_zone
        if type(currency_target_level) is not int or not 0<=currency_target_level<=10:
            raise ValueError('货币战争目标等级必须为0到10的整数。')
        self.currency_target_level=currency_target_level
        if type(currency_start_from_lobby) is not bool:
            raise ValueError('货币战争整局验证开关必须为布尔值。')
        self.currency_start_from_lobby=currency_start_from_lobby
        if (type(currency_control_probe) is not bool or type(currency_timeout_probe) is not bool
                or ((currency_control_probe or currency_timeout_probe) and operation != 'currency_wars')
                or (currency_control_probe and currency_timeout_probe)):
            raise ValueError('控制验收仅允许只读运行，且一次只选一种。')
        self.currency_control_probe = currency_control_probe
        self.currency_timeout_probe = currency_timeout_probe
        self.report.operation = operation
        self.battle_budget = None
        self.du_runs = settings.differential_universe_runs if du_runs is None else du_runs
        if isinstance(self.du_runs, bool) or not isinstance(self.du_runs, int) or not 1 <= self.du_runs <= 10:
            raise ValueError("差分宇宙局数必须是 1～10 的整数。")
        if type(du_resume_active) is not bool or (du_resume_active and operation != "differential_universe"):
            raise ValueError("接续差分宇宙仅适用于差分宇宙操作，且必须为布尔值。")
        if (du_periodic_rank is not None and
                (isinstance(du_periodic_rank, bool) or not isinstance(du_periodic_rank, int)
                 or not 1 <= du_periodic_rank <= 10 or operation != "differential_universe")):
            raise ValueError("周期演算接续难度必须是 1～10 的整数，且仅适用于差分宇宙操作。")
        if du_periodic_rank is not None and not du_resume_active:
            raise ValueError("周期演算接续难度只可配合 --resume-active-du。")
        if du_periodic_rank is not None and self.du_runs != 1:
            raise ValueError("周期演算接续仅完成当前 1 局。")
        self.du_resume_active = du_resume_active
        self.du_periodic_rank = du_periodic_rank

    def _run_tasks(self, context, workflow):
        selected = [name for name in ("assignments", "battle", "daily", "mail", "battlepass")
                    if getattr(self.settings, name)]
        if not selected:
            raise AutomationError("至少选择一个任务。")
        for index, name in enumerate(selected):
            self.checkpoint()
            self.report.failure_task = name
            self.emit(dict(type="task", task=name, status="running", detail="正在执行"))
            try:
                result = self._resume_step(getattr(workflow, name), name)
            except Stopped:
                raise
            except Exception as error:
                result = TaskResult(name, "partial", f"未核实完成：{error}")
                self.report.error = str(error)
                self.report.safe_next = ("已保留每日奖励验证；请人工返回主界面后仅重试未完成的免费领奖。"
                                         if self.report.daily_verified else
                                         "请人工核对当前界面和消耗，返回主界面后选择仅补领奖；不要直接重跑刷本。")
                self.report.results.append(result)
                self.emit(dict(type="task", **result.__dict__))
                if context.last_scene is not None:
                    try:
                        context.evidence(context.last_scene, name + "_failure")
                    except Exception as evidence_error:
                        self.log(f"失败截图未保存：{evidence_error}", "warning")
                for remaining in selected[index + 1:]:
                    skipped = TaskResult(remaining, "skipped", "前一步页面未核实，未继续发送输入。")
                    self.report.results.append(skipped)
                    self.emit(dict(type="task", **skipped.__dict__))
                break
            self.report.results.append(result)
            self.emit(dict(type="task", **result.__dict__))
            self.log(f"{result.task}：{result.detail}")
        else:
            self.report.failure_task = ""
        self.report.status = "success" if all(r.status == "ok" for r in self.report.results) else "partial"
        if self.settings.daily and not self.report.daily_verified:
            self.report.status = "partial"

    def emit(self, event):
        if self._overlay is not None:
            self._overlay.publish(event)
        self._emit(event)

    def log(self, message: str, level="info"):
        if self._logger:
            getattr(self._logger, level if level in ("info", "warning", "error") else "info")(message)
        self.emit(dict(type="log", message=message, level=level))

    def _inspect_currency_wars(self, context):
        from .currency_wars import CurrencyWarsWorkflow, SAFE_NEXT, TASK
        self.report.failure_task = TASK
        self.report.safe_next = SAFE_NEXT
        self.emit(dict(type="task", task=TASK, status="running", detail="启动准备：进入游戏，不开始对局" if self.report.operation == 'currency_wars_prepare' else "连续战斗与结算推进验证" if self.report.operation == "currency_wars_flow_test" else "当前节点战斗验证" if self.report.operation == "currency_wars_node_test" else "单次部署验证" if self.report.operation == "currency_wars_deploy_test" else "单次前台拖动验证" if self.report.operation == "currency_wars_drag_test" else "只读识别与证据保存"))
        if self.report.operation == 'currency_wars_prepare':
            from .currency_wars_prepare import prepare
            result = prepare(context)
        elif self.report.operation == "currency_wars_drag_test":
            from .currency_wars_deployment import test_front_swap
            result = test_front_swap(context)
        elif self.report.operation == "currency_wars_deploy_test":
            from .currency_wars_deployment import test_bench_deployment
            result = test_bench_deployment(context)
        elif self.report.operation == "currency_wars_node_test":
            from .currency_wars_node import run_node
            result = run_node(context)
        elif self.report.operation == "currency_wars_flow_test":
            from .currency_wars_flow import run_flow
            result = run_flow(context)
        else:
            if self.currency_control_probe:
                from .currency_wars_control import inspect_controls
                result = inspect_controls(context)
            else:
                result = self._resume_step(CurrencyWarsWorkflow(context).inspect, TASK)
        self.report.results.append(result)
        self.emit(dict(type="task", **result.__dict__))
        self.report.status = "partial"

    def stop(self):
        self._stop.set()
        self._pause.clear()

    def toggle_pause(self) -> bool:
        self.input_epoch += 1
        if self._pause.is_set():
            self._pause.clear()
            self.log("继续任务；正在重新检查游戏窗口。")
            self.emit(dict(type="paused", paused=False))
            return False
        self._pause.set()
        self.log("任务已暂停，按 F9 或点击继续恢复。")
        self.emit(dict(type="paused", paused=True))
        return True

    def _control_checkpoint(self):
        if self._stop.is_set():
            raise Stopped("任务已停止。")
        if self._pause.is_set():
            started = time.monotonic()
            try:
                while self._pause.is_set():
                    if self._stop.wait(0.1):
                        raise Stopped("任务已停止。")
            finally:
                self.inactive_duration += time.monotonic() - started
        if self._stop.is_set():
            raise Stopped("任务已停止。")

    def wait_for_focus(self, window=None):
        window = window or self._window
        if window is None:
            return
        self._control_checkpoint()
        try:
            window.guard()
            return
        except FocusLost:
            pass
        started = time.monotonic()
        inactive_before = self.inactive_duration
        self.input_epoch += 1
        self.emit(dict(type="focus_wait", waiting=True))
        self.log("等待游戏回到前台；未发送输入，不抢占焦点。", "warning")
        try:
            while True:
                self._control_checkpoint()
                if window.emergency_pressed():
                    self.stop()
                    self._control_checkpoint()
                try:
                    window.guard()
                    self.input_epoch += 1
                    return
                except FocusLost:
                    if self._stop.wait(.1):
                        raise Stopped("任务已停止。")
        finally:
            self.inactive_duration = inactive_before + time.monotonic() - started
            self.emit(dict(type="focus_wait", waiting=False))

    def checkpoint(self):
        self._control_checkpoint()
        if self._overlay is not None:
            for message, level in self._overlay.drain_notices():
                self.log(message, level)
        if self._window is not None:
            self.wait_for_focus()

    def _prepare_daily_game(self):
        """Check first; launch only when absent, then focus once at startup."""
        self.log('检查游戏是否已启动。')
        try:
            self._window = find_game(self.settings.game_path)
            self.log('游戏已运行，准备置于前台并返回主界面。')
            return
        except AutomationError:
            pass
        self.log(launch_game(self.settings))
        self.log('等待游戏窗口出现；使用已有登录状态进入游戏。')
        for _ in range(120):
            self.checkpoint()
            try:
                self._window = find_game(self.settings.game_path)
                return
            except AutomationError:
                if self._stop.wait(1):
                    raise Stopped('任务已停止。')
        raise AutomationError('启动后120秒仍未找到游戏窗口，已停止。')

    def _resume_step(self, action, name):
        while True:
            try:
                return action()
            except InputInterrupted:
                self.checkpoint()
                if name == "battle" and (self.report.stamina_pending or self.report.immersifiers_pending):
                    raise AutomationError("挑战输入已中断且消耗待核对；保留本轮预算，不重复开始挑战。")
                if name == 'daily' and self.report.daily_synthesis.get('status') == 'pending':
                    raise AutomationError('日常合成输入已中断，保留待核对记录，不重复合成。')
                self.log("已丢弃暂停前的目标，按当前画面重新核实未完成步骤。")

    def _hotkeys(self):
        from .windows import user32
        previous = False
        while not self._monitor_end.wait(0.05):
            if (self._window.emergency_pressed() if self._window is not None else bool(user32.GetAsyncKeyState(0x79) & 0x8001)):
                self.stop()
            current = bool(user32.GetAsyncKeyState(0x78) & 0x8001)
            if self._window is not None and current and not previous and user32.GetForegroundWindow() == self._window.hwnd:
                self.toggle_pause()
            previous = current

    def _arm_hotkeys(self):
        from .windows import user32
        # A newly started process can inherit the low-bit history of the F10
        # used to stop the preceding run. Clear that history before arming;
        # a key that is still held must stop this run immediately.
        if user32.GetAsyncKeyState(0x79) & 0x8000:
            self.stop()
            self._control_checkpoint()

    def run(self) -> RunReport:
        from .workflows import DailyWorkflow
        from .windows import kernel32
        directory = ROOT / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        directory.mkdir(parents=True)
        self.report.run_dir = str(directory)
        self.report.started_at = datetime.now().astimezone().isoformat()
        self.report.source = str(ROOT)
        self._logger = logging.getLogger(f"autohsr.{directory.name}")
        self._logger.setLevel(logging.INFO)
        handler = logging.FileHandler(directory / "run.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        self._logger.addHandler(handler)
        kernel32.CreateMutexW.argtypes = [C.c_void_p, C.c_int, C.c_wchar_p]
        kernel32.CreateMutexW.restype = C.c_void_p
        mutex = kernel32.CreateMutexW(None, False, "Local\\AutoHSR.DailyRunner")
        already_running = C.get_last_error() == 183
        context = None
        monitor = None
        monitor_started = False
        try:
            if not mutex or already_running:
                raise AutomationError("另一个 AutoHSR 任务正在运行，请先停止后重试。")
            currency_wars = self.report.operation in ("currency_wars", "currency_wars_prepare", "currency_wars_drag_test", "currency_wars_deploy_test", "currency_wars_node_test", "currency_wars_flow_test")
            differential_universe = self.report.operation == "differential_universe"
            catalogue = self.report.operation == "dungeon_catalogue"
            if self.report.operation not in ("daily", "reward_only", "currency_wars", "currency_wars_prepare", "currency_wars_drag_test", "currency_wars_deploy_test", "currency_wars_node_test", "currency_wars_flow_test", "differential_universe", "dungeon_catalogue"):
                raise AutomationError("未知运行类型，未访问游戏。")
            self.settings.validate("check" if catalogue else "currency_wars" if currency_wars else "differential_universe" if differential_universe else "daily")
            if not catalogue and not currency_wars and not differential_universe and self.settings.battle and self.settings.allow_stamina_spend:
                from .recovery import BattleBudget
                self.battle_budget = BattleBudget(ROOT / "runs", self.settings, self.report)
                self.battle_budget.begin(new_run=self.new_battle_run)
            self.checkpoint()
            self._arm_hotkeys()
            monitor = threading.Thread(target=self._hotkeys, name="AutoHSR-hotkeys", daemon=True)
            monitor.start()
            monitor_started = True
            if (not catalogue and not currency_wars and not differential_universe) or self.report.operation == 'currency_wars_prepare':
                self._prepare_daily_game()
            self._window = self._window or find_game(self.settings.game_path)
            if self.report.operation != "currency_wars" and is_elevated(self._window.hwnd) is True and not is_admin():
                raise AutomationError("游戏以管理员运行，请在设置启用管理员免重复确认启动后重开助手，或使用 Start-AutoHSR-Admin.cmd。")
            self._window.focus()
            if self.settings.overlay_logs:
                from .overlay import OverlayService
                self._overlay = OverlayService()
                try:
                    self._overlay.start(self._window.hwnd)
                except Exception as error:
                    self.log(f'前台日志字幕启动失败，文件日志继续保留：{error}', 'warning')
            self.log("正在加载中文 OCR 模型。F9 暂停/继续，F10 紧急停止。")
            vision = (IsolatedVision(self.settings.ocr_confidence, checkpoint=self._control_checkpoint,
                                      inactive=lambda: self.inactive_duration,
                                      timeout=.05 if self.currency_timeout_probe else 30.) if currency_wars else
                      Vision(self.settings.ocr_confidence))
            context = Context(self, self._window, vision)
            context.battle_budget = self.battle_budget
            if catalogue:
                from .dungeon_workflow import scan_catalogue
                result = scan_catalogue(DailyWorkflow(context))
                self.report.results.append(result)
                self.report.status = "success" if result.status == "ok" else "partial"
            elif currency_wars:
                self._inspect_currency_wars(context)
            elif differential_universe:
                from .differential_universe import DifferentialUniverseWorkflow
                # A universe may already have begun; never replay the whole run
                # after an interrupted input or pause. Preserve evidence and stop.
                result = DifferentialUniverseWorkflow(context, self.du_runs,
                    resume_active=self.du_resume_active, periodic_rank=self.du_periodic_rank).run()
                self.report.results.append(result)
                self.report.status = "success" if result.status == "ok" else "partial"
                self.report.failure_task = "" if result.status == "ok" else "differential_universe"
                self.emit(dict(type="task", **result.__dict__))
            else:
                workflow = DailyWorkflow(context)
                initial = context.snapshot()
                context.evidence(initial, "start")
                if self.report.operation == 'daily' and self.settings.daily and self.settings.daily_synthesis:
                    from .daily_synthesis import resume_pending
                    try:
                        from .du_daily import account_key
                        account_key(initial)
                    except AutomationError:
                        pass  # Login pages have no account identity or craft to resume.
                    else:
                        if resume_pending(workflow, initial):
                            initial = context.snapshot()
                # Planar extraction has a uniquely named existing-save setup
                # page, including its resource price. Reuse that verified page
                # when no preceding assignment task needs the phone menu.
                ready_planar = (self.settings.dungeon_category == "planar" and self.settings.battle
                                and not self.settings.assignments and workflow._calyx_target(initial)
                                and workflow._team_page(initial))
                if not ready_planar:
                    workflow.ensure_main()
                self._run_tasks(context, workflow)
            self.log("任务已结束；请查看报告中的验证状态与证据。")
        except Stopped as error:
            self.report.status = "stopped"
            self.report.error = str(error)
            self.report.safe_next = ("货币战争操作已停止；核对画面和本次动作记录后重新识别。" if self.report.operation.startswith("currency_wars") else
                                     "差分宇宙自动演算已停止；核对本次截图、OCR 与动作记录。不要继续现有未完成存档。" if self.report.operation == "differential_universe" else
                                     "停止请求已生效；核对当前战斗及消耗后，可选择仅补领奖。")
            self.log(str(error), "warning")
        except Exception as error:
            self.report.status = "partial" if self.report.daily_verified else "failed"
            self.report.error = str(error)
            self.report.safe_next = ("货币战争操作失败；核对动作记录与前后截图，不自动重放。" if self.report.operation.startswith("currency_wars") else
                                     "差分宇宙自动演算失败；核对当前页面、动作记录与截图后再决定如何处理存档。" if self.report.operation == "differential_universe" else
                                     "请人工核对当前界面和消耗；返回主界面后仅补领奖，新增刷本预算需明确确认。")
            self.log(str(error), "error")
            if context and context.last_scene:
                try:
                    context.evidence(context.last_scene, "failure")
                except Exception as evidence_error:
                    self.log(f"失败截图未保存：{evidence_error}", "warning")
            self.report.results.append(TaskResult("run", "failed", str(error)))
        finally:
            if self._overlay is not None:
                try:
                    self._overlay.close()
                except Exception as error:
                    self.log(f'日志字幕关闭失败：{error}', 'warning')
                self._overlay = None
            self._monitor_end.set()
            if monitor_started:
                monitor.join(timeout=1)
            self.report.finished_at = datetime.now().astimezone().isoformat()
            if self.battle_budget:
                try:
                    self.battle_budget.finish()
                except OSError as error:
                    self.report.status = "partial"
                    self.report.error = f"刷本记录保存失败：{error}"
                    self.report.safe_next = "保留现有记录，人工核对消耗；不要直接开始新一轮刷本。"
            if mutex:
                kernel32.CloseHandle(mutex)
            try:
                self.report.report_saved = True
                temporary = directory / "report.tmp"
                temporary.write_text(json.dumps(self.report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                replace_file(temporary,directory / "report.json")
            except OSError as error:
                self.report.report_saved = False
                self.report.report_write_error = str(error)
                self.report.status = "partial" if self.report.daily_verified else "failed"
                self.report.error = (self.report.error + "；" if self.report.error else "") + f"报告保存失败：{error}"
                self.report.safe_next = ("报告未保存；保留动作记录和截图，人工核对后重新识别。" if self.report.operation.startswith("currency_wars") else
                                         "差分宇宙报告保存失败；保留当前目录，人工核对当前存档和动作。" if self.report.operation == "differential_universe" else
                                         "报告未保存；保留当前证据与刷本记录，人工核对消耗，不要直接重跑刷本。")
                self.log(f"报告保存失败：{error}", "error")
            if self.report.report_saved and self.report.operation == "differential_universe":
                try:
                    files = [path for path in directory.rglob("*") if path.is_file()
                             and path.name not in ("evidence_manifest.json", "evidence_manifest.sha256")]
                    entries = []
                    for path in sorted(files, key=lambda p: p.relative_to(directory).as_posix()):
                        digest = hashlib.sha256(path.read_bytes()).hexdigest()
                        entries.append({"path": path.relative_to(directory).as_posix(),
                                        "size_bytes": path.stat().st_size, "sha256": digest})
                    manifest_path = directory / "evidence_manifest.json"
                    manifest_path.write_text(json.dumps({"algorithm": "sha256", "files": entries},
                                                        ensure_ascii=False, indent=2), encoding="utf-8")
                    manifest_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                    (directory / "evidence_manifest.sha256").write_text(
                        f"{manifest_digest}  evidence_manifest.json\n", encoding="ascii")
                except OSError as error:
                    self.report.status = "partial"
                    self.report.error = (self.report.error + "；" if self.report.error else "") + f"证据清单保存失败：{error}"
                    self.report.safe_next = "报告已保存，但证据清单不完整；核对当前目录与差分宇宙存档后再处理。"
                    self.log(f"证据清单保存失败：{error}", "error")
                    try:
                        temporary = directory / "report.tmp"
                        temporary.write_text(json.dumps(self.report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                        replace_file(temporary,directory / "report.json")
                    except OSError:
                        pass
            self._logger.removeHandler(handler)
            handler.close()
            self.emit(dict(type="finished", report=self.report.to_dict()))
        return self.report
