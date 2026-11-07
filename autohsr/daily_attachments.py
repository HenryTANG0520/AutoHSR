"""One explicit free-reward task and its current native input boundary."""

from dataclasses import dataclass, replace
from time import monotonic

from .currency_wars_identity import UID_COUNTEREVIDENCE, checked_account_key
from .free_rewards import (battlepass_claim_target, battlepass_modal, battlepass_page, battlepass_progress, battlepass_tab,
                           claim_enabled, mail_claimed, mail_entry, mailbox, reward_overlay, task_category)
from .models import AutomationError, InputInterrupted, Stopped, TaskResult, Token, normalize
from .workflow_identity import active


ATTACHMENT_FLOWS = {'mail': '仅领取邮件附件', 'battlepass': '仅领取无名勋礼'}
MAIL = 'mail_attachments'
BATTLEPASS_STAGES = {'本周任务': 'battlepass_weekly_tasks', '本期任务': 'battlepass_period_tasks',
                     'rewards': 'battlepass_free_levels'}
SAFE_NEXT = '请核对本次免费领取和原始报告。结果待核对时保留当前画面。'
_CLOSE_LABELS = ('点击空白处关闭', '点击任意位置关闭', '点击空白处继续')
_OVERLAY_STAGES = {MAIL, BATTLEPASS_STAGES['rewards']}
_MAIL_BULK_AREA = (.12, .83, .35, .97)
_MAIL_SINGLE_AREA = (.80, .83, .98, .97)


def attachment_settings(settings, task):
    if type(task) is not str or task not in ATTACHMENT_FLOWS:
        raise ValueError('请选择一个独立邮件附件或无名勋礼任务。')
    return replace(settings, assignments=False, battle=False, daily=False, redemption_enabled=False,
                   mail=task == 'mail', battlepass=task == 'battlepass', allow_stamina_spend=False,
                   daily_synthesis=False, auto_launch=False, use_support=False, support_daily_only=False,
                   weekly_enabled=False, power_plan_enabled=False, notification_enabled=False)


def attachment_runner(settings, emit, *, task, root=None):
    from .task_workflow_run import TaskWorkflowRunner

    frozen = attachment_settings(settings, task)
    document = dict(version=1, name=ATTACHMENT_FLOWS[task], steps=[
        dict(id=task, type='task', task='daily', params={'tasks': [task]}),
    ])
    return TaskWorkflowRunner(frozen, document, emit, root=root)


@dataclass
class AttachmentResult(TaskResult):
    attachment_outcome: str
    verified_claims: list[str]


@dataclass(frozen=True)
class _Claim:
    stage: str
    epoch: int
    sequence: int
    account: str
    close_started: bool = False


def result(ctx, task, status, detail):
    verified = list(getattr(ctx, '_verified_attachment_claims', ()))
    if status == 'ok' and getattr(ctx, '_pending_attachment_claim', None) is not None:
        status, detail = 'partial', '本次免费领取已尝试，结果尚待核对。'
    outcome = ('claimed' if verified else 'empty') if status == 'ok' else 'unknown'
    return AttachmentResult(task, status, detail, outcome, verified)


def _uid_reads(scene):
    return tuple(scene.field_reads.get(UID_COUNTEREVIDENCE) or ())


def _account(scene, confidence, *, hidden=False):
    if hidden and not (_uid_reads(scene) or any(t.within((0, .94, .35, 1))
                       and normalize(t.text).startswith('uid') for t in scene.tokens)):
        return None
    return checked_account_key(scene, confidence)


