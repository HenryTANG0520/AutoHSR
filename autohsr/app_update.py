"""Discover and stage AutoHSR's official Windows portable release."""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import http.client
import json
import os
from pathlib import Path
import re
from tempfile import mkstemp
from time import monotonic
from urllib.parse import urljoin, urlsplit
from zipfile import BadZipFile, ZipFile

from . import __version__
from .storage import hold_read_sources, remove_owned_stage


_REPOSITORY = 'https://github.com/HenryTANG0520/AutoHSR'
_LATEST = _REPOSITORY + '/releases/latest'
_TAG_PREFIX = _REPOSITORY + '/releases/tag/'
_REDIRECTS = (301, 302, 303, 307, 308)
_ASSET_HOST = 'release-assets.githubusercontent.com'
_MAX_ARCHIVE = 512 * 1024 * 1024
_CHUNK = 1024 * 1024
_VERSION = r'(?:0|[1-9][0-9]{0,3})(?:\.(?:0|[1-9][0-9]{0,3})){2}'


class UpdateError(ValueError):
    """A bounded reason suitable for a CLI or desktop receipt."""


@dataclass(frozen=True)
class Release:
    tag: str
    digest: str

    @property
    def filename(self):
        return f'AutoHSR-{self.tag}-windows-x64.zip'

    @property
    def asset(self):
        return f'{_REPOSITORY}/releases/download/{self.tag}/{self.filename}'


@contextmanager
def _response(url, deadline):
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise UpdateError('release_source_unverified') from None
    if (parsed.scheme != 'https' or parsed.netloc not in ('github.com', _ASSET_HOST)
            or parsed.fragment or not parsed.path.startswith('/') or any(c.isspace() for c in url)):
        raise UpdateError('release_source_unverified')
    left = deadline - monotonic()
    if left <= 0:
        raise TimeoutError()
    connection = http.client.HTTPSConnection(parsed.netloc, timeout=min(15, left))
    try:
        connection.connect()
        socket = connection.sock

        def remaining():
            left = deadline - monotonic()
            if left <= 0:
                raise TimeoutError()
            socket.settimeout(min(15, left))

        path = parsed.path + ('?' + parsed.query if parsed.query else '')
        remaining()
        connection.request('GET', path, headers={'Accept-Encoding': 'identity', 'User-Agent': 'AutoHSR'})
        remaining()
        with connection.getresponse() as response:
            yield response, remaining
    finally:
        connection.close()


def _body(response, remaining, limit):
    if response.status != 200 or response.getheader('Content-Encoding', 'identity').lower() != 'identity':
        raise UpdateError('release_response_unverified')
    length = response.getheader('Content-Length')
    if length is not None and (not re.fullmatch(r'[0-9]{1,10}', length) or not 0 < int(length) <= limit):
        raise UpdateError('release_size_unverified')
    count = 0
    while True:
        remaining()
        block = response.read1(min(_CHUNK, limit + 1 - count))
        if not block:
            if not count or length is not None and count != int(length):
                raise UpdateError('release_size_unverified')
            return
        count += len(block)
        if count > limit:
            raise UpdateError('release_size_unverified')
        yield block


def _asset(url, limit, timeout):
    deadline = monotonic() + timeout
    with _response(url, deadline) as (response, remaining):
        if response.status not in _REDIRECTS:
            yield from _body(response, remaining, limit)
            return
        location = response.getheader('Location')
    if not location or not location.startswith('https://' + _ASSET_HOST + '/'):
        raise UpdateError('release_source_unverified')
    with _response(location, deadline) as (response, remaining):
        yield from _body(response, remaining, limit)


def release_from_checksum(raw):
    filename = rb'AutoHSR-(v' + _VERSION.encode('ascii') + rb')-windows-x64\.zip'
    match = re.fullmatch(rb'([0-9a-fA-F]{64}) [ *]' + filename + rb'\r?\n?', raw)
    if match is None:
        raise UpdateError('release_checksum_unverified')
    return Release(match[2].decode('ascii'), match[1].decode('ascii').lower())


