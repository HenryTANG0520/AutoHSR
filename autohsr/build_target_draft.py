"""Publish a reviewed build-target plan only after its original report is durable."""
from contextlib import contextmanager
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import msvcrt
import os
from pathlib import Path
from uuid import uuid4

import numpy as np

from .models import AutomationError, Stopped
from .storage import file_revision, hold_read_sources


PLAN = 'power-plan.json'


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


@contextmanager
def _private_file(directory, payload):
    """Write through an exclusive Windows handle whose original name dies on close."""
    kernel = C.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = (W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE)
    create.restype = W.HANDLE
    path = directory / f'.build-target-{uuid4().hex}.tmp'
    # GENERIC_WRITE | DELETE, no sharing, CREATE_NEW, TEMPORARY | DELETE_ON_CLOSE.
    handle = create(str(path), 0x40010000, 0, None, 1, 0x04000100, None)
    if handle == W.HANDLE(-1).value:
        raise C.WinError(C.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except OSError:
        close = kernel.CloseHandle
        close.argtypes = (W.HANDLE,)
        close(handle)
        raise
    with os.fdopen(descriptor, 'wb', buffering=0) as stream:
        if stream.write(payload) != len(payload):
            raise OSError('培养草稿暂存写入不完整。')
        os.fsync(stream.fileno())
        yield path, stream


def _link(source, destination):
    try:
        os.link(source, destination)
    except FileExistsError:
        raise AutomationError(f'本次目录已有 {destination.name}，原文件保留。') from None


class DraftSource:
    """Bind one saved observation to its live capture for either read-only output."""

    def __init__(self, reader, scene):
        self.reader = reader
        self.scene = scene
        self.tokens = tuple(scene.tokens)
        self.captured_at = scene.captured_at
        self.account = reader.account
        self.shape, self.dtype = scene.image.shape, scene.image.dtype
        self.image = np.frombuffer(scene.image.tobytes(), dtype=self.dtype).reshape(self.shape)
        scene.image = self.image
        self.directory = Path(reader.ctx.report.run_dir).resolve(strict=True)
        saved = reader.ctx.evidence(scene, 'build_target_preview', with_sha256=True)
        if saved is None:
            raise AutomationError('培养目标画面未保存。')
        path, self.digest = saved
        self.path = self.directory / Path(path).name
        if Path(path).resolve(strict=True) != self.path:
            raise AutomationError('培养目标证据不在本次运行目录。')
        self.revision = file_revision(self.path)
        self.check_evidence()

    def check_evidence(self):
        if (self.path.resolve(strict=True) != self.path or file_revision(self.path) != self.revision
                or hashlib.sha256(self.path.read_bytes()).hexdigest() != self.digest):
            raise AutomationError('培养目标的原始截图已改变。')

    def guard(self):
        ctx, scene = self.reader.ctx, self.scene
        if (not self.reader._current_account(scene) or self.reader.account != self.account
                or scene.captured_at != self.captured_at or tuple(scene.tokens) != self.tokens
                or scene.image is not self.image or self.image.shape != self.shape or self.image.dtype != self.dtype):
            raise AutomationError('培养目标的原始画面或账号已改变。')
        # Account and evidence reads precede the final window and control checks.
        ctx.window.guard(self.reader.geometry)
        if ctx.window.emergency_pressed():
            raise Stopped('F10 紧急停止，培养目标证据保留待核对。')
        self.reader._require_current_capture(scene)


class BuildTargetDraft:
    def __init__(self, source, planned, material, cost):
        self.source = source
        self.payload = _json_bytes(planned)
        self.audit_saved = False
        self.metadata = dict(state='staged', mode='dry_run', count_source='manual', material=material, items=planned,
                             stamina_required=cost, sha256=hashlib.sha256(self.payload).hexdigest())

    def publish(self, directory, report_path, report_payload):
        source = self.source
        destination = directory / PLAN
        with _private_file(directory, self.payload) as (plan_path, plan):
            with _private_file(directory, report_payload) as (audit_path, audit):
                original = os.fstat(audit.fileno())
                with hold_read_sources((source.path,)):
                    source.check_evidence()
                    source.guard()
                    _link(audit_path, report_path)
                    audit.close()
            self.audit_saved = True

            with hold_read_sources((source.path, report_path)):
                source.check_evidence()
                current = report_path.stat()
                if (report_path.resolve(strict=True) != report_path
                        or (current.st_dev, current.st_ino) != (original.st_dev, original.st_ino)
                        or report_path.read_bytes() != report_payload):
                    raise AutomationError('培养草稿的原始报告已改变。')
                source.guard()
                _link(plan_path, destination)
                plan.close()


def publish_report(runner, directory, context):
    """Keep the audit truthful even when publishing the second file fails."""
    report = runner.report
    directory = directory.resolve(strict=True)
    report_path = directory / 'report.json'
    draft = getattr(context, 'build_target_draft', None)
    result = report.results[-1] if report.results else None
    ready = (draft is not None and result is not None and result.task == 'build_target_plan'
             and result.status == report.status == 'partial' and not report.error)
    report.report_saved = True
    try:
        payload = _json_bytes(report.to_dict())
        if not ready:
            with _private_file(directory, payload) as (audit_path, _):
                _link(audit_path, report_path)
            return
        draft.publish(directory, report_path, payload)
    except (OSError, AutomationError) as error:
        report.report_saved = ready and draft.audit_saved
        if not report.report_saved:
            report.report_write_error = str(error)
        report.status = 'stopped' if isinstance(error, Stopped) or report.status == 'stopped' else 'failed'
        message = '培养草稿未发布：' + str(error)
        report.error = '；'.join(filter(None, (report.error, message)))
        report.safe_next = '保留本次证据和原文件，重新核对当前材料后再生成草稿。'
        if ready:
            report.build_target['draft'] = dict(draft.metadata, state='publication_failed')
            result.status = report.status
            result.detail = message
        runner.log(message, 'warning' if report.status == 'stopped' else 'error')
        return

    report.build_target['draft'] = dict(draft.metadata, state='prepared', file=PLAN)
    result.status = 'ok'
    result.detail = f'已发布单项体力草稿，预计使用 {draft.metadata["stamina_required"]} 开拓力。'
    report.status = 'success'
    report.failure_task = ''
    report.safe_next = '可审阅草稿，并通过普通体力计划入口明确启动该副本。'


def publish_preview_report(runner, directory, context):
    report = runner.report
    observed = getattr(context, 'build_target_preview_source', None)
    report.report_saved = True
    if observed is None or report.status != 'partial' or report.error:
        runner._save_run_report(directory)
        return
    source, unverified = observed
    try:
        runner._save_run_report(directory, preview_source=source)
    except (OSError, AutomationError) as error:
        report.status = 'stopped' if isinstance(error, Stopped) else 'failed'
        report.failure_task = 'build_target_preview'
        report.error = '培养预览原件或发布未核实：' + str(error)
        report.build_target.update(preview=unverified, page_verified=False)
        result = report.results[-1]
        result.status, result.detail = report.status, report.error
        runner._save_run_report(directory)
