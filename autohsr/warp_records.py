"""Local Star Rail records: strict types, numeric IDs and lossless core merging.

Behaviour reference: March7thAssistant app/tools/warp_export.py (7cf6c6b).
Interchange specification: https://uigf.org/zh/standards/uigf.html
"""
from copy import deepcopy
from datetime import datetime, timedelta
import json
import re
import time

from . import __version__

MAX_BYTES=32*1024*1024
MAX_ROWS=500000
POOLS=('1','2','11','12','21','22')
LANGS=frozenset(('de-de','en-us','es-es','fr-fr','id-id','it-it','ja-jp','ko-kr',
                 'pt-pt','ru-ru','th-th','tr-tr','vi-vn','zh-cn','zh-tw'))
REQUIRED=frozenset(('gacha_id','gacha_type','item_id','time','id'))
OPTIONAL=frozenset(('count','name','item_type','rank_type'))


class WarpError(ValueError):
    """Public messages deliberately contain no imported values or auth URLs."""


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise WarpError('记录JSON含重复字段，未猜测覆盖。')
        result[key]=value
    return result


def loads(raw):
    if not isinstance(raw,(str,bytes)) or len(raw)>MAX_BYTES:raise WarpError('记录文件超过32 MiB上限。')
    try:
        return json.loads(raw,object_pairs_hook=_pairs,
                          parse_constant=lambda _:(_ for _ in ()).throw(WarpError('记录包含非有限数值。')))
    except (UnicodeError,json.JSONDecodeError,RecursionError) as error:
        raise WarpError('记录JSON无法解析。') from error


def uid(value):
    if type(value) is int and value>=0:value=str(value)
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,20}',value):raise WarpError('账号UID格式无效。')
    return value


def zone(value):
    # SRGF uses number, UIGF uses integer. An integral legacy number is exact.
    if type(value) is float and value.is_integer():value=int(value)
    if type(value) is not int or not -23<=value<=23:raise WarpError('记录时区须为有效的整小时偏移。')
    return value


def record(raw):
    if type(raw) is not dict or not REQUIRED<=raw.keys():raise WarpError('记录缺少卡池、物品、时间或ID。')
    if any(type(raw[k]) is not str for k in REQUIRED|OPTIONAL if k in raw):
        raise WarpError('记录的ID、卡池及物品字段必须保留字符串类型。')
    if (raw['gacha_type'] not in POOLS or not re.fullmatch(r'[0-9]{1,19}',raw['id'])
            or any(not raw[k] or len(raw[k])>100 for k in ('gacha_id','item_id'))):
        raise WarpError('记录ID、物品或卡池类型无效。')
    try:
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}',raw['time']):raise ValueError()
        datetime.strptime(raw['time'],'%Y-%m-%d %H:%M:%S')
    except ValueError as error:raise WarpError('记录时间必须是有效的原始年月日时分秒。') from error
    if ('count' in raw and not re.fullmatch(r'[1-9][0-9]{0,5}',raw['count'])
            or 'rank_type' in raw and raw['rank_type'] not in ('3','4','5')
            or any(len(raw[k])>500 for k in ('name','item_type') if k in raw)):
        raise WarpError('记录数量、星级或显示文字无效。')
    # Unknown extension fields are retained locally, rather than silently lost.
    try:json.dumps(raw,allow_nan=False)
    except (ValueError,TypeError,RecursionError) as error:raise WarpError('记录扩展字段不是有效JSON。') from error
    return deepcopy(raw)


def account(raw,*,srgf=False):
    if type(raw) is not dict or not {'uid','timezone','list'}<=raw.keys():raise WarpError('账号记录缺少UID、时区或列表。')
    language=raw.get('lang')
    if language is not None and (type(language) is not str or language not in LANGS):raise WarpError('记录语言代码不受支持。')
    if srgf and language is None:raise WarpError('SRGF必须声明记录语言。')
    rows=raw['list']
    if type(rows) is not list or len(rows)>MAX_ROWS:raise WarpError('记录列表无效或超过数量上限。')
    result=dict(uid=uid(raw['uid']),timezone=zone(raw['timezone']),list=[])
    if language is not None:result['lang']=language
    by_id={}
    for raw_row in rows:
        value=record(raw_row)
        for key,expected in (('uid',result['uid']),('lang',language)):
            if key in value and (uid(value[key]) if key=='uid' else value[key])!=expected:
                raise WarpError('单条记录的账号或语言与分组不同。')
            value.pop(key,None)
        key=value['id']
        if key in by_id:value=_combine(by_id[key],value)
        by_id[key]=value
    result['list']=sorted(by_id.values(),key=lambda row:int(row['id']))
    return result


def _combine(left,right):
    for key in left.keys()&right.keys():
        if left[key]!=right[key]:raise WarpError('相同账号和记录ID存在冲突，未覆盖原记录。')
    return dict(deepcopy(left),**deepcopy(right))


