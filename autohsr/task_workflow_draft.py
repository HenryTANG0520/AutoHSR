"""Edit explicit local task-workflow files without owning execution."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from stat import S_ISREG

from .storage import file_revision, hold_read_sources
from .task_workflow import MAX_BYTES, Recipe, WorkflowError, compile_recipe, loads
from .warp_records import WarpError
from .warp_service import publish_new


class WorkflowSaveConflict(WorkflowError):
    """The UI can distinguish an occupied name from an uncertain readback."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def _selected_file(value) -> Path:
    try:
        path = Path(value)
    except TypeError as error:
        raise WorkflowError('请选择明确的流程文件。') from error
    if path.name in ('', '..') or (os.name == 'nt' and (':' in path.name or path.name.endswith((' ', '.')))):
        raise WorkflowError('请选择明确的流程文件。')
    directory = path.parent.resolve(strict=True)
    if not directory.is_dir():
        raise WorkflowError('流程文件的父目录须已存在。')
    return directory / path.name


def _snapshot(path: Path):
    if not S_ISREG(path.lstat().st_mode):
        raise WorkflowError('所选流程来源须为普通文件。')
    with hold_read_sources((path,)):
        if not S_ISREG(path.lstat().st_mode):
            raise WorkflowError('所选流程来源须为普通文件。')
        revision = file_revision(path)
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        if file_revision(path) != revision:
            raise WorkflowError('流程文件在读取期间改变。')
    return raw, revision


def _payload(document) -> bytes:
    raw = (json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf8')
    if len(raw) > MAX_BYTES:
        raw = json.dumps(document, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf8')
    return raw


@dataclass(frozen=True)
class SavedWorkflow:
    path: Path
    sha256: str
    recipe: Recipe


class WorkflowDraft:
    """An editable copy of one explicitly loaded, valid v1 workflow."""

    def __init__(self, source: Path, raw: bytes, revision, original: dict):
        self._source = source
        self._raw = raw
        self._revision = revision
        self._original = original
        self.document = deepcopy(original)

    @classmethod
    def load(cls, path) -> WorkflowDraft:
        source = _selected_file(path)
        raw, revision = _snapshot(source)
        recipe = compile_recipe(loads(raw), base_dir=source.parent)
        return cls(source, raw, revision, recipe.document)

    @property
    def source(self) -> Path:
        return self._source

    @property
    def dirty(self) -> bool:
        return self.document != self._original

    def source_is_current(self) -> bool:
        try:
            return _snapshot(self.source) == (self._raw, self._revision)
        except (WorkflowError, OSError):
            return False

    def validate(self, *, selected_path=None, destination=None) -> Recipe:
        base = self.source.parent if destination is None else _selected_file(destination).parent
        return compile_recipe(self.document, selected_path=selected_path, base_dir=base)

    def save_as(self, path) -> SavedWorkflow:
        destination = _selected_file(path)
        if destination == self.source:
            if not self.source_is_current():
                raise WorkflowSaveConflict('source_changed', '来源文件已改变或无法读取，请重新加载或另选新文件。')
            raise WorkflowSaveConflict('source_path', '请选择新文件名，原流程文件予以保留。')
        if os.path.lexists(destination):
            raise WorkflowSaveConflict('target_exists', '另存目标已存在，请选择新文件名。')

        # Check the full tree, even after a selected-step preview.
        recipe = compile_recipe(self.document, base_dir=destination.parent)
        raw = _payload(recipe.document)
        checked = compile_recipe(loads(raw), base_dir=destination.parent)
        if checked.document != recipe.document:
            raise WorkflowError('草稿包含无法保留的非JSON值。')
        digest = hashlib.sha256(raw).hexdigest()

        try:
            staged_digest = publish_new(destination, lambda stream: stream.write(raw), limit=MAX_BYTES)
        except WarpError as error:
            # The publisher's exclusive rename also detects a target created
            # after the earlier existence check.
            if isinstance(error.__cause__, FileExistsError) or os.path.lexists(destination):
                raise WorkflowSaveConflict('target_exists', '另存目标已被创建，请选择新文件名。') from error
            raise WorkflowError('流程文件未能发布。') from error

        try:
            saved, _ = _snapshot(destination)
            if saved != raw or staged_digest != digest:
                raise WorkflowError('发布内容与草稿字节不同。')
        except (OSError, WorkflowError) as error:
            raise WorkflowSaveConflict('readback_changed', '另存后无法核实回读，请检查目标文件并保留当前草稿。') from error
        return SavedWorkflow(destination, digest, checked)
