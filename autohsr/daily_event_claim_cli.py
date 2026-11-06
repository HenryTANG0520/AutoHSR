"""Explicit entry point for submitting one selected day of 巡星之礼."""

import json
import sys

from .config import Settings
from .daily_observe import EVENT_CLAIM_OPERATION


def run(args, raw_args, parser):
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if (flags.count('--daily-event-claim') != 1
            or len(set(flags)) != len(flags)
            or set(flags) - {'--daily-event-claim', '--observe-daily-event-return', '--config', '--game-path'}):
        parser.error('巡星之礼单日提交只接受本次回页观察、--config 和 --game-path。')

    from .app import Runner

    try:
        settings = Settings.load(args.config)
        if args.game_path is not None:
            settings.game_path = args.game_path
        def emit(event):
            if event.get('type') == 'daily_event_manual_close':
                print(event['message'], file=sys.stderr, flush=True)

        runner = Runner(settings, emit, operation=EVENT_CLAIM_OPERATION, daily_event_claim_day=args.daily_event_claim,
                        daily_event_observe_return=args.observe_daily_event_return)
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
