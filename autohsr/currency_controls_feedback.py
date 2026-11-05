"""Pure, anonymous presentation for native loop/points/reward controls.

Only typed public facts are projected. Journals, PNGs and private evidence are
not re-read here; detailed errors remain in the GUI's existing error view.
"""
from datetime import date


OPERATIONS = ('currency_wars_loop', 'currency_wars_points', 'currency_wars_rewards')
_LOOP_STATES = ('active', 'complete', 'cancelled', 'exhausted', 'expired', 'defeated')
_REWARD_PHASES = ('lobby', 'panel', 'overlay', 'panel_after_claim', 'panel_settled', 'returned', 'blocked')
_REWARD_INTENTS = ('open_points_rewards', 'claim_weekly_rewards', 'dismiss_weekly_rewards', 'return_weekly_lobby')
_REWARD_RESULTS = dict(open_points_rewards='points_rewards', claim_weekly_rewards='reward_overlay',
                       dismiss_weekly_rewards='points_rewards', return_weekly_lobby='lobby')


def _number(value):
    return type(value) is int and value >= 0


def _week(value):
    if type(value) is not str:
        return False
    try:
        day = date.fromisoformat(value)
        return day.isoformat() == value and day.weekday() == 0
    except ValueError:
        return False


def _counts(data):
    if type(data) is not dict or data.get('mode') != 'standard_loop':
        return None
    total, wins, losses = (data.get(key) for key in ('completed', 'victories', 'defeats'))
    if (not all(_number(value) for value in (total, wins, losses)) or wins + losses != total
            or type(data.get('settled_games')) is not int or data['settled_games'] != total):
        return None
    requested = data.get('requested_runs')
    if (not _number(requested) or requested > 2147483647 or requested and total > requested):
        return None
    return total, wins, losses, requested


def _scope(data):
    return (data.get('development_only') is True and type(data.get('acceptance_runs')) is int
            and data['acceptance_runs'] == 0)


def _score(data, *, summary=False):
    if type(data) is not dict:
        return None
    current, limit = data.get('current'), data.get('limit')
    if not _number(current) or limit != 18000 or type(limit) is not int or current > limit:
        return None
    if summary:
        period = data.get('period_verified')
    else:
        period_data = data.get('period')
        period = period_data.get('verified') if type(period_data) is dict else None
    full, target = data.get('score_complete'), data.get('weekly_target_verified')
    if (type(period) is not bool or type(full) is not bool or type(target) is not bool
            or full is not (current == limit) or target is not (full and period)):
        return None
    return current, limit, period, target


def _goal(data, completed):
    goal = data.get('points_goal')
    if type(goal) is not dict or not _week(goal.get('week')):
        return None
    observation = goal.get('observation')
    if observation is None:
        if goal.get('checked_completed') is None and goal.get('latest') is None:
            return dict(week=goal['week'], score=None, current=False, matched=False, target=False)
        return None
    score = _score(observation, summary=True)
    checked = goal.get('checked_completed')
    if (score is None or not _number(checked) or checked > completed or type(goal.get('latest')) is not dict
            or not _week(observation.get('game_week'))):
        return None
    matched = observation['game_week'] == goal['week']
    current = checked == completed
    return dict(week=goal['week'], score=score, current=current, matched=matched,
                target=score[3] and current and matched)


def _count_text(counts):
    total, wins, losses, _ = counts
    return f'已结束开发局 {total} 局 · 胜 {wins}／负 {losses}'


def _parent(title, report, *, verified=False):
    state = report.get('status')
    if state in ('stopped', 'cancelled'):
        return title + ' · 后续已停止' if verified else title + ' · 已停止'
    if state == 'failed':
        return title + ' · 后续失败' if verified else title + ' · 失败'
    if report.get('report_saved') is not True:
        return title + ' · 报告待核对'
    return title


