"""Player-facing observation and results; raw evidence stays in its own report."""
from __future__ import annotations

from .currency_wars_pages import PAGE_LABELS
from .ux import issue_text, standard_activity, standard_run_verified

STAGES = {"needs_decision": "等待下一步决策", "needs_observation": "等待核实当前画面",
          "unknown": "动作结果待核对", "pending": "动作结果待核对", "unchanged": "页面未改变",
          "verified": "当前动作已核实", "transition_verified": "页面转换已核实",
          "game_ready": "游戏已就绪", "entry_ready": "标准模式已定位",
          "rank_ready": "标准难度已核实", "step_limit": "本次步骤已结束"}


def observation(data: dict) -> str:
    mode = data.get("mode")
    lines = []
    if mode == "standard_development":
        lines.append("标准 A8 · 财富造物主 40")
        lines.append("已核实开局" if data.get("start_verified") is True else "开局待核实")
        lines.append(standard_activity(data))
        lines.append("开发局胜利及结算已核实 · 未计独立验收" if standard_run_verified(data) else "整局未完成")
    elif mode == "entry_navigation":
        lines.append("标准A8财富造物主40已核实" if data.get("rank_verified") is True else
                     "标准模式已定位" if data.get("entry_ready") is True else STAGES.get(data.get("action_status"), "入口待核实"))
        lines.append("未开始新对局")
    elif mode == "startup_prepare":
        kind = data.get("page_kind")
        label = {"phone": "手机菜单", "world": "大世界"}.get(kind, PAGE_LABELS.get(kind, "当前页面未核实"))
        lines.extend((label, "启动准备已核实" if data.get("game_ready") is True else "启动准备待核实", "未开始新对局"))
    elif mode == "flow_test":
        count = sum(isinstance(a, dict) and a.get("node_verified") is True for a in data.get("actions", []))
        lines.extend((f"已验证 {count} 个节点", STAGES.get(data.get("action_status"), "当前动作待核对"), "整局未完成"))
    elif mode == "single_node_test":
        node = data.get("origin_node")
        lines.append((str(node)+" · " if node else "") + ("节点胜利已验证" if data.get("node_verified") is True else "节点结果待核对"))
        lines.append("整局未完成")
    elif mode in ("single_drag_test", "single_deployment_test"):
        lines.append({"verified": "部署已确认" if mode == "single_deployment_test" else "头像已互换",
                      "unchanged": "卡位未改变", "pending": "动作结果待核对"}.get(data.get("action_status"), "动作结果待核对"))
        lines.append("整局未完成")
    else:
        kind = data.get("page_kind")
        if kind == "world_entry" and data.get("page_verified") is True:
            lines.append("朝露公馆 · 货币战争交互入口，尚未打开玩法")
        elif data.get("page_verified") is True and kind in PAGE_LABELS:
            lines.append("已识别："+PAGE_LABELS[kind])
        elif data.get("mode_text_visible") is True:
            lines.append("已记录候选文字 · 当前页面未核实")
        else:
            lines.append("当前页面未核实")
        match = data.get("match")
        if isinstance(match, dict):
            fields = []
            node = match.get("node")
            fields.append("节点 "+(node if isinstance(node, str) and node else "未识别"))
            for name, label in (("gold", "金币"), ("level", "等级")):
                value = match.get(name)
                fields.append(label+" "+(str(value) if type(value) is int and value >= 0 else "未识别"))
            deployment = match.get("deployment")
            if isinstance(deployment, (list, tuple)) and len(deployment) == 2 and all(type(v) is int and v >= 0 for v in deployment):
                fields.append("出战 "+"/".join(map(str, deployment)))
            lines.append(" · ".join(fields))
    if data.get("reason"):
        lines.append(str(data["reason"]))
    return "\n".join(dict.fromkeys(lines))


def result(report: dict) -> tuple[str, str]:
    data = report.get("currency_wars") or {}
    status, operation = report.get("status"), report.get("operation")
    complete = operation == "currency_wars_standard" and standard_run_verified(data)
    stage = standard_activity(data) if operation == "currency_wars_standard" else None
    if complete:
        title = "开发局结算已核实"
        if status in ("failed", "partial", "stopped"):
            title += " · 后续"+("已停止" if status == "stopped" else "未完成")
    elif status in ("failed", "stopped"):
        title = "运行失败" if status == "failed" else "已停止"
    elif operation == "currency_wars_standard":
        title = {"核验补给角色": "补给角色待核实", "核验角色装备": "装备结果待核对",
                 "核验换人角色": "换人结果待核对", "核对奖励交付": "奖励交付待核对",
                 "等待核实当前画面": "当前画面待核实", "观察当前局面": "本次开发已结束"}.get(stage, stage)
    elif operation == "currency_wars_prepare":
        title = "启动准备结束"
    elif operation == "currency_wars":
        title = "只读识别结束" if data.get("page_verified") is True else "当前页面待核实"
    else:
        title = "本次验证结束"
    issue = issue_text(report)
    lines = [issue] if issue else []
    description = observation(data) if data else "本次未生成有效观察记录"
    # The result heading already states the final stage. Keep the reason and
    # independent completion evidence, but do not repeat an active-stage label.
    lines.extend(line for line in description.splitlines() if (not issue or line not in issue)
                 and not (line == stage and status not in ("failed", "stopped")))
    if report.get("safe_next") and (status != "success" or issue):
        lines.append("下一步："+str(report["safe_next"]))
    return title, "\n".join(dict.fromkeys(lines))
