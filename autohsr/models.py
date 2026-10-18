from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

ROI = tuple[float, float, float, float]
FULL: ROI = (0, 0, 1, 1)


def normalize(text: str) -> str:
    return re.sub(r"[\s·•:：,，。!！?？()（）]", "", text).casefold()


@dataclass(frozen=True)
class Token:
    text: str
    score: float
    box: tuple[float, float, float, float]

    @property
    def center(self) -> tuple[float, float]:
        x1, y1, x2, y2 = self.box
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    def within(self, roi: ROI) -> bool:
        x, y = self.center
        return roi[0] <= x <= roi[2] and roi[1] <= y <= roi[3]


@dataclass
class Scene:
    tokens: list[Token]
    image: object = None
    geometry: object = None
    captured_at: float = 0

    @property
    def text(self) -> str:
        return "\n".join(t.text for t in self.tokens)

    def find(self, labels: str | Iterable[str], roi: ROI = FULL, exact: bool = False) -> Token | None:
        labels = [labels] if isinstance(labels, str) else list(labels)
        candidates = []
        for token in self.tokens:
            if not token.within(roi):
                continue
            text = normalize(token.text)
            for label in labels:
                wanted = normalize(label)
                if text == wanted or (not exact and wanted and wanted in text):
                    candidates.append((text == wanted, token.score, -len(text), token))
                    break
        return max(candidates, key=lambda v: v[:3])[3] if candidates else None

    def has(self, labels: str | Iterable[str], roi: ROI = FULL, exact: bool = False) -> bool:
        return self.find(labels, roi, exact) is not None


class AutomationError(RuntimeError):
    pass


class EmptyCapture(AutomationError):
    """A blank transition frame; observation can be retried without input."""
    pass


class Stopped(AutomationError):
    pass


class FocusLost(AutomationError):
    pass


class InputInterrupted(AutomationError):
    pass


@dataclass
class TaskResult:
    task: str
    status: str
    detail: str


@dataclass
class RunReport:
    status: str = "partial"
    results: list[TaskResult] = field(default_factory=list)
    stamina_spent: int = 0
    daily_verified: bool = False
    engagement: int | None = None
    run_dir: str = ""
    operation: str = "daily"
    started_at: str = ""
    finished_at: str = ""
    source: str = ""
    game_day: str = "unverified"
    budget_scope: str = "run"
    stamina_limit: int = 0
    stamina_pending: int = 0
    failure_task: str = ""
    error: str = ""
    safe_next: str = ""
    exit_status: str = "not_requested"
    currency_wars: dict = field(default_factory=dict)
    differential_universe: dict = field(default_factory=dict)
    report_saved: bool = False
    report_write_error: str = ""

    def to_dict(self) -> dict:
        from dataclasses import asdict
        return asdict(self)
