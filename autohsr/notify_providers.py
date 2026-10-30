"""Text adapters for the pinned March7thAssistant notification registry.

No provider module is imported from upstream. Images, encrypted Matrix rooms,
Bark ciphertext and QQ event discovery are separate, still-unimplemented paths.
"""
from copy import deepcopy
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlencode, urlsplit, urlunsplit, parse_qsl

from .notify_http import Call, Reply, headers, json_body, url
from .notify_profiles import NotifyError, NotifyCancelled, PROVIDERS, MAX_BYTES, text

OPTIONS = {
 'telegram': 'token userid api_url thread_id',
 'matrix': 'homeserver access_token room_id device_id user_id',
 'onebot': 'endpoint token user_id group_id',
 'gocqhttp': 'endpoint path token user_id group_id message_type auto_escape',
 'smtp': 'host user password From To port ssl starttls',
 'wechatworkapp': 'corpid corpsecret agentid touser base_url',
 'wechatworkbot': 'key webhook_url',
 'custom': 'url method datatype data',
 'lark': 'webhook sign keyword',
 'serverchan3': 'sendkey',
 'serverchanturbo': 'sctkey channel openid',
 'kook': 'token target_id chat_type',
 'webhook': 'url method headers body',
 'meow': 'nickname',
 'bark': 'key device_key base_url group icon isarchive sound url copy autocopy',
 'dingtalk': 'token secret markdown',
 'discord': 'webhook username avatar_url color',
 'gotify': 'url token priority',
 'pushdeer': 'token pushkey type url',
 'pushplus': 'token markdown topic channel webhook callbackUrl',
 'qmsg': 'key mode qq',
 'qqbot': 'appid client_secret openid group_openid',
 'winotify': 'app_id',
}
REQUIRED = {
 'telegram': 'token userid', 'matrix': 'homeserver access_token room_id',
 'onebot': 'endpoint', 'gocqhttp': 'endpoint', 'smtp': 'host',
 'wechatworkapp': 'corpid corpsecret agentid touser', 'custom': 'url',
 'lark': 'webhook', 'serverchan3': 'sendkey', 'serverchanturbo': 'sctkey',
 'kook': 'token target_id', 'webhook': 'url', 'meow': 'nickname',
 'dingtalk': 'token', 'discord': 'webhook', 'gotify': 'url token',
 'pushplus': 'token', 'qmsg': 'key', 'qqbot': 'appid client_secret',
}
BOOLEAN = {'allow_insecure', 'auto_escape', 'ssl', 'starttls', 'markdown'}
INTEGER = {'port', 'priority', 'thread_id', 'isarchive', 'autocopy', 'color'}
URL_FIELDS = {'url', 'base_url', 'homeserver', 'endpoint', 'webhook_url', 'webhook', 'avatar_url', 'icon', 'callbackUrl'}


def _string(params, key, default=None):
    value = params.get(key, default)
    if type(value) is int and key in ('userid', 'user_id', 'group_id', 'agentid', 'appid', 'qq', 'target_id'):
        value = str(value)
    return text(value)