def observe(ctx, scene):
    from .policy import replenishment_dialog
    from .workflows import DailyWorkflow

    pending = getattr(ctx, '_pending_attachment_claim', None)
    if DailyWorkflow._supply_overlay(scene) or (reward_overlay(scene) and (
            pending is None or pending.stage not in _OVERLAY_STAGES)):
        raise AutomationError('独立免费领奖遇到列车补给或无关的物品展示，请手动核对当前页面。')
    if replenishment_dialog(scene) or battlepass_modal(scene):
        raise AutomationError('独立免费领奖遇到付费或奖励选择弹窗，已停止。')
    account = _account(scene, max(.85, ctx.settings.ocr_confidence), hidden=True)
    if pending is not None:
        if ctx.runner.input_epoch != pending.epoch or ctx.scene_epoch != pending.epoch:
            raise InputInterrupted('免费领取后输入代次已变，保留结果待核对。')
        if account is not None and account != pending.account:
            raise AutomationError('免费领取后账号已改变，保留结果待核对。')


def _unique(scene, target, labels, area, confidence):
    matches = [t for t in scene.tokens if t.within(area) and normalize(t.text) in labels]
    return len(matches) == 1 and matches[0] == target and confidence <= target.score <= 1


def mail_attachments_cleared(scene, confidence):
    bulk = scene.find('全部领取', _MAIL_BULK_AREA, exact=True)
    return (bulk is not None and _unique(scene, bulk, ('全部领取',), _MAIL_BULK_AREA, confidence)
            and not scene.has(('领取', '领取附件'), _MAIL_SINGLE_AREA, exact=True)
            and mail_claimed(scene))


def _action(ctx, scene, target):
    from .workflows import DailyWorkflow

    observe(ctx, scene)
    if not isinstance(target, Token):
        raise AutomationError('独立免费领奖只接受已核实的可见控件。')
    task = ctx.runner.daily_attachment_only
    confidence = ctx.settings.ocr_confidence
    pending = getattr(ctx, '_pending_attachment_claim', None)
    if pending is not None:
        if (reward_overlay(scene) and not pending.close_started and ctx.capture_sequence > pending.sequence
                and _unique(scene, target, _CLOSE_LABELS, (.25, .65, .75, .97), confidence)):
            return 'close', pending.stage
        raise AutomationError('本次免费领取尚待核对，不能重发或切换到其它领取。')
    if DailyWorkflow._phone(scene):
        labels = ('邮件', '邮箱') if task == 'mail' else ('无名勋礼',)
        if (_unique(scene, target, labels, (.55, .25, 1, 1), confidence)
                or task == 'mail' and mail_entry(scene) == target):
            return 'navigate', None
    elif DailyWorkflow._login(scene) and not DailyWorkflow._login_blocked(scene):
        if _unique(scene, target, ('点击进入', '点击进入游戏', '开始游戏'), (0, 0, 1, 1), confidence):
            return 'navigate', None
    elif task == 'mail' and mailbox(scene) and battlepass_page(scene) is None:
        if (_unique(scene, target, ('全部领取',), _MAIL_BULK_AREA, confidence)
                and claim_enabled(scene, target) is True):
            return 'claim', MAIL
    elif task == 'battlepass' and (kind := battlepass_page(scene)) is not None and not mailbox(scene):
        if any(battlepass_tab(scene, page) == target for page in ('tasks', 'rewards') if page != kind):
            return 'navigate', None
        label = normalize(target.text)
        if (kind == 'tasks' and label in ('本周任务', '本期任务')
                and _unique(scene, target, (label,), (.07, .31, .20, .74), confidence)):
            return 'navigate', None
        if (battlepass_claim_target(scene, getattr(ctx, 'vision', None), confidence) == target
                and claim_enabled(scene, target) is True):
            if kind == 'rewards':
                return 'claim', BATTLEPASS_STAGES['rewards']
            categories = [label for label in ('本周任务', '本期任务') if task_category(scene, label)]
            if len(categories) == 1 and battlepass_progress(scene) is not None:
                return 'claim', BATTLEPASS_STAGES[categories[0]]
    raise AutomationError('独立免费领奖当前按钮与选定任务不符。')


