"""Same-run evidence for inputs on the calibrated standard double-supply page."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
import math
from pathlib import Path
import re

from .currency_wars_initial import evidence_ref, source_file_ref
from .currency_wars_standard_encounter import _scope as standard_scope, same_account
from .currency_wars_supply_observation import DOUBLE_SUPPLY_LAYOUT, double_supply_rows
from .models import AutomationError, Stopped
from .storage import hold_read_sources


INTENTS = frozenset(('refresh_standard_supply', 'select_standard_supply', 'confirm_standard_supply'))
ARRIVAL = 'double_supply_arrival'
INPUT = 'double_supply_input'
FEEDBACK = 'double_supply_feedback'


def _double_table(candidates):
    return bool(candidates and candidates[0].get('layout') == DOUBLE_SUPPLY_LAYOUT)


def same_journal(durable, live):
    # Previously collected profiles may contain in-memory tuples. On disk the
    # same record represents them as arrays, without changing any evidence.
    try:
        return (durable == live or json.dumps(durable, sort_keys=True, allow_nan=False)
                == json.dumps(live, sort_keys=True, allow_nan=False))
    except (TypeError, ValueError):
        return False


def input_state(session, start):
    keys = ('match_id', 'status', 'mode', 'rank', 'wealth', 'start_verified', 'entry', 'account_key',
            'account_verified_run', 'account_verified_epoch', 'client', 'reward', 'collection', 'rules_version',
            'strategy', 'loop_owner')
    return tuple(session.get(key) for key in keys), session['actions'][start:]


def record_arrival(session, action, scene, confidence):
    if double_supply_rows(scene, confidence) is None:
        return
    reward = session['reward']
    root, epoch = reward['basis']['run_dir'], action['input_epoch']
    scope = standard_scope(session, root, epoch)
    start = session['actions'][action['target'][1]]
    original = start.get('encounter_origin', {})
    if scope is None or original.get('scope') != scope:
        return
    try:
        if not same_account(scene, session, confidence):
            return
        first = original['before']
        before = source_file_ref(start['before'], root)
        after = evidence_ref(scene, action['after'], root)
        if (first['source'] != before or before['path'] == after['path']
                or not first['captured_at'] < scene.captured_at):
            return
    except (AutomationError, KeyError, TypeError):
        return
    action[ARRIVAL] = dict(scope=scope, origin=[before, after], captured_at=scene.captured_at)


def _sources(session, root, epoch):
    from .currency_wars_standard_supply_refresh import _source

    reward = session['reward']
    basis = reward['basis']
    scope = standard_scope(session, root, epoch)
    if (scope is None
            or reward.get('status') != 'awaiting' or basis.get('run_dir') != root or basis.get('input_epoch') != epoch):
        raise AutomationError('双件补给缺少本次标准 A8-40 对局、账号或原备战来源。')
    actions, index = session['actions'], reward['origin_action_id']
    _source(actions, index, basis['node'])
    arrival = actions[index]
    start = actions[arrival['target'][1]]
    original = arrival.get(ARRIVAL, {})
    if original.get('scope') != scope or start.get('input_epoch') != epoch or arrival.get('input_epoch') != epoch:
        raise AutomationError('双件补给的原出战或到达未绑定本次采集。')
    origin = [source_file_ref(start['before'], root), source_file_ref(arrival['after'], root)]
    if origin != original.get('origin') or start.get('encounter_origin', {}).get('before', {}).get('source') != origin[0]:
        raise AutomationError('双件补给的原出战或到达画面已改变。')
    sources = list(origin)
    last_time = original['captured_at']
    for item in actions[index + 1:-1]:
        record, feedback = item.get(INPUT, {}), item.get(FEEDBACK, [])
        if (item.get('action') not in INTENTS - {'confirm_standard_supply'} or not valid_record(item, actions)
                or record['captured_at'] < last_time):
            raise AutomationError('双件补给的刷新或选中回执未绑定本次原画面。')
        first, second = feedback
        sources.extend((record['before'], first['evidence'], second['evidence']))
        last_time = second['captured_at']
    return index, origin, sources, last_time


def _record(session, action, scene, root, epoch):
    try:
        index, origin, sources, last_time = _sources(session, root, epoch)
        before = evidence_ref(scene, action['before'], root)
        if (action.get('input_epoch') != epoch or action['target'][1] != index
                or not math.isfinite(scene.captured_at) or scene.captured_at < last_time):
            raise AutomationError('双件补给的本次动作和当前画面与原回执不符。')
        return (dict(run_dir=root, input_epoch=epoch, origin_action_id=index, origin=origin,
                     before=before, captured_at=scene.captured_at), tuple([*sources, before]))
    except (AttributeError, KeyError, IndexError, OSError, TypeError, ValueError) as error:
        raise AutomationError('双件补给的本次动作或原始画面不可核实。') from error


def bind(session, scene, candidates):
    if _double_table(candidates):
        action = session['actions'][-1]
        root = session['account_verified_run']
        record, _ = _record(session, action, scene, root, action['input_epoch'])
        action[INPUT] = record


def dispatch_sources(session, choice, scene, root, epoch, confidence):
    if choice.intent not in INTENTS:
        return ()
    from .currency_wars_standard_supply_refresh import table

    action = session['actions'][-1]
    candidates = table(scene, confidence)
    if not _double_table(candidates):
        if INPUT in action:
            raise AutomationError('双件补给的当前版式已改变。')
        return ()
    saved = (action.get('supply_refresh_origin', {}).get('before_table') if choice.intent == 'refresh_standard_supply'
             else action.get('supply_candidate_table'))
    record, sources = _record(session, action, scene, root, epoch)
    if saved != candidates or action.get(INPUT) != record:
        raise AutomationError('双件补给的完整候选或原生来源与落盘意图不一致。')
    _require_files(sources, root)
    return sources


def valid_record(action, actions):
    try:
        record, frames = action[INPUT], action[FEEDBACK]
        index = action['target'][1]
        if type(index) is not int or not 0 <= index < action['id']:
            return False
        origin = actions[index][ARRIVAL]
        first, second = frames
        stamps = (origin['captured_at'], record['captured_at'], first['captured_at'], second['captured_at'])
        files = [record['before'], first['evidence'], second['evidence']]
        return (action['status'] == 'verified' and record['origin_action_id'] == index
                and record['origin'] == origin['origin'] and record['run_dir'] == origin['scope']['run_dir']
                and action['input_epoch'] == record['input_epoch'] == origin['scope']['input_epoch']
                and all(type(stamp) in (int, float) and math.isfinite(stamp) for stamp in stamps)
                and stamps[0] <= stamps[1] < stamps[2] < stamps[3]
                and files[0]['path'] == action['before'] and files[2]['path'] == action['after']
                and len({file['path'] for file in files}) == len(files)
                and all(re.fullmatch('[0-9a-f]{64}', file['sha256']) for file in files))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False


def _require_files(sources, root):
    for source in sources:
        if source_file_ref(source['path'], root) != source:
            raise AutomationError('双件补给的原出战、候选或回执画面已改变。')


@contextmanager
def hold_delivery_sources(session):
    from .currency_wars_standard_supply_refresh import valid_claim_chain

    reward = session.get('reward', {})
    if reward.get('status') != 'unit_verifying' or not session.get('collection', {}).get('complete'):
        yield
        return
    actions = session['actions']
    action = actions[reward['claim_action_id']]
    if not _double_table(action.get('supply_candidate_table')):
        yield
        return
    if not valid_claim_chain(action, actions):
        raise AutomationError('双件补给的选中或确认回执缺失，未结清交付。')
    origin = action[INPUT]
    scope = actions[origin['origin_action_id']][ARRIVAL]['scope']
    if (session.get('match_id') != scope.get('match_id') or session.get('account_key') != scope.get('account_key')
            or session.get('client', {}).get('sha256') != scope.get('client_sha256')):
        raise AutomationError('双件补给的交付回执属于其他对局、账号或客户端。')
    sources = list(origin['origin'])
    for step in actions[origin['origin_action_id'] + 1:action['id'] + 1]:
        sources.append(step[INPUT]['before'])
        sources.extend(frame['evidence'] for frame in step[FEEDBACK])
    with hold_read_sources(Path(source['path']) for source in sources):
        _require_files(sources, origin['run_dir'])
        yield


def feedback_key(choice, scene, confidence):
    if choice.intent == 'confirm_standard_supply':
        from .currency_wars_equipment_catalog import inventory, inventory_counts
        from .currency_wars_match import read_match

        state = read_match(scene, confidence)
        if state is None:
            raise AutomationError('双件补给尚未回到可读备战。')
        return ('preparation', state.node, state.gold, state.hp, state.level, state.experience, state.deployment,
                dict(inventory_counts(inventory(scene, confidence))))
    from .currency_wars_standard_supply_refresh import table

    return ('supply_selection', table(scene, confidence))


def commit_feedback(c, store, guard, choice, before, captures, write_evidence):
    from .currency_wars_standard_rewards import returned
    from .currency_wars_standard_supply_refresh import refreshed

    previous = store.data
    root, epoch, confidence = c.report.run_dir, c.runner.input_epoch, c.settings.ocr_confidence
    (first_stamp, first), (second_stamp, after) = captures
    action = dict(previous['actions'][-1], status='verified',
                  after=write_evidence(after, 'currency_standard_after_' + choice.intent))
    first_path = write_evidence(first, 'currency_standard_first_' + choice.intent)
    if first is after or first_stamp != first.captured_at or second_stamp != after.captured_at:
        raise AutomationError('双件补给反馈缺少两张递增的新画面。')
    action[FEEDBACK] = [
        dict(captured_at=frame.captured_at, evidence=evidence_ref(frame, path, root))
        for frame, path in ((first, first_path), (after, action['after']))
    ]
    session = dict(previous, actions=[*previous['actions'][:-1], action], reward=deepcopy(previous['reward']),
                   action_status='transition_verified', screenshot=action['after'])
    if not valid_record(action, session['actions']):
        raise AutomationError('双件补给反馈未对应本次动作的两份原画面。')
    if choice.intent == 'refresh_standard_supply':
        refreshed(session, choice, after, confidence)
    else:
        session.pop('collection', None)
        if choice.intent == 'confirm_standard_supply':
            returned(session, choice, after, confidence)
    sources = dispatch_sources(previous, choice, before, root, epoch, confidence)
    sources += tuple(frame['evidence'] for frame in action[FEEDBACK])

    window, image, geometry = c.window, after.image, after.geometry
    tokens, field_reads = tuple(after.tokens), after.field_reads.copy()

    def pending_unchanged():
        if (not same_journal(store.require_pending(choice.intent, epoch), previous)
                or not same_account(after, previous, confidence)):
            raise AutomationError('双件补给回执的原意图或账号已改变。')
        window.guard(geometry)
        if window.emergency_pressed() or c.runner.stop_requested:
            raise Stopped('双件补给回执写入前任务已停止。')
        guard._require_current_scene(after)
        if (c.runner.input_epoch != epoch or c.window is not window or c.currency_standard_session is not store
                or c.report.run_dir != root or store.data is not session or c.settings.ocr_confidence != confidence
                or after.image is not image or image.flags.writeable or after.geometry != geometry
                or after.captured_at != second_stamp or tuple(after.tokens) != tokens or after.field_reads != field_reads):
            raise AutomationError('双件补给回执的当前画面、窗口或代次已改变。')

    c.checkpoint()
    with ExitStack() as held:
        held.enter_context(hold_read_sources(Path(source['path']) for source in sources))
        _require_files(sources, root)
        if image.flags.writeable:
            image.setflags(write=False)
            held.callback(image.setflags, write=True)
        store.data = session
        try:
            store.persist(before_replace=pending_unchanged)
        except Exception:
            store.data = previous
            raise
    c.report.currency_wars = session
