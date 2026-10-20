from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", ROOT))
CONFIG_PATH = ROOT / "config.json"


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
    auto_launch: bool = False
    action_delay: float = 1.0
    battle_timeout: int = 900
    ocr_confidence: float = 0.65
    differential_universe_runs: int = 3

    def validate(self, operation: str = "daily") -> None:
        if not isinstance(self.game_path, str) or not self.game_path.lower().endswith("starrail.exe"):
            raise ValueError("请选择 StarRail.exe 游戏程序。")
        if operation == "save" or (operation == "daily" and self.battle and self.allow_stamina_spend):
            if not isinstance(self.target_name, str) or len(self.target_name.strip()) < 2:
                raise ValueError("请选择副本，例如：回忆之蕾。")
            if not isinstance(self.target_location, str):
                raise ValueError("副本地点必须是文字；留空时仅允许唯一匹配目标。")
            if operation == "daily" and not self.target_location.strip():
                raise ValueError("刷本必须填写地点，以区分同名花萼；未开始挑战。")
            if isinstance(self.stamina_limit, bool) or not isinstance(self.stamina_limit, int) or not 10 <= self.stamina_limit <= 240 or self.stamina_limit % 10:
                raise ValueError("本次运行开拓力上限应为 10～240 之间的 10 的倍数。")
            if isinstance(self.rounds, bool) or not isinstance(self.rounds, int) or not 1 <= self.rounds <= 6:
                raise ValueError("每次挑战轮数应为 1～6。")
            from .dungeons import category_for, count_limit
            category = category_for(self)
            if self.challenge_count is not None:
                if type(self.challenge_count) is not int or not 1 <= self.challenge_count <= count_limit(category):
                    raise ValueError(f"{category.label}本次挑战次数应为 1～{count_limit(category)}。")
                if self.challenge_count * category.cost > self.stamina_limit:
                    raise ValueError("所选次数的预计消耗超过本次开拓力上限，请减少次数或调整上限。")
        for name in ("use_support", "assignments", "battle", "allow_stamina_spend", "daily", "mail", "battlepass", "auto_launch"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} 必须是布尔值。")
        for name in ("action_delay", "battle_timeout", "ocr_confidence"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name} 必须是有限数值。")
        if not 0.3 <= self.action_delay <= 5 or not 60 <= self.battle_timeout <= 3600 or not 0.4 <= self.ocr_confidence <= 0.99:
            raise ValueError("等待时间、战斗超时或 OCR 阈值超出允许范围。")
        if (isinstance(self.differential_universe_runs, bool) or
                not isinstance(self.differential_universe_runs, int) or
                not 1 <= self.differential_universe_runs <= 3):
            raise ValueError("差分宇宙本次自动演算局数应为 1～3 局。")

    def save(self, path: Path = CONFIG_PATH) -> None:
        self.validate("save")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

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
