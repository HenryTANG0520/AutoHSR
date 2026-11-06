"""Explicit command-line entry for one named SMS reply."""
import json

from .config import Settings
from .daily_observe import MESSAGE_REPLY_OPERATION


def add_arguments(mode):
    from .daily_message_reply import REPLY_SELECTIONS

    choices = '；'.join(' '.join(selection) for selection in REPLY_SELECTIONS)
    mode.add_argument('--daily-message-reply', nargs=2, metavar=('NODE', 'CHOICE'),
                      help=f'在已选中会话提交一次明确回复。支持 {choices}')


def run(args, raw_args, parser):
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if (flags.count('--daily-message-reply') != 1 or len(set(flags)) != len(flags)
            or set(flags) - {'--daily-message-reply', '--config', '--game-path'}):
        parser.error('短信回复为独立入口，仅可附带 --config 和 --game-path。')

    from .app import Runner
    from .daily_message_reply_flow import supported_selection

    selection = tuple(args.daily_message_reply)
    if not supported_selection(selection):
        parser.error('请选择已校准的短信节点和回复。支持的组合见 --help。')
    try:
        settings = Settings.load(args.config)
        if args.game_path is not None:
            settings.game_path = args.game_path
        runner = Runner(settings, operation=MESSAGE_REPLY_OPERATION, daily_message_reply=selection)
    except (OSError, ValueError, TypeError):
        print(json.dumps({'status': 'failed', 'error': '无法读取本次短信回复配置。'}, ensure_ascii=False))
        return 1

    try:
        report = runner.run()
    except KeyboardInterrupt:
        print(json.dumps(runner.report.to_dict(), ensure_ascii=False, indent=2))
        return 130
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 130 if report.status == 'stopped' else 0 if report.status == 'success' else 1
