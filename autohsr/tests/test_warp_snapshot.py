"""Remote snapshot handoff with synthetic pages and explicit temporary sources."""
import hashlib
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from urllib.parse import parse_qs, urlsplit
import unittest
from unittest.mock import Mock, patch

from autohsr.tests.test_warp_records import LINK, page, row
from autohsr.warp_fetch import WarpStopped
from autohsr.warp_records import POOLS, WarpError, loads, parse
from autohsr.warp_service import fetch_snapshot, run


class WarpSnapshotTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory(prefix='autohsr-warp-snapshot-')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.link = self.root / 'private-url.txt'
        self.link.write_text(LINK, 'utf8')
        no_network = patch('autohsr.warp_fetch.request_page', side_effect=AssertionError('offline fixture'))
        no_network.start()
        self.addCleanup(no_network.stop)

    @staticmethod
    def request_for(record):
        def reply(url):
            query = parse_qs(urlsplit(url).query)
            if query['page'] == ['1'] and query['gacha_type'] == [record['gacha_type']]:
                return page([record])
            return page([])

        return Mock(side_effect=reply)

    def snapshot(self, record=None):
        request = self.request_for(row('9') if record is None else record)
        value = fetch_snapshot(url_file=self.link, request=request, sleep=lambda _: None)
        return value, request

    def test_url_snapshot_analyzes_and_exports_without_reopening_source_or_network(self):
        raw = dict(row('9007199254740993001'), name='仅本地角色',
                   request_metadata=dict(url=LINK, authkey='synthetic-secret'))
        snapshot, request = self.snapshot(raw)
        urls = [urlsplit(call.args[0]) for call in request.call_args_list]
        self.assertEqual({url.netloc for url in urls}, {'public-operation-hkrpg.mihoyo.com'})
        self.assertEqual(len(urls), len(POOLS) + 1)
        self.assertTrue(any(url.path.endswith('getLdGachaLog') for url in urls))
        original = self.link.read_bytes()
        with self.assertRaises(WarpError):
            snapshot.export(self.link)
        self.assertEqual(self.link.read_bytes(), original)
        self.link.write_bytes(b'changed after capture')
        output = self.root / 'new.json'
        with (patch('autohsr.warp_service.read_url_file', side_effect=AssertionError('snapshot is detached')),
              patch('autohsr.warp_service.find_cache_link', side_effect=AssertionError('snapshot is detached')),
              patch('autohsr.warp_service.fetch', side_effect=AssertionError('snapshot is already fetched'))):
            analysis = snapshot.analyze()
            self.assertEqual((analysis['status'], analysis['mode'], analysis['records']), ('success', 'analysis', 1))
            self.assertEqual(analysis['fetch'], dict(pools=list(POOLS), pages=len(urls), complete=True))
            self.assertFalse(analysis['history_complete'])
            detail, = analysis.pop('details')['accounts']
            self.assertEqual(detail['uid'], '100000000')
            self.assertEqual(detail['pools']['11']['five_star_history'][0]['name'], '仅本地角色')
            self.assertEqual(set(self.root.iterdir()), {self.link})
            analysis['fetch']['pools'].clear()
            result = snapshot.export(output, selected_uid='100000000')
        self.assertEqual((result['status'], result['mode'], result['format']), ('success', 'export', 'uigf-v4.2'))
        self.assertEqual(result['fetch']['pools'], list(POOLS))
        self.assertEqual(result['output_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
        values, _ = parse(loads(output.read_bytes()))
        self.assertEqual(values[0]['list'][0]['id'], raw['id'])
        self.assertNotIn('request_metadata', values[0]['list'][0])
        for private in (LINK, 'synthetic-secret', str(self.link)):
            self.assertNotIn(private, output.read_text('utf8'))
            self.assertNotIn(private, repr(snapshot))
        for private in ('100000000', '仅本地角色', raw['id']):
            self.assertNotIn(private, json.dumps([analysis, result], ensure_ascii=False))
        self.assertEqual(request.call_count, len(urls))

    def test_cache_snapshot_reads_only_the_selected_layout_and_keeps_existing_bounds(self):
        root = self.root / 'selected'
        cache = root / 'webCaches/profile/Cache/Cache_Data/data_2'
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b'prefix\0' + LINK.replace('hkrpg_cn', 'hkrpg_global').encode() + b'\0')
        before = cache.read_bytes()
        (root / 'unrelated.txt').write_text(LINK, 'utf8')
        request = self.request_for(row('9'))
        snapshot = fetch_snapshot(cache_dir=root, request=request, sleep=lambda _: None)
        self.assertEqual(snapshot.analyze()['records'], 1)
        hosts = {urlsplit(call.args[0]).netloc for call in request.call_args_list}
        self.assertEqual(hosts, {'public-operation-hkrpg-sg.hoyoverse.com'})
        self.assertEqual(cache.read_bytes(), before)
        with patch('autohsr.warp_fetch.MAX_CACHE', len(before) - 1), self.assertRaises(WarpError):
            fetch_snapshot(cache_dir=root, request=Mock(side_effect=AssertionError('cache cap before request')))

    def test_requires_one_explicit_source_and_hides_private_file_read_errors(self):
        request = Mock(side_effect=AssertionError('invalid source before request'))
        with patch('autohsr.warp_service.read_url_file') as read, patch('autohsr.warp_service.find_cache_link') as scan:
            for sources in ({}, dict(url_file=self.link, cache_dir=self.root)):
                with self.subTest(sources=sources), self.assertRaises(WarpError):
                    fetch_snapshot(**sources, request=request)
            read.assert_not_called()
            scan.assert_not_called()
        missing = self.root / 'synthetic-private-name.txt'
        with self.assertRaises(WarpError) as caught:
            fetch_snapshot(url_file=missing, request=request)
        self.assertNotIn(missing.name, str(caught.exception))
        request.assert_not_called()

    def test_cancellation_before_source_after_request_and_before_publication(self):
        with patch('autohsr.warp_service.read_url_file') as read, self.assertRaises(WarpStopped):
            fetch_snapshot(url_file=self.link, cancel=lambda: True)
        read.assert_not_called()
        stopped = Event()

        def respond(_):
            stopped.set()
            return page([row('9', '1')])

        request = Mock(side_effect=respond)
        with self.assertRaises(WarpStopped):
            fetch_snapshot(url_file=self.link, cancel=stopped.is_set, request=request)
        request.assert_called_once()
        snapshot, acquired = self.snapshot()
        stopped.clear()
        output = self.root / 'stopped.json'
        sync = os.fsync

        def stop_after_flush(descriptor):
            sync(descriptor)
            stopped.set()

        with patch('autohsr.warp_service.os.fsync', side_effect=stop_after_flush), self.assertRaises(WarpStopped):
            snapshot.export(output, cancel=stopped.is_set)
        with self.assertRaises(WarpStopped):
            snapshot.analyze(cancel=stopped.is_set)
        self.assertEqual(list(self.root.iterdir()), [self.link])
        self.assertEqual(self.link.read_text('utf8'), LINK)
        self.assertEqual(snapshot.analyze()['records'], 1)
        self.assertEqual(acquired.call_count, len(POOLS) + 1)

    def test_formats_and_selected_account_keep_native_contract(self):
        snapshot, request = self.snapshot()
        for output, options in (
                (self.root / 'wrong.json', dict(format='xlsx')),
                (self.root / 'wrong-uid.json', dict(selected_uid='200000000')),
                (None, {}),
        ):
            with self.subTest(output=output), self.assertRaises(WarpError):
                snapshot.export(output, **options)
        self.assertEqual(list(self.root.iterdir()), [self.link])
        legacy = self.root / 'legacy.json'
        self.assertEqual(snapshot.export(legacy, format='srgf')['format'], 'srgf-v1.0')
        workbook = self.root / 'snapshot.xlsx'
        self.assertEqual(snapshot.export(workbook, format='xlsx')['format'], 'xlsx')
        self.assertEqual(workbook.read_bytes()[:2], b'PK')
        self.assertEqual(request.call_count, len(POOLS) + 1)
        collab, _ = self.snapshot(row('9', '21'))
        with self.assertRaises(WarpError):
            collab.export(self.root / 'legacy-collab.json', format='srgf')
        self.assertFalse((self.root / 'legacy-collab.json').exists())

    def test_legacy_online_analysis_emits_anonymous_summary(self):
        events = []
        request = self.request_for(dict(row('9007199254740993001'), name='仅本地角色'))
        result = run(url_file=self.link, analysis_only=True, request=request, sleep=lambda _: None, emit=events.append)
        self.assertEqual(events[-1], dict(result, type='warp_analysis_finished'))
        self.assertNotIn('details', result)
        payload = json.dumps(events, ensure_ascii=False)
        for private in ('100000000', '9007199254740993001', '仅本地角色', 'synthetic-secret', str(self.link)):
            self.assertNotIn(private, payload)


if __name__ == '__main__':
    unittest.main()
