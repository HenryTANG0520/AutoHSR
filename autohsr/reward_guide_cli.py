"""Explicit reward guide PNG export and SMTP attachment actions."""

import json
from pathlib import Path


_NOTIFY_IMAGE = '--reward-guide-notify'
_NOTIFY_PROFILE = '--reward-guide-notify-profile'
_CAPTURE = '--reward-guide-capture'


def add_capture_argument(mode):
    mode.add_argument(_CAPTURE, type=Path, metavar='NEW_PNG',
                      help='从已在前台的奖励指南核对当前列表并导出一张新 PNG')


def run_capture(args, raw_args, parser):
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if (flags.count(_CAPTURE) != 1 or len(flags) != len(set(flags))
            or set(flags) - {_CAPTURE, '--config', '--game-path'}):
        parser.error('奖励指南单屏导出为独立入口，仅可附带 --config 和 --game-path。')

    from .config import Settings
    from .reward_guide_capture import RewardGuideCapture, _receipt, capture_reward_guide
    from .reward_guide_export import _Rejected

    try:
        capture = RewardGuideCapture(args.reward_guide_capture)
        settings = Settings.load(args.config)
        if args.game_path is not None:
            settings.game_path = args.game_path
    except _Rejected as error:
        receipt = _receipt(str(error))
    except KeyboardInterrupt:
        receipt = _receipt('stopped')
    except (OSError, ValueError, TypeError):
        receipt = _receipt('invalid_config')
    else:
        try:
            receipt = capture_reward_guide(settings, capture)
        except KeyboardInterrupt:
            receipt = capture.receipt or _receipt('stopped')
        except (OSError, RuntimeError, ValueError):
            receipt = capture.receipt or _receipt('unverified')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if receipt['status'] in ('stopped', 'publish_unverified'):
        return 130
    return 0 if receipt['status'] == 'ok' else 1


def add_notification_arguments(mode, parser):
    mode.add_argument(_NOTIFY_IMAGE, type=Path, metavar='PNG',
                      help='明确发送一份本地奖励指南 PNG，使用已保存的 SMTP 配置')
    parser.add_argument(_NOTIFY_PROFILE, metavar='ALIAS',
                        help='配合 --reward-guide-notify 指定一个已保存的加密 SMTP 配置名称')


def run_notification(args, raw_args, parser):
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if (len(flags) != 2 or set(flags) != {_NOTIFY_IMAGE, _NOTIFY_PROFILE}
            or args.reward_guide_notify is None or args.reward_guide_notify_profile is None):
        parser.error('请只指定 --reward-guide-notify PNG 和 --reward-guide-notify-profile ALIAS。')

    interrupted = False
    try:
        from .reward_guide_notify import send_reward_guide

        result = send_reward_guide(args.reward_guide_notify, args.reward_guide_notify_profile)
        receipt = {key: result[key] for key in ('status', 'reason', 'reused')}
    except (KeyboardInterrupt, Exception) as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        receipt = dict(status='unknown', reason='delivery_unknown', reused=False)

    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    if interrupted or receipt['status'] == 'cancelled':
        return 130
    return 0 if receipt['status'] == 'accepted' else 1


def run(args, raw_args, parser):
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if (len(flags) != 2 or set(flags) != {'--reward-guide-stitch', '--reward-guide-output'}
            or args.reward_guide_stitch is None or args.reward_guide_output is None):
        parser.error('请只指定 --reward-guide-stitch PNG … 和 --reward-guide-output NEW_PNG。')

    from .reward_guide_export import export_reward_guide

    receipt = export_reward_guide(args.reward_guide_stitch, args.reward_guide_output)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt['status'] == 'ok' else 1
