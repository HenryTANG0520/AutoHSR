"""Read-only catalog tools and explicit, non-persistent run overrides."""
import argparse
import json
import sys
from pathlib import Path


def add_arguments(mode, parser):
    mode.add_argument('--redeem-codes', action='store_true', help='独立处理兑换码批次；不刷本、不保存本次配置')
    mode.add_argument('--redemption-check', type=Path, help='离线核对本地兑换码表与有效期；不访问游戏或联网')
    mode.add_argument('--redemption-fetch', action='store_true', help='显式联网预览当前码表；不兑换、不写配置')
    parser.add_argument('--redemption-server', choices=('cn', 'global'), help='兑换码服务器；预览工具须显式选择')
    parser.add_argument('--redemption-source', choices=('online', 'manual', 'file'), help='本次兑换码来源')
    parser.add_argument('--redemption-code', action='append', help='手动兑换码，可重复；保留原字符串与大小写')
    parser.add_argument('--redemption-catalog', type=Path, help='本次本地兑换码表')
    parser.add_argument('--with-redemption', action=argparse.BooleanOptionalAction, default=None, help='仅覆盖本次日常的兑换码开关')
    parser.add_argument('--redemption-mail', action=argparse.BooleanOptionalAction, default=None, help='成功兑换后核对免费邮件附件')


def dispatch(args, parser, raw_args):
    if args.redemption_check is None and not args.redemption_fetch:
        return None
    allowed = {'--redemption-check', '--redemption-fetch', '--redemption-server'}
    if any(token.startswith('--') and token.split('=')[0] not in allowed for token in raw_args):
        parser.error('兑换码预览仅接受明确来源及服务器，不加载运行、通知或每日配置。')
    if args.redemption_server is None:
        parser.error('兑换码预览须明确 --redemption-server cn 或 global。')
    try:
        from .redemption_codes import from_file, fetch_catalog
        batch = (from_file(args.redemption_check, args.redemption_server) if args.redemption_check is not None
                 else fetch_catalog(args.redemption_server))
        # This explicit preview exposes public codes to their owner. Runner
        # events use counts only; no account data exists in either tool.
        print(json.dumps(dict(server=batch.server, codes=list(batch.codes), skipped=list(batch.skipped),
                              source=batch.source, game_accessed=False), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps(dict(error=str(error), game_accessed=False), ensure_ascii=False), file=sys.stderr)
        return 2


def apply_overrides(args, parser, settings):
    values = any(getattr(args, key) is not None for key in ('redemption_server', 'redemption_source',
        'redemption_code', 'redemption_catalog', 'with_redemption', 'redemption_mail'))
    if values and not (args.redeem_codes or (args.run or args.plan) and not args.reward_only and not args.resume_weekly_currency):
        parser.error('兑换码选项只用于独立 --redeem-codes 或本次 --run/--plan 日常。')
    if args.redeem_codes and args.with_redemption is False:
        parser.error('独立兑换不能与关闭兑换开关混用。')
    if args.redemption_code is not None and args.redemption_catalog is not None:
        parser.error('手动兑换码与本地码表须分别选择来源。')
    if args.redeem_codes:
        settings.redemption_enabled = True
    if args.with_redemption is not None:
        settings.redemption_enabled = args.with_redemption
    for name in ('redemption_server', 'redemption_source', 'redemption_mail'):
        value = getattr(args, name)
        if value is not None:
            setattr(settings, 'redemption_claim_mail' if name == 'redemption_mail' else name, value)
    if args.redemption_code is not None:
        if args.redemption_source not in (None, 'manual'):
            parser.error('手动兑换码需要manual来源。')
        settings.redemption_source, settings.redemption_codes = 'manual', list(args.redemption_code)
    if args.redemption_catalog is not None:
        if args.redemption_source not in (None, 'file'):
            parser.error('本地码表需要file来源。')
        settings.redemption_source, settings.redemption_catalog = 'file', str(args.redemption_catalog.resolve())
    if values and not settings.redemption_enabled:
        if any(getattr(args, key) is not None for key in ('redemption_code', 'redemption_catalog', 'redemption_source', 'redemption_server', 'redemption_mail')):
            parser.error('本次兑换码参数需要明确启用 --with-redemption 或 --redeem-codes。')
