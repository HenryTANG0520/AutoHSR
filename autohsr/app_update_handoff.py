"""Independent update worker and its on-disk handoff protocol."""

import http.client
import json
import os
from pathlib import Path
import re
import subprocess
from time import monotonic, sleep

from .app_update import Release, UpdateError, _VERSION, compare_release, official_release, stage_release
from .app_update_install import _EXE, _TRANSACTION, _id, install, maintenance
from .app_update_windows import handoff_lock, require_closed
from .storage import remove_owned_stage, replace_file


PROTOCOL = 1
WORKER = 'AutoHSRUpdater.exe'
_JOB_ID = re.compile(r'[0-9a-f]{32}')
_WAIT_SECONDS = 120
_DESKTOP_WAIT_SECONDS = 40


class UpdateCancelled(UpdateError):
    """The operator withdrew a queued update before installation."""


def publish(job, name, record):
    temporary = job / ('.' + name + '.tmp')
    original = None
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            original = os.fstat(stream.fileno())
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, job / name, exclusive=True)
    finally:
        if original is not None and os.path.lexists(temporary):
            remove_owned_stage(temporary, original)


def read_record(path):
    if _id(path, directory=False) is None:
        raise UpdateError('update_handoff_unverified')
    try:
        with path.open('rb') as stream:
            raw = stream.read(4097)
        value = json.loads(raw) if len(raw) <= 4096 else None
    except (ValueError, RecursionError):
        raise UpdateError('update_handoff_unverified') from None
    if not isinstance(value, dict):
        raise UpdateError('update_handoff_unverified')
    return value


def read_job(path):
    job = Path(path).absolute()
    if (not _JOB_ID.fullmatch(job.name) or job.parent.name != 'app-update'
            or job.parent.parent.name != 'runs' or job.resolve(strict=True) != job):
        raise UpdateError('update_handoff_unverified')
    for directory in (job, job.parent, job.parent.parent):
        if _id(directory, directory=True) is None:
            raise UpdateError('update_handoff_unverified')
    request = read_record(job / 'request.json')
    if (set(request) != {'protocol', 'tag', 'sha256', 'restart', 'current_version'}
            or type(request['protocol']) is not int
            or request['protocol'] != PROTOCOL or type(request['restart']) is not bool
            or type(request['tag']) is not str or not re.fullmatch('v' + _VERSION, request['tag'])
            or type(request['sha256']) is not str or not re.fullmatch(r'[0-9a-f]{64}', request['sha256'])
            or type(request['current_version']) is not str or not re.fullmatch(_VERSION, request['current_version'])):
        raise UpdateError('update_handoff_unverified')
    return job, job.parents[2], Release(request['tag'], request['sha256']), request['restart'], request['current_version']


def installed_version(root):
    marker = root / '_internal' / 'autohsr-version.txt'
    if _id(marker, directory=False) is None:
        raise UpdateError('installed_version_unverified')
    try:
        with marker.open('rb') as stream:
            version = stream.read(64).decode('ascii').strip()
    except UnicodeError:
        raise UpdateError('installed_version_unverified') from None
    if not re.fullmatch(_VERSION, version):
        raise UpdateError('installed_version_unverified')
    return version


def process_environment():
    environment = os.environ.copy()
    environment.pop('_MEIPASS2', None)
    environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return environment


def cancel_job(job):
    job, _, _, _, _ = read_job(job)
    if not os.path.lexists(job / 'cancel.json'):
        publish(job, 'cancel.json', dict(protocol=PROTOCOL, job=job.name))


def _require_requested(job):
    path = job / 'cancel.json'
    if os.path.lexists(path):
        if read_record(path) != {'protocol': PROTOCOL, 'job': job.name}:
            raise UpdateError('update_handoff_unverified')
        raise UpdateCancelled('update_cancelled')


def _wait_closed(root, *, check=lambda: None):
    deadline = monotonic() + _WAIT_SECONDS
    while True:
        check()
        try:
            require_closed(root / _EXE)
            return
        except UpdateError as error:
            if str(error) != 'installation_running':
                raise
        if monotonic() >= deadline:
            raise UpdateError('installation_close_timeout')
        sleep(.25)


