"""Explicit task-tree CLI; validation never loads game configuration or inputs."""
import json
from pathlib import Path
import sys

from .task_workflow import compile_recipe, read


def add_arguments(mode, parser):
    mode.add_argument('--task-workflow', type=Path, help='执行明确选择的任务流程JSON；原生任务门禁和预算继续生效')
    mode.add_argument('--task-workflow-check', type=Path, help='离线检查任务树和最大预算；不读取游戏配置或记录源文件')
    parser.add_argument('--workflow-step-path', help='仅执行指定步骤子树，例如1/0；序号从0开始，不补执行前序步骤')


def dispatch(args, parser, raw_args):
    selected = args.task_workflow or args.task_workflow_check
    if selected is None:
        if args.workflow_step_path is not None:
            parser.error('--workflow-step-path 需要 --task-workflow 或 --task-workflow-check。')
        return None
    allowed = {'--task-workflow', '--task-workflow-check', '--workflow-step-path'}
    if args.task_workflow is not None:
        allowed.update(('--config', '--notify', '--no-notify', '--notify-profile'))
    if any(arg.split('=', 1)[0] not in allowed for arg in raw_args if arg.startswith('--')):
        parser.error('任务流程不能混用其他运行或资源覆盖参数；每步参数在流程JSON中明确配置。')
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
            from .task_workflow_run import TaskWorkflowRunner
            settings = Settings.load(args.config)
            from .notify_cli import override as override_notify
            override_notify(args, settings)
            def emit(event):
                if event.get('type') != 'finished':
                    print(json.dumps(event, ensure_ascii=False, default=str), file=sys.stderr, flush=True)
            from .notify_runtime import hooks
            emit, wrap_notifications = hooks(settings, emit)
            runner = TaskWorkflowRunner(settings, document, emit, selected_path=args.workflow_step_path,
                                        base_dir=selected.resolve().parent)
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
