"""Opt-in redemption selection; validation never fetches or edits the game."""
from pathlib import Path


def validate_settings(settings, *, requested=False):
    from .config import SettingsError
    from .redemption_codes import from_values, validate_code
    for key in ('redemption_enabled', 'redemption_claim_mail'):
        if type(getattr(settings, key)) is not bool:
            raise SettingsError(key, '兑换码开关必须为布尔值。')
    if settings.redemption_source not in ('online', 'manual', 'file'):
        raise SettingsError('redemption_source', '兑换码来源须为 online、manual 或 file。')
    if settings.redemption_server not in ('cn', 'global'):
        raise SettingsError('redemption_server', '请选择兑换码服务器 cn 或 global。')
    if type(settings.redemption_codes) is not list:
        raise SettingsError('redemption_codes', '手动兑换码必须为字符串列表。')
    try:
        for code in settings.redemption_codes:
            validate_code(code)
        batch = from_values(settings.redemption_codes, settings.redemption_server)
    except ValueError as error:
        raise SettingsError('redemption_codes', str(error)) from error
    if (not isinstance(settings.redemption_catalog, str) or len(settings.redemption_catalog) > 4096
            or any(ord(char) < 32 for char in settings.redemption_catalog)):
        raise SettingsError('redemption_catalog', '本地兑换码表路径无效。')
    if settings.redemption_enabled or requested:
        if settings.redemption_source == 'manual' and not batch.codes:
            raise SettingsError('redemption_codes', '手动兑换需要至少一个有效兑换码。')
        if settings.redemption_source == 'file' and not settings.redemption_catalog:
            raise SettingsError('redemption_catalog', '请选择本地兑换码表。')


def resolve_batch(settings, *, cancel=None):
    from .config import RESOURCE_ROOT, ROOT
    from .redemption_codes import CodeBatch, from_values, from_file, fetch_catalog
    validate_settings(settings, requested=True)
    if cancel:
        cancel()
    if settings.redemption_source == 'manual':
        return from_values(settings.redemption_codes, settings.redemption_server)
    if settings.redemption_source == 'file':
        path = Path(settings.redemption_catalog)
        return from_file(path if path.is_absolute() else ROOT / path, settings.redemption_server)
    try:
        return fetch_catalog(settings.redemption_server, cancel=cancel)
    except (OSError, ValueError) as error:
        if cancel:
            cancel()
        fallback = from_file(RESOURCE_ROOT / 'assets/upstream/March7thAssistant/redemption_codes.json',
                             settings.redemption_server)
        # Provider exceptions may contain arbitrary response text or a local
        # path. The public explanation needs only the error class and policy.
        source = dict(fallback.source, fallback=True, online_error=type(error).__name__)
        return CodeBatch(fallback.codes, fallback.server, source, fallback.skipped)
