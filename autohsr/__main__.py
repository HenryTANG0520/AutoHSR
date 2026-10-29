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
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="AutoHSR：通过屏幕识别完成星穹铁道每日任务。无参数时打开图形界面。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--currency-wars-replay", type=Path, help="离线回放 .sample.json；不访问游戏或加载每日配置")
    mode.add_argument("--currency-wars-check", action="store_true", help="货币战争只读识别与证据保存；自动玩法尚未开放")
    mode.add_argument("--currency-wars-prepare", action="store_true", help="启动或复用游戏，进入已有登录及主界面；不开始对局")
    mode.add_argument("--currency-wars-locate", action="store_true", help="启动准备并通过指南定位货币战争标准模式；不开始对局")
    mode.add_argument("--currency-wars-configure", action="store_true", help="定位标准博弈并配置A8财富造物主40；不开始对局")
    mode.add_argument("--currency-wars-standard", action="store_true", help="标准A8-40开发：核实配置后新开局；未知页面停下留证")
    mode.add_argument('--currency-wars-loop', action='store_true', help='标准A8-40连续开发：逐局核实结算与保存，失败或未知即停止')
    mode.add_argument("--check", action="store_true", help="检测窗口和 OCR，输出 JSON；不操作游戏")
    mode.add_argument("--scan-dungeons", action="store_true", help="采集生存索引全部副本入口；不开始挑战或消耗资源")
    mode.add_argument("--launch", action="store_true", help="仅启动游戏程序")
    mode.add_argument("--run", action="store_true", help="按配置执行每日任务；F10 紧急停止")
    mode.add_argument("--plan", action="store_true", help="执行日常和到期周常计划；不登记定时任务")
    mode.add_argument("--differential-universe", action="store_true", help="自动演算差分宇宙；不消耗每日刷本预算")
    mode.add_argument("--self-test", action="store_true", help="运行离线单元测试（仅源码版，不操作游戏）")
    mode.add_argument("--admin-launch", choices=("status", "enable", "disable"),
                      help="查询、启用或移除当前账户及本目录的管理员免重复确认启动；不启动游戏")
    mode.add_argument("--no-admin-launch", action="store_true", help="跳过管理员启动入口，仅打开当前权限的 GUI 以排查或移除授权")
    mode.add_argument("--admin-task", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--admin-owner", help=argparse.SUPPRESS)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH, help="配置 JSON 路径")
    parser.add_argument("--replay-ocr", action="store_true", help="仅配合 --currency-wars-replay，对样本 PNG 重新执行隔离 OCR")
    parser.add_argument("--game-path", help="命令行模式：StarRail.exe 路径")
    parser.add_argument("--target", help="命令行模式：副本中文名称")
    parser.add_argument("--location", help="命令行模式：刷本必填副本地点，区分同名副本")
    parser.add_argument("--stamina", type=int, help="命令行模式：开拓力上限，10～240，10 的倍数")
    parser.add_argument("--rounds", type=int, help="命令行模式：每次挑战轮数，1～6")
    parser.add_argument("--category", help="副本分类：calyx_golden/calyx_crimson/stagnant_shadow/cavern/echo_of_war/planar")
    parser.add_argument("--count", type=int, help="本次完成的挑战次数；达到次数即停止，仍受开拓力上限约束")
    parser.add_argument("--du-runs", type=int, help="差分宇宙局数，1～10；仅配合 --differential-universe")
    parser.add_argument("--du-team", help="每次开局从预设编队选择此名称；默认哈哈哈哈")
    parser.add_argument("--du-mode", choices=('periodic','normal'), help="演算模式；默认 periodic 周期演算")
    parser.add_argument("--du-save", action="store_true", help="通关后保存为 AutoHSR 编号存档；默认不保存")
    parser.add_argument("--du-rewards", action="store_true", help="运行前后检查并领取差分宇宙红点奖励；默认关闭")
    parser.add_argument("--du-daily", action="store_true", help="每天首次通关后领奖并刷浴火钢心位面饰品；不补充资源，默认关闭")
    parser.add_argument("--du-daily-from", help="通关后日常起始游戏日 YYYY-MM-DD；仅配合 --du-daily，凌晨4点换日")
    parser.add_argument("--resume-active-du", action="store_true",
                        help="仅在屏幕已识别到差分宇宙运行页面时接续当前局；不会启动新档")
    parser.add_argument("--du-periodic-rank", type=int,
                        help="接续当前用户已启动的周期演算时提供页面已选难度（1～10）；会将该局计入请求局数")
    parser.add_argument("--reward-only", action="store_true", help="本次仅验证并补领每日实训；不刷本，不保存配置")
    parser.add_argument("--new-battle-run", action="store_true", help="明确开始新的刷本预算；先人工核对上次已确认及待核对消耗")
    parser.add_argument("--resume-active-currency", action="store_true", help="仅配合标准开发入口，接续有记录且已核实开始的货币战争")
    parser.add_argument('--currency-runs', type=int, help='循环请求局数，0表示直到停止；仅用于 --currency-wars-loop，不保存配置')
    parser.add_argument('--resume-currency-loop', action='store_true', help='明确接续原循环的剩余局数与原设置；仅用于 --currency-wars-loop')
    parser.add_argument("--currency-strategy", choices=('default','aglaea','seele'),
                        help="标准开发购买与成长策略；新局默认 default，接续沿用本局记录")
    parser.add_argument('--currency-remembrance-name',help='本局记忆开拓者实际显示名称；留空不配置，接续沿用已记录名称，不保存设置')
    parser.add_argument('--currency-fast-mode',action=argparse.BooleanOptionalAction,default=None,
                        help='速通装备：普通装备仅在标准首领节点分配，命名核心仍优先；可用 --no-currency-fast-mode 关闭，接续沿用本局，不保存设置')
    args = parser.parse_args(raw_args)
    if args.resume_active_currency and not args.currency_wars_standard:
        parser.error('--resume-active-currency 仅用于 --currency-wars-standard。')
    if (args.currency_runs is not None or args.resume_currency_loop) and not args.currency_wars_loop:
        parser.error('--currency-runs 与 --resume-currency-loop 仅用于 --currency-wars-loop。')
    for option, value in (('--currency-strategy',args.currency_strategy), ('--currency-remembrance-name',args.currency_remembrance_name),
                          ('--currency-fast-mode',args.currency_fast_mode)):
        if value is not None and not (args.currency_wars_standard or args.currency_wars_loop):
            parser.error(option+' 仅用于 --currency-wars-standard 或 --currency-wars-loop。')
    if args.admin_owner is not None and args.admin_launch not in ("enable", "disable"):
        parser.error("--admin-owner 仅用于管理员授权操作。")
    if args.admin_task and raw_args != ["--admin-task"]:
        parser.error("管理员启动任务只能打开固定的默认 GUI。")
    if args.admin_launch:
        try:
            from .admin_launch import configure, status, status_text
            data = status() if args.admin_launch == "status" else configure(args.admin_launch, expected_sid=args.admin_owner)
            print(_json(dict(**data, message=status_text(data))))
            return 0
        except Exception as error:
            print(_json({"error": str(error)}), file=sys.stderr)
            return 2
    if args.replay_ocr and args.currency_wars_replay is None:
        print(_json({"error": "--replay-ocr 仅用于 --currency-wars-replay。"}), file=sys.stderr)
        return 2
    if (args.reward_only and not args.run) or (args.new_battle_run and not (args.run or args.plan)):
        print(_json({"error": "--reward-only 仅用于 --run；--new-battle-run 可用于 --run 或 --plan。"}), file=sys.stderr)
        return 2
    if args.du_runs is not None and not args.differential_universe:
        print(_json({"error": "--du-runs 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.du_save and not args.differential_universe:
        print(_json({"error": "--du-save 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.du_team is not None and not args.differential_universe:
        print(_json({"error": "--du-team 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.du_mode is not None and not args.differential_universe:
        print(_json({"error": "--du-mode 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.du_rewards and not args.differential_universe:
        print(_json({"error": "--du-rewards 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.du_daily and not args.differential_universe:
        print(_json({"error": "--du-daily 仅用于 --differential-universe。"}), file=sys.stderr)
        return 2
    if args.du_daily_from is not None and not args.du_daily:
        print(_json({"error": "--du-daily-from 仅配合 --du-daily 使用。"}), file=sys.stderr)
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
    if not any((args.check, args.scan_dungeons, args.launch, args.run, args.plan, args.currency_wars_check, args.currency_wars_prepare, args.currency_wars_locate, args.currency_wars_configure, args.currency_wars_standard, args.currency_wars_loop, args.differential_universe)):
        from .admin_launch import AdminLaunchError, handoff, is_admin
        try:
            if args.admin_task and not is_admin():
                raise AdminLaunchError("管理员启动任务未获得管理员权限，未打开任务界面。")
            if not args.admin_task and not args.no_admin_launch and args.config.resolve() == CONFIG_PATH.resolve():
                if handoff():
                    return 0
        except Exception as error:
            # A failed or unknown handoff must not open a second controller.
            if sys.stderr is not None:
                print(_json({"error": str(error)}), file=sys.stderr)
            else:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("管理员启动未完成", str(error), parent=root)
                root.destroy()
            return 2
        from .gui import main as gui_main
        gui_main(args.config, admin_task=True) if args.admin_task else gui_main(args.config)
        return 0
    try:
        settings = Settings.load(args.config)
        for argument, field in (("game_path", "game_path"), ("target", "target_name"), ("location", "target_location"), ("stamina", "stamina_limit"), ("rounds", "rounds"), ("category", "dungeon_category"), ("count", "challenge_count")):
            value = getattr(args, argument)
            if value is not None:
                setattr(settings, field, value)
        if args.du_runs is not None:
            settings.differential_universe_runs = args.du_runs
        if args.du_team is not None:
            settings.differential_universe_team = args.du_team.strip()
        if args.du_mode is not None:
            settings.differential_universe_mode = args.du_mode
        if args.du_save:
            settings.differential_universe_save = True
        if args.du_rewards:
            settings.differential_universe_rewards = True
        if args.du_daily:
            settings.differential_universe_daily = True
        if args.du_daily_from is not None:
            settings.differential_universe_daily_from = args.du_daily_from
        if args.scan_dungeons:
            settings.dungeon_category = args.category or "auto"
        if args.reward_only:
            from .recovery import reward_only_settings
            settings = reward_only_settings(settings)
        settings.validate("check" if args.check or args.scan_dungeons else "launch" if args.launch else "currency_wars" if args.currency_wars_check or args.currency_wars_prepare or args.currency_wars_locate or args.currency_wars_configure or args.currency_wars_standard or args.currency_wars_loop else "differential_universe" if args.differential_universe else "daily")
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
        if args.currency_wars_loop:
            from .currency_wars_loop import CurrencyLoopRunner
            runner = CurrencyLoopRunner(settings, emit, runs=args.currency_runs, resume=args.resume_currency_loop,
                currency_strategy=args.currency_strategy, currency_remembrance_name=args.currency_remembrance_name,
                currency_fast_mode=args.currency_fast_mode)
        elif args.plan:
            from .plan_runner import PlanRunner
            runner = PlanRunner(settings, emit, new_battle_run=args.new_battle_run)
        else:
            runner = Runner(settings, emit, new_battle_run=args.new_battle_run,
                            operation="dungeon_catalogue" if args.scan_dungeons else "currency_wars_standard" if args.currency_wars_standard else "currency_wars_prepare" if args.currency_wars_prepare or args.currency_wars_locate or args.currency_wars_configure else "currency_wars" if args.currency_wars_check else "differential_universe" if args.differential_universe else "reward_only" if args.reward_only else "daily",
                            **(dict(currency_locate=True) if args.currency_wars_locate or args.currency_wars_configure else {}),
                            **(dict(currency_configure=True) if args.currency_wars_configure else {}),
                            **(dict(currency_resume=args.resume_active_currency) if args.currency_wars_standard else {}),
                            **(dict(currency_strategy=args.currency_strategy) if args.currency_strategy is not None else {}),
                            **(dict(currency_remembrance_name=args.currency_remembrance_name) if args.currency_remembrance_name is not None else {}),
                            **(dict(currency_fast_mode=args.currency_fast_mode) if args.currency_fast_mode is not None else {}),
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
