"""Build a bounded navigation diagnostic and project its anonymous receipts."""

from hashlib import sha256
import json
from pathlib import Path
import re

from .config import ROOT
from .storage import hold_read_sources
from .task_workflow import (ACHIEVEMENT_OVERVIEW_PAGE, ACTIVITY_WORKFLOW_PAGES, BATTLEPASS_WORKFLOW_PAGES, MAX_BYTES,
                            MESSAGE_WORKFLOW_PAGE, PAGE_TASK, REDEMPTION_FORM_PAGE, SCREEN_CHECK_EXTRA_PAGES,
                            SCREEN_CHECK_PAGES, VISA_CHARACTERS_PAGE, VISA_COLLECTION_PAGE, WORKFLOW_PAGES,
                            WORLD_WORKFLOW_PAGE, Recipe, WorkflowError, _pairs, compile_recipe)
from .task_workflow_run import _bytes as _workflow_bytes
from .workflow_navigation import _GUIDE_PAGES, _MAX_ACTIONS, _REDEMPTION_MORE, _VISA_MORE_MENU


NAME = '核对所选页面'
RECOVERY_NAME = '恢复后核对未执行页面'
MAX_SOURCE_BYTES = 64 * 1024 * 1024
_TERMINAL = ('success', 'partial', 'failed', 'stopped')
_STEP_SETUP_FIELDS = frozenset(('sequence', 'step', 'type', 'task', 'trail', 'status', 'started_at'))
_SHA256 = re.compile(r'[a-f0-9]{64}')
_LOCAL_DRIVE = re.compile(r'[A-Za-z]:')
_NAVIGATION_PAGES = frozenset((*WORKFLOW_PAGES, 'world', 'activity_list'))
_ACTIONS = frozenset(('return_to_hub', 'open_journey_events', *('open_' + page for page in WORKFLOW_PAGES)))
_EXTRA_ACTIONS = {
    VISA_COLLECTION_PAGE: ('open_more', 'open_visa_collection'),
    VISA_CHARACTERS_PAGE: ('open_phone', 'open_more', 'open_visa_collection', 'open_visa_characters'),
    ACHIEVEMENT_OVERVIEW_PAGE: ('open_achievements',),
    REDEMPTION_FORM_PAGE: ('open_redemption_more', 'open_redemption_form'),
    WORLD_WORKFLOW_PAGE: ('return_to_hub',),
    **{page: ('open_battlepass', 'open_' + page) for page in BATTLEPASS_WORKFLOW_PAGES},
}


def _document(targets):
    if (not isinstance(targets, (list, tuple)) or not 1 <= len(targets) <= len(SCREEN_CHECK_PAGES)
            or any(type(target) is not str or target not in SCREEN_CHECK_PAGES for target in targets)
            or len(set(targets)) != len(targets)):
        raise WorkflowError('请选择至少一个支持的日常页面，每页只选一次。')
    if MESSAGE_WORKFLOW_PAGE in targets and len(targets) != 1:
        raise WorkflowError('短信通知须单独核对，请从已有未读角标的大世界或已打开的通知面板开始。')
    if len(targets) != 1 and any(target in SCREEN_CHECK_EXTRA_PAGES for target in targets):
        raise WorkflowError('大世界、漫游签证、成就总览、兑换码表单和指定无名勋礼页签须单独核对。')
    activity = tuple(page for page in ACTIVITY_WORKFLOW_PAGES if page in targets)
    if activity and tuple(targets[-len(activity):]) != activity:
        raise WorkflowError('活动页面须放在末尾，并按巡星之礼、奖励指南的顺序排列。')
    return dict(version=1, name=NAME, steps=[
        dict(id='page_' + target, type='task', task=PAGE_TASK, params=dict(target=target), on_failure='stop')
        for target in targets
    ])


def build_recipe(targets, *, base_dir=None) -> Recipe:
    """Preview explicit targets in order. Execution still belongs to TaskWorkflowRunner."""
    return compile_recipe(_document(targets), base_dir=base_dir)


def _recovery_document(targets):
    document = _document(targets)
    if any(target in (*SCREEN_CHECK_EXTRA_PAGES, MESSAGE_WORKFLOW_PAGE) for target in targets):
        raise WorkflowError('独立核对页不能加入批量续查。')
    world = _document((WORLD_WORKFLOW_PAGE,))['steps'][0]
    world['params']['observe_only'] = True
    return dict(document, name=RECOVERY_NAME, steps=[world, *document['steps']])


def _expected_document(recipe):
    if isinstance(recipe, Recipe) and not recipe.path:
        try:
            targets = tuple(step['params']['target'] for step in recipe.steps)
            if recipe.document['name'] == RECOVERY_NAME and targets[:1] == (WORLD_WORKFLOW_PAGE,):
                expected = _recovery_document(targets[1:])
            else:
                expected = _document(targets)
            if recipe.steps == expected['steps'] and _workflow_bytes(recipe.document) == _workflow_bytes(expected):
                return expected
        except (KeyError, TypeError, ValueError):
            pass
    raise WorkflowError('请使用本次核对所选页面的预览。')


