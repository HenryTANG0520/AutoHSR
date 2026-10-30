"""SMTP and Windows toast transports; invoked only by an opted-in caller."""
from email.message import EmailMessage
from email.utils import getaddresses
import ipaddress
import os
import re
import smtplib
import ssl
import subprocess

from .notify_profiles import NotifyError, text


def _addresses(value):
    values = value if isinstance(value, list) else [value]
    if not 1 <= len(values) <= 50:
        raise NotifyError('SMTP接收地址数量无效。')
    for item in values:
        text(item)
        if any(char in item for char in ('\r', '\n')):
            raise NotifyError('SMTP地址不能包含换行。')
    parsed = getaddresses(values)
    if not 1 <= len(parsed) <= 50 or any(not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+', address) for _, address in parsed):
        raise NotifyError('SMTP地址格式无效。')
    return [address for _, address in parsed]


def validate_smtp(p):
    host = text(p.get('host'), maximum=253)
    if '/' in host or any(c.isspace() for c in host):
        raise NotifyError('SMTP主机格式无效。')
    port = p.get('port', 465)
    if type(port) is not int or not 1 <= port <= 65535:
        raise NotifyError('SMTP端口须为1～65535的整数。')
    sender = p.get('From') or p.get('user')
    recipient = p.get('To') or p.get('user')
    if len(_addresses(sender)) != 1:
        raise NotifyError('SMTP需要一个发件地址。')
    _addresses(recipient)
    local = host.lower() == 'localhost'
    try:
        local |= ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if not p.get('ssl', True) and not p.get('starttls', False) and not (local or p.get('allow_insecure', False)):
        raise NotifyError('SMTP需要SSL、STARTTLS，或明确允许非加密传输。')
    if p.get('user') and not p.get('password'):
        raise NotifyError('SMTP认证需要密码。')


TOAST_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$null = [Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]
$null = [Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]
$titleText = [System.Security.SecurityElement]::Escape($env:AUTOHSR_NOTIFY_TITLE)
$bodyText = [System.Security.SecurityElement]::Escape($env:AUTOHSR_NOTIFY_BODY)
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$titleText</text><text>$bodyText</text></binding></visual></toast>")
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($env:AUTOHSR_NOTIFY_APP_ID).Show($toast)
'''


def send(provider, p, title, content):
    if provider == 'winotify':
        if os.name != 'nt':
            raise NotifyError('本机通知需要Windows。')
        env = dict(os.environ, AUTOHSR_NOTIFY_TITLE=title, AUTOHSR_NOTIFY_BODY=content,
                   AUTOHSR_NOTIFY_APP_ID=p.get('app_id', 'AutoHSR'))
        try:
            process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', TOAST_SCRIPT],
                env=env, capture_output=True, timeout=15, creationflags=0x08000000)
            return 'accepted' if process.returncode == 0 else 'rejected'
        except Exception:
            raise NotifyError('本机通知未取得可核实结果；不自动重试。') from None
    validate_smtp(p)
    sender = p.get('From') or p.get('user')
    recipients = p.get('To') or p.get('user')
    message = EmailMessage()
    message['Subject'], message['From'] = title, sender
    message['To'] = ', '.join(recipients) if isinstance(recipients, list) else recipients
    message.set_content(content, charset='utf8')
    connection = None
    try:
        context = ssl.create_default_context()
        if p.get('starttls', False):
            connection = smtplib.SMTP(p['host'], p.get('port', 587), timeout=15)
            connection.starttls(context=context)
        else:
            connection = smtplib.SMTP_SSL(p['host'], p.get('port', 465), timeout=15, context=context) if p.get('ssl', True) else \
                         smtplib.SMTP(p['host'], p.get('port', 25), timeout=15)
        if p.get('user'):
            connection.login(p['user'], p['password'])
        refused = connection.send_message(message, from_addr=_addresses(sender)[0], to_addrs=_addresses(recipients))
        return 'partial' if refused else 'accepted'
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused):
        return 'rejected'
    except Exception:
        raise NotifyError('SMTP未取得完整发送响应；状态未知，不自动重试。') from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