def validate(provider, params):
    allowed = set(OPTIONS[provider].split()) | {'allow_insecure'}
    if set(params) - allowed:
        raise NotifyError('通知包含尚未支持的参数；未忽略或降级凭据、图片及加密选项。')
    for name, value in params.items():
        if name in BOOLEAN:
            if type(value) is not bool:
                raise NotifyError('通知开关必须是布尔值。')
        elif name in INTEGER:
            if type(value) is not int or not -1 <= value <= 16777215:
                raise NotifyError('通知整数参数无效。')
        elif name in ('headers', 'body', 'data') or name == 'To' and isinstance(value, list):
            continue
        else:
            if any(char in _string(params, name) for char in ('\r', '\n', '\t')):
                raise NotifyError('通知连接参数必须为单行文字。')
    for name in REQUIRED.get(provider, '').split():
        _string(params, name)
    for names in ({'onebot': ('user_id', 'group_id'), 'gocqhttp': ('user_id', 'group_id'),
                   'wechatworkbot': ('key', 'webhook_url'), 'bark': ('key', 'device_key'),
                   'pushdeer': ('token', 'pushkey'), 'qqbot': ('openid', 'group_openid')}.get(provider, ()),):
        if names and not any(params.get(name) for name in names):
            raise NotifyError('通知缺少明确的凭据或接收对象。')
    insecure = params.get('allow_insecure', False)
    for name in URL_FIELDS & set(params):
        # Pushplus webhook is a service routing name, Bark url is an open-on-tap link.
        if (provider, name) in (('pushplus', 'webhook'),):
            continue
        value = _string(params, name)
        if provider == 'gocqhttp' and name == 'endpoint' and '://' not in value:
            value = 'http://' + value
        url(value, insecure=insecure)
    if 'headers' in params:
        headers(params['headers'])
    if params.get('method', 'POST').upper() not in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE'):
        raise NotifyError('通知请求方法无效。')
    if provider == 'custom' and params.get('datatype', 'data') not in ('data', 'json', 'params'):
        raise NotifyError('自定义通知datatype须为data、json或params。')
    if provider == 'kook' and params.get('chat_type', '1') not in ('1', '9'):
        raise NotifyError('KOOK接收类型须为字符串1（私聊）或9（频道）。')
    if provider == 'smtp':
        from .notify_local import validate_smtp
        validate_smtp(params)
    # Build once without network so every required URL/format is checked before dispatch.
    if provider not in ('smtp', 'winotify', 'wechatworkapp', 'qqbot', 'matrix'):
        calls(provider, params, 'AutoHSR', 'configuration check', 'validation')


def _add_query(address, values):
    part = urlsplit(address)
    query = dict(parse_qsl(part.query, keep_blank_values=True))
    query.update(values)
    return urlunsplit((part.scheme, part.netloc, part.path, urlencode(query), ''))


