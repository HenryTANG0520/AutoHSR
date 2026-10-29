"""UI-neutral record import/fetch/export. No game or saved settings are touched."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .warp_records import MAX_BYTES,POOLS,WarpError,export,loads,merge,parse,summary
from .warp_fetch import checkpoint,fetch,find_cache_link,read_url_file


def write_new(path,data,*,cancel=None):
    """Publish a complete new file; an existing destination is never replaced."""
    path=Path(path)
    raw=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')
    if len(raw)>MAX_BYTES:raise WarpError('导出记录超过32 MiB上限。')
    if path.exists():raise WarpError('导出目标已存在，请选择新文件名以保留原件。')
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.autohsr-warp-',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name);stream.write(raw);stream.flush();os.fsync(stream.fileno())
        checkpoint(cancel)
        # Windows rename is exclusive even on filesystems without hard links.
        # Elsewhere, a same-directory hard link supplies no-replace semantics.
        if os.name=='nt':os.rename(temporary,path)
        else:os.link(temporary,path)
    except FileExistsError as error:raise WarpError('导出目标已被其他操作创建，未覆盖。') from error
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    return hashlib.sha256(raw).hexdigest()


def run(*,imports=(),url_file=None,cache_dir=None,output,format='uigf',selected_uid=None,
        pools=POOLS,max_pages=1000,cancel=None,emit=None,request=None,sleep=None):
    emit=emit or (lambda event:None)
    if not isinstance(imports,(tuple,list)) or len(imports)>1000:raise WarpError('最多一次导入1000份记录文件。')
    if url_file is not None and cache_dir is not None:raise WarpError('链接文件与缓存目录只能选一种读取来源。')
    if not imports and url_file is None and cache_dir is None:raise WarpError('请提供记录导入文件或明确的链接／缓存来源。')
    output=Path(output)
    if output.exists():raise WarpError('导出目标已存在，请选择新文件名。')
    inputs=[Path(p) for p in imports]
    if url_file is not None:inputs.append(Path(url_file))
    if any(p.resolve()==output.resolve() for p in inputs):raise WarpError('导出文件不能代替输入原件。')
    accounts=[];sources=[]
    for path in imports:
        checkpoint(cancel)
        with Path(path).open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        values,details=parse(loads(raw));accounts=merge(accounts,values)
        sources.append(details)
        emit(dict(type='warp_import_progress',files=len(sources),**summary(accounts)))
    fetched=None
    if url_file is not None or cache_dir is not None:
        checkpoint(cancel)
        link=read_url_file(url_file) if url_file is not None else find_cache_link(cache_dir,cancel=cancel)
        values,fetched=fetch(link,pools=pools,max_pages=max_pages,request=request,cancel=cancel,emit=emit,sleep=sleep)
        accounts=merge(accounts,values)
    checkpoint(cancel)
    data=export(accounts,format=format,selected_uid=selected_uid)
    exported,_=parse(data)
    checkpoint(cancel)
    checksum=write_new(output,data,cancel=cancel)
    result=dict(status='success',format='uigf-v4.2' if format=='uigf' else 'srgf-v1.0',
                **summary(exported),sources=sources,fetch=fetched,output_sha256=checksum)
    emit(dict(type='warp_finished',**result))
    return result