def _probe(root, job, release):
    options = dict(cwd=root, env=process_environment(), creationflags=subprocess.CREATE_NO_WINDOW,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        result = subprocess.run([str(root / _EXE), '--app-update-probe', str(job)], timeout=35, **options)
        receipt = read_record(job / 'probe.json')
    except (OSError, UpdateError, subprocess.TimeoutExpired):
        raise UpdateError('new_runtime_unverified') from None
    if result.returncode != 0 or type(receipt.get('protocol')) is not int or receipt != startup_receipt(job, release):
        raise UpdateError('new_runtime_unverified')


def startup_receipt(job, release):
    return dict(protocol=PROTOCOL, job=job.name, version=release.tag[1:])


def _desktop(root, job, release):
    try:
        child = subprocess.Popen([str(root / _EXE), '--app-update-desktop', str(job)], cwd=root,
                                 env=process_environment(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return 'failed', None
    expected = startup_receipt(job, release)
    ready = job / 'desktop.json'
    deadline = monotonic() + _DESKTOP_WAIT_SECONDS
    while True:
        if os.path.lexists(ready):
            try:
                receipt = read_record(ready)
            except (OSError, UpdateError):
                return 'unverified', None
            mode = receipt.pop('mode', None)
            if type(receipt.get('protocol')) is int and receipt == expected and mode in ('window', 'admin_task'):
                return 'ready', mode
            return 'unverified', None
        if child.poll() is not None:
            return 'exited_before_ready', None
        if monotonic() >= deadline:
            return 'timeout', None
        sleep(.15)


def _apply(job, root, release, restart, current_version):
    archive = job / release.filename
    if any(os.path.lexists(job / name) for name in ('result.json', 'probe.json', 'desktop.json')):
        raise UpdateError('update_handoff_already_used')
    if os.path.lexists(root / _TRANSACTION):
        raise UpdateError('installation_previous_transaction')
    if compare_release(release, current_version) != 'available':
        raise UpdateError('release_not_newer_than_installed')
    _require_requested(job)
    if official_release() != release:
        raise UpdateError('release_changed_after_handoff')
    stage_release(release, archive)
    created = archive.lstat()
    try:
        _wait_closed(root, check=lambda: _require_requested(job))
        if installed_version(root) != current_version:
            raise UpdateError('installed_version_changed_after_handoff')
        _require_requested(job)
        install(archive, root, release)
        try:
            _probe(root, job, release)
        except (UpdateError, KeyboardInterrupt) as error:
            try:
                if maintenance(root, 'rollback')['installation'] != 'original':
                    raise UpdateError('installation_recovery_required')
            except (OSError, UpdateError):
                raise UpdateError('installation_recovery_required') from None
            if isinstance(error, KeyboardInterrupt):
                raise
            return dict(status='failed', reason='new_runtime_unverified', installation='original')
    finally:
        try:
            remove_owned_stage(archive, created)
        except OSError:
            pass
    report = dict(status='success', installation='installed', version=release.tag[1:],
                  runtime_verified=True, backup_retained=True, desktop_restart='not_requested')
    if restart:
        state, mode = _desktop(root, job, release)
        report['desktop_restart'] = state
        if state == 'ready':
            report['desktop_ready_via'] = mode
        else:
            report['status'] = 'partial'
    return report


def worker(path):
    job, root, release, restart, current_version = read_job(path)
    with handoff_lock(root):
        if os.path.lexists(job / 'result.json'):
            raise UpdateError('update_handoff_already_used')
        try:
            report = _apply(job, root, release, restart, current_version)
        except (UpdateCancelled, KeyboardInterrupt):
            report = dict(status='stopped')
        except UpdateError as error:
            report = dict(status='failed', reason=str(error))
        except (OSError, http.client.HTTPException):
            report = dict(status='failed', reason='update_handoff_io_failed')
        publish(job, 'result.json', report)
        return {'success': 0, 'partial': 1, 'failed': 1, 'stopped': 130}[report['status']]
