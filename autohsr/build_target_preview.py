"""Preview visible cultivation material routes against the bundled dungeon catalogue."""
from dataclasses import dataclass
import re

from .build_target_read import (
    FRAGMENT_CONFIDENCE, MODAL, MODAL_AREA, SECTIONS, SHORTFALL,
    BuildTargetRead, _has_split_label, guide_blocked, guide_entry,
)
from .currency_wars_prepare import trusted
from .dungeon_workflow import guide_row_fields
from .dungeons import BY_KEY, CATEGORIES, Dungeon, count_limit
from .models import AutomationError, TaskResult, normalize


# The pinned BuildTarget uses the first crop for a compact material detail.
# Its older Calyx reader bounds the source section within the second crop.
MATERIAL_TITLE = (783 / 1920, 318 / 1080, 1083 / 1920, 373 / 1080)
SOURCE_BODY = (790 / 1920, 377 / 1080, 1484 / 1920, 731 / 1080)
SOURCE_LABEL = '获得途径'
DETAIL_BLOCKERS = tuple(label for label in MODAL if label != SOURCE_LABEL)
CALYX_SOURCE = re.compile(r'拟造花萼〖([^〖〗\r\n]{2,64})〗')
LOCK_MARKERS = ('未解锁', '尚未解锁')

# Exact families from the pinned drop index, checked against assets/dungeons.json.
# For golden Calyxes the screen must supply a location. Crimson locations here
# are bound to the family by the reference as well as by the visible source row.
CALYX_FAMILIES = (
    (('漫游指南',), 'calyx_golden', '回忆之蕾', None),
    (('提纯以太', '凝缩以太', '稀薄以太'), 'calyx_golden', '以太之蕾', None),
    (('《绒绒号》典藏版合集', '《绒绒号》连载纪念刊', '《绒绒号》手绘分镜稿'),
     'calyx_crimson', '欢愉之蕾', '「世界尽头」酒馆'),
    (('法吉娜之心', '法吉娜之酒', '法吉娜之泪'), 'calyx_crimson', '虚无之蕾', '「辉痕圣林」神悟树庭'),
)
CALYX_BY_MATERIAL = {material: (category, target, location)
                     for names, category, target, location in CALYX_FAMILIES for material in names}


@dataclass(frozen=True)
class MaterialDetail:
    material: str
    locations: tuple[str, ...]
    unreadable_calyx_rows: int
    lock_marker_rows: int
    target_section_visible: bool


def _inside(token, region):
    x1, y1, x2, y2 = token.box
    return region[0] <= x1 < x2 <= region[2] and region[1] <= y1 < y2 <= region[3]


def _catalogue_row_areas(scene, catalogue):
    for category in CATEGORIES:
        for _, button, name, place in guide_row_fields(scene, category.key, catalogue=catalogue):
            boxes = (button.box, name.box) if place is None else (button.box, name.box, place.box)
            yield (min(box[0] for box in boxes), min(box[1] for box in boxes),
                   max(box[2] for box in boxes), max(box[3] for box in boxes))


def _calyx_locations(scene, page, fragments, heading):
    rows = sorted((token for token in scene.tokens if token.within(SOURCE_BODY)
                   and token.box[1] >= heading.box[3] and token.text.strip().startswith('拟造花萼')),
                  key=lambda token: token.box[1])
    locations = []
    unreadable = 0
    locked = 0
    for token in rows:
        match = CALYX_SOURCE.fullmatch(token.text.strip())
        overlaps = any(other is not token and min(other.box[3], token.box[3]) > max(other.box[1], token.box[1])
                       for other in rows)
        if not match or token not in page.tokens or not _inside(token, SOURCE_BODY) or overlaps:
            unreadable += 1
            continue
        row_area = (SOURCE_BODY[0], token.box[1], MODAL_AREA[2], token.box[3])
        if (scene.has(LOCK_MARKERS, row_area, exact=True)
                or _has_split_label(fragments, LOCK_MARKERS, row_area)):
            locked += 1
            continue
        locations.append(match[1].strip())
    return tuple(dict.fromkeys(locations)), unreadable, locked


