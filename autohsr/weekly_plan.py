"""Weekly eligibility and evidence-backed, per-account run receipts.

Scheduling follows March7thAssistant's separation of a full run and its optional
timer. This module never starts a timer: an explicit plan start checks eligibility.
DU receipts support fixed run counts and an explicit periodic points goal.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from .models import AutomationError
from .storage import hold_read_sources, replace_file

CHINA = timezone(timedelta(hours=8))
DAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
MODES = {"differential_universe": "差分宇宙", "currency_wars": "货币战争"}
DU_LEDGER = "differential-universe-ledger.json"


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=False, indent=2).replace("\n", os.linesep).encode("utf-8")


def claim_account_key(scene, confidence):
    from .currency_wars_identity import checked_account_key
    from .du_daily import account_key
    from .du_periodic_points import GuidePointsUnverified, _account

    # The week ledger and the native sequence use different fingerprint
    # formats. Admit only one UID candidate across both readers' regions.
    try:
        _account(scene, confidence, allow_hidden=False)
        checked_account_key(scene, confidence)
        return account_key(scene)
    except (AutomationError, GuidePointsUnverified) as error:
        raise AutomationError("差分周常领奖未核实唯一的当前账号。") from error


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
        raise SettingsError("weekly_runs", "周常局数应为 1～10。")


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
        target += f" · 周积分及奖励，最多 {settings.weekly_runs} 局"
    when = "到期，运行时核对" if slot.due else f"{DAYS[settings.weekly_day-1]} {settings.weekly_time} 后"
    return f"{target} · {when}"


def _verified_du_runs(report, requested):
    data = report.get("differential_universe") or {}
    runs = data.get("run_results")
    completed = data.get("completed_runs")
    if (type(requested) is int and 1 <= requested <= 10
            and report.get("operation") == "differential_universe"
            and report.get("report_saved") is True
            and data.get("mode") == "周期演算" and type(data.get("requested_runs")) is int
            and data["requested_runs"] == requested
            and type(completed) is int and 0 <= completed <= requested
            and isinstance(runs, list) and len(runs) == completed
            and all(isinstance(r, dict) and r.get("status") == "completed" and r.get("counted") is True
                    and r.get("difficulty_verified") is True and r.get("started_evidence")
                    and r.get("victory_evidence") and r.get("return_evidence") for r in runs)):
        return data


def verified_du_report(report, requested):
    data = _verified_du_runs(report, requested)
    return data is not None and report.get("status") == "success" and data["completed_runs"] == requested


def _points_report_state(report, maximum, week):
    from .currency_wars_points import game_week

    data = _verified_du_runs(report, maximum)
    if data is None or any(run.get("origin") != "fresh" for run in data["run_results"]):
        return None
    completed = data["completed_runs"]
    goal = data.get("periodic_points_goal")
    if (not isinstance(goal, dict) or goal.get("source") != "du_home"
            or type(goal.get("maximum")) is not int or goal["maximum"] != maximum):
        return None
    history = goal.get("observations")
    if not isinstance(history, list) or len(history) != completed + 1:
        return None
    cap, previous = None, -1
    for count, row in enumerate(history):
        if not isinstance(row, dict):
            return None
        current, limit, evidence = row.get("current"), row.get("cap"), row.get("evidence")
        if (type(row.get("completed_runs")) is not int or row["completed_runs"] != count
                or row.get("game_week") != week or type(limit) is not int or limit <= 0
                or (cap is not None and limit != cap) or type(current) is not int or not previous <= current <= limit
                or current < 0 or row.get("capped") is not (current == limit) or (count < completed and current == limit)
                or not isinstance(evidence, list) or len(evidence) != 2 or not all(isinstance(ref, dict) for ref in evidence)):
            return None
        try:
            if game_week(datetime.fromisoformat(row["observed_at"])) != week:
                return None
        except (KeyError, TypeError, ValueError):
            return None
        cap, previous = limit, current
    if goal.get("status") == "capped" and history[-1]["capped"] and report.get("status") == "success":
        return "complete"
    if (goal.get("status") == "exhausted" and not history[-1]["capped"]
            and completed == maximum and report.get("status") == "partial"):
        return "exhausted"


def _points_image_refs(du):
    for observation in du["periodic_points_goal"]["observations"]:
        yield from observation["evidence"]


def _points_image_hashes(du, directory):
    from .currency_wars_initial import source_file_ref

    hashes = {}
    for reference in _points_image_refs(du):
        try:
            actual = source_file_ref(reference["path"], directory)
        except AutomationError as error:
            raise ValueError("周常积分双帧证据文件未核实。") from error
        if actual != reference or actual["path"] in hashes:
            raise ValueError("周常积分双帧证据缺失、重复或已变化。")
        hashes[actual["path"]] = actual["sha256"]
    return hashes


def _ledger_path(directory):
    path = Path(directory).resolve() / DU_LEDGER
    if path.resolve() != path:
        raise ValueError("差分周常原生账本路径已变化。")
    return path


def _points_ledger_ref(report, scope):
    du = report["differential_universe"]
    path = _ledger_path(report["run_dir"])
    if du.get("weekly_points_scope") != scope or Path(du["ledger_path"]).resolve() != path:
        raise ValueError("差分周常原生报告与本周意图不一致。")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != du.get("weekly_points_ledger_sha256"):
        raise ValueError("差分周常原生账本已变化。")
    ledger = json.loads(raw)
    fields = ("session_id", "requested_runs", "completed_runs", "current_run", "run_results",
              "actions", "page_history", "periodic_points_goal", "weekly_points_scope")
    if ledger.get("schema_version") != 1 or any(ledger.get(field) != du[field] for field in fields):
        raise ValueError("差分周常原生账本与原报告不一致。")
    return dict(path=str(path), sha256=digest)


def evidence_hashes(report, *, include_points=False):
    directory = Path(report["run_dir"]).resolve()
    hashes = {}
    du = report["differential_universe"]
    for run in du["run_results"]:
        for field in ("started_evidence", "victory_evidence", "return_evidence"):
            path = Path(run[field]).resolve()
            if not path.is_relative_to(directory):
                raise ValueError("演算证据不在原始运行目录中。")
            hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if include_points:
        points = _points_image_hashes(du, directory)
        if hashes.keys() & points.keys():
            raise ValueError("演算与积分证据重复。")
        hashes.update(points)
    return hashes


class WeeklyReceipt:
    """Unknown intent blocks later weeks too; completion requires the saved report."""

    def __init__(self, root, account, slot):
        if not re.fullmatch(r"[a-f0-9]{24}", account):
            raise ValueError("无效的本地账号标识。")
        self.root = Path(root).resolve()
        self.account = account
        self.folder = self.root/"weekly-plan"/account
        self.path = self.folder/(slot.week+".json")
        self.slot = slot
        self.data = None
        self.reused_report = None
        self._intent_sha256 = None

    def points_scope(self, data):
        intent = data.get("intent_id")
        if (data.get("account_key") != self.account or data.get("mode") != "differential_universe"
                or not isinstance(intent, str) or not re.fullmatch(r"[a-f0-9]{32}", intent)):
            raise ValueError("差分周常积分回执的账号或原意图未核实。")
        return dict(account_key=self.account, week=data["week"], maximum=data["requested_runs"], intent_id=intent)

    def require_intent(self):
        try:
            if (self._intent_sha256 is not None and self.path.resolve() == self.path
                    and hashlib.sha256(self.path.read_bytes()).hexdigest() == self._intent_sha256):
                return
        except OSError as error:
            raise AutomationError("差分周常原意图无法读取，保留待核对。") from error
        raise AutomationError("差分周常原意图已变化，保留待核对。")

    def _state(self, data, report):
        objective = data.get("objective", "fixed_runs")
        if objective == "points":
            return _points_report_state(report, data["requested_runs"], data["week"])
        if objective == "fixed_runs" and verified_du_report(report, data["requested_runs"]):
            return "complete"

    def _report(self, data):
        path = Path(data["report"]).resolve()
        if not path.is_relative_to(self.root) or path.name != "report.json":
            raise ValueError("报告不在运行目录中。")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != data["report_sha256"]:
            raise ValueError("原报告已变化。")
        report = json.loads(raw)
        if Path(report["run_dir"]).resolve() != path.parent:
            raise ValueError("原报告与证据目录不一致。")
        points = data.get("objective") == "points"
        if points and data.get("ledger") != _points_ledger_ref(report, self.points_scope(data)):
            raise ValueError("差分周常原生账本未核实。")
        if data["evidence"] != evidence_hashes(report, include_points=points):
            raise ValueError("原始演算证据已变化。")
        return report

    def begin(self, settings, *, until_points=False, before_start=None):
        self.folder.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.folder.glob("*.json")):
            try:
                data = json.loads(path.read_text("utf-8"))
                if (data.get("version") != 1 or data.get("week") != path.stem
                        or data.get("state") not in ("complete", "exhausted")):
                    raise ValueError("完成证据不完整。")
                original = self._report(data)
                if self._state(data, original) != data["state"]:
                    raise ValueError("完成证据不完整。")
                if path == self.path:
                    self.data, self.reused_report = data, original
            except (OSError, ValueError, KeyError, TypeError, AttributeError, AutomationError) as exc:
                raise AutomationError("有周常记录待核对；保留原报告，未再开局。") from exc
        if self.reused_report is not None:
            return False
        if before_start is not None:
            before_start()
        self.data = dict(version=1, week=self.slot.week, state="started",
                         mode=settings.weekly_mode, requested_runs=settings.weekly_runs,
                         due_at=self.slot.due_at.isoformat(), started_at=datetime.now(CHINA).isoformat())
        if until_points:
            self.data.update(objective="points", account_key=self.account, intent_id=uuid.uuid4().hex)
        # Write intent before the workflow can enter a game. No replacement on retry.
        raw = _json_bytes(self.data)
        with self.path.open("xb") as stream:
            stream.write(raw)
        self._intent_sha256 = hashlib.sha256(raw).hexdigest()
        return True

    def complete(self, report, *, before_replace=None, require_current_week=None):
        state = self._state(self.data, report) if self.data is not None and self.data["state"] == "started" else None
        if state is None:
            raise AutomationError("周常演算完成证据不足；本周记录仍待核对。")
        report_path = (Path(report["run_dir"])/"report.json").resolve()
        if not report_path.is_relative_to(self.root):
            raise AutomationError("周常原始报告不在运行目录中；本周记录仍待核对。")
        raw = report_path.read_bytes()
        points = self.data.get("objective") == "points"
        # Match Runner's UTF-8 write_text bytes before binding the original report hash.
        if points and raw != _json_bytes(report):
            raise AutomationError("差分周常原生报告已变化，保留原意图。")
        persisted = json.loads(raw)
        if not points and persisted != json.loads(json.dumps(report)):
            raise AutomationError("周常原始报告未完整保存；本周记录仍待核对。")
        data = dict(self.data, state=state, report=str(report_path),
                    report_sha256=hashlib.sha256(raw).hexdigest(), evidence=evidence_hashes(persisted, include_points=points),
                    finished_at=datetime.now(CHINA).isoformat())
        if points:
            data["ledger"] = _points_ledger_ref(persisted, self.points_scope(self.data))
        sources = (report_path, *data["evidence"])
        if points:
            sources += (data["ledger"]["path"],)
        temp = self.path.with_suffix(".tmp")
        candidate = _json_bytes(data)
        temp.write_bytes(candidate)

        @contextmanager
        def verified_attempt():
            from .currency_wars_points import game_week

            with hold_read_sources(sources):
                try:
                    self._report(data)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise AutomationError("差分周常原报告或原始演算证据已变化，保留原意图。") from error
                if temp.read_bytes() != candidate:
                    raise AutomationError("差分周常待写回执已变化，保留原意图。")
                self.require_intent()
                if require_current_week is not None:
                    require_current_week()
                elif points and game_week(datetime.now(CHINA)) != self.slot.week:
                    raise AutomationError("差分周常积分回执落盘前已跨游戏周，保留原意图。")
                yield

        replace_file(temp, self.path, before_replace=before_replace, attempt_scope=verified_attempt)
        self.data = data
        return state


class WeeklyGuard:
    """Called inside the ordinary DU Runner's input lock, before any new run."""

    def __init__(self, root, settings, slot, *, until_points=False, strict_points_account=False):
        if (type(until_points) is not bool or until_points and
                (settings.weekly_enabled is not True or settings.weekly_mode != "differential_universe")):
            raise ValueError("周期积分目标需要已启用的差分周常。")
        if type(strict_points_account) is not bool or strict_points_account and not until_points:
            raise ValueError("周期领奖账号绑定需要差分周积分目标。")
        self.root, self.settings, self.slot = root, replace(settings), slot
        self.until_points = until_points
        self.strict_points_account = strict_points_account
        self.receipt = None
        self.already_complete = False
        self._ledger = None

    @property
    def reused_report(self):
        return self.receipt.reused_report if self.receipt is not None else None

    @property
    def already_exhausted(self):
        return self.reused_report is not None and self.receipt.data["state"] == "exhausted"

    def require_current_week(self):
        current = weekly_slot(self.settings)
        if not self.slot.due or current.week != self.slot.week:
            raise AutomationError("原周常演算目标尚未到期或已跨游戏周；保留原目标和已核实局数，停止推进。")

    def prepare(self, context):
        from .du_daily import account_key
        from .workflows import DailyWorkflow
        context.checkpoint()
        self.require_current_week()
        DailyWorkflow(context).ensure_main()
        context.checkpoint()
        scene = context.snapshot()
        try:
            account = (claim_account_key(scene, max(.85, context.settings.ocr_confidence))
                       if self.strict_points_account else account_key(scene))
        except AutomationError as exc:
            raise AutomationError("周常未核实当前账号；未开始演算。") from exc
        self.require_current_week()
        self.receipt = WeeklyReceipt(self.root, account, self.slot)

        def before_start():
            context.checkpoint()
            self.require_current_week()

        started = self.receipt.begin(self.settings, until_points=self.until_points, before_start=before_start)
        if not started:
            before_start()
        self.already_complete = not started and self.receipt.data["state"] == "complete"
        return started

    def require_account(self, scene):
        from .du_daily import account_key

        if self.receipt is None or account_key(scene) != self.receipt.account:
            raise AutomationError("当前账号与周常目标不一致。")

    def _require_ledger(self, path):
        if self.receipt is None:
            raise AutomationError("差分周常尚未写入原积分意图。")
        self.receipt.require_intent()
        try:
            if self._ledger is None:
                if not path.exists():
                    return
            elif self._ledger[0] == path and hashlib.sha256(path.read_bytes()).hexdigest() == self._ledger[1]:
                return
        except OSError as error:
            raise AutomationError("差分周常原生账本无法读取，停止继续演算。") from error
        raise AutomationError("差分周常原生账本已变化，停止继续演算。")

    def persist_points_ledger(self, du, payload, *, before_replace=None):
        path = _ledger_path(du["run_dir"])
        if self.receipt is None or not path.is_relative_to(self.receipt.root):
            raise AutomationError("差分周常原生账本路径不在本次运行目录。")
        scope = self.receipt.points_scope(self.receipt.data)
        payload = dict(payload, weekly_points_scope=scope, periodic_points_goal=du["periodic_points_goal"])
        raw = _json_bytes(payload)
        temp = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temp.write_bytes(raw)

        def recheck():
            if before_replace is not None:
                before_replace()
            self._require_ledger(path)

        replace_file(temp, path, before_replace=recheck)
        digest = hashlib.sha256(raw).hexdigest()
        self._ledger = (path, digest)
        du.update(ledger_path=str(path), weekly_points_scope=scope, weekly_points_ledger_sha256=digest)

    def require_points_sources(self, du, *, read_sources=None):
        self.require_current_week()
        try:
            path = _ledger_path(du["run_dir"])
            if self.receipt is None or self._ledger is None:
                raise ValueError("差分周常原生账本尚未写入。")
            if read_sources is not None:
                images = (reference["path"] for reference in _points_image_refs(du))
                read_sources.enter_context(hold_read_sources((self.receipt.path, path, *images)))
            self._require_ledger(path)
            _points_image_hashes(du, path.parent)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise AutomationError("差分周常原生账本或积分双帧已失效，停止继续演算。") from error

    def complete(self, report, *, checkpoint=None):
        if self.already_complete:
            return "complete"
        if self.receipt is None:
            raise AutomationError("周常尚未核实账号与执行记录。")

        def before_replace():
            if checkpoint is not None:
                checkpoint()
            self.require_current_week()

        return self.receipt.complete(report, before_replace=before_replace, require_current_week=self.require_current_week)
