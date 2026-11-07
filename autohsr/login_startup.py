"""Explicit, current-account registration for launching the desktop on logon."""

from .admin_launch import AdminLaunchError, _task, launch_spec


def status() -> dict:
    return _task("status", launch_spec(login=True))


def configure(operation: str) -> dict:
    if operation not in ("enable", "disable"):
        raise ValueError("请选择启用或移除登录自启。")
    spec = launch_spec(login=True)
    before = _task("status", spec)
    if (operation == "enable" and before["enabled"]) or (operation == "disable" and not before["exists"]):
        return before
    _task(operation, spec)
    after = _task("status", spec)
    if (operation == "enable" and not after["enabled"]) or (operation == "disable" and after["exists"]):
        raise AdminLaunchError("操作后未能核实登录自启状态。请刷新状态后再检查。")
    return after


def status_text(data: dict) -> str:
    if data["enabled"]:
        return "已启用 · 下次登录时启动助手到托盘"
    if data["exists"]:
        return "任务已停用或与当前安装不符 · 请重新启用或移除"
    return "未启用"
