"""Immutable, evidence-scoped strategy facts. No game inputs or network access."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def integer(value, low, high, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'整数应在{low}～{high}之间')


def text(value, limit=80, *, optional=False):
    if optional and value is None:
        return
    if (type(value) is not str or not 0 < len(value) <= limit
            or any(ord(c) < 32 for c in value)):
        raise ValueError('文字字段无效')


def labels(value, *, optional=False):
    if optional and value is None:
        return
    if type(value) is not tuple or len(value) > 32 or len(set(value)) != len(value):
        raise ValueError('标签集合无效')
    for item in value:
        text(item)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('JSON包含重复字段')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('JSON包含非有限数')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _keys(data, cls):
    if type(data) is not dict or set(data) - {f.name for f in fields(cls)}:
        raise ValueError('未知或无效状态字段')
    return dict(data)


@dataclass(frozen=True)
class FactEvidence:
    field: str
    source_id: str
    input_epoch: int

    def __post_init__(self):
        text(self.field)
        text(self.source_id, 512)
        integer(self.input_epoch, 0, 2**53)


@dataclass(frozen=True)
class UnitState:
    name: str
    zone: str
    slot: int
    star: int | None = None
    tier: int | None = None
    traits: tuple[str, ...] | None = None
    equipment: tuple[str, ...] | None = None
    eligible_zones: tuple[str, ...] | None = None

    def __post_init__(self):
        text(self.name)
        if self.zone not in ('front', 'back', 'bench'):
            raise ValueError('角色位置无效')
        integer(self.slot, 1, 20)
        integer(self.star, 1, 4, optional=True)
        integer(self.tier, 1, 5, optional=True)
        labels(self.traits, optional=True)
        if self.equipment is not None:
            if type(self.equipment) is not tuple or len(self.equipment) > 8:
                raise ValueError('角色装备无效')
            for item in self.equipment:
                text(item)
        labels(self.eligible_zones, optional=True)
        if self.eligible_zones is not None and not set(self.eligible_zones) <= {'front', 'back'}:
            raise ValueError('角色适配位置无效')


@dataclass(frozen=True)
class ShopOffer:
    slot: int
    name: str
    price: int | None = None
    tier: int | None = None
    star: int | None = None
    traits: tuple[str, ...] | None = None

    def __post_init__(self):
        integer(self.slot, 0, 4)
        text(self.name)
        # Discounts may make the price different from the 1..5 cost tier.
        integer(self.price, 0, 999, optional=True)
        integer(self.tier, 1, 5, optional=True)
        integer(self.star, 1, 4, optional=True)
        labels(self.traits, optional=True)


@dataclass(frozen=True)
class StrategySnapshot:
    page: str = 'unknown'
    input_epoch: int = 0
    observed_at: float = 0.0
    game_version: str | None = None
    mode: str | None = None
    rank: int | None = None
    wealth: int | None = None
    node: str | None = None
    gold: int | None = None
    hp: int | None = None
    level: int | None = None
    experience: tuple[int, int] | None = None
    capacity: int | None = None
    bench_capacity: int | None = None
    bench_occupied: int | None = None
    roster: tuple[UnitState, ...] = ()
    roster_complete: bool = False
    offers: tuple[ShopOffer, ...] = ()
    inventory: tuple[str, ...] | None = None
    environment: tuple[str, ...] | None = None
    investments: tuple[str, ...] | None = None
    recent_losses: tuple[int, ...] = ()
    transaction_status: str = 'unknown'
    refresh_budget: int | None = None
    rules_version: str | None = None
    evidence: tuple[FactEvidence, ...] = ()

    def __post_init__(self):
        text(self.page)
        integer(self.input_epoch, 0, 2**53)
        if (type(self.observed_at) not in (int, float) or not math.isfinite(self.observed_at)
                or self.observed_at < 0):
            raise ValueError('采集时间无效')
        for name in ('game_version', 'rules_version', 'node'):
            text(getattr(self, name), optional=True)
        if self.node is not None and not re.fullmatch(r'[1-3]-[1-9][0-9]?', self.node):
            raise ValueError('节点无效')
        if self.mode not in (None, 'standard', 'overclock'):
            raise ValueError('博弈模式无效')
        for name, bounds in {'rank': (0, 8), 'wealth': (1, 999), 'gold': (0, 99999),
                             'hp': (0, 100), 'level': (1, 20), 'capacity': (0, 20),
                             'bench_capacity': (0, 20), 'bench_occupied': (0, 20),
                             'refresh_budget': (0, 99999)}.items():
            integer(getattr(self, name), *bounds, optional=True)
        if self.experience is not None:
            if type(self.experience) is not tuple or len(self.experience) != 2:
                raise ValueError('经验字段无效')
            integer(self.experience[1], 1, 9999)
            integer(self.experience[0], 0, self.experience[1] - 1)
        if type(self.roster_complete) is not bool:
            raise ValueError('阵容完整性必须是布尔值')
        if self.transaction_status not in ('unknown', 'clear', 'pending'):
            raise ValueError('交易核对状态无效')
        for name, cls, limit in (('roster', UnitState, 40), ('offers', ShopOffer, 5),
                                 ('evidence', FactEvidence, 40)):
            value = getattr(self, name)
            if type(value) is not tuple or len(value) > limit or any(type(x) is not cls for x in value):
                raise ValueError('状态集合无效：' + name)
        positions = [(u.zone, u.slot) for u in self.roster]
        if len(set(positions)) != len(positions) or len({o.slot for o in self.offers}) != len(self.offers):
            raise ValueError('角色或商店位置重复')
        deployed = sum(u.zone != 'bench' for u in self.roster)
        bench = sum(u.zone == 'bench' for u in self.roster)
        if (self.capacity is not None and deployed > self.capacity
                or self.bench_capacity is not None and self.bench_occupied is not None
                and self.bench_occupied > self.bench_capacity):
            raise ValueError('阵容超过已知容量')
        if self.roster_complete and (self.bench_occupied is None or bench != self.bench_occupied):
            raise ValueError('完整阵容与备战占用不符')
        if (self.bench_capacity is not None
                and any(u.zone == 'bench' and u.slot > self.bench_capacity for u in self.roster)):
            raise ValueError('备战格超出容量')
        for name in ('environment', 'investments'):
            labels(getattr(self, name), optional=True)
        if self.inventory is not None:
            if type(self.inventory) is not tuple or len(self.inventory) > 80:
                raise ValueError('装备仓库无效')
            for item in self.inventory:
                text(item)
        if type(self.recent_losses) is not tuple or len(self.recent_losses) > 8:
            raise ValueError('战斗历史无效')
        for value in self.recent_losses:
            integer(value, 0, 100)
        allowed = {f.name for f in fields(self)} - {'evidence', 'observed_at', 'input_epoch'}
        if (any(e.field not in allowed for e in self.evidence)
                or len({e.field for e in self.evidence}) != len(self.evidence)):
            raise ValueError('证据字段未知或冲突')

    def known(self, *names):
        proven = {e.field for e in self.evidence if e.input_epoch == self.input_epoch}
        return all(name in proven and getattr(self, name, None) is not None for name in names)

    def public_state(self):
        """Allowlisted game facts only; never export local evidence paths."""
        data = asdict(self)
        for name in ('evidence', 'observed_at'):
            data.pop(name)
        for name in tuple(data):
            if name != 'input_epoch' and not self.known(name):
                data[name] = None
        data['known_fields'] = sorted(e.field for e in self.evidence if e.input_epoch == self.input_epoch)
        if data['roster'] is not None:
            data['roster'] = sorted(data['roster'], key=lambda u: (u['zone'], u['slot']))
        if data['offers'] is not None:
            data['offers'] = sorted(data['offers'], key=lambda o: o['slot'])
        return data

    @property
    def snapshot_id(self):
        raw = json.dumps(self.public_state(), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(raw.encode()).hexdigest()

    def fresh(self, now, epoch, max_age=8.0):
        return (epoch == self.input_epoch and type(now) in (int, float) and math.isfinite(now)
                and 0 <= now - self.observed_at <= max_age)

    @classmethod
    def from_dict(cls, data):
        values = _keys(data, cls)
        for name, kind in (('roster', UnitState), ('offers', ShopOffer), ('evidence', FactEvidence)):
            items = values.get(name, [])
            if type(items) is not list:
                raise ValueError('JSON集合必须是数组')
            converted = []
            for item in items:
                fields_ = _keys(item, kind)
                for key in ('traits', 'equipment', 'eligible_zones'):
                    if fields_.get(key) is not None:
                        if type(fields_[key]) is not list:
                            raise ValueError('标签必须是数组')
                        fields_[key] = tuple(fields_[key])
                converted.append(kind(**fields_))
            values[name] = tuple(converted)
        for name in ('experience', 'inventory', 'environment', 'investments', 'recent_losses'):
            if values.get(name) is not None:
                if type(values[name]) is not list:
                    raise ValueError('JSON集合必须是数组')
                values[name] = tuple(values[name])
        return cls(**values)


def load_snapshot(path):
    raw = Path(path).read_bytes()
    if len(raw) > 262144:
        raise ValueError('局面文件超过256KiB')
    from dataclasses import replace
    # Files are replay evidence, never a current foreground observation.
    return replace(StrategySnapshot.from_dict(strict_json(raw)), observed_at=0.0)


def snapshot_from_scene(scene, input_epoch, confidence=.65, source_id='current_scene'):
    """Carry only currently read HUD fields; mode, roster and ledger stay unknown."""
    from .currency_wars import observe
    from .currency_wars_match import read_match
    values = dict(page=observe(scene, confidence).page_kind, input_epoch=input_epoch,
                  observed_at=scene.captured_at)
    state = read_match(scene, confidence)
    if state:
        values.update(node=state.node, gold=state.gold, hp=state.hp, level=state.level,
                      experience=state.experience,
                      capacity=state.deployment[1] if state.deployment else None,
                      offers=tuple(ShopOffer(o.slot, o.name, price=o.cost) for o in state.offers))
    values['evidence'] = tuple(FactEvidence(name, source_id, input_epoch) for name, value in values.items()
                              if name not in ('input_epoch', 'observed_at') and value is not None)
    return StrategySnapshot(**values)
