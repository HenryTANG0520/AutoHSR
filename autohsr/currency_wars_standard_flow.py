"""Standard A8-40 development flow. Only observed and validated inputs run."""
from __future__ import annotations

import time
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .currency_wars_navigation import locate, unique
from .currency_wars_prepare import trusted
from .currency_wars_session import StandardSession,require_session_access
from .currency_wars_standard import difficulty_page, selected_rank
from .models import AutomationError, EmptyCapture, TaskResult
from .models import Token, normalize


@dataclass(frozen=True)
class StandardAction:
    intent: str
    expected: str
    target: object
    details: tuple = ()
    payload: tuple = ()


def _preparation_probe(scene,confidence,known,session=None):
    from .currency_wars_collector import first_unit_probe,roster_cells
    # A fresh nineteen-cell scan can prove zero owned units. Failure to read
    # the layout or match the HUD still raises rather than authorizing a shop.
    if any(c.state=='occupied' for c in roster_cells(scene,confidence)):
        return first_unit_probe(scene,confidence,known,session=session)
    if known:
        raise AutomationError('当前空阵容与已采集角色不符，未沿用缓存或自动开店。')
    return None


def next_action(scene, confidence=.65, *, session=None):
    """Re-derive only the exact in-flight proposal; never replay old unknown IO."""
    session = session or {}
    actions = session.get('actions', [])
    pending = actions[-1] if actions and actions[-1].get('status') == 'pending' else None
    prior = dict(session, actions=actions[:-1], rederiving_action=pending) if pending else session
    choice = _next_action(scene, confidence, session=prior)
    if pending and (choice.intent != pending.get('action') or choice.expected != pending.get('expected')
                    or json.dumps(list(choice.payload),sort_keys=True,allow_nan=False)!=json.dumps(pending.get('target', []),sort_keys=True,allow_nan=False)):
        raise AutomationError('当前页面推导结果与已落盘意图不同，未替换或重放动作。')
    return choice


