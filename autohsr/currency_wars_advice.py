"""Offline, bounded guide advice. No runner, window, input or transaction API."""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

DEFAULT_STRATEGY = Path(__file__).resolve().parents[1] / 'assets/strategies/currency_joy_quantum.json'
FIELD_TYPES = {'page': str, 'game_version': str, 'mode': str, 'selected_strategy': str,
               'guide_scope_confirmed': bool, 'level': int, 'core_present': bool, 'core_cost': int}
ACTIONS = {'hold_experience', 'review_level8'}
ROOT_KEYS = {'schema_version', 'strategy_id', 'scenario', 'applicability', 'required_state',
             'allowed_actions', 'selection_basis', 'rules', 'fallback', 'stop_conditions',
             'sources', 'validation'}


def _object(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError('字段集合无效')


def load_strategy(path=DEFAULT_STRATEGY):
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > 65536:
        raise ValueError('策略超过64KiB')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('重复JSON字段')
            result[key] = value
        return result
    data = json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('非有限数')))
    _object(data, ROOT_KEYS)
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise ValueError('策略版本无效')
    if data['strategy_id'] != 'joy_quantum_lv7' or data['scenario'] != 'level7_upgrade_order':
        raise ValueError('未支持的策略场景')
    if data['required_state'] != list(FIELD_TYPES) or data['allowed_actions'] != sorted(ACTIONS):
        raise ValueError('状态或动作白名单无效')
    app = data['applicability']
    _object(app, ('pages', 'game_versions', 'modes', 'scope_confirmation_required'))
    if app != {'pages': ['preparation', 'shop'], 'game_versions': ['4.4'],
               'modes': ['overclock'], 'scope_confirmation_required': True}:
        raise ValueError('未核实的适用范围')
    if data['fallback'] != 'stop_and_request_missing_state':
        raise ValueError('后备方案无效')
    if not isinstance(data['sources'], list) or not data['sources']:
        raise ValueError('缺少来源')
    source_ids = set()
    for source in data['sources']:
        _object(source, ('id', 'kind', 'path', 'claim'))
        if any(type(value) is not str or not value or len(value) > 2000 for value in source.values()):
            raise ValueError('来源无效')
        if source['id'] in source_ids or source['kind'] not in ('guide', 'tutorial', 'observation'):
            raise ValueError('来源标识无效')
        source_ids.add(source['id'])
    rules = data['rules']
    if type(rules) is not list or not 1 <= len(rules) <= 8:
        raise ValueError('规则数量无效')
    ids, priorities = set(), set()
    for rule in rules:
        _object(rule, ('id', 'priority', 'all', 'action', 'source_id', 'evidence_class'))
        if (type(rule['id']) is not str or not rule['id'] or rule['id'] in ids
                or type(rule['priority']) is not int or not 0 <= rule['priority'] <= 100
                or rule['priority'] in priorities or rule['action'] not in ACTIONS
                or rule['source_id'] not in source_ids or rule['evidence_class'] != 'guide_rule'):
            raise ValueError('规则标识、优先级、动作或来源无效')
        ids.add(rule['id']); priorities.add(rule['priority'])
        if type(rule['all']) is not list or not 1 <= len(rule['all']) <= 8:
            raise ValueError('条件数量无效')
        for cond in rule['all']:
            _object(cond, ('field', 'op', 'value'))
            kind = FIELD_TYPES.get(cond['field'])
            if (kind is None or type(cond['value']) is not kind
                    or cond['op'] not in ('eq', 'lt', 'gte')
                    or (cond['op'] != 'eq' and kind is not int)
                    or (kind is int and not 0 <= cond['value'] <= 20)):
                raise ValueError('不支持的条件')
    if (type(data['selection_basis']) is not str or not data['selection_basis']
            or type(data['stop_conditions']) is not list
            or not all(type(x) is str for x in data['stop_conditions'])
            or data['validation'] != {'guide_transcribed': True, 'live_strategy_verified': False,
                                      'automatic_execution': False, 'cross_version_verified': False}):
        raise ValueError('选择依据或验证状态无效')
    return data, hashlib.sha256(raw).hexdigest()


