"""Explicit task-tree CLI; validation never loads game configuration or inputs."""
import json
from pathlib import Path
import sys

from .task_capabilities import SCREEN_CHECK_PLAN, SCREEN_CHECK_PLAN_VERSION, TaskCapabilities
from .task_workflow import WORKFLOW_PAGES, WorkflowError, compile_recipe, read, workflow_notification_png_path


_TASK_CAPABILITIES = TaskCapabilities(enabled={SCREEN_CHECK_PLAN})


def add_arguments(mode, parser):
    mode.add_argument('--task-workflow', type=Path, help='执行明确选择的任务流程JSON；原生任务门禁和预算继续生效')
    mode.add_argument('--task-workflow-check', type=Path, help='离线检查任务树和最大预算；不读取游戏配置或记录源文件')
    mode.add_argument('--task-workflow-export', type=Path, help='把已保存的任务流JSON及其便携素材导出为ZIP')
    mode.add_argument('--task-workflow-import', type=Path, help='把任务流素材ZIP校验后解包到新目录')
    mode.add_argument('--task-workflow-convert-yaml', type=Path, help='把支持的三月七 YAML 步骤转换成新的任务流 JSON')
    mode.add_argument('--screen-check-plan', nargs='+', choices=WORKFLOW_PAGES,
                      help='离线预览所选页面的顺序和预算，活动页面须放末尾')
    mode.add_argument('--screen-check-pages', nargs='+', choices=WORKFLOW_PAGES,
                      help='从已登录前台按指定顺序导航核对，结果待核对时停止')
    parser.add_argument('--workflow-bundle-destination', type=Path, help='导出的新ZIP路径或导入的新目录')
    parser.add_argument('--workflow-json-destination', type=Path, help='三月七 YAML 转换生成的新 JSON 路径')
    parser.add_argument('--workflow-yaml-native-vision', action='store_true',
                        help='仅用于 --task-workflow-convert-yaml。显式采用 AutoHSR 原生双帧图文规则，默认关闭')
    parser.add_argument('--workflow-yaml-notify-profile',
                        help='仅用于 --task-workflow-convert-yaml。为纯文本通知绑定一个原生方案名称，不授权发送')
    parser.add_argument('--workflow-step-path', help='仅执行指定步骤子树，例如1/0；序号从0开始，不补执行前序步骤')
    parser.add_argument('--workflow-allow-notify', action='store_true',
                        help='授权本次明确选择的任务流程向已保存方案发送主动通知')
    parser.add_argument('--workflow-notify-png', nargs=2, metavar=('PNG', 'SMTP方案'),
                        help='为本次手动任务流明确授权 JSON 中绑定的一份本地 PNG 和已保存的 SMTP 方案')


def validate_arguments(args, parser):
    """Check mode-specific switches before any CLI mode reads its sources."""
    if args.workflow_yaml_native_vision and args.task_workflow_convert_yaml is None:
        parser.error('--workflow-yaml-native-vision 仅用于 --task-workflow-convert-yaml。')
    if args.workflow_yaml_notify_profile is not None and args.task_workflow_convert_yaml is None:
        parser.error('--workflow-yaml-notify-profile 仅用于 --task-workflow-convert-yaml。')
    if args.workflow_notify_png is not None and (args.task_workflow is None or not args.workflow_allow_notify):
        parser.error('--workflow-notify-png 需要 --task-workflow 和 --workflow-allow-notify。')


