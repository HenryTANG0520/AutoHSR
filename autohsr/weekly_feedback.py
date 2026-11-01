"""Read-only, account-free desktop descriptions of frozen Currency Wars goals."""
from __future__ import annotations


def _daily_preview(report):
    """Only task presentation fields; never expose the receipt's account or paths."""
    from .ux import reported_battle_metrics
    rows = {}
    for row in report.get('results', []):
        if not isinstance(row, dict) or not isinstance(row.get('task'), str):
            continue
        task = row['task']
        if task not in ('assignments', 'battle', 'daily', 'mail', 'battlepass'):
            continue
        rows[task] = dict(status=row.get('status') if isinstance(row.get('status'), str) else 'partial',
                          detail=row.get('detail') if isinstance(row.get('detail'), str) else '')
    if report.get('daily_verified') is True:
        rows['daily'] = dict(status='ok', detail='每日实训奖励已核实领取。')
    if 'battle' in rows:
        rows['battle']['metrics'] = reported_battle_metrics(report)
        from .power_plan_ui import result_text
        text=result_text(report,reused=True)
        if text:
            rows['battle'].update(status='本次结束' if (report.get('power_plan') or {}).get('run_status')=='complete' else '未完整结束',detail=text)
    return rows


def pending_currency_week(root):
    """Offer an explicit continuation only after local source checks; never write."""
    from pathlib import Path
    if not (Path(root)/'currency-loop-current.json').exists():
        return None
    from .currency_wars_loop_store import LoopStore
    from .currency_wars_weekly import check_complete, check_sources, read_ref, unfinished
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
        caption = (f"原周常 · {plan['week']} · 货币战争 · 已结束 {data['completed']} 局／上限 {plan['maximum']} 局")
        defeats=data.get('defeats',0)
        caption+=f" · 胜 {data['completed']-defeats}／负 {defeats}"
        if data.get('status')=='defeated':caption+=' · 上局失败已停止'
        if plan['daily'] is not None:
            caption += ' · 沿用原日常报告'
        daily_preview = _daily_preview(read_ref(store.root, plan['daily'])[1]) if plan['daily'] is not None else {}
        return dict(resume=True, action='补存周常结果' if audit else '继续周常', caption=caption,
                    week=plan['week'], due_at=plan['due_at'], maximum=plan['maximum'], completed=data['completed'],
                    daily_reused=plan['daily'] is not None, daily_preview=daily_preview)
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
            '货币战争 · 失败后已停止' if state == 'defeated' else
            '货币战争 · 原周目标已过期' if state == 'expired' else '货币战争 · 周常待核对')
    maximum, completed = weekly.get('maximum_runs', weekly.get('requested_runs')), weekly.get('completed_runs')
    if (type(maximum) is int and type(completed) is int and 1 <= maximum <= 10 and 0 <= completed <= maximum):
        text += f' · 开发对局 {completed} 局／上限 {maximum} 局'
        text += outcome_caption(weekly, completed)
    week = weekly.get('week')
    if isinstance(week, str):
        from datetime import date
        try:
            if date.fromisoformat(week).isoformat() == week:
                text = week+' 当周 · '+text
        except ValueError:
            pass
    return text


def outcome_caption(data, completed):
    victories,defeats=data.get('victories'),data.get('defeats')
    if (type(completed) is int and type(victories) is int and type(defeats) is int
            and min(completed,victories,defeats)>=0 and victories+defeats==completed):
        return f' · 胜 {victories}／负 {defeats}'
    return ''
