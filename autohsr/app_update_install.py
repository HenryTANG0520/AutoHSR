"""Install a verified portable runtime without moving the user's data."""

import http.client
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import shutil
import stat
from tempfile import TemporaryDirectory, mkdtemp
from zipfile import BadZipFile, ZipFile

from . import __version__
from .app_update import (UpdateError, _MAX_ARCHIVE, _sha256_stream, compare_release, official_release,
                         release_from_checksum)
from .app_update_windows import handoff_lock, install_lock, require_closed
from .storage import hold_read_sources


_EXE = 'AutoHSR.exe'
_LIB = '_internal'
_TRANSACTION = '.autohsr-update'
_ITEMS = (_EXE, _LIB)
_LIMIT = 1536 * 1024 * 1024
_INVALID_NAME = re.compile(r'[<>:"\\|?*\x00-\x1f]')
_DEVICES = {'con', 'prn', 'aux', 'nul', 'conin$', 'conout$',
            *(f'{kind}{n}' for kind in ('com', 'lpt') for n in '0123456789¹²³')}


def _id(path, *, directory):
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    regular = stat.S_ISDIR if directory else stat.S_ISREG
    if (not regular(value.st_mode) or not value.st_ino
            or getattr(value, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise UpdateError('installation_path_unverified')
    return value.st_dev, value.st_ino


def _runtime(root):
    identities = {name: _id(root / name, directory=name == _LIB) for name in _ITEMS}
    if None in identities.values() or _id(root / _LIB / 'assets', directory=True) is None:
        raise UpdateError('portable_runtime_unverified')
    with (root / _EXE).open('rb') as exe:
        if exe.read(2) != b'MZ':
            raise UpdateError('portable_runtime_unverified')
    return identities


def _archive_entries(archive):
    """Validate Windows paths before writing any selected runtime member."""
    entries, destinations, size = [], set(), 0
    listing = archive.infolist()
    if not 0 < len(listing) <= 20000:
        raise UpdateError('release_layout_unverified')
    wrapped = all(entry.filename.split('/')[0].casefold() == 'autohsr' for entry in listing)
    for entry in listing:
        parts = entry.orig_filename.removesuffix('/').split('/')
        if (any(not part or part in ('.', '..') or part.endswith(('.', ' ')) or _INVALID_NAME.search(part)
                or part.split('.')[0].rstrip().casefold() in _DEVICES for part in parts)
                or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)
                or entry.flag_bits & 1):
            raise UpdateError('release_layout_unverified')
        relative = parts[1:] if wrapped else parts
        if not relative or relative[0] not in _ITEMS:
            continue
        if ((relative[0] == _EXE and (len(relative) != 1 or entry.is_dir()))
                or (relative == [_LIB] and not entry.is_dir())):
            raise UpdateError('release_layout_unverified')
        key = '/'.join(relative).casefold()
        if key in destinations:
            raise UpdateError('release_layout_unverified')
        destinations.add(key)
        size += entry.file_size
        if size > _LIMIT:
            raise UpdateError('release_size_unverified')
        entries.append((entry, relative))
    if _EXE.casefold() not in destinations or not any(key.startswith('_internal/assets/') for key in destinations):
        raise UpdateError('release_layout_unverified')
    return entries, size


def _extract(source, destination, digest):
    path = Path(source).resolve(strict=True)
    if not path.is_file() or not 0 < path.stat().st_size <= _MAX_ARCHIVE:
        raise UpdateError('release_size_unverified')
    try:
        with hold_read_sources((path,)), path.open('rb') as stream:
            if _sha256_stream(stream) != digest:
                raise UpdateError('release_hash_mismatch')
            stream.seek(0)
            with ZipFile(stream) as archive:
                entries, size = _archive_entries(archive)
                if shutil.disk_usage(destination).free < size:
                    raise UpdateError('installation_space_insufficient')
                for entry, parts in entries:
                    target = destination.joinpath(*parts)
                    if entry.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(entry) as content, target.open('xb') as output:
                            shutil.copyfileobj(content, output, 1024 * 1024)
    except (BadZipFile, NotImplementedError, RuntimeError):
        raise UpdateError('release_layout_unverified') from None


def _moves(root, journal):
    previous, next_runtime = journal / 'previous', journal / 'next'
    return ((root / _EXE, previous / _EXE), (root / _LIB, previous / _LIB),
            (next_runtime / _LIB, root / _LIB), (next_runtime / _EXE, root / _EXE))


def _closed(root, journal):
    require_closed(root / _EXE, journal / 'previous' / _EXE, journal / 'next' / _EXE)


def _record(journal):
    for directory in (journal, journal / 'previous', journal / 'next'):
        if _id(directory, directory=True) is None:
            raise UpdateError('installation_journal_unverified')
    source = journal / 'state.json'
    if _id(source, directory=False) is None:
        raise UpdateError('installation_journal_unverified')
    try:
        with source.open('rb') as stream:
            raw = stream.read(4097)
        record = json.loads(raw) if len(raw) <= 4096 else None
        if (not isinstance(record, dict) or set(record) != {'schema', 'release', 'sha256', 'old', 'new'}
                or type(record['schema']) is not int or record['schema'] != 1
                or not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', record['release'])
                or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])):
            raise ValueError()
        for name in ('old', 'new'):
            runtime = record[name]
            if not isinstance(runtime, dict) or set(runtime) != set(_ITEMS):
                raise ValueError()
            for identity in runtime.values():
                if (not isinstance(identity, list) or len(identity) != 2
                        or any(type(number) is not int for number in identity) or identity[1] <= 0):
                    raise ValueError()
        return record
    except (ValueError, TypeError, RecursionError):
        raise UpdateError('installation_journal_unverified') from None