def _loop(report, data):
    counts = _counts(data)
    if counts is None:
        return _parent('货币循环结果待核对', report), ['开发结束局数、胜败或请求上限尚未核实。', '本次结果不计独立验收。']
    total, wins, losses, requested = counts
    lines = [_count_text(counts), '请求上限：0（直到停止）。' if requested == 0 else f'请求上限：{requested} 局。']
    scope = _scope(data)
    lines.append('开发结果不计独立验收 · 独立验收 0 局。' if scope else '独立验收计数待核对，本次结果不作为独立验收。')
    until = data.get('until_points', False)
    nested = data.get('status')
    valid = scope and type(until) is bool and nested in _LOOP_STATES and (data.get('active') is None or type(data.get('active')) is dict)
    goal = _goal(data, total) if until is True else None
    if until is True and goal is None:
        valid = False
    title, verified = '货币循环未完成', False
    if until is True:
        lines.append('目标：本周积分达标后停止。')
        if goal is None:
            lines.append('原周目标或积分记录待核对。')
        else:
            lines.append('原目标游戏周：' + goal['week'] + '。')
            score = goal['score']
            if score is None:
                lines.append('尚无已核实的积分观察。')
            else:
                lines.append(f'最近记录积分：{score[0]}/{score[1]}。')
                if not goal['matched']:
                    lines.append('积分记录不属原目标游戏周。')
                elif not goal['current']:
                    lines.append('最新结束局后的积分尚待核对。')
                elif not score[2]:
                    lines.append('游戏周倒计时未核实，积分目标待核对。')
        if nested == 'complete':
            verified = valid and goal is not None and goal['target'] and data.get('active') is None
            title = '本周积分目标已达标' if verified else '积分目标结果待核对'
        elif nested == 'exhausted':
            valid = (valid and requested > 0 and total == requested and data.get('active') is None
                     and goal is not None and goal['score'] is not None and goal['current']
                     and goal['matched'] and goal['score'][2] and not goal['target'])
            title = '局数上限已用完' if valid else '循环结果待核对'
            lines.append('没有追加开发局；积分目标仍未完成。' if valid else '已结束局数保留；积分目标尚待核对。')
        elif nested == 'expired':
            title = '原周积分目标已过期' if valid else '循环结果待核对'
            lines.append('已跨游戏周，原目标没有自动迁移或追加新局。')
    elif until is False:
        if data.get('points_goal') is not None:
            valid = False
        if nested == 'complete':
            verified = valid and requested > 0 and total == requested and data.get('active') is None
            title = ('指定开发局数已结算' + ('（含败局）' if losses else '')) if verified else '循环完成情况待核对'
        elif nested in ('exhausted', 'expired'):
            valid = False
    if nested == 'defeated':
        valid = valid and losses > 0 and data.get('continue_after_defeat', False) is False and data.get('active') is None
        title = '败局结算后已停止' if valid else '循环结果待核对'
        lines.append('败局保留在已结束局数中，未算作胜利。')
    elif nested == 'cancelled':
        title = '货币循环已取消'
    if data.get('active') is not None:
        lines.append('当前开发局尚未完整核实结算，未计入已结束局数。')
    if not valid:
        title = '货币循环结果待核对'
        verified = False
    lines.append('积分达标与积分奖励领取分开；本循环未核实领奖。')
    return _parent(title, report, verified=verified), lines


def _points(report, data):
    score = _score(data)
    valid = (data.get('schema') == 1 and type(data.get('schema')) is int and data.get('mode') == 'weekly_points'
             and data.get('points_verified') is True and data.get('rewards_verified') is False
             and data.get('completion_verified') is False and data.get('match_started') is False
             and score is not None and _week(data.get('game_week')))
    lines = []
    if valid:
        lines.append(f'记录积分：{score[0]}/{score[1]}。')
        lines.append('观察游戏周：' + data['game_week'] + '。')
        title = ('本周积分已达标' if score[3] else '显示满分，游戏周待核对'
                 if score[0] == score[1] else '本周积分尚未达标')
        if not score[2]:lines.append('游戏周倒计时未核实。')
        if report.get('report_saved') is not True:title = '积分观察待核对'
    else:
        title = '积分观察待核对'
        lines.append('当前积分或游戏周观察尚未完整核实。')
    lines.extend(('积分观察不证明奖励已领取。', '本次不增加开发对局或独立验收计数。'))
    return _parent(title, report, verified=valid and report.get('report_saved') is True), lines


