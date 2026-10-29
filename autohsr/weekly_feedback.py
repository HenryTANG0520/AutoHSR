"""Read-only, account-free desktop descriptions of frozen Currency Wars goals."""
from __future__ import annotations


def pending_currency_week(root):
    """Offer an explicit continuation only after local source checks; never write."""
    from pathlib import Path
    if not (Path(root)/'currency-loop-current.json').exists():
        return None
    from .currency_wars_loop_store import LoopStore
    from .currency_wars_weekly import check_complete, check_sources, unfinished
    from .models import AutomationError
    try:
        store = LoopStore(root)
        data = store.load()
        if not data or not data.get('weekly_plan'):
            return None
        plan = data['weekly_plan']
        if not unfinished(store):
            if plan['state'] == 'complete':
                check_complete(store)
            return None
        check_sources(store)
        audit = plan['phase'] == 'done'
        caption = (f"原周常 · {plan['week']} · 货币战争 · 已完成 {data['completed']} 局／上限 {plan['maximum']} 局")
        if plan['daily'] is not None:
            caption += ' · 沿用原日常报告'
        return dict(resume=True, action='补存周常结果' if audit else '继续周常', caption=caption,
                    week=plan['week'], due_at=plan['due_at'], maximum=plan['maximum'], completed=data['completed'],
                    daily_reused=plan['daily'] is not None)
    except AutomationError as error:
        return dict(resume=False, caption='原周常待核对：'+str(error))
    except OSError:
        return dict(resume=False, caption='原周常证据文件缺失或不可读，未自动接续。')
    except (ValueError, TypeError, KeyError):
        return dict(resume=False, caption='原周常记录格式无效，未自动接续。')


def currency_weekly_caption(report):
    weekly = report.get('weekly_plan') or {}
    if weekly.get('mode') != 'currency_wars':
        return None
    state = weekly.get('status')
    if state in ('disabled', 'not_due', 'waiting'):
        return None
    verified = (report.get('status') == 'success' and report.get('report_saved') is True
                and weekly.get('score_rewards_verified') is True and state in ('complete', 'already_complete'))
    audit = (report.get('currency_wars') or {}).get('read_only_recovery') is True
    text = ('货币战争 · 原周常回执已核对' if verified and audit else
            '货币战争 · 积分及奖励已核实' if verified else
            '货币战争 · 原上限已用完' if state == 'exhausted' else
            '货币战争 · 原周目标已过期' if state == 'expired' else '货币战争 · 周常待核对')
    maximum, completed = weekly.get('maximum_runs', weekly.get('requested_runs')), weekly.get('completed_runs')
    if (type(maximum) is int and type(completed) is int and 1 <= maximum <= 10 and 0 <= completed <= maximum):
        text += f' · 开发对局 {completed} 局／上限 {maximum} 局'
    week = weekly.get('week')
    if isinstance(week, str):
        from datetime import date
        try:
            if date.fromisoformat(week).isoformat() == week:
                text = week+' 当周 · '+text
        except ValueError:
            pass
    return text