def _phase(root, journal, record):
    moves = _moves(root, journal)
    slots = {path for edge in moves for path in edge}
    actual = {path: _id(path, directory=path.name == _LIB) for path in slots}
    expected = dict.fromkeys(slots)
    for name in _ITEMS:
        expected[root / name] = tuple(record['old'][name])
        expected[journal / 'next' / name] = tuple(record['new'][name])
    for phase, (source, destination) in enumerate(moves, 1):
        if actual == expected:
            return phase - 1
        expected[source], expected[destination] = None, expected[source]
    if actual == expected:
        return len(moves)
    raise UpdateError('installation_layout_changed')


def _restore(root, journal, record):
    _closed(root, journal)
    moves = _moves(root, journal)
    phase = _phase(root, journal, record)
    while phase:
        source, destination = moves[phase - 1]
        destination.rename(source)
        if phase == len(moves):
            _closed(root, journal)
        phase -= 1
        if _phase(root, journal, record) != phase:
            raise UpdateError('installation_layout_changed')


def install(archive, root, release):
    journal = root / _TRANSACTION
    with install_lock(root):
        if os.path.lexists(journal):
            raise UpdateError('installation_previous_transaction')
        _closed(root, journal)
        previous = _runtime(root)
        with TemporaryDirectory(prefix='.autohsr-update-stage-', dir=root) as folder:
            stage = Path(folder)
            (stage / 'previous').mkdir()
            next_runtime = stage / 'next'
            next_runtime.mkdir()
            _extract(archive, next_runtime, release.digest)
            candidate = _runtime(next_runtime)
            with (stage / 'state.json').open('x', encoding='utf-8') as stream:
                json.dump(dict(schema=1, release=release.tag, sha256=release.digest, old=previous, new=candidate), stream)
                stream.flush()
                os.fsync(stream.fileno())
            stage.rename(journal)
        record = _record(journal)
        try:
            _closed(root, journal)
            if _phase(root, journal, record) != 0:
                raise UpdateError('installation_layout_changed')
            for index, (source, destination) in enumerate(_moves(root, journal), 1):
                source.rename(destination)
                if index == 1:
                    _closed(root, journal)
                if _phase(root, journal, record) != index:
                    raise UpdateError('installation_layout_changed')
        except (OSError, UpdateError, KeyboardInterrupt):
            try:
                _restore(root, journal, record)
            except (OSError, UpdateError):
                raise UpdateError('installation_recovery_required') from None
            raise
        return dict(installation='installed', release=record['release'], backup_retained=True)


def maintenance(root, action):
    journal = root / _TRANSACTION
    with install_lock(root):
        if not os.path.lexists(journal):
            return dict(installation='no_transaction', backup_retained=False)
        record = _record(journal)
        phase = _phase(root, journal, record)
        cleanup = {}
        if action == 'rollback':
            _restore(root, journal, record)
            phase = 0
        if action == 'accept':
            if phase not in (0, 4):
                raise UpdateError('installation_recovery_required')
            _closed(root, journal)
            if journal.resolve(strict=True) != journal or journal.parent != root:
                raise UpdateError('installation_path_unverified')
            if {child.name for child in journal.iterdir()} != {'previous', 'next', 'state.json'}:
                raise UpdateError('installation_journal_unverified')
            retired = Path(mkdtemp(prefix='.autohsr-update-discard-', dir=root))
            try:
                journal.rename(retired / 'transaction')
            except OSError:
                retired.rmdir()
                raise
            if retired.resolve(strict=True) != retired or retired.parent != root:
                raise UpdateError('installation_path_unverified')
            try:
                shutil.rmtree(retired)
            except OSError:
                cleanup['cleanup_pending'] = retired.name
        state = 'original' if phase == 0 else 'installed' if phase == 4 else 'interrupted'
        return dict(installation=state, release=record['release'], backup_retained=action != 'accept', **cleanup)


def run(args, raw_args, parser):
    choices = {
        '--app-update-install': args.app_update_install,
        '--app-update-status': args.app_update_status,
        '--app-update-rollback': args.app_update_rollback,
        '--app-update-accept': args.app_update_accept,
    }
    flag, argument = next((flag, value) for flag, value in choices.items() if value is not None)
    installing = flag == '--app-update-install'
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    install_flags = [flag, '--app-update-target']
    if args.app_update_checksum is not None:
        install_flags.append('--app-update-checksum')
    if ((installing and (sorted(flags) != sorted(install_flags) or args.app_update_target is None))
            or (not installing and flags != [flag])):
        parser.error('安装须指定暂存 ZIP 与 --app-update-target，可附带官方 --app-update-checksum。')
    try:
        root = (args.app_update_target if installing else argument).resolve(strict=True)
        if not root.is_dir():
            raise UpdateError('installation_path_unverified')
        status_only = flag == '--app-update-status'
        with nullcontext() if status_only else handoff_lock(root):
            if installing:
                if args.app_update_checksum is None:
                    release = official_release()
                else:
                    with args.app_update_checksum.open('rb') as stream:
                        raw = stream.read(1025)
                    if len(raw) > 1024:
                        raise UpdateError('release_checksum_unverified')
                    release = release_from_checksum(raw)
                if compare_release(release, __version__) == 'local_ahead':
                    raise UpdateError('release_older_than_installed')
                result = install(argument, root, release)
            else:
                result = maintenance(root, flag.rsplit('-', 1)[1])
        report = dict(status='success', **result)
    except KeyboardInterrupt:
        report = dict(status='stopped')
    except UpdateError as error:
        report = dict(status='failed', reason=str(error))
    except (OSError, http.client.HTTPException):
        report = dict(status='failed', reason='installation_io_failed')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {'success': 0, 'failed': 1, 'stopped': 130}[report['status']]
