"""Native scope for the task tree's explicit assignments-only selection."""
from dataclasses import dataclass, replace
import re
from time import monotonic

from .currency_wars_identity import UID_COUNTEREVIDENCE, checked_account_key
from .daily_support import complete_uid_label
from .models import AutomationError, InputInterrupted, Stopped, Token, normalize
from .workflow_identity import active
from .workflows import DailyWorkflow, TITLE


CLAIM = 'assignment_claim'
CLOSE = 'assignment_reward_close'
CLAIM_AREA = (.65, .78, .97, .96)
CLOSE_AREA = (.25, .65, .75, .97)
ELAPSED_AREA = (.65, .45, .96, .70)
CLOSE_LABELS = ('点击空白处关闭', '点击任意位置关闭', '点击空白处继续')
PAYMENT = ('购买', '续购', '续费', '订购', '支付', '付款')


def assignment_receipt(report):
    """Project a native independent assignment result without account data."""
    value = report.get('assignment')
    if (report.get('operation') != 'daily' or report.get('report_saved') is not True
            or not isinstance(value, dict) or value.keys() != {'outcome', 'submission'}):
        return None
    state = value['outcome'], value['submission']
    if report.get('status') == 'success' and state in (('claimed', 'verified'), ('empty', 'not_attempted')):
        return dict(value)
    if report.get('status') in ('partial', 'failed', 'stopped') and state in (
            ('unknown', 'not_attempted'), ('unknown', 'attempted')):
        return dict(value)
    return None


@dataclass(frozen=True)
class _Attempt:
    epoch: int
    sequence: int
    account: str
    close_attempted: bool = False


def _account(scene, confidence, *, allow_hidden=False):
    if allow_hidden and not (scene.field_reads.get(UID_COUNTEREVIDENCE) or any(
            token.within((0, .94, .35, 1)) and normalize(token.text).startswith('uid') for token in scene.tokens)):
        return None
    if complete_uid_label(scene) is None:
        raise AutomationError('独立委托当前账号未完整核实。')
    return checked_account_key(scene, confidence)


def _page(scene):
    return (scene.has('委托', TITLE, exact=True) and DailyWorkflow._persistent_assignments(scene)
            and not DailyWorkflow._supply_overlay(scene) and not DailyWorkflow._login_reward_overlay(scene)
            and not scene.has(PAYMENT) and not scene.has(CLOSE_LABELS, exact=True))


def _unique(scene, labels, region, confidence):
    tokens = [token for token in scene.tokens if token.within(region) and normalize(token.text) in labels]
    return tokens[0] if len(tokens) == 1 and confidence <= tokens[0].score <= 1 else None


def _elapsed_hours(scene, confidence):
    fields = [token for token in scene.tokens if token.within(ELAPSED_AREA)
              and normalize(token.text).startswith('已进行')]
    if len(fields) != 1 or not confidence <= fields[0].score <= 1:
        return None
    match = re.fullmatch(r'已进行([0-9]{1,2})/30(?:小时|h)', normalize(fields[0].text))
    hours = int(match[1]) if match else None
    return hours if hours is not None and hours <= 30 else None


def _target(scene, intent, confidence):
    if intent == CLAIM and _page(scene):
        claim = _unique(scene, ('领取奖励',), CLAIM_AREA, confidence)
        hours = _elapsed_hours(scene, confidence)
        if (claim is not None and hours is not None and hours > 0
                and DailyWorkflow._assignment_claim_enabled(scene, claim) is True):
            return claim
    if (intent == CLOSE and DailyWorkflow._login_reward_overlay(scene)
            and not DailyWorkflow._supply_overlay(scene) and not scene.has(PAYMENT)):
        return _unique(scene, CLOSE_LABELS, CLOSE_AREA, confidence)
    return None


def _settled(flow, scene, confidence):
    if (not _page(scene) or _elapsed_hours(scene, confidence) != 0
            or not flow._assignment_settled(scene)):
        return False
    if not scene.has('领取奖励', CLAIM_AREA, exact=True):
        return True
    claim = _unique(scene, ('领取奖励',), CLAIM_AREA, confidence)
    return claim is not None and flow._assignment_claim_enabled(scene, claim) is False


def require_navigation(scene, target):
    if (isinstance(target, Token) and not DailyWorkflow._supply_overlay(scene)
            and not DailyWorkflow._login_reward_overlay(scene)):
        label = normalize(target.text)
        if label == '委托' and target.within((.55, .25, 1, 1)) and DailyWorkflow._phone(scene):
            return
        if (label in ('点击进入', '点击进入游戏', '开始游戏') and DailyWorkflow._login(scene)
                and not DailyWorkflow._login_blocked(scene)):
            return
    raise AutomationError('独立委托只允许已核实的委托入口与必要的登录导航。')


