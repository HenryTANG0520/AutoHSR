"""Navigate and inventory the live Survival Index without spending resources."""
from __future__ import annotations

import re
import json
from datetime import datetime
from pathlib import Path

from .config import ROOT, RESOURCE_ROOT
from .dungeons import CATEGORIES, Dungeon, category_for, save_catalogue, load_catalogue, mission_name, mission_map
from .models import AutomationError, Scene, normalize


def guide_rows(scene: Scene, category: str, *, strict=True):
    """Only complete visible rows: title, map and one associated entry."""
    buttons = [t for t in scene.tokens if t.within((.74, .28, .88, .80))
               and normalize(t.text) in ("进入", "传送", "前往")]
    result = []
    offset = .09 if category == "echo_of_war" else 0 if category == "planar" else .02
    for button in buttons:
        names = [t for t in scene.tokens if t.within((.44, .26, .70, .82))
                 and abs(t.center[1] - (button.center[1] - offset)) < .018
                 and re.search(r"[\u4e00-\u9fff]", t.text)
                 and normalize(t.text) not in ("基础掉落", "推荐属性", "基础奖励")]
        if len(names) != 1:
            continue
        name = names[0]
        if category == "planar" and scene.has("位面饰品", (.14,.26,.35,.83), exact=True):
            result.append((Dungeon(category, name.text.strip(), "位面饰品"), button))
            continue
        if strict and category == "calyx_golden" and name.text not in ("回忆之蕾", "以太之蕾", "藏珍之蕾"):
            continue
        if strict and category == "calyx_crimson" and not re.fullmatch(r"[\u4e00-\u9fff]{2}之蕾", name.text):
            continue
        places = [t for t in scene.tokens if t.within((.45, .26, .72, .83))
                  and .015 < t.center[1] - name.center[1] < .055
                  and re.search(r"[\u4e00-\u9fff]", t.text)]
        if len(places) != 1:
            continue
        result.append((Dungeon(category, mission_name(category, name.text), mission_map(places[0].text)), button))
    return result


def refine_scene(workflow, scene, category):
    if hasattr(workflow.ctx, "refine_dungeon_rows"):
        workflow.ctx.refine_dungeon_rows(scene, category)
    return scene


def scroll_list(workflow, scene, amount, *, left=False):
    if not workflow._tab(scene, "生存索引"):
        raise AutomationError("未核实生存索引，未滚动副本列表。")
    workflow.ctx.move(scene, (.27 if left else .71, .56))
    workflow.ctx.scroll(amount)
    workflow._pause()
    return workflow._snapshot()


def select_category(workflow, category):
    scene = workflow._open_guide("生存索引")
    # Category list remembers its previous offset. Rewind it before searching.
    scene = scroll_list(workflow, scene, 12000, left=True)
    for _ in range(8):
        token = scene.find(category.label, (.14, .27, .35, .81), exact=True)
        if token:
            workflow._click(scene, token)
            scene = workflow._wait(lambda s: workflow._tab(s, "生存索引"), description="核实副本分类")
            # Mission lists also remember their offset; always start at the top.
            scene = scroll_list(workflow, scene, 60000)
            if category.weekly_limit:
                workflow._weekly_rewards = weekly_rewards(scene)
            return scene
        scene = scroll_list(workflow, scene, -1440, left=True)
    raise AutomationError(f"生存索引未找到{category.label}；可能尚未解锁。")


def weekly_rewards(scene):
    if not scene.has("本周可领取奖励次数", (.40,.26,.70,.34)):
        return None
    counts = []
    for token in scene.tokens:
        if token.within((.44,.32,.58,.38)):
            match = re.fullmatch(r"([0-3])/3", normalize(token.text))
            if match:
                counts.append(int(match.group(1)))
    return counts[0] if len(counts) == 1 else None


