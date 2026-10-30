"""Explicit two-team challenge configuration, without game or input authority.

The pinned support manifest supplies known character IDs and exact display
names only. A valid plan does not establish ownership, availability, selected
teams, or calibrated challenge-page recognition. No techniques or retries are
scheduled by this configuration.
"""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import sys
from types import MappingProxyType
import unicodedata


UPSTREAM_COMMIT = '7cf6c6bed474539485d3b1504077ac352866829f'
# Git text checkout may use LF or CRLF; bind the exact LF-normalized content.
MANIFEST_SHA256 = 'dd7a383d5e82265278e8636f642a956084d9a4ff0ca9c8672879fadba0e7677b'
MAX_MANIFEST_BYTES = 256 * 1024
MODE_LIMITS = MappingProxyType({
    'memory_of_chaos': 12,
    'pure_fiction': 4,
    'apocalyptic_shadow': 4,
})
_PLAN_KEYS = frozenset(('mode', 'levels', 'team1', 'team2'))


class ChallengePlanError(ValueError):
    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


def _manifest_path():
    # Match packaged resource lookup without importing Settings or a Runner.
    root = (Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parent.parent)
    return Path(getattr(sys, '_MEIPASS', root)) / 'assets/upstream/March7thAssistant/support/sources.json'


def _text(value):
    return (type(value) is str and 0 < len(value) <= 80 and value == value.strip()
            and not any(unicodedata.category(char) in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp') for char in value))


@lru_cache(maxsize=1)
def _catalogue():
    try:
        with _manifest_path().open('rb') as stream:
            raw = stream.read(MAX_MANIFEST_BYTES + 1)
        if (len(raw) > MAX_MANIFEST_BYTES
                or hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest() != MANIFEST_SHA256):
            raise ValueError('manifest changed')
        data = json.loads(raw)
        if data['commit'] != UPSTREAM_COMMIT or len(data['images']) != 105:
            raise ValueError('manifest source changed')
        identities = {}
        display_names = {}
        for row in data['images']:
            character, name = row['character'], row['name']
            if (type(character) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]{0,63}', character)
                    or not _text(name) or character in identities):
                raise ValueError('invalid character catalogue')
            identities[character] = name
            display_names.setdefault(name, []).append(character)
        aliases = {name: matches[0] for name, matches in display_names.items() if len(matches) == 1}
        return MappingProxyType(identities), MappingProxyType(aliases)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError):
        raise ChallengePlanError('catalogue', '无法核实固定角色目录，不能建立高难编队计划。') from None


def known_characters():
    """Known asset identities; this does not enumerate an account's roster."""
    return tuple(_catalogue()[0])


def _team(value, field):
    if type(value) not in (list, tuple) or len(value) != 4:
        raise ChallengePlanError(field, '高难每队必须明确指定四名角色。')
    identities, aliases = _catalogue()
    result = []
    for name in value:
        if not _text(name):
            raise ChallengePlanError(field, '角色须使用明确标识或完整名称，不能含空白边界或控制字符。')
        if name in identities:
            character = name
        elif name in aliases:
            character = aliases[name]
        else:
            raise ChallengePlanError(field, '角色未知或名称不唯一，请使用固定目录中的明确角色标识。')
        if character in result:
            raise ChallengePlanError(field, '同一队伍不能重复指定角色。')
        result.append(character)
    return tuple(result)


@dataclass(frozen=True)
class ChallengePlan:
    mode: str
    levels: tuple[int, int]
    team1: tuple[str, str, str, str]
    team2: tuple[str, str, str, str]

    def __post_init__(self):
        if type(self.mode) is not str or self.mode not in MODE_LIMITS:
            raise ChallengePlanError('mode', '高难模式须为混沌回忆、虚构叙事或末日幻影的明确标识。')
        if (type(self.levels) not in (list, tuple) or len(self.levels) != 2
                or any(type(level) is not int for level in self.levels)):
            raise ChallengePlanError('levels', '层数范围必须明确为两个整数，不能使用布尔值或数字字符串。')
        first, last = self.levels
        if not 1 <= first <= last <= MODE_LIMITS[self.mode]:
            raise ChallengePlanError('levels', '层数范围超出本模式范围或起止顺序无效。')
        team1, team2 = _team(self.team1, 'team1'), _team(self.team2, 'team2')
        if set(team1) & set(team2):
            raise ChallengePlanError('teams', '两队不能重复指定同一角色。')
        object.__setattr__(self, 'levels', (first, last))
        object.__setattr__(self, 'team1', team1)
        object.__setattr__(self, 'team2', team2)

    @classmethod
    def from_dict(cls, raw):
        if type(raw) is not dict or set(raw) != _PLAN_KEYS:
            raise ChallengePlanError('plan', '高难计划必须且只能包含mode、levels、team1、team2。')
        return cls(raw['mode'], raw['levels'], raw['team1'], raw['team2'])

    def to_dict(self):
        return dict(mode=self.mode, levels=list(self.levels),
                    team1=list(self.team1), team2=list(self.team2))

    @property
    def digest(self):
        raw = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    @property
    def teams(self):
        return self.team1, self.team2

    @property
    def level_start(self):
        return self.levels[0]

    @property
    def level_end(self):
        return self.levels[1]


def from_values(mode, levels, team1, team2):
    return ChallengePlan(mode, levels, team1, team2)
