"""Bounded progression through calibrated combat and result screens."""
from __future__ import annotations

import json
import time
from pathlib import Path

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .currency_wars_match import read_match
from .currency_wars_node import result_node, run_node, start_target
from .models import AutomationError, EmptyCapture, TaskResult, normalize


def continue_target(scene, confidence=.65):
    if observe(scene, confidence).page_kind != 'node_result' or result_node(scene, confidence) is None:
        raise AutomationError('继续挑战需要明确的节点胜利结算。')
    import re
    hp = [int(m[1]) for t in scene.tokens if confidence <= t.score <= 1
          and t.within((.3,.43,.5,.5)) and (m:=re.fullmatch(r'小队生命值([0-9]{1,3})',normalize(t.text)))]
    if len(set(hp)) != 1 or not 0 < hp[0] <= 100:
        raise AutomationError('结算生命值未核实，未继续挑战。')
    matches = [t for t in scene.tokens if confidence <= t.score <= 1
               and normalize(t.text) == '继续挑战' and t.within((.4,.79,.6,.86))]
    if len(matches) != 1:
        raise AutomationError('继续挑战按钮不唯一或未核实。')
    return matches[0]


def plane_target(scene,confidence=.65):
    if observe(scene,confidence).page_kind != 'plane_map':
        raise AutomationError('位面地图未核实。')
    return next(t for t in scene.tokens if t.score >= confidence and
                normalize(t.text)=='点击空白处继续' and t.within((.43,.86,.57,.93)))


def active_plane(scene,confidence=.65):
    plane_target(scene,confidence)
    if scene.image is None:
        raise AutomationError('没有位面地图图像。')
    from .currency_wars_deployment import _crop
    import cv2
    import numpy as np
    found=[]
    for plane,cx in enumerate((.23,.50,.77),1):
        hsv=cv2.cvtColor(_crop(scene.image,(cx-.025,.39,cx+.025,.47)),cv2.COLOR_BGR2HSV)
        fraction=np.mean((hsv[:,:,0]>=15)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>=100)&(hsv[:,:,2]>=120))
        if fraction >= .35:
            found.append(plane)
    if len(found)!=1:
        raise AutomationError('高亮位面不唯一或未核实。')
    return found[0]


def flow_snapshot(c,guard):
    # Transitional banners and Gemi's automatic shop can briefly obscure the
    # calibrated page. Observe for a bounded interval without sending input.
    elapsed=0.
    scene=None
    while elapsed<25:
        started=time.monotonic()
        inactive=c.runner.inactive_duration
        try:
            scene=c.snapshot()
        except EmptyCapture:
            scene=None
        if scene is not None:
            guard._require_current_scene(scene)
            kind=observe(scene,c.settings.ocr_confidence).page_kind
            if kind!='unknown':
                return scene,kind
        c.sleep(1)
        elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    if scene is None:
        raise EmptyCapture('连续流程等待画面恢复超时；未发送新的输入。')
    return scene,'unknown'


