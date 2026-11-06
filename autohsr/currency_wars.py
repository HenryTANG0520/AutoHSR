"""Read-only calibration workflow; no unobserved gameplay rules or inputs."""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, replace

from .models import AutomationError, InputInterrupted, Scene, TaskResult, normalize
from .currency_wars_pages import PAGE_LABELS, classify_page

TASK = "currency_wars"
BLOCKER = "已采集完整教程并核实攻略、经济、部署及单节点战斗；完整对局仍待验证，自动玩法未开放。"
SAFE_NEXT = "继续验证部署、战斗与结算，并补齐决策和动作反馈；不重放结果不明的交易。"
REVIEW_ITEMS = (
    ("guide", "攻略参考与所选攻略"),
    ("tutorial", "UI 引导、问号及其他教程"),
    ("economy", "随机候选、资源类型与存钱机制"),
    ("transitions", "单步反馈、超时、恢复与终局"),
)


@dataclass(frozen=True)
class Observation:
    mode_text_visible: bool
    matching_tokens: tuple[dict, ...]
    page_kind: str = "unknown"
    page_verified: bool = False
    rules_verified: bool = False
    gameplay_enabled: bool = False
    completion_verified: bool = False


@dataclass(frozen=True)
class Decision:
    action: str = "stop_without_input"
    reason: str = "unknown_page"


def decide(observation: Observation) -> Decision:
    if observation.page_kind == "world_entry":
        return Decision(reason="entry_not_open")
    return Decision(reason="rules_unverified" if observation.page_verified or observation.mode_text_visible else "unknown_page")


def observe(scene: Scene, confidence: float) -> Observation:
    """Recognize calibrated UI from multiple anchors; never infer rules or completion."""
    matches = []
    trusted = []
    for token in scene.tokens:
        if (not math.isfinite(token.score) or not confidence <= token.score <= 1
                or len(token.box) != 4 or not all(math.isfinite(x) and 0 <= x <= 1 for x in token.box)
                or token.box[0] >= token.box[2] or token.box[1] >= token.box[3]):
            continue
        trusted.append(token)
        if normalize(token.text) == normalize("货币战争"):
            matches.append(dict(text=token.text, confidence=token.score, box=list(token.box)))
    kind = classify_page(trusted)
    return Observation(bool(matches), tuple(matches), page_kind=kind,
                       page_verified=kind not in ("unknown", "world_entry"))


