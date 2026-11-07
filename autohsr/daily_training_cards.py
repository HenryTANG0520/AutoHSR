"""Structured, read-only observations of the visible 4.6 daily training cards."""

from collections import Counter
import re

from .challenge_pages import _inside, _overlaps
from .daily_support import COLUMNS, FULL
from .daily_synthesis import compact
from .models import normalize


TRAINING_CARD_VERSION = '4.6.0'

# The title, completion threshold and allowed point values come from the same
# pinned quest pool. Multiple internal quest IDs can render the same card.
TASKS = {
    'login': ('登录游戏', 1, (100,)),
    'assignments': ('派遣委托或收取1次委托奖励', 1, (100,)),
    'daily_quest': ('完成1个日常任务', 1, (200,)),
    'spend_power': ('累计消耗120点开拓力', 120, (200,)),
    'golden_calyx': ('完成1次「拟造花萼（金）」', 1, (100, 200)),
    'crimson_calyx': ('完成1次「拟造花萼（赤）」', 1, (100, 200)),
    'stagnant_shadow': ('完成1次「凝滞虚影」', 1, (100, 200)),
    'cavern_of_corrosion': ('完成1次「侵蚀隧洞」', 1, (100, 200)),
    'echo_of_war': ('完成1次「历战余响」', 1, (200,)),
    'support_win': ('使用支援角色并获得战斗胜利1次', 1, (200,)),
    'synthesis': ('使用1次「万能合成机」', 1, (100,)),
    'photo': ('拍照1次', 1, (100,)),
    'technique': ('累计施放2次秘技', 2, (100,)),
    'break_objects': ('累计击碎3个可破坏物', 3, (200,)),
    'defeat_enemies': ('累计消灭20个敌人', 20, (100,)),
    'weakness_breaks': ('累计触发弱点击破效果5次', 5, (100,)),
    'three_break_types': ('单场战斗中，触发3种不同属性的弱点击破', 1, (100,)),
    'weakness_entry_once': ('利用弱点进入战斗并获胜1次', 1, (100,)),
    'weakness_entry_three': ('利用弱点进入战斗并获胜3次', 3, (100,)),
    'ultimate_finisher': ('施放终结技造成制胜一击1次', 1, (200,)),
    'forgotten_hall': ('完成1次「忘却之庭」', 1, (200,)),
    'simulated_universe_area': ('通关「模拟宇宙」（任意世界）的1个区域', 1, (200,)),
    'simulated_universe': ('完成1次「模拟宇宙」', 1, (500,)),
    'divergent_or_currency': ('完成1次「差分宇宙」或「货币战争」', 1, (500,)),
    'fuel_or_deep_immersifier': ('使用1次「助燃券」或「深度沉浸器」', 1, (100,)),
    'level_character': ('将任意角色等级提升1次', 1, (100,)),
    'level_relic': ('将任意遗器等级提升1次', 1, (100,)),
    'level_light_cone': ('将任意光锥等级提升1次', 1, (100,)),
    'salvage_relic': ('分解任意1件遗器', 1, (100,)),
    'craft_consumable': ('合成1次消耗品', 1, (100,)),
    'craft_material': ('合成1次材料', 1, (100,)),
    'use_consumable': ('使用1件消耗品', 1, (100,)),
}
_KEYS = {compact(title): key for key, (title, _, _) in TASKS.items()}
_STATUSES = {'进行中': 'pending', '前往': 'pending', '领取': 'claimable',
             '已领取': 'claimed', '已完成': 'completed', FULL: 'activity_full'}
STATUS_LABELS = {'pending': '待完成', 'claimable': '可领取', 'claimed': '已领取',
                 'completed': '已完成', 'activity_full': '活跃已满'}


def _field(tokens, column, band, confidence):
    left, right = column
    top, bottom = band
    area = (left, top, right, bottom)
    found = [token for token in tokens if _overlaps(token.box, area)]
    if any(not _inside(token.box, area) or not confidence <= token.score <= 1 for token in found):
        return []
    return found


def _progress(tokens):
    if not tokens:
        return None
    line = sorted(tokens, key=lambda token: token.box[0])
    if (max(token.box[1] for token in line) >= min(token.box[3] for token in line)
            or any(not -.002 <= b.box[0] - a.box[2] <= .018 for a, b in zip(line, line[1:]))):
        return None
    match = re.fullmatch(r'进度([0-9]{1,3})[/／]([0-9]{1,3})',
                         ''.join(normalize(token.text) for token in line))
    return (int(match[1]), int(match[2])) if match else None


def _points(tokens):
    if len(tokens) == 2:
        amount, caption = sorted(tokens, key=lambda token: token.center[1])
        ax, ay = amount.center
        cx, cy = caption.center
        if normalize(caption.text) != '活跃度' or abs(ax - cx) > .012 or not .012 <= cy - ay <= .05:
            return None
        tokens = [amount]
    if len(tokens) != 1:
        return None
    match = re.fullmatch(r'[+＋]([0-9]{1,3})(?:活跃度)?', normalize(tokens[0].text))
    return int(match[1]) if match else None


def _valid(card, activity):
    if not isinstance(card, dict) or card.keys() != {'task', 'progress', 'target', 'points', 'state'}:
        return False
    key, progress, target, points, state = (card[field] for field in ('task', 'progress', 'target', 'points', 'state'))
    if (type(key) is not str or key not in TASKS or type(state) is not str or state not in STATUS_LABELS
            or any(type(number) is not int for number in (progress, target, points))):
        return False
    _, goal, options = TASKS[key]
    if target != goal or not 0 <= progress <= goal or points not in options:
        return False
    if state == 'activity_full':
        return activity == 500
    if state == 'pending':
        return progress < goal and activity < 500
    return progress == goal


def _card(scene, column, activity, confidence):
    title = _field(scene.tokens, column, (.435, .535), confidence)
    title.sort(key=lambda token: (round(token.center[1], 2), token.center[0]))
    key = _KEYS.get(compact(''.join(token.text for token in title)))
    if key is None:
        return None
    progress = _progress(_field(scene.tokens, column, (.375, .428), confidence))
    points = _points(_field(scene.tokens, column, (.60, .71), confidence))
    controls = _field(scene.tokens, column, (.73, .81), confidence)
    if progress is None or points is None or len(controls) != 1:
        return None
    card = dict(task=key, progress=progress[0], target=progress[1], points=points,
                state=_STATUSES.get(normalize(controls[0].text)))
    return card if _valid(card, activity) else None


def _frame_cards(scene, activity, confidence):
    cards = [_card(scene, (left, left + .15), activity, confidence) for left in COLUMNS]
    counts = Counter((card['task'], card['points']) for card in cards if card is not None)
    return [card if card is not None and counts[card['task'], card['points']] == 1 else None for card in cards]


def stable_cards(scenes, activity, confidence):
    first, second = (_frame_cards(scene, activity, confidence) for scene in scenes)
    return [card for before, card in zip(first, second) if card is not None and before == card]


def valid_cards(cards, activity):
    return (isinstance(cards, list) and 0 < len(cards) <= len(COLUMNS)
            and all(_valid(card, activity) for card in cards)
            and len({(card['task'], card['points']) for card in cards}) == len(cards))
