"""Preview visible cultivation materials and Calyx rewards without game input."""
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
import re
from unicodedata import normalize as unicode_normalize

from .build_target_read import (
    FRAGMENT_CONFIDENCE, MODAL, MODAL_AREA, SECTIONS, SHORTFALL,
    BuildTargetRead, _has_split_label, guide_blocked, guide_entry,
)
from .build_target_shortfall import GALAXY_SANDBOX, ROLE, ResultShortfall, TargetPanel, result_shortfall, target_panel
from .build_target_synthesis import SynthesisPreview, synthesis_preview
from .currency_wars_prepare import trusted
from .dungeon_workflow import guide_row_fields
from .dungeons import BY_KEY, CATEGORIES, Dungeon, count_limit
from .models import AutomationError, TaskResult, normalize
from .power_plan import items
from .workflows import DailyWorkflow


# The pinned BuildTarget uses the first crop for a compact material detail.
# Its older Calyx reader bounds the source section within the second crop.
MATERIAL_TITLE = (783 / 1920, 318 / 1080, 1083 / 1920, 373 / 1080)
OBSERVATION_TITLE = (*MATERIAL_TITLE[:2], .61, MATERIAL_TITLE[3])
HELD_AREA = (.25, .65, .39, .735)
SOURCE_BODY = (790 / 1920, 377 / 1080, 1484 / 1920, 731 / 1080)
OBSERVATION_SOURCE = (.40, SOURCE_BODY[1], SOURCE_BODY[2], .71)
SOURCE_LABEL = '获得途径'
DETAIL_BLOCKERS = tuple(label for label in MODAL if label != SOURCE_LABEL)
CALYX_SOURCE = re.compile(r'拟造花萼〖([^〖〗\r\n]{2,64})〗')
LOCK_MARKERS = ('未解锁', '尚未解锁')
HELD_COUNT = r'(?:0|[1-9][0-9]{0,8}|[1-9][0-9]{0,2}(?:,[0-9]{3}){1,2})'
CALYX_TITLE = (.59, .09, .96, .15)
CALYX_DIFFICULTY = (.60, .148, .79, .20)
CALYX_ROUNDS = (.58, .70, .94, .87)
SELECTED_ROUND_VALUE = (.79, .75, .89, .84)
CALYX_COST = (.61, .87, .79, .97)
DIFFICULTIES = ('i', 'ii', 'iii', 'iv', 'v', 'vi')

