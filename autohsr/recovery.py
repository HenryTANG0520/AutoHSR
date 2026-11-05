"""Durable, per-run battle intent. This never resumes or starts a game itself."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .models import AutomationError
from .storage import replace_file


def reward_only_settings(settings):
    return replace(settings, assignments=False, battle=False, daily=True, mail=False, battlepass=False,
                   daily_synthesis=False)


def _historical_battle(data, path):
    if not isinstance(data, dict):
        raise ValueError("invalid historical report")
    operation = data.get("operation", "daily")
    summary = operation in ("plan", "task_workflow")
    if operation != "daily" and not summary:
        return None
    spent = data.get("stamina_spent", 0)
    tokens_spent = data.get("immersifiers_spent", 0)
    if (type(spent) is not int or spent < 0
            or type(tokens_spent) is not int or not 0 <= tokens_spent <= 12):
        raise ValueError("invalid historical resource counts")
    pending = data.get("stamina_pending")
    pending = pending if type(pending) is int and pending >= 0 else None
    # Both fields were introduced together. Keep an explicit positive pending
    # amount from a partial report, but one zero cannot prove both counts.
    tokens_pending = data.get("immersifiers_pending", 0)
    tokens_pending = tokens_pending if type(tokens_pending) is int and 0 <= tokens_pending <= 12 else None
    if tokens_pending == 0 and ("immersifiers_spent" in data) != ("immersifiers_pending" in data):
        tokens_pending = None
    limit = data.get("stamina_limit", 0)
    allocated = operation == "daily" and type(limit) is int and limit > 0
    explicit_unknown = (pending is None and ("stamina_pending" in data or allocated)) or tokens_pending is None
    unsettled = explicit_unknown or bool(pending or tokens_pending)
    # Parent plans and workflows copy their child's totals. Keep any explicit
    # uncertainty if only a parent report survives, but never use its copied
    # settled totals to supersede a report from the run that actually paid.
    if not unsettled and (summary or not (spent or tokens_spent)):
        return None

    status = data.get("status")
    if status not in ("active", "success", "partial", "failed", "stopped"):
        raise ValueError("invalid historical report status")
    # Before the durable journal, successful reports recorded only confirmed
    # stamina. Modern or interrupted reports cannot use that exception.
    journal_fields = ("operation", "budget_scope", "stamina_limit", "stamina_pending",
                      "immersifiers_spent", "immersifiers_pending", "report_saved")
    if status == "success" and not any(field in data for field in journal_fields):
        pending = 0
    return dict(blocked=status != "success" or pending != 0 or tokens_pending != 0,
                corrupt=False, spent=spent, pending=pending, source=str(path), legacy=True, status=status,
                immersifiers_spent=tokens_spent, immersifiers_pending=tokens_pending)


def recovery_state(runs: Path, *, direct_report: bool = False) -> dict:
    """Read the canonical journal or reports in the caller's budget scope.

    A DU batch owns a direct daily report. The ordinary runs root owns reports
    in its child run directories. A present journal takes precedence.
    """
    path = runs / "battle-session.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or data.get("version") != 1
                    or type(data.get("spent")) is not int or data["spent"] < 0
                    or type(data.get("pending")) is not int or data["pending"] < 0
                    or type(data.get("limit")) is not int or not 10 <= data["limit"] <= 240
                    or data["spent"] + data["pending"] > data["limit"]
                    or (("immersifiers_spent" in data) != ("immersifiers_pending" in data))
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
    # A later successful report cannot resolve a different run's payment.
    # Retain the latest settled candidate while looking for older uncertainty.
    if direct_report:
        direct = runs / "report.json"
        reports = (direct,) if direct.exists() else ()
    else:
        reports = sorted(runs.glob("*/report.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest_settled = None
    for report in reports:
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            if direct_report and (not isinstance(data, dict) or data.get("operation") != "daily"):
                raise ValueError("invalid direct battle report")
            state = _historical_battle(data, report)
            if state is not None:
                if direct_report or new_budget_block_reason(state) is not None:
                    return state
                if latest_settled is None:
                    latest_settled = state
        except (OSError, ValueError, TypeError, AttributeError):
            return dict(blocked=True, corrupt=True, spent=0, pending=0, source=str(report),
                        reason="历史运行报告无法读取，消耗情况未核实；请先保留记录并人工核对。")
    return latest_settled or dict(blocked=False, corrupt=False, spent=0, pending=0, source="")


def new_budget_block_reason(state) -> str | None:
    """Return the blocking reason for a state read by ``recovery_state``."""
    if state["corrupt"]:
        return state["reason"]
    if state["pending"] != 0 or state.get("immersifiers_pending", 0) != 0:
        return "上次刷本支付仍待核对；未开启新一轮刷本。可先仅补领奖，并保留原账单人工核对。"
    return None


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

    def preflight(self, *, new_run=False,protect_pending=False):
        """Check every budget, retaining the existing ``protect_pending`` keyword."""
        state = recovery_state(self.runs)
        reason = new_budget_block_reason(state)
        if reason is not None:
            raise AutomationError(reason)
        if state.get('power_plan'):
            from .power_plan_store import validate
            validate(self.runs,state,settled=True)
        if state["blocked"] and not new_run:
            pending = state['pending']
            from .ux import immersifier_text
            raise AutomationError(f"上次刷本未完整结束（已确认{state['spent']}，待核对{pending}开拓力{immersifier_text(state)}）。"
                                  "请先仅补领奖；开始新一轮刷本须明确确认新增预算。")
        return state

    def begin(self, *, new_run=False,protect_pending=False):
        state = self.preflight(new_run=new_run, protect_pending=protect_pending)
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

    def confirm(self, cost: int, *, immersifiers=0, completed: int | None = None):
        if (not self.active or type(cost) is not int or type(immersifiers) is not int
                or self.report.stamina_pending != cost or cost < 0
                or self.report.immersifiers_pending != immersifiers or cost + immersifiers <= 0):
            raise AutomationError("本次结算没有唯一待核对消耗，禁止重复记账。")
        report = self.report
        if completed is not None and (self.power_plan is not None or type(completed) is not int
                                      or completed <= report.battle_completed):
            raise AutomationError("本次结算完成次数与原记录不一致。")
        previous = (report.stamina_spent, report.stamina_pending, report.immersifiers_spent,
                    report.immersifiers_pending, report.battle_completed)
        plan = deepcopy(report.power_plan) if self.power_plan is not None else None
        try:
            if self.power_plan is not None:
                self.power_plan.confirm(cost, immersifiers)
            elif completed is not None:
                report.battle_completed = completed
            report.stamina_spent += cost
            report.stamina_pending = 0
            report.immersifiers_spent += immersifiers
            report.immersifiers_pending = 0
            self._write()
        except Exception:
            (report.stamina_spent, report.stamina_pending, report.immersifiers_spent,
             report.immersifiers_pending, report.battle_completed) = previous
            if plan is not None:
                report.power_plan.clear()
                report.power_plan.update(plan)
            raise
        if self.power_plan is not None:self.power_plan.publish('confirmed')

    def finish(self):
        if self.active:
            self._write(self.report.status)
