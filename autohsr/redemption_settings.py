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
    if settings.redemption_server not in ('cn', 'global', 'auto'):
        raise SettingsError('redemption_server', '请选择兑换码服务器 cn、global 或 auto。')
    if type(settings.redemption_codes) is not list:
        raise SettingsError('redemption_codes', '手动兑换码必须为字符串列表。')
    try:
        for code in settings.redemption_codes:
            validate_code(code)
        # This is syntax validation only; auto is resolved by a live Native
        # Context, never by saving settings, previews or workflow compilation.
        batch = from_values(settings.redemption_codes, 'cn' if settings.redemption_server == 'auto' else settings.redemption_server)
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


def resolve_batch(settings, *, cancel=None, server_resolution=None):
    from .config import RESOURCE_ROOT, ROOT
    from .redemption_codes import CodeBatch, from_values, from_file, fetch_catalog
    validate_settings(settings, requested=True)
    server = settings.redemption_server
    if server == 'auto':
        from .config import SettingsError
        from .redemption_server import ServerResolution
        if not isinstance(server_resolution, ServerResolution):
            raise SettingsError('redemption_server', 'auto需要本次原生窗口的已核实服务器来源。')
        server = server_resolution.server
    def selected(batch):
        if server_resolution is None or settings.redemption_server != 'auto':
            return batch
        return CodeBatch(batch.codes, batch.server,
            dict(batch.source, server_selection='auto', server_resolution=server_resolution.to_dict()), batch.skipped)
    if cancel:
        cancel()
    if settings.redemption_source == 'manual':
        return selected(from_values(settings.redemption_codes, server))
    if settings.redemption_source == 'file':
        path = Path(settings.redemption_catalog)
        return selected(from_file(path if path.is_absolute() else ROOT / path, server))
    try:
        return selected(fetch_catalog(server, cancel=cancel))
    except (OSError, ValueError) as error:
        if cancel:
            cancel()
        fallback = from_file(RESOURCE_ROOT / 'assets/upstream/March7thAssistant/redemption_codes.json',
                             server)
        # Provider exceptions may contain arbitrary response text or a local
        # path. The public explanation needs only the error class and policy.
        source = dict(fallback.source, fallback=True, online_error=type(error).__name__)
        return selected(CodeBatch(fallback.codes, fallback.server, source, fallback.skipped))
