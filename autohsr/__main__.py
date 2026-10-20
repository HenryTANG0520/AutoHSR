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
    mode.add_argument("--currency-wars-replay", type=Path, help="离线回放 .sample.json；不访问游戏或加载每日配置")
    mode.add_argument("--currency-wars-check", action="store_true", help="货币战争只读识别与证据保存；自动玩法尚未开放")
    mode.add_argument("--check", action="store_true", help="检测窗口和 OCR，输出 JSON；不操作游戏")
    mode.add_argument("--scan-dungeons", action="store_true", help="采集生存索引全部副本入口；不开始挑战或消耗资源")
    mode.add_argument("--launch", action="store_true", help="仅启动游戏程序")
    mode.add_argument("--run", action="store_true", help="按配置执行每日任务；F10 紧急停止")
    mode.add_argument("--differential-universe", action="store_true", help="自动演算差分宇宙；不消耗每日刷本预算")
    mode.add_argument("--self-test", action="store_true", help="运行离线单元测试（仅源码版，不操作游戏）")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="配置 JSON 路径")
    parser.add_argument("--replay-ocr", action="store_true", help="仅配合 --currency-wars-replay，对样本 PNG 重新执行隔离 OCR")
    parser.add_argument("--game-path", help="命令行模式：StarRail.exe 路径")
    parser.add_argument("--target", help="命令行模式：副本中文名称")
    parser.add_argument("--location", help="命令行模式：刷本必填副本地点，区分同名副本")
    parser.add_argument("--stamina", type=int, help="命令行模式：开拓力上限，10～240，10 的倍数")
    parser.add_argument("--rounds", type=int, help="命令行模式：每次挑战轮数，1～6")
    parser.add_argument("--category", help="副本分类：calyx_golden/calyx_crimson/stagnant_shadow/cavern/echo_of_war/planar")
    parser.add_argument("--count", type=int, help="本次完成的挑战次数；达到次数即停止，仍受开拓力上限约束")
    parser.add_argument("--du-runs", type=int, help="差分宇宙局数，1～3；仅配合 --differential-universe")
    parser.add_argument("--resume-active-du", action="store_true",
                        help="仅在屏幕已识别到差分宇宙运行页面时接续当前局；不会启动新档")
    parser.add_argument("--du-periodic-rank", type=int,
                        help="接续当前用户已启动的周期演算时提供页面已选难度（1～10）；会将该局计入请求局数")
    parser.add_argument("--reward-only", action="store_true", help="本次仅验证并补领每日实训；不刷本，不保存配置")
    parser.add_argument("--new-battle-run", action="store_true", help="明确开始新的刷本预算；先人工核对上次已确认及待核对消耗")
    args = parser.parse_args(argv)
    if args.replay_ocr and args.currency_wars_replay is None:
        print(_json({"error": "--replay-ocr 仅用于 --currency-wars-replay。"}), file=sys.stderr)
        return 2
    if (args.reward_only or args.new_battle_run) and not args.run:
        print(_json({"error": "--reward-only 与 --new-battle-run 仅用于 --run。"}), file=sys.stderr)
        return 2
    if args.du_runs is not None and not args.differential_universe:
        print(_json({"error": "--du-runs 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.resume_active_du and not args.differential_universe:
        print(_json({"error": "--resume-active-du 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.du_periodic_rank is not None and not args.differential_universe:
        print(_json({"error": "--du-periodic-rank 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.du_periodic_rank is not None and not args.resume_active_du:
        print(_json({"error": "--du-periodic-rank 仅配合 --resume-active-du 使用。"}), file=sys.stderr)
        return 2
    if args.du_periodic_rank is not None and not 1 <= args.du_periodic_rank <= 10:
        print(_json({"error": "--du-periodic-rank 必须是 1～10。"}), file=sys.stderr)
        return 2
    if args.currency_wars_replay is not None:
        try:
            from .currency_wars_replay import replay_sample
            result = replay_sample(args.currency_wars_replay, reocr=args.replay_ocr)
            print(_json(result))
            return 1 if result["expectation_passed"] is False else 0
        except Exception as error:
            print(_json({"error": str(error), "game_accessed": False}), file=sys.stderr)
            return 2
    if args.self_test:
        import unittest
        test_path = Path(__file__).resolve().parent / "tests"
        if getattr(sys, "frozen", False) or not test_path.is_dir():
            print(_json({"error": "请在源码目录使用 --self-test；打包版不包含单元测试。"}), file=sys.stderr)
            return 2
        tests = unittest.defaultTestLoader.discover(str(test_path))
        result = unittest.TextTestRunner(verbosity=2).run(tests)
        return 0 if result.wasSuccessful() else 1
    if not any((args.check, args.scan_dungeons, args.launch, args.run, args.currency_wars_check, args.differential_universe)):
        from .gui import main as gui_main
        gui_main(args.config)
        return 0
    try:
        settings = Settings.load(args.config)
        for argument, field in (("game_path", "game_path"), ("target", "target_name"), ("location", "target_location"), ("stamina", "stamina_limit"), ("rounds", "rounds"), ("category", "dungeon_category"), ("count", "challenge_count")):
            value = getattr(args, argument)
            if value is not None:
                setattr(settings, field, value)
        if args.du_runs is not None:
            settings.differential_universe_runs = args.du_runs
        if args.scan_dungeons:
            settings.dungeon_category = args.category or "auto"
        if args.reward_only:
            from .recovery import reward_only_settings
            settings = reward_only_settings(settings)
        settings.validate("check" if args.check or args.scan_dungeons else "launch" if args.launch else "currency_wars" if args.currency_wars_check else "differential_universe" if args.differential_universe else "daily")
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
        runner = Runner(settings, emit, new_battle_run=args.new_battle_run,
                        operation="dungeon_catalogue" if args.scan_dungeons else "currency_wars" if args.currency_wars_check else "differential_universe" if args.differential_universe else "reward_only" if args.reward_only else "daily",
                        **(dict(du_runs=settings.differential_universe_runs,
                                du_resume_active=args.resume_active_du,
                                du_periodic_rank=args.du_periodic_rank) if args.differential_universe else {}))
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
    from multiprocessing import freeze_support
    freeze_support()
    raise SystemExit(main())
