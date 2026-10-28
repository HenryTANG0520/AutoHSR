"""Weekly eligibility and evidence-backed, per-account run receipts.

Scheduling follows March7thAssistant's separation of a full run and its optional
timer. This module never starts a timer: an explicit plan start checks eligibility.
The supported target is a fixed number of DU runs, not weekly score rewards.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re

from .models import AutomationError
from .storage import replace_file

CHINA = timezone(timedelta(hours=8))
DAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
MODES = {"differential_universe": "差分宇宙", "currency_wars": "货币战争"}


def validate_schedule(settings):
    from .config import SettingsError
    if type(settings.weekly_enabled) is not bool:
        raise SettingsError("weekly_enabled", "加入周常必须为布尔值。")
    if not isinstance(settings.weekly_mode, str) or settings.weekly_mode not in MODES:
        raise SettingsError("weekly_mode", "周常玩法请选择差分宇宙或货币战争。")
    if type(settings.weekly_day) is not int or not 1 <= settings.weekly_day <= 7:
        raise SettingsError("weekly_day", "周常星期必须为 1～7。")
    if not isinstance(settings.weekly_time, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", settings.weekly_time):
        raise SettingsError("weekly_time", "周常时间请填写 HH:MM，例如 04:00（北京时间）。")
    if type(settings.weekly_runs) is not int or not 1 <= settings.weekly_runs <= 10:
        raise SettingsError("weekly_runs", "周常演算局数应为 1～10。")


@dataclass(frozen=True)
class WeeklySlot:
    week: str
    due_at: datetime
    due: bool


def weekly_slot(settings, now=None):
    validate_schedule(settings)
    now = now or datetime.now(CHINA)
    if now.tzinfo is None:
        raise ValueError("周常时间需要时区。")
    now = now.astimezone(CHINA)
    game_date = (now-timedelta(hours=4)).date()
    monday = game_date-timedelta(days=game_date.weekday())
    reset = datetime.combine(monday, datetime.min.time(), CHINA)+timedelta(hours=4)
    hour, minute = map(int, settings.weekly_time.split(":"))
    due = reset.replace(hour=hour, minute=minute)+timedelta(days=settings.weekly_day-1)
    # Monday before 04:00 belongs to the ending game week.
    if due < reset:
        due += timedelta(days=7)
    return WeeklySlot(monday.isoformat(), due, now >= due)


def plan_caption(settings, now=None):
    if not settings.weekly_enabled:
        return "周常未加入"
    slot = weekly_slot(settings, now)
    target = MODES[settings.weekly_mode]
    if settings.weekly_mode == "differential_universe":
        target += f" · {settings.weekly_runs} 局"
    else:
        target += " · 待接入"
    when = "到期，运行时核对" if slot.due else f"{DAYS[settings.weekly_day-1]} {settings.weekly_time} 后"
    return f"{target} · {when}"


def verified_du_report(report, requested):
    data = report.get("differential_universe") or {}
    runs = data.get("run_results") or []
    return (type(requested) is int and 1 <= requested <= 10
            and report.get("operation") == "differential_universe"
            and report.get("status") == "success" and report.get("report_saved") is True
            and data.get("mode") == "周期演算" and data.get("requested_runs") == requested
            and data.get("completed_runs") == requested and len(runs) == requested
            and all(r.get("status") == "completed" and r.get("counted") is True
                    and r.get("difficulty_verified") is True and r.get("started_evidence")
                    and r.get("victory_evidence") and r.get("return_evidence") for r in runs))


def evidence_hashes(report):
    directory = Path(report["run_dir"]).resolve()
    hashes = {}
    for run in report["differential_universe"]["run_results"]:
        for field in ("started_evidence", "victory_evidence", "return_evidence"):
            path = Path(run[field]).resolve()
            if not path.is_relative_to(directory):
                raise ValueError("演算证据不在原始运行目录中。")
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


class WeeklyReceipt:
    """Unknown intent blocks later weeks too; completion requires the saved report."""

    def __init__(self, root, account, slot):
        if not re.fullmatch(r"[a-f0-9]{24}", account):
            raise ValueError("无效的本地账号标识。")
        self.root = Path(root).resolve()
        self.folder = self.root/"weekly-plan"/account
        self.path = self.folder/(slot.week+".json")
        self.slot = slot
        self.data = None

    def _report(self, data):
        path = Path(data["report"]).resolve()
        if not path.is_relative_to(self.root) or path.name != "report.json":
            raise ValueError("报告不在运行目录中。")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != data["report_sha256"]:
            raise ValueError("原报告已变化。")
        report = json.loads(raw)
        if data["evidence"] != evidence_hashes(report):
            raise ValueError("原始演算证据已变化。")
        return report

    def begin(self, settings):
        self.folder.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.folder.glob("*.json")):
            try:
                data = json.loads(path.read_text("utf-8"))
                if (data.get("version") != 1 or data.get("week") != path.stem
                        or data.get("state") != "complete"
                        or not verified_du_report(self._report(data), data["requested_runs"])):
                    raise ValueError("完成证据不完整。")
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                raise AutomationError("有周常记录待核对；保留原报告，未再开局。") from exc
        if self.path.exists():
            return False
        self.data = dict(version=1, week=self.slot.week, state="started",
                         mode=settings.weekly_mode, requested_runs=settings.weekly_runs,
                         due_at=self.slot.due_at.isoformat(), started_at=datetime.now(CHINA).isoformat())
        # Write intent before the workflow can enter a game. No replacement on retry.
        with self.path.open("x", encoding="utf-8") as stream:
            json.dump(self.data, stream, ensure_ascii=False, indent=2)
        return True

    def complete(self, report):
        if self.data is None or not verified_du_report(report, self.data["requested_runs"]):
            raise AutomationError("周常演算完成证据不足；本周记录仍待核对。")
        report_path = (Path(report["run_dir"])/"report.json").resolve()
        raw = report_path.read_bytes()
        persisted = json.loads(raw)
        if (not report_path.is_relative_to(self.root)
                or persisted != json.loads(json.dumps(report))
                or not verified_du_report(persisted, self.data["requested_runs"])):
            raise AutomationError("周常原始报告未完整保存；本周记录仍待核对。")
        data = dict(self.data, state="complete", report=str(report_path),
                    report_sha256=hashlib.sha256(raw).hexdigest(), evidence=evidence_hashes(persisted),
                    finished_at=datetime.now(CHINA).isoformat())
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(temp, self.path)
        self.data = data


class WeeklyGuard:
    """Called inside the ordinary DU Runner's input lock, before any new run."""

    def __init__(self, root, settings, slot):
        self.root, self.settings, self.slot = root, settings, slot
        self.receipt = None
        self.already_complete = False

    def prepare(self, context):
        from .du_daily import account_key
        from .workflows import DailyWorkflow
        DailyWorkflow(context).ensure_main()
        context.checkpoint()
        scene = context.snapshot()
        try:
            account = account_key(scene)
        except AutomationError as exc:
            raise AutomationError("周常未核实当前账号；未开始演算。") from exc
        self.receipt = WeeklyReceipt(self.root, account, self.slot)
        self.already_complete = not self.receipt.begin(self.settings)
        return not self.already_complete

    def complete(self, report):
        if self.already_complete:
            return
        if self.receipt is None:
            raise AutomationError("周常尚未核实账号与执行记录。")
        self.receipt.complete(report)