def _next_action(scene, confidence=.65, *, session=None):
    from .currency_wars_standard_popup import active_action as popup_action
    popup=popup_action(scene,session or {},confidence)
    if popup is not None:return popup
    from .currency_wars_standard_consumables import active_action as consumable_action
    consumable=consumable_action(scene,session or {},confidence)
    if consumable is not None:return consumable
    from .currency_wars_standard_investment import active_action as investment_action
    investment = investment_action(scene,session or {},confidence)
    if investment is not None:return investment
    from .currency_wars_standard_equipment import active_action as equipment_action
    equipment = equipment_action(scene,session or {},confidence)
    if equipment is not None:
        return equipment
    from .currency_wars_standard_sale import active_action as sale_action
    sale = sale_action(scene,session or {},confidence)
    if sale is not None:
        return sale
    from .currency_wars_standard_exchange import active_action
    verification = active_action(scene, session or {}, confidence)
    if verification is not None:
        return verification
    from .currency_wars_standard_rewards import active_action as reward_action
    reward = reward_action(scene,session or {},confidence)
    if reward is not None:
        return reward
    clean = trusted(scene, confidence)
    if difficulty_page(scene, confidence) and selected_rank(scene, confidence) == 40:
        return StandardAction('start_standard_a8_40', 'boss_preview',
                              unique(clean, '开始对局', (.75, .82, .99, .97)))
    kind = observe(scene, confidence).page_kind
    from .currency_wars_standard_reorder import active as reordering,proposal as reorder_proposal
    if reordering(session or {}):
        if kind not in ('preparation','character'):
            raise AutomationError('全局整理尚未完成，只允许核实当前角色与移动。')
        if kind=='preparation':
            probe=_preparation_probe(scene,confidence,session.get('collection',{}).get('units'),session)
            if probe is not None:
                cell,target=probe
                return StandardAction('inspect_standard_unit','character',target,payload=(cell.zone,cell.slot,cell.node,cell.signature))
            from .currency_wars_standard_reorder import recommendation_probe
            recommendation=recommendation_probe(scene,session,confidence)
            if recommendation is not None:return recommendation
            return reorder_proposal(scene,session,confidence)
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
        from .currency_wars_standard_trading import purchase_action, shop_return_values
        from .currency_wars_standard_market import close_standard_shop
        last=(session or {}).get('actions',[])
        last=last[-1] if last else {}
        if last.get('action')=='refresh_standard_shop' and last.get('receipt',{}).get('bonus_xp',0)>0:
            payload,_=shop_return_values(scene,session,confidence)
            return StandardAction('close_standard_shop','standard_shop_closed',close_standard_shop(scene,session,confidence),payload=payload)
        purchase = purchase_action(scene, session or {}, confidence)
        if purchase is not None:
            return purchase
        from .currency_wars_standard_refresh import refresh_action
        refresh = refresh_action(scene,session or {},confidence)
        if refresh is not None:
            return refresh
        from .currency_wars_standard_market import close_standard_shop
        target = close_standard_shop(scene,session or {},confidence)
        payload, purchased = shop_return_values(scene, session, confidence)
        return StandardAction('close_standard_shop_after_purchase' if purchased else 'close_standard_shop',
                              'standard_shop_closed', target, payload=payload)
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
        if 'strategy' in (session or {}) and (loot_centers(scene) or any(
                normalize(t.text)=='开启' and t.within((.18,.78,.80,.92)) for t in clean.tokens)):
            probe = _preparation_probe(scene,confidence,session.get('collection',{}).get('units'),session)
            if probe is not None:
                cell,target = probe
                return StandardAction('inspect_standard_unit','character',target,
                                      payload=(cell.zone,cell.slot,cell.node,cell.signature))
        if 'strategy' in (session or {}):
            from .currency_wars_standard_rewards import open_bench_action
            opening = open_bench_action(scene,session,confidence)
            if opening is not None:return opening
        from .currency_wars_loot import loot_target
        if loot_centers(scene):
            x, y, radius = loot_target(scene, confidence)
            return StandardAction('collect_standard_loot', 'loot_collected',
                                  Token('已核实奖励晶矿', 1., (x-radius,y-radius*16/9,x+radius,y+radius*16/9)),
                                  payload=(x,y,radius))
        probe = _preparation_probe(scene,confidence,(session or {}).get('collection',{}).get('units'),session)
        if probe is None:
            from .currency_wars_standard_market import open_standard_shop
            from .currency_wars_match import read_match
            state = read_match(scene,confidence)
            if 'strategy' in (session or {}):
                from .currency_wars_standard_sale import proposal as sale_proposal
                sale = sale_proposal(scene,session,confidence)
                if sale is not None:
                    return sale
            if state.node in (session or {}).get('shop_observed_nodes',[]):
                if 'strategy' in (session or {}) and state.deployment and state.deployment[0] == state.deployment[1]:
                    from .currency_wars_standard_exchange import exchange_proposal
                    exchange = exchange_proposal(scene, session, confidence)
                    if exchange is not None:
                        return exchange
                    reorder=reorder_proposal(scene,session,confidence)
                    if reorder is not None:return reorder
                from .currency_wars_standard_deployment import standard_deployment, POLICY
                deployment = standard_deployment(scene,session or {},confidence)
                if deployment is None:
                    if 'strategy' in (session or {}):
                        from .currency_wars_standard_trading import experience_action
                        experience = experience_action(scene, session, confidence)
                        if experience is not None:
                            return experience
                        from .currency_wars_standard_equipment import proposal as equipment_proposal
                        equipment = equipment_proposal(scene,session,confidence)
                        if equipment is not None:
                            return equipment
                        from .currency_wars_standard_consumables import proposal as consumable_proposal
                        consumable=consumable_proposal(scene,session,confidence)
                        if consumable is not None:return consumable
                    attempt = (session or {}).get('node_attempt',{})
                    actions = (session or {}).get('actions',[])
                    inflight = (session or {}).get('rederiving_action') or (actions[-1] if actions else {})
                    own_pending = bool(inflight.get('action')=='start_standard_node'
                                       and inflight.get('status')=='pending'
                                       and attempt.get('start_action_id')==inflight.get('id')
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
        from .currency_wars_standard_collection import stale,close_action,profile as current_profile,close_current
        if stale(session or {}):return close_action(scene,session or {},confidence)
        profile = current_profile(scene,session,confidence)
        key = profile.zone+':'+str(profile.slot)
        record = (session or {}).get('collection',{}).get('units',{}).get(key)
        if not record or record.get('unit') != asdict(profile):
            raise AutomationError('当前角色信息尚未记入本次采集，未关闭面板。')
        if 'strategy' in (session or {}) and profile.zone != 'bench' and 'recommendations' not in record:
            return StandardAction('open_standard_equipment_recommendations','standard_equipment_recommendations',
                                  unique(clean,'装备推荐',(.72,.70,.85,.80)),
                                  payload=(profile.zone,profile.slot,profile.name,record['signature']))
        return close_current(scene,session,confidence)
    raise AutomationError('标准对局当前页面需要局面采集或新动作校准：' + kind)


def evidence(c, scene, label):
    from .currency_wars_replay import save_sample
    screenshot = c.evidence(scene, label)
    save_sample(scene, screenshot, stage='entry')
    return str(screenshot)


def transition_ready(choice, scene, confidence=.65, *, before=None, session=None):
    from .currency_wars_defeat import INTENTS as DEFEAT_INTENTS,feedback as defeat_feedback
    if choice.intent in DEFEAT_INTENTS:return session is not None and defeat_feedback(choice,scene,session,confidence)
    if choice.expected in ('standard_movement_star_selected','standard_movement_star_returned','standard_popup_unit_board'):
        from .currency_wars_standard_popup import feedback
        return session is not None and feedback(choice,scene,session,confidence)
    if choice.expected=='standard_supply_refreshed':
        from .currency_wars_standard_supply_refresh import feedback
        return before is not None and session is not None and feedback(choice,before,scene,session,confidence)
    if choice.expected in ('standard_consumable_applied','standard_consumable_returned'):
        from .currency_wars_standard_consumables import feedback
        return before is not None and session is not None and feedback(choice,before,scene,session,confidence)
    if choice.expected=='standard_consumable_board':
        from .currency_wars_standard_consumables import board_ready
        try:return session is not None and board_ready(scene,session['consumable'],confidence)
        except (AutomationError,KeyError):return False
    if choice.expected in ('standard_stale_unit_board','standard_collected_unit_board'):
        from .currency_wars_standard_collection import board_feedback
        return board_feedback(choice,scene,confidence,session=session)
    if choice.expected in ('standard_investment_selected','standard_investment_applied'):
        from .currency_wars_standard_investment import feedback
        return session is not None and feedback(choice,scene,session,confidence)
    if choice.expected=='standard_reward_opened':
        from .currency_wars_standard_rewards import PAGES
        from .currency_wars_match import read_match
        state = read_match(scene,confidence,include_rewards=True)
        return bool(state and state.page in PAGES-{'supply_selection'} and state.node==choice.payload[0])
    if choice.expected in ('standard_reward_returned','standard_supply_selected'):
        from .currency_wars_standard_rewards import feedback
        return before is not None and session is not None and feedback(choice,before,scene,session,confidence)
    if choice.expected=='standard_reward_unit_board':
        from .currency_wars_standard_rewards import board_ready
        try:return session is not None and board_ready(scene,session['reward'],confidence)
        except AutomationError:return False
    if choice.expected == 'standard_equipment_inspectable':
        from .currency_wars_standard_equipment import inspectable
        return before is not None and inspectable(choice,before,scene,confidence)
    if choice.expected == 'standard_equipment_board':
        from .currency_wars_standard_equipment import _board
        try:
            return bool(session and _board(scene,session['equipment'],confidence))
        except (AutomationError,KeyError):
            return False
    if choice.expected == 'standard_equipment_recommendations':
        from .currency_wars_equipment_catalog import recommendation_visible
        from .currency_wars_collector import owned_profile
        try:
            profile = owned_profile(scene,(session or {}).get('inspecting'),confidence)
            return recommendation_visible(scene,confidence) and (profile.zone,profile.slot,profile.name)==choice.payload[:3]
        except AutomationError:
            return False
    if choice.expected in ('standard_sale_panel','standard_field_sale_panel'):
        from .currency_wars_standard_sale import panel_feedback
        return before is not None and panel_feedback(choice,before,scene,confidence)
    if choice.expected == 'standard_sale_cancelled':
        from .currency_wars_standard_sale import cancelled_feedback
        return session is not None and cancelled_feedback(scene,session,confidence)
    if choice.expected in ('standard_exchange_inspectable','standard_relocate_inspectable'):
        from .currency_wars_standard_exchange import inspectable
        return before is not None and inspectable(choice, before, scene, confidence)
    if choice.expected == 'standard_exchange_board':
        from .currency_wars_match import read_match
        state = read_match(scene,confidence)
        return bool(state and state.page == 'preparation'
                    and (state.node,state.gold,state.hp,state.level) == choice.payload[:4]
                    and state.deployment == choice.payload[4:6])
    from .currency_wars_standard_ledger import FINANCIAL_ACTIONS
    if choice.intent in FINANCIAL_ACTIONS:
        from .currency_wars_standard_trading import financial_feedback
        return before is not None and financial_feedback(choice, before, scene, confidence,session=session) is not None
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
                    and (state.node,state.gold,state.hp,state.level)==choice.payload[:4]
                    and (len(choice.payload)==4 or (state.experience or (0,0))==choice.payload[4:6]))
    if choice.expected == 'standard_shop_observe':
        from .currency_wars_match import read_match
        state = read_match(scene,confidence)
        node,gold,hp,level = choice.payload
        return bool(state and state.page=='shop' and (state.node,state.gold,state.level)==(node,gold,level)
                    and state.hp in (None,hp))
    if choice.expected == 'loot_collected':
        from .currency_wars_loot import loot_feedback
        result = loot_feedback(before,scene,choice.payload,confidence) if before is not None else None
        if result=='choice_opened' and session is not None:
            from .currency_wars_match import read_match
            source = session.get('actions',[{}])[-1].get('reward_basis')
            state = read_match(scene,confidence,include_rewards=True)
            if source and (not state or state.node!=source['node']):return False
        return result in ('disappeared','choice_opened')
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
    from .currency_wars_standard_ledger import FINANCIAL_ACTIONS
    if c.report.operation != 'currency_wars_standard':
        raise AutomationError('标准对局开发须使用独立入口。')
    # This initial path is intentionally not an acceptance counter. Any repair
    # or development continuation is recorded separately from ten frozen runs.
    store = StandardSession(Path(c.report.run_dir).parent/'currency-standard-session.json')
    c.currency_standard_session = store
    loop_guard = getattr(c.runner, 'currency_loop_guard', None)
    if loop_guard is not None:
        loop_guard.require_access(store.data,c.runner.currency_resume)
    else:
        require_session_access(store.data,c.runner.currency_resume)
    from .currency_wars_standard_policy import STRATEGIES
    from .currency_wars_names import resolve_name
    requested_strategy = getattr(c.runner, 'currency_strategy', None)
    strategy = (store.data or {}).get('strategy',requested_strategy or 'default')
    if strategy not in STRATEGIES or requested_strategy is not None and requested_strategy != strategy:
        raise AutomationError('本次策略与已记录对局不同，未中途改写策略。')
    remembrance_name=resolve_name(c.settings,getattr(c.runner,'currency_remembrance_name',None),store.data,resume=c.runner.currency_resume)
    from .currency_wars_equipment_mode import resolve_fast_mode,FAST_FIELD
    fast_mode=resolve_fast_mode(c.settings,getattr(c.runner,'currency_fast_mode',None),store.data,resume=c.runner.currency_resume)
    if c.runner.currency_resume:
        store.data.setdefault('continuations', []).append(str(c.report.run_dir))
        store.persist()
    else:
        result = locate(c)
        entry = c.report.currency_wars
        if not entry.get('rank_verified'):
            return result
        if store.data is None:
            store.begin(c.report.run_dir, entry)
    store.data['strategy'] = strategy
    store.data['remembrance_name']=remembrance_name
    store.data[FAST_FIELD]=fast_mode
    store.persist()
    if loop_guard is not None:
        loop_guard.bind(store)
    c.report.currency_wars = store.data
    guard = CurrencyWarsWorkflow(c)
    scene = c.snapshot()
    from .currency_wars_standard_budget import StandardBudget
    from .currency_wars_session import MAX_ACTIONS
    budget=StandardBudget(store.data)
    for _ in range(MAX_ACTIONS+1):
        c.checkpoint()
        if store.data['completion_verified'] or store.data.get('defeat_settlement_verified'):
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
        limited=budget.check(store.data)
        if limited:
            store.data.update(action_status='step_limit',reason=limited)
            store.persist();break
        collection = store.data.get('collection',{})
        if collection.get('run_dir') != c.report.run_dir or collection.get('input_epoch') != c.runner.input_epoch:
            collection = dict(run_dir=c.report.run_dir,input_epoch=c.runner.input_epoch,units={},complete=False)
            store.data['collection'] = collection
            store.persist()
        kind = observe(scene,c.settings.ocr_confidence).page_kind
        if kind in ('battle','node_result','final_victory','match_defeat') and store.data.get('exchange',{}).get('status','verified') == 'verified':
            from .currency_wars_standard_node import observe_started_node
            scene, verified = observe_started_node(c,store,scene)
            if not verified:
                break
            kind = observe(scene,c.settings.ocr_confidence).page_kind
        if kind == 'preparation':
            try:
                collection['complete'] = _preparation_probe(scene,c.settings.ocr_confidence,collection['units'],store.data) is None
            except AutomationError:
                collection['complete'] = False
            store.persist()
            from .currency_wars_standard_rewards import verify_unit
            verifying_reward = store.data.get('reward',{}).get('status')=='unit_verifying'
            problem = verify_unit(store.data,scene,c.runner.input_epoch,c.settings.ocr_confidence)
            store.persist()
            if problem:raise AutomationError(problem)
            if verifying_reward and store.data.get('reward',{}).get('status')=='verified':c.checkpoint()
            from .currency_wars_investment_units import verify as verify_investment_units
            verifying_investment=store.data.get('investment',{}).get('status')=='unit_verifying'
            problem=verify_investment_units(store.data,scene,c.runner.input_epoch,c.settings.ocr_confidence)
            store.persist()
            if problem:raise AutomationError(problem)
            if verifying_investment and store.data.get('investment',{}).get('status')=='verified':c.checkpoint()
            from .currency_wars_standard_consumables import verify as verify_consumable
            verifying_consumable=store.data.get('consumable',{}).get('status')=='verifying'
            problem=verify_consumable(store.data,scene,c.runner.input_epoch,c.settings.ocr_confidence)
            store.persist()
            if problem:raise AutomationError(problem)
            if verifying_consumable and store.data.get('consumable',{}).get('status')=='verified':c.checkpoint()
            from .currency_wars_standard_reorder import advance as advance_reorder
            if advance_reorder(store.data,scene,c.settings.ocr_confidence):
                store.persist();c.checkpoint()
        from .currency_wars_standard_exchange import panel_stale, record_profile
        from .currency_wars_standard_sale import stale as sale_stale
        from .currency_wars_standard_equipment import panel_stale as equipment_stale, record_profile as equipment_profile
        from .currency_wars_standard_rewards import panel_stale as reward_stale
        from .currency_wars_standard_consumables import panel_stale as consumable_stale
        from .currency_wars_standard_collection import stale as collection_stale,ordinary,profile as current_profile
        from .currency_wars_standard_popup import panel_stale as popup_stale,profile as popup_profile,require_panel_account
        if kind == 'character' and not panel_stale(store.data) and not sale_stale(store.data) and not equipment_stale(store.data) and not reward_stale(store.data) and not consumable_stale(store.data) and not collection_stale(store.data) and not popup_stale(store.data):
            require_panel_account(scene,store.data,c.settings.ocr_confidence)
            from .currency_wars_collector import owned_profile
            try:
                profile = (current_profile(scene,store.data,c.settings.ocr_confidence) if ordinary(store.data)
                    else owned_profile(scene,store.data.get('inspecting'),c.settings.ocr_confidence))
            except AutomationError:
                pass  # next_action records the exact missing field below.
            else:
                inspecting = store.data['inspecting']
                profile_source = evidence(c,scene,'currency_standard_owned_'+str(profile.slot))
                previous = collection['units'].get(profile.zone+':'+str(profile.slot),{})
                previous = previous if previous.get('signature')==inspecting['signature'] else {}
                collection['units'][profile.zone+':'+str(profile.slot)] = dict(previous,unit=asdict(profile),
                    signature=inspecting['signature'],node=inspecting['node'],
                    source=profile_source,input_epoch=c.runner.input_epoch,run_dir=c.report.run_dir,
                    inspection_action_id=inspecting.get('inspection_action_id'))
                problem = record_profile(store.data,profile,inspecting,profile_source,c.runner.input_epoch)
                problem = problem or equipment_profile(store.data,profile,inspecting,profile_source,c.runner.input_epoch)
                from .currency_wars_worn_reforge import record_profile as worn_reforge_profile
                problem = problem or worn_reforge_profile(store.data,profile,inspecting,profile_source,c.runner.input_epoch)
                problem = problem or popup_profile(store.data,profile,inspecting,profile_source,c.runner.input_epoch,scene,c.settings.ocr_confidence)
                store.persist()
                if problem:
                    raise AutomationError(problem)
                c.log(f'阵容采集：{profile.zone}:{profile.slot} {profile.name}，{profile.star}星、{profile.tier}费；已读{len(collection["units"])}张。')
        from .currency_wars_standard_investment import enter as investment_enter
        if kind=='investment_selection' and (not store.data.get('investment') or store.data['investment'].get('status')=='verified'):
            investment_enter(store.data,scene,c.settings.ocr_confidence)
            store.persist()
        try:
            choice = next_action(scene, c.settings.ocr_confidence,session=store.data)
        except AutomationError as error:
            from .currency_wars_collector import collected_snapshot
            if kind == 'preparation':
                try:
                    collection['complete'] = _preparation_probe(scene,c.settings.ocr_confidence,collection['units'],store.data) is None
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
        if choice.intent == 'start_standard_a8_40' and getattr(c.runner, 'currency_loop_guard', None) is not None:
            c.runner.currency_loop_guard.require_start()
        if choice.intent == 'open_standard_shop':
            from .currency_wars_collector import collected_snapshot
            from .currency_wars_standard_trading import bench_signatures
            store.data['pre_shop_snapshot'] = asdict(collected_snapshot(scene,store.data,c.runner.input_epoch,
                                                       'before_standard_shop',c.settings.ocr_confidence))
            store.data['pre_shop_bench'] = bench_signatures(scene)
            store.persist()
        action = store.pending(choice.intent, c.runner.input_epoch,
                               evidence(c, scene, 'currency_standard_'+choice.intent), choice.expected)
        if choice.intent == 'deploy_standard_owned':
            action['decision'] = dict(name=choice.details[0],star=choice.details[1],tier=choice.details[2],
                                      zone=choice.details[3],score=choice.details[4],policy=choice.details[5])
            store.persist()
        elif choice.intent in FINANCIAL_ACTIONS or choice.intent in ('inspect_standard_sale_unit','inspect_standard_field_sale_unit'):
            action['decision'] = dict(strategy=choice.details[0], score=choice.details[1],
                                      reasons=list(choice.details[2]), policy=choice.details[3])
            store.persist()
        elif choice.intent in ('stage_standard_exchange','stage_standard_relocate'):
            action['decision'] = dict(source=choice.details[0],target=choice.details[1],
                                      improvement=choice.details[2],policy=choice.details[3])
            store.persist()
        elif choice.intent == 'stage_standard_equipment':
            action['decision'] = dict(name=choice.details[0],item=choice.details[1],expected=list(choice.details[2]),
                                      reason=choice.details[3],policy=choice.details[4])
            store.persist()
        elif choice.intent=='stage_standard_consumable':
            action['decision']=dict(item=choice.details[0],effect=choice.details[1],name=choice.details[2],policy=choice.details[3])
            store.persist()
        elif choice.intent=='refresh_standard_supply':
            action['decision']=dict(strategy=choice.details[0],remaining=choice.details[1],need=list(choice.details[2]),policy=choice.details[3])
            store.persist()
        elif choice.intent in ('choose_standard_reward','select_standard_supply','confirm_standard_supply'):
            action['decision'] = dict(name=choice.details[0],item=choice.details[1],unit=choice.details[2],
                                      gold=choice.details[3],policy=choice.details[4])
            if len(choice.payload)==11:
                action['decision'].update(selection_count=choice.payload[9],expected_tier=choice.payload[10])
            store.persist()
        elif choice.intent in ('select_standard_investment','confirm_standard_investment'):
            action['decision']=dict(name=choice.details[0],kind=choice.details[1],parameters=dict(choice.details[2]),policy=choice.details[3])
            from .currency_wars_standard_investment import bind_selection
            bind_selection(store.data,choice,scene,c.runner.input_epoch,c.report.run_dir,c.settings.ocr_confidence)
            store.persist()
        elif choice.details:
            action['decision'] = dict(name=choice.details[0], kind=choice.details[1], effect=choice.details[2],
                                      parameters=dict(choice.details[3]), score=choice.details[4],
                                      reason=choice.details[5], policy=choice.details[6])
            store.persist()
        if choice.payload:
            action['target'] = list(choice.payload)
            store.persist()
        if choice.intent=='inspect_standard_unit':
            from .currency_wars_standard_collection import bind_inspection
            bind_inspection(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        from .currency_wars_standard_popup import bind_move,bind_intent as bind_popup
        bind_move(store.data,choice,scene,c.settings.ocr_confidence)
        bind_popup(store.data,choice,scene,c.settings.ocr_confidence)
        if choice.intent in ('deploy_standard_owned','stage_standard_exchange','stage_standard_relocate','select_standard_movement_star','confirm_standard_movement_star','inspect_standard_popup_unit','close_standard_popup_unit','close_standard_popup_stale_panel'):
            store.persist()
        if choice.intent=='refresh_standard_supply':
            from .currency_wars_standard_supply_refresh import bind_intent
            bind_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent in ('select_standard_supply','confirm_standard_supply'):
            from .currency_wars_standard_supply_refresh import bind_choice
            bind_choice(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent in ('stage_standard_exchange','stage_standard_relocate','inspect_standard_exchange_unit'):
            from .currency_wars_standard_exchange import record_intent
            record_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent in ('inspect_standard_sale_unit','inspect_standard_field_sale_unit'):
            from .currency_wars_standard_sale import bind_intent
            bind_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent == 'stage_standard_equipment':
            from .currency_wars_standard_equipment import bind_intent
            bind_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent=='stage_standard_consumable':
            from .currency_wars_standard_consumables import bind_intent
            bind_intent(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        if choice.intent == 'inspect_standard_equipment_unit':
            store.data['equipment']['inspection_attempts'] += 1
            store.persist()
        if choice.intent == 'start_standard_node':
            store.data['node_attempt'] = dict(node=choice.payload[0],start_action_id=action['id'],
                                              status='start_pending',node_verified=False,battle_observed=False)
            store.persist()
        if choice.intent in ('start_standard_node','collect_standard_loot','open_standard_bench_reward'):
            from .currency_wars_standard_rewards import bind_source
            bind_source(store.data,choice,scene,c.settings.ocr_confidence)
            from .currency_wars_standard_investment import bind_reward
            bind_reward(store.data,choice)
            store.persist()
        if choice.intent in ('close_standard_unit','close_standard_stale_unit'):
            from .currency_wars_standard_collection import bind_close
            bind_close(store.data,choice,scene,c.settings.ocr_confidence)
            store.persist()
        c.report.currency_wars = store.data
        c.log('标准A8-40开发：' + choice.intent)
        c.currency_standard_input(scene, choice)
        elapsed, after, stable, previous_popup = 0., None, 0, None
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
                    from .currency_wars_standard_popup import arrival as popup_arrival
                    popup_stamp=popup_arrival(choice,after,store.data,c.settings.ocr_confidence)
                    ready = bool(popup_stamp) or transition_ready(choice, after, c.settings.ocr_confidence, before=scene,session=store.data)
                    if popup_stamp!=previous_popup:stable=0
                    previous_popup=popup_stamp
                stable = stable+1 if ready else 0
                from .currency_wars_defeat import INTENTS as DEFEAT_INTENTS
                required = 2 if choice.intent in DEFEAT_INTENTS or choice.expected in ('loot_collected','standard_owned_deployed','standard_exchange_inspectable','standard_relocate_inspectable',
                                                    'standard_offer_bought','standard_experience_bought','standard_shop_refreshed',
                                                    'standard_sale_panel','standard_owned_sold','standard_field_sale_panel','standard_field_owned_sold','standard_equipment_inspectable',
                                                    'standard_reward_returned','standard_supply_selected','standard_supply_refreshed',
                                                    'standard_investment_selected','standard_investment_applied',
                                                    'standard_stale_unit_board','standard_collected_unit_board',
                                                    'standard_movement_star_selected','standard_movement_star_returned','standard_popup_unit_board',
                                                    'standard_consumable_applied','standard_consumable_returned','standard_consumable_board') else 1
                if stable >= required:
                    after_path = evidence(c, after, 'currency_standard_after_'+choice.intent)
                    if previous_popup:
                        action.update(status='verified',after=after_path)
                        from .currency_wars_standard_popup import opened
                        opened(store.data,choice,after,c.settings.ocr_confidence)
                        store.persist();scene=after
                        break
                    if choice.intent in FINANCIAL_ACTIONS:
                        from .currency_wars_standard_trading import financial_feedback
                        from .currency_wars_standard_ledger import valid_receipt
                        receipt = financial_feedback(choice, scene, after, c.settings.ocr_confidence,session=store.data)
                        if not valid_receipt(dict(action,status='verified',after=after_path,receipt=receipt)):
                            raise AutomationError('标准交易收据与原意图不符，保留待核对状态。')
                    action.update(status='verified', after=after_path)
                    store.data.update(action_status='transition_verified', screenshot=action['after'])
                    if choice.intent in FINANCIAL_ACTIONS:
                        from .currency_wars_standard_trading import record_financial_feedback
                        record_financial_feedback(store.data, choice, receipt)
                    if choice.intent == 'start_standard_a8_40':
                        store.data['status'] = 'active'
                        store.data['start_verified'] = True
                    if choice.intent.startswith('confirm_standard_environment_'):
                        store.data['environment'] = action['decision']
                        store.data.pop('expected_board', None)
                    if choice.intent == 'start_standard_node':
                        store.data['node_attempt']['status']='observing'
                    if choice.intent in ('inspect_standard_unit','inspect_standard_exchange_unit','inspect_standard_equipment_unit','inspect_standard_reward_unit','inspect_standard_consumable_unit','inspect_standard_popup_unit'):
                        action['inspection_run_dir']=c.report.run_dir
                        store.data['inspecting'] = dict(zone=choice.payload[0],slot=choice.payload[1],
                                                        node=choice.payload[2],signature=choice.payload[3],
                                                        input_epoch=c.runner.input_epoch,
                                                        run_dir=c.report.run_dir,
                                                        before=action['before'],after=action['after'],inspection_action_id=action['id'])
                        if choice.intent == 'inspect_standard_exchange_unit':
                            store.data['inspecting']['exchange_id'] = choice.payload[4]
                        if choice.intent == 'inspect_standard_equipment_unit':
                            store.data['inspecting']['equipment_id'] = choice.payload[4]
                        if choice.intent=='inspect_standard_consumable_unit':
                            store.data['inspecting']['consumable_id']=choice.payload[4]
                    elif choice.intent in ('close_standard_unit','close_standard_stale_unit'):
                        from .currency_wars_standard_collection import closed
                        closed(store.data,choice,after,c.settings.ocr_confidence)
                    elif choice.intent == 'stage_standard_equipment':
                        from .currency_wars_standard_equipment import begin_verification
                        begin_verification(store.data,choice,scene,after,c.settings.ocr_confidence)
                        store.data['action_status'] = 'equipment_identity_pending'
                    elif choice.intent in ('close_standard_equipment_unit','close_standard_equipment_stale_panel'):
                        from .currency_wars_standard_equipment import after_close
                        after_close(store.data,choice,after,c.settings.ocr_confidence)
                        if store.data['equipment']['status']=='verified':
                            store.data['action_status'] = 'equipment_verified'
                    elif choice.intent in ('open_standard_equipment_recommendations','open_standard_consumable_recommendations'):
                        from .currency_wars_equipment_catalog import recommendation_facts
                        record = store.data['collection']['units'][choice.payload[0]+':'+str(choice.payload[1])]
                        names,recipes = recommendation_facts(after,c.settings.ocr_confidence)
                        record['recommendations'] = list(names)
                        record['equipment_recipes'] = list(recipes)
                        record['recommendations_source'] = after_path
                    elif choice.intent in ('close_standard_reward_unit','close_standard_reward_stale_panel'):
                        if choice.intent=='close_standard_reward_stale_panel':
                            store.data.pop('inspecting',None)
                            store.data.pop('collection',None)
                    elif choice.intent in ('stage_standard_consumable','choose_standard_consumable_gear'):
                        from .currency_wars_standard_consumables import applied
                        applied(store.data,choice,after,c.settings.ocr_confidence)
                        store.data['action_status']='consumable_identity_pending'
                    elif choice.intent=='refresh_standard_supply':
                        from .currency_wars_standard_supply_refresh import refreshed
                        refreshed(store.data,choice,after,c.settings.ocr_confidence)
                    elif choice.intent in ('close_standard_consumable_unit','close_standard_consumable_stale_panel'):
                        if choice.intent=='close_standard_consumable_stale_panel':
                            store.data.pop('inspecting',None);store.data.pop('collection',None)
                    elif choice.intent in ('confirm_standard_movement_star','close_standard_popup_unit','close_standard_popup_stale_panel'):
                        from .currency_wars_standard_popup import returned as popup_returned
                        popup_returned(store.data,choice,after,c.settings.ocr_confidence)
                    elif choice.intent in ('inspect_standard_sale_unit','inspect_standard_field_sale_unit'):
                        from .currency_wars_standard_sale import target_zone
                        store.data['inspecting'] = dict(zone=target_zone(choice.payload),slot=choice.payload[4],node=choice.payload[0],
                                                        signature=choice.payload[8],input_epoch=c.runner.input_epoch,
                                                        run_dir=c.report.run_dir,before=action['before'],after=action['after'])
                    elif choice.intent == 'close_standard_sale_stale_panel':
                        from .currency_wars_standard_sale import finish
                        finish(store.data,cancelled=True)
                    elif choice.intent in ('stage_standard_exchange','stage_standard_relocate'):
                        from .currency_wars_standard_exchange import begin_verification
                        begin_verification(store.data,choice,scene,after,c.settings.ocr_confidence)
                        store.data['action_status'] = 'exchange_identity_pending'
                    elif choice.intent in ('close_standard_exchange_unit','close_standard_exchange_stale_panel'):
                        from .currency_wars_standard_exchange import after_close
                        after_close(store.data,choice,after,c.settings.ocr_confidence)
                    elif choice.intent == 'deploy_standard_owned':
                        from .currency_wars_standard_deployment import transfer_collection, deployment_feedback
                        action['feedback'] = deployment_feedback(scene,after,choice.target,c.settings.ocr_confidence)
                        transfer_collection(store.data,scene,after,choice.target,action['after'],c.settings.ocr_confidence)
                    elif choice.intent not in ('close_standard_unit','open_standard_shop','close_standard_shop','select_standard_movement_star',
                                                'buy_standard_experience','refresh_standard_shop','sell_standard_owned','sell_standard_field_owned'):
                        store.data.pop('collection',None)
                    if choice.intent == 'close_standard_shop':
                        nodes = store.data.setdefault('shop_observed_nodes',[])
                        if len(choice.payload)==6 and choice.payload[0] in nodes:
                            nodes.remove(choice.payload[0])
                        elif len(choice.payload)==4 and choice.payload[0] not in nodes:
                            nodes.append(choice.payload[0])
                    from .currency_wars_standard_progress import progress_verified
                    progress_verified(store.data, choice, after, c.settings.ocr_confidence)
                    from .currency_wars_standard_investment import enter as investment_enter, confirmed, reward_completed
                    investment_enter(store.data,after,c.settings.ocr_confidence)
                    if choice.intent=='confirm_standard_investment':confirmed(store.data,choice,after,c.settings.ocr_confidence)
                    from .currency_wars_standard_rewards import enter, returned
                    enter(store.data,choice,after,c.settings.ocr_confidence)
                    if choice.intent in ('choose_standard_reward','confirm_standard_supply'):
                        returned(store.data,choice,after,c.settings.ocr_confidence)
                        reward_completed(store.data)
                    from .currency_wars_character_rewards import observe_shop
                    observe_shop(store.data,after,action,c.settings.ocr_confidence)
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
        if store.data['completion_verified'] or store.data.get('defeat_settlement_verified'):
            break
    else:
        store.data.update(action_status='step_limit', reason='本次标准观察达到本局动作上限对应的轮数，已停止并保留记录。')
        store.persist()
    c.report.currency_wars = store.data
    c.runner.emit(dict(type=TASK, data=store.data))
    if store.data['completion_verified']:
        c.report.safe_next = '本次为开发对局，结算完成不计作独立验收；原始证据已保留。'
        return TaskResult(TASK, 'success', store.data['reason'])
    if store.data.get('defeat_settlement_verified'):
        c.report.safe_next='本局失败且结算已核实；原报告保留，循环按冻结设置与原局数上限处理，不接续或重打这局。'
        return TaskResult(TASK,'partial',store.data['reason'])
    c.report.safe_next = '先读取标准对局当前局面，再接续已核实动作；不重开或重放未知交易。'
    return TaskResult(TASK, 'partial', store.data.get('reason', '标准对局开发未完成，已留证。'))