def parse(data):
    """Read Star Rail only; return canonical accounts and explicit format notes."""
    if type(data) is not dict or type(data.get('info')) is not dict:raise WarpError('未识别记录格式。')
    info=data['info'];notes=[]
    if 'srgf_version' in info:
        if info['srgf_version']!='v1.0':raise WarpError('不支持该SRGF版本。')
        if not {'uid','region_time_zone','lang'}<=info.keys() or 'list' not in data:raise WarpError('SRGF账号信息不完整。')
        accounts=[account(dict(uid=info['uid'],timezone=info['region_time_zone'],lang=info['lang'],list=data['list']),srgf=True)]
        if any(r['gacha_type'] in ('21','22') for r in accounts[0]['list']):
            notes.append('legacy_srgf_extended_pools')
        source='srgf-v1.0'
    else:
        if info.get('version') not in ('v4.0','v4.1','v4.2'):raise WarpError('仅支持UIGF v4.0、v4.1、v4.2中的星铁记录。')
        if (not {'export_timestamp','export_app','export_app_version'}<=info.keys()
                or type(info['export_timestamp']) not in (str,int) or type(info['export_app']) is not str
                or type(info['export_app_version']) is not str):raise WarpError('UIGF导出信息字段或类型不完整。')
        values=data.get('hkrpg')
        if type(values) is not list or not values or len(values)>1000:raise WarpError('UIGF没有有效的星铁账号列表。')
        accounts=[account(a) for a in values];source='uigf-'+info['version']
        if info['version']=='v4.0' and any(r['gacha_type'] in ('21','22') for a in accounts for r in a['list']):
            raise WarpError('UIGF v4.0不包含联动卡池，请使用正确的v4.1或v4.2文件。')
        if any(key in data for key in ('hk4e','nap','hk4e_ugc')):notes.append('other_games_not_imported')
    return merge(accounts),dict(format=source,notes=notes)


def merge(*groups):
    """Same UID: preserve first timezone and convert incoming wall times exactly."""
    result={}
    for group in groups:
        for original in group:
            incoming=account(original);key=incoming['uid']
            if key not in result:result[key]=incoming;continue
            base=result[key]
            if incoming.get('lang')!=base.get('lang'):
                raise WarpError('同账号记录语言不同，请分别导出；未混合翻译文字。')
            previous={r['id']:r for r in base['list']}
            for row in incoming['list']:
                delta=base['timezone']-incoming['timezone']
                if delta:
                    try:row['time']=(datetime.strptime(row['time'],'%Y-%m-%d %H:%M:%S')+timedelta(hours=delta)).isoformat(' ',timespec='seconds')
                    except (ValueError,OverflowError) as error:raise WarpError('记录时间无法转换至原时区。') from error
                if row['id'] in previous:row=_combine(previous[row['id']],row)
                previous[row['id']]=row
            if len(previous)>MAX_ROWS:raise WarpError('合并后记录超过数量上限。')
            base['list']=sorted(previous.values(),key=lambda row:int(row['id']))
    return sorted(result.values(),key=lambda a:int(a['uid']))


def export(accounts,*,format='uigf',selected_uid=None,timestamp=None):
    values=merge(accounts)
    if selected_uid is not None:
        key=uid(selected_uid);values=[a for a in values if a['uid']==key]
        if not values:raise WarpError('指定账号不在本次记录中。')
    if not values:raise WarpError('没有可导出的星铁账号记录。')
    timestamp=int(time.time()) if timestamp is None else timestamp
    if type(timestamp) is not int or timestamp<0:raise WarpError('导出时间戳无效。')
    info=dict(export_timestamp=timestamp,export_app='AutoHSR',export_app_version=__version__)
    if format=='uigf':return dict(info=dict(info,version='v4.2'),hkrpg=values)
    if format!='srgf':raise WarpError('导出格式须为uigf或srgf。')
    if len(values)!=1:raise WarpError('SRGF只能保存一个账号，请明确指定UID或使用UIGF。')
    value=values[0]
    if 'lang' not in value:raise WarpError('SRGF需要明确语言，未补造默认语言。')
    if any(r['gacha_type'] in ('21','22') for r in value['list']):
        raise WarpError('SRGF v1.0不支持联动卡池，请使用UIGF以保留全部记录。')
    return dict(info=dict(info,uid=value['uid'],lang=value['lang'],region_time_zone=value['timezone'],srgf_version='v1.0'),list=value['list'])


def summary(accounts):
    values=merge(accounts);pools={key:dict(records=0,four_star=0,five_star=0,unknown_rank=0) for key in POOLS}
    for a in values:
        for row in a['list']:
            totals=pools[row['gacha_type']];totals['records']+=1
            field={'4':'four_star','5':'five_star'}.get(row.get('rank_type'))
            if field:totals[field]+=1
            elif 'rank_type' not in row:totals['unknown_rank']+=1
    return dict(accounts=len(values),records=sum(len(a['list']) for a in values),pools=pools,
                history_complete=False,game_accessed=False)
