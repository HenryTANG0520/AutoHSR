"""Explicit high-difficulty preparation and a file-only plan preview."""
import json
from pathlib import Path
import sys


def read_plan(path):
    from .challenge_plan import ChallengePlan
    from .currency_wars_state import strict_json
    with Path(path).open('rb') as stream:
        raw = stream.read(64 * 1024 + 1)
    if len(raw) > 64 * 1024:
        raise ValueError('高难计划超过64 KiB。')
    return ChallengePlan.from_dict(strict_json(raw.decode('utf-8-sig')))


def add_arguments(mode, parser):
    mode.add_argument('--challenge-check', type=Path, help='离线核对高难双队与层数计划；不访问游戏或保存配置')
    mode.add_argument('--challenge-prepare', action='store_true', help='从已打开的混沌主页核实并进入首个目标层备战；不选角、开战或领奖')
    parser.add_argument('--challenge-plan', type=Path, help='仅用于本次高难备战的明确双队JSON计划；不保存配置')


def dispatch(args, parser, raw_args):
    if args.challenge_check is not None:
        if any(token.startswith('--') and token.split('=')[0] != '--challenge-check' for token in raw_args):
            parser.error('高难计划预览只读取指定计划，不接受配置或运行选项。')
        try:
            plan = read_plan(args.challenge_check)
            print(json.dumps(dict(plan=plan.to_dict(), plan_digest=plan.digest, game_accessed=False),
                             ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError) as error:
            print(json.dumps(dict(error=str(error), game_accessed=False), ensure_ascii=False), file=sys.stderr)
            return 2
    if args.challenge_plan is not None and not args.challenge_prepare:
        parser.error('--challenge-plan仅用于明确的--challenge-prepare入口。')
    if args.challenge_prepare:
        allowed = {'--challenge-prepare', '--challenge-plan', '--config', '--game-path',
                   '--notify', '--no-notify', '--notify-profile'}
        if any(token.startswith('--') and token.split('=')[0] not in allowed for token in raw_args):
            parser.error('高难备战不能混入日常、资源、其他玩法或接续选项。')
    return None


def apply_overrides(args, settings):
    if args.challenge_plan is not None:
        settings.challenge_plan = read_plan(args.challenge_plan).to_dict()


def validate_settings(settings, *, requested=False):
    from .challenge_plan import ChallengePlan
    from .config import SettingsError
    value = settings.challenge_plan
    if type(value) is not dict:
        raise SettingsError('challenge_plan', '高难计划必须为对象；未配置时使用空对象。')
    if not value and not requested:
        return None
    try:
        plan = ChallengePlan.from_dict(value)
    except ValueError as error:
        raise SettingsError('challenge_plan', str(error)) from error
    if requested and plan.mode != 'memory_of_chaos':
        raise SettingsError('challenge_plan', '当前原生备战仅接混沌回忆，虚构叙事与末日幻影执行仍待适配。')
    return plan