def _absolute(value):
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError('invalid report path')
    path = Path(value)
    if not path.is_absolute() or not path.name or '..' in path.parts or (
            path.drive and not _LOCAL_DRIVE.fullmatch(path.drive)):
        raise ValueError('invalid report path')
    return path


def _action_counts(actions, target):
    if not isinstance(actions, list) or len(actions) > _MAX_ACTIONS:
        raise ValueError('invalid navigation actions')
    allowed_actions, allowed_pages = _ACTIONS, _NAVIGATION_PAGES
    if target in _EXTRA_ACTIONS:
        allowed_actions = _EXTRA_ACTIONS[target]
        allowed_pages = allowed_pages.union(SCREEN_CHECK_EXTRA_PAGES, (_REDEMPTION_MORE, _VISA_MORE_MENU))
    previous = None
    sent = unconfirmed = 0
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError('invalid navigation action')
        kind, source = action.get('action'), action.get('source_page')
        state, arrived = action.get('input_status'), action.get('destination_status')
        page, expected = action.get('destination_page'), action.get('expected_pages')
        if (not isinstance(kind, str) or kind not in allowed_actions or not isinstance(source, str)
                or source not in allowed_pages or (previous is not None and source != previous)
                or not isinstance(expected, list) or not expected
                or any(not isinstance(page, str) or page not in allowed_pages for page in expected)
                or state not in ('sent', 'unconfirmed') or arrived not in ('verified', 'unknown')
                or (arrived == 'verified' and (state != 'sent' or page not in expected))
                or (arrived == 'unknown' and (page is not None or index + 1 != len(actions)))):
            raise ValueError('conflicting navigation action')
        sent += state == 'sent'
        unconfirmed += state == 'unconfirmed'
        previous = page
    return sent, unconfirmed, previous


def _project_child(row, step, parent_dir, read_source):
    source = step.get('source')
    if not isinstance(source, dict):
        return
    try:
        path = _absolute(source.get('path'))
        digest = source.get('sha256')
        if (path.name != 'report.json' or path.parent == parent_dir or path.parent.parent != parent_dir.parent
                or not isinstance(digest, str) or not _SHA256.fullmatch(digest)):
            return
        raw = read_source(path)
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SOURCE_BYTES or sha256(raw).hexdigest() != digest:
            return
        child = json.loads(raw, object_pairs_hook=_pairs)
        if (not isinstance(child, dict) or child.get('operation') != PAGE_TASK or child.get('report_saved') is not True
                or child.get('status') not in _TERMINAL or _absolute(child.get('run_dir')) != path.parent):
            return
        navigation = child.get('workflow_navigation')
        target = row['target']
        if (not isinstance(navigation, dict) or navigation.get('target') != target
                or type(navigation.get('page_verified')) is not bool):
            return
        actions = navigation.get('actions')
        sent, unconfirmed, last = _action_counts(actions, target)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        return
    row.update(actions_sent=sent, actions_unconfirmed=unconfirmed)
    facts = step.get('facts')
    accepted = _GUIDE_PAGES if target == 'guide' else (target,)
    if (step.get('status') == child['status'] == 'success' and step.get('account_verified') is True
            and isinstance(facts, dict) and facts.get('status') == 'success' and facts.get('page_verified') is True
            and navigation['page_verified'] is True and (not actions or last in accepted)):
        row['status'] = 'verified'
        if target == 'daily_training':
            from .daily_training_observe import training_observation_receipt

            observation = training_observation_receipt(navigation)
            if observation is not None and step.get('training_observation') == observation:
                row['training_observation'] = observation
        if target == VISA_CHARACTERS_PAGE:
            from .support_gift_observe import gift_receipt

            gift = gift_receipt(navigation)
            if gift is not None and step.get('support_gift_observation') == gift:
                row['support_gift_observation'] = gift


