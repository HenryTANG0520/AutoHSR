"""Portable task-tree definitions and explicitly referenced local media."""

from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from struct import unpack
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile
from zlib import error as DeflateError

from .models import AutomationError, Stopped
from .screenshot_tool import MAX_BYTES as MAX_IMAGE_BYTES
from .storage import file_revision, hold_read_sources, replace_file
from .task_workflow import MAX_BYTES as MAX_WORKFLOW_BYTES, REDEMPTION_TASK, compile_recipe, execution_task, loads, read
from .workflow_audio import MAX_FILE_BYTES as MAX_AUDIO_BYTES, _local_drive


_WORKFLOW = 'workflow.json'
_MANIFEST = 'manifest.json'
_ASSET = re.compile(r'assets/[0-9]{4}\.(?:png|jpg|jpeg|wav)')
_SHA256 = re.compile(r'[0-9a-f]{64}')
_MAX_ASSETS = 256
_MAX_EXPANDED = 128 * 1024 * 1024
_MAX_MANIFEST = 128 * 1024
_MAX_INDEX = 128 * 1024
_MAX_ARCHIVE = _MAX_EXPANDED + _MAX_MANIFEST + _MAX_INDEX + 65536
_BLOCK = 1024 * 1024
_IMAGE = frozenset(('.png', '.jpg', '.jpeg'))
_AUDIO = frozenset(('.wav',))
_FIELDS = {
    'workflow_image': {'image': _IMAGE, 'template': _IMAGE},
    'workflow_text': {'image': _IMAGE},
    'workflow_game_image': {'template': _IMAGE},
    'workflow_audio': {'path': _AUDIO},
}


class BundleError(ValueError):
    """A bundle, its sources or its exclusive destination could not be verified."""


def _path(value, *, base=None, new=False):
    path = Path(value)
    if (path.drive and not path.is_absolute()) or (os.name == 'nt' and path.root and not path.drive):
        raise BundleError('请明确选择本地文件或目标目录。')
    path = (Path.cwd() if base is None else base) / path
    if len(path.parts) < 2 or (os.name == 'nt' and (
            len(path.drive) != 2 or not _local_drive(path.anchor))):
        raise BundleError('请明确选择本地文件或目标目录。')
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:], start=1):
        last = index == len(path.parts) - 1
        if part == '..' and not last:
            current = current.parent
            continue
        if part.endswith(('.', ' ')) or ':' in part or '\\' in part or PureWindowsPath(part).is_reserved():
            raise BundleError('文件或目标目录的名称无效。')
        current /= part
        if last and new:
            if os.path.lexists(current):
                raise BundleError('目标已经存在，请选择新位置。')
            return current
        metadata = current.lstat()
        expected = stat.S_ISREG if last else stat.S_ISDIR
        if not expected(metadata.st_mode) or getattr(metadata, 'st_file_attributes', 0) & (
                stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_OFFLINE):
            raise BundleError('仅支持普通本地文件和目录。')
    return current


def _references(nodes):
    for node in nodes:
        operation = execution_task(node) or {}
        task = operation.get('task')
        params = operation.get('params', {})
        if task in ('warp_analysis', 'warp_export'):
            raise BundleError('该任务流依赖跃迁记录文件，请移除对应步骤后打包。')
        if task == 'workflow_notify':
            raise BundleError('该任务流依赖本地通知方案，请移除对应步骤后打包。')
        if params.get('use_power_plan') is True:
            raise BundleError('该任务流依赖本地体力计划，请取消对应步骤的体力计划后打包。')
        if task == REDEMPTION_TASK and params['source'] != 'online':
            raise BundleError('素材包仅支持在线兑换来源，请移除手动兑换码和本地码表步骤。')
        if task == 'daily':
            if ('redemption_codes' in params or 'redemption_catalog' in params
                    or params.get('redemption_source', 'online') != 'online'):
                raise BundleError('素材包仅支持在线兑换来源，请移除手动兑换码和本地码表参数。')
            if (params.get('redemption_server', 'auto') not in ('auto', 'cn', 'global')
                    or type(params.get('redemption_claim_mail', False)) is not bool):
                raise BundleError('素材包内的在线兑换服务器或领取设置无效。')
        for key, allowed in _FIELDS.get(task, {}).items():
            yield params, key, allowed
        yield from _references(node.get('steps', ()))
        yield from _references(node.get('else_steps', ()))


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode('utf-8')


