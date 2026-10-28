"""Standard A8-40 development flow. Only observed and validated inputs run."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .currency_wars_navigation import locate, unique
from .currency_wars_prepare import trusted
from .currency_wars_session import StandardSession
from .currency_wars_standard import difficulty_page, selected_rank
from .models import AutomationError, EmptyCapture, TaskResult
from .models import Token


@dataclass(frozen=True)
class StandardAction:
    intent: str
    expected: str
    target: object
    details: tuple = ()
    payload: tuple = ()


def next_action(scene, confidence=.65, *, session=None):
    clean = trusted(scene, confidence)
    if difficulty_page(scene, confidence) and selected_rank(scene, confidence) == 40:
        return StandardAction('start_standard_a8_40', 'boss_preview',
                              unique(clean, '开始对局', (.75, .82, .99, .97)))
    kind = observe(scene, confidence).page_kind
    from .currency_wars_standard_progress import progress_action
    progress = progress_action(scene, session or {}, confidence)
    if progress is not None:
        return progress
    if kind == 'boss_preview':
        return StandardAction('advance_standard_preview', 'plane_map',
                              unique(clean, '下一步', (.74, .87, .84, .95)))
    if kind == 'plane_map':
        return StandardAction('advance_standard_plane', 'environment',
                              unique(clean, '点击空白处继续', (.43, .86, .57, .93)))
    if kind == 'shop':
        from .currency_wars_standard_market import close_standard_shop
        target = close_standard_shop(scene,session or {},confidence)
        before = session['pre_shop_snapshot']
        return StandardAction('close_standard_shop','standard_shop_closed',target,
                              payload=tuple(before[k] for k in ('node','gold','hp','level')))
    if kind == 'environment':
        if scene.image is None:
            raise AutomationError('环境选择缺少当前图像，未发送输入。')
        from .currency_wars_environment import standard_environment_choice, standard_environment_confirm, ENVIRONMENT_POLICY
        choice = standard_environment_choice(scene, confidence)
        details = (choice.name.text, choice.kind, choice.effect, choice.parameters, choice.score,
                   choice.reason, ENVIRONMENT_POLICY)
        try:
            target = standard_environment_confirm(scene, choice, confidence)
        except AutomationError:
            return StandardAction('select_standard_environment_'+str(choice.slot),
                                  'environment_selected_'+str(choice.slot), choice.name, details)
        expected_board = (session or {}).get('expected_board')
        return StandardAction('confirm_standard_environment_'+str(choice.slot), 'initial_board', target, details,
                              payload=(expected_board,) if expected_board else ())
    if kind == 'preparation':
        from .currency_wars_node import loot_centers
        from .currency_wars_loot import loot_target
        if loot_centers(scene):
            x, y, radius = loot_target(scene, confidence)
            return StandardAction('collect_standard_loot', 'loot_collected',
                                  Token('已核实奖励晶矿', 1., (x-radius,y-radius*16/9,x+radius,y+radius*16/9)),
                                  payload=(x,y,radius))
        from .currency_wars_collector import first_unit_probe
        probe = first_unit_probe(scene, confidence, (session or {}).get('collection',{}).get('units'))
        if probe is None:
            from .currency_wars_standard_market import open_standard_shop
            from .currency_wars_match import read_match
            state = read_match(scene,confidence)
            if state.node in (session or {}).get('shop_observed_nodes',[]):
                from .currency_wars_standard_deployment import standard_deployment, POLICY
                deployment = standard_deployment(scene,session or {},confidence)
                if deployment is None:
                    attempt = (session or {}).get('node_attempt',{})
                    actions = (session or {}).get('actions',[])
                    own_pending = bool(actions and actions[-1].get('action')=='start_standard_node'
                                       and actions[-1].get('status')=='pending'
                                       and attempt.get('start_action_id')==actions[-1].get('id')
                                       and attempt.get('status')=='start_pending')
                    if attempt.get('node')==state.node and not own_pending:
                        raise AutomationError('本节点已有出战提交，未重复出战。')
                    from .currency_wars_node import start_target
                    return StandardAction('start_standard_node','standard_node_entered',start_target(scene,confidence),
                                          payload=(state.node,state.gold,state.hp,state.level))
                plan,unit,score,payload = deployment
                return StandardAction('deploy_standard_owned','standard_owned_deployed',plan,
                                      details=(unit.name,unit.star,unit.tier,plan.zone,score,POLICY),payload=payload)
            target = open_standard_shop(scene,session or {},confidence)
            return StandardAction('open_standard_shop','standard_shop_observe',target,
                                  payload=(state.node,state.gold,state.hp,state.level))
        cell, target = probe
        return StandardAction('inspect_standard_unit', 'character', target,
                              payload=(cell.zone,cell.slot,cell.node,cell.signature))
    if kind == 'character':
        from .currency_wars_collector import owned_profile
        profile = owned_profile(scene,(session or {}).get('inspecting'),confidence)
        key = profile.zone+':'+str(profile.slot)
        record = (session or {}).get('collection',{}).get('units',{}).get(key)
        if not record or record.get('unit') != asdict(profile):
            raise AutomationError('当前角色信息尚未记入本次采集，未关闭面板。')
        return StandardAction('close_standard_unit','preparation',
                              Token('关闭已采集角色面板',1.,(.49,.49,.51,.51)))
    raise AutomationError('标准对局当前页面需要局面采集或新动作校准：' + kind)


def evidence(c, scene, label):
    from .currency_wars_replay import save_sample
    screenshot = c.evidence(scene, label)
    save_sample(scene, screenshot, stage='entry')
    return str(screenshot)


def transition_ready(choice, scene, confidence=.65, *, before=None):
    if choice.expected == 'standard_node_advanced':
        from .currency_wars_standard_progress import advancement_feedback
        return advancement_feedback(scene, choice.payload[0], confidence) is not None
    if choice.expected == 'standard_plane_entered':
        return observe(scene, confidence).page_kind in ('environment', 'investment_selection')
    if choice.expected == 'standard_arrival_shop_closed':
        from .currency_wars_match import read_match
        state = read_match(scene, confidence)
        return bool(state and state.page == 'preparation' and (state.node, state.gold, state.level) == choice.payload[:3]
                    and state.hp is not None and state.hp > 0)
    if choice.expected == 'standard_node_entered':
        from .currency_wars_standard_node import entry_feedback
        return entry_feedback(scene,choice.payload[0],confidence)
    if choice.expected == 'standard_owned_deployed':
        from .currency_wars_standard_deployment import deployment_feedback
        return bool(before is not None and deployment_feedback(before,scene,choice.target,confidence)['status']=='verified')
    if choice.expected == 'standard_shop_closed':
        from .currency_wars_match import read_match
        state = read_match(scene,confidence)
        return bool(state and state.page=='preparation'
                    and (state.node,state.gold,state.hp,state.level)==choice.payload)
    if choice.expected == 'standard_shop_observe':
        from .currency_wars_match import read_match
        state = read_match(scene,confidence)
        node,gold,hp,level = choice.payload
        return bool(state and state.page=='shop' and (state.node,state.gold,state.level)==(node,gold,level)
                    and state.hp in (None,hp))
    if choice.expected == 'loot_collected':
        from .currency_wars_loot import loot_feedback
        return before is not None and loot_feedback(before, scene, choice.payload, confidence) in ('disappeared','choice_opened')
    if choice.expected.startswith('environment_selected_'):
        from .currency_wars_environment import standard_environment_choice, standard_environment_confirm
        try:
            picked = standard_environment_choice(scene, confidence)
            standard_environment_confirm(scene, picked, confidence)
            return picked.slot == int(choice.expected.rsplit('_',1)[1])
        except AutomationError:
            return False
    if choice.expected == 'initial_board':
        from .currency_wars_match import read_match
        state = read_match(scene, confidence)
        expected_node = choice.payload[0] if choice.payload else '1-1'
        return bool(state and state.node == expected_node and state.page in ('shop','preparation'))
    return observe(scene, confidence).page_kind == choice.expected


def run_standard(c):
    if c.report.operation != 'currency_wars_standard':
        raise AutomationError('标准对局开发须使用独立入口。')
    # This initial path is intentionally not an acceptance counter. Any repair
    # or development continuation is recorded separately from ten frozen runs.
    store = StandardSession(Path(c.report.run_dir).parent/'currency-standard-session.json')
    c.currency_standard_session = store
    if store.data is not None and not c.runner.currency_resume:
        raise AutomationError('已有标准对局记录，请使用明确的接续入口核对当前局，未重开。')
    if c.runner.currency_resume:
        if store.data is None or store.data['status'] != 'active':
            raise AutomationError('没有已核实开始且可接续的标准对局；未知开局未重放。')
        if (store.data['actions'] and store.data['actions'][-1]['status'] != 'verified'
                and store.data['actions'][-1]['action'] != 'open_standard_shop'):
            raise AutomationError('上次标准动作尚未核实，先核对反馈，未接续输入。')
        store.data.setdefault('continuations', []).append(str(c.report.run_dir))
        store.persist()
    else:
        result = locate(c)
        entry = c.report.currency_wars
        if not entry.get('rank_verified'):
            return result
        store.begin(c.report.run_dir, entry)
    c.report.currency_wars = store.data
    guard = CurrencyWarsWorkflow(c)
    scene = c.snapshot()
    for _ in range(40):
        c.checkpoint()
        if store.data['completion_verified']:
            break
        guard._require_current_scene(scene)
        if (store.data.get('account_verified_run') != c.report.run_dir or
                store.data.get('account_verified_epoch') != c.runner.input_epoch):
            from .currency_wars_identity import bind_account, refresh_client
            bind_account(store,scene,c.report.run_dir,c.runner.input_epoch,max(.85,c.settings.ocr_confidence))
            refresh_client(store,getattr(getattr(c,'window',None),'path',None),c.report.run_dir,c.runner.input_epoch)
            c.log('标准对局来源：账号一致；客户端安装版本' +
                  store.data.get('client',{}).get('full_version','仍未知') + '。')
            guard._require_current_scene(scene)
        if store.data['actions'] and store.data['actions'][-1]['status'] != 'verified':
            # Only this read-only UI transition may be reconciled here. It
            # never resends the prior click and cannot settle a paid action.
            previous = store.data['actions'][-1]
            payload = tuple(previous.get('target',()))
            before = store.data.get('pre_shop_snapshot',{})
            if (previous['action'] != 'open_standard_shop' or previous.get('expected') != 'standard_shop_observe'
                    or payload != tuple(before.get(name) for name in ('node','gold','hp','level'))
                    or not transition_ready(StandardAction(previous['action'],previous['expected'],None,payload=payload),
                                            scene,c.settings.ocr_confidence)):
                raise AutomationError('上次标准动作尚未核实，未重放输入或继续交易。')
            previous.update(original_status=previous['status'],status='verified',
                            reconciliation='observed_shop_without_input',resolved_run=c.report.run_dir,
                            reconciled_after=evidence(c,scene,'currency_standard_shop_reconciled'))
            store.data.update(action_status='readonly_reconciled',screenshot=previous['reconciled_after'])
            store.persist()
            c.log('已观察核实上次打开标准商店，本次没有重发开店点击。')
        collection = store.data.get('collection',{})
        if collection.get('run_dir') != c.report.run_dir or collection.get('input_epoch') != c.runner.input_epoch:
            collection = dict(run_dir=c.report.run_dir,input_epoch=c.runner.input_epoch,units={},complete=False)
            store.data['collection'] = collection
            store.persist()
        kind = observe(scene,c.settings.ocr_confidence).page_kind
        if kind in ('battle','node_result','final_victory'):
            from .currency_wars_standard_node import observe_started_node
            scene, verified = observe_started_node(c,store,scene)
            if not verified:
                break
            kind = observe(scene,c.settings.ocr_confidence).page_kind
        if kind == 'preparation':
            from .currency_wars_collector import first_unit_probe
            try:
                collection['complete'] = first_unit_probe(scene,c.settings.ocr_confidence,collection['units']) is None
            except AutomationError:
                collection['complete'] = False
            store.persist()
        if kind == 'character':
            from .currency_wars_collector import owned_profile
            try:
                profile = owned_profile(scene,store.data.get('inspecting'),c.settings.ocr_confidence)
            except AutomationError:
                pass  # next_action records the exact missing field below.
            else:
                inspecting = store.data['inspecting']
                collection['units'][profile.zone+':'+str(profile.slot)] = dict(unit=asdict(profile),
                    signature=inspecting['signature'],node=inspecting['node'],
                    source=evidence(c,scene,'currency_standard_owned_'+str(profile.slot)))
                store.persist()
                c.log(f'阵容采集：{profile.zone}:{profile.slot} {profile.name}，{profile.star}星、{profile.tier}费；已读{len(collection["units"])}张。')
        try:
            choice = next_action(scene, c.settings.ocr_confidence,session=store.data)
        except AutomationError as error:
            from .currency_wars_collector import collected_snapshot, first_unit_probe
            if kind == 'preparation':
                try:
                    collection['complete'] = first_unit_probe(scene,c.settings.ocr_confidence,collection['units']) is None
                except AutomationError:
                    collection['complete'] = False
            current = collected_snapshot(scene,store.data,c.runner.input_epoch,'standard_current',c.settings.ocr_confidence)
            from .currency_wars_planner import OfflineProvider, candidates
            store.data.update(action_status='needs_observation', reason=str(error),
                              page_kind=observe(scene, c.settings.ocr_confidence).page_kind,
                              strategy_snapshot=asdict(current),
                              strategy_candidates=[asdict(candidate) for candidate in candidates(current)],
                              strategy_decision=asdict(OfflineProvider().decide(current)),
                              screenshot=evidence(c, scene, 'currency_standard_observe'))
            if current.roster_complete:
                c.log(f'完整阵容已核实：{len(current.roster)}张角色，备战{current.bench_occupied}/{current.bench_capacity}；缺失事实继续由离线决策要求补充。')
            store.persist()
            break
        if choice.intent == 'start_standard_a8_40' and (store.data['status'] != 'start_pending' or store.data['actions']):
            raise AutomationError('已有标准开局提交，未开始第二个对局。')
        if choice.intent == 'open_standard_shop':
            from .currency_wars_collector import collected_snapshot
            store.data['pre_shop_snapshot'] = asdict(collected_snapshot(scene,store.data,c.runner.input_epoch,
                                                       'before_standard_shop',c.settings.ocr_confidence))
            store.persist()
        action = store.pending(choice.intent, c.runner.input_epoch,
                               evidence(c, scene, 'currency_standard_'+choice.intent), choice.expected)
        if choice.intent == 'deploy_standard_owned':
            action['decision'] = dict(name=choice.details[0],star=choice.details[1],tier=choice.details[2],
                                      zone=choice.details[3],score=choice.details[4],policy=choice.details[5])
            store.persist()
        elif choice.details:
            action['decision'] = dict(name=choice.details[0], kind=choice.details[1], effect=choice.details[2],
                                      parameters=dict(choice.details[3]), score=choice.details[4],
                                      reason=choice.details[5], policy=choice.details[6])
            store.persist()
        if choice.payload:
            action['target'] = list(choice.payload)
            store.persist()
        if choice.intent == 'start_standard_node':
            store.data['node_attempt'] = dict(node=choice.payload[0],start_action_id=action['id'],
                                              status='start_pending',node_verified=False,battle_observed=False)
            store.persist()
        c.report.currency_wars = store.data
        c.log('标准A8-40开发：' + choice.intent)
        c.currency_standard_input(scene, choice)
        elapsed, after, stable = 0., None, 0
        while elapsed < 60:
            started, inactive = time.monotonic(), c.runner.inactive_duration
            try:
                after = c.snapshot()
            except EmptyCapture:
                after = None
            if after is not None:
                guard._require_current_scene(after)
                from .currency_wars_identity import account_key
                try:
                    observed_account = account_key(after, max(.85, c.settings.ocr_confidence))
                except AutomationError:
                    ready = False  # Animation may hide the UID; observe within this deadline.
                else:
                    if observed_account != store.data.get('account_key'):
                        raise AutomationError('标准动作反馈账号来源不一致，原意图保留待核对。')
                    ready = transition_ready(choice, after, c.settings.ocr_confidence, before=scene)
                stable = stable+1 if ready else 0
                required = 2 if choice.expected in ('loot_collected','standard_owned_deployed') else 1
                if stable >= required:
                    action.update(status='verified', after=evidence(c, after, 'currency_standard_after_'+choice.intent))
                    store.data.update(action_status='transition_verified', screenshot=action['after'])
                    if choice.intent == 'start_standard_a8_40':
                        store.data['status'] = 'active'
                        store.data['start_verified'] = True
                    if choice.intent.startswith('confirm_standard_environment_'):
                        store.data['environment'] = action['decision']
                        store.data.pop('expected_board', None)
                    if choice.intent == 'start_standard_node':
                        store.data['node_attempt']['status']='observing'
                    if choice.intent == 'inspect_standard_unit':
                        store.data['inspecting'] = dict(zone=choice.payload[0],slot=choice.payload[1],
                                                        node=choice.payload[2],signature=choice.payload[3],
                                                        before=action['before'],after=action['after'])
                    elif choice.intent == 'deploy_standard_owned':
                        from .currency_wars_standard_deployment import transfer_collection, deployment_feedback
                        action['feedback'] = deployment_feedback(scene,after,choice.target,c.settings.ocr_confidence)
                        transfer_collection(store.data,scene,after,choice.target,action['after'],c.settings.ocr_confidence)
                    elif choice.intent not in ('close_standard_unit','open_standard_shop','close_standard_shop'):
                        store.data.pop('collection',None)
                    if choice.intent == 'close_standard_shop':
                        nodes = store.data.setdefault('shop_observed_nodes',[])
                        if choice.payload[0] not in nodes:
                            nodes.append(choice.payload[0])
                    from .currency_wars_standard_progress import progress_verified
                    progress_verified(store.data, choice, after, c.settings.ocr_confidence)
                    store.persist()
                    scene = after
                    break
            c.sleep(.5)
            elapsed += max(0., time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status'] = 'unknown'
            store.data.update(action_status='unknown', reason='标准动作转换未核实，未重复输入。')
            if after is not None:
                store.data['screenshot'] = evidence(c, after, 'currency_standard_transition_unknown')
            store.persist()
            break
        if store.data['completion_verified']:
            break
    else:
        store.data.update(action_status='step_limit', reason='本次标准开发达到步骤上限。')
        store.persist()
    c.report.currency_wars = store.data
    c.runner.emit(dict(type=TASK, data=store.data))
    if store.data['completion_verified']:
        c.report.safe_next = '本次为开发对局，结算完成不计作独立验收；原始证据已保留。'
        return TaskResult(TASK, 'success', store.data['reason'])
    c.report.safe_next = '先读取标准对局当前局面，再接续已核实动作；不重开或重放未知交易。'
    return TaskResult(TASK, 'partial', store.data.get('reason', '标准对局开发未完成，已留证。'))
