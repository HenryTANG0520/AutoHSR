"""Rules transcribed from the local 4.6 tutorial and observed transactions.

No streak/base income or shop pool probability is inferred from one balance
change. Standard interest and the overclock exception are separate rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Mode(str, Enum):
    STANDARD = "standard"
    OVERCLOCK = "overclock"


def _amount(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("金币必须是非负整数")
    return value


def interest(mode: Mode, gold: int) -> int:
    """Tutorial captures 36 and 81: 1 per 10, cap 5; overclock pays 0."""
    _amount(gold)
    if mode == Mode.OVERCLOCK:
        return 0
    if mode == Mode.STANDARD:
        return min(5, gold // 10)
    raise ValueError("未确认博弈模式")


@dataclass(frozen=True)
class SpendAssessment:
    affordable: bool
    remaining: int
    interest_before: int
    interest_after: int
    interest_lost: int


def assess_spend(mode: Mode, gold: int, cost: int) -> SpendAssessment:
    _amount(gold)
    _amount(cost)
    before = interest(mode, gold)
    affordable = cost <= gold
    remaining = gold - cost if affordable else gold
    after = interest(mode, remaining)
    return SpendAssessment(affordable, remaining, before, after, before - after)


REFRESH_COST = 2  # Shop capture 101; tutorial 38.
EXPERIENCE_COST = 4  # Before/after captures 102, 103.
EXPERIENCE_GAIN = 4


def reserve_for_interest(mode: Mode, gold: int) -> int:
    """Keep the currently reached interest tier, not an invented optimum."""
    return interest(mode, gold) * 10
