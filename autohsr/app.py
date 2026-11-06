from __future__ import annotations

from contextlib import ExitStack, contextmanager, nullcontext
from copy import deepcopy
import ctypes as C
import hashlib
import json
import logging
from pathlib import Path
import re
import threading
import time
from datetime import datetime

from .config import ROOT, RESOURCE_ROOT, Settings, SettingsError
from .du_points_followup import FollowupWeekExpired, require_followup_week
from .models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, RunReport, Scene, Stopped, TaskResult, Token, normalize
from .vision import Vision, save_scene,helper_overlay
from .ocr_isolation import IsolatedVision
from .windows import find_game, is_admin, is_elevated, launch
from .storage import file_revision, hold_read_sources, replace_file


def launch_game(settings: Settings) -> str:
    from .workflow_lease import require_workflow_access
    require_workflow_access()
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
    try:
        from .currency_wars_identity import installed_client
        client = installed_client(window.current_executable())
        result['game_client'] = dict(status='verified', **{key: client[key]
            for key in ('version', 'full_version', 'kind', 'sha256')})
    except Exception:
        result['game_client'] = dict(status='unknown', reason='客户端安装版本未核实；未使用EXE引擎版本代替。')
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
        self.capture_sequence = 0
        self.capture_occlusion_count = 0
        self._scroll_anchor = None
        self._currency_deploy_request = None
        self._currency_equipment_request = None
        self._currency_position_request = None
        self._du_actions = []
        self._daily_startup = None
        from .workflow_identity import wrap_window
        self.window = wrap_window(self, window)

    def log(self, message: str, level="info"):
        self.runner.log(message, level)

    def item_view(self,settings):
        view=Context(self.runner,self.window,self.vision)
        view.settings=settings;view.report=self.report
        view.battle_budget=getattr(self,'battle_budget',None)
        return view

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

    @contextmanager
    def daily_startup(self, workflow, cold_start):
        from .workflows import DailyStartupObservation
        previous = self._daily_startup
        self._daily_startup = DailyStartupObservation(workflow, cold_start)
        try:
            yield
        finally:
            self._daily_startup = previous

    def snapshot(self) -> Scene:
        occluded_frames=0
        while True:
            self.checkpoint()
            self.last_scene = None
            self._scroll_anchor = None
            capture_epoch = self.runner.input_epoch
            captured_at = time.monotonic()
            self.capture_sequence += 1
            try:
                image, geometry = self.window.capture()
                scene = self.vision.read(image, geometry)
                if helper_overlay(scene):
                    self.capture_occlusion_count += 1
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
                elif self.report.operation == 'du_rewards':
                    self.vision.refine_du_reward_balance(scene)
                if self.report.operation == 'redemption' or self.report.operation == 'daily' and self.settings.redemption_enabled:
                    self.vision.refine_redemption(scene)
                scene.captured_at = captured_at
                self.checkpoint()
                if capture_epoch != self.runner.input_epoch:
                    self.last_scene = None
                    continue
                self.window.guard(geometry)
            except FocusLost:
                self.last_scene = None
                if (self.report.operation in ('challenge_result', 'challenge_lobby', 'team_preset_calibration')
                        or getattr(self.runner, '_challenge_read_only', False) is True):
                    raise
                self.runner.wait_for_focus(self.window)
                continue
            except EmptyCapture:
                if self._daily_startup is None:
                    raise
                self._daily_startup.retry(None)
                continue
            self.scene_epoch = capture_epoch
            self.last_scene = scene  # Keep a failing identity frame for local evidence.
            if self._daily_startup is not None and not self._daily_startup.accept(scene):
                self.last_scene = None
                self._daily_startup.retry(scene)
                continue
            from .workflow_identity import observe
            if not observe(self, scene):
                self.last_scene = None
                self.sleep(.15)
                continue
            return scene

    def _focus_interrupted(self):
        self.last_scene = None
        self._scroll_anchor = None
        self.runner.wait_for_focus(self.window)
        raise InputInterrupted("焦点恢复后须重新识别，旧输入目标已丢弃。")

    def _require_gameplay_input(self):
        archive = getattr(self, 'du_archive_workflow', None)
        if archive is not None and (getattr(archive, 'c', None) is not self or getattr(archive, 'finished', False) is not True):
            raise AutomationError('差分存档流程尚未核实返回，仅允许本次持久保存意图输入。')
        if self.report.operation == 'du_rewards':
            raise AutomationError('差分独立领奖仅允许专用意图入口，不能使用通用点击、按键或移动。')
        if self.report.operation == 'challenge_prepare':
            raise AutomationError('高难备战只允许专用层数核验入口，不能使用通用点击或按键。')
        if self.report.operation == 'challenge_lobby':
            raise AutomationError('高难主页导航只允许本次已核实的专用操作。')
        if self.report.operation == 'challenge_result':
            raise AutomationError('高难结果只允许观察当前画面。')
        if self.report.operation == 'team_preset_calibration':
            raise AutomationError('编队入口校准只允许本次手机编队入口点击。')
        if self.report.operation == 'build_target_read':
            raise AutomationError('培养目标读取只允许核实后的生存索引入口点击。')
        if self.report.operation in ('build_target_preview', 'build_target_plan'):
            raise AutomationError('培养材料预览只观察当前画面。')
        if self.report.operation.startswith("currency_wars"):
            raise AutomationError("货币战争当前仅允许只读识别，禁止发送游戏输入。")

    def _currency_weekly_checkpoint(self):
        guard=getattr(self.runner,'currency_weekly_guard',None)
        if guard is not None:guard.current()

    def build_target_entry_input(self, scene):
        from .build_target_read import BuildTargetRead
        reader = getattr(self, 'build_target_reader', None)
        if (self.report.operation != 'build_target_read' or not isinstance(reader, BuildTargetRead)
                or reader.ctx is not self or reader.record is not self.report.build_target):
            raise AutomationError('缺少本次独立培养目标读取及入口证据。')
        self.checkpoint()
        try:
            self.window.guard(scene.geometry)
            target = reader.authorize_entry(scene)

            def before_send():
                if reader.authorize_entry(scene) != target:
                    raise AutomationError('培养目标入口在发送前发生变化。')
                self.last_scene, self._scroll_anchor = None, None
                reader.record['entry_input'] = 'unconfirmed'

            self.window.click(*target.center, scene.geometry, before_send=before_send)
        except FocusLost:
            self._focus_interrupted()
        reader.record['entry_input'] = 'sent'

    def team_preset_entry_input(self, scene):
        from .team_preset_calibration import OPERATION, TeamPresetCalibration
        reader = getattr(self, 'team_preset_reader', None)
        if (self.report.operation != OPERATION or not isinstance(reader, TeamPresetCalibration)
                or reader.c is not self or reader.record is not self.report.team_preset_calibration):
            raise AutomationError('缺少本次独立编队入口校准与落盘意图。')
        self.checkpoint()
        with reader.hold_intent():
            target = reader.authorize(scene)
            reader.guard_window()

            def before_submit():
                if reader.authorize(scene) != target:
                    raise AutomationError('手机编队入口在提交前已改变。')
                reader.guard_window()
                if self.window.emergency_pressed():
                    raise Stopped('F10 紧急停止。')
                reader.mark_attempt(scene)
                self.last_scene, self._scroll_anchor = None, None

            self.window.click(*target.center, scene.geometry, before_submit=before_submit)
        if reader.record['input_status'] != 'unconfirmed':
            raise AutomationError('缺少本次手机编队入口的原生提交标记。')
        reader.record['input_status'] = 'sent'
        return time.monotonic()

    def du_rewards_input(self, scene, action):
        from .du_rewards_only import RewardAction
        if self.report.operation != 'du_rewards' or type(action) is not RewardAction:
            raise AutomationError('差分独立领奖需要本次专用任务及明确动作。')
        workflow = getattr(self, 'du_rewards_workflow', None)
        if workflow is None or workflow.c is not self:
            raise AutomationError('缺少本次差分领奖流程与落盘意图。')
        if sum(value is not None for value in (action.target, action.key, action.drag)) != 1:
            raise AutomationError('差分领奖动作形态不唯一，未发送输入。')
        if getattr(workflow, 'periodic_only', False) is True:
            self._du_periodic_reward_input(workflow, scene, action)
            return
        self.checkpoint()
        workflow.authorize(scene, action)
        self.window.guard(scene.geometry)
        self.checkpoint()
        workflow.authorize(scene, action)
        held_checkpoint = self._du_held_checkpoint(scene) if action.drag is not None else None
        self.last_scene, self._scroll_anchor = None, None
        try:
            if action.target is not None:
                self.window.click(*action.target.center, scene.geometry)
            elif action.key == 'esc':
                self.window.key('esc')
            elif action.drag is not None:
                self.window.drag(*action.drag, scene.geometry, checkpoint=held_checkpoint)
            else:
                raise AutomationError('差分独立领奖只允许已核实的返回键。')
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def _du_periodic_reward_input(self, workflow, scene, action):
        from .du_periodic_rewards import capture_time

        window, geometry = self.window, scene.geometry
        image, tokens, fields = scene.image, tuple(scene.tokens), scene.field_reads.copy()
        epoch, sequence, stamp, hwnd = self.scene_epoch, self.capture_sequence, scene.captured_at, window.hwnd
        submitted = False

        def before_submit():
            nonlocal submitted
            if submitted or self.window is not window or scene.geometry != geometry:
                raise InputInterrupted('周期领奖发送前的窗口来源已改变。')
            workflow.authorize(scene, action)
            window.guard(geometry)
            if window.emergency_pressed() is True:
                raise Stopped('周期领奖已停止，未发送当前动作。')
            capture_time(scene, workflow.week)
            if getattr(self.runner, 'stop_requested', False) is True:
                raise Stopped('周期领奖已停止，未发送当前动作。')
            if (self.window is not window or window.hwnd != hwnd or scene.geometry != geometry
                    or self.last_scene is not scene or self.capture_sequence != sequence
                    or self.scene_epoch != epoch or self.runner.input_epoch != epoch
                    or scene.captured_at != stamp or not 0 <= time.monotonic() - stamp <= 8
                    or scene.image is not image or image.flags.writeable or tuple(scene.tokens) != tokens
                    or scene.field_reads != fields):
                raise InputInterrupted('周期领奖最后核对的画面或输入代次已改变。')
            submitted = True
            self.last_scene, self._scroll_anchor = None, None

        if geometry is None:
            raise AutomationError('周期领奖缺少当前窗口几何。')
        workflow.authorize(scene, action)
        try:
            with ExitStack() as held:
                held.enter_context(hold_read_sources(workflow.input_sources(action)))
                if image.flags.writeable:
                    image.setflags(write=False)
                    held.callback(image.setflags, write=True)
                if action.target is not None:
                    window.click(*action.target.center, geometry, before_submit=before_submit)
                elif action.key == 'esc':
                    window.key('esc', expected=geometry, before_submit=before_submit)
                else:
                    raise AutomationError('周期领奖仅支持已核实的点击和返回。')
        except FocusLost:
            self._focus_interrupted()
        if not submitted:
            raise AutomationError('周期领奖缺少原生发送边界回执，原动作待核对。')
        self.sleep(self.settings.action_delay)

    def redemption_input(self, scene, action):
        if not (self.report.operation == 'redemption' or self.report.operation == 'daily' and self.settings.redemption_enabled):
            raise AutomationError('当前任务未启用兑换码流程。')
        workflow = getattr(self, 'redemption_workflow', None)
        if workflow is None or workflow.c is not self:
            raise AutomationError('缺少本次兑换流程与落盘意图。')
        self.checkpoint()
        workflow.authorize(scene, action)
        self.window.guard(scene.geometry)
        workflow._fresh(scene)
        self.last_scene, self._scroll_anchor = None, None
        try:
            if action.text:
                typing_epoch = self.runner.input_epoch
                def typing_checkpoint():
                    self.checkpoint()
                    if self.runner.input_epoch != typing_epoch or self.scene_epoch != typing_epoch:
                        raise InputInterrupted('兑换码输入代次已改变，未继续输入剩余字符。')
                    workflow.require_server_binding()
                self.window.type_redemption_code(action.text, scene.geometry, checkpoint=typing_checkpoint)
            elif action.key == 'esc':
                self.window.key('esc')
            elif action.target is not None:
                self.window.click(*action.target.center, scene.geometry)
            else:
                raise AutomationError('兑换动作没有已核实的输入目标。')
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def challenge_lobby_input(self, scene, action):
        from .challenge_lobby import ChallengeLobbyNavigation

        navigation = getattr(self, 'challenge_lobby_navigation', None)
        if (self.report.operation != 'challenge_lobby' or not isinstance(navigation, ChallengeLobbyNavigation)
                or navigation.c is not self or navigation.data is not self.report.challenge):
            raise AutomationError('缺少本次高难主页导航与动作记录。')
        with hold_read_sources(navigation.input_sources()):
            navigation.authorize(scene, action)

            def before_submit():
                navigation.authorize(scene, action)
                self.last_scene, self._scroll_anchor = None, None

            self.window.click(*action.target.center, scene.geometry, before_submit=before_submit)

    def challenge_prepare_input(self, scene, action) -> float:
        if self.report.operation != 'challenge_prepare':
            raise AutomationError('当前任务不允许高难备战选择。')
        if getattr(self.runner, '_challenge_read_only', False) is True:
            raise AutomationError('末日幻影备战只读观察当前前台页面。')
        workflow = getattr(self, 'challenge_preparation', None)
        if workflow is None or workflow.c is not self:
            raise AutomationError('缺少本次高难备战流程和落盘意图。')
        self.checkpoint()
        workflow.authorize(scene, action)
        self.window.guard(scene.geometry)
        workflow._fresh(scene)
        try:
            if workflow.calibrated_selection is None:
                self.last_scene, self._scroll_anchor = None, None
                self.window.click(*action.target.center, scene.geometry)
            else:
                with workflow.lock_calibrated_selection() as recheck:
                    self.window.click(*action.target.center, scene.geometry, before_submit=recheck)
        except FocusLost:
            self._focus_interrupted()
        finally:
            self.last_scene, self._scroll_anchor = None, None
        submitted_at = time.monotonic()
        self.sleep(self.settings.action_delay)
        return submitted_at

    def currency_prepare_click(self, scene, intent, target):
        from .currency_wars_prepare import PREPARATION_OPERATIONS
        if self.report.operation not in PREPARATION_OPERATIONS:
            raise AutomationError('当前任务不允许货币战争启动准备输入。')
        from .currency_wars import CurrencyWarsWorkflow
        from .currency_wars_prepare import click_target
        self.checkpoint()
        self._currency_weekly_checkpoint()
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
        from .currency_wars_prepare import PREPARATION_OPERATIONS
        if self.report.operation not in PREPARATION_OPERATIONS:
            raise AutomationError('当前任务不允许启动准备返回。')
        from .currency_wars import CurrencyWarsWorkflow
        from .currency_wars_prepare import key_allowed
        from .workflows import DailyWorkflow
        self.checkpoint()
        self._currency_weekly_checkpoint()
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

    def currency_navigation_input(self, scene, choice):
        from .currency_wars_prepare import PREPARATION_OPERATIONS
        if self.report.operation not in PREPARATION_OPERATIONS or not self.runner.currency_locate:
            raise AutomationError('当前任务未请求货币战争入口导航。')
        from .currency_wars import CurrencyWarsWorkflow
        from .currency_wars_navigation import next_action, require_rank_input
        self.checkpoint()
        self._currency_weekly_checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        if next_action(scene, self) != choice:
            raise AutomationError('入口导航目标改变，未发送旧输入。')
        require_rank_input(self, scene, choice)
        self.last_scene, self._scroll_anchor = None, None
        try:
            if choice.key is not None:
                self.window.key(choice.key)
            else:
                self.window.click(*choice.target.center, scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        self.sleep(self.settings.action_delay)

    def currency_overclock_input(self, scene, target):
        from contextlib import ExitStack
        from .currency_wars import CurrencyWarsWorkflow
        flow = getattr(self, '_currency_overclock_configuration', None)
        if (getattr(flow, 'c', None) is not self
                or getattr(flow, 'operation', None) != self.report.operation):
            raise AutomationError('超频输入需要明确入口与本次待核对意图。')
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        try:
            self.window.guard(scene.geometry)
            flow.authorize(scene, target)

            with ExitStack() as read_sources:
                def before_send():
                    flow.authorize(scene, target, consume=True, read_sources=read_sources)
                    self.last_scene, self._scroll_anchor = None, None

                self.window.click(*target.center, scene.geometry, before_send=before_send)
        except FocusLost:
            self._focus_interrupted()
        except OSError as error:
            raise AutomationError('超频配置原证据读取或共享读保护失败，原记录保留。') from error
        self.sleep(self.settings.action_delay)

    def currency_weekly_reward_input(self, scene, choice):
        from .currency_wars_weekly_rewards import OPERATION, next_action
        from .currency_wars_weekly_reward_run import client, current, current_frame
        from .currency_wars import CurrencyWarsWorkflow
        if self.report.operation!=OPERATION:
            raise AutomationError('当前任务不允许货币战争积分领奖输入。')
        store=getattr(self,'currency_weekly_rewards',None)
        if store is None:raise AutomationError('缺少积分领奖本次意图记录。')
        if max(.85,self.settings.ocr_confidence)!=store.data['confidence']:
            raise AutomationError('积分领奖冻结识别设置改变，未继续输入。')
        current(self,scene,store.data)
        store.require_pending(choice,self.runner.input_epoch)
        if client(self)!=store.data['client']:
            raise AutomationError('积分领奖客户端来源改变，未继续输入。')
        if next_action(scene,store.data,max(.85,self.settings.ocr_confidence))!=choice:
            raise AutomationError('积分领奖目标与当前画面不符。')
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        recovered_claim=choice.intent=='claim_weekly_rewards' and 'limit_recovery' in store.data
        if not recovered_claim:
            self.last_scene,self._scroll_anchor=None,None
        try:
            if choice.key is not None:self.window.key(choice.key)
            elif recovered_claim:
                def recheck_recovered_claim():
                    self.window.guard(scene.geometry)
                    if next_action(scene,store.data,max(.85,self.settings.ocr_confidence))!=choice:
                        raise AutomationError('接续领取目标已改变。')
                    current(self,scene,store.data)
                    store.require_pending(choice,self.runner.input_epoch)
                    current_frame(self,scene,store.data)
                self.window.click(*choice.target.center,scene.geometry,before_send=recheck_recovered_claim)
            else:self.window.click(*choice.target.center,scene.geometry)
        except FocusLost:self._focus_interrupted()
        finally:
            self.last_scene,self._scroll_anchor=None,None
        self.sleep(self.settings.action_delay)

    def currency_standard_input(self, scene, choice):
        if self.report.operation != 'currency_wars_standard':
            raise AutomationError('当前任务不允许标准博弈开发输入。')
        from .currency_wars import CurrencyWarsWorkflow
        from .currency_wars_standard_flow import loot_sale_input_scope, next_action
        self.checkpoint()
        self._currency_weekly_checkpoint()
        guard = CurrencyWarsWorkflow(self)
        guard._require_current_scene(scene)
        store = getattr(self, 'currency_standard_session', None)
        if store is None:
            raise AutomationError('缺少本次标准对局的记录。')
        input_epoch = self.runner.input_epoch
        captured_at, geometry = scene.captured_at, scene.geometry
        data = store.require_pending(choice.intent, input_epoch)
        from .currency_wars_identity import account_key, checked_account_key
        from .currency_wars_environment import ENVIRONMENT_CONFIRM, ENVIRONMENT_SELECT
        environment_confirm = choice.intent.startswith(ENVIRONMENT_CONFIRM)
        environment_step = environment_confirm or choice.intent.startswith(ENVIRONMENT_SELECT)
        confidence = self.settings.ocr_confidence
        current_account = (checked_account_key(scene, confidence) if environment_step else
                           account_key(scene, max(.85, confidence)))
        if data.get('account_key') != current_account:
            raise AutomationError('当前账号与已记录对局不一致，未发送标准动作。')
        if choice.intent == 'start_standard_a8_40':
            if data['status'] != 'start_pending' or len(data['actions']) != 1:
                raise AutomationError('标准开局已有提交记录，未重复开始。')
        elif data['status'] != 'active':
            raise AutomationError('尚未核实标准对局已开始。')
        initial_confirm = environment_confirm and choice.payload in ((), ('1-1',))
        environment_scope = ('actions', 'expected_board')
        if environment_step and any(data.get(key) != store.data.get(key) for key in environment_scope):
            raise AutomationError('投资环境位面或动作与落盘记录不一致，未发送输入。')
        if environment_step:
            from contextlib import ExitStack
            from .currency_wars_initial import evidence_ref, require_evidence_pixels
            from .storage import file_revision, hold_read_sources
        initial_keys = ('initial_environment', 'initial_shop_return', 'initial_shop_observation', 'initial_shop_observation_history')
        if any(key in store.data or key in data for key in initial_keys):
            from .currency_wars_initial import validate_origin
            for key in initial_keys:
                if json.dumps(data.get(key), sort_keys=True, allow_nan=False) != json.dumps(store.data.get(key), sort_keys=True, allow_nan=False):
                    raise AutomationError('初始环境来源尚未与落盘记录一致，未发送输入。')
            origin = validate_origin(data)
            if 'initial_shop_return' in data:
                from .currency_wars_initial_shop import validate_return
                validate_return(data)
            if 'initial_shop_observation' in data or 'initial_shop_observation_history' in data:
                from .currency_wars_initial_shop_observation import validate as validate_shop_observation
                validate_shop_observation(data,current=choice.intent=='close_standard_initial_shop')
            if initial_confirm:
                if (origin['action_id'] != data['actions'][-1]['id']
                        or evidence_ref(scene, data['actions'][-1]['before'], origin['run_dir']) != origin['origin']['before']):
                    raise AutomationError('初始环境确认前画面与落盘来源不一致。')
        elif initial_confirm:
            raise AutomationError('初始环境确认尚未保存专用来源，未发送输入。')
        from .currency_wars_standard_investment import shop_input_scope
        from .currency_wars_standard_investment_refresh import input_scope as investment_refresh_input_scope
        from .currency_wars_standard_progress import progress_input_scope
        from .currency_wars_standard_encounter import dispatch_sources as encounter_dispatch_sources
        from .currency_wars_standard_double_supply import (
            dispatch_sources as supply_dispatch_sources, same_journal as same_supply_journal,
        )
        encounter_sources = encounter_dispatch_sources(data, choice, self.report.run_dir, input_epoch, store.path.parent)
        supply_sources = supply_dispatch_sources(data, choice, scene, self.report.run_dir, input_epoch,
                                                  self.settings.ocr_confidence)
        if encounter_sources and data != store.data:
            raise AutomationError('遭遇原节点或本次意图与落盘记录不一致，未发送输入。')
        if supply_sources and not same_supply_journal(data, store.data):
            raise AutomationError('双件补给原节点或本次意图与落盘记录不一致，未发送输入。')
        use_durable_source = (loot_sale_input_scope(choice, store.data, data)
                              or progress_input_scope(choice.intent, store.data, data)
                              or shop_input_scope(choice.intent, store.data, data)
                              or investment_refresh_input_scope(choice.intent, store.data, data)
                              or encounter_sources or supply_sources)
        session = data if use_durable_source or environment_step else store.data
        if choice.intent in ('open_standard_bench_reward', 'choose_standard_reward'):
            investment = store.data.get('investment', {})
            if investment != data.get('investment', {}):
                raise AutomationError('投资来源尚未与落盘记录一致，未发送输入。')
            if investment.get('status') == 'reward_verifying':
                from .currency_wars_standard_investment import box_opening_page
                box_opening_page(data, choice)
                session = data
        if next_action(scene, self.settings.ocr_confidence,session=session) != choice:
            raise AutomationError('标准开发动作与当前页面不符。')
        if choice.payload and data['actions'][-1].get('target') != list(choice.payload):
            raise AutomationError('标准动作目标与落盘记录不一致。')
        loop_guard = getattr(self.runner, 'currency_loop_guard', None)
        start_sources = ()
        if loop_guard is not None:
            start_sources = loop_guard.authorize(scene, data, max(.85, self.settings.ocr_confidence))
        guard._require_current_scene(scene)
        if choice.intent in ('deploy_standard_owned','stage_standard_exchange','stage_standard_relocate','stage_standard_equipment','stage_standard_consumable'):
            plan = choice.target
            route = ((plan.start[0],.735),(plan.end[0],.735)) if plan.zone=='back' or getattr(plan,'source_zone',None)=='back' else ()
            self._dispatch_drag(scene,plan.start,plan.end,route=route)
            return
        if choice.intent=='open_standard_bench_reward':
            self._currency_open_reward_held(scene,choice.payload[1])
            return
        loss_progress = (choice.intent in ('continue_standard_node', 'advance_standard_next_plane',
                                           'advance_standard_boss_intro', 'close_standard_arrival_shop')
                         and data.get('node_attempt', {}).get('node_loss_verified') is True)
        if choice.intent == 'start_standard_a8_40' or loss_progress or encounter_sources or supply_sources:
            self._currency_standard_evidenced_click(scene, choice, guard, store, data, loop_guard, start_sources,
                                                    encounter_sources=encounter_sources, supply_sources=supply_sources)
            self.sleep(self.settings.action_delay)
            return
        if environment_step:
            before = Path(data['actions'][-1]['before'])
            run_dir = origin['run_dir'] if initial_confirm else self.report.run_dir
            image = scene.image
            source = origin['origin']['before'] if initial_confirm else evidence_ref(scene, before, run_dir)
            journal, window = store.path, self.window
            confidence = self.settings.ocr_confidence

            def source_revisions():
                try:
                    return file_revision(before), file_revision(journal)
                except OSError as error:
                    raise AutomationError('初始环境证据或落盘意图不可复核，未发送输入。') from error

            def before_send():
                self.checkpoint()
                guard._require_current_scene(scene)
                try:
                    source_holds.enter_context(hold_read_sources((journal, before)))
                except OSError as error:
                    raise AutomationError('初始环境证据或落盘意图无法保持只读，未发送输入。') from error
                revisions = source_revisions()
                if evidence_ref(scene, before, run_dir) != source:
                    raise AutomationError('初始环境原输入画面证据已改变，未发送输入。')
                current = store.require_pending(choice.intent, input_epoch)
                if current != data:
                    raise AutomationError('初始环境落盘意图在发送前已改变，未发送输入。')
                if scene.image is not image:
                    raise AutomationError('初始环境当前采集已更换，未发送输入。')
                if image.flags.writeable:
                    image.setflags(write=False)
                    source_holds.callback(image.setflags, write=True)
                tokens, fields = tuple(scene.tokens), scene.field_reads.copy()
                if next_action(scene, confidence, session=current) != choice:
                    raise AutomationError('初始环境当前卡片与原提交不一致，未发送输入。')
                if revisions != source_revisions():
                    raise AutomationError('初始环境证据或落盘意图在发送前已改变，未发送输入。')
                require_evidence_pixels(scene, source)
                live = store.data
                if any(current.get(key) != live.get(key) for key in (*environment_scope, *initial_keys)):
                    raise AutomationError('投资环境位面或落盘意图在发送前已改变，未发送输入。')
                if checked_account_key(scene, confidence) != current.get('account_key'):
                    raise AutomationError('初始环境当前账号与原提交不一致，未发送输入。')

                # Keep the files and pixels protected while the last window check runs.
                window.guard(geometry)
                if (self.window is not window or getattr(self, 'currency_standard_session', None) is not store
                        or store.path != journal or store.data is not live):
                    raise AutomationError('初始环境落盘意图在发送前已改变，未发送输入。')
                if (scene.captured_at != captured_at or scene.geometry != geometry
                        or scene.image is not image or image.flags.writeable
                        or tuple(scene.tokens) != tokens or scene.field_reads != fields
                        or self.settings.ocr_confidence != confidence):
                    raise AutomationError('初始环境当前画面与原提交不一致，未发送输入。')
                if self.runner.input_epoch != input_epoch:
                    raise InputInterrupted('初始环境输入代次已改变，未沿用旧意图。')
                if getattr(self.runner, 'stop_requested', False) is True:
                    raise Stopped('任务已停止。')
                guard._require_current_scene(scene)
                if window.emergency_pressed():
                    raise Stopped('F10 紧急停止。')
                self.last_scene, self._scroll_anchor = None, None
        else:
            self.last_scene, self._scroll_anchor = None, None
        try:
            if environment_step:
                # The final callback acquires the holds through the native submission.
                with ExitStack() as source_holds:
                    window.click(*choice.target.center, geometry, before_send=before_send)
            else:
                self.window.click(*choice.target.center, scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        finally:
            if environment_step:
                self.last_scene, self._scroll_anchor = None, None
        self.sleep(self.settings.action_delay)

    def _currency_standard_evidenced_click(self, scene, choice, guard, store, data, loop_guard, start_sources,
                                          *, encounter_sources=(), supply_sources=()):
        from .currency_wars_identity import account_key, installed_client
        from .currency_wars_initial import _pixels, evidence_ref, source_file_ref
        from .currency_wars_points_goal import require_start_window
        from .currency_wars_standard_encounter import dispatch_sources, require_files, same_account
        from .currency_wars_standard_double_supply import (
            INPUT as DOUBLE_SUPPLY_INPUT, dispatch_sources as supply_dispatch_sources,
            input_state as supply_input_state, same_journal as same_supply_journal,
        )
        from .currency_wars_standard_flow import next_action
        from .currency_wars_standard_node import original_loss_files

        starting = choice.intent == 'start_standard_a8_40'
        encounter_followup = choice.encounter_arrival is not None
        operation = ('标准开局' if starting else '遭遇推进' if encounter_sources
                     else '双件补给' if supply_sources else '节点失利推进')
        before = data['actions'][-1].get('before')
        if not isinstance(before, str) or not before:
            raise AutomationError(operation + '缺少原始画面，未发送输入。')
        journal, window = store.path, self.window
        run_dir, epoch, confidence = self.report.run_dir, self.runner.input_epoch, self.settings.ocr_confidence
        origin = data['node_history'][-1] if encounter_followup else data.get('node_attempt', {})
        losses = (original_loss_files(dict(data, node_attempt=origin), journal.parent)
                  if not starting and not supply_sources and origin.get('node_loss_verified') is True else ())
        files = [store.path, Path(before), *(Path(source) for source in start_sources),
                 *(path for path, _ in losses), *(path for path, _ in encounter_sources)]
        files.extend(Path(source['path']) for source in supply_sources if source['path'] != before)
        if loop_guard is not None:
            files.append(loop_guard.store.path)
        executable = getattr(window, 'path', None)
        hwnd = getattr(window, 'hwnd', None)
        if encounter_followup or supply_sources:
            version_file = data.get('client', {}).get('source')
            if not isinstance(version_file, str) or not version_file:
                raise AutomationError(operation + '缺少当前客户端版本来源。')
            files.append(Path(version_file))
        geometry, captured_at, image = scene.geometry, scene.captured_at, scene.image

        def encounter_scope_matches(saved):
            live = store.data
            start = origin['start_action_id']
            if encounter_followup:
                end = choice.encounter_arrival + 2
                if (live.get('node_history', [])[-1:] != saved['node_history'][-1:]
                        or live['actions'][-1:] != saved['actions'][-1:]
                        or live['actions'][start:end] != saved['actions'][start:end]
                        or getattr(window, 'hwnd', None) != hwnd
                        or getattr(window, 'path', None) != executable):
                    return False
            elif live['actions'][start:] != saved['actions'][start:]:
                return False
            fields = ('node_attempt', 'client', 'account_key', 'account_verified_run', 'account_verified_epoch',
                      'match_id', 'status', 'start_verified', 'rules_version', 'loop_owner',
                      'entry', 'mode', 'rank', 'wealth')
            return (self.window is window and getattr(self, 'currency_standard_session', None) is store and store.path == journal
                    and self.report.run_dir == run_dir and len(live['actions']) == len(saved['actions'])
                    and all(live.get(key) == saved.get(key) for key in fields))

        def revisions():
            try:
                return tuple(file_revision(path) for path in files)
            except OSError as error:
                raise AutomationError(operation + '的记录或原始画面已不可读。') from error

        def before_send(held):
            self.checkpoint()
            guard._require_current_scene(scene)
            held.enter_context(hold_read_sources(files))
            saved_revisions = revisions()
            saved = store.require_pending(choice.intent, self.runner.input_epoch)
            if saved != data or not (same_supply_journal(saved, store.data) if supply_sources else saved == store.data):
                raise AutomationError(operation + '的原落盘意图已改变，未发送输入。')
            if supply_sources:
                arrival = saved['actions'][-1][DOUBLE_SUPPLY_INPUT]['origin_action_id']
                start = saved['actions'][arrival]['target'][1]
                supply_state = deepcopy(supply_input_state(store.data, start))
            try:
                reference = evidence_ref(scene, before, self.report.run_dir)
            except AutomationError as error:
                raise AutomationError(operation + '的原始画面与当前采集不符或不可读。') from error
            if encounter_sources:
                if (dispatch_sources(saved, choice, run_dir, epoch, journal.parent) != encounter_sources
                        or reference != encounter_sources[-1][1]):
                    raise AutomationError('遭遇当前输入来源与原落盘意图不一致。')
                require_files(encounter_sources, run_dir)
            if supply_sources and supply_dispatch_sources(saved, choice, scene, run_dir, epoch, confidence) != supply_sources:
                raise AutomationError('双件补给当前候选或原反馈证据已改变，未发送输入。')
            if encounter_followup or supply_sources:
                client = installed_client(window.current_executable() if supply_sources else executable)
                if any(saved['client'].get(key) != value for key, value in client.items()):
                    raise AutomationError(operation + '的安装版本来源已改变，未发送输入。')
            if any(source_file_ref(path, path.parent)['sha256'] != digest for path, digest in losses):
                raise AutomationError('原节点失利证据已改变，未继续挑战。')
            self._currency_weekly_checkpoint()
            if (loop_guard is not None
                    and loop_guard.authorize(scene, saved, max(.85, self.settings.ocr_confidence)) != start_sources):
                raise AutomationError(operation + '的循环来源已改变，未发送输入。')
            if revisions() != saved_revisions:
                raise AutomationError(operation + '的记录或原始画面在发送前已改变。')
            if scene.image is not image:
                raise AutomationError(operation + '的当前采集已更换。')
            if image.flags.writeable:
                image.setflags(write=False)
                held.callback(image.setflags, write=True)
            tokens, field_reads = tuple(scene.tokens), scene.field_reads.copy()
            observed_account = (same_account(scene, saved, confidence) if encounter_sources or supply_sources
                                else account_key(scene, confidence) == saved['account_key'])
            if (_pixels(image) != reference['pixel_sha256']
                    or not observed_account
                    or next_action(scene, confidence, session=saved) != choice):
                raise AutomationError(operation + '的当前账号、页面或目标已改变，未发送输入。')
            # The read handles remain held through SendInput. Recheck the
            # window and controls after hashing and re-deriving the target.
            window.guard(geometry)
            if window.emergency_pressed():
                raise Stopped('F10 紧急停止。')
            if starting and loop_guard is not None:
                require_start_window(loop_guard.store)
            guard._require_current_scene(scene)
            if (scene.geometry != geometry or scene.captured_at != captured_at or scene.image is not image
                    or image.flags.writeable or tuple(scene.tokens) != tokens):
                raise AutomationError(operation + '的当前采集在发送前已改变。')
            if encounter_sources:
                if (not encounter_scope_matches(saved) or scene.field_reads != field_reads
                        or self.settings.ocr_confidence != confidence):
                    raise AutomationError('遭遇输入意图或当前画面在发送前已改变。')
                if self.runner.input_epoch != epoch:
                    raise InputInterrupted('遭遇输入代次已改变，未沿用旧意图。')
            if supply_sources:
                if (self.window is not window or self.currency_standard_session is not store or store.path != journal
                        or self.report.run_dir != run_dir or getattr(window, 'hwnd', None) != hwnd
                        or getattr(window, 'path', None) != executable or self.settings.ocr_confidence != confidence
                        or scene.field_reads != field_reads or supply_input_state(store.data, start) != supply_state):
                    raise AutomationError('双件补给输入意图或当前画面在发送前已改变。')
                if self.runner.input_epoch != epoch:
                    raise InputInterrupted('双件补给输入代次已改变，未沿用旧意图。')
            if self.runner.stop_requested:
                raise Stopped('任务已停止。')

        try:
            with ExitStack() as held:
                window.click(*choice.target.center, geometry, before_send=lambda: before_send(held))
        except FocusLost:
            self._focus_interrupted()
        except (OSError, ValueError) as error:
            raise AutomationError(operation + '的记录或原始画面无法稳定读取。') from error
        finally:
            self.last_scene, self._scroll_anchor = None, None

    def power_plan_battle_input(self, scene: Scene, target: Token, cost: int, *, support_decision=None):
        from .policy import guard_click, replenishment_dialog
        from .power_plan_run import PowerRun
        from .workflows import BOTTOM, TITLE, DailyWorkflow

        self._require_gameplay_input()
        budget = getattr(self, 'battle_budget', None)
        plan = getattr(budget, 'power_plan', None)
        if (self.report.operation != 'daily' or not self.settings.allow_stamina_spend
                or self.settings.dungeon_category == 'planar' or not isinstance(plan, PowerRun) or plan.ctx is not self):
            raise AutomationError('普通体力计划支付缺少本次副本和预算。')
        self.checkpoint()
        epoch, captured_at, geometry = self.scene_epoch, scene.captured_at, scene.geometry
        tokens = tuple(scene.tokens)
        starts = [token for token in tokens if token.within(BOTTOM) and normalize(token.text) == '开始挑战']
        if geometry is None or not scene.has('队伍', TITLE) or starts != [target]:
            raise AutomationError('普通体力计划未核实队伍和唯一的开始挑战按钮。')

        def require_current():
            if self.runner.stop_requested:
                raise Stopped('普通体力计划支付前已停止。')
            if scene is not self.last_scene or self.scene_epoch != epoch or self.runner.input_epoch != epoch:
                raise InputInterrupted('普通体力计划支付前输入代次或画面已变化。')
            if (scene.geometry != geometry or scene.captured_at != captured_at or not 0 <= time.monotonic()-captured_at <= 8
                    or tuple(scene.tokens) != tokens):
                raise AutomationError('普通体力计划支付前队伍画面或文字已变化。')

        require_current()
        guard_click(scene, target)
        if replenishment_dialog(scene):
            raise AutomationError('开拓力补充或兑换界面只允许取消。')
        visible, balance = DailyWorkflow._team_stamina(scene, self.settings.ocr_confidence)
        if visible and plan.require_balance(self, scene, balance) < cost:
            raise AutomationError('队伍页当前开拓力低于原费用，未开始挑战。')
        self.log(f'点击：{target.text}')
        budget.reserve(cost)
        intent = plan.data['intent']
        ready_to_send = False

        def before_send():
            nonlocal ready_to_send
            if ready_to_send:
                raise AutomationError('普通体力计划本批已通过发送，支付待核对。')
            self.window.guard(geometry)
            plan.require_ordinary_intent(self, intent)
            if intent['epoch'] != epoch:
                raise InputInterrupted('普通体力计划支付意图的输入代次已变化。')
            if intent['row'] == -2:
                from .echo_weekly import require_week
                require_week(plan.data['weekly_echo'])
            if support_decision is not None:
                support_decision.require_current(self, scene)
            require_current()
            if support_decision is None:
                ready_to_send = True

        def before_submit():
            nonlocal ready_to_send
            support_decision.require_current(self, scene)
            require_current()
            ready_to_send = True

        try:
            checks = {'before_send': before_send}
            if support_decision is not None:
                checks['before_submit'] = before_submit
            self.window.click(*target.center, geometry, **checks)
        except (AutomationError, OSError) as error:
            # The task tree's final week check can veto after before_send.
            if ready_to_send and not isinstance(error, FollowupWeekExpired):
                if isinstance(error, FocusLost):
                    self._focus_interrupted()
                if isinstance(error, Stopped):
                    raise
                raise AutomationError(f'普通体力计划本批已尝试提交，支付待核对。{error}') from error
            plan.record_unsent(self, intent, str(error))
            if isinstance(error, Stopped):
                raise
            raise AutomationError(f'普通体力计划本批开始挑战未发送。{error}') from error
        if not ready_to_send:
            raise AutomationError('普通体力计划缺少原生发送回执，本批支付待核对。')
        self.last_scene = None
        self.sleep(self.settings.action_delay)

    def click(self, scene: Scene, target: Token | tuple[float, float], *, du_intent="navigation",
              du_feedback_deadline: float | None = None, assignment_intent: str | None = None):
        self._require_gameplay_input()
        if du_feedback_deadline is not None and (self.report.operation != 'differential_universe'
                or du_intent not in ('curio_discard_confirm','du_tutorial_close')):
            raise AutomationError('差分舍弃专用反馈时限仅用于本次确认和弹层关闭。')
        if du_intent.startswith('du_save_'):
            raise AutomationError('差分存档输入须使用本次持久保存意图，未通过通用点击发送。')
        self.checkpoint()
        if self.scene_epoch != self.runner.input_epoch:
            raise InputInterrupted("暂停恢复后须重新识别，未发送旧画面点击。")
        if scene is not self.last_scene or time.monotonic() - scene.captured_at > 8:
            raise AutomationError("识别画面已经过期，请重新识别后操作。")
        from .policy import guard_click, guard_differential_universe_click, replenishment_dialog
        assignment_commit = None
        if assignment_intent is not None:
            from .daily_assignment_scope import before_submit
            assignment_commit = before_submit(self, scene, target, assignment_intent)
        elif getattr(self.runner, 'assignments_only', False) is True:
            from .daily_assignment_scope import require_navigation
            require_navigation(scene, target)
        weekly_start_guard = None
        synthesis_resource_guard = None
        points_goal = None
        points_request = None
        if self.report.operation == "differential_universe":
            goal = getattr(self, 'du_points_goal', None)
            if goal is not None or getattr(self.runner, 'du_until_points', False) is True:
                from .du_periodic_points import is_setup_launch_click
                if du_intent != 'periodic_start' and is_setup_launch_click(scene, target):
                    raise AutomationError('周期积分目标的启动按钮须走专用启动检查，未发送点击。')
                if du_intent in ('periodic_start', 'du_team_open'):
                    if goal is None:
                        raise AutomationError('本次周期积分来源未核实，未发送点击。')
                    goal.require_setup(scene, target=target if du_intent == 'periodic_start' else None)
            if du_intent=='periodic_start':
                points_goal = goal
                if points_goal is not None:
                    report = self.report.differential_universe
                    actions = report.get('actions', [])
                    points_request = actions[-1] if actions else {}
                    if (points_request.get('intent') != 'periodic_start' or points_request.get('status') != 'requested'
                            or points_request.get('run') != report.get('current_run')
                            or points_request.get('action') != getattr(target, 'text', None)):
                        raise AutomationError('本局周期积分启动缺少已记录的请求，未发送点击。')
                from .weekly_plan import WeeklyGuard
                candidate=getattr(self.runner,'weekly_plan',None)
                if isinstance(candidate,WeeklyGuard):
                    weekly_start_guard=candidate
                    weekly_start_guard.require_current_week()
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
            from .daily_synthesis import RESOURCE_INPUTS, guard_click as guard_synthesis_click
            guard_synthesis_click(scene, target, du_intent, self.report.daily_synthesis)
            if du_intent in RESOURCE_INPUTS:
                synthesis_resource_guard = guard_synthesis_click
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
        discard_feedback = du_intent == 'curio_discard_confirm' or du_feedback_deadline is not None
        station_confirmation = self.report.operation == 'differential_universe' and du_intent == 'station_confirm'
        if station_confirmation:
            station_window, station_geometry = self.window, scene.geometry
            station_epoch, station_occlusions = self.scene_epoch, self.capture_occlusion_count
            station_time, station_image, station_tokens = scene.captured_at, scene.image, tuple(scene.tokens)
        if self.report.operation == "differential_universe":
            before = self.evidence(scene, "du_before_" + re.sub(r"[^\w\u3400-\u9fff-]", "_", label)[:32])
            if discard_feedback:
                self.checkpoint()
                if self.scene_epoch != self.runner.input_epoch or scene is not self.last_scene:
                    raise InputInterrupted('奇物舍弃或关闭弹层前画面已改变，未发送旧目标。')
                now = time.monotonic()
                if du_feedback_deadline is not None and now - self.runner.inactive_duration >= du_feedback_deadline:
                    raise AutomationError('强制舍弃奇物反馈待核对，已超过观察时限，未发送输入。')
                if not 0 <= now - scene.captured_at <= 8:
                    raise AutomationError('奇物舍弃证据保存后画面已过期，反馈待核对，未发送输入。')
            du_record = {"action": label, "status": "requested" if points_goal is not None or station_confirmation else "sent",
                         "before": str(before), "page_text": scene.text}
            self.report.differential_universe.setdefault("actions", []).append(du_record)
        if weekly_start_guard is not None:
            try:
                self.checkpoint()
                if self.scene_epoch!=self.runner.input_epoch or scene is not self.last_scene:
                    raise InputInterrupted('周常启动前输入代次或当前画面改变，未发送旧目标。')
                if not 0<=time.monotonic()-scene.captured_at<=8:
                    raise AutomationError('周常启动证据保存后画面已过期，未发送输入。')
                weekly_start_guard.require_current_week()
            except AutomationError as error:
                if du_record is not None:
                    du_record.update(status='not_sent',reason='weekly_start_revalidation_failed',detail=str(error))
                raise
        if synthesis_resource_guard is not None:
            self.checkpoint()
            if self.scene_epoch != self.runner.input_epoch or scene is not self.last_scene:
                raise InputInterrupted('合成输入前代次或当前画面改变，未发送旧目标。')
            if not 0 <= time.monotonic() - scene.captured_at <= 8:
                raise AutomationError('合成输入前画面已过期，未发送输入。')
            synthesis_resource_guard(scene, target, du_intent, self.report.daily_synthesis)
        try:
            if assignment_commit is not None:
                self.window.click(*coordinates, scene.geometry, before_submit=assignment_commit)
            elif station_confirmation:
                def check_station_before_send():
                    if self.window is not station_window:
                        raise InputInterrupted('差分选站确认前窗口已改变，未发送旧目标。')
                    guard_differential_universe_click(scene, target, intent='station_confirm')
                    station_window.guard(station_geometry)
                    if (station_window.emergency_pressed() is True
                            or getattr(self.runner, 'stop_requested', False) is True):
                        raise Stopped('差分选站确认已停止，未发送输入。')
                    if (self.scene_epoch != station_epoch or self.runner.input_epoch != station_epoch
                            or scene is not self.last_scene or scene.geometry != station_geometry
                            or scene.image is not station_image or tuple(scene.tokens) != station_tokens
                            or self.capture_occlusion_count != station_occlusions or scene.captured_at != station_time
                            or not 0 <= time.monotonic() - station_time <= 8):
                        raise InputInterrupted('差分选站确认画面已改变或过期，未发送旧目标。')
                    du_record['status'] = 'unknown'

                try:
                    station_window.click(*coordinates, station_geometry, before_send=check_station_before_send)
                except (AutomationError, OSError) as error:
                    if du_record['status'] == 'requested':
                        du_record.update(status='not_sent', reason='station_confirmation_revalidation_failed', detail=str(error))
                    raise
                du_record['status'] = 'sent'
            elif points_goal is None:
                self.window.click(*coordinates,scene.geometry)
            else:
                try:
                    with ExitStack() as held:
                        def check_points_before_send():
                            points_goal.require_setup(scene, target=target, read_sources=held)
                            points_request['status'] = du_record['status'] = 'unknown'

                        self.window.click(*coordinates, scene.geometry, before_send=check_points_before_send)
                except (AutomationError, OSError) as error:
                    if du_record['status'] == 'requested':
                        du_record.update(status='not_sent',reason='points_goal_revalidation_failed',detail=str(error))
                    raise
                points_request['status'] = du_record['status'] = 'sent'
        except FocusLost:
            if points_goal is not None:
                raise
            self._focus_interrupted()
        self.last_scene = None
        self.sleep(self.settings.action_delay)
        # Forced curio discard and its one overlay close share the workflow's deadline.
        if du_record is not None and not discard_feedback:
            after = self._snapshot_after_du_input()
            after_path = self.evidence(after, "du_after_action")
            du_record["after"] = str(after_path)
            du_record["after_text"] = after.text

    def differential_universe_station_reroll_click(self, scene, target, attempt):
        from .du_station_reroll import StationReroll

        self._require_gameplay_input()
        if (self.report.operation != 'differential_universe'
                or not isinstance(attempt, StationReroll) or attempt.context is not self
                or self.settings.differential_universe_station_reroll is not True):
            raise AutomationError('选站重抽仅允许本次已开启的新周期局输入。')
        attempt.dispatch(scene, target)
        self.last_scene = None

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
        from .weekly_plan import WeeklyGuard
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
        try:
            weekly = getattr(self.runner, "weekly_plan", None)
            if isinstance(weekly, WeeklyGuard) and weekly.until_points:
                weekly.persist_points_ledger(du, payload)
                return
            temp = ledger.with_suffix(f".{uuid.uuid4().hex}.tmp")
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
        raise AutomationError('差分存档名称须绑定本次持久保存意图，未直接输入。')

    def differential_universe_archive_input(self, scene: Scene, action):
        from .du_archive_workflow import ArchiveAction
        if (self.report.operation != 'differential_universe' or not self.settings.differential_universe_save
                or type(action) is not ArchiveAction):
            raise AutomationError('差分存档需要已开启的保存任务及本次明确动作。')
        workflow = getattr(self, 'du_archive_workflow', None)
        if workflow is None or workflow.c is not self:
            raise AutomationError('缺少本次差分存档流程与落盘意图。')
        if sum(value is not None for value in (action.target, action.key, action.name)) != 1:
            raise AutomationError('差分存档动作形态不唯一，未输入。')
        if (action.target is not None and not isinstance(action.target, Token)
                or action.key is not None and action.key != 'esc'
                or action.name is not None and not isinstance(action.name, str)):
            raise AutomationError('差分存档动作类型未核实，未输入。')
        window, geometry, captured_at = self.window, scene.geometry, scene.captured_at
        epoch, occlusions = self.scene_epoch, self.capture_occlusion_count
        tokens = tuple(scene.tokens)
        durable_checked = False
        attempted = False

        def before_submit():
            nonlocal attempted
            self.checkpoint()
            workflow.require_current_input(scene, action)
            require_followup_week()
            window.guard(geometry)
            if (window.emergency_pressed() is True
                    or getattr(self.runner, 'stop_requested', False) is True):
                raise Stopped('差分存档已停止，未发送当前动作。')
            if (attempted or self.window is not window or scene is not self.last_scene
                    or self.scene_epoch != epoch or self.runner.input_epoch != epoch
                    or scene.geometry != geometry or scene.captured_at != captured_at
                    or scene.image is not image or tuple(scene.tokens) != tokens
                    or self.capture_occlusion_count != occlusions
                    or not 0 <= time.monotonic() - captured_at <= 8):
                raise InputInterrupted('差分存档发送前的画面或窗口来源已变化。')
            attempted = True
            self.last_scene, self._scroll_anchor = None, None

        try:
            import numpy as np

            if geometry is None:
                raise AutomationError('差分存档缺少当前窗口几何。')
            if not isinstance(scene.image, np.ndarray):
                raise AutomationError('差分存档缺少当前画面的原始像素。')
            # Keep the validated pixels immutable until the first native packet.
            image = np.frombuffer(scene.image.tobytes(), dtype=scene.image.dtype).reshape(scene.image.shape)
            scene.image = image
            self.checkpoint()
            workflow.authorize(scene, action)
            window.guard(geometry)
            self.checkpoint()
            workflow.authorize(scene, action)
            durable_checked = True
            if action.target is not None:
                window.click(*action.target.center, geometry, before_submit=before_submit)
            elif action.name is not None:
                window.type_du_save_name(action.name, geometry, checkpoint=self._du_held_checkpoint(scene),
                                         before_submit=before_submit)
            else:
                window.key('esc', expected=geometry, before_submit=before_submit)
        except (AutomationError, OSError) as error:
            if not attempted:
                self.last_scene, self._scroll_anchor = None, None
                if durable_checked:
                    workflow.mark_not_sent(action)
            elif isinstance(error, FocusLost):
                self._focus_interrupted()
            raise
        if not attempted:
            self.last_scene, self._scroll_anchor = None, None
            raise AutomationError('差分存档原生发送缺少边界回执，动作待核对。')
        self.sleep(self.settings.action_delay)

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

    def evidence(self, scene: Scene, name: str, *, with_sha256=False):
        stamp = datetime.now().strftime("%H%M%S_%f")
        return save_scene(scene, Path(self.report.run_dir), f"{stamp}_{name}", with_sha256=with_sha256)

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
        if self.report.operation in ('du_rewards', 'build_target_read', 'build_target_preview', 'build_target_plan',
                                     'team_preset_calibration'):
            self._require_gameplay_input()
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
        self._dispatch_drag(scene,start,end,route=route)

    def _dispatch_drag(self, scene, start, end, *, route=()):
        """Shared release/focus mechanics after a dedicated action gate."""
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
        first_node = getattr(self, '_legacy_first_node', None)
        # Invalidate before dispatch, including unknown input outcomes.
        try:
            if first_node is not None and first_node.applies(scene):
                first_node.click(scene, target)
            else:
                self.last_scene, self._scroll_anchor = None, None
                self.window.click(*target.center, scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        except OSError as error:
            raise AutomationError('出战前置证据读取或共享读保护失败，原意图保留。') from error
        self.sleep(self.settings.action_delay)

    def currency_continue_node(self, scene: Scene):
        if self.report.operation != 'currency_wars_flow_test':
            raise AutomationError('当前运行类型不允许推进货币战争结算。')
        if getattr(self, '_legacy_first_node', None) is not None:
            raise AutomationError('本次超频 A0 首节点只核对结果，下一节点接续待核对。')
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
        from .currency_wars_overclock_session import FLOW_OPERATION, START_ACTION
        session = getattr(self, 'overclock_session', None)
        if name == START_ACTION:
            raise AutomationError('超频 A0 开局须经共享原生开局门禁。')
        if (self.report.operation != FLOW_OPERATION or session is None
                or not self.runner.currency_start_from_lobby and name != 'advance_boss_preview'):
            raise AutomationError('本次运行未请求从主页开始整局验证。')
        from .currency_wars_entry import entry_target
        from .currency_wars import CurrencyWarsWorkflow
        session.require_history()
        if name != 'advance_boss_preview' and session.data is not None:
            raise AutomationError('已核实本局开局，未再次进入模式页。')
        self.checkpoint()
        CurrencyWarsWorkflow(self)._require_current_scene(scene)
        current,_,target=entry_target(scene,self.settings.ocr_confidence)
        if current!=name:
            raise AutomationError('开局页面与本次动作不一致。')
        try:
            if name == 'advance_boss_preview':
                from .currency_wars_overclock import click_legacy_preview
                click_legacy_preview(self, scene, target)
            else:
                self.last_scene, self._scroll_anchor = None, None
                self.window.click(*target.center, scene.geometry)
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
        return self._currency_open_reward_held(scene,slot)

    def _currency_open_reward_held(self,scene,slot):
        from .currency_wars_deployment import _BENCH_CENTERS
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
        first_node = getattr(self, '_legacy_first_node', None)
        try:
            if first_node is not None and first_node.applies(scene):
                first_node.click_pickup(scene, target)
            else:
                self.last_scene, self._scroll_anchor = None, None
                self.window.click(*target[:2], scene.geometry)
        except FocusLost:
            self._focus_interrupted()
        except OSError as error:
            raise AutomationError('晶矿前置证据读取或共享读保护失败，原意图保留。') from error
        self.sleep(self.settings.action_delay)

    def template(self, scene: Scene, name: str, roi=(0, 0, 1, 1), threshold=0.88):
        path = RESOURCE_ROOT / "assets" / "templates" / f"{name}.png"
        if not path.exists():
            return None
        return self.vision.template(scene, path, roi, threshold)


class Runner:
    def __init__(self, settings: Settings, emit=None, *, new_battle_run=False, operation="daily",
                 du_runs=None, du_resume_active=False, du_periodic_rank=None, du_use_cassettes=False, du_until_points=False,
                 du_periodic_rewards=False,
                 currency_source_slot=3,currency_zone='back',currency_target_level=0,currency_start_from_lobby=False,
                 currency_control_probe=False, currency_timeout_probe=False, currency_locate=False,
                 currency_configure=False, currency_wealth=None, currency_resume=False, weekly_plan=None, currency_strategy=None,
                 currency_remembrance_name=None,currency_fast_mode=None,currency_loop_guard=None,currency_rewards_resume=False,currency_weekly_guard=None,
                 use_power_plan=False,new_power_plan=False,currency_overclock_open_a0=False,build_target_selection=None,
                 challenge_lobby_mode=None, assignments_only=False):
        from dataclasses import replace
        if operation == 'reward_only':
            from .recovery import reward_only_settings
            settings = reward_only_settings(settings)
        else:
            settings = replace(settings)
        if (type(assignments_only) is not bool or assignments_only
                and (operation != 'daily' or settings.assignments is not True or new_battle_run or use_power_plan
                     or any((settings.battle, settings.daily, settings.redemption_enabled, settings.mail, settings.battlepass)))):
            raise ValueError('独立委托只允许本次明确选择已有委托奖励。')
        self.assignments_only = assignments_only
        if operation in ('build_target_read', 'build_target_preview', 'build_target_plan') and new_battle_run:
            raise ValueError('培养目标读取不能建立刷本预算。')
        if operation == 'team_preset_calibration' and new_battle_run:
            raise ValueError('编队入口校准不能建立刷本预算。')
        if operation == 'build_target_plan' or build_target_selection is not None:
            from .build_target_preview import BuildTargetSelection
            if operation != 'build_target_plan' or type(build_target_selection) is not BuildTargetSelection:
                raise ValueError('培养草稿需要独立入口和明确选择。')
        self.build_target_selection = build_target_selection
        if type(du_use_cassettes) is not bool or du_use_cassettes and operation != 'du_rewards':
            raise ValueError('已有月下卡带选项仅用于独立差分领奖。')
        if type(du_periodic_rewards) is not bool or du_periodic_rewards and (operation != 'du_rewards' or du_use_cassettes):
            raise ValueError('周期积分领奖需要独立差分领奖，且与月下卡带互斥。')
        self.du_use_cassettes = du_use_cassettes
        self.du_periodic_rewards = du_periodic_rewards
        if (type(use_power_plan) is not bool or type(new_power_plan) is not bool or new_power_plan and not use_power_plan
                or use_power_plan and (operation!='daily' or not settings.battle)):
            raise ValueError('体力计划仅用于已选择刷本的日常入口，新目标须明确启用体力计划。')
        self.use_power_plan=use_power_plan;self.new_power_plan=new_power_plan
        if use_power_plan:settings.validate('power_plan')
        from .weekly_plan import WeeklyGuard
        if weekly_plan is not None and (not isinstance(weekly_plan, WeeklyGuard) or operation != "differential_universe"):
            raise ValueError("周常记录核验仅用于计划中的差分宇宙。")
        self.weekly_plan = weekly_plan
        from .currency_wars_loop_store import LoopGuard
        if currency_loop_guard is not None and (operation != 'currency_wars_standard' or not isinstance(currency_loop_guard, LoopGuard)):
            raise ValueError('循环逐局记录仅用于原生标准货币战争。')
        self.currency_loop_guard = currency_loop_guard
        from .currency_wars_weekly import WeekGuard
        if currency_weekly_guard is not None and (not isinstance(currency_weekly_guard,WeekGuard)
                or (operation,currency_weekly_guard.stage) not in (('currency_wars_points','points'),('currency_wars_rewards','rewards'))):
            raise ValueError('货币战争周常归属仅允许对应积分／领奖子流程。')
        self.currency_weekly_guard=currency_weekly_guard
        if type(currency_rewards_resume) is not bool or currency_rewards_resume and operation!='currency_wars_rewards':
            raise ValueError('积分领奖接续仅用于独立积分领奖入口。')
        self.currency_rewards_resume=currency_rewards_resume
        if (type(currency_overclock_open_a0) is not bool or currency_overclock_open_a0 and
                (operation != 'currency_wars_overclock_configure' or new_battle_run)):
            raise ValueError('打开超频 A0 难度页需要独立超频入口。')
        self.currency_overclock_open_a0 = currency_overclock_open_a0
        if operation == 'challenge_lobby' or challenge_lobby_mode is not None:
            from .challenge_plan import MODE_LIMITS
            if (operation != 'challenge_lobby' or type(challenge_lobby_mode) is not str
                    or challenge_lobby_mode not in MODE_LIMITS or new_battle_run or weekly_plan is not None):
                raise ValueError('高难主页导航需要独立入口和明确模式。')
        self.challenge_lobby_mode = challenge_lobby_mode
        self.settings = settings
        self._challenge_prepare_mode = (settings.challenge_plan.get('mode') if operation == 'challenge_prepare'
                                        and isinstance(settings.challenge_plan, dict) else None)
        self._challenge_read_only = (operation == 'challenge_result' or self._challenge_prepare_mode == 'apocalyptic_shadow')
        self._foreground_only = self._challenge_read_only or operation in ('challenge_lobby', 'team_preset_calibration')
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
        from .currency_wars_prepare import PREPARATION_OPERATIONS
        preparation_operations = PREPARATION_OPERATIONS
        if type(currency_locate) is not bool or currency_locate and operation not in preparation_operations:
            raise ValueError('货币战争入口导航仅允许独立准备操作。')
        self.currency_locate = currency_locate
        if (type(currency_configure) is not bool or currency_configure and
                (operation not in ('currency_wars_prepare','currency_wars_standard') or not currency_locate)):
            raise ValueError('标准A8配置仅允许货币战争入口导航操作。')
        self.currency_configure = currency_configure
        if currency_wealth is not None:
            if operation != 'currency_wars_prepare' or not currency_configure:
                raise ValueError('财富档位覆盖仅允许独立配置入口。')
            from .currency_wars_standard import validate_wealth
            currency_wealth = validate_wealth(currency_wealth)
        self.currency_wealth = currency_wealth
        if type(currency_resume) is not bool or currency_resume and operation != 'currency_wars_standard':
            raise ValueError('接续标准对局只适用于标准开发入口。')
        self.currency_resume = currency_resume
        from .currency_wars_standard_policy import STRATEGIES
        if currency_strategy is not None and (operation != 'currency_wars_standard' or currency_strategy not in STRATEGIES):
            raise ValueError('货币战争策略仅用于标准入口，须为 default、aglaea 或 seele。')
        self.currency_strategy = currency_strategy
        from .currency_wars_names import validate_name
        if currency_remembrance_name is not None and operation!='currency_wars_standard':
            raise ValueError('记忆开拓者名称仅用于标准货币战争入口。')
        self.currency_remembrance_name=None if currency_remembrance_name is None else validate_name(currency_remembrance_name)
        from .currency_wars_equipment_mode import validate_fast_mode
        if currency_fast_mode is not None and operation!='currency_wars_standard':
            raise ValueError('速通装备设置仅用于标准货币战争入口。')
        self.currency_fast_mode=None if currency_fast_mode is None else validate_fast_mode(currency_fast_mode)
        if operation == 'currency_wars_standard':
            self.currency_locate = self.currency_configure = True
        if operation in ('currency_wars_points','currency_wars_rewards'):
            self.currency_locate = True
        self.currency_source_slot,self.currency_zone = currency_source_slot,currency_zone
        if type(currency_target_level) is not int or not 0<=currency_target_level<=10:
            raise ValueError('货币战争目标等级必须为0到10的整数。')
        self.currency_target_level=currency_target_level
        if type(currency_start_from_lobby) is not bool:
            raise ValueError('货币战争整局验证开关必须为布尔值。')
        if operation in ('currency_wars_overclock_start', 'currency_wars_overclock_prepare') and (
                new_battle_run or currency_start_from_lobby or weekly_plan is not None):
            raise ValueError('超频 A0 开局和备战各用独立入口。')
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
        if (type(du_until_points) is not bool or du_until_points and (operation != 'differential_universe'
                or du_runs is None or du_resume_active
                or settings.differential_universe_mode != 'periodic')):
            raise ValueError('周期积分目标须用于新开周期演算，并明确指定局数上限。')
        if weekly_plan is not None and (du_until_points != weekly_plan.until_points or du_until_points and (
                self.du_runs != weekly_plan.settings.weekly_runs or settings.differential_universe_save
                or settings.differential_universe_rewards or settings.differential_universe_daily or du_use_cassettes)):
            raise ValueError('差分周常积分目标须沿用原开局上限，只执行周期演算和积分核验。')
        self.du_until_points = du_until_points
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
        selected = [name for name in ("assignments", "battle", "daily", "redemption", "mail", "battlepass")
                    if ((self.settings.redemption_enabled and self.report.operation == 'daily')
                        if name == 'redemption' else getattr(self.settings, name))]
        if not selected:
            raise AutomationError("至少选择一个任务。")
        power=None
        if self.use_power_plan:
            from .power_plan_run import PowerWorkflow
            power=PowerWorkflow(context,new_goal=self.new_power_plan)
        for index, name in enumerate(selected):
            self.checkpoint()
            self.report.failure_task = name
            self.emit(dict(type="task", task=name, status="running", detail="正在执行"))
            try:
                result = self._resume_step(power.run if name=='battle' and power is not None else getattr(workflow, name), name)
            except Stopped:
                raise
            except Exception as error:
                result = TaskResult(name, "partial", f"未核实完成：{error}")
                self.report.error = str(error)
                self.report.safe_next = ("原委托结果待核对。请查看本次截图及当前领取状态。"
                                         if self.assignments_only else
                                         "已保留每日奖励验证；请人工返回主界面后仅重试未完成的免费领奖。"
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
            if name == 'redemption' and result.status != 'ok':
                for remaining in selected[index + 1:]:
                    skipped = TaskResult(remaining, 'skipped', '兑换页面或附件尚未核实，未继续输入。')
                    self.report.results.append(skipped)
                    self.emit(dict(type='task', **skipped.__dict__))
                break
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
        from .currency_wars_overclock import (
            OPERATION as OVERCLOCK_CONFIGURE, PREPARATION_MODE, configure_overclock,
            prepare_overclock, start_overclock,
        )
        from .currency_wars_overclock_session import FLOW_OPERATION, PREP_OPERATION, START_OPERATION
        self.report.failure_task = TASK
        self.report.safe_next = SAFE_NEXT
        overclock_detail = ("打开并核对超频 A0 难度页" if self.currency_overclock_open_a0
                            else "核对并配置当前模式页的超频选择")
        details = {
            OVERCLOCK_CONFIGURE: overclock_detail,
            START_OPERATION: '核对超频 A0 开局与首领预览',
            PREP_OPERATION: '核对原超频 A0 开局与当前备战步骤',
            'currency_wars_rewards': '核对并领取当前可领取积分奖励',
            'currency_wars_points': '核对当前积分与游戏周',
            'currency_wars_standard': '标准A8-40开发：核实开局与当前局面',
            'currency_wars_prepare': '启动准备：进入游戏，不开始对局',
            FLOW_OPERATION: '连续战斗与结算推进验证',
            'currency_wars_node_test': '当前节点战斗验证',
            'currency_wars_deploy_test': '单次部署验证',
            'currency_wars_drag_test': '单次前台拖动验证',
        }
        if getattr(getattr(context, 'overclock_session', None), 'legacy_handoff', False):
            details[FLOW_OPERATION] = '复核原超频 A0 对局的 1-1 首备战'
        self.emit(dict(type='task', task=TASK, status='running',
                       detail=details.get(self.report.operation, '只读识别与证据保存')))
        if self.report.operation == 'currency_wars_rewards':
            from .currency_wars_weekly_reward_run import inspect_rewards
            result=inspect_rewards(context)
        elif self.report.operation == 'currency_wars_points':
            from .currency_wars_points_run import inspect_points
            result = inspect_points(context)
        elif self.report.operation == 'currency_wars_standard':
            from .currency_wars_standard_flow import run_standard
            result = run_standard(context)
        elif self.report.operation == OVERCLOCK_CONFIGURE:
            result = configure_overclock(context)
        elif self.report.operation == START_OPERATION:
            result = start_overclock(context)
        elif self.report.operation == PREP_OPERATION:
            result = prepare_overclock(context)
        elif self.report.operation == 'currency_wars_prepare':
            if self.currency_locate:
                from .currency_wars_navigation import locate
                result = locate(context)
            else:
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
        data = self.report.currency_wars
        completed = (self.report.operation == 'currency_wars_standard' and result.status == 'success'
                     and data.get('status') == 'settled' and data.get('completion_verified') is True
                     and data.get('settlement_verified') is True)
        points_checked=(self.report.operation=='currency_wars_points' and result.status=='ok'
                        and data.get('mode')=='weekly_points' and data.get('points_verified') is True
                        and data.get('completion_verified') is False)
        rewards_checked=(self.report.operation=='currency_wars_rewards' and result.status=='ok'
                         and data.get('mode')=='weekly_rewards' and data.get('phase')=='returned'
                         and data.get('rewards_verified') is True and data.get('completion_verified') is False)
        mode_configured = (self.report.operation == OVERCLOCK_CONFIGURE and result.status == 'ok'
                           and data.get('mode_verified') is True and data.get('match_started') is False
                           and (not self.currency_overclock_open_a0 or data.get('difficulty_verified') is True)
                           and data.get('completion_verified') is False)
        overclock_started = (self.report.operation == START_OPERATION and result.status == 'ok'
                             and data.get('mode') == 'overclock_a0_start' and data.get('status') == 'verified'
                             and data.get('match_started') is True and data.get('completion_verified') is False)
        preparation_step = (self.report.operation == PREP_OPERATION and result.status == 'ok'
                            and data.get('mode') == PREPARATION_MODE and data.get('status') == 'verified'
                            and data.get('match_started') is True and data.get('completion_verified') is False)
        self.report.status = 'success' if (completed or points_checked or rewards_checked or mode_configured
                                           or overclock_started or preparation_step) else 'partial'
        if self.report.status == 'success':
            self.report.failure_task = ''

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

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
        require_followup_week()
        if self._overlay is not None:
            for message, level in self._overlay.drain_notices():
                self.log(message, level)
        if self._window is not None:
            if self._foreground_only:
                self._window.guard()
            else:
                self.wait_for_focus()

    def _prepare_daily_game(self):
        """Check first; launch only when absent, then focus once at startup."""
        self.log('检查游戏是否已启动。')
        try:
            self._window = find_game(self.settings.game_path)
            self.log('游戏已运行，准备置于前台并返回主界面。')
            return False
        except AutomationError:
            pass
        self.log(launch_game(self.settings))
        self.log('等待游戏窗口出现；使用已有登录状态进入游戏。')
        for _ in range(120):
            self.checkpoint()
            try:
                self._window = find_game(self.settings.game_path)
                return True
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
                if name == 'redemption':
                    raise AutomationError('兑换操作已中断，原提交与逐码结果保留；未重启整批或重放确认。')
                if name == 'assignments' and self.assignments_only:
                    raise AutomationError('独立委托输入或反馈已中断，保留本次待核对记录。')
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

    def _save_run_report(self, directory, points_workflow=None, *, challenge_reader=None, preview_source=None):
        temporary = directory / 'report.tmp'

        def write_report():
            payload = json.dumps(self.report.to_dict(), ensure_ascii=False, indent=2)
            temporary.write_text(payload, encoding='utf-8')
            return payload

        if challenge_reader is not None:
            challenge_reader.save_report(temporary, write_report)
            return
        write_report()
        if preview_source is not None:
            def verify_preview():
                preview_source.check_evidence()
                preview_source.guard()

            with hold_read_sources((preview_source.path,)):
                replace_file(temporary, directory / 'report.json', before_replace=verify_preview)
            return
        if points_workflow is None:
            replace_file(temporary, directory / 'report.json')
            return

        def check_publication_week():
            if not points_workflow.expire_points_at_publication():
                return
            if self.report.status == 'success':
                self.report.status = 'partial'
            if self.report.status == 'partial':
                self.report.failure_task = 'differential_universe'
            for result in self.report.results:
                if result.task == 'differential_universe':
                    result.status = 'partial'
                    result.detail = points_workflow.report['last_message']
            write_report()

        replace_file(temporary, directory / 'report.json', before_replace=check_publication_week)

    def run(self) -> RunReport:
        from .currency_wars_overclock import OPERATION as OVERCLOCK_CONFIGURE
        from .currency_wars_overclock_session import FLOW_OPERATION, PREP_OPERATION, START_OPERATION, OverclockSession
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
        points_workflow = None
        challenge_reader = None
        overclock_session = None
        overclock_preparation = None
        monitor = None
        monitor_started = False
        defer_battle_budget = False
        build_target_read = self.report.operation == 'build_target_read'
        build_target_plan = self.report.operation == 'build_target_plan'
        build_target_preview = self.report.operation == 'build_target_preview' or build_target_plan
        build_target = build_target_read or build_target_preview
        challenge_result = self.report.operation == 'challenge_result'
        challenge_lobby = self.report.operation == 'challenge_lobby'
        team_calibration = self.report.operation == 'team_preset_calibration'
        challenge_navigation = challenge_lobby or team_calibration
        guard_publication = self._foreground_only or build_target_preview
        build_target_safe_next = ('请核对当前培养目标或打开同一材料的获得途径。'
                                  if build_target_preview else '请在当前账号的生存索引核对培养目标页。材料详情与副本来源待校准。')
        if build_target or challenge_result or challenge_navigation:
            self.report.failure_task = self.report.operation
        try:
            if challenge_result:
                from .challenge_result import SAFE_NEXT
                self.report.safe_next = SAFE_NEXT
            elif challenge_lobby:
                from .challenge_lobby import SAFE_NEXT
                self.report.safe_next = SAFE_NEXT
            elif team_calibration:
                from .team_preset_calibration import SAFE_NEXT, initial_record
                self.report.safe_next = SAFE_NEXT
                self.report.team_preset_calibration = initial_record()
            if not mutex or already_running:
                raise AutomationError("另一个 AutoHSR 任务正在运行，请先停止后重试。")
            from .workflow_lease import require_workflow_access
            require_workflow_access()
            currency_wars = self.report.operation in ("currency_wars", "currency_wars_prepare", "currency_wars_standard", "currency_wars_points", "currency_wars_rewards", OVERCLOCK_CONFIGURE, START_OPERATION, PREP_OPERATION, "currency_wars_drag_test", "currency_wars_deploy_test", "currency_wars_node_test", FLOW_OPERATION)
            differential_universe = self.report.operation == "differential_universe"
            catalogue = self.report.operation == "dungeon_catalogue"
            guide_only = catalogue or build_target or challenge_result or challenge_navigation
            redemption = self.report.operation == 'redemption'
            challenge_prepare = self.report.operation == 'challenge_prepare'
            du_rewards = self.report.operation == 'du_rewards'
            if not (guide_only or currency_wars) and self.report.operation not in ("daily", "reward_only", "redemption", "challenge_prepare", "du_rewards", "differential_universe"):
                raise AutomationError("未知运行类型，未访问游戏。")
            self.settings.validate('build_target_preview' if build_target_preview else 'du_rewards' if du_rewards else 'challenge_prepare' if challenge_prepare else "check" if guide_only else "currency_wars" if currency_wars else "differential_universe" if differential_universe else 'redemption' if redemption else "power_plan" if self.use_power_plan else "daily")
            if challenge_prepare and self.settings.challenge_plan['mode'] != self._challenge_prepare_mode:
                raise SettingsError('challenge_plan', '高难计划模式已改变，请重新开始备战。')
            if self.report.operation != 'currency_wars' and not challenge_result:
                from .du_reward_store import preflight
                preflight(directory.parent)
                from .du_archive_store import preflight as archive_preflight
                archive_preflight(directory.parent)
            configured_name=''
            if self.report.operation in (START_OPERATION, FLOW_OPERATION, PREP_OPERATION):
                preparing = self.report.operation == PREP_OPERATION
                overclock_session = OverclockSession(directory, advancing=(
                    preparing or self.report.operation == FLOW_OPERATION and not self.currency_start_from_lobby),
                    preparing=preparing)
                if overclock_session.legacy_handoff and (self.weekly_plan is not None or self.new_battle_run):
                    raise AutomationError('超频 A0 首备战接续需要独立的推进当前对局入口。')
                if preparing or overclock_session.legacy_handoff:
                    from .currency_wars_overclock_preparation import PreparationJournal
                    overclock_preparation = PreparationJournal(overclock_session)
                    if overclock_session.legacy_handoff:
                        overclock_preparation.require_complete()
            if self.report.operation in ('currency_wars_points','currency_wars_rewards',OVERCLOCK_CONFIGURE):
                from .currency_wars_points_run import require_no_active_match
                from .currency_wars_session import StandardSession
                saved = StandardSession(directory.parent/'currency-standard-session.json').data
                if self.report.operation == OVERCLOCK_CONFIGURE:
                    require_no_active_match(saved, purpose='超频模式配置')
                else:
                    require_no_active_match(saved, defeat_root=directory.parent)
            if self.report.operation != 'currency_wars' and not challenge_result:
                from .currency_wars_weekly_reward_store import RewardStore
                rewards=RewardStore(directory.parent)
                saved_rewards=rewards.preflight(self.currency_rewards_resume if self.report.operation=='currency_wars_rewards' else False)
                from .currency_wars_weekly import native_gate
                self.currency_weekly_guard=native_gate(directory.parent,self.report.operation,self.currency_loop_guard,
                    self.currency_weekly_guard,standard_resume=self.currency_resume,rewards_resume=self.currency_rewards_resume)
                if (self.report.operation=='currency_wars_rewards' and self.currency_rewards_resume and saved_rewards
                        and saved_rewards['phase']=='returned' and saved_rewards['rewards_verified'] is True):
                    from copy import deepcopy
                    self.report.currency_wars=deepcopy(saved_rewards)
                    self.report.status='success';self.report.failure_task=''
                    self.report.safe_next='原领奖及返回证据完整；仅补存新审计报告与回执，未导航或重发领取。'
                    self.report.results.append(TaskResult('currency_wars','ok',self.report.safe_next))
                    return self.report
            if self.report.operation=='currency_wars_standard':
                from .currency_wars_names import resolve_name
                from .currency_wars_session import StandardSession,require_session_access
                from .currency_wars_equipment_mode import resolve_fast_mode
                saved=StandardSession(directory.parent/'currency-standard-session.json').data
                if self.currency_loop_guard is not None:
                    self.currency_loop_guard.require_access(saved,self.currency_resume)
                    self.currency_loop_guard.register_run(directory)
                else:
                    require_session_access(saved,self.currency_resume)
                configured_name=resolve_name(self.settings,self.currency_remembrance_name,saved,resume=self.currency_resume)
                resolve_fast_mode(self.settings,self.currency_fast_mode,saved,resume=self.currency_resume)
            if not guide_only and not currency_wars and not differential_universe and not redemption and not challenge_prepare and not du_rewards and self.settings.battle and self.settings.allow_stamina_spend:
                from .recovery import BattleBudget
                self.battle_budget = BattleBudget(ROOT / "runs", self.settings, self.report)
                from .workflow_identity import active as workflow_identity_active
                defer_battle_budget = workflow_identity_active()
                begin = self.battle_budget.preflight if defer_battle_budget else self.battle_budget.begin
                begin(new_run=self.new_battle_run,**(dict(protect_pending=True) if self.use_power_plan else {}))
            self.checkpoint()
            self._arm_hotkeys()
            monitor = threading.Thread(target=self._hotkeys, name="AutoHSR-hotkeys", daemon=True)
            monitor.start()
            monitor_started = True
            cold_start = False
            if not (challenge_result or challenge_navigation) and ((not guide_only and not currency_wars and not differential_universe and not challenge_prepare and not du_rewards) or self.weekly_plan is not None or self.report.operation in ('currency_wars_prepare', 'currency_wars_standard', 'currency_wars_points', 'currency_wars_rewards')):
                cold_start = self._prepare_daily_game() is True
            self._window = self._window or find_game(self.settings.game_path)
            if self.report.operation != "currency_wars" and is_elevated(self._window.hwnd) is True and not is_admin():
                raise AutomationError("游戏以管理员运行，请在设置启用管理员免重复确认启动后重开助手，或使用 Start-AutoHSR-Admin.cmd。")
            if self._foreground_only:
                self._window.guard()
            else:
                self._window.focus()
            if self.settings.overlay_logs and not self._foreground_only:
                from .overlay import OverlayService
                self._overlay = OverlayService()
                try:
                    self._overlay.start(self._window.hwnd)
                except Exception as error:
                    self.log(f'前台日志字幕启动失败，文件日志继续保留：{error}', 'warning')
            self.log("正在加载中文 OCR 模型。F9 暂停/继续，F10 紧急停止。")
            ocr_confidence = self.settings.ocr_confidence
            if team_calibration:
                from .team_preset_calibration import COLLECTION_FLOOR
                ocr_confidence = min(ocr_confidence, COLLECTION_FLOOR)
            vision = (IsolatedVision(ocr_confidence, checkpoint=self._control_checkpoint,
                                      inactive=lambda: self.inactive_duration,
                                      configured_name=configured_name,
                                      timeout=.05 if self.currency_timeout_probe else 30.) if currency_wars else
                      Vision(ocr_confidence))
            if self.assignments_only:
                from .currency_wars_identity import UID_VETO_FLOOR
                vision.uid_counterevidence_floor = UID_VETO_FLOOR
            context = Context(self, self._window, vision)
            context.overclock_session = overclock_session
            context.overclock_preparation = overclock_preparation
            context.battle_budget = self.battle_budget
            from .workflow_identity import prepare as prepare_workflow_identity
            daily_workflow = DailyWorkflow(context) if self.report.operation in ('daily', 'reward_only') else None
            if daily_workflow is not None:
                self.report.failure_task = 'startup'
            with context.daily_startup(daily_workflow, cold_start) if daily_workflow is not None else nullcontext():
                if not (build_target or self._foreground_only):
                    prepare_workflow_identity(context)
                if defer_battle_budget:
                    self.battle_budget.begin(new_run=self.new_battle_run,
                        **(dict(protect_pending=True) if self.use_power_plan else {}))
                initial = context.snapshot() if daily_workflow is not None else None
            if catalogue:
                from .dungeon_workflow import scan_catalogue
                result = scan_catalogue(DailyWorkflow(context))
                self.report.results.append(result)
                self.report.status = "success" if result.status == "ok" else "partial"
            elif build_target_read:
                from .build_target_read import BuildTargetRead
                self.emit(dict(type='task', task='build_target_read', status='running', detail='核对培养目标入口与到页反馈'))
                result = BuildTargetRead(context).run()
                self.report.results.append(result)
                self.report.status = 'success'
                self.report.failure_task = ''
                self.emit(dict(type='task', **result.__dict__))
            elif team_calibration:
                from .team_preset_calibration import TeamPresetCalibration
                self.emit(dict(type='task', task=self.report.operation, status='running',
                               detail='核对当前手机编队入口与到页证据'))
                team_reader = TeamPresetCalibration(context)
                result = team_reader.run()
                challenge_reader = team_reader
                self.report.results.append(result)
                self.report.status = 'success' if result.status == 'ok' else 'partial'
                self.report.failure_task = '' if result.status == 'ok' else self.report.operation
            elif build_target_preview:
                from .build_target_preview import run_preview
                self.emit(dict(type='task', task=self.report.operation, status='running', detail='观察材料与副本候选'))
                result = run_preview(context, selection=self.build_target_selection)
                self.report.results.append(result)
                self.report.status = 'partial'
                self.report.safe_next = build_target_safe_next
                if not build_target_plan:
                    self.emit(dict(type='task', **result.__dict__))
            elif du_rewards:
                from .du_rewards_only import run_rewards
                self.report.failure_task = 'du_rewards'
                detail = ('核对差分周期积分和已有奖励' if self.du_periodic_rewards
                          else '核对并领取已有差分红点奖励；不开始演算')
                self.emit(dict(type='task', task='du_rewards', status='running', detail=detail))
                result = run_rewards(context, use_cassettes=self.du_use_cassettes,
                                     **(dict(periodic_only=True) if self.du_periodic_rewards else {}))
                self.report.results.append(result)
                self.report.status = 'success' if result.status == 'ok' else 'partial'
                self.report.failure_task = '' if result.status == 'ok' else 'du_rewards'
                self.emit(dict(type='task', **result.__dict__))
            elif challenge_prepare:
                from .challenge_prepare import prepare_challenge
                self.report.failure_task = 'challenge_prepare'
                self.emit(dict(type='task', task='challenge_prepare', status='running', detail='核实当前高难模式与首个目标层备战'))
                result = prepare_challenge(context)
                preparation = getattr(context, 'challenge_preparation', None)
                if getattr(preparation, 'publication_receipt', None) is not None:
                    challenge_reader = preparation
                    guard_publication = True
                self.report.results.append(result)
                self.report.status = 'success' if result.status == 'ok' else 'partial'
                self.report.failure_task = '' if result.status == 'ok' else 'challenge_prepare'
                if challenge_reader is None:
                    self.emit(dict(type='task', **result.__dict__))
            elif challenge_lobby:
                from .challenge_lobby import ChallengeLobbyNavigation
                challenge_reader = ChallengeLobbyNavigation(context, self.challenge_lobby_mode)
                result = challenge_reader.run()
                self.report.results.append(result)
                self.report.status = 'success'
                self.report.failure_task = ''
                self.emit(dict(type='task', **result.__dict__))
            elif challenge_result:
                from .challenge_result import ResultReader
                self.emit(dict(type='task', task='challenge_result', status='running', detail='只读核对当前高难结算反馈'))
                challenge_reader = ResultReader(context)
                result = challenge_reader.run()
                self.report.results.append(result)
                self.report.status = 'partial'
                self.emit(dict(type='task', **result.__dict__))
            elif redemption:
                from .redemption_run import run_redemption
                self.report.failure_task = 'redemption'
                self.emit(dict(type='task', task='redemption', status='running', detail='核对并处理兑换码批次'))
                result = run_redemption(context)
                self.report.results.append(result)
                self.report.status = 'success' if result.status == 'ok' else 'partial'
                self.report.failure_task = '' if result.status == 'ok' else 'redemption'
                self.emit(dict(type='task', **result.__dict__))
            elif currency_wars:
                self._inspect_currency_wars(context)
            elif differential_universe:
                from .differential_universe import DifferentialUniverseWorkflow
                # A universe may already have begun; never replay the whole run
                # after an interrupted input or pause. Preserve evidence and stop.
                if self.weekly_plan is None or self.weekly_plan.prepare(context):
                    du_workflow = DifferentialUniverseWorkflow(context, self.du_runs,
                        resume_active=self.du_resume_active, periodic_rank=self.du_periodic_rank,
                        **({'until_points': True} if self.du_until_points else {}))
                    if self.du_until_points:
                        points_workflow = du_workflow
                    result = du_workflow.run()
                elif self.weekly_plan.already_exhausted:
                    result = TaskResult("weekly", "partial", "本周原开局上限已用完，周期积分仍未满。")
                else:
                    result = TaskResult("weekly", "ok", "本周演算已完成，已跳过。")
                self.report.results.append(result)
                self.report.status = "success" if result.status == "ok" else "partial"
                self.report.failure_task = "" if result.status == "ok" else "differential_universe"
                self.emit(dict(type="task", **result.__dict__))
            else:
                workflow = daily_workflow
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
                ready_planar = (not self.use_power_plan and self.settings.dungeon_category == "planar" and self.settings.battle
                                and not self.settings.assignments and workflow._calyx_target(initial)
                                and workflow._team_page(initial))
                if not ready_planar and not self.assignments_only:
                    with context.daily_startup(workflow, cold_start):
                        workflow.ensure_main()
                self.report.failure_task = ""
                self._run_tasks(context, workflow)
            self.log("任务已结束；请查看报告中的验证状态与证据。")
        except KeyboardInterrupt:
            if build_target_plan:
                self.stop()
                self.report.status = 'stopped'
                self.report.error = '培养草稿已停止。'
                self.report.safe_next = build_target_safe_next
            raise
        except Stopped as error:
            self.stop()
            self.report.status = "stopped"
            self.report.error = str(error)
            self.report.safe_next = ("货币战争操作已停止；核对画面和本次动作记录后重新识别。" if self.report.operation.startswith("currency_wars") else
                                     build_target_safe_next if build_target else
                                     self.report.safe_next if challenge_result or challenge_navigation else
                                     '独立委托已停止。请查看本次截图及当前领取状态。' if self.assignments_only else
                                     '差分领奖已停止；保留原意图及已核实领取，不重放未知动作；本次未开始演算。' if self.report.operation == 'du_rewards' else
                                     '高难备战已停止；保留层数选择记录，重新核对当前页面；本次未开战。' if self.report.operation == 'challenge_prepare' else
                                     '兑换已停止；已核实逐码结果保留，先核对未知提交，不重复确认。' if self.report.operation == 'redemption' else
                                     "差分宇宙自动演算已停止；核对本次截图、OCR 与动作记录。不要继续现有未完成存档。" if self.report.operation == "differential_universe" else
                                     "停止请求已生效；核对当前战斗及消耗后，可选择仅补领奖。")
            self.log(str(error), "warning")
        except Exception as error:
            target_input = build_target_read and self.report.build_target.get('entry_input') in ('unconfirmed', 'sent')
            team_input = (team_calibration and
                          self.report.team_preset_calibration.get('input_status') in ('unconfirmed', 'sent'))
            mode_pending = ((self.report.operation in (OVERCLOCK_CONFIGURE, PREP_OPERATION)
                             or self.report.currency_wars.get('mode') == 'overclock_a0_start')
                            and self.report.currency_wars.get('actions'))
            self.report.status = "partial" if (self.report.daily_verified or self.report.redemption.get('results')
                or self.report.challenge.get('actions') or self.report.du_rewards.get('actions')
                or target_input or team_input or mode_pending) else "failed"
            self.report.error = str(error)
            self.report.safe_next = ("积分领奖未完成；保留原报告和领奖记录，未知领取不重发；仅已核实步骤可明确接续。" if self.report.operation=='currency_wars_rewards' else
                                     build_target_safe_next if build_target else
                                     self.report.safe_next if challenge_result or challenge_navigation else
                                     '差分领奖未完整核实；保留原意图和已核实领取，未知动作不重放；本次未开始演算。' if self.report.operation == 'du_rewards' else
                                     '高难备战未完整核实；查看原层数选择和页面证据，不自动重发；本次未开战。' if self.report.operation == 'challenge_prepare' else
                                     '兑换批次未完成；先核对逐码结果和未知提交，已保存成功不重试。' if self.report.operation == 'redemption' else
                                     "货币战争操作失败；核对动作记录与前后截图，不自动重放。" if self.report.operation.startswith("currency_wars") else
                                     "差分宇宙自动演算失败；核对当前页面、动作记录与截图后再决定如何处理存档。" if self.report.operation == "differential_universe" else
                                     "请人工核对当前界面和消耗；返回主界面后仅补领奖，新增刷本预算需明确确认。")
            if isinstance(error, SettingsError):
                self.report.input_error_field = error.field
                self.report.safe_next = "请修改对应设置，再次开始。"
            elif self.report.failure_task == 'startup':
                self.report.safe_next = "请手动进入游戏主界面后重试当前任务。"
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
            if not guard_publication:
                self._monitor_end.set()
                if monitor_started:
                    monitor.join(timeout=1)
            self.report.finished_at = datetime.now().astimezone().isoformat()
            if self.battle_budget:
                try:
                    self.battle_budget.finish()
                except (OSError, AutomationError) as error:
                    self.report.status = "partial"
                    self.report.error = f"刷本记录保存失败：{error}"
                    self.report.safe_next = "保留现有记录，人工核对消耗；不要直接开始新一轮刷本。"
            if mutex and not guard_publication and self.report.operation not in ('currency_wars_points','currency_wars_rewards'):
                kernel32.CloseHandle(mutex)
            try:
                if build_target_plan:
                    from .build_target_draft import publish_report
                    publish_report(self, directory, context)
                elif build_target_preview:
                    from .build_target_draft import publish_preview_report
                    publish_preview_report(self, directory, context)
                elif challenge_reader is None:
                    self.report.report_saved = True
                    self._save_run_report(directory, points_workflow)
                else:
                    self.report.report_saved = True
                    self._save_run_report(directory, challenge_reader=challenge_reader)
            except OSError as error:
                self.report.report_saved = False
                self.report.report_write_error = str(error)
                attempted_team_entry = (team_calibration and
                    self.report.team_preset_calibration.get('input_status') in ('unconfirmed', 'sent'))
                self.report.status = "partial" if self.report.daily_verified or attempted_team_entry else "failed"
                self.report.error = (self.report.error + "；" if self.report.error else "") + f"报告保存失败：{error}"
                self.report.safe_next = ("报告未保存；保留动作记录和截图，人工核对后重新识别。" if self.report.operation.startswith("currency_wars") else
                                         build_target_safe_next if build_target else
                                         self.report.safe_next if challenge_result or challenge_navigation else
                                         '高难备战报告未保存；保留原选择与页面证据，核对当前层数；本次未开战。' if self.report.operation == 'challenge_prepare' else
                                         "差分宇宙报告保存失败；保留当前目录，人工核对当前存档和动作。" if self.report.operation == "differential_universe" else
                                         "报告未保存；保留当前证据与刷本记录，人工核对消耗，不要直接重跑刷本。")
                self.log(f"报告保存失败：{error}", "error")
            finally:
                if guard_publication:
                    self._monitor_end.set()
                    if monitor_started:
                        monitor.join(timeout=1)
                    if mutex:
                        kernel32.CloseHandle(mutex)
            if self.report.operation in ('currency_wars_points','currency_wars_rewards'):
                try:
                    if self.report.report_saved and self.report.status=='success':
                        if self.report.operation=='currency_wars_points':
                            from .currency_wars_points_run import finalize
                        else:
                            from .currency_wars_weekly_reward_run import finalize
                        finalize(self.report)
                except Exception as error:
                    self.report.status='partial'
                    self.report.error='积分观察／领奖回执保存或核验失败：'+str(error)
                    self.report.safe_next=('保留原报告和积分截图，重新核对；本次未开始对局或领取积分奖励。'
                        if self.report.operation=='currency_wars_points' else '原领奖记录和失败报告保留；明确接续只读核验并补存回执，不重发领取。')
                    self.log(self.report.error,'error')
                    try:
                        temporary=directory/'report.tmp'
                        temporary.write_text(json.dumps(self.report.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
                        replace_file(temporary,directory/'report.json')
                    except OSError as report_error:
                        self.report.report_saved=False;self.report.report_write_error=str(report_error)
                finally:
                    if mutex:kernel32.CloseHandle(mutex)
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
                        self._save_run_report(directory, points_workflow)
                    except OSError:
                        pass
            self._logger.removeHandler(handler)
            handler.close()
            self.emit(dict(type="finished", report=self.report.to_dict()))
        return self.report
