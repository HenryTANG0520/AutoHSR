"""Pure, bounded presentation of the independent DU reward receipt.

This does not read journals or verify PNGs. It projects the native receipt's
typed scope/results, and never includes its private evidence or error strings.
"""

FREE_CATEGORIES = ('拟合等级', '稳态数组', '可能性画廊')
MOON = '月下奇谭'
PERIODIC = '周期积分'
CATEGORIES = (*FREE_CATEGORIES, MOON)
_UNKNOWN_DOT = '未绑定红点'
_CLAIM_INTENTS = {'du_reward_dot': '拟合等级', 'du_reward_claim': '稳态数组',
                  'du_reward_gallery_claim': '可能性画廊', 'du_reward_unlock': MOON}
_DATA_STATES = ('running', 'complete', 'partial', 'unknown', 'stopped', 'abort_before_input')


def _integer(value):
    return type(value) is int and value >= 0


def _categories(value, allowed):
    if (type(value) is not list or len(value) > len(allowed)
            or any(type(item) is not str or item not in allowed for item in value)
            or len(set(value)) != len(value)):
        raise ValueError('invalid categories')
    return tuple(item for item in allowed if item in value)


def _summary(data):
    if (type(data) is not dict or type(data.get('schema')) is not int or data['schema'] != 1
            or data.get('operation') != 'du_rewards' or data.get('status') not in _DATA_STATES
            or data.get('battle_started') is not False
            or any(type(data.get(name)) is not bool for name in
                   ('use_cassettes', 'rewards_verified', 'safe_to_restart', 'all_notifications_cleared'))):
        raise ValueError('invalid receipt')
    use = data['use_cassettes']
    wanted = (*FREE_CATEGORIES, MOON) if use else FREE_CATEGORIES
    requested = _categories(data.get('requested_categories'), CATEGORIES)
    if requested != wanted:
        raise ValueError('inconsistent request')
    remaining = _categories(data.get('remaining_categories'), (*wanted, _UNKNOWN_DOT))
    skipped = _categories(data.get('skipped_optional_categories'), (PERIODIC,) if use else (MOON, PERIODIC))
    actions, claims = data.get('actions'), data.get('claims')
    if (type(actions) is not list or len(actions) > 240 or type(claims) is not list or len(claims) > 240):
        raise ValueError('invalid actions')
    expected, actual, pending = {}, {}, False
    for index, action in enumerate(actions):
        if (type(action) is not dict or type(action.get('id')) is not int or action['id'] != index
                or action.get('status') not in ('pending', 'submitted', 'verified', 'unknown')
                or type(action.get('request')) is not dict):
            raise ValueError('invalid action')
        intent = action['request'].get('intent')
        if type(intent) is not str:
            raise ValueError('invalid action')
        if intent in _CLAIM_INTENTS:
            expected[index] = _CLAIM_INTENTS[intent]
        pending |= action['status'] != 'verified'
    spent, verified, outstanding_moon = 0, 0, 0
    budget = data.get('cassettes')
    if type(budget) is not dict:
        raise ValueError('invalid budget')
    initial, limit, reported_spent = (budget.get(key) for key in ('initial_balance', 'limit', 'spent_verified'))
    if (initial is not None and not _integer(initial) or not _integer(limit) or not _integer(reported_spent)
            or reported_spent > limit or reported_spent > 2400 or limit % 100 or reported_spent % 100
            or initial is None and (limit or reported_spent)
            or initial is not None and limit != initial // 100 * 100
            or not use and (initial is not None or limit or reported_spent)):
        raise ValueError('inconsistent budget')
    for index, claim in enumerate(claims):
        if (type(claim) is not dict or type(claim.get('id')) is not int or claim['id'] != index
                or claim.get('source') not in wanted or claim.get('status') not in ('pending', 'received', 'verified')
                or type(claim.get('action_id')) is not int or not 0 <= claim['action_id'] <= len(actions)
                or claim['action_id'] in actual):
            raise ValueError('invalid claim')
        action_id, source = claim['action_id'], claim['source']
        # A pending obligation can be persisted before its action is appended.
        if action_id == len(actions):
            if claim['status'] == 'verified' or index != len(claims) - 1:
                raise ValueError('missing action')
        else:
            actual[action_id] = source
            if expected.get(action_id) != source:
                raise ValueError('inconsistent claim')
        if claim['status'] == 'verified':
            if actions[action_id]['status'] != 'verified':
                raise ValueError('unverified action')
            verified += 1
        else:
            pending = True
        if source == MOON:
            before = claim.get('balance_before')
            if (claim.get('amount') != 100 or type(claim.get('amount')) is not int
                    or not _integer(before) or initial is None or before != initial - spent
                    or spent + 100 > limit):
                raise ValueError('inconsistent debit')
            if claim['status'] == 'verified':
                after = claim.get('balance_after')
                if not _integer(after) or after != before - 100:
                    raise ValueError('unverified debit')
                spent += 100
            else:
                outstanding_moon += 1
    if actual != expected or spent != reported_spent or outstanding_moon > 1:
        raise ValueError('incomplete claim coverage')
    obligation = data.get('obligation', 'missing')
    if obligation is not None:
        if (type(obligation) is not dict or not claims or obligation != claims[-1]
                or claims[-1]['status'] == 'verified'):
            raise ValueError('invalid obligation')
        pending = True
    elif any(claim['status'] != 'verified' for claim in claims):
        raise ValueError('missing obligation')
    if data['status'] == 'abort_before_input' and (actions or claims or obligation is not None
            or data['rewards_verified'] or not data['safe_to_restart']):
        raise ValueError('inconsistent abort')
    complete = data['status'] == 'complete' and data['rewards_verified']
    if (data['status'] == 'complete' and (not complete or pending or remaining or not data['safe_to_restart'])
            or data['rewards_verified'] and data['status'] != 'complete'
            or data['status'] == 'partial' and (not remaining or not data['safe_to_restart'])
            or data['all_notifications_cleared'] and (remaining or skipped or pending)):
        raise ValueError('inconsistent completion')
    return dict(requested=requested, remaining=remaining, skipped=skipped, use=use,
        state=data['status'], complete=complete, all_clear=data['all_notifications_cleared'],
        pending=pending, verified=verified, limit=limit, spent=spent,
        initial_known=initial is not None, outstanding_moon=outstanding_moon)


