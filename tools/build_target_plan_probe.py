"""Exercise cultivation plan arithmetic against the offline evidence fixture."""
import argparse
from dataclasses import dataclass, replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from autohsr.dungeons import BY_KEY, count_limit


FIXTURE = ROOT / 'autohsr/tests/fixtures/dungeons/build_target_quantities.json'
CALYX = ('calyx_golden', 'calyx_crimson')


@dataclass(frozen=True)
class Scope:
    category: str
    target: str
    location: str | None
    difficulty: int
    version: str | None
    bonus: str


@dataclass(frozen=True)
class Yield:
    material: str
    scope: Scope
    basis: str
    rounds: int
    units: int


def estimate(material, shortfall, scope, evidence, configured_limit):
    if (scope.category not in CALYX or type(configured_limit) is not int
            or not 10 <= configured_limit <= 240 or configured_limit % 10):
        raise ValueError('需要花萼分类及 10～240 内的配置开拓力上限。')
    if shortfall is not None and (type(shortfall) is not int or not 0 <= shortfall <= 999_999_999):
        raise ValueError('逐件缺口须为已核实的非负整数。')
    rule = BY_KEY[scope.category]
    cap = min(rule.batch, count_limit(rule, configured_limit))
    result = dict(state='unverified_shortfall', required_rounds=None, required_stamina=None,
                  max_draft_rounds_by_config=cap)
    if not isinstance(material, str) or not material.strip() or shortfall is None:
        return result
    if shortfall == 0:
        return dict(result, state='nothing_needed', required_rounds=0, required_stamina=0)
    if evidence is None or evidence.basis != 'guaranteed_minimum' or type(evidence.rounds) is not int or evidence.rounds != 1:
        return dict(result, state='unverified_per_round_minimum')
    if (evidence.material != material or evidence.scope != scope or not scope.target or not scope.location
            or not scope.version or type(scope.difficulty) is not int or not 1 <= scope.difficulty <= 6
            or scope.bonus != 'base'):
        return dict(result, state='unverified_scope')
    if type(evidence.units) is not int or evidence.units <= 0:
        return dict(result, state='no_positive_minimum')
    rounds = (shortfall + evidence.units - 1) // evidence.units
    return dict(result, state='within_draft_limit' if rounds <= cap else 'beyond_draft_limit',
                required_rounds=rounds, required_stamina=rounds * rule.cost)


def replay_fixture(data, configured_limit):
    history = data['observed_loot']
    if not history or any(row['basis'] != 'observed_total' for row in history):
        raise ValueError('实测掉落夹具只接受 observed_total。')
    chain = data['public_chain']
    result = next(row for row in history if row['id'] == chain['settlement_id'])
    scope = Scope(**result['scope'])
    material = chain['material']
    total = result['items'][material]
    payout = Yield(material, scope, result['basis'], result['rounds'], total)
    actual = estimate(material, chain['before_amount'], scope, payout, configured_limit)

    # These complete inputs exercise the math and the one-draft cap.
    synthetic_scope = Scope('calyx_crimson', '智识之蕾', '海原电视塔', 6, 'synthetic', 'base')
    minimum = Yield(material, synthetic_scope, 'guaranteed_minimum', 1, 2)
    return dict(
        replayed=dict(material=material, before=chain['before_amount'], after=chain['after_amount'],
                      observed_total=total, observed_rounds=result['rounds'], settlement_samples=len(history),
                      estimate=actual),
        synthetic_examples=dict(
            positive=estimate(material, 5, synthetic_scope, minimum, configured_limit),
            capped=estimate(material, 13, synthetic_scope, minimum, configured_limit),
            zero=estimate(material, 0, synthetic_scope, None, configured_limit),
            mismatched=estimate(material, 5, synthetic_scope, replace(minimum, scope=replace(synthetic_scope, difficulty=5)),
                                configured_limit),
        ),
    )


def main():
    parser = argparse.ArgumentParser(description='离线核对培养数量样本及体力草稿计算边界。')
    parser.add_argument('--stamina', type=int, default=60, help='模拟配置开拓力上限，默认 60')
    args = parser.parse_args()
    try:
        data = json.loads(FIXTURE.read_text(encoding='utf-8'))
        result = replay_fixture(data, args.stamina)
    except (KeyError, OSError, StopIteration, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
