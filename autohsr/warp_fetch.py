"""Explicit cache/URL reads and bounded, official GET-only history pagination.

No game process, input framework, automatic Player.log discovery or telemetry.
Auth URLs stay in memory and never appear in events, exceptions or exports.
"""
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .warp_records import LANGS,POOLS,WarpError,account,loads,merge,uid,zone

MAX_CACHE=64*1024*1024
ENDPOINTS={'hkrpg_cn':'https://public-operation-hkrpg.mihoyo.com',
           'hkrpg_global':'https://public-operation-hkrpg-sg.hoyoverse.com'}


class WarpStopped(WarpError):pass


def checkpoint(cancel):
    if cancel is not None and cancel():raise WarpStopped('跃迁记录操作已停止，原文件保持。')


class WarpLink:
    def __init__(self,url):
        try:
            if type(url) is not str:raise ValueError()
            url=url.strip()
            if len(url)>65536 or any(char.isspace() for char in url):raise ValueError()
            parsed=urllib.parse.urlsplit(url)
            host=parsed.hostname or ''
            if (parsed.scheme!='https' or parsed.username is not None or parsed.password is not None
                    or parsed.port not in (None,443) or not any(host==d or host.endswith('.'+d) for d in ('mihoyo.com','hoyoverse.com'))):
                raise ValueError()
            pairs=urllib.parse.parse_qsl(parsed.query,keep_blank_values=True,strict_parsing=True,max_num_fields=100)
            params={}
            for key,value in pairs:
                if key in params:raise ValueError()
                if key not in ('page','size','end_id','gacha_type'):params[key]=value
            if (params.get('game_biz') not in ENDPOINTS or not params.get('authkey')
                    or params.get('auth_appid')!='webview_gacha' or params.get('lang') not in LANGS):raise ValueError()
        except (AttributeError,TypeError,ValueError) as error:raise WarpError('跃迁记录链接缺少有效的官方来源、鉴权或语言字段。') from error
        self._params=params

    def __repr__(self):return '<WarpLink redacted>'

    @property
    def language(self):return self._params['lang']

    def request_url(self,pool,page,end_id):
        path='getLdGachaLog' if pool in ('21','22') else 'getGachaLog'
        params=dict(self._params,gacha_type=pool,page=str(page),size='20',end_id=str(end_id))
        return ENDPOINTS[self._params['game_biz']]+'/common/hkrpg_gacha_record/api/'+path+'?'+urllib.parse.urlencode(params)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):return None


def request_page(url):
    """Redirection is disabled so auth cannot move to a different host."""
    opener=urllib.request.build_opener(_NoRedirect)
    with opener.open(urllib.request.Request(url,headers={'User-Agent':'AutoHSR/0.1.0'}),timeout=15) as response:
        if response.status!=200:raise WarpError('官方记录接口返回非成功状态。')
        raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise WarpError('官方记录响应超过大小限制。')
        return loads(raw)


def read_url_file(path):
    with Path(path).open('rb') as stream:raw=stream.read(1024*1024+1)
    if len(raw)>1024*1024:raise WarpError('链接文件超过大小限制。')
    try:return WarpLink(raw.decode('utf-8-sig').strip())
    except UnicodeError as error:raise WarpError('链接文件不是有效UTF-8文字。') from error


def find_cache_link(directory,*,cancel=None):
    """Only the explicitly supplied StarRail_Data directory is searched."""
    directory=Path(directory)
    if not directory.is_dir():raise WarpError('指定缓存目录不存在。')
    paths=sorted(directory.glob('webCaches/*/Cache/Cache_Data/data_2'),key=lambda p:p.stat().st_mtime_ns,reverse=True)
    if len(paths)>100:raise WarpError('缓存目录候选过多，请核对指定的StarRail_Data目录。')
    consumed=0
    for path in paths:
        checkpoint(cancel)
        with path.open('rb') as stream:raw=stream.read(MAX_CACHE-consumed+1)
        consumed+=len(raw)
        if consumed>MAX_CACHE:raise WarpError('缓存读取超过64 MiB总上限。')
        candidates=[]
        for match in re.finditer(rb'https://[^\x00-\x20<>"\\]+',raw):
            if len(candidates)==10000:raise WarpError('缓存链接候选过多，请改用明确的链接文件。')
            candidates.append(match)
        for match in reversed(candidates):
            try:return WarpLink(match[0].decode('utf8'))
            except (WarpError,UnicodeError):continue
    raise WarpError('未找到有效跃迁记录链接，请在游戏中手动打开记录后重新读取。')


