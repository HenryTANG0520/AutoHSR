"""Explicit profile management/test actions; no implicit network configuration."""
from pathlib import Path
import argparse
import json
import sys
import uuid

from .notify_profiles import MAX_BYTES, PROVIDERS, NotifyError, ProfileStore, loads


def add_arguments(mode, parser):
    mode.add_argument('--notify-providers', action='store_true', help='列出通知文本渠道及当前边界；不读取凭据或发送')
    mode.add_argument('--notify-profile-list', action='store_true', help='列出本地已保存通知配置的名称和渠道；不输出凭据')
    mode.add_argument('--notify-profile-import', type=Path, help='显式导入通知JSON并用当前Windows用户DPAPI保存；保留输入原件，不发送')
    mode.add_argument('--notify-profile-check', help='只读核对一个已保存通知配置；不发送或验证远端凭据有效性')
    mode.add_argument('--notify-test', help='显式向指定配置发送一条AutoHSR测试通知')
    parser.add_argument('--notify-replace-profile', action='store_true', help='仅用于导入时明确替换已有配置，保留原加密备份')
    parser.add_argument('--notify-store-dir', type=Path, help='通知工具的明确本地配置目录；不用于游戏运行入口')
    parser.add_argument('--notify', action=argparse.BooleanOptionalAction, default=None,
                        help='本次启用或关闭运行结束通知，不保存设置')
    parser.add_argument('--notify-profile', action='append', help='本次明确选择通知配置，可重复指定；同时启用本次通知')


def override(args, settings):
    if args.notify is not None:
        settings.notification_enabled = args.notify
    if args.notify_profile is not None:
        if args.notify is False:
            raise NotifyError('选择通知配置不能同时关闭本次通知。')
        settings.notification_profiles = list(args.notify_profile)
        settings.notification_enabled = True


def dispatch(args, parser, raw_args):
    selected = args.notify_providers or args.notify_profile_list or any(value is not None for value in
               (args.notify_profile_import, args.notify_profile_check, args.notify_test))
    if not selected:
        if args.notify_store_dir is not None or args.notify_replace_profile:
            parser.error('通知目录和替换选项仅用于独立通知工具。')
        return None
    allowed = {'--notify-providers', '--notify-profile-list', '--notify-profile-import',
               '--notify-profile-check', '--notify-test', '--notify-store-dir', '--notify-replace-profile'}
    if any(arg.split('=', 1)[0] not in allowed for arg in raw_args if arg.startswith('--')):
        parser.error('通知工具不能混用游戏、记录、管理员或运行设置选项。')
    if args.notify_replace_profile and args.notify_profile_import is None:
        parser.error('替换通知配置仅用于显式导入。')
    try:
        if args.notify_providers:
            data = dict(status='success', providers=list(PROVIDERS), text_only=True, network_accessed=False)
        else:
            store = ProfileStore(args.notify_store_dir)
            if args.notify_profile_list:
                data = dict(status='success', profiles=store.list_public(), network_accessed=False)
            elif args.notify_profile_import is not None:
                with args.notify_profile_import.open('rb') as stream:
                    value = loads(stream.read(MAX_BYTES + 1))
                data = dict(status='success', **store.save(value, replace=args.notify_replace_profile), network_accessed=False)
            elif args.notify_profile_check is not None:
                value = store.load_private(args.notify_profile_check)
                data = dict(status='success', id=value['id'], provider=value['provider'], network_accessed=False,
                            remote_credentials_verified=False)
            else:
                from .notify_runtime import NotificationService
                service = NotificationService(root=args.notify_store_dir)
                frozen = service.store.load_version(args.notify_test)
                data = service.deliver(frozen, 'AutoHSR 通知测试', '这是用户明确请求的通知测试，不代表游戏任务已执行。',
                                       'explicit-test-' + uuid.uuid4().hex)
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if data['status'] in ('success', 'accepted') else 1
    except KeyboardInterrupt:
        data, code = dict(status='cancelled', error='通知操作已停止；未自动重试。'), 130
    except NotifyError as error:
        data, code = dict(status='failed', error=str(error)), 2
    except Exception:
        data, code = dict(status='failed', error='通知配置或发送未核实；凭据及服务端原文不输出。'), 2
    print(json.dumps(data, ensure_ascii=False), file=sys.stderr)
    return code
