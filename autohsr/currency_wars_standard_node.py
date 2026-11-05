"""Observe one dispatched standard node; never click skills or restart a fight."""
import math
import re
import time
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, observe
from .currency_wars_identity import account_key
from .currency_wars_node import battle_node, result_node, result_nodes
from .currency_wars_pages import merged_loss_node_numbers
from .currency_wars_prepare import trusted
from .models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, Stopped, normalize


_LIFE_VALUE = r'([0-9]{1,3})(?:/([0-9]{1,3}))?'


def read_survived_loss(scene, confidence=.65):
    """Read a current, non-terminal loss and its exact Continue target."""
    if observe(scene, confidence).page_kind != 'node_loss':
        return None
    clean = trusted(scene, confidence)
    node = result_node(clean, confidence)
    tokens = clean.tokens
    if node is None or merged_loss_node_numbers(tokens) - {node}:
        return None
    life_row = [t for t in tokens if t.within((.3,.43,.5,.5))]
    lives = [match for t in life_row if (match := re.fullmatch('小队生命值' + _LIFE_VALUE, normalize(t.text)))]
    labels = [t for t in life_row if normalize(t.text) == '小队生命值']
    if labels:
        if len(labels) != 1 or lives:
            return None
        label = labels[0]
        lives = [match for t in life_row if abs(t.center[1] - label.center[1]) <= .012
                 and 0 <= t.box[0] - label.box[2] <= .03
                 and (match := re.fullmatch(_LIFE_VALUE, normalize(t.text)))]
    buttons = [t for t in tokens if t.within((.4,.79,.6,.86)) and normalize(t.text) == '继续挑战']
    if len(lives) != 1 or len(buttons) != 1:
        return None
    hp = int(lives[0][1])
    maximum = int(lives[0][2]) if lives[0][2] is not None else 100
    if 1 <= hp <= maximum <= 100:
        return node, hp, buttons[0]
    return None