# Exact families from the pinned drop index, checked against assets/dungeons.json.
# For golden Calyxes the screen must supply a location. Crimson locations here
# are bound to the family by the reference as well as by the visible source row.
CALYX_FAMILIES = (
    (('漫游指南',), 'calyx_golden', '回忆之蕾', None),
    (('提纯以太', '凝缩以太', '稀薄以太'), 'calyx_golden', '以太之蕾', None),
    (('《绒绒号》典藏版合集', '《绒绒号》连载纪念刊', '《绒绒号》手绘分镜稿'),
     'calyx_crimson', '欢愉之蕾', '「世界尽头」酒馆'),
    (('法吉娜之心', '法吉娜之酒', '法吉娜之泪'), 'calyx_crimson', '虚无之蕾', '「辉痕圣林」神悟树庭'),
    ((GALAXY_SANDBOX,), 'calyx_crimson', '智识之蕾', '海原电视塔'),
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
    repeated_locations: tuple[str, ...]
    held: int | None = field(default=None, compare=False)


@dataclass(frozen=True)
class CalyxRewardPreview:
    category: str
    target: str
    difficulty: int
    selected_rounds: int
    shown_total_stamina: int


@dataclass(frozen=True)
class BuildTargetSelection:
    material: str
    location: str
    count: int

    def __post_init__(self):
        if type(self.material) is not str or self.material not in CALYX_BY_MATERIAL:
            raise ValueError('请指定当前支持的完整培养材料名。')
        if (type(self.location) is not str or not 2 <= len(self.location) <= 64
                or self.location != self.location.strip() or any(c in self.location for c in '\r\n')):
            raise ValueError('请指定获得途径中的完整副本地点。')
        if type(self.count) is not int or not 1 <= self.count <= 6:
            raise ValueError('培养草稿需明确指定 1～6 次挑战。')


def _inside(token, region):
    x1, y1, x2, y2 = token.box
    return region[0] <= x1 < x2 <= region[2] and region[1] <= y1 < y2 <= region[3]


def _material_held(scene, title, heading, confidence):
    def text(token):
        return re.sub(r'\s+', '', unicode_normalize('NFKC', token.text))

    fields = [token for token in scene.tokens if _inside(token, HELD_AREA)
              and token.box[0] < title.box[0] and token.box[1] > title.box[3]]
    labels = [token for token in fields if text(token).startswith('当前持有')]
    if (len(labels) != 1 or labels[0].score < confidence
            or _has_split_label(scene, ('当前持有',), HELD_AREA, exact=False)):
        return None
    label = labels[0]
    match = re.fullmatch(rf'当前持有:?({HELD_COUNT})?', text(label))
    if match is None or label.box[2] >= heading.box[0]:
        return None
    numbers = [token for token in fields if token is not label
               and 0 <= token.box[0] - label.box[2] <= .024
               and abs(token.center[1] - label.center[1]) <= .014
               and re.match(r'[0-9oO]', text(token))]
    if match[1] is not None:
        return None if numbers else int(match[1].replace(',', ''))
    if len(numbers) == 1 and numbers[0].score >= confidence and re.fullmatch(HELD_COUNT, text(numbers[0])):
        return int(text(numbers[0]).replace(',', ''))
    return None


def _calyx_preview(reader, scene, page):
    if scene.has(('挑战成功', '挑战失败'), exact=True):
        return None, None
    if not (page.has('可能遭遇', (.59, .20, .78, .26), exact=True)
            and page.has('可能获取', (.59, .54, .78, .63), exact=True)
            and page.has('挑战', (.78, .87, .98, .97), exact=True)):
        return None, None
    fields = trusted(scene, 0.)
    headers = [t for t in fields.tokens if t.within(CALYX_TITLE) and '拟造花萼' in normalize(t.text)]
    levels = [t for t in fields.tokens if t.within(CALYX_DIFFICULTY) and normalize(t.text).startswith('难度')]
    if len(headers) != 1 or len(levels) != 1 or headers[0] not in page.tokens or levels[0] not in page.tokens:
        return None, None
    header = headers[0]
    difficulty = normalize(unicode_normalize('NFKC', levels[0].text)).removeprefix('难度')
    if difficulty not in DIFFICULTIES:
        return None, None
    titles = {normalize(dungeon.name + BY_KEY[dungeon.category].label): (dungeon.category, dungeon.name)
              for dungeon in reader.catalogue if dungeon.category in ('calyx_golden', 'calyx_crimson')}
    calyx = titles.get(normalize(header.text))
    if calyx is None:
        return None, None
    selectors = [t for t in fields.tokens if t.within(CALYX_ROUNDS)
                 and normalize(t.text).startswith(('挑战次数', '挑战轮数'))]
    costs = [t for t in fields.tokens if t.within(CALYX_COST) and normalize(t.text).startswith(('x', '×'))]
    if (len(selectors) != 1 or selectors[0] not in page.tokens or len(costs) != 1
            or not re.fullmatch(r'[x×][0-9]{1,3}', normalize(costs[0].text))
            or _has_split_label(fields, ('挑战次数', '挑战轮数'), CALYX_ROUNDS, exact=False)):
        return None, None
    selector = selectors[0]
    if re.search(r'[0-9]$', normalize(selector.text)) and any(
            t is not selector and t.within(SELECTED_ROUND_VALUE) and re.fullmatch(r'[0-9]{1,2}', t.text.strip())
            and abs(t.center[1] - selector.center[1]) < .04 and t.center[0] > selector.center[0]
            for t in fields.tokens):
        return None, None
    rounds = DailyWorkflow._round_count(page)
    # The cost includes the x glyph. Confirm its reading against the
    # independent round control and the catalogue's per-round cost.
    cost = DailyWorkflow._cost(trusted(scene, max(.80, reader.collection_confidence)))
    if (rounds is None or rounds != DailyWorkflow._round_count(fields)
            or cost != rounds * BY_KEY[calyx[0]].cost or cost != DailyWorkflow._cost(fields)):
        return None, None
    return CalyxRewardPreview(*calyx, DIFFICULTIES.index(difficulty) + 1, rounds, cost), header


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
    seen, repeated = set(), set()
    unreadable = 0
    locked = 0
    for token in rows:
        match = CALYX_SOURCE.fullmatch(token.text.strip())
        if not match:
            unreadable += 1
            continue
        location = match[1].strip()
        if location in seen:
            repeated.add(location)
        seen.add(location)
        overlaps = any(other is not token and min(other.box[3], token.box[3]) > max(other.box[1], token.box[1])
                       for other in rows)
        if token not in page.tokens or not _inside(token, SOURCE_BODY) or overlaps:
            unreadable += 1
            continue
        row_area = (SOURCE_BODY[0], token.box[1], MODAL_AREA[2], token.box[3])
        if (scene.has(LOCK_MARKERS, row_area, exact=True)
                or _has_split_label(fragments, LOCK_MARKERS, row_area)):
            locked += 1
            continue
        locations.append(location)
    return tuple(dict.fromkeys(locations)), unreadable, locked, tuple(sorted(repeated))


def _title_candidate(token):
    return (token.text.strip() in CALYX_BY_MATERIAL
            or token.score >= FRAGMENT_CONFIDENCE and re.search(r'[\u3400-\u9fff]', token.text))


def _classify(reader, scene, *, read_quantities=False):
    captured = trusted(scene, reader.collection_confidence)
    page = trusted(captured, reader.confidence)
    if read_quantities:
        recipe, anchor = synthesis_preview(reader, scene, page)
        if recipe is not None:
            return recipe, anchor
    if guide_blocked(scene, modal=DETAIL_BLOCKERS):
        return None, None
    entry = guide_entry(scene, page)
    if entry is None:
        if not read_quantities:
            return None, None
        if page.has('角色培养', ROLE, exact=True):
            if any(_catalogue_row_areas(captured, reader.catalogue)):
                return None, None
            target, anchor, _ = target_panel(scene, page, entry, read_materials=True)
            return target, anchor
        result, anchor = result_shortfall(scene, page)
        return (result, anchor) if result is not None else _calyx_preview(reader, scene, page)
    catalogue_rows = tuple(_catalogue_row_areas(captured, reader.catalogue))
    headings = [token for token in captured.tokens if token.within(MODAL_AREA)
                and normalize(token.text) == SOURCE_LABEL]
    title_region = [token for token in captured.tokens if token.within(MATERIAL_TITLE)]
    if not headings and not any(token.text.strip() in CALYX_BY_MATERIAL for token in title_region):
        if catalogue_rows:
            return None, None
        if read_quantities and page.has('角色培养', ROLE, exact=True):
            target, anchor, conflict = target_panel(scene, page, entry, read_materials=True)
            if target is not None or conflict:
                return target, anchor
        kind, panel_entry = reader._classify(scene)
        if kind == 'panel':
            return kind, panel_entry
        return None, None
    titles = [token for token in title_region if _title_candidate(token)]
    if len(titles) != 1 or len(headings) != 1:
        return None, None
    title, heading = titles[0], headings[0]
    if title.text.strip() not in CALYX_BY_MATERIAL or title not in page.tokens or heading not in page.tokens:
        return None, None
    # A separate directory background only vetoes the cultivation context.
    if any(heading.within(area) for area in catalogue_rows):
        return None, None
    fragments = trusted(scene, 0.)
    if _has_split_label(fragments, (SOURCE_LABEL,), MODAL_AREA):
        return None, None
    held = _material_held(fragments, title, heading, reader.confidence) if read_quantities else None
    if held is not None and any(token is not title and token.within(OBSERVATION_TITLE) and _title_candidate(token)
                                for token in captured.tokens):
        held = None
    if _inside(title, MATERIAL_TITLE) and _inside(heading, SOURCE_BODY):
        locations, unreadable, locked, repeated = _calyx_locations(scene, page, fragments, heading)
    elif held is not None and _inside(title, OBSERVATION_TITLE) and _inside(heading, OBSERVATION_SOURCE):
        # The longer item card still supplies inventory. Routes require the
        # independently calibrated source layout.
        locations, unreadable, locked, repeated = (), 0, 0, ()
    else:
        return None, None
    target_titles = [token for token in scene.tokens if token.within(SECTIONS)
                     and normalize(token.text) == SHORTFALL]
    target_visible = (len(target_titles) == 1 and target_titles[0] in page.tokens
                      and target_titles[0].box[3] <= title.box[1] and not catalogue_rows)
    return MaterialDetail(title.text.strip(), locations, unreadable, locked, target_visible, repeated, held), entry


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


def _merge_preview(first, second):
    if isinstance(second, MaterialDetail) and first.held != second.held:
        return replace(second, held=None)
    if isinstance(second, TargetPanel):
        def unique_names(panel):
            counts = Counter(name for row in panel.shortfall_rows for name in row.materials if name)
            return {name for name, count in counts.items() if count == 1}

        unique = unique_names(first) & unique_names(second)
        rows = tuple(replace(new, materials=tuple(
            current if previous == current and current in unique else None
            for previous, current in zip(old.materials, new.materials)
        )) for old, new in zip(first.shortfall_rows, second.shortfall_rows))
        return replace(second, shortfall_rows=rows)
    return second


def run_preview(ctx, *, selection=None):
    operation = 'build_target_preview' if selection is None else 'build_target_plan'
    if ctx.report.operation != operation:
        raise AutomationError('材料预览需要独立只读入口。')
    reader = BuildTargetRead(ctx)
    limit = ctx.settings.stamina_limit
    preview = dict(state='unverified', material=None, held=None, shortfall=None, craftable=None, units_per_challenge=None,
                   count=None, configured_limit=limit, effective_limit=None, target_section_visible=False,
                   source_locations=[], candidates=[])
    ctx.report.build_target = dict(reader.record, preview=preview)
    observe_quantities = selection is None
    if observe_quantities:
        preview['suggestion_reason'] = 'no_current_evidence'
    scene, observation = reader._observe(
        classify=lambda current: _classify(reader, current, read_quantities=observe_quantities),
        merge=_merge_preview if observe_quantities else None, require_adjacent=True,
    )
    sources = _catalogue_sources(observation, reader.catalogue) if isinstance(observation, MaterialDetail) else []
    candidates = []
    if isinstance(observation, MaterialDetail) and observation.target_section_visible:
        for source in sources:
            rule = BY_KEY[source.category]
            maximum = count_limit(rule, limit)
            blocker = None
            if observation.unreadable_calyx_rows:
                blocker = 'incomplete_source'
            elif source.location in observation.repeated_locations:
                blocker = 'repeated_location'
            candidates.append(dict(category=source.category, target=source.name, location=source.location,
                                   stamina_cost=rule.cost, max_challenges_by_config=maximum,
                                   max_draft_challenges_by_config=min(rule.batch, maximum),
                                   manual_draft_blocker=blocker))
    from .build_target_draft import DraftSource
    source = DraftSource(reader, scene)
    preview['evidence'] = source.path.name
    preview['evidence_sha256'] = source.digest
    unverified_preview = preview.copy()
    if selection is not None and _classify(reader, scene)[0] != observation:
        raise AutomationError('保存画面后培养材料或来源发生变化，未生成体力草稿。')
    reader._verify_observation(scene)
    if observe_quantities:
        preview['suggestion_reason'] = 'material_shortfall_unbound'
    if isinstance(observation, CalyxRewardPreview):
        rule = BY_KEY[observation.category]
        preview.update(state='calyx_reward_preview', calyx_reward_preview=dict(
            **asdict(observation), rewards='possible_items', stamina_per_challenge=rule.cost,
            selected_stamina_within_config=observation.shown_total_stamina <= limit,
            max_draft_challenges_by_config=min(rule.batch, count_limit(rule, limit))))
        preview['suggestion_reason'] = 'possible_rewards_only'
        detail = f'已核对{observation.target}难度 {observation.difficulty} 的奖励预览与挑战费用。'
    elif isinstance(observation, ResultShortfall):
        preview.update(state='calyx_result_shortfall', post_battle_shortfall=dict(
            observed_needed=list(observation.observed_needed), completed_rounds=observation.completed_rounds,
            repeat_stamina=observation.repeat_stamina))
        preview['suggestion_reason'] = 'settled_batch_only'
        detail = '已核对结算中的培养剩余提示和实际完成波次。'
    elif isinstance(observation, SynthesisPreview):
        preview.update(state='synthesis_preview', synthesis_preview=asdict(observation), suggestion_reason='recipe_only')
        detail = '已核对材料配方的持有量、所选合成量和滑杆上限。'
    elif isinstance(observation, TargetPanel):
        ctx.report.build_target['page_verified'] = True
        shortfall_rows = []
        for row in observation.shortfall_rows:
            fields = dict(observed_needed=list(row.observed_needed), shown_stamina=row.shown_stamina)
            identified = [dict(material=material, amount=amount, slot=slot)
                          for material, amount, slot in zip(row.materials, row.observed_needed, row.slots) if material]
            if identified:
                fields['identified_materials'] = identified
            shortfall_rows.append(fields)
        preview.update(state=observation.state, target_section_visible=True, shortfall_rows=shortfall_rows)
        detail = {
            'target_level_trace_complete': '培养目标页显示已完成等级、行迹的提升。',
            'target_materials_sufficient': '培养目标页显示已获得足够的等级和行迹材料。',
            'target_resources_needed': '已观察培养目标的缺口区，材料与单轮产量需分别核实。',
        }[observation.state]
        if observation.state != 'target_resources_needed':
            preview['suggestion_reason'] = 'level_trace_requirements_met'
        elif (len(shortfall_rows) == 1 and len(shortfall_rows[0]['observed_needed']) == 1
              and 'identified_materials' in shortfall_rows[0]):
            item, = shortfall_rows[0]['identified_materials']
            preview.update(material=item['material'], shortfall=item['amount'])
            if item['amount'] == 0:
                preview['suggestion_reason'] = 'material_shortfall_zero'
                detail = f'已核对「{item["material"]}」当前缺口为 0。'
            else:
                preview['suggestion_reason'] = 'unverified_per_round_minimum'
                detail = f'已核对「{item["material"]}」缺口 {item["amount"]}，单轮保底仍待核实。'
    elif observation == 'panel':
        ctx.report.build_target['page_verified'] = True
        preview.update(state='panel_observed', target_section_visible=True)
        detail = '已保存培养目标页。打开一项材料详情并显示获得途径可核对目录候选。'
    else:
        preview.update(state='catalogue_candidates' if candidates else 'material_observed',
                       material=observation.material, held=observation.held, candidates=candidates,
                       target_section_visible=observation.target_section_visible,
                       source_locations=[source.location for source in sources],
                       lock_marker_rows=observation.lock_marker_rows,
                       unmatched_calyx_rows=observation.unreadable_calyx_rows + len(observation.locations) - len(sources))
        detail = f'已观察材料「{observation.material}」及 {len(candidates)} 项目录候选，缺口和单轮产量待核实。'
    if selection is None:
        ctx.build_target_preview_source = source, unverified_preview
        return TaskResult(operation, 'partial', detail)

    if not isinstance(observation, MaterialDetail) or observation.material != selection.material:
        raise AutomationError('当前材料详情或指定来源未完整核实，未生成体力草稿。')
    candidate = next((row for row in candidates if row['location'] == selection.location), None)
    if candidate is None:
        raise AutomationError('指定地点缺少已核实、可用的培养来源，未生成体力草稿。')
    if candidate['manual_draft_blocker']:
        raise AutomationError('当前材料详情或指定来源未完整核实，未生成体力草稿。')
    maximum = candidate['max_draft_challenges_by_config']
    if selection.count > maximum:
        raise AutomationError(f'指定次数超过当前配置的开拓力上限，本份草稿最多 {maximum} 次。')
    cost = candidate['stamina_cost'] * selection.count
    row = {key: candidate[key] for key in ('category', 'target', 'location')}
    item, = items([dict(row, count=selection.count)])
    from .build_target_draft import BuildTargetDraft
    draft = BuildTargetDraft(source, [item.to_dict()], selection.material, cost)
    ctx.build_target_draft = draft
    ctx.report.build_target['draft'] = draft.metadata
    return TaskResult(operation, 'partial', '已核实指定材料和来源，体力草稿待发布。')
