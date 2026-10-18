"""Bounded read-only acceptance window, using the normal cancellation path."""
import time
from .currency_wars import CurrencyWarsWorkflow, TASK
from .models import TaskResult


def inspect_controls(context):
    runner = context.runner
    if runner.report.operation != 'currency_wars':
        raise ValueError('控制验收不允许玩法输入。')
    start, inactive = time.monotonic(), runner.inactive_duration
    count = 0
    runner.log('只读控制验收：两次真实截图后分别进入暂停检查点；F9继续，F10停止。最多30秒活动时间，不发送游戏输入。')
    try:
        while count < 2 and time.monotonic() - start - (runner.inactive_duration - inactive) < 30:
            runner._resume_step(CurrencyWarsWorkflow(context).inspect, TASK)
            count += 1
            runner.log(f'只读验收检查点{count}：已采集真实画面，主动调用正常暂停路径，等待F9继续或F10停止。')
            runner.toggle_pause()
            context.checkpoint()
        return TaskResult(TASK, 'partial', '只读控制检查点验收已结束，未发送游戏输入。')
    finally:
        data = runner.report.currency_wars or {}
        data['control_probe'] = dict(observations=count, input_epoch=runner.input_epoch,
                                     inactive_seconds=runner.inactive_duration-inactive,
                                     wall_seconds=time.monotonic()-start, maximum_active_seconds=30,
                                     gameplay_inputs_allowed=False)
        runner.report.currency_wars = data
