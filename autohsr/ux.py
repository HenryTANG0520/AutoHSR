"""Shared desktop behavior contract; no game or filesystem mutations."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

OPERATIONS = {"plan": "日常与周常计划", "daily": "每日", "reward_only": "仅补领奖", "enter_game": "进入游戏", "check": "窗口检测",
              "currency_wars": "货币战争只读识别", "currency_wars_drag_test": "货币战争单次换位",
              "currency_wars_deploy_test": "货币战争单次部署", "currency_wars_node_test": "货币战争节点战斗",
              "currency_wars_flow_test": "货币战争流程推进验证",
              "differential_universe": "差分宇宙自动演算"}


def planned_battle_metrics(category, count, enabled=True):
    if not enabled:
        return None
    from .dungeons import count_limit
    try:
        count = int(count)
        if not 1 <= count <= count_limit(category):
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        return "— 次", "次数待填写"
    prefix = "最多" if category.key == "planar" else "预计"
    cost = f"{prefix} {count*category.cost} 开拓力"
    if category.key == "planar":
        cost += "\n已有沉浸器优先"
    return f"{count} 次", cost


def reported_battle_metrics(report):
    completed, requested = report.get("battle_completed"), report.get("battle_requested")
    known_count = type(completed) is int and completed >= 0
    known_target = type(requested) is int and requested > 0
    value = (f"{completed}/{requested} 次" if known_count and known_target and completed <= requested else
             f"{completed} 次" if known_count and requested is None else "— 次")
    spent = report.get("stamina_spent")
    pending = any(key in report and (type(report[key]) is not int or report[key] > 0 or report[key] < 0)
                  for key in ("stamina_pending", "immersifiers_pending"))
    if pending:
        return value, "消耗待核对"
    cost = f"已用 {spent} 开拓力" if type(spent) is int and spent >= 0 else "消耗未记录"
    if "immersifiers_spent" in report:
        count = report["immersifiers_spent"]
        if type(count) is not int or count < 0:
            cost += "\n沉浸器待核对"
        elif count:
            cost += f"\n沉浸器 {count}"
    return value, cost


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


def issue_text(report: dict) -> str:
    """The first visible line carries the reason, while full costs stay in details."""
    error = report.get("error") or next((r.get("detail", "") for r in report.get("results", [])
        if r.get("status") in ("failed", "partial", "stopped")), "")
    parts = []
    if report.get("report_saved") is False:
        parts.append("报告未保存")
    for field, name in (("stamina_pending", "开拓力"), ("immersifiers_pending", "沉浸器")):
        value = report.get(field, 0)
        if value is None:
            parts.append(name+"待核对")
        elif type(value) is int and value > 0:
            parts.append(f"{value} {name}待核对")
    if error:
        parts.append(" ".join(str(error).split()))
    return " · ".join(parts)


def plan_result(report: dict) -> tuple[str, str] | None:
    """Use the frozen task scope; missing legacy context retains its old view."""
    if report.get("operation") != "plan":
        return None
    weekly = report.get("weekly_plan")
    tasks = weekly.get("daily_tasks") if isinstance(weekly, dict) else None
    if (not isinstance(tasks, list) or any(not isinstance(name, str) or name not in
            ("assignments", "battle", "daily", "mail", "battlepass") for name in tasks)
            or len(tasks) != len(set(tasks))):
        return None
    status = report.get("status")
    label = {"success": "全部完成", "partial": "部分完成", "failed": "失败",
             "stopped": "已停止", "cancelled": "已停止"}.get(status, "运行结束")
    if status == "success" and report.get("report_saved") is not True:
        label = "结果待核对"
    weekly_status = weekly.get("status")
    reused = weekly.get('daily_reused') is True and report.get('budget_scope') == 'original_daily_run'
    if tasks and status == "success" and report.get("report_saved") is True and weekly_status in ("disabled", "not_due"):
        label = "日常已完成"
    elif not tasks and status == "success" and report.get("report_saved") is True:
        label = {"not_due": "本次无需执行", "complete": "周常演算完成" if weekly.get("mode") == "differential_universe" else "周常完成",
                 "already_complete": "周常已完成", "disabled": "本次未执行任务"}.get(weekly_status, label)
    if weekly.get('mode') == 'currency_wars' and weekly_status in ('complete', 'already_complete'):
        verified = status == 'success' and report.get('report_saved') is True and weekly.get('score_rewards_verified') is True
        if not verified:
            label = '周常待核对'
        elif not tasks:
            label = '周常积分及奖励完成'
        if verified and (report.get('currency_wars') or {}).get('read_only_recovery') is True:
            label = '原周常结果已补存'
    parts = [label]
    if reused:
        parts.append('沿用原日常结果')
    if not tasks and weekly_status == "not_due":
        parts.append("周常未到期")
    resources = (("stamina_spent", "stamina_pending", "开拓力"),
                 ("immersifiers_spent", "immersifiers_pending", "沉浸器"))
    unexpected_cost = any(key in report and (type(report[key]) is not int or report[key] != 0)
                          for pair in resources for key in pair[:2])
    if label == "本次无需执行" and (unexpected_cost or report.get("daily_verified") is True):
        label = parts[0] = "结果待核对"
    if "battle" in tasks or unexpected_cost:
        if "battle" in tasks:
            value, _ = reported_battle_metrics(report)
            parts.append("副本 "+value)
        for spent, pending, name in resources:
            amount, unknown = report.get(spent), report.get(pending, 0)
            if spent == "stamina_spent" or amount or unknown or (spent in report and type(amount) is not int):
                parts.append(('原日常' if reused else '')+(f"已确认 {amount} {name}" if type(amount) is int and amount >= 0 else name+"消耗未记录"))
            if pending in report and (type(unknown) is not int or unknown < 0):
                parts.append(name+"待核对")
            elif type(unknown) is int and unknown > 0:
                parts.append(f"{unknown} {name}待核对")
    if "daily" in tasks or report.get("daily_verified") is True:
        parts.append(('原日常' if reused else '')+("实训奖励已核实" if report.get("daily_verified") is True else "实训奖励未核实"))
    if any(isinstance(row, dict) and row.get("task") == "close_game" for row in report.get("results", [])):
        parts.append(('原日常：' if reused else '')+exit_text(report))
    lines = [" · ".join(parts)]
    message = weekly.get("message")
    if weekly_status == "not_due":
        try:
            due = datetime.fromisoformat(weekly["due_at"])
            if due.tzinfo is None:
                raise ValueError("Missing time zone")
            from .weekly_plan import CHINA
            lines.append(("周常未到期 · " if tasks else "")+"计划时间："+
                         due.astimezone(CHINA).strftime("%Y-%m-%d %H:%M")+"（北京时间）")
        except (KeyError, TypeError, ValueError):
            if isinstance(message, str) and message:
                lines.append(message)
    elif weekly.get('mode') == 'currency_wars' and weekly_status != 'disabled':
        from .weekly_feedback import currency_weekly_caption
        caption = currency_weekly_caption(report)
        if caption:
            lines.append(caption)
    elif weekly_status != "disabled" and isinstance(message, str) and message and message != report.get("error"):
        week = weekly.get("week")
        lines.append(message.replace("本周", week+" 当周") if isinstance(week, str) and
                     re.fullmatch(r"\d{4}-\d{2}-\d{2}", week) else message)
    recovery = recovery_text(report)
    if recovery:
        lines.append(recovery)
    return label, "\n".join(lines)


def universe_result(report: dict) -> tuple[str, str]:
    """Describe recorded outcomes without exposing OCR, IDs or action payloads."""
    data = report.get("differential_universe") or {}
    requested, completed = data.get("requested_runs"), data.get("completed_runs")
    counts_known = (type(requested) is int and type(completed) is int
                    and 1 <= requested <= 10 and 0 <= completed <= requested)
    status = report.get("status")
    outcome = {"success": "演算完成", "stopped": "已停止", "failed": "运行失败",
               "partial": "部分完成"}.get(status, "运行结束")
    if status == "success" and (not counts_known or completed != requested):
        outcome = "完成情况待核对"
    title = outcome + (f" · 已完成 {completed}/{requested} 局" if counts_known else " · 局数未核实")
    if counts_known and completed == requested and status in ("failed", "partial", "stopped"):
        rewards = data.get("reward_collection") or {}
        following = ("后续已停止" if status == "stopped" else "领奖未完成"
                     if rewards.get("status") in ("failed", "unhandled_notification") else "后续未完成")
        title = f"已完成 {completed}/{requested} 局 · {following}"
    lines = []
    issue = issue_text(report)
    if issue:
        lines.append(issue)
    mode = data.get("mode")
    if mode in ("周期演算", "常规演算"):
        lines.append(mode)
    results = [r for r in data.get("run_results", []) if isinstance(r, dict)]
    resumed = [r for r in results if r.get("origin") == "resumed_trial"
               and r.get("status") in ("completed", "returned_uncounted")]
    if resumed:
        counted = sum(r.get("counted") is True for r in resumed)
        lines.append(f"接续通关 {len(resumed)} 局 · {counted} 局计入本次目标")
    saved = [str(r["save_name"]) for r in results
             if r.get("save_status") == "saved" and r.get("save_name") and r.get("save_evidence")]
    if saved:
        lines.append("已保存：" + "、".join(saved))
    full = sum(r.get("save_status") == "skipped_full" for r in results)
    if full:
        lines.append(f"存档槽已满 · {full} 局跳过保存")
    rewards = data.get("reward_collection") or {}
    reward_status = rewards.get("status")
    if reward_status and reward_status != "disabled":
        verified = reward_status == "complete" and bool(rewards.get("home_evidence"))
        message = "红点奖励已核实领完" if verified else "红点奖励未完成"
        cassettes = [r.get("mode_cassettes_used") for r in rewards.get("claims", [])
                    if isinstance(r, dict) and "mode_cassettes_used" in r]
        if cassettes:
            cost_known = all(type(v) is int and v >= 0 for v in cassettes)
            message += f" · 已使用 {sum(cassettes)} 月下卡带" if cost_known else " · 卡带消耗待核对"
        if not verified and rewards.get("failure_reason") and rewards["failure_reason"] not in issue:
            message += "："+str(rewards["failure_reason"])
        lines.append(message)
    for entry in data.get("daily_interludes", []):
        if not isinstance(entry, dict):
            continue
        daily_status = entry.get("status")
        if daily_status == "before_start_day":
            lines.append(f"通关后日常未到开始日期：{entry.get('start_day', '未记录')}")
        elif daily_status == "complete":
            amounts = [entry.get("stamina_spent"), entry.get("immersifiers_spent")]
            if all(type(v) is int and v >= 0 for v in amounts):
                lines.append(f"通关后日常完成 · {amounts[0]} 开拓力 · {amounts[1]} 沉浸器")
            else:
                lines.append("通关后日常已结束 · 消耗待核对")
        else:
            lines.append("通关后日常未完成" + ("："+str(entry["error"]) if entry.get("error") and entry["error"] not in issue else ""))
    if report.get("safe_next") and status != "success":
        lines.append("下一步："+str(report["safe_next"]))
    return title, "\n".join(lines)


def standard_run_verified(data: dict) -> bool:
    return (data.get("mode") == "standard_development" and data.get("status") == "settled"
            and data.get("completion_verified") is True and data.get("settlement_verified") is True)


def standard_activity(data: dict) -> str:
    exchange = data.get("exchange") or {}
    equipment = data.get("equipment") or {}
    reward = data.get("reward") or {}
    status = data.get("action_status")
    if reward.get("status") == "awaiting":
        return "核对奖励交付"
    if reward.get("status") == "unit_verifying":
        return "核验补给角色"
    if reward.get("status") == "unit_mismatch":
        return "补给角色不符"
    if status == "reward_verified":
        return "奖励交付已核实" if reward_delivery_verified(data) else "奖励交付待核对"
    if equipment.get("status") == "verifying":
        return "核验角色装备"
    if equipment.get("status") == "equipment_mismatch":
        return "角色装备不符"
    if status == "equipment_verified":
        return "装备已核实" if equipment.get("status") == "verified" else "装备结果待核对"
    if exchange.get("status") == "verifying":
        return "核验换人角色"
    if exchange.get("status") == "identity_mismatch":
        return "换人角色不符"
    if status == "exchange_verified":
        return "换人已核实" if exchange.get("status") == "verified" else "换人结果待核对"
    return {"exchange_identity_pending": "核验换人角色", "equipment_identity_pending": "核验角色装备",
            "needs_observation": "等待核实当前画面",
            "readonly_reconciled": "当前页面已核实", "transition_verified": "页面转换已核实",
            "unknown": "动作结果待核对", "step_limit": "本次开发步骤已结束",
            "settled": "本局结算已核实" if standard_run_verified(data) else "结算待核对"}.get(status, "观察当前局面")


def reward_delivery_verified(data: dict) -> bool:
    """A transition receipt alone is not a delivered unit or completed reward."""
    reward, actions = data.get("reward") or {}, data.get("actions") or []
    if reward.get("status") != "verified" or not isinstance(actions, list):
        return False
    indices = [reward.get("origin_action_id"), reward.get("claim_action_id")]
    if not all(type(index) is int and 0 <= index < len(actions) for index in indices):
        return False
    if not all(isinstance(actions[index], dict) and actions[index].get("id") == index
               and actions[index].get("reward_verified") is True for index in indices):
        return False
    effect = actions[indices[1]].get("reward_effect") or {}
    return (effect.get("inventory_checked") is True and effect.get("unit_verified") is True
            and (not effect.get("unit") or effect.get("other_roster_verified") is True))
