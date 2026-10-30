"""Observe one dispatched standard node; never click skills or restart a fight."""
import time

from .currency_wars import CurrencyWarsWorkflow, observe
from .currency_wars_identity import account_key
from .currency_wars_node import battle_node, result_node
from .models import AutomationError, EmptyCapture


def _observe_auto(c, store, scene, guard, tracker):
    """Record control state only; never derive a key or click from uncertainty."""
    from .currency_wars_auto import AutoObservation, read_auto
    from .currency_wars_standard_flow import evidence
    try:
        observed = read_auto(scene, c.settings.ocr_confidence)
    except Exception:
        observed = AutoObservation('unknown', 0., (('reason', 'reader_unavailable'), ('off_calibrated', False)))
    guard._require_current_scene(scene)  # Discard a result interrupted during CV.
    attempt = store.data['node_attempt']
    epoch = c.runner.input_epoch
    if tracker.get('epoch') != epoch:
        tracker.update(epoch=epoch, frames=[])
    frames = tracker.setdefault('frames', [])
    saved = None
    if observed.state == 'on':
        if len(frames) < 2 and (not frames or scene.captured_at > frames[-1]['captured_at']):
            saved = evidence(c, scene, 'currency_standard_auto_on_' + str(len(frames) + 1))
            frames.append(dict(captured_at=scene.captured_at, input_epoch=epoch, node=attempt['node'], evidence=saved))
    else:
        frames.clear()
    verified = observed.state == 'on' and len(frames) == 2
    key = (observed.state, verified)
    if tracker.get('last') == key:
        return
    tracker['last'] = key
    saved = saved or evidence(c, scene, 'currency_standard_auto_' + observed.state)
    attempt['auto_observation'] = dict(observed.to_dict(), node=attempt['node'], input_epoch=epoch,
                                      captured_at=scene.captured_at, evidence=saved, verified_on=verified,
                                      on_frames=[dict(frame) for frame in frames])
    attempt['auto_on_observed'] = attempt.get('auto_on_observed') is True or verified
    if verified:
        attempt.setdefault('auto_on_evidence', [dict(frame) for frame in frames])
    store.persist()
    if verified:
        c.log('标准节点' + attempt['node'] + '两帧核实自动战斗已开启，仅观察本次战斗。')
    elif observed.state == 'on':
        c.log('标准节点' + attempt['node'] + '观察到开启控件，等待下一份新鲜画面核对。')
    elif observed.state == 'disabled':
        c.log('标准节点' + attempt['node'] + '自动控件暂不可用，继续观察本次战斗或结算。')
    else:
        c.log('标准节点' + attempt['node'] + '自动战斗状态未核实，仅观察本次战斗或结算。')


def entry_feedback(scene, node, confidence=.65):
    kind = observe(scene,confidence).page_kind
    return ((kind=='battle' and battle_node(scene,confidence)==node)
            or (kind=='match_defeat' and result_node(scene,confidence)==node)
            or (kind in ('node_result','final_victory') and result_node(scene,confidence)==node
                and (kind != 'final_victory' or node.startswith('3-'))))


