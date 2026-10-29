"""Optional weekly Echo prelude; the observed game allowance is authoritative."""
from datetime import datetime
from types import SimpleNamespace

from .models import AutomationError
from .power_plan import items
from .weekly_plan import CHINA,weekly_slot


def local_now():return datetime.now(CHINA)


def validate_settings(settings):
    from .config import SettingsError
    if type(settings.echo_of_war_enabled) is not bool:
        raise SettingsError('echo_of_war_enabled','历战周计划开关必须为布尔值。')
    if type(settings.echo_of_war_start_day) is not int or not 1<=settings.echo_of_war_start_day<=7:
        raise SettingsError('echo_of_war_start_day','历战开始星期应为1～7。')
    for field in ('echo_of_war_target','echo_of_war_location'):
        value=getattr(settings,field)
        if type(value) is not str or not 2<=len(value.strip())<=100:
            raise SettingsError(field,'历战周计划须填写明确副本和地点。')


def slot(day,now):
    schedule=SimpleNamespace(weekly_enabled=True,weekly_mode='differential_universe',weekly_day=day,
                             weekly_time='04:00',weekly_runs=1)
    return weekly_slot(schedule,now)


def create(settings,*,started_at=''):
    validate_settings(settings)
    if not settings.echo_of_war_enabled:return None
    started=datetime.fromisoformat(started_at) if started_at else local_now()
    schedule=slot(settings.echo_of_war_start_day,started)
    return dict(schema=1,start_day=settings.echo_of_war_start_day,started_at=started.isoformat(),
        week=schedule.week,due_at=schedule.due_at.isoformat(),due=schedule.due,
        target=dict(category='echo_of_war',target=settings.echo_of_war_target.strip(),location=settings.echo_of_war_location.strip()),
        maximum=3,completed=0,observations=[],state='waiting' if schedule.due else 'not_due')


def target(data):return items([dict(data['target'],count=3)])[0]


def remaining(data):
    if not data['observations']:return None
    last=data['observations'][-1]
    return last['remaining']-(data['completed']-last['completed'])


def require_week(data):
    if not data['due']:raise AutomationError('历战周计划尚未到期，未开始挑战。')
    if slot(data['start_day'],local_now()).week!=data['week']:
        raise AutomationError('历战周计划已跨游戏周，保留原额度，不自动建立新周目标。')


def validate(data,proof,*,completed=None):
    """Validate frozen scheduling and monotonically consumed observed quota."""
    if data is None:
        if completed:raise ValueError('没有历战周目标却存在支付')
        return None
    if (type(data) is not dict or type(data['schema']) is not int or data['schema']!=1
            or type(data['start_day']) is not int or not 1<=data['start_day']<=7
            or type(data['maximum']) is not int or data['maximum']!=3
            or type(data['completed']) is not int or not 0<=data['completed']<=3
            or type(data['due']) is not bool
            or data['state'] not in ('waiting','not_due','active','complete','limited','partial')
            or type(data['observations']) is not list or len(data['observations'])>20):raise ValueError('历战周目标结构无效')
    started=datetime.fromisoformat(data['started_at']);schedule=slot(data['start_day'],started)
    if (data['week']!=schedule.week or data['due']!=schedule.due or data['due_at']!=schedule.due_at.isoformat()
            or target(data).category!='echo_of_war' or completed is not None and completed!=data['completed']):
        raise ValueError('历战游戏周、目标或支付计数不同')
    previous=None
    for observation in data['observations']:
        if (type(observation) is not dict or any(type(observation[k]) is not int or not 0<=observation[k]<=3 for k in ('remaining','completed'))
                or observation['completed']>data['completed']):raise ValueError('历战周次数观察无效')
        if previous is None:
            if observation['completed']!=0:raise ValueError('历战缺少支付前周次数')
        elif (observation['completed']<previous['completed']
                or observation['remaining']>previous['remaining']-(observation['completed']-previous['completed'])):
            raise ValueError('历战观察扩大了原周额度')
        proof(observation['evidence']);previous=observation
    if not data['due']:
        if data['state']!='not_due' or data['completed'] or previous is not None:raise ValueError('未到期历战已有执行记录')
    elif previous is None:
        if data['state']!='waiting' or data['completed']:raise ValueError('历战缺少本周额度来源')
    elif (remaining(data)<0 or data['completed']>data['observations'][0]['remaining']
            or data['state']=='complete' and (previous['remaining']!=0 or previous['completed']!=data['completed'])):
        raise ValueError('历战次数或完成证据不符')
    return target(data)
