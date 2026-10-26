"""Standard shop contracts, separate from the overclock trial purchase policy."""
from .currency_wars_deployment import backend_layout
from .currency_wars_match import read_match
from .currency_wars_navigation import unique
from .currency_wars_prepare import trusted
from .models import AutomationError


def open_standard_shop(scene, session, confidence=.65):
    state = read_match(scene,confidence)
    if (not state or state.page != 'preparation' or not state.node or state.gold is None
            or state.hp is None or state.level is None):
        raise AutomationError('标准商店需要完整备战节点、金币、生命和等级。')
    collection = session.get('collection',{})
    client = session.get('client',{})
    if (session.get('status') != 'active' or not session.get('start_verified')
            or not session.get('entry',{}).get('rank_verified') or not session.get('account_key')
            or session.get('account_verified_run') != collection.get('run_dir')
            or session.get('account_verified_epoch') != collection.get('input_epoch')
            or client.get('verified_run') != collection.get('run_dir')
            or client.get('input_epoch') != collection.get('input_epoch')
            or client.get('version') != '4.6' or session.get('rules_version') != '4.6'
            or not collection.get('complete')):
        raise AutomationError('标准商店的本局、同账号、版本或完整阵容证据不足。')
    if backend_layout(scene.image)[0] != 6:
        raise AutomationError('当前后台布局不在标准普通商店范围内。')
    from .currency_wars_market import overclock_board
    if overclock_board(scene):
        raise AutomationError('当前画面显示超频标记，不能沿用标准对局记录。')
    return unique(trusted(scene,confidence),'商店',(.81,.88,.89,.95))


def close_standard_shop(scene, session, confidence=.65):
    state = read_match(scene,confidence)
    before = session.get('pre_shop_snapshot',{})
    actions = session.get('actions',[])
    if actions and actions[-1].get('action')=='close_standard_shop' and actions[-1].get('status')=='pending':
        actions = actions[:-1]  # Re-derive the same read-only proposal after its intent was persisted.
    if (not state or state.page != 'shop' or session.get('status') != 'active'
            or (state.node,state.gold,state.level) != tuple(before.get(k) for k in ('node','gold','level'))
            or before.get('hp') is None or state.hp not in (None,before['hp'])
            or not actions or actions[-1].get('action') != 'open_standard_shop'
            or actions[-1].get('status') != 'verified'):
        raise AutomationError('收起标准商店前缺少同节点、余额或已核实开店来源。')
    return unique(trusted(scene,confidence),'收起',(.81,.88,.89,.95))
