"""Explicit local schedule tools and an opt-in, process-bound controller."""
from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time

from .config import ROOT
from .schedule_plan import CHINA, ScheduleError, preview, read, revision
from .schedule_dispatch import validate_target
from .schedule_store import ScheduleStore

DEFAULT_ROOT = ROOT / 'schedules.local'


def add_arguments(mode, parser):
    mode.add_argument('--schedule-check', type=Path, help='只读检查定时定义和目标结构；不读游戏配置或目标来源，不启用计时')
    mode.add_argument('--schedule-save', type=Path, help='显式保存定时定义的新版本；不会启用计时或登记系统任务')
    mode.add_argument('--schedule-list', action='store_true', help='只读列出已保存计划；读取不启用')
    mode.add_argument('--schedule-preview', help='只读预览已保存计划的未来五次时间，不启用')
    mode.add_argument('--schedule-run', action='append', help='本进程显式启用所选已保存计划并计时；可重复选择，退出即停止')
    parser.add_argument('--schedule-store-dir', type=Path, help='独立计划工具与控制器使用的本地定义/回执目录')
    parser.add_argument('--schedule-replace', action='store_true', help='保存时明确新建替代版本；保留所有旧版本和回执')
    parser.add_argument('--schedule-expected-revision', help='替代版本时核对所读的旧SHA-256，防止覆盖其他编辑')
    parser.add_argument('--schedule-from', help='仅预览使用的含时区ISO时间；不能改变实际运行时钟')
    parser.add_argument('--schedule-limit-seconds', type=float, help='仅控制器使用的本次计时期限，0～86400秒；到期协作停止并等待退出')


def _selected(args):
    return args.schedule_list or any(value is not None for value in
            (args.schedule_check, args.schedule_save, args.schedule_preview, args.schedule_run))


def _public(plan):
    return {name: plan[name] for name in ('id', 'name', 'version', 'time', 'weekdays', 'repeat', 'conflict', 'timeout_seconds')}


def _stop_pressed():
    from .windows import user32
    return bool(user32.GetAsyncKeyState(0x79) & 0x8001)


def _shutdown(controller):
    controller.stop()
    while True:
        try:
            if controller.wait_idle(1):
                return
            print(json.dumps(dict(type='schedule_stopping', waiting_for_owned_runner=True)), file=sys.stderr, flush=True)
        except KeyboardInterrupt:
            controller.stop()


def dispatch(args, parser, raw_args):
    extras = (args.schedule_store_dir is not None or args.schedule_replace or args.schedule_expected_revision is not None
              or args.schedule_from is not None or args.schedule_limit_seconds is not None)
    if not _selected(args):
        if extras:
            parser.error('计划附加参数需要明确的独立计划入口。')
        return None
    allowed = {'--schedule-check', '--schedule-save', '--schedule-list', '--schedule-preview', '--schedule-run',
               '--schedule-store-dir', '--schedule-replace', '--schedule-expected-revision', '--schedule-from',
               '--schedule-limit-seconds'}
    if args.schedule_run is not None:
        allowed.add('--config')
    if any(arg.split('=', 1)[0] not in allowed for arg in raw_args if arg.startswith('--')):
        parser.error('计划工具不能混用游戏、记录、通知或管理员命令；运行设置在所选配置与目标中明确指定。')
    if (args.schedule_replace or args.schedule_expected_revision is not None) and args.schedule_save is None:
        parser.error('替代版本和旧版本核对仅用于显式保存计划。')
    if args.schedule_expected_revision is not None and not args.schedule_replace:
        parser.error('旧版本核对需要明确选择替代版本。')
    if args.schedule_from is not None and args.schedule_preview is None:
        parser.error('指定参考时间仅用于只读预览。')
    if args.schedule_limit_seconds is not None and args.schedule_run is None:
        parser.error('计时期限仅用于显式运行控制器。')
    controller, shutdown_done = None, False
    try:
        store = ScheduleStore(args.schedule_store_dir or DEFAULT_ROOT)
        if args.schedule_check is not None or args.schedule_save is not None:
            plan = read(args.schedule_check or args.schedule_save)
            validate_target(plan['target'])
            if args.schedule_check is not None:
                data = dict(status='success', mode='schedule_validation', plan=_public(plan), revision=revision(plan),
                            enabled=False, configuration_loaded=False, target_sources_read=False, game_accessed=False)
            else:
                result = store.save(plan, replace=args.schedule_replace, expected_revision=args.schedule_expected_revision)
                data = dict(status='success', id=result['plan']['id'], revision=result['revision'], enabled=False,
                            system_tasks_registered=False, configuration_loaded=False, game_accessed=False)
        elif args.schedule_list:
            data = dict(status='success', plans=store.list_public(), system_tasks_registered=False, game_accessed=False)
        elif args.schedule_preview is not None:
            plan, _ = store.load(args.schedule_preview)
            now = datetime.fromisoformat(args.schedule_from) if args.schedule_from is not None else datetime.now(CHINA)
            data = dict(status='success', **preview(plan, now), enabled=False, game_accessed=False)
        else:
            names = args.schedule_run
            if not names or len(names) > 32 or len(set(names)) != len(names):
                raise ScheduleError('本次须选择1～32个不重复计划。')
            limit = args.schedule_limit_seconds
            if limit is not None and (not math.isfinite(limit) or not 0 <= limit <= 86400):
                raise ScheduleError('本次计时期限须为0～86400秒的有限数值。')
            from .config import Settings
            from .schedule_dispatch import NativeScheduleExecutor
            from .schedule_runtime import Scheduler
            settings = Settings.load(args.config)
            def emit(event):
                print(json.dumps(event, ensure_ascii=False, allow_nan=False), file=sys.stderr, flush=True)
            controller = Scheduler(store, NativeScheduleExecutor(settings), emit=emit)
            for name in names:
                controller.enable(name)
            controller.start()
            started = time.monotonic()
            reason = 'controller_stopped'
            while controller.snapshot()['running']:
                if limit is not None and time.monotonic() - started >= limit:
                    reason = 'monitor_limit'
                    break
                if _stop_pressed():
                    reason = 'user_stop'
                    break
                controller.tick()
                time.sleep(.2)
            _shutdown(controller)
            shutdown_done = True
            data = dict(status='stopped', mode='schedule_controller', reason=reason, snapshot=controller.snapshot())
        print(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except KeyboardInterrupt:
        code, data = 130, dict(status='stopped', error='已停止计时并等待本控制器的任务释放；未重放触发。')
    except ScheduleError as error:
        code, data = 2, dict(status='failed', error=str(error))
    except Exception:
        code, data = 2, dict(status='failed', error='计划定义、冻结目标或执行状态未核实；未输出私人数据。')
    finally:
        if controller is not None and not shutdown_done:
            _shutdown(controller)
    print(json.dumps(data, ensure_ascii=False), file=sys.stderr)
    return code