def _facts(raw):
    return {'size': len(raw), 'sha256': sha256(raw).hexdigest()}


def _copy(source, destination, limit, checkpoint):
    count, digest = 0, sha256()
    while True:
        checkpoint()
        block = source.read(min(_BLOCK, limit + 1 - count))
        if not block:
            return {'size': count, 'sha256': digest.hexdigest()}
        count += len(block)
        if count > limit:
            raise BundleError('素材包内容超过大小上限。')
        digest.update(block)
        destination.write(block)


def _verify_media(path, suffix, size, checkpoint):
    checkpoint()
    if suffix == '.wav':
        from .workflow_audio import _read_clip

        try:
            _read_clip(path, size)
        except AutomationError:
            raise BundleError('任务流包含无效或超限的 PCM WAV。') from None
        return
    from .workflow_vision import WorkflowVisionError, _read

    with path.open('rb') as stream:
        magic = stream.read(8)
    expected = b'\x89PNG\r\n\x1a\n' if suffix == '.png' else b'\xff\xd8\xff'
    if not magic.startswith(expected):
        raise BundleError('素材的实际图片格式与扩展名不符。')
    try:
        _read(path, checkpoint)
    except WorkflowVisionError:
        raise BundleError('任务流包含损坏或超限的图片。') from None


def _publish(staged, target, revisions, checkpoint):
    def ready():
        checkpoint()
        if any(file_revision(path) != revision for path, revision in revisions.items()):
            raise BundleError('素材包来源在发布前已改变。')
        checkpoint()

    try:
        replace_file(staged, target, before_replace=ready, exclusive=True)
    except FileExistsError:
        raise BundleError('目标已经存在，未覆盖原件。') from None