def _call(address, params, *, body=None, form=None, method='POST', extra_headers=None, phase='send'):
    address = url(address, insecure=params.get('allow_insecure', False))
    hdrs = headers(extra_headers or {})
    raw = None
    if body is not None:
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf8')
        if not any(name.lower() == 'content-type' for name in hdrs):
            hdrs['Content-Type'] = 'application/json; charset=utf-8'
    if form is not None:
        encoded = urlencode({key: val for key, val in form.items() if val is not None}, doseq=True)
        if method == 'GET':
            address = _add_query(address, form)
        else:
            raw = encoded.encode('utf8')
            if not any(name.lower() == 'content-type' for name in hdrs):
                hdrs['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8'
    if raw is not None and len(raw) > MAX_BYTES:
        raise NotifyError('通知请求超过64 KiB。')
    return Call(address, method, raw, hdrs, phase)


def _replace(value, title, content, depth=0):
    if depth > 8:
        raise NotifyError('通知模板嵌套过深。')
    if isinstance(value, dict):
        return {key: _replace(item, title, content, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace(item, title, content, depth + 1) for item in value]
    if isinstance(value, str):
        if '{image}' in value:
            raise NotifyError('图片通知尚未接入，未发送空图片冒充完成。')
        return value.replace('{title}', title).replace('{content}', content).replace('{message}', title + '\n' + content)
    return value


def calls(provider, p, title, content, identity, *, token=None):
    message = title + ('\n' + content if content else '')
    make = lambda address, **options: _call(address, p, **options)
    if provider == 'telegram':
        base = p.get('api_url', 'api.telegram.org').rstrip('/')
        if '://' not in base:
            base = 'https://' + base
        data = dict(chat_id=_string(p, 'userid'), text=message)
        if 'thread_id' in p:
            data['message_thread_id'] = p['thread_id']
        return [make(base + '/bot' + quote(p['token'], safe=':') + '/sendMessage', body=data)]
    if provider in ('onebot', 'gocqhttp'):
        endpoint = p['endpoint'].rstrip('/')
        if provider == 'gocqhttp' and '://' not in endpoint:
            endpoint = 'http://' + endpoint
        path = p.get('path', '/send_msg') if provider == 'gocqhttp' else '/send_msg'
        if not path.startswith('/') or '?' in path or '#' in path:
            raise NotifyError('通知路径无效。')
        endpoint = endpoint if endpoint.endswith(path) else endpoint + path
        result = []
        targets = (('private', 'user_id'), ('group', 'group_id'))
        if provider == 'gocqhttp' and 'message_type' in p:
            kind = p['message_type']
            if kind not in ('private', 'group'):
                raise NotifyError('GoCQHTTP消息类型须为private或group。')
            name = 'user_id' if kind == 'private' else 'group_id'
            if not p.get(name):
                raise NotifyError('GoCQHTTP所选消息类型缺少对应接收对象。')
            targets = ((kind, name),)
        for kind, name in targets:
            if p.get(name):
                data = dict(message_type=kind, **{name: _string(p, name)},
                            message=[dict(type='text', data=dict(text=message))] if provider == 'onebot' else message)
                if provider == 'gocqhttp':
                    data.update(access_token=p.get('token'), auto_escape=p.get('auto_escape', True))
                    result.append(make(endpoint, method='GET', form=data))
                else:
                    hdrs = {'Authorization': 'Bearer ' + p['token']} if p.get('token') else {}
                    result.append(make(endpoint, body=data, extra_headers=hdrs))
        return result
    if provider == 'matrix':
        base = p['homeserver'].rstrip('/') + '/_matrix/client/v3/rooms/' + quote(p['room_id'], safe='')
        hdrs = dict(Authorization='Bearer ' + p['access_token'])
        return [make(base + '/send/m.room.message/' + quote(identity, safe=''), method='PUT',
                     body=dict(msgtype='m.text', body=message), extra_headers=hdrs)]
    if provider == 'wechatworkapp':
        return [make(_add_query(p.get('base_url', 'https://qyapi.weixin.qq.com').rstrip('/') +
                     '/cgi-bin/message/send', dict(access_token=token)), body=dict(touser=p['touser'],
                     agentid=_string(p, 'agentid'), msgtype='text', text=dict(content=message), safe=0))]
    if provider == 'wechatworkbot':
        endpoint = p.get('webhook_url') or 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=' + quote(p['key'], safe='')
        return [make(endpoint, body=dict(msgtype='text', text=dict(content=message)))]
    if provider == 'qqbot':
        return [make('https://api.sgroup.qq.com/v2/' + kind + '/' + quote(p[name], safe='') + '/messages',
                     body=dict(content=message, msg_type=0), extra_headers=dict(Authorization='QQBot ' + token))
                for kind, name in (('users', 'openid'), ('groups', 'group_openid')) if p.get(name)]
    if provider in ('serverchan3', 'serverchanturbo'):
        key = p['sendkey' if provider == 'serverchan3' else 'sctkey']
        endpoint = 'https://sctapi.ftqq.com/' + quote(key, safe='') + '.send'
        if provider == 'serverchan3' and key.startswith('sctp'):
            import re
            matched = re.match(r'sctp([0-9]+)t', key)
            if not matched:
                raise NotifyError('Server酱3凭据格式无效。')
            endpoint = 'https://' + matched[1] + '.push.ft07.com/send/' + quote(key, safe='') + '.send'
        if provider == 'serverchan3':
            return [make(endpoint, body=dict(title=title, desp=content))]
        return [make(endpoint, form=dict(text=title, desp=content,
                     **{key: p[key] for key in ('channel', 'openid') if key in p}))]
    if provider == 'lark':
        if p.get('keyword'):
            content = p['keyword'] + '\n' + content
        data = dict(msg_type='post', content=dict(post=dict(zh_cn=dict(title=title,
                    content=[[dict(tag='text', text=content)]]))))
        if p.get('sign'):
            stamp = str(int(time.time()))
            signature = hmac.new((stamp + '\n' + p['sign']).encode(), digestmod=hashlib.sha256).digest()
            data.update(timestamp=stamp, sign=base64.b64encode(signature).decode())
        return [make(p['webhook'], body=data)]
    if provider == 'dingtalk':
        endpoint = p['token'] if p['token'].startswith(('https://', 'http://')) else \
                   'https://oapi.dingtalk.com/robot/send?access_token=' + quote(p['token'], safe='')
        if p.get('secret'):
            stamp = str(int(time.time() * 1000))
            signature = hmac.new(p['secret'].encode(), (stamp + '\n' + p['secret']).encode(), hashlib.sha256).digest()
            endpoint = _add_query(endpoint, dict(timestamp=stamp, sign=base64.b64encode(signature).decode()))
        data = dict(msgtype='markdown', markdown=dict(title=title, text=content)) if p.get('markdown') else \
               dict(msgtype='text', text=dict(content=message))
        return [make(endpoint, body=data)]
    if provider == 'discord':
        data = dict(embeds=[dict(title=title, description=content, color=p.get('color', 16478873))])
        data.update({name: p[name] for name in ('username', 'avatar_url') if name in p})
        return [make(p['webhook'], body=data)]
    if provider == 'bark':
        endpoint = p.get('base_url', 'https://api.day.app/push').rstrip('/')
        if not endpoint.endswith('/push'):
            endpoint += '/push'
        data = dict(device_key=p.get('key') or p['device_key'], title=title, body=content)
        mapping = dict(group='group', icon='icon', isarchive='isArchive', sound='sound', url='url', copy='copy', autocopy='autoCopy')
        data.update({target: p[key] for key, target in mapping.items() if key in p})
        return [make(endpoint, body=data)]
    if provider == 'gotify':
        return [make(_add_query(p['url'].rstrip('/') + '/message', dict(token=p['token'])),
                     body=dict(title=title, message=content or '.', priority=p.get('priority', 0)))]
    if provider == 'pushdeer':
        return [make(p.get('url', 'https://api2.pushdeer.com/message/push'), body=dict(
                     pushkey=p.get('token') or p['pushkey'], type=p.get('type', 'markdown'), text=title, desp=content or '.'))]
    if provider == 'pushplus':
        data = dict(token=p['token'], title=title, content=content or '.', template='markdown' if p.get('markdown') else 'html')
        data.update({key: p[key] for key in ('topic', 'channel', 'webhook', 'callbackUrl') if key in p})
        return [make('https://www.pushplus.plus/send', body=data)]
    if provider == 'qmsg':
        mode = p.get('mode', 'send')
        if mode not in ('send', 'group'):
            raise NotifyError('Qmsg模式须为send或group。')
        return [make('https://qmsg.zendee.cn/' + mode + '/' + quote(p['key'], safe=''),
                     form=dict(msg=message, qq=p.get('qq')))]
    if provider == 'kook':
        kind = p.get('chat_type', '1')
        if kind not in ('1', '9'):
            raise NotifyError('KOOK接收类型须为字符串1（私聊）或9（频道）。')
        # Preserve the upstream configuration intent: 1 selects a user, 9 a
        # channel. The API's `type` itself describes text formatting, not routing.
        route = 'direct-message' if kind == '1' else 'message'
        return [make('https://www.kookapp.cn/api/v3/' + route + '/create', body=dict(type=int(kind),
                     target_id=_string(p, 'target_id'), content=('**' + title + '**\n' + content) if kind == '9' else message),
                     extra_headers=dict(Authorization='Bot ' + p['token']))]
    if provider == 'meow':
        return [make('https://api.chuckfang.com/' + quote(p['nickname'], safe='') + '/', body=dict(title=title, msg=content))]
    if provider in ('webhook', 'custom'):
        body = _replace(p.get('body' if provider == 'webhook' else 'data', dict(title='{title}', content='{content}')), title, content)
        method = p.get('method', 'POST').upper()
        hdrs = p.get('headers', {})
        datatype = p.get('datatype', 'json' if provider == 'webhook' else 'data')
        if isinstance(body, str):
            if len(body.encode('utf8')) > MAX_BYTES:
                raise NotifyError('通知模板超过64 KiB。')
            return [Call(url(p['url'], insecure=p.get('allow_insecure', False)), method, body.encode('utf8'), headers(hdrs))]
        if datatype != 'json':
            if not isinstance(body, dict):
                raise NotifyError('表单通知模板需要对象。')
            if datatype == 'params':
                return [make(_add_query(p['url'], body), method=method, extra_headers=hdrs)]
            return [make(p['url'], method=method, form=body, extra_headers=hdrs)]
        return [make(p['url'], method=method, body=body, extra_headers=hdrs)]
    raise NotifyError('当前通知渠道需要独立传输。')


def acknowledgement(provider, reply):
    if 300 <= reply.status < 400 or reply.status >= 500:
        return 'unknown'
    if not 200 <= reply.status < 300:
        return 'rejected'
    data = json_body(reply)
    expected = {'serverchan3': ('code', 0), 'serverchanturbo': ('code', 0), 'bark': ('code', 200),
                'pushplus': ('code', 200), 'pushdeer': ('code', 0), 'kook': ('code', 0),
                'wechatworkbot': ('errcode', 0), 'wechatworkapp': ('errcode', 0), 'dingtalk': ('errcode', 0),
                'meow': ('status', 200)}
    if provider in expected:
        key, value = expected[provider]
        if type(data.get(key)) is not int:
            return 'unknown'
        if data[key] != value:
            return 'rejected'
        if provider == 'wechatworkapp' and any(data.get(key) for key in ('invaliduser', 'invalidparty', 'invalidtag', 'unlicenseduser')):
            return 'partial'
        return 'accepted'
    if provider in ('onebot', 'gocqhttp'):
        code, status = data.get('retcode'), data.get('status')
        if type(code) is not int:
            return 'unknown'
        if status == 'ok' and code == 0:
            return 'accepted'
        if status == 'failed' and code not in (0, 1):
            return 'rejected'
        return 'unknown'  # Async acceptance does not verify the eventual result.
    if provider == 'telegram':
        return 'accepted' if data.get('ok') is True else 'rejected' if data.get('ok') is False else 'unknown'
    if provider in ('matrix', 'qqbot', 'gotify'):
        key = {'matrix': 'event_id', 'qqbot': 'id', 'gotify': 'id'}[provider]
        return 'accepted' if isinstance(data.get(key), (str, int)) and not isinstance(data[key], bool) and data[key] else \
               'rejected' if data.get('errcode') or data.get('code') or data.get('error') else 'unknown'
    if provider == 'lark':
        values = [data[key] for key in ('code', 'StatusCode') if key in data]
        return 'accepted' if values and all(type(v) is int and v == 0 for v in values) else \
               'rejected' if values and all(type(v) is int and v != 0 for v in values) else 'unknown'
    if provider == 'qmsg':
        return 'accepted' if data.get('success') is True and type(data.get('code', 0)) is int and data.get('code', 0) == 0 else \
               'rejected' if data.get('success') is False else 'unknown'
    if provider == 'discord' and (data.get('code') or data.get('error')):
        return 'rejected'
    return 'accepted'  # Generic webhook/Discord: HTTP acceptance, not human delivery.


def execute(profile, title, content, identity, *, request, checkpoint, dispatch, acknowledged, local_send=None):
    provider, p = profile['provider'], profile['params']
    validate(provider, p)
    token = None
    if provider in ('smtp', 'winotify'):
        from .notify_local import send
        checkpoint(); dispatch('send', 0)
        status = (local_send or send)(provider, p, title, content)
        acknowledged(0, status)
        return status
    if provider == 'matrix':
        endpoint = p['homeserver'].rstrip('/') + '/_matrix/client/v3/rooms/' + quote(p['room_id'], safe='') + '/state/m.room.encryption'
        checkpoint(); dispatch('verify_room', -1)
        reply = request(_call(endpoint, p, method='GET', extra_headers=dict(Authorization='Bearer ' + p['access_token']), phase='verify'))
        if not (reply.status == 404 and json_body(reply).get('errcode') == 'M_NOT_FOUND'):
            raise NotifyError('Matrix房间未核实为无加密；未发送明文消息。')
        acknowledged(-1, 'verified')
    if provider in ('wechatworkapp', 'qqbot'):
        if provider == 'wechatworkapp':
            endpoint = _add_query(p.get('base_url', 'https://qyapi.weixin.qq.com').rstrip('/') + '/cgi-bin/gettoken',
                                  dict(corpid=p['corpid'], corpsecret=p['corpsecret']))
            call = _call(endpoint, p, method='GET', phase='authorize')
        else:
            call = _call('https://bots.qq.com/app/getAppAccessToken', p,
                         body=dict(appId=_string(p, 'appid'), clientSecret=p['client_secret']), phase='authorize')
        checkpoint(); dispatch('authorize', -1)
        reply = request(call); data = json_body(reply)
        if not 200 <= reply.status < 300 or any(type(data[key]) is not int or data[key] != 0
                for key in ('code', 'errcode') if key in data):
            raise NotifyError('通知授权未核实；未提交消息。')
        token = text(data.get('access_token'))
        acknowledged(-1, 'verified')
    results = []
    for index, call in enumerate(calls(provider, p, title, content, identity, token=token)):
        checkpoint(); dispatch('send', index)
        status = acknowledgement(provider, request(call))
        acknowledged(index, status); results.append(status)
        if status != 'accepted':
            break
    return 'accepted' if results and all(value == 'accepted' for value in results) else \
           'partial' if 'accepted' in results or 'partial' in results else results[-1] if results else 'rejected'