def open_dungeon(workflow):
    category = category_for(workflow.settings)
    scene = workflow._snapshot()
    if workflow._calyx_target(scene) and not category.weekly_limit:
        return scene
    workflow._calyx_location = None
    scene = select_category(workflow, category)
    if category.weekly_limit and getattr(workflow, "_weekly_rewards", None) is None:
        raise AutomationError("未核实历战余响本周剩余领奖次数，未开始挑战。")
    if category.weekly_limit and workflow._weekly_rewards == 0:
        raise AutomationError("历战余响本周领奖次数已用完，未进行无奖励挑战。")
    target = normalize(workflow.settings.target_name)
    location = normalize(workflow.settings.target_location)
    previous = None
    repeats = 0
    for _ in range(60):
        scene = refine_scene(workflow, scene, category.key)
        if not workflow._tab(scene, "生存索引"):
            raise AutomationError("查找副本时已离开生存索引。")
        rows = [(mission, button) for mission, button in guide_rows(scene, category.key)
                if normalize(mission.name) == target and normalize(mission.location) == location]
        if len(rows) > 1:
            raise AutomationError("同名同地点副本出现多个入口，未选择。")
        if rows:
            mission, button = rows[0]
            workflow.ctx.evidence(scene, "dungeon_guide_target")
            workflow._click(scene, button)
            scene = workflow._wait(lambda s: workflow._calyx(s) and s.has(mission.name),
                                   timeout=60, description=f"核实{mission.name}挑战页")
            workflow._calyx_location = mission.location
            workflow.ctx.evidence(scene, "dungeon_details_verified")
            return scene
        signature = tuple((normalize(m.name), normalize(m.location)) for m,b in guide_rows(scene, category.key))
        repeats = repeats + 1 if signature == previous else 0
        previous = signature
        if repeats >= 2:
            break
        scene = scroll_list(workflow, scene, -1440)
    raise AutomationError(f"未找到完整副本入口：{workflow.settings.target_name} / {workflow.settings.target_location}。")


def scan_catalogue(workflow):
    categories = CATEGORIES if workflow.settings.dungeon_category == "auto" else (category_for(workflow.settings),)
    selected = {category.key for category in categories}
    try:
        existing = load_catalogue(RESOURCE_ROOT / "assets" / "dungeons.json", ROOT / "dungeons.local.json")
    except (ValueError, TypeError, OSError):
        existing = load_catalogue(RESOURCE_ROOT / "assets" / "dungeons.json")
    missions = {(m.category, normalize(m.name), normalize(m.location)): m
                for m in existing
                if m.category not in selected}
    results = {}
    for category in categories:
        scene = select_category(workflow, category)
        previous = None
        repeats = 0
        found = set()
        for page in range(80):
            scene = refine_scene(workflow, scene, category.key)
            if not workflow._tab(scene, "生存索引"):
                raise AutomationError("副本采集离开生存索引，已停止。")
            screenshot = workflow.ctx.evidence(scene, f"catalogue_{category.key}_{page:02}")
            if screenshot:
                Path(screenshot).with_suffix(".json").write_text(json.dumps(
                    dict(category=category.key, tokens=[dict(text=t.text, score=t.score, box=t.box) for t in scene.tokens]),
                    ensure_ascii=False, indent=2), encoding="utf-8")
            rows = guide_rows(scene, category.key)
            for mission, _ in rows:
                key = (mission.category, normalize(mission.name), normalize(mission.location))
                missions[key] = mission
                found.add(key)
            # Compare only the list region; animated backgrounds/currency cannot
            # prevent end detection. Require three identical settled observations.
            signature = tuple((normalize(m.name), normalize(m.location)) for m,b in rows)
            repeats = repeats + 1 if signature == previous else 0
            previous = signature
            if repeats >= 2:
                break
            scene = scroll_list(workflow, scene, -1440)
        else:
            raise AutomationError(f"{category.label}列表未确认到底，目录未覆盖旧文件。")
        if not found:
            raise AutomationError(f"{category.label}未识别到完整副本行，目录未覆盖旧文件。")
        results[category.key] = len(found)
        workflow.ctx.log(f"{category.label}：采集{len(found)}个副本入口。")
    destination = ROOT / "dungeons.local.json"
    save_catalogue(destination, list(missions.values()), observed_at=datetime.now().astimezone().isoformat(),
                   source=workflow.ctx.report.run_dir, categories=results)
    workflow.ctx.report.dungeon_catalogue = dict(path=str(destination), count=len(missions), categories=results)
    return workflow._result("dungeon_catalogue", "ok", f"已采集{len(missions)}个副本入口，未开始挑战或消耗资源。")
