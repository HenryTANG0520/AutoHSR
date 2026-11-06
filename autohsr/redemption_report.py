"""Allowlisted redemption feedback for parent reports and notifications."""
import re

from .redemption_codes import MAX_ROWS


RESULTS = ('redeemed', 'expired', 'already_used', 'invalid')
COUNTS = (*RESULTS, 'reused')


def _batch_summary(batch, *, reused_report=False):
    if (type(batch) is not dict or type(batch.get('schema')) is not int or batch['schema'] != 1
            or batch.get('status') not in ('completed', 'partial', 'stopped')):
        return {'state': 'unverified'}
    codes, rows = batch.get('codes'), batch.get('results')
    if type(codes) is not list or type(rows) is not list or not 0 <= len(rows) <= len(codes) <= MAX_ROWS:
        return {'state': 'unverified'}

    counts = dict.fromkeys(COUNTS, 0)
    entries = set()
    for row in rows:
        if type(row) is not dict or row.get('status') not in RESULTS or type(row.get('reused')) is not bool:
            return {'state': 'unverified'}
        if not row['reused']:
            entry = row.get('entry_id')
            if type(entry) is not str or re.fullmatch('[0-9a-f]{32}', entry) is None or entry in entries:
                return {'state': 'unverified'}
            entries.add(entry)
        counts['reused' if row['reused'] else row['status']] += 1
    submitted = sum(counts[key] for key in RESULTS)
    if any(type(batch.get(key)) is not int or batch[key] != value
           for key, value in (('submitted', submitted), ('redeemed', counts['redeemed']), ('reused', counts['reused']))):
        return {'state': 'unverified'}

    if batch['status'] == 'completed':
        if len(rows) != len(codes) or 'pending_entry_id' in batch:
            return {'state': 'unverified'}
        state = 'completed' if codes else 'empty'
    else:
        state = 'needs_review'
    return dict(state=state, reused_report=reused_report, **counts)


def _saved_summary(summary):
    if type(summary) is dict and type(summary.get('reused_report')) is bool:
        state = summary.get('state')
        counts = {key: summary.get(key) for key in COUNTS}
        if (state in ('completed', 'empty', 'needs_review')
                and all(type(value) is int and 0 <= value <= MAX_ROWS for value in counts.values())):
            total = sum(counts.values())
            if total <= MAX_ROWS and (state == 'needs_review' or (state == 'empty') == (total == 0)):
                return dict(state=state, reused_report=summary['reused_report'], **counts)
    return {'state': 'unverified'}


def report_summary(report):
    """Return only outcome counts and source role, or None for other tasks."""
    operation = report.get('operation')
    if operation == 'task_workflow':
        workflow = report.get('workflow')
        if type(workflow) is dict and 'redemption_summary' in workflow:
            return _saved_summary(workflow['redemption_summary'])
    batch = report.get('redemption')
    if batch:
        weekly = report.get('weekly_plan')
        reused_report = (operation == 'plan' and type(weekly) is dict and weekly.get('daily_reused') is True
                         and report.get('budget_scope') == 'original_daily_run')
        return _batch_summary(batch, reused_report=reused_report)
    rows = report.get('results')
    if operation == 'redemption' or (type(rows) is list and any(
            type(row) is dict and row.get('task') == 'redemption' for row in rows)):
        return {'state': 'unverified'}
    return None