class CurrencyWarsWorkflow:
    def __init__(self, context):
        self.c = context

    def _require_current_scene(self, scene, *, handoff_observation=False):
        if self.c.scene_epoch != self.c.runner.input_epoch or self.c.last_scene is not scene:
            raise InputInterrupted("暂停后重新采集货币战争画面，不沿用旧证据。")
        if not math.isfinite(scene.captured_at) or not 0 <= time.monotonic() - scene.captured_at <= 8:
            raise AutomationError("货币战争画面已过期，请重新只读识别。")
        session = getattr(self.c, 'overclock_session', None)
        if session is not None and self.c.report.operation == 'currency_wars_flow_test':
            if getattr(session, 'legacy_handoff', False) and not handoff_observation:
                raise AutomationError('超频 A0 首备战接续仅可观察当前节点。')
            from .currency_wars_overclock import require_legacy_frame
            require_legacy_frame(self.c, scene)

    def inspect(self) -> TaskResult:
        self.c.checkpoint()
        started = time.monotonic()
        inactive_before = self.c.runner.inactive_duration
        scene = self.c.snapshot()
        self.c.checkpoint()
        active_elapsed = time.monotonic() - started - (self.c.runner.inactive_duration - inactive_before)
        if active_elapsed > 30:
            raise AutomationError("货币战争只读识别超过 30 秒，未发送游戏输入。")
        self._require_current_scene(scene)
        confidence = self.c.settings.ocr_confidence
        observation = observe(scene, confidence)
        from .currency_wars_points import read_points_observation
        from .currency_wars_settlement_observation import read_settlement
        settlement = read_settlement(scene, confidence)
        progress = read_points_observation(scene, confidence)
        if settlement is not None:
            observation = replace(observation, page_kind=settlement.page, page_verified=True)
        elif progress is not None:
            observation = replace(observation, page_kind=progress.page, page_verified=True)
        encounter = None
        if observation.page_kind == 'unknown':
            from .currency_wars_encounter import read_encounter
            encounter = read_encounter(scene, self.c.settings.ocr_confidence, include_experience=True)
            if encounter is not None and encounter.layout_verified:
                observation = replace(observation, page_kind='encounter_selection', page_verified=True)
        screenshot = self.c.evidence(scene, "currency_wars_observation")
        self.c.checkpoint()
        self._require_current_scene(scene)
        from .currency_wars_replay import save_sample
        sample = save_sample(scene, screenshot)
        self.c.checkpoint()
        self._require_current_scene(scene)
        decision = decide(observation)
        data = dict(
            mode="read_only_calibration", **asdict(observation), screenshot=str(screenshot),
            review=[dict(id=key, label=label, status="partial" if key == "transitions" else "reference_recorded")
                    for key, label in REVIEW_ITEMS],
            reference_version="CNPRODWin4.6.0_D16781997_A16781679_L16781679",
            reference_rules=dict(tutorial_pages=79, standard_interest_step=10,
                                 standard_interest_cap=5, overclock_interest=0),
            blocker=BLOCKER, decision=decision.action, decision_reason=decision.reason, sample=str(sample),
        )
        if settlement is not None:
            data['settlement_observation'] = asdict(settlement)
        if progress is not None:
            data['points_progress'] = asdict(progress)
        from .currency_wars_overclock import read_overclock
        mode = read_overclock(scene, self.c.settings.ocr_confidence)
        if mode.state != 'other_page':
            data['overclock_configuration'] = asdict(mode)
        if observation.page_kind == 'investment_selection':
            from .currency_wars_investment_policy import badge_declarations
            data['investment_badge_declarations'] = badge_declarations(scene, self.c.settings.ocr_confidence)
        if encounter is not None:
            data['encounter'] = asdict(encounter)
        if observation.page_kind == 'supply_selection':
            from .currency_wars_supply_observation import read_double_supply
            supply = read_double_supply(scene, self.c.settings.ocr_confidence)
            if supply is not None:
                data['double_supply'] = supply
        from .currency_wars_match import read_match
        match = read_match(scene, self.c.settings.ocr_confidence)
        data["match"] = asdict(match) if match is not None else None
        if match is not None and match.page in ('preparation', 'shop'):
            from .currency_wars_investment_badges import read_grail_gold_receipt
            badge_gold = read_grail_gold_receipt(scene, self.c.settings.ocr_confidence)
            if badge_gold is not None:
                data['investment_badge_gold_receipt'] = badge_gold
        # Same state model used by offline/API advisers. Read-only inspection
        # deliberately remains offline even if an API was configured elsewhere.
        from .currency_wars_state import snapshot_from_scene
        from .currency_wars_planner import OfflineProvider, candidates
        strategy_state = snapshot_from_scene(scene, self.c.runner.input_epoch,
                                             self.c.settings.ocr_confidence, str(screenshot))
        data['strategy_snapshot'] = asdict(strategy_state)
        data['strategy_candidates'] = [asdict(choice) for choice in candidates(strategy_state)]
        data['strategy_decision'] = asdict(OfflineProvider().decide(strategy_state))
        self.c.report.currency_wars = data
        self.c.report.error = BLOCKER
        self.c.report.safe_next = SAFE_NEXT
        self.c.runner.emit(dict(type="currency_wars", data=data))
        detail = ("已识别朝露公馆的货币战争交互入口，尚未打开玩法。" if observation.page_kind == "world_entry" else
                  f"已识别{PAGE_LABELS[observation.page_kind]}，自动玩法及整局完成状态尚未验证。" if observation.page_verified else
                  "已记录遭遇节点候选，双卡布局待核实。" if encounter is not None else
                  "已保存“货币战争”候选文字，页面尚未核实。" if observation.mode_text_visible
                  else "未识别到可信的“货币战争”完整文字，未推测当前页面。")
        self.c.log(detail + BLOCKER, "warning")
        return TaskResult(TASK, "partial", detail + BLOCKER)
