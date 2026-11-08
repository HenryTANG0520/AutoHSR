"""The daily-training search adapter for the authorized single-item craft."""

from .daily_synthesis import RECIPE, task_target


def synthesis_target(pair, view):
    first, second = (task_target(frame.scene) for frame in pair)
    if (first is not None and second is not None
            and all(abs(a - b) <= .006 for a, b in zip(first.box, second.box))
            and any(card['task'] == 'synthesis' and card['state'] == 'pending'
                    and abs(center - second.center[0]) <= .035
                    for card, center in zip(view.cards, view.centers))):
        return 'synthesis'
    return None


def run_independent(workflow, scene):
    from .daily_synthesis import complete_once
    from .daily_training_search import search_task
    from .task_workflow import TRAINING_SYNTHESIS_TASK

    report = workflow.ctx.report
    if not workflow._tab(scene, '每日实训'):
        return workflow._result(TRAINING_SYNTHESIS_TASK, 'partial', '请打开已登录账号的每日实训页。', scene)
    activity = workflow._activity(scene)
    report.engagement = activity
    receipt = dict(state='unverified', scrolls=[])
    report.training_synthesis_search = receipt
    scene, found = search_task(workflow, scene, activity, lambda pair, view, _: synthesis_target(pair, view),
                              receipt, inspect_current=True)
    if found != 'synthesis':
        return workflow._result(TRAINING_SYNTHESIS_TASK, 'partial', '当前实训的单件合成任务待核实。', scene)
    complete_once(workflow, scene)
    if synthesis_receipt(report.daily_synthesis) is None:
        return workflow._result(TRAINING_SYNTHESIS_TASK, 'partial', '奇巧零食和两种材料的变动待核实。')
    return workflow._result(TRAINING_SYNTHESIS_TASK, 'ok', '已核实合成一个奇巧零食及两种材料各减少一个。')


def synthesis_receipt(record):
    if (not isinstance(record, dict) or record.get('status') != 'complete'
            or record.get('task_verified') is not True or record.get('recipe') != RECIPE
            or type(record.get('quantity')) is not int or record['quantity'] != 1):
        return None
    before, after = record.get('before_holding'), record.get('after_holding')
    costs, balances = record.get('before_materials'), record.get('after_materials')
    if (type(before) is not int or before < 0 or type(after) is not int or after != before + 1
            or not isinstance(costs, (list, tuple)) or not isinstance(balances, (list, tuple))
            or len(costs) != 2 or len(balances) != 2):
        return None
    for original, current in zip(costs, balances):
        if (not isinstance(original, (list, tuple)) or not isinstance(current, (list, tuple))
                or len(original) != 2 or len(current) != 2
                or any(type(value) is not int for value in (*original, *current))
                or original[0] < 1 or original[1] != 1 or current[0] != original[0] - 1 or current[1] != 1):
            return None
    return dict(recipe=RECIPE, quantity=1, material_units=[1, 1])
