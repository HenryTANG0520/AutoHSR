"""Shared legal candidates and an explainable offline policy; never sends inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .currency_wars_economy import Mode, assess_spend
from .currency_wars_state import StrategySnapshot, integer, labels, load_snapshot, strict_json, text


@dataclass(frozen=True)
class RouteSpec:
    route_id: str
    game_versions: tuple[str, ...]
    modes: tuple[str, ...]
    sources: tuple[str, ...]
    core_names: tuple[str, ...] = ()
    preferred_names: tuple[str, ...] = ()
    required_equipment: tuple[str, ...] = ()
    target_level: int | None = None
    rules_checked: bool = False

    def __post_init__(self):
        text(self.route_id)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', self.route_id):
            raise ValueError('策略标识须为字母、数字、下划线或连字符')
        for name in ('game_versions', 'modes', 'sources', 'core_names', 'preferred_names'):
            labels(getattr(self, name))
        if not self.sources or not self.game_versions or not self.modes or not set(self.modes) <= {'standard', 'overclock'}:
            raise ValueError('策略缺少来源或明确的适用范围')
        if type(self.required_equipment) is not tuple or len(self.required_equipment) > 8:
            raise ValueError('必要装备无效')
        for item in self.required_equipment:
            text(item)
        integer(self.target_level, 1, 20, optional=True)
        if type(self.rules_checked) is not bool:
            raise ValueError('策略规则核验状态无效')

    def applicable(self, state):
        return (self.rules_checked and state.known('game_version', 'mode')
                and state.game_version in self.game_versions and state.mode in self.modes)


def load_routes(path):
    raw = Path(path).read_bytes()
    if len(raw) > 262144:
        raise ValueError('策略文件超过256KiB')
    data = strict_json(raw)
    if (type(data) is not dict or set(data) != {'schema_version', 'routes'}
            or type(data['schema_version']) is not int or data['schema_version'] != 1
            or type(data['routes']) is not list or len(data['routes']) > 32):
        raise ValueError('策略包格式无效')
    result = []
    for item in data['routes']:
        if type(item) is not dict or set(item) - {f.name for f in fields(RouteSpec)}:
            raise ValueError('策略字段无效')
        item = dict(item)
        for name in ('game_versions', 'modes', 'sources', 'core_names', 'preferred_names', 'required_equipment'):
            if name in item:
                if type(item[name]) is not list:
                    raise ValueError('策略标签必须是数组')
                item[name] = tuple(item[name])
        result.append(RouteSpec(**item))
    if len({r.route_id for r in result}) != len(result):
        raise ValueError('策略标识重复')
    return tuple(result)


@dataclass(frozen=True)
class ActionCandidate:
    candidate_id: str
    snapshot_id: str
    kind: str
    target: str
    price: int
    utility: float
    reasons: tuple[str, ...]
    required_facts: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    snapshot_id: str
    candidate_id: str
    provider: str
    goal: str
    reasons: tuple[str, ...]
    route_id: str | None = None
    fallback_reason: str | None = None
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    # A strategy answer is never an input permission. Context rechecks later.
    executable: bool = False


def route_ranking(state, routes):
    from collections import Counter
    owned = {u.name for u in state.roster} if state.known('roster') else set()
    gear = Counter(state.inventory or ()) if state.known('inventory') else Counter()
    if state.known('roster'):
        gear.update(item for unit in state.roster for item in (unit.equipment or ()))
    result = []
    for route in routes:
        if not route.applicable(state):
            continue
        need = Counter(route.required_equipment)
        matched = sum((need & gear).values())
        # Provisional policy values, not probabilities or predicted battle wins.
        score = 12 * len(owned & set(route.core_names)) + 3 * len(owned & set(route.preferred_names)) + 8 * matched
        result.append((score, route.route_id, route))
    return tuple(sorted(result, key=lambda r: (-r[0], r[1])))


def _candidate(state, kind, target, price, score, reasons, required):
    raw = json.dumps([state.snapshot_id, kind, target, price], ensure_ascii=False)
    identifier = hashlib.sha256(raw.encode()).hexdigest()[:24]
    return ActionCandidate(identifier, state.snapshot_id, kind, target, price, round(score, 3),
                           tuple(reasons), tuple(required))


def candidates(state, route=None):
    """Generate only supported, fact-backed choices. No guessed mode or balance."""
    make = lambda *args: _candidate(state, *args)
    if not state.known('page', 'node') or state.page not in ('preparation', 'shop'):
        return (make('observe', 'page', 0, 0, ('先确认当前局内页面与节点',), ()),)
    if not state.known('transaction_status') or state.transaction_status != 'clear':
        return (make('observe', 'transaction_status', 0, 0, ('先核对既有交易，不重复消费',), ('page', 'node')),)
    base = ('page', 'node', 'transaction_status')
    result = [make('hold', 'current', 0, 0, ('保留金币与当前阵容',), base)]
    required = base + ('gold', 'mode', 'game_version', 'rules_version', 'roster', 'roster_complete',
                       'capacity', 'bench_capacity', 'bench_occupied')
    missing = [name for name in required if not state.known(name)]
    if not state.roster_complete and 'roster_complete' not in missing:
        missing.append('roster_complete')
    if (state.rules_version != '4.6' or state.game_version != state.rules_version) and 'rules_version' not in missing:
        missing.append('rules_version')
    if missing:
        return tuple(make('observe', name, 0, 1, ('补齐决策事实：' + name,), base) for name in missing)
    if state.known('hp') and state.hp == 0:
        return (make('observe', 'match_result', 0, 0, ('生命为零，先核实对局结果',), base + ('hp',)),)
    deployed = [u for u in state.roster if u.zone != 'bench']
    vacancies = state.capacity - len(deployed)
    free = state.bench_capacity - state.bench_occupied
    risk = 0.0
    if state.known('hp', 'recent_losses') and state.hp:
        risk = min(1.0, sum(state.recent_losses[-2:]) / state.hp)
    spend_penalty = lambda price: assess_spend(Mode(state.mode), state.gold, price).interest_lost * 8 * (1 - risk)
    route = route if route is not None and route.applicable(state) else None
    if state.page == 'shop':
        if not state.known('offers'):
            result.append(make('observe', 'offers', 0, 1, ('读取当前商店候选和实际售价',), base))
            return tuple(result)
        for offer in state.offers:
            if offer.price is None:
                result.append(make('observe', f'offer:{offer.slot}:price', 0, 1, ('候选售价未知',), base))
                continue
            if offer.price > state.gold or free < 1:
                continue
            owned = [u for u in state.roster if u.name == offer.name]
            copies = [u for u in owned if offer.star is not None and offer.tier is not None
                      and u.star == offer.star and u.tier == offer.tier]
            score = -offer.price * .5 - spend_penalty(offer.price)
            reasons = [f'实际支付{offer.price}金币', f'利息档位机会成本{spend_penalty(offer.price):.2f}']
            if len(copies) == 2 and offer.star < 3:
                score += 70 + 25 * risk
                reasons.append('已有两张同星同费用角色，可形成三张升星条件')
            elif len(copies) == 1:
                score += 10
                reasons.append('建立同星同费用对子，尚无即时升星')
            if not owned and vacancies > 0:
                score += 18
                reasons.append('有出战空位的新角色候选，仍须核对适配位置')
            if route and offer.name in route.core_names:
                score += 24
                reasons.append('当前适用路线的核心候选')
            elif route and offer.name in route.preferred_names and not owned:
                score += 12
                reasons.append('当前适用路线的辅助候选')
            # Bounded two-step lookahead over visible offers only. This does
            # not sample an invented future shop or authorize the second buy.
            other = [o for o in state.offers if o.slot != offer.slot and o.name == offer.name
                     and offer.star is not None and offer.tier is not None
                     and o.star == offer.star and o.tier == offer.tier and o.price is not None]
            if len(copies) == 1 and offer.star < 3 and free >= 2 and any(
                    o.price + offer.price <= state.gold for o in other):
                score += 35
                reasons.append('两步可见购买可达三张升星条件，每步需重新核对')
            if free <= 2 and len(copies) != 2:
                score -= 20
                reasons.append('备战空间紧张，扣除囤牌收益')
            if score > 0:
                result.append(make('buy', str(offer.slot), offer.price, score, reasons, required + ('offers',)))
        if (route and state.known('refresh_budget') and state.refresh_budget >= 2 and state.gold >= 2
                and free > 0 and any(name not in {u.name for u in state.roster} for name in route.core_names)):
            score = 2 + 10 * risk - spend_penalty(2)
            result.append(make('refresh', 'shop', 2, score,
                               ('核心缺失；仅在本节点剩余搜索预算内刷新', '未知未来来牌，不计算精确概率'),
                               required + ('refresh_budget', 'offers')))
    elif (route and route.target_level is not None and state.known('level', 'experience')
          and state.level < route.target_level and state.gold >= 4):
        immediate = state.experience[1] - state.experience[0] <= 4
        ready = any(u.zone == 'bench' and u.eligible_zones for u in state.roster)
        score = (18 if immediate and ready and vacancies == 0 else 2) - spend_penalty(4)
        result.append(make('experience', 'level', 4, score,
                           ('按当前路线提升人口目标', '本次增加4经验，容量变化必须实读核对'),
                           required + ('level', 'experience')))
    return tuple(result)


class OfflineProvider:
    def __init__(self):
        self.current_route = None

    def decide(self, state, choices=None, knowledge=()):
        ranking = route_ranking(state, knowledge)
        route = ranking[0][2] if ranking else None
        old = next((item for item in ranking if item[1] == self.current_route), None)
        if old and ranking[0][0] < old[0] + 12:
            route = old[2]
        self.current_route = route.route_id if route else None
        choices = candidates(state, route) if choices is None else choices
        if not choices or any(c.snapshot_id != state.snapshot_id for c in choices):
            raise ValueError('候选缺失或来自其他局面')
        selected = min(choices, key=lambda c: (-c.utility, c.price, c.candidate_id))
        goal = ('observe' if selected.kind == 'observe' else 'stabilize' if selected.kind == 'buy'
                else 'level' if selected.kind == 'experience' else 'search' if selected.kind == 'refresh' else 'economy')
        return Decision(state.snapshot_id, selected.candidate_id, 'offline', goal, selected.reasons,
                        route_id=self.current_route)


def validate_decision(state, decision, choices, *, now, input_epoch):
    """Used after a fresh observation; does not itself permit keyboard/mouse IO."""
    if not state.fresh(now, input_epoch) or state.snapshot_id != decision.snapshot_id:
        return False
    selected = [c for c in choices if c.candidate_id == decision.candidate_id and c.snapshot_id == state.snapshot_id]
    return bool(len(selected) == 1 and state.known(*selected[0].required_facts)
                and not decision.executable)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='货币战争策略只读决策；不访问游戏，不发送输入。')
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--state', type=Path)
    inputs.add_argument('--sample', type=Path)
    parser.add_argument('--routes', type=Path)
    parser.add_argument('--provider', choices=('offline', 'hybrid'), default='offline')
    parser.add_argument('--base-url', default='')
    parser.add_argument('--model', default='')
    parser.add_argument('--key-env', default='AUTOHSR_LLM_API_KEY')
    parser.add_argument('--token-limit-field', choices=('max_tokens', 'max_completion_tokens'), default='max_tokens')
    args = parser.parse_args(argv)
    try:
        if args.state:
            state = load_snapshot(args.state)
        else:
            from .currency_wars_replay import load_sample
            _, scene = load_sample(args.sample)
            from .currency_wars_state import snapshot_from_scene
            state = snapshot_from_scene(scene, 0, source_id=str(args.sample))
        routes = load_routes(args.routes) if args.routes else ()
        provider = OfflineProvider()
        decision = provider.decide(state, knowledge=routes)
        route = next((r for r in routes if r.route_id == decision.route_id), None)
        choices = candidates(state, route)
        if args.provider == 'hybrid':
            from .currency_wars_llm import HybridProvider, LLMSettings
            decision = HybridProvider(LLMSettings(provider='hybrid', base_url=args.base_url,
                model=args.model, key_env=args.key_env, token_limit_field=args.token_limit_field),
                offline=provider).decide(state, choices, routes)
        print(json.dumps(dict(decision=asdict(decision), candidates=[asdict(c) for c in choices],
                              game_accessed=False, automatic_execution=False), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as error:
        print(json.dumps(dict(error=str(error), game_accessed=False, automatic_execution=False), ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