def before_click(ctx, scene, target):
    if not active() or ctx.report.operation != 'daily':
        raise AutomationError('独立免费领奖缺少当前任务树账号约束。')
    action, stage = _action(ctx, scene, target)
    pending = getattr(ctx, '_pending_attachment_claim', None)
    window, geometry = ctx.window, scene.geometry
    if geometry is None:
        raise AutomationError('独立免费领奖当前画面缺少原生窗口几何。')
    epoch, sequence = ctx.runner.input_epoch, ctx.capture_sequence
    captured, image, tokens, uid_reads = scene.captured_at, scene.image, tuple(scene.tokens), _uid_reads(scene)
    confidence = max(.85, ctx.settings.ocr_confidence)
    if action == 'claim':
        if stage in getattr(ctx, '_verified_attachment_claims', ()):
            raise AutomationError('本次已核对该领取，不能重发。')
        next_pending = _Claim(stage, epoch, sequence, _account(scene, confidence))
    elif action == 'close':
        next_pending = replace(pending, close_started=True)
    else:
        next_pending = None

    def current():
        return (ctx.window is window and ctx.last_scene is scene and ctx.capture_sequence == sequence
                and scene.geometry == geometry and scene.image is image and scene.captured_at == captured
                and tuple(scene.tokens) == tokens and _uid_reads(scene) == uid_reads
                and getattr(ctx, '_pending_attachment_claim', None) is pending
                and 0 <= monotonic() - captured <= 8)

    def submit():
        if not current() or _action(ctx, scene, target) != (action, stage):
            raise AutomationError('独立免费领奖发送前的画面或按钮已改变。')
        window.guard(geometry)
        if window.emergency_pressed() or ctx.runner.stop_requested:
            raise Stopped('独立免费领奖输入前已停止。')
        if ctx.scene_epoch != epoch or ctx.runner.input_epoch != epoch:
            raise InputInterrupted('独立免费领奖发送前代次已变，保留原目标。')
        if not current():
            raise AutomationError('独立免费领奖发送前的画面或按钮已改变。')
        ctx._pending_attachment_claim = next_pending

    return submit


def require_key(ctx, name):
    from .workflows import DailyWorkflow

    scene = ctx.last_scene
    observe(ctx, scene)
    flow = DailyWorkflow(ctx)
    if (not active() or name != 'esc' or scene.geometry is None or not 0 <= monotonic() - scene.captured_at <= 8
            or getattr(ctx, '_pending_attachment_claim', None) is not None
            or flow._in_battle(scene) or not (flow._world(scene) or flow._navigation_page(scene))):
        raise AutomationError('独立免费领奖只允许从已核实的非战斗界面返回。')


def confirmed(ctx, stage, scene, *, previous=None):
    pending = getattr(ctx, '_pending_attachment_claim', None)
    confidence = max(.85, ctx.settings.ocr_confidence)

    def check():
        observe(ctx, scene)
        if (pending is None or pending.stage != stage or ctx.last_scene is not scene
                or getattr(ctx, '_pending_attachment_claim', None) is not pending
                or ctx.capture_sequence <= pending.sequence or not 0 <= monotonic() - scene.captured_at <= 8
                or _account(scene, confidence) != pending.account
                or stage in _OVERLAY_STAGES and not pending.close_started):
            raise AutomationError('免费领取缺少本次提交或返回依据，保留结果待核对。')
        if stage == MAIL:
            if previous is None:
                raise AutomationError('邮件附件缺少首次回页证据。')
            first, sequence = previous
            if (first is scene or first.geometry is None or first.geometry != scene.geometry
                    or not pending.sequence < sequence == ctx.capture_sequence - 1
                    or not 0 <= monotonic() - first.captured_at <= 8 or first.captured_at >= scene.captured_at
                    or _account(first, confidence) != pending.account
                    or not all(mail_attachments_cleared(frame, confidence) for frame in (first, scene))):
                raise AutomationError('两张邮件回页尚未核实附件均已清除，保留本次领取待核对。')

    check()
    if stage == MAIL:
        ctx.evidence(previous[0], stage + '_first_settled')
    ctx.evidence(scene, stage + '_settled')
    ctx.checkpoint()
    check()
    verified = tuple(getattr(ctx, '_verified_attachment_claims', ()))
    ctx._verified_attachment_claims = (*verified, stage)
    ctx._pending_attachment_claim = None
