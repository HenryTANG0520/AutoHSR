"""Separate, explicit toolbox entry; never loads gameplay configuration."""
from pathlib import Path

from .warp_fetch import WarpStopped
from .warp_records import POOLS,WarpError


def add_arguments(mode,parser):
    mode.add_argument('--warp-records',action='store_true',help='导入／读取已有跃迁记录并导出；不启动游戏或执行跃迁')
    mode.add_argument('--warp-analysis',action='store_true',help='仅分析所选跃迁记录，输出匿名窗口统计，不生成导出文件')
    parser.add_argument('--warp-import',action='append',type=Path,help='导入SRGF或UIGF星铁JSON；可重复指定，保留原件')
    parser.add_argument('--warp-url-file',type=Path,help='本地UTF-8记录链接文件；鉴权不输出或保存')
    parser.add_argument('--warp-cache-dir',type=Path,help='明确指定StarRail_Data目录，只读其跃迁网页缓存')
    parser.add_argument('--warp-output',type=Path,help='导出必填：新JSON或.xlsx文件；不覆盖现有文件')
    parser.add_argument('--warp-format',choices=('uigf','srgf','xlsx'),help='UIGF v4.2（默认）、旧SRGF v1.0或Excel表格；旧SRGF拒绝联动池')
    parser.add_argument('--warp-uid',help='只导出该UID；多账号SRGF必须明确选择')
    parser.add_argument('--warp-pools',help='只读取指定卡池，逗号分隔1,2,11,12,21,22；默认全部')
    parser.add_argument('--warp-max-pages',type=int,help='每卡池最多1～5000页，默认1000；未到末页不输出为完整结果')


def dispatch(args,parser,raw_args):
    fields=('warp_import','warp_url_file','warp_cache_dir','warp_output','warp_format','warp_uid','warp_pools','warp_max_pages')
    if not (args.warp_records or args.warp_analysis):
        if any(getattr(args,k) is not None for k in fields):parser.error('跃迁记录选项仅用于 --warp-records。')
        return None
    allowed={'--warp-records','--warp-analysis'}|{'--'+k.replace('_','-') for k in fields}
    if any(arg.split('=',1)[0] not in allowed for arg in raw_args if arg.startswith('--')):
        parser.error('跃迁记录工具不能混用游戏任务、管理员或配置选项。')
    if args.warp_analysis and (args.warp_output is not None or args.warp_format is not None):
        parser.error('--warp-analysis 不接受导出文件或格式；生成文件使用 --warp-records。')
    if not args.warp_analysis and args.warp_output is None:parser.error('--warp-records 需要 --warp-output 新文件路径。')
    if (args.warp_pools is not None or args.warp_max_pages is not None) and args.warp_url_file is None and args.warp_cache_dir is None:
        parser.error('卡池及页数选项需要明确的链接或缓存读取来源。')
    import json
    import sys
    from .warp_service import run
    try:
        pools=args.warp_pools.split(',') if args.warp_pools is not None else POOLS
        result=run(imports=args.warp_import or (),url_file=args.warp_url_file,cache_dir=args.warp_cache_dir,
            output=args.warp_output,format=args.warp_format or 'uigf',selected_uid=args.warp_uid,
            pools=pools,max_pages=1000 if args.warp_max_pages is None else args.warp_max_pages,analysis_only=args.warp_analysis)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (KeyboardInterrupt,WarpStopped):
        result=dict(status='stopped',error='跃迁记录操作已停止；原文件保持。',game_accessed=False);code=130
    except WarpError as error:
        result=dict(status='failed',error=str(error),game_accessed=False);code=2
    except Exception:
        result=dict(status='failed',error='跃迁记录读取或写入失败；未输出为完成。',game_accessed=False);code=2
    print(json.dumps(result,ensure_ascii=False),file=sys.stderr);return code
