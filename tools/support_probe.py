"""Capture AutoHSR's support picker and stop before selecting or fighting.

Uses the normal guarded workflow. The instrumented click cannot pass a
support picker, and never permits the final start-battle control.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import Stopped, Token


def main() -> None:
    settings = Settings.load(ROOT / "test-config.json")
    settings.assignments = False
    settings.daily = False
    settings.mail = False
    settings.battlepass = False
    settings.battle = True
    settings.use_support = True
    settings.stamina_limit = 10
    settings.rounds = 1
    original_click = Context.click

    def capture_then_stop(context, scene, target):
        picker = (scene.has("支援角色", (0.01, 0.03, 0.32, 0.16), exact=True)
                  and scene.has("仅查看好友", (0.01, 0.09, 0.25, 0.20), exact=True))
        starts_battle = isinstance(target, Token) and target.text.strip() == "开始挑战"
        if picker or starts_battle:
            context.evidence(scene, "support_picker_calibration")
            raise Stopped("支援校准已保存画面；未选择角色、未开始战斗。")
        return original_click(context, scene, target)

    Context.click = capture_then_stop
    try:
        report = Runner(settings).run()
    finally:
        Context.click = original_click
    (ROOT / "runs" / "support-probe.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