def advise(state, strategy_path=DEFAULT_STRATEGY):
    result = dict(status='refused', action=None, executable=False, game_accessed=False,
                  strategy_id=None, strategy_sha256=None, rule_ids=[], reasons=[], missing=[],
                  message='暂停给出动作建议；先补齐或核实局面信息。')
    try:
        config, digest = load_strategy(strategy_path)
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        result['reasons'] = [dict(code='invalid_config', detail=str(error))]
        return result
    result.update(strategy_id=config['strategy_id'], strategy_sha256=digest)
    if type(state) is not dict:
        result['reasons'] = [dict(code='invalid_state')]
        return result
    for field, kind in FIELD_TYPES.items():
        value = state.get(field)
        if value is None:
            result['missing'].append(field)
        elif type(value) is not kind or (kind is int and not 0 <= value <= (19 if field == 'level' else 5)):
            result['reasons'].append(dict(code='invalid_state_field', field=field))
    if result['reasons']:
        return result
    if state.get('level') == 7 and state.get('core_cost') is None:
        result['message'] = '画面识别为7级；先查看银狼Lv.999的当前费用，并核实攻略适用性，暂不判断购买经验。'
    app = config['applicability']
    for field, allowed in (('page', app['pages']), ('game_version', app['game_versions']),
                           ('mode', app['modes']), ('selected_strategy', [config['strategy_id']]),
                           ('guide_scope_confirmed', [True]), ('core_present', [True])):
        if state.get(field) is not None and state[field] not in allowed:
            result['reasons'].append(dict(code='outside_verified_scope', field=field,
                                          observed=state[field], required=allowed))
    if result['missing']:
        result['reasons'].append(dict(code='missing_state', fields=result['missing']))
    if result['reasons']:
        return result
    if state['level'] != 7 or not 1 <= state['core_cost'] <= 5:
        result['reasons'] = [dict(code='outside_scenario', level=state['level'], core_cost=state['core_cost'])]
        return result
    operators = {'eq': lambda a, b: a == b, 'lt': lambda a, b: a < b, 'gte': lambda a, b: a >= b}
    for rule in sorted(config['rules'], key=lambda r: r['priority'], reverse=True):
        if all(operators[c['op']](state[c['field']], c['value']) for c in rule['all']):
            result.update(status='advice', action=rule['action'], rule_ids=[rule['id']],
                          message=(f"当前7级，核心费用{state['core_cost']}；规则{rule['id']}匹配，建议暂缓购买经验。"
                                   if rule['action'] == 'hold_experience' else
                                   f"当前7级，核心费用{state['core_cost']}；规则{rule['id']}匹配，可进一步评估升8的资源与生存条件，尚不建议交易。"),
                          reasons=[dict(code='matched_guide_rule', source_id=rule['source_id'],
                                        facts=[dict(c, observed=state[c['field']]) for c in rule['all']])])
            return result
    result['reasons'] = [dict(code='no_matching_rule')]
    return result


def replay_advice(sample, strategy_path=DEFAULT_STRATEGY):
    # Reuse hash/size/token validation; historical evidence never becomes live state.
    from .currency_wars_replay import load_sample
    from .currency_wars import observe
    from .currency_wars_match import read_match
    metadata, scene = load_sample(sample)
    observation, match = observe(scene, .65), read_match(scene, .65)
    import re
    version = re.search(r'(?:Win)?(\d+\.\d+)\.', metadata['game_version'])
    state = dict(page=observation.page_kind, game_version=version[1] if version else None)
    if match:
        state.update(level=match.level, gold=match.gold, hp=match.hp, node=match.node)
    return dict(sample=str(Path(sample).resolve()), historical=True, state=state,
                perception=dict(page=observation.page_kind, match=asdict(match) if match else None),
                advice=advise(state, strategy_path))


def main(argv=None):
    parser = argparse.ArgumentParser(description='货币战争离线建议：不接触游戏，不执行动作')
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--sample', type=Path, nargs='+')
    inputs.add_argument('--state', type=Path)
    parser.add_argument('--strategy', type=Path, default=DEFAULT_STRATEGY)
    args = parser.parse_args(argv)
    try:
        if args.state:
            if args.state.stat().st_size > 65536:
                raise ValueError('状态超过64KiB')
            output = advise(json.loads(args.state.read_text(encoding='utf-8')), args.strategy)
        else:
            output = [replay_advice(p, args.strategy) for p in args.sample]
        print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        return 2 if (isinstance(output, dict) and output['status'] == 'refused') else 0
    except (OSError, ValueError, RuntimeError, RecursionError) as error:
        print(json.dumps(dict(status='refused', action=None, executable=False, error=str(error)), ensure_ascii=False))
        return 2


if __name__ == '__main__':
    import sys
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
