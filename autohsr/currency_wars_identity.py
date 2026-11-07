"""Local identity/version evidence; never exported as model input."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .currency_wars_prepare import trusted
from .game_installation import installed_client
from .models import AutomationError, Scene, normalize


UID_COUNTEREVIDENCE = 'uid_counterevidence'
UID_VETO_FLOOR = .65


class AccountNotObserved(AutomationError):
    """The current frame contains no complete, trusted account candidate."""


def complete_uid(token):
    if token.within((0, .94, .23, 1)):
        return re.fullmatch(r'uid([0-9]{8,10})', normalize(token.text))
    return None


def account_key(scene, confidence=.85):
    values = [match[1] for token in trusted(scene, confidence).tokens if (match := complete_uid(token))]
    if len(values) != 1:
        failure = AccountNotObserved if not values else AutomationError
        raise failure('当前账号标识未完整核实，未沿用旧对局事实。')
    return hashlib.sha256(('autohsr-currency-account-v1:'+values[0]).encode('ascii')).hexdigest()


def checked_account_key(scene, confidence):
    """Require a strong account read, with complete weaker UIDs used only to veto."""
    low = [token for token in scene.field_reads.get(UID_COUNTEREVIDENCE, ()) if token is not None]
    candidates = Scene([*scene.tokens, *low]) if low else scene
    account_key(candidates, min(UID_VETO_FLOOR, confidence))
    return account_key(scene, max(.85, confidence))


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