def run_flow(c):
    """Never resume pending inputs. A new run reobserves the current game UI."""
    guard = CurrencyWarsWorkflow(c)
    data = dict(mode='flow_test', actions=[], completion_verified=False, gameplay_enabled=False,
                action_status='observing', screenshot='',target_level=getattr(c.runner,'currency_target_level',0),
                start_from_lobby_requested=getattr(c.runner,'currency_start_from_lobby',False))
    journal = Path(c.report.run_dir)/'currency-flow.json'
    def persist():
        c.report.currency_wars = data
        journal.write_text(json.dumps(data, ensure_ascii=False, indent=2),encoding='utf-8')
    persist()
    seen = set()
    excluded_candidates={}
    equipment_checked={}
    shop_nodes=set()
    for index in range(180 if data['start_from_lobby_requested'] else 36):
        c.checkpoint()
        scene,kind = flow_snapshot(c,guard)
        if kind=='environment':
            from .currency_wars_environment import environment_choice,choose_environment
            try:
                environment_choice(scene,c.settings.ocr_confidence)
            except AutomationError as error:
                data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                            screenshot=str(c.evidence(scene,'currency_environment_needed')))
                persist()
                break
            if not choose_environment(c,scene,data,persist):
                break
            continue
        if kind in ('lobby','mode_select','difficulty_select','boss_preview') and data['start_from_lobby_requested']:
            from .currency_wars_entry import entry_target,advance_entry
            try:
                entry_target(scene,c.settings.ocr_confidence)
            except AutomationError as error:
                data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                            screenshot=str(c.evidence(scene,'currency_entry_needs_decision')))
                persist()
                break
            if not advance_entry(c,scene,data,persist):
                break
            continue
        if kind in ('final_victory','match_rating','match_summary','match_statistics'):
            from .currency_wars_ending import advance_ending
            if not advance_ending(c,scene,data,persist):
                break
            if data.get('settlement_verified'):
                break
            continue
        if kind=='preparation':
            from .currency_wars_experience import target_level as experience_level
            target_level=experience_level(scene,c.runner,c.settings.ocr_confidence)
            state=read_match(scene,c.settings.ocr_confidence)
            if target_level and state and state.level is None:
                data.update(action_status='needs_decision',page_kind=kind,reason='当前等级未核实，未购买经验或开始战斗。',
                            screenshot=str(c.evidence(scene,'currency_level_unverified')))
                persist()
                break
            if target_level and state and state.level is not None and state.level<target_level:
                from .currency_wars_experience import experience_target,buy_experience
                try:
                    experience_target(scene,c.settings.ocr_confidence)
                except AutomationError as error:
                    data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                                screenshot=str(c.evidence(scene,'currency_experience_unavailable')))
                    persist()
                    break
                if not buy_experience(c,scene,data,persist):
                    break
                continue
        if kind=='boss_intro':
            from .currency_wars_intro import advance_boss
            if not advance_boss(c,scene,data,persist):
                break
            continue
        if kind=='star_selection':
            from .currency_wars_star import star_choice,choose_star
            try:
                star_choice(scene,c.settings.ocr_confidence)
            except AutomationError as error:
                data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                            screenshot=str(c.evidence(scene,'currency_star_needed')))
                persist()
                break
            if not choose_star(c,scene,data,persist):
                break
            continue
        if kind=='bench_full':
            from .currency_wars_sale import duplicate_candidate,sell_duplicate
            try:
                candidate,field=duplicate_candidate(scene,c.settings.ocr_confidence)
            except AutomationError as error:
                data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                            screenshot=str(c.evidence(scene,'currency_overflow_needs_space')))
                persist()
                break
            if not sell_duplicate(c,scene,candidate,field,data,persist):
                break
            continue
        if kind in ('equipment_selection','advanced_equipment_selection','expert_selection'):
            from .currency_wars_rewards import reward_choice,reward_action
            try:
                reward_choice(scene,c.settings.ocr_confidence)
            except AutomationError as error:
                data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                            screenshot=str(c.evidence(scene,'currency_reward_needed')))
                persist()
                break
            if not reward_action(c,scene,data,persist):
                break
            continue
        if kind=='shop':
            from .currency_wars_shop import close_shop_target,close_shop
            shop_state=read_match(scene,c.settings.ocr_confidence)
            if data['start_from_lobby_requested'] and shop_state:
                from .currency_wars_market import purchase_choice,buy_offer
                purchases=sum(a.get('action')=='buy_shop_role' and a.get('origin_node')==shop_state.node
                              for a in data['actions'])
                try:
                    offer=purchase_choice(scene,c.settings.ocr_confidence) if purchases<3 else None
                except AutomationError:
                    offer=None
                if offer is not None:
                    if not buy_offer(c,scene,offer,data,persist):
                        break
                    continue
            try:
                close_shop_target(scene,c.settings.ocr_confidence)
            except AutomationError as error:
                data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                            screenshot=str(c.evidence(scene,'currency_flow_shop_needed')))
                persist()
                break
            if not close_shop(c,scene,data,persist):
                break
            if shop_state:
                shop_nodes.add(shop_state.node)
            continue
        if kind=='supply_selection':
            from .currency_wars_supply import supply_choice,choose_supply
            try:
                supply_choice(scene,c.settings.ocr_confidence)
            except AutomationError as error:
                data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                            screenshot=str(c.evidence(scene,'currency_flow_supply_needed')))
                persist()
                break
            if not choose_supply(c,scene,data,persist):
                break
            continue
        if kind=='investment_selection':
            from .currency_wars_choices import choose_investment,investment_choice
            try:
                investment_choice(scene,c.settings.ocr_confidence)
            except AutomationError as error:
                data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                            screenshot=str(c.evidence(scene,'currency_flow_investment_needed')))
                persist()
                break
            handled=choose_investment(c,scene,data,persist)
            if not handled:
                break
            continue
        if kind in ('preparation', 'battle'):
            if kind == 'preparation':
                from .currency_wars_position import misplaced_backend,correct_position
                misplaced=misplaced_backend(scene,c.settings.ocr_confidence)
                if misplaced is not None:
                    if not correct_position(c,scene,misplaced,data,persist):
                        break
                    continue
                from .currency_wars_rewards import open_reward_target,reward_action
                try:
                    open_reward_target(scene,c.settings.ocr_confidence)
                except AutomationError:
                    pass
                else:
                    if not reward_action(c,scene,data,persist,opening=True):
                        break
                    continue
                state=read_match(scene,c.settings.ocr_confidence)
                if data['start_from_lobby_requested'] and state and state.node not in shop_nodes:
                    from .currency_wars_market import open_shop_target,open_shop
                    try:
                        open_shop_target(scene,c.settings.ocr_confidence)
                    except AutomationError:
                        pass
                    else:
                        shop_nodes.add(state.node)
                        if not open_shop(c,scene,data,persist):
                            break
                        continue
                if state and state.deployment and state.deployment[0]<state.deployment[1]:
                    from .currency_wars_roster import next_candidate,deploy_candidate
                    excluded=excluded_candidates.setdefault(state.node,set())
                    try:
                        candidate=next_candidate(scene,c.settings.ocr_confidence,excluded)
                    except AutomationError as error:
                        data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                                    screenshot=str(c.evidence(scene,'currency_roster_unavailable')))
                        persist()
                        break
                    excluded.add(candidate.slot)
                    if not deploy_candidate(c,scene,candidate,data,persist):
                        break
                    continue
                from .currency_wars_node import loot_centers
                if loot_centers(scene):
                    from .currency_wars_loot import loot_target,collect_loot
                    try:
                        loot_target(scene,c.settings.ocr_confidence)
                    except AutomationError as error:
                        from .currency_wars_deployment import _crop,_texture,bench_face
                        full=all(_texture(_crop(scene.image,bench_face(slot)))>=15 for slot in range(1,10))
                        if full:
                            from .currency_wars_sale import duplicate_candidate,sell_duplicate
                            try:
                                candidate,field=duplicate_candidate(scene,c.settings.ocr_confidence)
                            except AutomationError as sale_error:
                                error=sale_error
                            else:
                                if not sell_duplicate(c,scene,candidate,field,data,persist):
                                    break
                                continue
                        data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                                    screenshot=str(c.evidence(scene,'currency_loot_needs_space')))
                        persist()
                        break
                    if not collect_loot(c,scene,data,persist):
                        if data.get('action_status')=='overflow_pending':
                            continue
                        break
                    continue
                try:
                    start_target(scene,c.settings.ocr_confidence)
                except AutomationError as error:
                    data.update(action_status='needs_decision',page_kind=kind,reason=str(error),
                                screenshot=str(c.evidence(scene,'currency_flow_preparation_needed')))
                    persist()
                    break
                from .currency_wars_equipment import equipment_items,equipment_fields,equip_battery
                item_name,items='battery',()
                for equipment in ('hard_armor','energy_sail','battery','armor'):
                    found=equipment_items(scene,equipment,c.settings.ocr_confidence)
                    if found:
                        item_name,items=equipment,found
                        break
                if items and state.gold is None:
                    data.update(action_status='needs_decision',reason='装备穿戴前金币未核实。',
                                screenshot=str(c.evidence(scene,'currency_equipment_gold_unknown')))
                    persist()
                    break
                checked=equipment_checked.setdefault((state.node,item_name),set())
                fields=equipment_fields(scene,checked,c.settings.ocr_confidence) if items else ()
                if fields:
                    field=fields[0]
                    checked.add((field.zone,field.slot))
                    if not equip_battery(c,scene,field,items[0],data,persist,item_name=item_name):
                        break
                    continue
                node = read_match(scene,c.settings.ocr_confidence).node
                if ('start',node) in seen:
                    raise AutomationError('当前节点已有出战记录，未重复出战。')
                seen.add(('start',node))
            run_node(c,journal_name=f'currency-node-{index}.json',initial_scene=scene)
            node_data = dict(c.report.currency_wars)
            data['actions'].append(node_data)
            data.update(action_status='node_verified' if node_data['node_verified'] else 'unknown',
                        screenshot=node_data['screenshot'])
            persist()
            if not node_data['node_verified']:
                break
            continue
        before = str(c.evidence(scene,'currency_flow_'+kind))
        data['screenshot'] = before
        if kind not in ('node_result','plane_map'):
            data.update(action_status='needs_decision',page_kind=kind)
            persist()
            break
        source = result_node(scene,c.settings.ocr_confidence) if kind=='node_result' else active_plane(scene,c.settings.ocr_confidence)
        continue_target(scene,c.settings.ocr_confidence) if kind=='node_result' else plane_target(scene,c.settings.ocr_confidence)
        action_name = 'continue_node' if kind=='node_result' else 'advance_plane'
        if (action_name,source) in seen:
            raise AutomationError('同一结算已提交继续挑战，未重复点击。')
        seen.add((action_name,source))
        action = dict(action=action_name,origin_node=source,status='pending',before=before)
        data['actions'].append(action)
        data['action_status']='pending'
        persist()
        c.currency_continue_node(scene) if kind=='node_result' else c.currency_advance_plane(scene)
        elapsed = 0.
        while elapsed < 30:
            started = time.monotonic()
            inactive = c.runner.inactive_duration
            try:
                after = c.snapshot()
            except EmptyCapture:
                after = None
            if after is not None:
                guard._require_current_scene(after)
                new_kind = observe(after,c.settings.ocr_confidence).page_kind
                new_match = read_match(after,c.settings.ocr_confidence)
                next_node = new_match.node if new_match else None
                ahead = (tuple(map(int,next_node.split('-'))) > tuple(map(int,source.split('-')))) if next_node and kind=='node_result' else bool(next_node and next_node.startswith(str(source)+'-'))
                if (new_kind in ('preparation','shop','character') and ahead
                        or new_kind in ('environment','supply_selection','investment_selection','boss_intro')
                        or kind=='node_result' and new_kind=='plane_map'):
                    action.update(status='verified',after=str(c.evidence(after,'currency_flow_after_continue')),
                                  next_page=new_kind)
                    data.update(action_status='transition_verified',screenshot=action['after'])
                    persist()
                    break
            c.sleep(1)
            elapsed += max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action.update(status='unknown')
            if after is not None:
                action['after']=str(c.evidence(after,'currency_flow_unknown'))
                data['screenshot']=action['after']
            data.update(action_status='unknown')
            persist()
            break
    else:
        data['action_status']='step_limit'
        persist()
    c.runner.emit(dict(type='currency_wars',data=data))
    detail = '流程推进已停在待处理界面；'+(data['reason'] if data.get('reason') else '已保存逐步记录。')+'整局尚未完成。'
    if data.get('settlement_verified'):
        detail='已验证终局返回货币战争主页；完整自动开局至结算仍待验证。'
    c.report.safe_next = '检查本次最后截图，补齐待处理界面；重新运行只识别当前画面，不重放历史输入。'
    return TaskResult(TASK,'partial',detail)