def paths_from_player_log(path):
    """Optional helper for a user-selected log; never scans local profiles."""
    with Path(path).open('rb') as stream:raw=stream.read(16*1024*1024+1)
    if len(raw)>16*1024*1024:raise WarpError('所选客户端日志超过16 MiB上限。')
    text=raw.decode('utf8',errors='replace').replace('\\','/')
    values=re.findall(r'[A-Za-z]:/[^\r\n"<>]*?/StarRail_Data/',text)
    return tuple(dict.fromkeys(Path(value) for value in values))


def fetch(link,*,pools=POOLS,max_pages=1000,request=None,cancel=None,emit=None,sleep=None):
    if not isinstance(link,WarpLink):raise WarpError('需要经过核对的跃迁记录链接。')
    if type(max_pages) is not int or not 1<=max_pages<=5000:raise WarpError('每卡池页数上限须为1～5000。')
    if (not isinstance(pools,(tuple,list)) or not pools or any(type(p) is not str or p not in POOLS for p in pools)
            or len(set(pools))!=len(pools)):
        raise WarpError('卡池必须从1、2、11、12、21、22中明确选择且不重复。')
    request=request or request_page;emit=emit or (lambda event:None);sleep=sleep or time.sleep
    current_uid=None;timezone=None;records=[];pages=0
    for pool in pools:
        end=0;done=False
        for page in range(1,max_pages+1):
            checkpoint(cancel)
            response=None
            for retry in range(3):
                checkpoint(cancel)
                try:response=request(link.request_url(pool,page,end));break
                except WarpError:raise
                except urllib.error.HTTPError as error:
                    if error.code<500 or retry==2:
                        raise WarpError('官方接口的HTTP状态未通过，未跟随重定向或输出完整结果。') from None
                    for _ in range(5):checkpoint(cancel);sleep(.1)
                except (OSError,TimeoutError):
                    if retry==2:raise WarpError('官方记录读取失败，重试上限已到；未保存为完整结果。') from None
                    for _ in range(5):checkpoint(cancel);sleep(.1)
            checkpoint(cancel);pages+=1
            if type(response) is not dict or type(response.get('retcode')) is not int:raise WarpError('官方记录响应结构无效。')
            if response['retcode']!=0:
                raise WarpError('跃迁记录鉴权已过期，请手动重新打开游戏记录。' if response['retcode']==-101 else '官方记录接口拒绝请求，未转述其原始返回文字。')
            data=response.get('data')
            if type(data) is not dict or type(data.get('list')) is not list or len(data['list'])>20:
                raise WarpError('官方记录页缺少有效列表。')
            rows=data['list']
            if not rows:done=True;break
            observed_zone=zone(data.get('region_time_zone'))
            if timezone is None:timezone=observed_zone
            elif timezone!=observed_zone:raise WarpError('获取途中记录时区发生变化。')
            ids=[]
            for row in rows:
                if type(row) is not dict or row.get('lang')!=link.language:raise WarpError('记录语言与本次链接不同。')
                observed_uid=uid(row.get('uid'))
                if current_uid is None:current_uid=observed_uid
                elif current_uid!=observed_uid:raise WarpError('获取途中账号发生变化，未合并账号。')
                # Account/record validators also enforce every required field.
                value=account(dict(uid=current_uid,timezone=timezone,lang=link.language,list=[row]))['list'][0]
                if value['gacha_type']!=pool:raise WarpError('返回记录不属于本次请求的卡池。')
                ids.append(int(value['id']));records.append(value)
            if ids!=sorted(set(ids),reverse=True) or end and ids[0]>=end:
                raise WarpError('记录分页ID重复或未向旧记录推进，未无限重试。')
            end=ids[-1]
            if len(records)>500000:raise WarpError('接口记录超过数量上限。')
            emit(dict(type='warp_fetch_progress',pool=pool,page=page,records=len(records)))
            checkpoint(cancel);sleep(.3)
        if not done:raise WarpError('到达本次页数上限，尚未读到末页；未输出为完整记录。')
    if current_uid is None:raise WarpError('所有卡池均为空，无法核实记录所属账号。')
    return merge([dict(uid=current_uid,timezone=timezone,lang=link.language,list=records)]),dict(pools=list(pools),pages=pages,complete=True)
