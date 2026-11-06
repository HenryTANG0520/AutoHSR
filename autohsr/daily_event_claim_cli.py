"""Explicit entry point for submitting one selected day of 巡星之礼."""

import json

from .config import Settings
from .daily_observe import EVENT_CLAIM_OPERATION


def run(args, raw_args, parser):
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if (flags.count('--daily-event-claim') != 1
            or len(set(flags)) != len(flags)
            or set(flags) - {'--daily-event-claim', '--config', '--game-path'}):
        parser.error('巡星之礼单日提交为独立入口，仅可附带 --config 和 --game-path。')

    from .app import Runner

    try:
        settings = Settings.load(args.config)
        if args.game_path is not None:
            settings.game_path = args.game_path
        runner = Runner(settings, operation=EVENT_CLAIM_OPERATION, daily_event_claim_day=args.daily_event_claim)
    except (OSError, ValueError, TypeError):
        print(json.dumps({'status': 'failed', 'error': '无法读取本次巡星之礼配置。'}, ensure_ascii=False))
        return 1

    try:
        report = runner.run()
    except KeyboardInterrupt:
        print(json.dumps(runner.report.to_dict(), ensure_ascii=False, indent=2))
        return 130
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if report.status == 'stopped':
        return 130
    return 0 if report.status == 'success' else 1
