"""Synthetic interchange and official-response contracts; no real auth or UID."""
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from urllib.parse import parse_qs,urlsplit
from urllib.error import HTTPError

from autohsr.warp_records import WarpError,account,export,loads,merge,parse,summary
from autohsr.warp_fetch import WarpLink,WarpStopped,fetch,find_cache_link,paths_from_player_log
from autohsr.warp_service import run,write_new


LINK='https://webstatic.mihoyo.com/history?auth_appid=webview_gacha&authkey=synthetic-secret&game_biz=hkrpg_cn&lang=zh-cn&end_id=999&page=42&gacha_type=12&size=5'


def row(identity='9007199254740993001',pool='11',**extra):
    return dict(gacha_id='1001',gacha_type=pool,item_id='1000',count='1',time='2026-10-29 12:34:56',
                name='合成测试角色',item_type='角色',rank_type='5',id=identity,**extra)


def group(rows=None,**extra):
    return dict(uid='100000000',timezone=8,lang='zh-cn',list=[row()] if rows is None else rows,**extra)


def page(rows,timezone=8):
    return dict(retcode=0,data=dict(region_time_zone=timezone,
        list=[dict(value,uid='100000000',lang='zh-cn') for value in rows]))


class WarpTests(unittest.TestCase):
    def test_uigf_all_pools_multiple_accounts_and_large_numeric_ids_roundtrip(self):
        first=group([row('9','1'),row('10','2'),row('9007199254740993001','11'),row('9007199254740993002','12'),
                     row('9007199254740993003','21'),row('9007199254740993004','22')])
        second=group([]);second['uid']=200000000
        original=[first,second];copy=deepcopy(original)
        data=export(original,timestamp=1793200000)
        self.assertEqual(data['info']['version'],'v4.2');self.assertEqual(data['hkrpg'][1]['uid'],'200000000')
        result,details=parse(loads(json.dumps(data).encode()))
        self.assertEqual([r['id'] for r in result[0]['list']],['9','10','9007199254740993001','9007199254740993002','9007199254740993003','9007199254740993004'])
        self.assertEqual(result,merge(original));self.assertEqual(copy,original)
        self.assertEqual(summary(result)['records'],6);self.assertFalse(summary(result)['history_complete'])

    def test_legacy_roundtrip_and_explicit_single_account_selection(self):
        first=group([row('1','1'),row('2','12')]);second=group([]);second['uid']='200000000'
        with self.assertRaises(WarpError):export([first,second],format='srgf')
        data=export([first,second],format='srgf',selected_uid='100000000',timestamp=123)
        self.assertEqual(data['info']['srgf_version'],'v1.0');self.assertEqual(data['info']['region_time_zone'],8)
        values,details=parse(data);self.assertEqual(values,[first]);self.assertEqual(details['format'],'srgf-v1.0')
        data['info']['region_time_zone']=8.0;self.assertEqual(parse(data)[0],[first])

    def test_extended_upstream_srgf_preserves_collaboration_but_never_exports_invalid_legacy(self):
        data=export([group()],format='srgf');data['list']=[row('1','21'),row('2','22')]
        values,details=parse(data)
        self.assertIn('legacy_srgf_extended_pools',details['notes'])
        with self.assertRaises(WarpError):export(values,format='srgf')
        self.assertEqual([r['gacha_type'] for r in export(values)['hkrpg'][0]['list']],['21','22'])

    def test_old_uigf_versions_and_other_games_are_explicitly_scoped(self):
        data=export([group()]);data['hk4e']=[dict(uid='900000000',timezone=8,list=[])]
        for version in ('v4.0','v4.1','v4.2'):
            data['info']['version']=version
            values,details=parse(data);self.assertEqual(len(values),1);self.assertIn('other_games_not_imported',details['notes'])
        data['info']['version']='v4.0';data['hkrpg'][0]['list']=[row('1','21')]
        with self.assertRaises(WarpError):parse(data)
        data['info']['version']='v5.0'
        with self.assertRaises(WarpError):parse(data)

    def test_duplicate_merge_fills_missing_optional_fields_but_rejects_conflicts(self):
        left=group([row('9'),row('10')]);right=deepcopy(left)
        del left['list'][1]['name'];right['list'][1]['extension']={'source':'synthetic'}
        result=merge([left],[right]);self.assertEqual(len(result[0]['list']),2)
        self.assertEqual(result[0]['list'][1]['name'],'合成测试角色')
        self.assertEqual(result[0]['list'][1]['extension'],{'source':'synthetic'})
        right['list'][0]['item_id']='2000'
        with self.assertRaises(WarpError):merge([left],[right])

    def test_timezone_conversion_preserves_instant_and_original_source(self):
        first=group([row('1')]);second=group([row('1'),row('2')]);second['timezone']=1
        for value in second['list']:value['time']='2026-10-29 05:34:56'
        before=deepcopy(second);result=merge([first],[second])
        self.assertEqual(len(result[0]['list']),2);self.assertEqual(result[0]['list'][1]['time'],'2026-10-29 12:34:56')
        self.assertEqual(second,before)
        second['lang']='en-us'
        with self.assertRaises(WarpError):merge([first],[second])

    def test_invalid_types_dates_missing_fields_and_ambiguous_json_are_rejected(self):
        mutations=[lambda a:a.update(uid=True),lambda a:a.update(timezone='8'),lambda a:a.update(lang={}),
            lambda a:a['list'][0].update(id=9007199254740993001),lambda a:a['list'][0].update(gacha_type='301'),
            lambda a:a['list'][0].update(time='2026-02-30 01:02:03'),lambda a:a['list'][0].update(count='0'),
            lambda a:a['list'][0].update(rank_type=None),lambda a:a['list'][0].pop('item_id')]
        for change in mutations:
            value=group();change(value)
            with self.subTest(change=change),self.assertRaises(WarpError):account(value)
        for raw in ('{"info":{},"info":{}}','{"x":NaN}','{"x":Infinity}'):
            with self.assertRaises(WarpError):loads(raw)

    def test_missing_rank_or_language_is_not_invented(self):
        data=group();data.pop('lang');data['list'][0].pop('rank_type')
        values=parse(export([data]))[0]
        self.assertNotIn('lang',values[0]);self.assertNotIn('rank_type',values[0]['list'][0])
        self.assertEqual(summary(values)['pools']['11']['unknown_rank'],1)
        with self.assertRaises(WarpError):export(values,format='srgf')

    def test_link_clears_old_cursor_uses_official_endpoints_and_redacts_repr(self):
        link=WarpLink(LINK);self.assertNotIn('synthetic-secret',repr(link))
        parsed=urlsplit(link.request_url('21',1,0));query=parse_qs(parsed.query)
        self.assertEqual(parsed.netloc,'public-operation-hkrpg.mihoyo.com');self.assertTrue(parsed.path.endswith('getLdGachaLog'))
        self.assertEqual((query['gacha_type'],query['page'],query['size'],query['end_id']),(['21'],['1'],['20'],['0']))
        overseas=WarpLink(LINK.replace('hkrpg_cn','hkrpg_global'))
        self.assertEqual(urlsplit(overseas.request_url('1',1,0)).netloc,'public-operation-hkrpg-sg.hoyoverse.com')
        for value in (LINK.replace('https:','http:'),LINK.replace('webstatic.mihoyo.com','mihoyo.com.evil.test'),
                      LINK+'&authkey=other',LINK.replace('webview_gacha','unrelated'),LINK.replace('hkrpg_cn','nap_cn'),LINK+'\n'+LINK):
            with self.subTest(link=value),self.assertRaises(WarpError):WarpLink(value)

    def test_pagination_is_numeric_descending_and_exhausts_every_requested_pool(self):
        responses=iter([page([row('10','11'),row('9','11')]),page([row('8','11')]),page([]),
                        page([row('7','21')]),page([])])
        calls=[];events=[]
        def request(url):calls.append(url);return next(responses)
        values,details=fetch(WarpLink(LINK),pools=('11','21'),request=request,emit=events.append,sleep=lambda _:None)
        self.assertEqual([r['id'] for r in values[0]['list']],['7','8','9','10'])
        self.assertEqual(parse_qs(urlsplit(calls[1]).query)['end_id'],['9'])
        self.assertEqual(parse_qs(urlsplit(calls[3]).query)['end_id'],['0'])
        self.assertEqual(details,dict(pools=['11','21'],pages=5,complete=True))
        self.assertNotIn('synthetic-secret',json.dumps(events));self.assertNotIn('100000000',json.dumps(events))

    def test_empty_final_page_is_required_not_short_page_or_page_limit(self):
        request=Mock(return_value=page([row('10')]))
        with self.assertRaises(WarpError):fetch(WarpLink(LINK),pools=('11',),max_pages=1,request=request,sleep=lambda _:None)
        self.assertEqual(request.call_count,1)
        request=Mock(return_value=page([]))
        with self.assertRaises(WarpError):fetch(WarpLink(LINK),pools=('11',),request=request,sleep=lambda _:None)

    def test_response_account_language_timezone_pool_and_cursor_changes_abort(self):
        wrong_uid=page([row('9')]);wrong_uid['data']['list'][0]['uid']='200000000'
        wrong_lang=page([row('9')]);wrong_lang['data']['list'][0]['lang']='en-us'
        for second in (wrong_uid,wrong_lang,page([row('9')],1),page([row('10')]),page([row('11')]),page([row('9','12')])):
            responses=iter([page([row('10')]),second])
            with self.subTest(response=second),self.assertRaises(WarpError):
                fetch(WarpLink(LINK),pools=('11',),request=lambda _:next(responses),sleep=lambda _:None)

    def test_transport_retry_bound_and_api_error_never_expose_credentials(self):
        calls=Mock(side_effect=OSError('URL '+LINK))
        with self.assertRaises(WarpError) as result:fetch(WarpLink(LINK),pools=('11',),request=calls,sleep=lambda _:None)
        self.assertEqual(calls.call_count,3);self.assertNotIn('synthetic-secret',str(result.exception))
        for code in (-101,-1000):
            with self.assertRaises(WarpError) as result:
                fetch(WarpLink(LINK),request=lambda _:dict(retcode=code,message=LINK),sleep=lambda _:None)
            self.assertNotIn('synthetic-secret',str(result.exception))

    def test_selected_cache_latest_valid_url_and_log_paths_are_read_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=root/'webCaches/1/Cache/Cache_Data/data_2';new=root/'webCaches/2/Cache/Cache_Data/data_2'
            old.parent.mkdir(parents=True);new.parent.mkdir(parents=True)
            old.write_bytes(LINK.encode()+b'\x00');new.write_bytes(b'prefix\0'+LINK.replace('hkrpg_cn','hkrpg_global').encode()+b'\0https://evil.test/?authkey=x\0')
            os.utime(old,(1,1));os.utime(new,(2,2));before=new.read_bytes()
            link=find_cache_link(root);self.assertIn('-sg.hoyoverse.com',link.request_url('11',1,0));self.assertEqual(new.read_bytes(),before)
            log=root/'Player.log';log.write_text('D:/Game Folder/StarRail_Data/\nD:/Game Folder/StarRail_Data/\n',encoding='utf8')
            self.assertEqual(paths_from_player_log(log),(Path('D:/Game Folder/StarRail_Data/'),))

    def test_service_merges_to_new_file_preserves_inputs_and_does_not_load_game(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);a=root/'one.json';b=root/'two.json';output=root/'export.json'
            a.write_text(json.dumps(export([group([row('9')])])),encoding='utf8')
            b.write_text(json.dumps(export([group([row('10')])],format='srgf')),encoding='utf8')
            originals=(a.read_bytes(),b.read_bytes());stdout=io.StringIO()
            with patch('autohsr.config.Settings.load',side_effect=AssertionError('no config read')), \
                 patch('autohsr.warp_fetch.request_page',side_effect=AssertionError('no network')),redirect_stdout(stdout):
                self.assertEqual(main(['--warp-records','--warp-import',str(a),'--warp-import',str(b),'--warp-output',str(output)]),0)
            data=loads(output.read_bytes());self.assertEqual(len(data['hkrpg'][0]['list']),2)
            self.assertEqual((a.read_bytes(),b.read_bytes()),originals)
            self.assertNotIn('100000000',stdout.getvalue());self.assertFalse(json.loads(stdout.getvalue())['game_accessed'])

    def test_service_network_stop_or_failure_leaves_no_output_and_old_file_intact(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);url=root/'link.txt';url.write_text(LINK,encoding='utf8');output=root/'new.json'
            stopped=[False]
            def emit(event):stopped[0]=True
            with self.assertRaises(WarpStopped):run(url_file=url,output=output,pools=('11',),request=lambda _:page([row('10')]),
                                                   emit=emit,cancel=lambda:stopped[0],sleep=lambda _:None)
            self.assertFalse(output.exists());self.assertEqual(url.read_text(encoding='utf8'),LINK)
            with self.assertRaises(WarpError):run(url_file=url,output=output,pools=('11',),max_pages=1,
                                                request=lambda _:page([row('10')]),sleep=lambda _:None)
            self.assertFalse(output.exists())

    def test_publish_conflict_and_write_failure_do_not_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'out.json';path.write_bytes(b'original')
            with self.assertRaises(WarpError):write_new(path,export([group()]))
            self.assertEqual(path.read_bytes(),b'original');new=root/'other.json'
            with patch('autohsr.warp_service.os.fsync',side_effect=OSError('synthetic disk failure')),self.assertRaises(OSError):
                write_new(new,export([group()]))
            self.assertFalse(new.exists());self.assertEqual(list(root.glob('.autohsr-warp-*')),[])

    def test_cli_scope_and_public_errors_do_not_echo_auth_or_launch_gui(self):
        from autohsr.__main__ import main
        for args in (['--warp-output','out.json'],['--warp-records','--config','unused.json','--warp-output','out.json'],
                     ['--warp-records','--warp-output','out.json','--warp-pools','11']):
            with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(args)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);url=root/'link.txt';url.write_text(LINK,encoding='utf8');errors=io.StringIO()
            with patch('autohsr.warp_service.fetch',side_effect=OSError(LINK)),redirect_stderr(errors):
                self.assertEqual(main(['--warp-records','--warp-url-file',str(url),'--warp-output',str(root/'out.json')]),2)
            self.assertNotIn('synthetic-secret',errors.getvalue());self.assertFalse((root/'out.json').exists())

    def test_http_redirect_and_client_errors_stop_without_retries_or_url_leak(self):
        from autohsr.warp_fetch import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None,None,302,'redirect',{},'https://evil.test/'))
        for status in (302,401,404):
            request=Mock(side_effect=HTTPError(LINK,status,LINK,{},None))
            with self.subTest(status=status),self.assertRaises(WarpError) as error:
                fetch(WarpLink(LINK),request=request,sleep=lambda _:None)
            self.assertEqual(request.call_count,1);self.assertNotIn('synthetic-secret',str(error.exception))

    def test_service_real_pagination_merges_import_and_all_six_pools(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'input.json';url=root/'link.txt';output=root/'combined.json'
            source.write_text(json.dumps(export([group([row('100','1')])])),encoding='utf8');before=source.read_bytes()
            url.write_text(LINK,encoding='utf8');calls=[]
            def request(value):
                query=parse_qs(urlsplit(value).query);pool=query['gacha_type'][0];calls.append((pool,query['page'][0]))
                return page([row('100' if pool=='1' else str(100+int(pool)),pool)]) if query['page']==['1'] else page([])
            result=run(imports=[source],url_file=url,output=output,request=request,sleep=lambda _:None)
            values,_=parse(loads(output.read_bytes()))
            self.assertEqual(len(values[0]['list']),6);self.assertEqual(result['records'],6)
            self.assertEqual(len(calls),12);self.assertEqual(result['fetch']['pools'],['1','2','11','12','21','22'])
            self.assertEqual(source.read_bytes(),before);self.assertNotIn('synthetic-secret',output.read_text(encoding='utf8'))

    def test_stop_after_flush_cleans_unpublished_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);stopped=[False];real_fsync=os.fsync
            def sync(descriptor):real_fsync(descriptor);stopped[0]=True
            with patch('autohsr.warp_service.os.fsync',side_effect=sync),self.assertRaises(WarpStopped):
                write_new(root/'out.json',export([group()]),cancel=lambda:stopped[0])
            self.assertFalse((root/'out.json').exists());self.assertEqual(list(root.iterdir()),[])

    def test_valid_early_year_timezone_shift_and_overflow_are_explicit(self):
        a=group([]);b=group();b['timezone']=0;b['list'][0]['time']='0001-01-01 01:02:03'
        result=merge([a],[b]);self.assertEqual(result[0]['list'][0]['time'],'0001-01-01 09:02:03')
        b['list'][0]['time']='9999-12-31 23:59:59'
        with self.assertRaises(WarpError):merge([a],[b])


if __name__=='__main__':unittest.main()
