from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from .storage import replace_file
from .du_station_policy import default_priorities

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
CONFIG_PATH = ROOT / "config.json"


class SettingsError(ValueError):
    """Validation failure with a field the desktop can focus without guessing."""
    def __init__(self, field: str, message: str):
        self.field = field
        super().__init__(message)


@dataclass
class Settings:
    game_path: str = r"E:\miHoYo Launcher\games\Star Rail Game\StarRail.exe"
    target_name: str = "回忆之蕾"
    target_location: str = "城郊雪原"
    stamina_limit: int = 240
    rounds: int = 6
    dungeon_category: str = "auto"
    challenge_count: int | None = None
    use_support: bool = True
    assignments: bool = True
    battle: bool = True
    allow_stamina_spend: bool = True
    daily: bool = True
    mail: bool = False
    battlepass: bool = False
    auto_launch: bool = True  # Legacy field; daily startup now always checks/launches.
    overlay_logs: bool = True
    daily_synthesis: bool = True
    action_delay: float = 1.0
    battle_timeout: int = 900
    ocr_confidence: float = 0.65
    differential_universe_runs: int = 3
    differential_universe_save: bool = False
    differential_universe_rewards: bool = False
    differential_universe_daily: bool = False
    differential_universe_daily_from: str = ""
    differential_universe_team: str = "哈哈哈哈"
    differential_universe_mode: str = "periodic"
    differential_universe_station_custom: bool = False
    differential_universe_station_priority: dict[str,int] = field(default_factory=default_priorities)
    differential_universe_station_disabled: list[str] = field(default_factory=list)
    weekly_enabled: bool = False
    weekly_mode: str = "differential_universe"
    weekly_day: int = 1
    weekly_time: str = "04:00"
    weekly_runs: int = 1
    currency_remembrance_name: str = ""
    currency_fast_mode: bool = False
    currency_runs: int = 1  # Only the explicit loop entry uses this; 0 = until stopped.
    currency_until_points: bool = False  # Optional weekly target; runs remains the new-game ceiling.
    power_plan: list[dict] = field(default_factory=list)
    power_plan_keep: bool = False
    power_plan_fill: bool = True
    echo_of_war_enabled: bool = False
    echo_of_war_start_day: int = 1
    echo_of_war_target: str = '毁灭的开端'
    echo_of_war_location: str = '支援舱段'

    def __post_init__(self):
        from copy import deepcopy
        self.differential_universe_station_priority=deepcopy(self.differential_universe_station_priority)
        self.differential_universe_station_disabled=deepcopy(self.differential_universe_station_disabled)
        self.power_plan=deepcopy(self.power_plan)

    def validate(self, operation: str = "daily") -> None:
        from .echo_weekly import validate_settings as validate_echo
        validate_echo(self)
        if operation in ('save','power_plan'):
            from .power_plan import items,plan_spec
            items(self.power_plan)
            if operation=='power_plan':plan_spec(self)
        for name in ('power_plan_keep','power_plan_fill'):
            if type(getattr(self,name)) is not bool:raise SettingsError(name,f'{name}必须为布尔值。')
        from .du_station_policy import StationPreferences
        StationPreferences.from_settings(self)
        from .weekly_plan import validate_schedule
        validate_schedule(self)
        from .currency_wars_loop_store import runs_value
        try:runs_value(self.currency_runs)
        except ValueError as error:raise SettingsError('currency_runs',str(error)) from error
        from .currency_wars_names import validate_name
        try:validate_name(self.currency_remembrance_name)
        except ValueError as error:raise SettingsError('currency_remembrance_name',str(error)) from error
        if not isinstance(self.game_path, str) or not self.game_path.lower().endswith("starrail.exe"):
            raise SettingsError("game_path", "请选择 StarRail.exe 游戏程序。")
        if operation == "save" or (operation in ("daily", "plan") and self.battle and self.allow_stamina_spend) or operation=='power_plan':
            use_default=operation!='power_plan' or self.power_plan_fill
            if use_default and (not isinstance(self.target_name, str) or len(self.target_name.strip()) < 2):
                raise SettingsError("target_name", "请选择副本，例如：回忆之蕾。")
            if use_default and not isinstance(self.target_location, str):
                raise SettingsError("target_location", "副本地点必须是文字；留空时仅允许唯一匹配目标。")
            if use_default and operation in ("daily", "plan",'power_plan') and not self.target_location.strip():
                raise SettingsError("target_location", "请填写副本地点，以区分同名花萼。")
            if isinstance(self.stamina_limit, bool) or not isinstance(self.stamina_limit, int) or not 10 <= self.stamina_limit <= 240 or self.stamina_limit % 10:
                raise SettingsError("stamina_limit", "本次开拓力上限应为 10～240 之间的 10 的倍数。")
            if isinstance(self.rounds, bool) or not isinstance(self.rounds, int) or not 1 <= self.rounds <= 6:
                raise SettingsError("rounds", "每次挑战轮数应为 1～6。")
            from .dungeons import category_for, count_limit
            category = category_for(self) if use_default else None
            if use_default and self.challenge_count is not None:
                if type(self.challenge_count) is not int or not 1 <= self.challenge_count <= count_limit(category):
                    raise SettingsError("challenge_count", f"{category.label}本次挑战次数应为 1～{count_limit(category)}。")
                if self.challenge_count * category.cost > self.stamina_limit:
                    raise SettingsError("challenge_count", "所选次数的预计消耗超过本次开拓力上限，请减少次数或调整上限。")
        for name in ("use_support", "assignments", "battle", "allow_stamina_spend", "daily", "mail", "battlepass", "auto_launch", "overlay_logs", "daily_synthesis", "differential_universe_save", "differential_universe_rewards", "differential_universe_daily", "currency_fast_mode", "currency_until_points"):
            if type(getattr(self, name)) is not bool:
                raise SettingsError(name, f"{name} 必须是布尔值。")
        for name, title, low, high in (("action_delay", "操作间隔（秒）", 0.3, 5),
                                      ("battle_timeout", "战斗超时（秒）", 60, 3600),
                                      ("ocr_confidence", "OCR 阈值", 0.4, 0.99)):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise SettingsError(name, f"{title}必须是有限数值。")
            if not low <= value <= high:
                raise SettingsError(name, f"{title}应为 {low}～{high}。")
        if (isinstance(self.differential_universe_runs, bool) or
                not isinstance(self.differential_universe_runs, int) or
                not 1 <= self.differential_universe_runs <= 10):
            raise SettingsError("differential_universe_runs", "差分宇宙本次演算局数应为 1～10 局。")
        if (not isinstance(self.differential_universe_team, str)
                or not self.differential_universe_team.strip()
                or len(self.differential_universe_team)>32):
            raise SettingsError("differential_universe_team", "请填写 1～32 字的差分宇宙预设编队名称。")
        if self.differential_universe_mode not in ('periodic','normal'):
            raise SettingsError("differential_universe_mode", "差分宇宙模式必须是 periodic 或 normal。")
        start_day=self.differential_universe_daily_from
        if not isinstance(start_day,str):
            raise SettingsError('differential_universe_daily_from', '通关后日常起始游戏日须为 YYYY-MM-DD 或留空。')
        if start_day:
            from datetime import date
            try:
                valid=date.fromisoformat(start_day).isoformat()==start_day
            except ValueError:
                valid=False
            if not valid:
                raise SettingsError('differential_universe_daily_from', '通关后日常起始游戏日须为 YYYY-MM-DD 或留空。')

    def save(self, path: Path = CONFIG_PATH) -> None:
        self.validate("save")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        replace_file(temp,path)

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> Settings:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        unknown = set(data) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"配置中存在未知字段：{', '.join(sorted(unknown))}")
        result = cls(**data)
        result.validate("save")
        return result
