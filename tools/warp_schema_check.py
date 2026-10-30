"""Offline independent format QA using user-supplied official schemas.

Optional jsonschema is a development tool, not an application dependency.
No network, player data, caches, credentials or game access are used here.
"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema-dir',type=Path,default=root/'runs/warp-standard-source')
    parser.add_argument('--validator-dir',type=Path,help='可选：本地开发用jsonschema模块目录')
    parser.add_argument('--report',type=Path,default=root/'runs/warp-schema-verification.json')
    args=parser.parse_args()
    if args.validator_dir is not None:sys.path.insert(0,str(args.validator_dir.resolve()))
    sys.path.insert(0,str(root))
    try:import jsonschema
    except ImportError:
        parser.error('需要可选开发验证器jsonschema；本工具不会自动安装或更改应用依赖。')
    from autohsr.warp_records import LANGS,export
    reference=json.loads((root/'assets/upstream/March7thAssistant/source.json').read_text(encoding='utf8'))['warp_format_references']
    schemas={};hashes={}
    for key,name in [('uigf','uigf-4.2-schema.json'),('srgf','srgf-1.0-schema.json')]:
        path=args.schema_dir/name
        if not path.is_file():parser.error('缺少指定的官方离线Schema，来源见docs/warp-records.md。')
        raw=path.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        if digest!=reference[key+'_schema_sha256'] or blob!=reference[key+'_schema_git_blob']:
            parser.error('Schema与本次固定来源不一致，未以其他规则代替校验。')
        schemas[key]=json.loads(raw);hashes[key]=digest
        jsonschema.validators.validator_for(schemas[key]).check_schema(schemas[key])
    checks=0
    for language in sorted(LANGS):
        for timezone in (-12,-5,0,1,8,14):
            rows=[dict(gacha_id='1001',gacha_type=pool,item_id='1000',count='1',time='2026-10-29 12:34:56',
                       name='合成验证角色',item_type='角色',rank_type='5',id=str(9007199254740993001+i))
                  for i,pool in enumerate(('1','2','11','12','21','22'))]
            for format in ('uigf','srgf'):
                value=dict(uid='100000000',timezone=timezone,lang=language,list=rows if format=='uigf' else rows[:4])
                data=export([value],format=format,timestamp=1793200000)
                jsonschema.validate(data,schemas[format]);checks+=1
    data=export([value]);data['hkrpg'][0]['list'][0]['id']=123
    if not list(jsonschema.validators.validator_for(schemas['uigf'])(schemas['uigf']).iter_errors(data)):
        raise AssertionError('独立Schema未拒绝数值ID反例。')
    data=export([value],format='srgf');data['list'][0]['gacha_type']='21'
    if not list(jsonschema.validators.validator_for(schemas['srgf'])(schemas['srgf']).iter_errors(data)):
        raise AssertionError('旧Schema未拒绝联动池反例。')
    result=dict(validator='jsonschema',validator_version=importlib.metadata.version('jsonschema'),
                successful_checks=checks,negative_checks=2,game_accessed=False,
                schema_commit=reference['verification_commit'],schemas=hashes)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