def survived_loss_receipt(attempt, start):
    """Verify the structure of the native two-frame loss receipt."""
    frames = attempt.get('loss_frames')
    target = start.get('target')
    hp = attempt.get('remaining_hp')
    if (attempt.get('result_kind') != 'node_loss' or attempt.get('node_loss_verified') is not True
            or attempt.get('node_verified') is not False or type(hp) is not int
            or not isinstance(target, list) or len(target) != 4 or target[0] != attempt.get('node')
            or type(target[2]) is not int or not 1 <= hp <= target[2] <= 100
            or not isinstance(attempt.get('loss_run_dir'), str) or not attempt['loss_run_dir']
            or not isinstance(frames, list) or len(frames) != 2):
        return False
    for frame in frames:
        if (not isinstance(frame, dict) or not isinstance(frame.get('evidence'), str) or not frame['evidence']
                or not isinstance(frame.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', frame['sha256'])
                or type(frame.get('captured_at')) not in (int, float) or not math.isfinite(frame['captured_at'])
                or type(frame.get('input_epoch')) is not int or frame['input_epoch'] < 0):
            return False
    first, second = frames
    return (first['input_epoch'] == second['input_epoch'] and first['captured_at'] < second['captured_at']
            and first['evidence'] != second['evidence'] == attempt.get('result'))


def original_loss_files(session, runs_root):
    attempt = session['node_attempt']
    try:
        index = attempt['start_action_id']
        if type(index) is not int or not 0 <= index < len(session['actions']):
            raise ValueError('invalid start action')
        start = session['actions'][index]
        if not survived_loss_receipt(attempt, start):
            raise ValueError('invalid loss receipt')
        directory = Path(attempt['loss_run_dir']).resolve(strict=True)
        sources = tuple((Path(frame['evidence']).resolve(strict=True), frame['sha256'])
                        for frame in attempt['loss_frames'])
        if (directory.parent != Path(runs_root).resolve() or sources[0][0] == sources[1][0]
                or any(path.parent != directory for path, _ in sources)):
            raise ValueError('outside original run')
        return sources
    except (IndexError, KeyError, OSError, TypeError, ValueError) as error:
        raise AutomationError('失利推进缺少原运行中的两张有效证据。') from error


def _record_survived_loss(c, store, guard, action, pair):
    from .currency_wars_initial import evidence_ref
    from .currency_wars_standard_flow import evidence

    attempt = store.data['node_attempt']
    scene, hp = pair[-1]
    node, epoch = attempt['node'], c.runner.input_epoch
    guard._require_current_scene(scene)
    frames = []
    for index, (capture, _) in enumerate(pair, 1):
        path = evidence(c, capture, f'currency_standard_loss_frame_{index}')
        reference = evidence_ref(capture, path, c.report.run_dir)
        frames.append(dict(evidence=reference['path'], sha256=reference['sha256'],
                           captured_at=capture.captured_at, input_epoch=epoch))
    guard._require_current_scene(scene)
    confidence = c.settings.ocr_confidence
    current = read_survived_loss(scene, confidence)
    if (current is None or current[:2] != (node, hp)
            or account_key(scene, confidence) != store.data.get('account_key')):
        raise AutomationError('留证期间节点失利结果或账号改变，未继续。')
    result = dict(attempt, status='verified', node_verified=False, node_loss_verified=True,
                  result_kind='node_loss', remaining_hp=hp, loss_run_dir=str(c.report.run_dir),
                  loss_frames=frames, result=frames[-1]['evidence'])
    if not survived_loss_receipt(result, action):
        raise AutomationError('节点失利的两份来源不完整，未继续。')
    attempt.update(result)
    store.persist()
    c.log(f'标准节点{node}失利，剩余小队生命值{hp}，已核实可继续。')


def _discard_current_auto(store, tracker):
    tracker.clear()
    # Historical verified-on facts remain valid. Without a current identity
    # there is no current auto observation, and no unbound frame becomes proof.
    if store.data['node_attempt'].pop('auto_observation', None) is not None:
        store.persist()


def _unreadable_reason(identity_unreadable, result_unreadable):
    if identity_unreadable:
        return '出战后持续未核实当前账号标识，未采用缺读帧的战斗或结算。'
    if result_unreadable:
        return '结算画面已出现，原观察期限内未核实本次节点号。'
    return '出战后持续未识别到对应战斗或结算。'


def _observe_auto(c, store, scene, guard, tracker):
    """Record control state only; never derive a key or click from uncertainty."""
    from .currency_wars_auto import AutoObservation, read_auto
    from .currency_wars_standard_flow import evidence
    try:
        observed = read_auto(scene, c.settings.ocr_confidence)
    except (Stopped, InputInterrupted, FocusLost):
        raise
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
    if kind == 'node_loss':
        loss = read_survived_loss(scene, confidence)
        return loss is not None and loss[0] == node
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
    if attempt.get('node_loss_verified') is True:
        guard._require_current_scene(scene)
        loss = read_survived_loss(scene, c.settings.ocr_confidence)
        if (not survived_loss_receipt(attempt, actions[action_id]) or attempt['status'] != 'verified'
                or loss is None or loss[:2] != (attempt['node'], attempt['remaining_hp'])
                or account_key(scene, c.settings.ocr_confidence) != store.data.get('account_key')):
            raise AutomationError('当前画面与原节点失利结果不符，保留原记录待核对。')
        return scene, True
    elapsed, unseen = 0., 0.
    defeat_frames=[]
    loss_frames = []
    auto_tracker = {}
    latest_stamp = None
    observation_epoch = c.runner.input_epoch
    identity_gap = False
    limit = min(180,c.settings.battle_timeout)
    while elapsed < limit:
        c.checkpoint()
        started, inactive = time.monotonic(), c.runner.inactive_duration
        kind = 'unknown'
        unreadable = True
        identity_unreadable = False
        result_unreadable = False
        if scene is None:
            defeat_frames=[]
            loss_frames.clear()
            _discard_current_auto(store, auto_tracker)
        else:
            guard._require_current_scene(scene)
            if observation_epoch != c.runner.input_epoch:
                observation_epoch = c.runner.input_epoch
                defeat_frames.clear()
                loss_frames.clear()
                _discard_current_auto(store, auto_tracker)
            fresh = latest_stamp is None or scene.captured_at > latest_stamp
            if fresh:
                latest_stamp = scene.captured_at
            try:
                observed_account = account_key(scene,max(.85,c.settings.ocr_confidence))
            except (Stopped, InputInterrupted, FocusLost):
                raise
            except AutomationError:
                # A missing/conflicting UID proves nothing about this frame.
                # Keep the existing bounded observation deadline; never carry
                # an incomplete auto-on proof across an identity gap.
                identity_unreadable = True
                if not identity_gap:
                    c.log('标准节点'+attempt['node']+'当前账号标识暂不可读，仅在原观察期限内重新采集。')
                identity_gap = True
            else:
                if observed_account != store.data.get('account_key'):
                    raise AutomationError('节点观察账号来源不一致。')
                identity_gap = False
                if fresh:
                    kind = observe(scene,c.settings.ocr_confidence).page_kind
            if kind!='match_defeat':defeat_frames=[]
            if kind != 'node_loss':
                loss_frames.clear()
            unreadable = kind in ('unknown','preparation')
            if kind=='battle':
                actual = battle_node(scene,c.settings.ocr_confidence)
                unreadable = actual is None
                if unreadable:
                    _discard_current_auto(store, auto_tracker)
                if actual is not None and actual != attempt['node']:
                    _discard_current_auto(store, auto_tracker)
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
            elif kind == 'node_loss':
                confidence = c.settings.ocr_confidence
                loss = read_survived_loss(scene, confidence)
                try:
                    same_account = account_key(scene, confidence) == observed_account
                except AutomationError:
                    same_account = False
                if loss is None or not same_account:
                    loss_frames.clear()
                    unreadable = True
                else:
                    node, hp, _ = loss
                    target = actions[action_id]['target']
                    starting_hp = target[2] if isinstance(target, list) and len(target) == 4 else None
                    if (node != attempt['node'] or type(starting_hp) is not int or not hp <= starting_hp <= 100
                            or store.data.get('match_victory_observed') or store.data.get('match_defeat_observed')):
                        attempt.update(status='unknown', reason='节点失利与原出战、生命值或终局来源不符。')
                        break
                    if loss_frames and loss_frames[-1][1] != hp:
                        loss_frames.clear()
                    loss_frames.append((scene, hp))
                    if len(loss_frames) == 2:
                        _record_survived_loss(c, store, guard, actions[action_id], loss_frames)
                        return scene, True
            elif kind in ('node_result','final_victory','match_defeat'):
                nodes = result_nodes(scene, c.settings.ocr_confidence)
                if not nodes:
                    unreadable = result_unreadable = True
                    defeat_frames.clear()
                    _discard_current_auto(store, auto_tracker)
                elif kind == 'match_defeat':
                    if nodes != {attempt['node']} or store.data.get('match_victory_observed') is True:
                        attempt.update(status='unknown',reason='整局结束与本次出战或原胜利状态不符。')
                        break
                    defeat_frames.append(evidence(c,scene,'currency_standard_defeat_frame_'+str(len(defeat_frames)+1)))
                    if len(defeat_frames)==2:
                        attempt.update(status='defeated',node_verified=False,defeat_observed=True,result_kind='match_defeat',
                            result=defeat_frames[-1],defeat_frames=defeat_frames,verification='matching_terminal_defeat_after_start')
                        store.data.update(match_defeat_observed=True,defeat_start_action_id=action_id)
                        store.persist();c.log('标准节点'+attempt['node']+'整局结束已观察；等待零生命与独立失败结算核验。')
                        return scene,True
                else:
                    same = nodes == {attempt['node']} and (kind != 'final_victory' or attempt['node'].startswith('3-'))
                    attempt.update(status='verified' if same else 'unknown',node_verified=same,
                                   result_kind=kind,
                                   result=evidence(c,scene,'currency_standard_node_result'),
                                   verification='matching_result_after_start' if same else 'wrong_result_node')
                    if same and kind == 'final_victory':
                        store.data.update(match_victory_observed=True, victory_start_action_id=action_id)
                    if not same:
                        reason = '结算节点号有冲突，已停止推进。' if len(nodes) > 1 else '结算与本次出战节点不符，已停止推进。'
                        attempt['reason'] = reason
                        store.data.update(action_status='node_unverified', reason=reason)
                    store.persist()
                    c.log('标准节点'+attempt['node']+('胜利已核实；整局尚未完成。' if same else '结算编号不符，停止推进。'))
                    return scene, same
            elif unreadable:
                _discard_current_auto(store, auto_tracker)
            else:
                attempt.update(status='unknown',reason='出战后出现未校准页面：'+kind)
                break
        c.sleep(2)
        duration = max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        elapsed += duration
        if unreadable:
            unseen += duration
            if unseen >= 30:
                attempt.update(status='unknown',reason=_unreadable_reason(identity_unreadable, result_unreadable))
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
            if unseen >= 30:
                attempt.update(status='unknown',reason=_unreadable_reason(identity_unreadable, result_unreadable))
                break
    else:
        attempt.update(status='timeout',reason='标准节点战斗观察超时，未重复出战。')
    if scene is not None:
        guard._require_current_scene(scene)
        attempt['screenshot'] = evidence(c,scene,'currency_standard_node_unknown')
    store.data.update(action_status='node_unverified',reason=attempt.get('reason','节点结算未核实。'))
    store.persist()
    return scene, False
