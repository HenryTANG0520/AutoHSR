"""Explicit standalone DU reward scope; no config or game access here."""


def add_arguments(mode, parser):
    mode.add_argument('--du-rewards-only', action='store_true',
        help='独立领取已打开差分主页的拟合／稳态／画廊已有红点奖励；不演算、不刷本，默认不使用月下卡带')
    parser.add_argument('--du-use-cassettes', action='store_true',
        help='仅配合--du-rewards-only，允许每次100已有月下卡带；以本次首次核实余额为上限，不保存设置')


def validate_arguments(args, parser, raw_args):
    if args.du_use_cassettes and not args.du_rewards_only:
        parser.error('--du-use-cassettes仅用于--du-rewards-only，不改变普通演算的领奖设置。')
    if not args.du_rewards_only:
        return
    allowed = {'--du-rewards-only', '--du-use-cassettes', '--config', '--game-path',
               '--notify', '--no-notify', '--notify-profile'}
    if any(token.startswith('--') and token.split('=')[0] not in allowed for token in raw_args):
        parser.error('差分独立领奖不能混入演算、日常、资源、新预算或其他玩法选项。')
