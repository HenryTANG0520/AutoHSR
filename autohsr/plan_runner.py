"""One explicit start, sequential ordinary Runners, one durable combined report."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import threading
import uuid

from .config import ROOT, SettingsError
from .models import RunReport, Stopped, TaskResult
from .storage import replace_file
from .weekly_plan import CHINA, WeeklyGuard, weekly_slot


class PlanRunner:
    def __init__(self, settings, emit=None, *, new_battle_run=False, runner_factory=None, root=None, now=None):
        from .app import Runner
        self.settings = replace(settings)
        self.settings.validate("plan")
        if not self.settings.weekly_enabled and not any(getattr(self.settings, name) for name in
                                                       ("assignments", "battle", "daily", "mail", "battlepass")):
            raise ValueError("请选择日常任务或加入周常。")
        self.emit = emit or (lambda event: None)
        self.factory = runner_factory or Runner
        self.root = Path(root) if root is not None else ROOT/"runs"
        self.slot = weekly_slot(self.settings, now)
        self.new_battle_run = new_battle_run
        self.child = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._paused = False
        self.report = RunReport(operation="plan")

    def stop(self):
        self._stop.set()
        with self._lock:
            if self.child is not None:
                self.child.stop()

    def toggle_pause(self):
        with self._lock:
            self._paused = self.child.toggle_pause() if self.child is not None else not self._paused
            return self._paused

    def _checkpoint(self):
        while True:
            if self._stop.is_set():
                raise Stopped("计划已停止；未继续下一项。")
            with self._lock:
                paused = self._paused
            if not paused:
                return
            self._stop.wait(.1)

    def _send(self, event, phase):
        if event.get("type") == "paused":
            with self._lock:
                self._paused = bool(event.get("paused"))
        if event.get("type") != "finished":
            self.emit(dict(event, phase=phase))

    def _run(self, settings, *, phase, **options):
        self._checkpoint()
        self.emit(dict(type="plan_phase", phase=phase))
        child = self.factory(settings, lambda event: self._send(event, phase), **options)
        with self._lock:
            self.child = child
            if self._stop.is_set():
                child.stop()
            if self._paused:
                child.toggle_pause()
        try:
            result = child.run()
            return result.to_dict() if hasattr(result, "to_dict") else result
        finally:
            with self._lock:
                self.child = None

    def _weekly_result(self, status, message):
        self.report.weekly_plan.update(status=status, message=message)
        result = TaskResult("weekly", "ok" if status in ("complete", "already_complete") else
                            "skipped" if status in ("disabled", "not_due") else "partial", message)
        self.report.results.append(result)
        self.emit(dict(type="task", **result.__dict__))

    def run(self):
        started = datetime.now(CHINA)
        directory = self.root/(started.strftime("%Y%m%d_%H%M%S_%f")+"_plan_"+uuid.uuid4().hex[:8])
        directory.mkdir(parents=True)
        report = self.report
        report.run_dir, report.started_at, report.source = str(directory), started.isoformat(), str(self.root.parent)
        report.weekly_plan = dict(week=self.slot.week, due_at=self.slot.due_at.isoformat(),
                                 mode=self.settings.weekly_mode, requested_runs=self.settings.weekly_runs,
                                 status="waiting", score_rewards_verified=False, children=[])
        try:
            self._checkpoint()
            daily_selected = any(getattr(self.settings, name) for name in ("assignments", "battle", "daily", "mail", "battlepass"))
            if daily_selected:
                daily = self._run(self.settings, phase="daily", operation="daily", new_battle_run=self.new_battle_run)
                report.weekly_plan["children"].append(dict(operation="daily", run_dir=daily.get("run_dir", "")))
                for name in ("stamina_spent", "stamina_limit", "stamina_pending", "immersifiers_spent",
                             "immersifiers_pending", "battle_completed", "battle_requested", "daily_verified",
                             "daily_synthesis", "engagement", "game_day", "error", "input_error_field", "safe_next", "failure_task"):
                    if name in daily:
                        setattr(report, name, daily[name])
                report.results.extend(TaskResult(r["task"], r["status"], r.get("detail", "")) for r in daily.get("results", []))
                self.emit(dict(type="plan_daily_result", report=daily))
                if daily.get("status") != "success" or daily.get("report_saved") is not True:
                    report.status = "stopped" if daily.get("status") == "stopped" else "partial"
                    self._weekly_result("not_started", "日常未完整结束；周常未开始。")
                    return report
            self._checkpoint()
            report.status = "success"
            if not self.settings.weekly_enabled:
                self._weekly_result("disabled", "周常未加入。")
            elif not self.slot.due:
                self._weekly_result("not_due", "周常未到计划时间。")
            elif self.settings.weekly_mode == "currency_wars":
                report.status = "partial"
                self._weekly_result("unavailable", "货币战争周积分奖励尚未接入；日常结果已保留。")
            else:
                self.emit(dict(type="task", task="weekly", status="running", detail="核对本周演算记录"))
                guard = WeeklyGuard(self.root, self.settings, self.slot)
                weekly_settings = replace(self.settings, assignments=False, battle=False, daily=False,
                                          mail=False, battlepass=False, differential_universe_mode="periodic",
                                          differential_universe_runs=self.settings.weekly_runs,
                                          differential_universe_daily=False, differential_universe_save=False,
                                          differential_universe_rewards=False)
                weekly = self._run(weekly_settings, phase="weekly", operation="differential_universe",
                                   du_runs=self.settings.weekly_runs, weekly_plan=guard)
                report.weekly_plan["children"].append(dict(operation="differential_universe", run_dir=weekly.get("run_dir", "")))
                report.differential_universe = weekly.get("differential_universe", {})
                if weekly.get("status") != "success":
                    report.status = "stopped" if weekly.get("status") == "stopped" else "partial"
                    report.error, report.safe_next = weekly.get("error", ""), weekly.get("safe_next", "")
                    report.input_error_field = weekly.get("input_error_field", "")
                    self._weekly_result("needs_review", "周常演算未完成；核对原报告后再处理。")
                else:
                    guard.complete(weekly)
                    self._weekly_result("already_complete" if guard.already_complete else "complete",
                                        "本周演算已完成，已跳过。" if guard.already_complete else
                                        f"本周 {self.settings.weekly_runs} 局周期演算已完成；周积分奖励未核实。")
        except Stopped as exc:
            report.status, report.error = "stopped", str(exc)
            self._weekly_result("not_started", "计划已停止；未继续下一项。")
        except Exception as exc:
            report.status, report.error = "partial" if report.results else "failed", str(exc)
            report.safe_next = "查看日常与周常各自的原始报告；未核实的开局不自动重放。"
            if isinstance(exc, SettingsError):
                report.input_error_field = exc.field
                report.safe_next = "请修改对应设置，再次开始。"
            self._weekly_result("needs_review", str(exc))
        finally:
            report.finished_at = datetime.now(CHINA).isoformat()
            try:
                report.report_saved = True
                temp = directory/"report.tmp"
                temp.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
                replace_file(temp, directory/"report.json")
            except OSError as exc:
                report.report_saved = False
                report.status = "partial"
                report.report_write_error = str(exc)
                report.error = (report.error+"；" if report.error else "")+"计划报告保存失败。"
            self.emit(dict(type="finished", report=report.to_dict()))
        return report
