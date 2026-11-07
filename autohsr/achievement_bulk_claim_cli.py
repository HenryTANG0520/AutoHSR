"""Explicit, foreground-only entry for an achievement bulk claim."""
import json

from .config import Settings
from .daily_observe import ACHIEVEMENT_CLAIM_OPERATION


def run(args, raw_args, parser):
    flags = [argument.partition('=')[0] for argument in raw_args if argument.startswith('--')]
    if (flags.count('--achievement-bulk-claim') != 1 or len(set(flags)) != len(flags)
            or set(flags) - {'--achievement-bulk-claim', '--config', '--game-path'}):
        parser.error('成就一键领奖为独立入口，仅可附带 --config 和 --game-path。')

    from .app import Runner

    try:
        settings = Settings.load(args.config, require_existing='--config' in flags)
        if args.game_path is not None:
            settings.game_path = args.game_path
        runner = Runner(settings, operation=ACHIEVEMENT_CLAIM_OPERATION)
    except (OSError, ValueError, TypeError):
        print(json.dumps({'status': 'failed', 'error': '无法读取本次成就领奖配置。'}, ensure_ascii=False))
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
