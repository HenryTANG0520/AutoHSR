"""Verify separate planar stamina and existing immersifier costs before starting."""
import re
from .models import AutomationError, normalize
from .planar_team import preparation


def inventory(scene):
    found = []
    for token in scene.tokens:
        if token.within((.85, 0, .95, .13)):
            match = re.fullmatch(r'(\d{1,2})/12[|丨+＋]*', normalize(token.text))
            if match and 0 <= int(match.group(1)) <= 12:
                found.append(int(match.group(1)))
    return found[0] if len(found) == 1 else None


def payment(workflow, scene, *, require_affordable=True, expected_count=None):
    count = workflow._round_count(scene)
    available = workflow._available(scene)
    tokens = inventory(scene)
    if not preparation(scene) or count is None or not 1 <= count <= 6 or tokens is None or available is None:
        raise AutomationError('未独立核实饰品提取次数、体力与沉浸器余额，未开始挑战。')
    if expected_count is not None and count!=expected_count:
        raise AutomationError('饰品提取次数在选队后发生变化，未开始挑战。')
    prices = workflow.ctx.planar_payment(scene)
    expected_tokens = min(count, tokens)
    expected_stamina = (count - expected_tokens) * 40
    if (prices != dict(stamina=expected_stamina, immersifiers=expected_tokens)
            or (require_affordable and expected_stamina > available)):
        evidence=getattr(workflow.ctx,'evidence',None)
        if evidence is not None:
            evidence(scene,'planar_payment_unverified')
        raise AutomationError('饰品提取资源图标、价格与次数不一致，未开始挑战。')
    return expected_stamina, expected_tokens


def limit_batch(workflow, scene, remaining):
    available, tokens = workflow._available(scene), inventory(scene)
    if available is None or tokens is None:
        raise AutomationError('饰品提取缺少体力或沉浸器余额，未调整次数。')
    requested = workflow.settings.challenge_count
    remaining_count = 6 if requested is None else requested - (workflow.ctx.report.battle_completed-getattr(workflow,'_battle_completed_base',0))
    goal=getattr(getattr(workflow.ctx,'battle_budget',None),'power_plan',None)
    if goal is not None:tokens=goal.tokens(tokens)
    desired = min(6, workflow.settings.rounds, remaining_count,
                  tokens + min(remaining, available) // 40)
    if desired <= 0:
        return scene, 0
    hover_rechecked=False
    for _ in range(12):
        count = workflow._round_count(scene)
        if not preparation(scene) or count is None:
            raise AutomationError('未核实饰品提取次数控件，未开始挑战。')
        if count == desired:
            stamina, _ = payment(workflow, scene)
            if stamina > remaining:
                raise AutomationError('饰品提取体力费用超过剩余预算。')
            # Nominal cost keeps settlement-wave accounting separate from payment.
            return scene, count * 40
        plus = count < desired
        roi = (.93, .74, .99, .85) if plus else (.74, .78, .80, .86)
        target = scene.find(('+', '＋') if plus else ('−', '-', '－'), roi, exact=True)
        if target is None:
            target = workflow._icon(scene, 'count_plus' if plus else 'count_minus', roi)
        if target is None:
            move=getattr(workflow.ctx,'move',None)
            if scene.image is not None and not hover_rechecked and callable(move):
                # A previous click leaves the cursor over a highlighted button.
                # Clear only menu hover, then re-observe; never click a guessed
                # increment/decrement location when its icon is missing.
                move(scene,(.70,.68))
                workflow.ctx.sleep(.15)
                scene=workflow._snapshot()
                hover_rechecked=True
                continue
            evidence=getattr(workflow.ctx,'evidence',None)
            if evidence is not None:
                evidence(scene,'planar_count_button_unverified')
            raise AutomationError('未核实饰品提取次数按钮，未开始挑战。')
        workflow._click(scene, target)
        hover_rechecked=False
        expected = count + (1 if plus else -1)
        scene = workflow._wait(lambda s: preparation(s) and workflow._round_count(s) == expected,
                               timeout=12, description='核实饰品提取挑战次数变化')
        # Intermediate values can still exceed the current balance while
        # decreasing a remembered six-wave batch. Nothing is started here.
        payment(workflow, scene, require_affordable=False)
    raise AutomationError('饰品提取次数调整超过上限。')