def _export_definition(source, checkpoint):
    recipe = compile_recipe(read(source), base_dir=source.parent)
    refs = tuple(_references(recipe.document['steps']))
    sources = {}
    for params, key, allowed in refs:
        checkpoint()
        value = Path(params[key])
        if value.suffix.lower() not in allowed:
            raise BundleError('任务流素材类型与步骤不符。')
        asset = _path(value, base=source.parent)
        if asset not in sources:
            if len(sources) == _MAX_ASSETS:
                raise BundleError('素材包最多包含 256 个素材。')
            sources[asset] = f'assets/{len(sources) + 1:04}{value.suffix.lower()}'
        params[key] = sources[asset]
    compile_recipe(recipe.document, base_dir=source.parent)
    raw = _json(recipe.document)
    if len(raw) > MAX_WORKFLOW_BYTES:
        raw = json.dumps(recipe.document, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    return raw, sources


def _write_bundle(staged, workflow, sources, revisions, checkpoint):
    facts = {_WORKFLOW: _facts(workflow)}
    with ZipFile(staged, 'x', compression=ZIP_STORED, allowZip64=False) as archive:
        archive.writestr(_WORKFLOW, workflow)
        for path, name in sources.items():
            suffix = Path(name).suffix
            size = revisions[path][2]
            limit = MAX_AUDIO_BYTES if suffix == '.wav' else MAX_IMAGE_BYTES
            if not 0 < size <= limit:
                raise BundleError('单个素材超过大小上限或为空。')
            _verify_media(path, suffix, size, checkpoint)
            with path.open('rb') as source, archive.open(name, 'w') as destination:
                facts[name] = _copy(source, destination, size, checkpoint)
            if facts[name]['size'] != size:
                raise BundleError('素材在打包期间发生变化。')
        archive.writestr(_MANIFEST, _json({'schema': 1, 'files': facts}))
    with staged.open('r+b') as stream:
        os.fsync(stream.fileno())


def export_bundle(source, target, *, checkpoint=lambda: None):
    """Publish a new bundle and return its absolute ZIP path."""
    checkpoint()
    try:
        source, target = _path(source), _path(target, new=True)
        if source.suffix.lower() != '.json' or target.suffix.lower() != '.zip':
            raise BundleError('请选择已保存的 JSON 任务流和新的 ZIP 目标。')
        with hold_read_sources((source,)):
            definition = file_revision(source)
            workflow, sources = _export_definition(source, checkpoint)
            with hold_read_sources(sources):
                revisions = {path: file_revision(path) for path in sources}
                if len(workflow) + sum(row[2] for row in revisions.values()) > _MAX_EXPANDED:
                    raise BundleError('素材包展开后最多 128 MiB。')
                revisions[source] = definition
                with TemporaryDirectory(dir=target.parent, prefix='.autohsr-bundle-') as temporary:
                    staged = Path(temporary) / 'bundle.zip'
                    _write_bundle(staged, workflow, sources, revisions, checkpoint)
                    revisions[staged] = file_revision(staged)
                    _publish(staged, target, revisions, checkpoint)
        return target
    except (BundleError, Stopped):
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        raise BundleError('任务流或引用素材缺失、不可读取，或者新 ZIP 无法发布。') from None


def _member_count(stream, size):
    # Bound zipfile's central-directory read before it creates member objects.
    if not 22 <= size <= _MAX_ARCHIVE:
        raise BundleError('ZIP 文件为空或超过大小上限。')
    stream.seek(size - 22)
    tail = stream.read(22)
    if len(tail) != 22:
        raise BundleError('ZIP 目录记录不完整。')
    magic, disk, start, count, total, length, offset, comment = unpack('<4s4H2IH', tail)
    if (magic != b'PK\x05\x06' or disk or start or comment or count != total or not 2 <= count <= _MAX_ASSETS + 2
            or not 0 < length <= _MAX_INDEX or offset + length != size - 22):
        raise BundleError('ZIP 目录记录无效、超限或不是支持的单卷素材包。')
    return count


def _index(archive, count):
    members = archive.infolist()
    if len(members) != count or min(info.header_offset for info in members) != 0:
        raise BundleError('ZIP 目录与实际文件项不符。')
    entries = {}
    for info in members:
        name = info.filename
        limit = ({_MANIFEST: _MAX_MANIFEST, _WORKFLOW: MAX_WORKFLOW_BYTES}.get(name)
                 or (MAX_AUDIO_BYTES if name.endswith('.wav') else MAX_IMAGE_BYTES))
        if (name in entries or info.orig_filename != name
                or (name not in (_MANIFEST, _WORKFLOW) and not _ASSET.fullmatch(name))
                or stat.S_IFMT(info.external_attr >> 16) not in (0, stat.S_IFREG)
                or info.external_attr & (stat.FILE_ATTRIBUTE_DIRECTORY | stat.FILE_ATTRIBUTE_REPARSE_POINT)
                or info.flag_bits & ~0x80e or info.compress_type not in (ZIP_STORED, ZIP_DEFLATED)
                or not 0 < info.file_size <= limit or not 0 < info.compress_size <= _MAX_ARCHIVE
                or (info.compress_type == ZIP_STORED and info.compress_size != info.file_size)):
            raise BundleError('ZIP 含不允许的路径、重复项、超限项或未知文件。')
        entries[name] = info
    if not {_MANIFEST, _WORKFLOW} <= entries.keys():
        raise BundleError('素材包缺少清单或任务流。')
    if sum(info.file_size for name, info in entries.items() if name != _MANIFEST) > _MAX_EXPANDED:
        raise BundleError('素材包展开后最多 128 MiB。')
    return entries


def _read_member(archive, info, checkpoint):
    output = BytesIO()
    with archive.open(info) as stream:
        facts = _copy(stream, output, info.file_size, checkpoint)
    if facts['size'] != info.file_size:
        raise BundleError('素材包文件长度与目录不符。')
    return output.getvalue(), facts


def _read_manifest(archive, entries, checkpoint):
    raw, _ = _read_member(archive, entries[_MANIFEST], checkpoint)
    manifest = loads(raw)
    if (not isinstance(manifest, dict) or set(manifest) != {'schema', 'files'}
            or type(manifest['schema']) is not int or manifest['schema'] != 1
            or not isinstance(manifest['files'], dict) or set(manifest['files']) != entries.keys() - {_MANIFEST}):
        raise BundleError('素材包清单与实际文件不符。')
    for name, row in manifest['files'].items():
        if (not isinstance(row, dict) or set(row) != {'size', 'sha256'}
                or type(row['size']) is not int or row['size'] != entries[name].file_size
                or not isinstance(row['sha256'], str) or not _SHA256.fullmatch(row['sha256'])):
            raise BundleError('素材包清单的长度或摘要无效。')
    return manifest['files']


def _stage_import(source, size, staged, checkpoint):
    revisions = {}
    with source.open('rb') as stream:
        count = _member_count(stream, size)
        with ZipFile(stream, 'r') as archive:
            entries = _index(archive, count)
            manifest = _read_manifest(archive, entries, checkpoint)
            raw, facts = _read_member(archive, entries[_WORKFLOW], checkpoint)
            if facts != manifest[_WORKFLOW]:
                raise BundleError('任务流文件的摘要与清单不符。')
            recipe = compile_recipe(loads(raw), base_dir=staged)
            names = set()
            for params, key, allowed in _references(recipe.document['steps']):
                name = params[key]
                if not _ASSET.fullmatch(name) or Path(name).suffix not in allowed:
                    raise BundleError('任务流素材须为包内的相对引用。')
                names.add(name)
            if names != manifest.keys() - {_WORKFLOW}:
                raise BundleError('素材包存在未引用的文件，或缺少任务流引用的素材。')
            if names:
                (staged / 'assets').mkdir()
            for name in sorted(names):
                target = staged / name
                with archive.open(entries[name]) as source_file, target.open('xb') as destination:
                    facts = _copy(source_file, destination, manifest[name]['size'], checkpoint)
                    if facts != manifest[name]:
                        raise BundleError('素材文件的大小或摘要与清单不符。')
                    destination.flush()
                    os.fsync(destination.fileno())
                _verify_media(target, target.suffix, facts['size'], checkpoint)
                revisions[target] = file_revision(target)
            target = staged / _WORKFLOW
            with target.open('xb') as definition:
                definition.write(raw)
                definition.flush()
                os.fsync(definition.fileno())
            revisions[target] = file_revision(target)
    return revisions


def import_bundle(bundle, destination, *, checkpoint=lambda: None):
    """Verify a bundle and publish its complete contents to a new directory."""
    checkpoint()
    try:
        if os.name != 'nt':
            raise BundleError('素材包导入需要 Windows 的排他目录发布。')
        bundle, destination = _path(bundle), _path(destination, new=True)
        if bundle.suffix.lower() != '.zip':
            raise BundleError('请选择 ZIP 素材包。')
        with hold_read_sources((bundle,)):
            revision = file_revision(bundle)
            with TemporaryDirectory(dir=destination.parent, prefix='.autohsr-bundle-') as temporary:
                staged = Path(temporary) / 'contents'
                staged.mkdir()
                revisions = _stage_import(bundle, revision[2], staged, checkpoint)
                revisions[bundle] = revision
                _publish(staged, destination, revisions, checkpoint)
        return destination / _WORKFLOW
    except (BundleError, Stopped):
        raise
    except (OSError, RuntimeError, TypeError, ValueError, EOFError, BadZipFile, DeflateError):
        raise BundleError('素材包损坏、不可读取，或者新目录无法发布。') from None
