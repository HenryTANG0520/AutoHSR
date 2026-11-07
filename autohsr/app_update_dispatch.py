"""App-side handoff dispatch and the installed binary's startup probe."""

import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from dataclasses import dataclass
from uuid import uuid4

from . import __version__
from .app_update import Release, UpdateError, _sha256_stream, compare_release, official_release
from .app_update_handoff import (PROTOCOL, WORKER, installed_version, process_environment, publish, read_job,
                                 read_record, startup_receipt)
from .app_update_install import _TRANSACTION, _id, _runtime
from .config import RESOURCE_ROOT, ROOT
from .storage import hold_read_sources


def _worker_command(job):
    if not getattr(sys, 'frozen', False):
        source = ROOT / 'update_launcher.py'
        if not source.is_file():
            raise UpdateError('independent_updater_missing')
        return [sys.executable, str(source), str(job)]
    source = RESOURCE_ROOT / WORKER
    if _id(source, directory=False) is None or not 0 < source.stat().st_size <= 64 * 1024 * 1024:
        raise UpdateError('independent_updater_missing')
    copy = job / WORKER
    with hold_read_sources((source,)), source.open('rb') as original, copy.open('xb') as output:
        shutil.copyfileobj(original, output)
    return [str(copy), str(job)]


def _spawn(job):
    command = _worker_command(job)
    options = dict(cwd=job, env=process_environment(), creationflags=subprocess.CREATE_NO_WINDOW,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not getattr(sys, 'frozen', False):
        return subprocess.Popen(command, **options)
    source, copy = RESOURCE_ROOT / WORKER, job / WORKER
    with hold_read_sources((source, copy)), source.open('rb') as original, copy.open('rb') as staged:
        if _sha256_stream(original) != _sha256_stream(staged):
            raise UpdateError('independent_updater_changed')
        return subprocess.Popen(command, **options)


@dataclass(frozen=True)
class UpdateCheck:
    installed: str
    release: Release
    relation: str
    can_install: bool
    previous_transaction: bool


def check_for_update(root):
    packaged = getattr(sys, 'frozen', False)
    version = installed_version(root) if packaged else __version__
    release = official_release()
    can_install = bool(packaged and _id(RESOURCE_ROOT / WORKER, directory=False) is not None)
    return UpdateCheck(version, release, compare_release(release, version), can_install,
                       os.path.lexists(root / _TRANSACTION))


def begin(root, *, restart=True, expected_release=None, cancelled=lambda: False):
    root = Path(root).resolve(strict=True)
    _runtime(root)
    if os.path.lexists(root / _TRANSACTION):
        raise UpdateError('installation_previous_transaction')
    version = installed_version(root)
    if cancelled():
        return dict(status='stopped')
    release = official_release()
    if expected_release is not None and release != expected_release:
        raise UpdateError('release_changed_after_check')
    if cancelled():
        return dict(status='stopped')
    relation = compare_release(release, version)
    if relation != 'available':
        return dict(status='success', update=relation, version=version, release=release.tag[1:])
    parent = root
    for name in ('runs', 'app-update'):
        parent = parent / name
        parent.mkdir(exist_ok=True)
        if _id(parent, directory=True) is None:
            raise UpdateError('update_handoff_unverified')
    job = parent / uuid4().hex
    job.mkdir()
    publish(job, 'request.json', dict(protocol=PROTOCOL, tag=release.tag, sha256=release.digest,
                                      restart=restart, current_version=version))
    if cancelled():
        publish(job, 'result.json', dict(status='stopped'))
        return dict(status='stopped')
    try:
        _spawn(job)
    except (OSError, UpdateError):
        publish(job, 'result.json', dict(status='failed', reason='independent_updater_not_started'))
        raise
    return dict(status='queued', job=job.name, version=version, release=release.tag[1:])


def recent_result(root):
    folder = root / 'runs' / 'app-update'
    if _id(folder, directory=True) is None:
        return None
    if folder.resolve(strict=True) != folder:
        raise UpdateError('update_handoff_unverified')
    # Use the request creation time, not the later result write time.
    requests = sorted((path for path in folder.glob('*/request.json') if path.parent.is_dir()),
                      key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in requests[:20]:
        try:
            job, _, release, _, _ = read_job(path.parent)
        except (OSError, UpdateError):
            continue
        result = job / 'result.json'
        record = read_record(result) if os.path.lexists(result) else dict(status='pending')
        return dict(version=release.tag[1:], **{name: record.get(name) for name in
                    ('status', 'desktop_restart', 'installation')})
    return None


def _updated_installation(path):
    job, root, release, restart, _ = read_job(path)
    if (not getattr(sys, 'frozen', False) or root != ROOT or RESOURCE_ROOT != root / '_internal'
            or __version__ != release.tag[1:] or installed_version(root) != __version__):
        raise UpdateError('new_runtime_unverified')
    _runtime(root)
    return job, release, restart


def probe(path):
    job, release, _ = _updated_installation(path)
    # Verify that the GUI and Python/Tk runtime import from the new installation.
    from . import gui

    gui.tk.Tcl()
    publish(job, 'probe.json', startup_receipt(job, release))


def desktop_ready_callback(path):
    job, release, restart = _updated_installation(path)
    expected = startup_receipt(job, release)
    receipt = read_record(job / 'probe.json')
    if (not restart or os.path.lexists(job / 'desktop.json')
            or type(receipt.get('protocol')) is not int or receipt != expected):
        raise UpdateError('new_desktop_unverified')

    def report(mode):
        try:
            publish(job, 'desktop.json', dict(expected, mode=mode))
        except OSError:
            # The desktop is usable even if the worker cannot collect proof.
            pass

    return report


def run(args, raw_args, parser):
    flag = '--app-update-probe' if args.app_update_probe is not None else '--app-update-handoff'
    flags = [arg.partition('=')[0] for arg in raw_args if arg.startswith('--')]
    allowed = [flag]
    if args.app_update_no_restart and flag == '--app-update-handoff':
        allowed.append('--app-update-no-restart')
    if sorted(flags) != sorted(allowed):
        parser.error('助手更新交接须单独运行，可选 --app-update-no-restart。')
    try:
        if args.app_update_probe is not None:
            probe(args.app_update_probe)
            return 0
        report = begin(args.app_update_handoff, restart=not args.app_update_no_restart)
    except KeyboardInterrupt:
        report = dict(status='stopped')
    except UpdateError as error:
        report = dict(status='failed', reason=str(error))
    except (OSError, http.client.HTTPException):
        report = dict(status='failed', reason='update_handoff_io_failed')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {'queued': 0, 'success': 0, 'failed': 1, 'stopped': 130}[report['status']]