def rewards_result(report) -> tuple[str, str]:
    """Return a safe title/body; unrelated DU results never establish completion."""
    report = report if type(report) is dict else {}
    if report.get('operation') != 'du_rewards':
        return '差分领奖待核对', '未取得本次独立差分领奖记录，请核对原报告。'
    state = report.get('status')
    title = ('差分领奖已停止' if state in ('stopped', 'cancelled') else
             '差分领奖失败' if state == 'failed' else '差分领奖待核对')
    lines = []
    saved = report.get('report_saved') is True
    if not saved:
        lines.append('报告未完整保存，领奖结果待核对。')
    try:
        value = _summary(report.get('du_rewards'))
    except (ValueError, TypeError, KeyError, IndexError):
        lines.append('独立领奖记录缺失、不完整或相互矛盾；请核对原报告中的领取与卡带记录。')
        return title, '\n'.join(lines)
    complete = value['complete'] and saved and state in ('success', 'partial', 'failed', 'stopped', 'cancelled')
    if state not in ('stopped', 'cancelled', 'failed'):
        if state == 'success' and complete:
            title = '差分领奖已核实'
        elif (value['pending'] or value['state'] in ('unknown', 'running') or not saved
                or state not in ('success', 'partial')):
            title = '差分领奖待核对'
        else:
            title = '差分领奖未完成'
    lines.append('本次请求：' + '、'.join(value['requested']) + '。')
    if complete:
        lines.append('本次请求范围已核实。')
    elif value['state'] == 'abort_before_input':
        lines.append('尚未提交输入，本次请求未核实。')
    else:
        lines.append('本次请求尚未完整核实。')
    if value['verified']:
        lines.append(f"已核实领取 {value['verified']} 项；已核实结果保留。")
    if value['remaining']:
        lines.append('尚待核实：' + '、'.join(value['remaining']) + '。')
    if value['skipped']:
        lines.append('未请求，已跳过：' + '、'.join(value['skipped']) + '。')
    lines.append('全部可见红点已核实清空。' if complete and value['all_clear'] else '未确认全部可见红点清空。')
    if value['use']:
        if value['initial_known']:
            lines.append(f"已有月下卡带：冻结额度 {value['limit']}，已核实消耗 {value['spent']}。")
        else:
            lines.append('已有月下卡带：冻结额度尚未核实，已核实消耗 0。')
        if value['outstanding_moon']:
            lines.append('另有 100 月下卡带待核对；请勿重放解锁。')
        elif value['state'] == 'unknown':
            lines.append('后续卡带状态待核对。')
    else:
        lines.append('本次未授权使用月下卡带。')
    if value['pending']:
        lines.append('存在未核实输入或领取义务，请先核对，勿重放。')
    if state in ('stopped', 'cancelled'):
        lines.append('后续已停止。')
    elif state == 'failed' and complete:
        lines.append('后续处理失败，已核实结果保留。')
    return title, '\n'.join(lines)