def official_release():
    with _response(_LATEST, monotonic() + 15) as (response, _):
        if response.status not in _REDIRECTS:
            raise UpdateError('release_tag_unverified')
        location = urljoin(_LATEST, response.getheader('Location') or '')
    match = re.fullmatch(re.escape(_TAG_PREFIX) + '(v' + _VERSION + ')', location)
    if match is None:
        raise UpdateError('release_tag_unverified')
    release = Release(match[1], '')
    raw = b''.join(_asset(release.asset + '.sha256', 1024, 15))
    verified = release_from_checksum(raw)
    if verified.tag != release.tag:
        raise UpdateError('release_checksum_unverified')
    return verified


def compare_release(release, current):
    if not re.fullmatch(_VERSION, current):
        raise UpdateError('installed_version_unverified')
    local = tuple(map(int, current.split('.')))
    latest = tuple(map(int, release.tag[1:].split('.')))
    return 'available' if latest > local else 'current' if latest == local else 'local_ahead'


def _check_archive(path):
    try:
        with ZipFile(path) as archive:
            files = {entry.filename.casefold() for entry in archive.infolist() if not entry.is_dir()}
    except (BadZipFile, OSError):
        raise UpdateError('release_archive_unverified') from None
    for prefix in ('', 'autohsr/'):
        if (prefix + 'autohsr.exe' in files and any(name.startswith(prefix + '_internal/') for name in files)):
            return
    raise UpdateError('release_archive_unverified')


def stage_release(release, destination):
    """Publish a verified ZIP at a new local path, with the current install untouched."""
    if (not re.fullmatch('v' + _VERSION, release.tag)
            or not re.fullmatch(r'[0-9a-f]{64}', release.digest)):
        raise UpdateError('release_source_unverified')
    destination = Path(destination)
    if destination.suffix.casefold() != '.zip' or not destination.name:
        raise UpdateError('stage_path_unverified')
    parent = destination.parent.resolve(strict=True)
    destination = parent / destination.name
    if not parent.is_dir() or os.path.lexists(destination):
        raise UpdateError('stage_destination_exists')
    descriptor, name = mkstemp(dir=parent, prefix='.autohsr-update-', suffix='.tmp')
    temporary, original = Path(name), None
    digest = sha256()
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            original = os.fstat(stream.fileno())
            for chunk in _asset(release.asset, _MAX_ARCHIVE, 600):
                stream.write(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if digest.hexdigest() != release.digest:
            raise UpdateError('release_hash_mismatch')
        with hold_read_sources((temporary,)):
            with temporary.open('rb') as stream:
                if not os.path.samestat(os.fstat(stream.fileno()), original):
                    raise UpdateError('stage_source_changed')
                if _sha256_stream(stream) != release.digest:
                    raise UpdateError('stage_source_changed')
            _check_archive(temporary)
            os.link(temporary, destination)
        return destination
    finally:
        if original is not None:
            remove_owned_stage(temporary, original)


def _sha256_stream(stream):
    digest = sha256()
    for chunk in iter(lambda: stream.read(_CHUNK), b''):
        digest.update(chunk)
    return digest.hexdigest()


def run(args, raw_args, parser):
    flag = '--app-update-check' if args.app_update_check else '--app-update-stage'
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    if flags != [flag]:
        parser.error('助手更新核对和暂存均须独立运行。')
    report = dict(status='failed', current_version=__version__, release_version=None)
    try:
        release = official_release()
        relation = compare_release(release, __version__)
        report.update(release_version=release.tag[1:], update=relation)
        if args.app_update_stage is not None:
            if relation == 'local_ahead':
                raise UpdateError('release_older_than_installed')
            stage_release(release, args.app_update_stage)
            report.update(staged=True, sha256=release.digest)
        report['status'] = 'success'
    except KeyboardInterrupt:
        report['status'] = 'stopped'
    except UpdateError as error:
        report['reason'] = str(error)
    except (OSError, http.client.HTTPException):
        report['reason'] = 'update_io_failed'
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {'success': 0, 'failed': 1, 'stopped': 130}[report['status']]
