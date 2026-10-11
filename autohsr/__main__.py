"""GUI entry point and scriptable diagnostics for AutoHSR."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import CONFIG_PATH, Settings


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="AutoHSR：通过屏幕识别完成星穹铁道每日任务。无参数时打开图形界面。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="检测窗口和 OCR，输出 JSON；不操作游戏")
    mode.add_argument("--launch", action="store_true", help="仅启动游戏程序")
    mode.add_argument("--run", action="store_true", help="按配置执行每日任务；F10 紧急停止")
    mode.add_argument("--self-test", action="store_true", help="运行离线单元测试（仅源码版，不操作游戏）")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="配置 JSON 路径")
    parser.add_argument("--game-path", help="命令行模式：StarRail.exe 路径")
    parser.add_argument("--target", help="命令行模式：拟造花萼中文名称")
    parser.add_argument("--location", help="命令行模式：副本地点，区分同名花萼；可留空")
    parser.add_argument("--stamina", type=int, help="命令行模式：开拓力上限，10～240，10 的倍数")
    parser.add_argument("--rounds", type=int, help="命令行模式：每次挑战轮数，1～6")
    args = parser.parse_args(argv)
    if args.self_test:
        import unittest
        test_path = Path(__file__).resolve().parent / "tests"
        if getattr(sys, "frozen", False) or not test_path.is_dir():
            print(_json({"error": "请在源码目录使用 --self-test；打包版不包含单元测试。"}), file=sys.stderr)
            return 2
        tests = unittest.defaultTestLoader.discover(str(test_path))
        result = unittest.TextTestRunner(verbosity=2).run(tests)
        return 0 if result.wasSuccessful() else 1
    if not any((args.check, args.launch, args.run)):
        from .gui import main as gui_main
        gui_main(args.config)
        return 0
    try:
        settings = Settings.load(args.config)
        for argument, field in (("game_path", "game_path"), ("target", "target_name"), ("location", "target_location"), ("stamina", "stamina_limit"), ("rounds", "rounds")):
            value = getattr(args, argument)
            if value is not None:
                setattr(settings, field, value)
        settings.validate()
        from .app import Runner, inspect_game, launch_game
        if args.check:
            print(_json(inspect_game(settings)))
            return 0
        if args.launch:
            print(launch_game(settings))
            return 0
        def emit(event: dict[str, Any]) -> None:
            kind = event.get("type", event.get("event", event.get("kind", "log")))
            if kind != "finished":
                print(json.dumps(event, ensure_ascii=False, default=str), file=sys.stderr, flush=True)
        runner = Runner(settings, emit)
        try:
            report = runner.run()
        except KeyboardInterrupt:
            runner.stop()
            print("已请求停止。", file=sys.stderr)
            return 130
        data = report.to_dict() if hasattr(report, "to_dict") else report
        print(_json(data))
        return 0 if isinstance(data, dict) and data.get("status") in ("success", "completed", "done") else 1
    except Exception as exc:
        print(_json({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