def _classify(reader, scene):
    if guide_blocked(scene, modal=DETAIL_BLOCKERS):
        return None, None
    captured = trusted(scene, reader.collection_confidence)
    page = trusted(captured, reader.confidence)
    entry = guide_entry(scene, page)
    if entry is None:
        return None, None
    catalogue_rows = tuple(_catalogue_row_areas(captured, reader.catalogue))
    headings = [token for token in captured.tokens if token.within(MODAL_AREA)
                and normalize(token.text) == SOURCE_LABEL]
    title_region = [token for token in captured.tokens if token.within(MATERIAL_TITLE)]
    if not headings and not any(token.text.strip() in CALYX_BY_MATERIAL for token in title_region):
        kind, entry = reader._classify(scene)
        return (kind, entry) if kind == 'panel' and not catalogue_rows else (None, None)
    titles = [token for token in title_region if token.text.strip() in CALYX_BY_MATERIAL
              or (token.score >= FRAGMENT_CONFIDENCE and re.search(r'[\u3400-\u9fff]', token.text))]
    if len(titles) != 1 or len(headings) != 1:
        return None, None
    title, heading = titles[0], headings[0]
    if (title.text.strip() not in CALYX_BY_MATERIAL or title not in page.tokens
            or heading not in page.tokens or not _inside(title, MATERIAL_TITLE)
            or not _inside(heading, SOURCE_BODY)):
        return None, None
    # A separate directory background only vetoes the cultivation context.
    if any(heading.within(area) for area in catalogue_rows):
        return None, None
    fragments = trusted(scene, 0.)
    if _has_split_label(fragments, (SOURCE_LABEL,), MODAL_AREA):
        return None, None
    locations, unreadable, locked = _calyx_locations(scene, page, fragments, heading)
    target_titles = [token for token in scene.tokens if token.within(SECTIONS)
                     and normalize(token.text) == SHORTFALL]
    target_visible = (len(target_titles) == 1 and target_titles[0] in page.tokens
                      and target_titles[0].box[3] <= title.box[1] and not catalogue_rows)
    return MaterialDetail(title.text.strip(), locations, unreadable, locked, target_visible), entry


def _catalogue_sources(detail, catalogue):
    category, target, reference_location = CALYX_BY_MATERIAL[detail.material]
    sources = []
    for location in detail.locations:
        if reference_location is not None and location != reference_location:
            continue
        dungeon = Dungeon(category, target, location)
        if dungeon in catalogue:
            sources.append(dungeon)
    return sources


def run_preview(ctx):
    if ctx.report.operation != 'build_target_preview':
        raise AutomationError('材料预览需要独立只读入口。')
    reader = BuildTargetRead(ctx)
    limit = ctx.settings.stamina_limit
    preview = dict(state='unverified', material=None, shortfall=None, units_per_challenge=None,
                   count=None, configured_limit=limit, effective_limit=None, target_section_visible=False,
                   source_locations=[], candidates=[])
    ctx.report.build_target = dict(reader.record, preview=preview)
    scene, observation = reader._observe(classify=lambda current: _classify(reader, current))
    sources = [] if observation == 'panel' else _catalogue_sources(observation, reader.catalogue)
    candidates = []
    if observation != 'panel' and observation.target_section_visible:
        for source in sources:
            rule = BY_KEY[source.category]
            candidates.append(dict(category=source.category, target=source.name, location=source.location,
                                   stamina_cost=rule.cost, max_challenges_by_config=count_limit(rule, limit)))
    preview['evidence'] = reader._save(scene, 'build_target_preview')
    reader._verify_observation(scene)
    if observation == 'panel':
        ctx.report.build_target['page_verified'] = True
        preview.update(state='panel_observed', target_section_visible=True)
        detail = '已保存培养目标页。打开一项材料详情并显示获得途径可核对目录候选。'
    else:
        preview.update(state='catalogue_candidates' if candidates else 'material_observed',
                       material=observation.material, candidates=candidates,
                       target_section_visible=observation.target_section_visible,
                       source_locations=[source.location for source in sources],
                       lock_marker_rows=observation.lock_marker_rows,
                       unmatched_calyx_rows=observation.unreadable_calyx_rows + len(observation.locations) - len(sources))
        detail = f'已观察材料「{observation.material}」及 {len(candidates)} 项目录候选，缺口和单轮产量待核实。'
    return TaskResult('build_target_preview', 'partial', detail)