def before_submit(ctx, scene, target, intent):
    if (getattr(ctx.runner, 'assignments_only', False) is not True
            or ctx.report.operation != 'daily' or not active()):
        raise AutomationError('独立委托输入缺少本次明确的任务范围和账号约束。')
    confidence = max(.85, ctx.settings.ocr_confidence)
    window, geometry = ctx.window, scene.geometry
    epoch, sequence = ctx.runner.input_epoch, ctx.capture_sequence
    captured_at, image = scene.captured_at, scene.image
    tokens, uid_reads = tuple(scene.tokens), scene.field_reads.get(UID_COUNTEREVIDENCE)
    attempt = getattr(ctx, '_assignment_reward_attempt', None)
    if target is None or target != _target(scene, intent, confidence) or geometry is None:
        raise AutomationError('独立委托当前按钮未核实。')
    if intent == CLAIM:
        if attempt is not None:
            raise AutomationError('独立委托已尝试领取，保留原结果待核对。')
        updated = _Attempt(epoch, sequence, _account(scene, confidence))
    else:
        if (attempt is None or attempt.epoch != epoch or sequence <= attempt.sequence
                or attempt.close_attempted):
            raise AutomationError('独立委托物品弹窗缺少本次领取来源。')
        updated = replace(attempt, close_attempted=True)

    def submit():
        window.guard(geometry)
        if (ctx.window is not window or ctx.last_scene is not scene or ctx.capture_sequence != sequence
                or scene.geometry != geometry or scene.image is not image or scene.captured_at != captured_at
                or not 0 <= monotonic() - captured_at <= 8 or tuple(scene.tokens) != tokens
                or scene.field_reads.get(UID_COUNTEREVIDENCE) != uid_reads
                or getattr(ctx, '_assignment_reward_attempt', None) is not attempt
                or target != _target(scene, intent, confidence)):
            raise AutomationError('独立委托发送前的画面或按钮已改变。')
        account = _account(scene, confidence, allow_hidden=intent == CLOSE)
        if account is not None and account != updated.account:
            raise AutomationError('独立委托发送前账号已改变。')
        if ctx.runner.stop_requested or window.emergency_pressed():
            raise Stopped('独立委托输入前已停止。')
        if ctx.scene_epoch != epoch or ctx.runner.input_epoch != epoch:
            raise InputInterrupted('独立委托输入前代次已变，已丢弃旧目标。')
        ctx._assignment_reward_attempt = updated
        if intent == CLAIM:
            ctx.report.assignment['submission'] = 'attempted'

    return submit


def run(flow):
    ctx = flow.ctx
    confidence = max(.85, flow.settings.ocr_confidence)
    scene = flow._snapshot()
    flow._require_reward_only_clear(scene)
    if not scene.has('委托', TITLE, exact=True):
        scene = flow._open_phone_item('委托', '委托')

    def ready(page):
        flow._require_reward_only_clear(page)
        return _page(page)

    if not ready(scene):
        scene = flow._wait(ready, timeout=8, description='核实持续委托页')
    account = _account(scene, confidence)
    count = flow._assignment_count(scene)
    epoch, sequence = ctx.runner.input_epoch, ctx.capture_sequence
    if _settled(flow, scene, confidence):
        def empty(page):
            return (page is not scene and ctx.capture_sequence > sequence and ctx.scene_epoch == epoch
                    and ctx.runner.input_epoch == epoch and _settled(flow, page, confidence)
                    and flow._assignment_count(page) == count and _account(page, confidence) == account)

        second = flow._wait(empty, timeout=8, description='复核持续委托暂无可领')
        result = flow._result('assignments', 'ok', '持续委托暂无可收取奖励，已核对原委托进行中。', second)
        ctx.report.assignment['outcome'] = 'empty'
        return result
    claim = _target(scene, CLAIM, confidence)
    if claim is None:
        raise AutomationError('未同时核实唯一可用的持续委托领取按钮和正数累积时长。')

    ctx.evidence(scene, 'assignments_before_claim')
    ctx.click(scene, claim, assignment_intent=CLAIM)

    def same_attempt(page):
        if ctx.runner.input_epoch != epoch or ctx.scene_epoch != epoch:
            raise InputInterrupted('独立委托领取后输入代次已变，原结果待核对。')
        if DailyWorkflow._supply_overlay(page) or page.has(PAYMENT):
            raise AutomationError('独立委托领取后出现无关奖励或支付界面。')
        observed = _account(page, confidence, allow_hidden=True)
        if observed is not None and observed != account:
            raise AutomationError('独立委托领取后账号已改变，原结果待核对。')
        return observed == account

    def settled(page):
        return (same_attempt(page) and flow._assignment_count(page) == count
                and _settled(flow, page, confidence))

    def feedback(page):
        return ctx.capture_sequence > sequence and (settled(page) or _target(page, CLOSE, confidence) is not None)

    first = flow._wait(feedback, timeout=15, description='核实本次委托领取反馈')
    close = _target(first, CLOSE, confidence)
    if close is not None:
        ctx.evidence(first, 'assignments_reward_display')
        ctx.click(first, close, assignment_intent=CLOSE)
        first = flow._wait(settled, timeout=15, description='核实委托回页')
    first_sequence = ctx.capture_sequence
    ctx.evidence(first, 'assignments_first_settled')
    second = flow._wait(lambda page: page is not first and ctx.capture_sequence > first_sequence and settled(page),
                        timeout=8, description='复核两张委托回页画面')
    result = flow._result('assignments', 'ok',
                          f'已提交一次领取，两张画面确认累积时长归零，原有 {count[0]}/{count[1]} 项委托持续进行。', second)
    ctx.report.assignment.update(outcome='claimed', submission='verified')
    return result