def observe_started_node(c, store, scene):
    from .currency_wars_standard_flow import evidence
    attempt = store.data.get('node_attempt',{})
    action_id = attempt.get('start_action_id')
    actions = store.data['actions']
    if (type(action_id) is not int or not 0 <= action_id < len(actions)
            or actions[action_id].get('action')!='start_standard_node'
            or actions[action_id].get('status')!='verified'
            or not actions[action_id].get('target')
            or actions[action_id]['target'][0]!=attempt.get('node')):
        raise AutomationError('当前战斗缺少已核实标准出战来源，未执行战斗输入。')
    guard = CurrencyWarsWorkflow(c)
    elapsed, unseen = 0., 0.
    defeat_frames=[]
    auto_tracker = {}
    limit = min(180,c.settings.battle_timeout)
    while elapsed < limit:
        c.checkpoint()
        started, inactive = time.monotonic(), c.runner.inactive_duration
        kind = 'unknown'
        unreadable = True
        if scene is not None:
            guard._require_current_scene(scene)
            if account_key(scene,max(.85,c.settings.ocr_confidence)) != store.data.get('account_key'):
                raise AutomationError('节点观察账号来源不一致。')
            kind = observe(scene,c.settings.ocr_confidence).page_kind
            if kind!='match_defeat':defeat_frames=[]
            unreadable = kind in ('unknown','preparation')
            if kind=='battle':
                actual = battle_node(scene,c.settings.ocr_confidence)
                unreadable = actual is None
                if actual is not None and actual != attempt['node']:
                    attempt.update(status='unknown',reason='战斗节点与本次出战来源不符。')
                    break
                if actual == attempt['node']:
                    unseen = 0.
                if actual == attempt['node'] and not attempt.get('battle_observed'):
                    attempt.update(battle_observed=True,battle=evidence(c,scene,'currency_standard_battle'))
                    store.persist()
                    c.log('标准节点'+attempt['node']+'战斗已观察，继续核对控件与本次结算。')
                if actual == attempt['node']:
                    _observe_auto(c, store, scene, guard, auto_tracker)
            elif kind=='match_defeat':
                if result_node(scene,c.settings.ocr_confidence)!=attempt['node'] or store.data.get('match_victory_observed') is True:
                    attempt.update(status='unknown',reason='整局结束与本次出战或原胜利状态不符。');break
                defeat_frames.append(evidence(c,scene,'currency_standard_defeat_frame_'+str(len(defeat_frames)+1)))
                if len(defeat_frames)==2:
                    attempt.update(status='defeated',node_verified=False,defeat_observed=True,result_kind='match_defeat',
                        result=defeat_frames[-1],defeat_frames=defeat_frames,verification='matching_terminal_defeat_after_start')
                    store.data.update(match_defeat_observed=True,defeat_start_action_id=action_id)
                    store.persist();c.log('标准节点'+attempt['node']+'整局结束已观察；等待零生命与独立失败结算核验。')
                    return scene,True
            elif kind in ('node_result','final_victory'):
                same = (result_node(scene,c.settings.ocr_confidence)==attempt['node']
                        and (kind != 'final_victory' or attempt['node'].startswith('3-')))
                attempt.update(status='verified' if same else 'unknown',node_verified=same,
                               result_kind=kind,
                               result=evidence(c,scene,'currency_standard_node_result'),
                               verification='matching_result_after_start' if same else 'wrong_result_node')
                if same and kind == 'final_victory':
                    store.data.update(match_victory_observed=True, victory_start_action_id=action_id)
                store.persist()
                c.log('标准节点'+attempt['node']+('胜利已核实；整局尚未完成。' if same else '结算编号不符，停止推进。'))
                return scene, same
            elif kind not in ('unknown','preparation'):
                attempt.update(status='unknown',reason='出战后出现未校准页面：'+kind)
                break
        c.sleep(2)
        duration = max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        elapsed += duration
        if unreadable:
            unseen += duration
            if unseen >= 30:
                attempt.update(status='unknown',reason='出战后持续未识别到对应战斗或结算。')
                break
        capture_started, capture_inactive = time.monotonic(), c.runner.inactive_duration
        try:
            scene = c.snapshot()
        except EmptyCapture:
            scene = None
        capture_duration = max(0.,time.monotonic()-capture_started-(c.runner.inactive_duration-capture_inactive))
        elapsed += capture_duration
        if unreadable:
            unseen += capture_duration
    else:
        attempt.update(status='timeout',reason='标准节点战斗观察超时，未重复出战。')
    if scene is not None:
        guard._require_current_scene(scene)
        attempt['screenshot'] = evidence(c,scene,'currency_standard_node_unknown')
    store.data.update(action_status='node_unverified',reason=attempt.get('reason','节点结算未核实。'))
    store.persist()
    return scene, False
