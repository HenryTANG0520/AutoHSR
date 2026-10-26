"""Local identity/version evidence; never exported as model input."""
from __future__ import annotations

import configparser
import hashlib
import re
from pathlib import Path

from .currency_wars_prepare import trusted
from .models import AutomationError, normalize


def account_key(scene, confidence=.85):
    values = [match[1] for token in trusted(scene,confidence).tokens
              if token.within((0,.94,.23,1)) and
              (match := re.fullmatch(r'uid([0-9]{8,10})',normalize(token.text)))]
    if len(values) != 1:
        raise AutomationError('当前账号标识未完整核实，未沿用旧对局事实。')
    return hashlib.sha256(('autohsr-currency-account-v1:'+values[0]).encode('ascii')).hexdigest()


def installed_client(executable):
    """The launcher config describes game version; EXE FileVersion is Unity."""
    try:
        if not isinstance(executable,(str,Path)):
            raise ValueError('missing process path')
        executable = Path(executable).resolve(strict=True)
        if executable.name.casefold() != 'starrail.exe' or not executable.is_file():
            raise ValueError('unexpected executable')
        path = executable.parent/'config.ini'
        if path.stat().st_size > 65536:
            raise ValueError('oversize config')
        raw = path.read_bytes()
        parser = configparser.ConfigParser(interpolation=None,strict=True)
        encoding = 'utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
        parser.read_string(raw.decode(encoding))
        sections = [section for section in parser.sections() if section.casefold() == 'general']
        if len(sections) != 1 or 'game_version' in parser.defaults():
            raise ValueError('ambiguous version section')
        full = parser.get(sections[0],'game_version',raw=True).strip()
        match = re.fullmatch(r'([1-9][0-9]?)\.([0-9]{1,2})\.[0-9]{1,4}',full)
        if not match:
            raise ValueError('invalid version')
        return dict(version=match[1]+'.'+str(int(match[2])), full_version=full,
                    executable=str(executable), source=str(path),
                    sha256=hashlib.sha256(raw).hexdigest(), kind='launcher_game_version')
    except (OSError,ValueError,UnicodeError,configparser.Error):
        # Do not include config content/keys in exception text.
        raise AutomationError('客户端安装版本未核实；不使用EXE引擎版本代替。') from None


def bind_account(store, scene, run_dir, epoch, confidence=.85):
    current = account_key(scene,confidence)
    previous = store.data.get('account_key')
    if previous is None:
        if store.data['status'] == 'start_pending' and not store.data['actions']:
            previous = current
            store.data['account_source'] = 'current_start_configuration'
        else:
            # Migrate only from the original, hash-validated A8-40 entry frame.
            from .currency_wars_replay import load_sample
            from .currency_wars_standard import difficulty_page, selected_rank
            try:
                sample = Path(store.data['entry']['screenshot']).with_suffix('.sample.json').resolve(strict=True)
                if not sample.is_relative_to(store.path.parent.resolve()):
                    raise ValueError('outside evidence root')
                _, original = load_sample(sample)
                if not difficulty_page(original) or selected_rank(original) != 40:
                    raise ValueError('wrong entry rank')
                previous = account_key(original,confidence)
            except (KeyError,OSError,ValueError,AutomationError):
                raise AutomationError('旧标准对局缺少可核实的同账号入口证据，未补造身份。') from None
            store.data['account_source'] = 'verified_original_entry'
        if previous != current:
            raise AutomationError('当前账号与标准对局入口不一致，未输入或覆盖记录。')
        store.data['account_key'] = previous
    if previous != current:
        raise AutomationError('当前账号与标准对局记录不一致，未输入或覆盖记录。')
    store.data.update(account_verified_run=str(run_dir),account_verified_epoch=epoch)
    store.persist()


def refresh_client(store, executable, run_dir, epoch):
    try:
        client = installed_client(executable)
    except AutomationError:
        store.data.pop('client',None)
        store.data.pop('rules_version',None)
        store.data['client_error'] = '安装版本未核实，保持未知。'
    else:
        previous = store.data.get('client')
        if previous and (previous['version'] != client['version'] or previous['executable'] != client['executable']):
            raise AutomationError('本局客户端版本或安装目录改变，先核对当前对局。')
        client.update(verified_run=str(run_dir),input_epoch=epoch)
        store.data['client'] = client
        store.data.pop('client_error',None)
        # This certifies the transcribed economy rules only, not every route.
        if client['version'] == '4.6':
            store.data['rules_version'] = '4.6'
            store.data['rules_scope'] = ['standard_interest','refresh_price','experience_price']
        else:
            store.data.pop('rules_version',None)
    store.persist()
