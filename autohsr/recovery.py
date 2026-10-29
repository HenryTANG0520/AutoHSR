"""Durable, per-run battle intent. This never resumes or starts a game itself."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .models import AutomationError
from .storage import replace_file


def reward_only_settings(settings):
    return replace(settings, assignments=False, battle=False, daily=True, mail=False, battlepass=False,
                   daily_synthesis=False)


def recovery_state(runs: Path) -> dict:
    path = runs / "battle-session.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("version") != 1
                    or type(data.get("spent")) is not int or data["spent"] < 0
                    or type(data.get("pending")) is not int or data["pending"] < 0
                    or type(data.get("limit")) is not int or not 10 <= data["limit"] <= 240
                    or data["spent"] + data["pending"] > data["limit"]
                    or any(type(data.get(k, 0)) is not int or not 0 <= data.get(k, 0) <= 12
                           for k in ('immersifiers_spent', 'immersifiers_pending'))
                    or data.get('immersifiers_spent', 0) + data.get('immersifiers_pending', 0) > 12
                    or data.get("status") not in ("active", "success", "partial", "failed", "stopped")):
                raise ValueError("invalid battle journal")
            return {**data, "blocked": data["pending"] > 0 or data.get('immersifiers_pending', 0) > 0
                    or (data["status"] != "success" and (data["spent"] > 0 or data.get('immersifiers_spent', 0) > 0)),
                    "source": str(path), "corrupt": False}
        except (OSError, ValueError, TypeError):
            return dict(blocked=True, corrupt=True, spent=0, pending=0, source=str(path),
                        reason="刷本记录无法读取；先保留记录并人工核对，不得重建预算。")
    # Legacy interrupted runs predate the durable journal. Do not let a later
    # reward-only report hide the last resource-consuming run.
    reports = sorted(runs.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for report in reports:
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            spent = data.get("stamina_spent", 0)
            if type(spent) is not int or spent <= 0:
                continue
            pending = data.get("stamina_pending")
            pending = pending if type(pending) is int and pending >= 0 else None
            return dict(blocked=data.get("status") != "success" or bool(pending), corrupt=False, spent=spent,
                        pending=pending, source=str(report), legacy=True, status=data.get("status"))
        except (OSError, ValueError, TypeError, AttributeError):
            return dict(blocked=True, corrupt=True, spent=0, pending=0, source=str(report),
                        reason="历史运行报告无法读取，消耗情况未核实；请先保留记录并人工核对。")
    return dict(blocked=False, corrupt=False, spent=0, pending=0, source="")


class BattleBudget:
    def __init__(self, runs: Path, settings, report):
        self.runs, self.settings, self.report = Path(runs), settings, report
        self.path = self.runs / "battle-session.json"
        self.active = False
        self.limit=settings.stamina_limit
        self.power_plan=None

    def _write(self, status="active"):
        self.runs.mkdir(parents=True, exist_ok=True)
        data = dict(version=1, status=status, spent=self.report.stamina_spent,
                    pending=self.report.stamina_pending, limit=self.limit,
                    run_dir=self.report.run_dir, updated_at=datetime.now().astimezone().isoformat(),
                    target=self.settings.target_name, location=self.settings.target_location)
        data.update(category=self.settings.dungeon_category, requested=self.report.battle_requested,
                    completed=self.report.battle_completed,
                    immersifiers_spent=self.report.immersifiers_spent,
                    immersifiers_pending=self.report.immersifiers_pending)
        if getattr(self.report,'power_plan',None):
            from .power_plan_store import validate
            data['power_plan']=self.report.power_plan
            validate(self.runs,data)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(temp,self.path)

    def begin(self, *, new_run=False,protect_pending=False):
        state = recovery_state(self.runs)
        if state["corrupt"]:
            raise AutomationError(state["reason"])
        if protect_pending and (state.get('pending') or state.get('immersifiers_pending')):
            raise AutomationError('原支付仍待核对；新增预算不重置体力计划。')
        if state.get('power_plan'):
            from .power_plan_store import validate
            validate(self.runs,state,settled=True)
        if state["blocked"] and not new_run:
            pending = state['pending'] if state['pending'] is not None else '未记录'
            from .ux import immersifier_text
            raise AutomationError(f"上次刷本未完整结束（已确认{state['spent']}，待核对{pending}开拓力{immersifier_text(state)}）。"
                                  "请先仅补领奖；开始新一轮刷本须明确确认新增预算。")
        self.report.budget_scope = "run"
        if state.get('power_plan'):
            from .power_plan_store import archive
            archive(self.runs,{k:v for k,v in state.items() if k not in ('blocked','source','corrupt')})
        self.report.stamina_limit = self.settings.stamina_limit
        self._write()
        self.active = True

    def reserve(self, cost: int, *, immersifiers=0):
        if (not self.active or type(cost) is not int or cost < 0 or cost % 10
                or type(immersifiers) is not int or not 0 <= immersifiers <= 12
                or cost + immersifiers <= 0
                or (immersifiers and self.settings.dungeon_category != 'planar')
                or self.report.stamina_pending or self.report.immersifiers_pending
                or self.report.immersifiers_spent + immersifiers > 12
                or self.report.stamina_spent + cost > self.limit):
            raise AutomationError("挑战预算无法核实，禁止再次开始挑战。")
        if self.power_plan is not None:self.power_plan.reserve(cost,immersifiers)
        self.report.stamina_pending = cost
        self.report.immersifiers_pending = immersifiers
        # Must complete before any Start Challenge input; an I/O failure stops.
        self._write()

    def confirm(self, cost: int, *, immersifiers=0):
        if (not self.active or type(cost) is not int or type(immersifiers) is not int
                or self.report.stamina_pending != cost or cost < 0
                or self.report.immersifiers_pending != immersifiers or cost + immersifiers <= 0):
            raise AutomationError("本次结算没有唯一待核对消耗，禁止重复记账。")
        previous=None
        if self.power_plan is not None:
            from copy import deepcopy
            previous=(deepcopy(self.report.power_plan),self.report.stamina_spent,self.report.stamina_pending,
                self.report.immersifiers_spent,self.report.immersifiers_pending,self.report.battle_completed)
        try:
            if self.power_plan is not None:self.power_plan.confirm(cost,immersifiers)
            self.report.stamina_spent += cost
            self.report.stamina_pending = 0
            self.report.immersifiers_spent += immersifiers
            self.report.immersifiers_pending = 0
            self._write()
        except Exception:
            if previous is not None:
                plan,spent,pending,tokens,token_pending,completed=previous
                self.report.power_plan.clear();self.report.power_plan.update(plan)
                self.report.stamina_spent,self.report.stamina_pending=spent,pending
                self.report.immersifiers_spent,self.report.immersifiers_pending=tokens,token_pending
                self.report.battle_completed=completed
            raise
        if self.power_plan is not None:self.power_plan.publish('confirmed')

    def finish(self):
        if self.active:
            self._write(self.report.status)