def project_result(recipe, report, *, read_source):
    """Project a final Runner receipt using caller-supplied original child report bytes.

    The reader receives only a lexical sibling run's report.json path. The caller
    controls access to local, bounded evidence. This function never opens files.
    """
    expected = _expected_document(recipe)
    nodes = expected['steps']
    rows = [dict(target=node['params']['target'], status='unknown', actions_sent=None, actions_unconfirmed=None)
            for node in nodes]
    result = dict(status='unknown', pages=rows)
    if (not isinstance(report, dict) or report.get('operation') != 'task_workflow' or report.get('report_saved') is not True
            or report.get('status') not in _TERMINAL or not isinstance(report.get('finished_at'), str)
            or not report['finished_at']):
        return result
    workflow = report.get('workflow')
    if (not isinstance(workflow, dict) or workflow.get('name') != expected['name'] or workflow.get('selected_path') != []
            or workflow.get('definition_sha256') != sha256(_workflow_bytes(expected)).hexdigest()):
        return result
    entries = workflow.get('steps')
    if (not isinstance(entries, list) or len(entries) > len(nodes)
            or report['status'] == 'success' and len(entries) != len(nodes)):
        return result
    for index, (entry, node) in enumerate(zip(entries, nodes), 1):
        if (not isinstance(entry, dict) or type(entry.get('sequence')) is not int or entry['sequence'] != index
                or (entry.get('step'), entry.get('type'), entry.get('task'), entry.get('trail'))
                != (node['id'], 'task', PAGE_TASK, [])):
            return result
        status = entry.get('status')
        last = index == len(entries)
        # Intent setup appends the row before writing it. A later successful
        # final save can retain this row even though no child was started.
        if (last and status == 'running' and report['status'] in ('partial', 'stopped')
                and entry.keys() == _STEP_SETUP_FIELDS
                and isinstance(entry['started_at'], str) and entry['started_at']):
            continue
        if status not in _TERMINAL or (not last and status != 'success'):
            return result
    try:
        parent_dir = _absolute(report.get('run_dir'))
    except (TypeError, ValueError):
        return result
    for row, step in zip(rows, entries):
        _project_child(row, step, parent_dir, read_source)
    for row in rows[len(entries):]:
        row['status'] = 'not_run'
    result['status'] = report['status']
    if result['status'] == 'success' and any(row['status'] != 'verified' for row in rows):
        result['status'] = 'partial'
    return result


def _read_local(path, limit):
    from .workflow_bundle import _path as local_file

    source = local_file(path)
    with hold_read_sources((source,)):
        if local_file(path) != source:
            raise OSError('报告的本地来源已变化。')
        with source.open('rb') as stream:
            raw = stream.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise ValueError('报告文件大小无效。')
    return raw


def saved_result(recipe, report, *, runs_root=None):
    """Project the finished run from bounded, ordinary local child reports."""
    root = Path(runs_root if runs_root is not None else ROOT / 'runs').absolute()

    def read_source(path):
        if path.parent.parent != root:
            raise OSError('子报告不在本次运行根目录。')
        return _read_local(path, MAX_SOURCE_BYTES)

    return project_result(recipe, report, read_source=read_source)


def _require_original_journal(path, entries):
    events = [json.loads(line, object_pairs_hook=_pairs) for line in _read_local(path, MAX_BYTES).splitlines()]
    expected = []
    for entry in entries:
        intent = {field: entry[field] for field in _STEP_SETUP_FIELDS}
        intent['status'] = 'running'
        expected.extend((dict(event='intent', **intent), dict(event='result', **entry)))
    if events != expected:
        raise WorkflowError('原报告与执行账本不一致。')


def recovery_recipe(path, *, runs_root=None):
    """Read an original saved page-check run and compile only its unstarted suffix."""
    root = Path(runs_root if runs_root is not None else ROOT / 'runs').absolute()
    path = (Path.cwd() / path)
    if path.name != 'report.json' or path.parent.parent != root or '..' in path.parts:
        raise WorkflowError('请指定 AutoHSR 本地运行目录中的页面核对 report.json。')
    try:
        report = json.loads(_read_local(path, MAX_SOURCE_BYTES), object_pairs_hook=_pairs)
        if not isinstance(report, dict) or _absolute(report.get('run_dir')) != path.parent:
            raise ValueError('report directory mismatch')
        document = json.loads(_read_local(path.with_name('workflow.json'), MAX_BYTES), object_pairs_hook=_pairs)
        original = compile_recipe(document)
        receipt = saved_result(original, report, runs_root=root)
        if receipt['status'] == 'partial':
            _require_original_journal(path.with_name('steps.jsonl'), report['workflow']['steps'])
    except (KeyError, OSError, RuntimeError, TypeError, ValueError):
        raise WorkflowError('原页面核对流程或报告无法核实。') from None
    rows = receipt['pages']
    workflow = report.get('workflow')
    identity = workflow.get('identity') if isinstance(workflow, dict) else None
    pending = [row['target'] for row in rows if row['status'] == 'not_run']
    observed = [row['status'] for row in rows if row['status'] != 'not_run']
    if (receipt['status'] != 'partial' or not pending or not observed or observed[-1] != 'unknown'
            or any(status != 'verified' for status in observed[:-1])
            or (rows[0]['target'] == WORLD_WORKFLOW_PAGE and rows[0]['status'] != 'verified')
            or report['workflow']['steps'][-1]['status'] not in ('failed', 'partial')
            or not isinstance(identity, dict) or identity.get('account_changed') is not False):
        raise WorkflowError('原批次没有可安全续查的未执行页面，请核对原报告。')
    return compile_recipe(_recovery_document(pending))
