"""Combine explicitly prepared cultivation drafts into one ordinary power plan."""
from contextlib import ExitStack
from hashlib import sha256
import json
from pathlib import Path
import re

from .build_target_draft import PLAN, _json_bytes, _link, _private_file
from .build_target_preview import MATERIAL_SOURCES
from .config import ROOT
from .models import AutomationError, normalize
from .power_plan import items
from .storage import hold_read_sources
from .task_workflow import MAX_BYTES, _pairs
from .workflow_bundle import _path as local_file


_HASH = re.compile(r'[a-f0-9]{64}')
_MAX_IMAGE_BYTES = 64 * 1024 * 1024


def _read(path, limit=MAX_BYTES):
    if local_file(path) != path:
        raise AutomationError('培养草稿来源已变化。')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise AutomationError('培养草稿来源大小无效。')
    return data


def _report(path):
    data = json.loads(_read(path), object_pairs_hook=_pairs)
    if not isinstance(data, dict):
        raise AutomationError('培养草稿回执格式无效。')
    return data


def _source(receipt, root, held):
    draft = receipt['build_target']['draft']
    preview = receipt['build_target']['preview']
    run_dir = Path(receipt['run_dir'])
    if (receipt.get('operation') != 'build_target_plan' or receipt.get('status') != 'success'
            or receipt.get('report_saved') is not True or run_dir.parent != root or '..' in run_dir.parts
            or draft.get('state') != 'prepared' or draft.get('mode') != 'dry_run'
            or draft.get('file') != PLAN or draft.get('count_source') != 'manual'):
        raise AutomationError('请选择本次培养命令成功输出的已发布草稿回执。')
    evidence = preview['evidence']
    if Path(evidence).name != evidence or Path(evidence).suffix.lower() != '.png':
        raise AutomationError('培养草稿缺少本次截图来源。')
    audit_path, plan_path, image_path = tuple(local_file(run_dir / name) for name in
                                             ('report.json', PLAN, evidence))
    held.enter_context(hold_read_sources((audit_path, plan_path, image_path)))
    audit = _report(audit_path)
    staged = {name: value for name, value in draft.items() if name != 'file'}
    staged['state'] = 'staged'
    if (audit.get('operation') != 'build_target_plan' or audit.get('status') != 'partial'
            or audit.get('report_saved') is not True or audit.get('run_dir') != receipt['run_dir']
            or audit['build_target'].get('draft') != staged or audit['build_target'].get('preview') != preview):
        raise AutomationError('培养草稿与其原始审计报告不一致。')
    raw_plan = _read(plan_path)
    if (sha256(raw_plan).hexdigest() != draft.get('sha256')
            or not isinstance(preview.get('evidence_sha256'), str)
            or not _HASH.fullmatch(preview['evidence_sha256'])
            or sha256(_read(image_path, _MAX_IMAGE_BYTES)).hexdigest() != preview['evidence_sha256']):
        raise AutomationError('培养草稿或截图已变化。')
    rows = json.loads(raw_plan, object_pairs_hook=_pairs)
    if rows != draft.get('items'):
        raise AutomationError('培养草稿条目与回执不一致。')
    item, = items(rows)
    material = draft.get('material')
    if (not isinstance(material, str) or material not in MATERIAL_SOURCES
            or (item.category, item.target) != MATERIAL_SOURCES[material][:2] or item.count > item.dungeon.batch
            or type(draft.get('stamina_required')) is not int
            or draft['stamina_required'] != item.count * item.dungeon.cost
            or preview.get('material') != material):
        raise AutomationError('培养草稿缺少同一材料的有效单项预算。')
    return item, material


def compose(receipts, *, stamina_limit, destination=None, runs_root=None):
    if (type(stamina_limit) is not int or not 10 <= stamina_limit <= 240 or stamina_limit % 10):
        raise AutomationError('本次开拓力上限应为 10～240 之间的 10 的倍数。')
    if not 2 <= len(receipts) <= 24:
        raise AutomationError('请选择 2～24 份已发布的培养草稿回执。')
    root = Path(runs_root if runs_root is not None else ROOT / 'runs').absolute()
    with ExitStack() as held:
        paths = tuple(local_file(path) for path in receipts)
        held.enter_context(hold_read_sources(paths))
        if len(set(paths)) != len(paths):
            raise AutomationError('同一份培养草稿回执只能选择一次。')
        try:
            selected = [_source(_report(path), root, held) for path in paths]
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise AutomationError('培养草稿回执或原始记录格式无效。') from error
        dungeons = [(item.category, normalize(item.target), normalize(item.location)) for item, _ in selected]
        if len(set(dungeons)) != len(dungeons):
            raise AutomationError('同一副本和地点出现多份草稿，请先明确该副本的总次数。')
        total = sum(item.count * item.dungeon.cost for item, _ in selected)
        if total > stamina_limit:
            raise AutomationError(f'合并预计使用 {total} 开拓力，超过本次上限 {stamina_limit}。')
        rows = [item.to_dict() for item, _ in selected]
        payload = _json_bytes(rows)
        result = dict(status='success', mode='preview', items=rows, materials=[material for _, material in selected],
                      stamina_limit=stamina_limit, stamina_required=total, stamina_remaining=stamina_limit - total,
                      game_accessed=False,
                      sha256=sha256(payload).hexdigest())
        if destination is not None:
            output = local_file(destination, new=True)
            if output.suffix.lower() != '.json':
                raise AutomationError('请为合并的体力计划指定新 JSON 文件。')
            with _private_file(output.parent, payload) as (staged, stream):
                _link(staged, output)
                stream.close()
            result.update(mode='prepared', output=str(output))
    return result


def run(args, raw_args, parser):
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    allowed = {'--compose-build-target', '--stamina', '--build-target-output'}
    if len(flags) != len(set(flags)) or set(flags) - allowed or args.stamina is None:
        parser.error('合并培养草稿须独立指定 --stamina，可另选 --build-target-output。')
    try:
        result = compose(args.compose_build_target, stamina_limit=args.stamina, destination=args.build_target_output)
    except (AutomationError, OSError, ValueError) as error:
        print(json.dumps(dict(status='failed', error=str(error)), ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
