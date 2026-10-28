"""Recognized free transitions and independently verified match-gold receipts."""
import re


FREE_ACTIONS = frozenset((
    'start_standard_a8_40', 'advance_standard_preview', 'advance_standard_plane',
    'collect_standard_loot', 'inspect_standard_unit', 'close_standard_unit',
    'open_standard_shop', 'close_standard_shop', 'deploy_standard_owned', 'start_standard_node',
    'continue_standard_node', 'advance_standard_next_plane', 'close_standard_arrival_shop',
    'close_standard_shop_after_purchase',
    'stage_standard_exchange','inspect_standard_exchange_unit','close_standard_exchange_unit','close_standard_exchange_stale_panel',
    'settle_standard_final_victory', 'settle_standard_match_rating',
    'settle_standard_match_summary', 'settle_standard_match_statistics',
))
PAID_ACTIONS = frozenset(('buy_standard_offer', 'buy_standard_experience', 'refresh_standard_shop'))


def valid_receipt(action):
    """A green action status alone cannot settle a financial intention."""
    receipt, target = action.get('receipt', {}), action.get('target')
    if (action.get('action') not in PAID_ACTIONS or action.get('status') != 'verified'
            or not action.get('before') or not action.get('after') or not isinstance(receipt, dict)
            or receipt.get('schema') != 1 or receipt.get('currency') != 'match_gold'
            or not isinstance(target, (list, tuple)) or not target
            or not isinstance(target[0], str) or not re.fullmatch(r'[1-3]-[1-9][0-9]?', target[0])
            or receipt.get('node') != target[0]):
        return False
    expected_length = 8 if action['action'] == 'buy_standard_offer' else 7
    if (len(target) != expected_length or any(type(value) is not int for value in target[1:4])
            or not 0 <= target[1] <= 99999 or not 0 < target[2] <= 100 or not 1 <= target[3] <= 10):
        return False
    before, after, price = (receipt.get(k) for k in ('gold_before', 'gold_after', 'price'))
    if (any(type(value) is not int or not 0 <= value <= 99999 for value in (before, after, price))
            or before-after != price or receipt.get('gold_before') != target[1]):
        return False
    if action['action'] == 'buy_standard_offer':
        return (len(target) == 8 and type(target[4]) is int and 0 <= target[4] <= 4
                and isinstance(target[5], str) and 0 < len(target[5]) <= 80
                and type(target[6]) is int and 0 <= target[6] <= 99
                and price == target[6] and receipt.get('slot') == target[4]
                and receipt.get('name') == target[5] and receipt.get('level_after') == target[3]
                and isinstance(target[7], str) and re.fullmatch(r'[0-9a-f]{64}', target[7]) is not None
                and receipt.get('bench_before') == target[7] and isinstance(receipt.get('bench_after'), str)
                and re.fullmatch(r'[0-9a-f]{64}', receipt['bench_after']) is not None
                and receipt['bench_after'] != target[7] and receipt.get('bench_changed') is True)
    if action['action'] == 'refresh_standard_shop':
        if (type(target[4]) is not int or not 0 <= target[4] <= 99 or price != target[4]
                or receipt.get('level_after') != target[3]
                or any(not isinstance(v,str) or re.fullmatch(r'[0-9a-f]{64}',v) is None for v in target[5:])
                or receipt.get('table_before') != target[5] or receipt.get('table_after') == target[5]
                or receipt.get('bench_before') != target[6] or receipt.get('bench_after') != target[6]):
            return False
        from .currency_wars_standard_refresh import table_digest
        try:
            return (table_digest(receipt.get('offers_before')) == target[5]
                    and table_digest(receipt.get('offers_after'),complete=True) == receipt.get('table_after'))
        except ValueError:
            return False
    if (any(type(value) is not int for value in target[4:]) or not 0 <= target[4] < target[5] <= 9999
            or not target[3] < target[6] <= 10 or price != 4 or receipt.get('hp_after') != target[2]):
        return False
    level, experience = receipt.get('level_after'), receipt.get('experience_after')
    if experience is None:
        return (target[3] == 9 and level == 10 and 1 <= target[5]-target[4] <= 4
                and receipt.get('max_level_verified') is True)
    if (type(level) is not int or not 1 <= level <= 10 or not isinstance(experience, list)
            or len(experience) != 2 or any(type(x) is not int for x in experience)
            or not 0 <= experience[0] < experience[1] <= 9999):
        return False
    gained = (experience[0]-target[4] if level == target[3] and experience[1] == target[5]
              else target[5]-target[4]+experience[0] if level == target[3]+1 else None)
    return gained == 4


def ledger_status(actions):
    for action in actions:
        if action.get('status') != 'verified':
            return 'pending' if action.get('status') == 'pending' else 'unknown'
        name = action.get('action', '')
        if name in PAID_ACTIONS:
            if not valid_receipt(action):
                return 'unknown'
        elif name not in FREE_ACTIONS and not re.fullmatch(r'(?:select|confirm)_standard_environment_[0-2]', name):
            return 'unknown'
    return 'clear'
