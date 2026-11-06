"""UI-neutral record import/fetch/export. No game or saved settings are touched."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .warp_records import MAX_BYTES, OPTIONAL, POOLS, REQUIRED, WarpError, export, loads, merge, parse, summary
from .warp_fetch import checkpoint,fetch,find_cache_link,read_url_file

_FORMATS = {'uigf': 'uigf-v4.2', 'srgf': 'srgf-v1.0', 'xlsx': 'xlsx'}
_MAX_IMPORT_FILES = 1000


def publish_new(path,writer,*,cancel=None,limit=MAX_BYTES):
    """Serialize privately, then publish once without replacing a destination."""
    path=Path(path)
    checkpoint(cancel)
    if path.exists():raise WarpError('导出目标已存在，请选择新文件名以保留原件。')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.autohsr-warp-',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name);writer(stream)
            if stream.seek(0,2)>limit:raise WarpError('导出文件超过本次格式的大小上限。')
            stream.flush();os.fsync(stream.fileno());stream.seek(0)
            digest=hashlib.sha256()
            while block:=stream.read(1024*1024):checkpoint(cancel);digest.update(block)
        checkpoint(cancel)
        # Windows rename is exclusive even on filesystems without hard links.
        # Elsewhere, a same-directory hard link supplies no-replace semantics.
        if os.name=='nt':os.rename(temporary,path)
        else:os.link(temporary,path)
    except FileExistsError as error:raise WarpError('导出目标已被其他操作创建，未覆盖。') from error
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return digest.hexdigest()


def write_new(path,data,*,cancel=None):
    raw=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
    if len(raw)>MAX_BYTES:raise WarpError('导出记录超过32 MiB上限。')
    return publish_new(path,lambda stream:stream.write(raw),cancel=cancel)


def _output_path(output, format):
    if not isinstance(format, str) or format not in _FORMATS:
        raise WarpError('记录操作或导出格式无效。')
    if output is None:
        raise WarpError('导出需要新的文件路径。')
    path = Path(output)
    if path.exists():
        raise WarpError('导出目标已存在，请选择新文件名。')
    if format == 'xlsx':
        if path.suffix.lower() != '.xlsx':
            raise WarpError('Excel导出文件应使用.xlsx扩展名。')
        from .warp_xlsx import require_engine
        require_engine()
    return path


def _fetch_source(url_file, cache_dir, *, cancel, **options):
    checkpoint(cancel)
    link = read_url_file(url_file) if url_file is not None else find_cache_link(cache_dir, cancel=cancel)
    return fetch(link, cancel=cancel, **options)


def _read_imports(imports, accounts, *, cancel, emit=None):
    sources = []
    for path in imports:
        checkpoint(cancel)
        with Path(path).open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        checkpoint(cancel)
        values, details = parse(loads(raw))
        checkpoint(cancel)
        accounts = merge(accounts, values)
        sources.append(details)
        if emit is not None:
            emit(dict(type='warp_import_progress', files=len(sources), **summary(accounts)))
    return accounts, sources


def _finish(accounts, *, cancel, output=None, format='uigf', selected_uid=None,
            include_details=False, sources=None, fetched=None):
    checkpoint(cancel)
    data = export(accounts, format='uigf' if format == 'xlsx' else format, selected_uid=selected_uid)
    exported, _ = parse(data)
    from .warp_statistics import analyze, public_statistics
    statistics = analyze(exported, history=include_details, cancel=cancel)
    checkpoint(cancel)
    result = dict(status='success', mode='analysis' if output is None else 'export', **summary(exported),
                  statistics=public_statistics(statistics), sources=sources or [], fetch=fetched)
    if output is None:
        if include_details:
            result['details'] = statistics
        return result
    if format == 'xlsx':
        from .warp_xlsx import write_new as write_workbook
        checksum = write_workbook(output, exported, cancel=cancel)
    else:
        checksum = write_new(output, data, cancel=cancel)
    result.update(format=_FORMATS[format], output_sha256=checksum)
    return result


class WarpSnapshot:
    """An acquired record window, without the link, path, or request callback."""
    __slots__ = ('_accounts', '_fetch', '_sources')

    def __init__(self, accounts, fetched, *, sources=()):
        self._accounts = accounts
        self._fetch = fetched
        self._sources = tuple(sources)

    def merge_imports(self, imports, *, cancel=None) -> 'WarpSnapshot':
        """Add explicit local records without changing this snapshot or its files."""
        paths = tuple(imports) if isinstance(imports, (list, tuple)) else ()
        if not paths:
            raise WarpError('请选择至少一份本地跃迁记录文件。')
        if len(self._sources) + len(paths) > _MAX_IMPORT_FILES:
            raise WarpError('同一快照最多累计导入1000份本地记录文件。')
        try:
            accounts, sources = _read_imports(paths, self._accounts, cancel=cancel)
        except OSError:
            raise WarpError('无法读取所选本地记录，请核对路径和权限。') from None
        checkpoint(cancel)
        return WarpSnapshot(accounts, self._fetch, sources=(*self._sources, *sources))

    def analyze(self, *, cancel=None):
        return _finish(self._accounts, cancel=cancel, include_details=True,
                       sources=deepcopy(list(self._sources)), fetched=deepcopy(self._fetch))

    def export(self, output, *, format='uigf', selected_uid=None, cancel=None):
        checkpoint(cancel)
        return _finish(self._accounts, cancel=cancel, output=_output_path(output, format), format=format,
                       selected_uid=selected_uid, sources=deepcopy(list(self._sources)), fetched=deepcopy(self._fetch))


def fetch_snapshot(*, url_file=None, cache_dir=None, cancel=None, request=None, sleep=None) -> WarpSnapshot:
    """Fetch once for a local UI. Details stay with the caller and are never events."""
    if (url_file is None) == (cache_dir is None):
        raise WarpError('请选择一个明确的链接文件或缓存目录。')
    try:
        accounts, fetched = _fetch_source(url_file, cache_dir, cancel=cancel, request=request, sleep=sleep)
    except OSError:
        raise WarpError('无法读取所选链接文件或缓存，请核对路径和权限。') from None
    # Online rows use the known record fields. Extension data from a response
    # can include request metadata and is not part of this local snapshot.
    fields = REQUIRED | OPTIONAL
    for account in accounts:
        records = account['list']
        for index, row in enumerate(records):
            if index % 256 == 0:
                checkpoint(cancel)
            records[index] = {key: value for key, value in row.items() if key in fields}
    checkpoint(cancel)
    return WarpSnapshot(accounts, {key: fetched[key] for key in ('pools', 'pages', 'complete')})


def run(*,imports=(),url_file=None,cache_dir=None,output=None,format='uigf',selected_uid=None,
        pools=POOLS,max_pages=1000,cancel=None,emit=None,request=None,sleep=None,analysis_only=False,
        include_details=False):
    emit=emit or (lambda event:None)
    if (type(analysis_only) is not bool or type(include_details) is not bool
            or not isinstance(format, str) or format not in _FORMATS):raise WarpError('记录操作或导出格式无效。')
    if include_details and (not analysis_only or url_file is not None or cache_dir is not None):
        raise WarpError('跃迁详情仅分析明确选中的本地导入文件。')
    if analysis_only and (output is not None or format!='uigf'):raise WarpError('仅分析不选择导出文件或导出格式。')
    if not analysis_only and output is None:raise WarpError('导出需要新的文件路径。')
    if not isinstance(imports,(tuple,list)) or len(imports)>_MAX_IMPORT_FILES:raise WarpError('最多一次导入1000份记录文件。')
    if url_file is not None and cache_dir is not None:raise WarpError('链接文件与缓存目录只能选一种读取来源。')
    if not imports and url_file is None and cache_dir is None:raise WarpError('请提供记录导入文件或明确的链接／缓存来源。')
    if output is not None:output=_output_path(output,format)
    inputs=[Path(p) for p in imports]
    if url_file is not None:inputs.append(Path(url_file))
    if output is not None and any(p.resolve()==output.resolve() for p in inputs):raise WarpError('导出文件不能代替输入原件。')
    accounts, sources = _read_imports(imports, (), cancel=cancel, emit=emit)
    fetched=None
    if url_file is not None or cache_dir is not None:
        values,fetched=_fetch_source(url_file,cache_dir,pools=pools,max_pages=max_pages,request=request,
                                     cancel=cancel,emit=emit,sleep=sleep)
        accounts=merge(accounts,values)
    result = _finish(accounts, cancel=cancel, output=output, format=format, selected_uid=selected_uid,
                     include_details=include_details, sources=sources, fetched=fetched)
    event = dict(result, type='warp_analysis_finished' if analysis_only else 'warp_finished')
    event.pop('details', None)
    emit(event)
    return result
