"""Shared desktop behavior contract; no game or filesystem mutations."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

OPERATIONS = {"daily": "每日", "reward_only": "仅补领奖", "enter_game": "进入游戏", "check": "窗口检测",
              "currency_wars": "货币战争只读识别", "currency_wars_drag_test": "货币战争单次换位",
              "currency_wars_deploy_test": "货币战争单次部署", "currency_wars_node_test": "货币战争节点战斗",
              "currency_wars_flow_test": "货币战争流程推进验证",
              "differential_universe": "差分宇宙自动演算"}


def input_readiness(helper_admin: bool, game_admin: bool | None) -> bool | None:
    if game_admin is None:
        return None
    return not game_admin or helper_admin


def report_context(report: dict, path: Path | None = None) -> str:
    stamp = report.get("started_at") or report.get("finished_at")
    if stamp:
        when = str(stamp).replace("T", " ")[:25]
    elif path and path.exists():
        when = "文件时间 " + datetime.fromtimestamp(path.stat().st_mtime).astimezone().strftime("%m-%d %H:%M")
    else:
        when = "时间未记录"
    source = Path(report.get("source") or (path.parent.parent.parent if path else "."))
    kind = "打包版" if "dist" in source.parts else "源码/其他目录"
    operation = OPERATIONS.get(report.get("operation", ""), "旧记录·操作未记录")
    day = report.get("reset_day") or report.get("game_day")
    day = "配置推算日 " + day if day and day not in ("unverified", "unverified-global-reset") else "游戏日未核实"
    return f"上次记录 · {when} · {operation} · {kind} · {day}"


def exit_text(report: dict) -> str:
    result = next((r for r in report.get("results", []) if r.get("task") == "close_game"), None)
    if result:
        return {"ok": "游戏已退出", "skipped": "游戏保留：" + result.get("detail", "条件未满足")}.get(
            result.get("status"), "游戏退出未确认：" + result.get("detail", "请手动核对"))
    return "游戏保留（未请求自动退出）"


def recovery_text(report: dict) -> str:
    error = report.get("error")
    if not error:
        failed = next((r for r in report.get("results", []) if r.get("status") in ("failed", "partial", "stopped")), None)
        error = failed.get("detail") if failed else ""
    if not error:
        return ""
    next_step = report.get("safe_next") or (
        "人工核对当前界面与消耗，返回主界面后仅补领奖。" if any(report.get(k) for k in
            ('stamina_spent','stamina_pending','immersifiers_spent','immersifiers_pending')) else
        "查看本次截图，处理登录/更新或未知页面后重新检测；未确认事项不要视为完成。")
    return f"原因：{error}\n下一步：{next_step}"


def immersifier_text(report: dict) -> str:
    spent,pending=report.get('immersifiers_spent',0),report.get('immersifiers_pending',0)
    return f' · 沉浸器已确认 {spent}，待核对 {pending}' if spent or pending else ''