def _rewards(report, data):
    current, phase = data.get('current'), data.get('phase')
    actions = data.get('actions')
    recovery = data.get('limit_recovery')
    valid = (type(data.get('schema')) is int and data['schema'] == 1 and data.get('mode') == 'weekly_rewards'
             and data.get('status') in ('active', 'complete') and phase in _REWARD_PHASES
             and _number(current) and current <= 18000 and _week(data.get('game_week'))
             and data.get('completion_verified') is False and data.get('match_started') is False
             and all(type(data.get(key)) is bool for key in ('rewards_verified', 'weekly_rewards_verified', 'claimed_now'))
             and type(actions) is list and len(actions) <= (5 if 'limit_recovery' in data else 4))
    if valid:
        valid = data['weekly_rewards_verified'] is (data['rewards_verified'] and current == 18000)
        for index, action in enumerate(actions):
            if (type(action) is not dict or type(action.get('id')) is not int or action['id'] != index
                    or action.get('intent') not in _REWARD_INTENTS or action.get('status') not in ('pending', 'unknown', 'verified')):
                valid = False
                break
            if action['status'] == 'verified':
                expected = _REWARD_RESULTS[action['intent']]
                if action.get('result') != expected and not (action['intent'] == 'claim_weekly_rewards' and action.get('result') == 'fuel_ticket_limit'):
                    valid = False
                    break
    if valid and 'limit_recovery' in data:
        valid = (type(recovery) is dict and type(recovery.get('blocked_id')) is int
                 and recovery['blocked_id'] == 1 and recovery.get('panel_state') in ('available', 'settled')
                 and _number(recovery.get('epoch')) and type(recovery.get('sources')) is list
                 and len(recovery['sources']) == 2 and len(actions) >= 2
                 and actions[1]['intent'] == 'claim_weekly_rewards' and actions[1]['status'] == 'verified'
                 and actions[1].get('result') == 'fuel_ticket_limit'
                 and all(type(source) is dict and source.get('page') == 'points_rewards'
                         and source.get('panel_state') == recovery['panel_state']
                         and source.get('current') == current and source.get('input_epoch') == recovery['epoch']
                         for source in recovery['sources']))
    complete = (valid and data['status'] == 'complete' and phase == 'returned' and data['rewards_verified'] is True
                and bool(actions) and actions[-1]['intent'] == 'return_weekly_lobby'
                and all(action['status'] == 'verified' and action.get('result') == (
                    'fuel_ticket_limit' if recovery is not None and action['id'] == 1 else _REWARD_RESULTS[action['intent']])
                    for action in actions))
    if complete:
        expected = list(_REWARD_INTENTS) if data['claimed_now'] else ['open_points_rewards', 'return_weekly_lobby']
        if recovery is not None:
            expected.insert(1, 'claim_weekly_rewards')
        complete = [action['intent'] for action in actions] == expected
        if complete and recovery is not None and data['claimed_now']:
            complete = recovery['panel_state'] == 'available'
    verified = complete and report.get('report_saved') is True
    lines = []
    if valid:
        lines.append(f'记录积分：{current}/18000。')
        if verified:
            lines.append('本次领取与主页返回已核实。' if data['claimed_now'] else '当前无可领取积分奖励已核实，已返回主页。')
            lines.append('周积分及可领取奖励状态已核实。' if data['weekly_rewards_verified'] else '当前可领取奖励状态已核实，周积分尚未满额。')
        elif data['claimed_now'] is True and any(action['intent'] == 'claim_weekly_rewards' and action['status'] == 'verified'
                                               and action.get('result') == 'reward_overlay' for action in actions):
            lines.append('已记录本次到账展示；完整领奖与返回仍待核对。')
    if verified:
        title = '积分领奖已核实'
    elif (valid and phase == 'blocked' and actions and actions[-1]['intent'] == 'claim_weekly_rewards'
          and actions[-1].get('result') == 'fuel_ticket_limit' and data['claimed_now'] is False
          and data['rewards_verified'] is False and data['status'] == 'active'
          and all(action['status'] == 'verified' for action in actions)):
        title = '助燃券满额，领奖未完成'
        lines.append('手动处理后停在同一积分奖励面板，使用“接续原领奖记录”。' if recovery is None else
                     '接续领取再次遇到满额，两次拒绝均已记录。')
    else:
        title = '积分领奖待核对'
        lines.append('领取、返回或原报告保存尚未完整核实；未知领取不重放。')
    lines.append('本次不证明对局通关，也不增加独立验收计数。')
    return _parent(title, report, verified=verified), lines


def result(report) -> tuple[str, str]:
    """Only these three native operations can establish their own result scope."""
    if type(report) is not dict or report.get('operation') not in OPERATIONS:
        return '货币战争结果待核对', '未取得本次循环、积分查询或积分领奖的独立记录。'
    if report.get('status') not in ('success', 'partial', 'failed', 'stopped', 'cancelled'):
        return '货币战争结果待核对', '本次运行状态未完整记录，请核对原报告。'
    data = report.get('currency_wars')
    data = data if type(data) is dict else {}
    operation = report['operation']
    if operation == 'currency_wars_loop':title, lines = _loop(report, data)
    elif operation == 'currency_wars_points':title, lines = _points(report, data)
    else:title, lines = _rewards(report, data)
    lines.append('报告已保存。' if report.get('report_saved') is True else '汇总报告未完整保存，请核对原记录。')
    return title, '\n'.join(lines)


def progress(event) -> str | None:
    """Project only the real loop phase/progress/points event shapes."""
    if type(event) is not dict:
        return None
    kind = event.get('type')
    if kind == 'currency_loop_points':
        return '正在核对本周积分与游戏周；积分奖励单独核实。'
    if kind == 'currency_loop_phase':
        slot, requested, resume = (event.get(key) for key in ('slot', 'requested_runs', 'resume'))
        if (not _number(slot) or slot < 1 or not _number(requested) or requested > 2147483647
                or requested and slot > requested or type(resume) is not bool):
            return None
        return f'开发第 {slot} 局 · ' + ('接续原局' if resume else '准备新局') + (' · 直到停止' if requested == 0 else f' · 上限 {requested} 局')
    if kind == 'currency_loop_progress':
        data = event.get('data')
        counts = _counts(data)
        if (counts is None or not _scope(data) or data.get('status') not in _LOOP_STATES
                or type(data.get('until_points', False)) is not bool):
            return None
        return _count_text(counts) + ' · 独立验收 0 局'
    return None