def _bundle(args, parser, raw_args):
    source = args.task_workflow_export or args.task_workflow_import
    destination = args.workflow_bundle_destination
    if source is None:
        if destination is not None:
            parser.error('--workflow-bundle-destination 仅用于任务流素材包导入或导出。')
        return None
    allowed = {'--task-workflow-export', '--task-workflow-import', '--workflow-bundle-destination'}
    if destination is None:
        parser.error('请用 --workflow-bundle-destination 指定尚不存在的输出路径。')
    if any(arg.partition('=')[0] not in allowed for arg in raw_args if arg.startswith('--')):
        parser.error('任务流素材包不能与其他运行参数混用。')
    from .workflow_bundle import BundleError, export_bundle, import_bundle

    exporting = args.task_workflow_export is not None
    action = export_bundle if exporting else import_bundle
    try:
        path = action(source, destination)
    except KeyboardInterrupt:
        print(json.dumps(dict(status='stopped', error='任务流素材包操作已停止。'), ensure_ascii=False), file=sys.stderr)
        return 130
    except BundleError as error:
        print(json.dumps(dict(status='failed', error=str(error)), ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(dict(status='success', mode='export' if exporting else 'import', path=str(path)),
                     ensure_ascii=False))
    return 0


def _convert_yaml(args, parser, raw_args):
    source = args.task_workflow_convert_yaml
    destination = args.workflow_json_destination
    if source is None:
        if destination is not None:
            parser.error('--workflow-json-destination 仅用于三月七 YAML 转换。')
        return None
    if destination is None:
        parser.error('请用 --workflow-json-destination 指定新的 JSON 文件。')
    provided = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    allowed = {'--task-workflow-convert-yaml', '--workflow-json-destination', '--workflow-yaml-native-vision',
               '--workflow-yaml-notify-profile'}
    if set(provided) - allowed:
        parser.error('三月七 YAML 转换不能与其他运行参数混用。')
    if provided.count('--workflow-yaml-notify-profile') > 1:
        parser.error('三月七 YAML 转换只能绑定一个通知方案。')
    from .workflow_yaml import convert_march7th_yaml

    try:
        saved = convert_march7th_yaml(source, destination, use_native_vision=args.workflow_yaml_native_vision,
                                     notify_profile=args.workflow_yaml_notify_profile)
    except KeyboardInterrupt:
        print(json.dumps(dict(status='stopped', error='YAML 转换已停止。'), ensure_ascii=False), file=sys.stderr)
        return 130
    except (WorkflowError, OSError) as error:
        print(json.dumps(dict(status='failed', error=str(error)), ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(dict(status='success', mode='convert_yaml', path=str(saved.path), sha256=saved.sha256),
                     ensure_ascii=False))
    return 0


def _screen_check(args, parser, raw_args):
    targets = args.screen_check_plan or args.screen_check_pages
    if targets is None:
        return None
    preview = args.screen_check_plan is not None
    flag = '--screen-check-plan' if preview else '--screen-check-pages'
    provided = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    allowed = {flag} if preview else {flag, '--config'}
    if provided.count(flag) != 1 or set(provided) - allowed:
        parser.error('所选页面核对须单独运行，执行时可指定 --config。')

    runner = None
    try:
        if preview:
            data = _TASK_CAPABILITIES.dispatch(SCREEN_CHECK_PLAN, SCREEN_CHECK_PLAN_VERSION, {'pages': targets})
        else:
            from .config import Settings
            from .selected_page_check import build_recipe, saved_result
            from .task_workflow_run import TaskWorkflowRunner

            recipe = build_recipe(targets)
            try:
                settings = Settings.load(args.config)
            except (OSError, TypeError, ValueError):
                raise WorkflowError('所选页面核对无法读取有效的设置文件。') from None
            runner = TaskWorkflowRunner(settings, recipe.document, base_dir=recipe.base_dir)
            data = saved_result(recipe, runner.run().to_dict())
    except KeyboardInterrupt:
        if runner is not None:
            runner.stop()
        data = dict(status='stopped')
    except (WorkflowError, OSError) as error:
        print(json.dumps(dict(status='failed', error=str(error)), ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data['status'] == 'success' else 130 if data['status'] == 'stopped' else 1


def dispatch(args, parser, raw_args):
    yaml_result = _convert_yaml(args, parser, raw_args)
    if yaml_result is not None:
        return yaml_result
    bundle_result = _bundle(args, parser, raw_args)
    if bundle_result is not None:
        return bundle_result
    screen_result = _screen_check(args, parser, raw_args)
    if screen_result is not None:
        return screen_result
    selected = args.task_workflow or args.task_workflow_check
    if selected is None:
        if args.workflow_step_path is not None:
            parser.error('--workflow-step-path 需要 --task-workflow 或 --task-workflow-check。')
        if args.workflow_allow_notify:
            parser.error('--workflow-allow-notify 需要 --task-workflow。')
        return None
    allowed = {'--task-workflow', '--task-workflow-check', '--workflow-step-path'}
    if args.task_workflow is not None:
        allowed.update(('--config', '--notify', '--no-notify', '--notify-profile', '--workflow-allow-notify',
                        '--workflow-notify-png'))
    provided = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if set(provided) - allowed:
        parser.error('任务流程不能混用其他运行或资源覆盖参数；每步参数在流程JSON中明确配置。')
    if provided.count('--workflow-notify-png') > 1:
        parser.error('本次任务流程只能授权一份本地 PNG 和一个 SMTP 方案。')
    runner = None
    try:
        document = read(selected)
        recipe = compile_recipe(document, selected_path=args.workflow_step_path, base_dir=selected.resolve().parent)
        if args.task_workflow_check is not None:
            data = dict(status='success', mode='validation', name=recipe.document['name'],
                        selected_path=list(recipe.path), reservations=recipe.profile, game_accessed=False,
                        configuration_loaded=False, source_files_read=False)
        else:
            from .config import Settings
            from .task_workflow_run import (TaskWorkflowRunner, WorkflowNotificationImage, freeze_step_notifications,
                                            step_notification_aliases, step_notification_images)
            aliases = step_notification_aliases(recipe)
            if aliases and not args.workflow_allow_notify:
                parser.error('任务流程含主动通知。请核对已保存方案后明确使用 --workflow-allow-notify。')
            images = step_notification_images(recipe)
            if images and args.workflow_notify_png is None:
                parser.error('任务流程含图片通知。请明确使用 --workflow-notify-png PNG SMTP方案。')
            if args.workflow_notify_png is not None:
                image, profile = args.workflow_notify_png
                image = Path.cwd() / workflow_notification_png_path(image)
                if images != {(str(image), profile)}:
                    raise WorkflowError('本次授权须与所选步骤中声明的 PNG 路径和 SMTP 方案完全一致。')
            authorization = ({'notification_versions': freeze_step_notifications(recipe)} if aliases else {})
            if images:
                from .reward_guide_notify import freeze_png

                authorization['notification_image'] = WorkflowNotificationImage(profile, freeze_png(image))
            settings = Settings.load(args.config)
            from .notify_cli import override as override_notify
            override_notify(args, settings)
            def emit(event):
                if event.get('type') != 'finished':
                    print(json.dumps(event, ensure_ascii=False, default=str), file=sys.stderr, flush=True)
            from .notify_runtime import hooks
            emit, wrap_notifications = hooks(settings, emit)
            runner = TaskWorkflowRunner(settings, document, emit, selected_path=args.workflow_step_path,
                                        base_dir=recipe.base_dir, **authorization)
            runner = wrap_notifications(runner)
            data = runner.run().to_dict()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0 if data['status'] == 'success' else 130 if data['status'] == 'stopped' else 1
    except KeyboardInterrupt:
        if runner is not None:
            runner.stop()
        code, data = 130, dict(status='stopped', error='已停止任务流程；未重放步骤。')
    except Exception as error:
        code, data = 2, dict(status='failed', error=str(error))
    print(json.dumps(data, ensure_ascii=False), file=sys.stderr)
    return code
