"""Read the official launcher package feed and compare an installed StarRail client."""

import http.client
import json
import re
import time
from urllib.parse import urlencode

from .game_installation import installed_client, version_parts
from .models import AutomationError


_SOURCES = {
    'cn': ('hyp-api.mihoyo.com', 'jGHBHlcOq1', '64kMb5iAWu', 'hkrpg_cn'),
    'global': ('sg-hyp-api.hoyoverse.com', 'VYTpXlbWo8', '4ziysqXOQ8', 'hkrpg_global'),
}
CHANNELS = tuple(_SOURCES)
_TIMEOUT = 8
_LIMIT = 256 * 1024


def _fetch(channel):
    host, launcher, game, _ = _SOURCES[channel]
    query = urlencode({'launcher_id': launcher, 'game_ids[]': game})
    connection = http.client.HTTPSConnection(host, timeout=_TIMEOUT)
    deadline = time.monotonic() + _TIMEOUT
    try:
        connection.connect()
        socket = connection.sock

        def remaining():
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError()
            socket.settimeout(left)

        remaining()
        connection.request('GET', '/hyp/hyp-connect/api/getGamePackages?' + query,
                           headers={'Accept': 'application/json', 'Accept-Encoding': 'identity'})
        remaining()
        with connection.getresponse() as response:
            if response.status != 200 or response.getheader('Content-Encoding', 'identity').lower() != 'identity':
                raise ValueError('unexpected response')
            length = response.getheader('Content-Length')
            if length is not None and (not re.fullmatch(r'[0-9]{1,9}', length) or int(length) > _LIMIT):
                raise ValueError('unsupported response length')
            data = bytearray()
            while True:
                remaining()
                block = response.read1(min(65536, _LIMIT + 1 - len(data)))
                if not block:
                    if length is not None and len(data) != int(length):
                        raise ValueError('incomplete response')
                    return bytes(data)
                data.extend(block)
                if len(data) > _LIMIT:
                    raise ValueError('unsupported response length')
    finally:
        connection.close()


def _pairs(pairs):
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError('duplicate package field')
    return fields


def _constant(_):
    raise ValueError('invalid package number')


def _packages(channel, raw):
    _, _, game, biz = _SOURCES[channel]
    data = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_constant)
    if type(data['retcode']) is not int or data['retcode'] != 0:
        raise ValueError('package feed did not succeed')
    packages = data['data']['game_packages']
    if not isinstance(packages, list) or len(packages) != 1:
        raise ValueError('ambiguous package list')
    package = packages[0]
    if (package['game']['id'], package['game']['biz']) != (game, biz):
        raise ValueError('unexpected game channel')
    release = package['main']['major']['version']
    release_number = version_parts(release)
    upcoming = package['pre_download']
    major, patches = upcoming['major'], upcoming['patches']
    if not isinstance(patches, list):
        raise ValueError('invalid pre-download list')
    if major is None:
        if patches:
            raise ValueError('incomplete pre-download package')
        return release, None, package
    preload = major['version']
    if version_parts(preload) <= release_number:
        raise ValueError('pre-download version does not advance the release')
    return release, preload, package


def _package_size(entry, installed):
    """Report game archive sizes only when the complete selected list is valid."""
    patches = entry.get('patches', [])
    if not isinstance(patches, list) or any(not isinstance(item, dict) for item in patches):
        return None
    matching = [item for item in patches if item.get('version') == installed]
    if len(matching) > 1:
        return None
    selected = matching[0] if matching else entry['major']
    files = selected.get('game_pkgs')
    if not isinstance(files, list) or not 1 <= len(files) <= 128:
        return None
    sizes = []
    for item in files:
        raw_size = item.get('size') if isinstance(item, dict) else None
        if type(raw_size) not in (int, str) or not re.fullmatch(r'[1-9][0-9]{0,14}', str(raw_size)):
            return None
        sizes.append(int(raw_size))
    return dict(kind='patch' if matching else 'full', files=len(sizes), download_bytes=sum(sizes))


def check_game_update(game_path, channel):
    """Return a read-only, path-free result for the explicitly selected feed."""
    if channel not in _SOURCES:
        raise ValueError('请选择国服或国际服的官方包清单。')
    report = dict(status='failed', channel=channel, installed_version=None, release_version=None,
                  update='unknown', pre_download='unknown', pre_download_version=None)
    try:
        initial = installed_client(game_path)
    except AutomationError:
        return dict(report, reason='installation_unverified')
    report['installed_version'] = initial['full_version']
    try:
        raw = _fetch(channel)
    except (OSError, http.client.HTTPException, ValueError):
        return dict(report, reason='package_feed_unavailable')
    try:
        release, upcoming, package = _packages(channel, raw)
    except (KeyError, IndexError, TypeError, ValueError, RecursionError):
        return dict(report, reason='package_feed_unverified')
    try:
        unchanged = installed_client(game_path) == initial
    except AutomationError:
        unchanged = False
    if not unchanged:
        return dict(report, installed_version=None, reason='installation_changed')
    local, remote = version_parts(initial['full_version']), version_parts(release)
    update = 'available' if local < remote else 'current' if local == remote else 'local_ahead'
    preload = 'not_advertised'
    if upcoming is not None:
        if local >= version_parts(upcoming):
            preload = 'local_at_or_ahead'
        else:
            preload = 'advertised'
    result = dict(report, status='success', release_version=release, update=update, pre_download=preload,
                  pre_download_version=upcoming)
    for eligible, source, name in ((update == 'available', 'main', 'update_package'),
                                   (preload == 'advertised', 'pre_download', 'pre_download_package')):
        if eligible and (size := _package_size(package[source], initial['full_version'])) is not None:
            result[name] = size
    return result


def run(args, raw_args, parser):
    from .config import Settings

    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if (flags.count('--game-update-check') != 1 or len(set(flags)) != len(flags)
            or set(flags) - {'--game-update-check', '--config', '--game-path'}):
        parser.error('游戏更新核对仅可附带 --config 和 --game-path。')
    try:
        path = args.game_path
        if path is None or '--config' in flags:
            settings = Settings.load(args.config, require_existing='--config' in flags)
            path = settings.game_path if path is None else path
        report = check_game_update(path, args.game_update_check)
    except (OSError, TypeError, ValueError):
        report = dict(status='failed', channel=args.game_update_check, reason='settings_unverified')
    except KeyboardInterrupt:
        print(json.dumps(dict(status='stopped', channel=args.game_update_check), ensure_ascii=False))
        return 130
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'success' else 1
