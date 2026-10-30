"""Local/transport catalog tests; no live catalog download or redemption."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autohsr.models import InputInterrupted, Stopped
from autohsr.redemption_codes import (CATALOG_URLS, MAX_BYTES, MAX_ROWS, CatalogCancelled,
    CatalogFetchError, CodeBatch, CodesError, _request, fetch_catalog, from_file, from_values, validate_code)


NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)


def row(code='lowerCase7', server='cn', expires_at=None):
    return dict(server=server, expires_at=expires_at, code=code)


def encoded(rows):
    return json.dumps(rows, ensure_ascii=False).encode('utf-8')


class RedemptionCodeTests(unittest.TestCase):
    def local(self, rows, server='cn', *, now=NOW):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'catalog.json'
            path.write_bytes(encoded(rows))
            with patch('http.client.HTTPSConnection', side_effect=AssertionError('local parsing must not download')):
                return from_file(path, server, now=now)

    def test_values_preserve_original_case_and_chinese_exact_dedup(self):
        batch = from_values(['lowerCase7', 'LOWERCASE7', '恭喜发财好运来', 'lowerCase7', ' bad',
                             'bad\n', '\tbad', 'bad\x00', 'x'*65, '\ud800', 17], 'cn')
        self.assertEqual(batch.codes, ('lowerCase7', 'LOWERCASE7', '恭喜发财好运来'))
        self.assertEqual(batch.skipped[0], dict(row=3, reason='duplicate'))
        self.assertTrue(all(s['reason'] == 'invalid_code' for s in batch.skipped[1:]))
        self.assertEqual(from_values([], 'cn').codes, ())
        self.assertEqual(CodeBatch((), 'global', {}, ()).server, 'global')
        with self.assertRaises(FrozenInstanceError): batch.server = 'global'

    def test_expiry_is_aware_with_null_permanent_and_explicit_naive_utc_compatibility(self):
        batch = self.local([row('permanent'), row('naive', expires_at='2026-10-30T13:00:00'),
            row('offset', expires_at='2026-10-30T21:00:00+08:00'),
            row('equal', expires_at='2026-10-30T12:00:00Z'),
            row('past', expires_at='2026-10-29T23:00:00+00:00'),
            row('other', 'global'), row('permanent')])
        self.assertEqual(batch.codes, ('permanent', 'naive', 'offset'))
        self.assertEqual(batch.source['naive_expiry_assumed_utc'], 1)
        self.assertEqual([s['reason'] for s in batch.skipped], ['expired', 'expired', 'other_server', 'duplicate'])
        with self.assertRaises(CodesError): self.local([row()], now=datetime(2026, 10, 30))

    def test_bad_rows_and_expiry_are_retained_as_reasons_without_raw_code_or_path(self):
        batch = self.local([None, 'not-row', {}, row(server='CN'), row('white space'),
            row(expires_at='not-date'), row(expires_at='2026-02-30T00:00:00Z'),
            row(expires_at='2026-10-30'), row(expires_at='0001-01-01T00:00:00+14:00'),
            row('恭喜发财好运来')])
        self.assertEqual(batch.codes, ('恭喜发财好运来',))
        self.assertEqual([s['reason'] for s in batch.skipped], ['invalid_row']*3 +
            ['invalid_server', 'invalid_code'] + ['invalid_expiry']*4)
        summary = json.dumps(batch.public_summary(), ensure_ascii=False)
        for forbidden in ('恭喜发财好运来', 'path', 'account', 'catalog.json'):
            self.assertNotIn(forbidden, summary)

    def test_servers_and_limits_are_strict_and_whitespace_is_never_trimmed(self):
        for server in ('CN', ' cn', 'global ', None, 1):
            with self.assertRaises(CodesError): from_values([], server)
        for code in ('', 'A B', 'A\u200bB', 'A\u3000B', 'ABC\r\n', 'full-widthＡ', 'a'*65):
            with self.assertRaises(CodesError): validate_code(code)
        with self.assertRaises(CodesError): from_values((str(i) for i in range(3)), 'cn')
        with self.assertRaises(CodesError): from_values(['a']*(MAX_ROWS+1), 'cn')
        with self.assertRaises(CodesError): from_values(['a'*(MAX_BYTES+1)], 'cn')
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('invalid injection must not download')):
            with self.assertRaises(CodesError): fetch_catalog('cn', now=NOW, fetcher=False)

    def test_local_json_is_bounded_and_rejects_duplicate_keys_nonfinite_or_invalid_utf8(self):
        for raw in (b'[{"server":"cn","server":"global","code":"a","expires_at":null}]',
                    b'[NaN]', b'\xff', b'{}', b'[' + b' '*MAX_BYTES + b']'):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder)/'catalog.json'; path.write_bytes(raw)
                with self.assertRaises(CodesError): from_file(path, 'cn', now=NOW)
        with self.assertRaises(OSError) as caught:
            from_file('missing-private-file-catalog.json', 'cn', now=NOW)
        self.assertNotIn('missing-private-file', str(caught.exception))

    def test_fetch_uses_fixed_order_and_stops_at_first_valid_catalog(self):
        calls = []
        def fetcher(url, **options):
            calls.append((url, options['timeout'], options['max_bytes']))
            options['cancel']()
            if len(calls) == 1: raise OSError('private transport detail')
            if len(calls) == 2: return b'not-json'
            return encoded([row('smallCase'), row('恭喜发财好运来')])
        batch = fetch_catalog('cn', now=NOW, fetcher=fetcher)
        self.assertEqual([c[0] for c in calls], list(CATALOG_URLS[:3]))
        self.assertEqual(batch.source['source_index'], 2)
        self.assertEqual(len(batch.source['attempts']), 2)
        self.assertEqual(batch.codes, ('smallCase', '恭喜发财好运来'))
        self.assertNotIn('private transport detail', json.dumps(batch.source))

    def test_empty_valid_catalog_is_not_replaced_by_a_later_source(self):
        calls = []
        def fetcher(url, **options):
            calls.append(url)
            return b'[]'
        self.assertEqual(fetch_catalog('global', now=NOW, fetcher=fetcher).codes, ())
        self.assertEqual(calls, [CATALOG_URLS[0]])

    def test_total_failure_is_oserror_for_explicit_local_fallback(self):
        calls = []
        def fetcher(url, **options):
            calls.append(url)
            return b'x'*(options['max_bytes']+1)
        with self.assertRaises(CatalogFetchError) as caught:
            fetch_catalog('cn', now=NOW, fetcher=fetcher, max_bytes=64)
        self.assertIsInstance(caught.exception, OSError)
        self.assertEqual(calls, list(CATALOG_URLS))
        self.assertEqual(len(caught.exception.attempts), 4)
        self.assertNotIn('http', str(caught.exception))

    def test_cancel_exceptions_preserve_identity_and_never_fall_back(self):
        for exception in (Stopped('stop'), InputInterrupted('pause'), ValueError('callback cancellation')):
            calls = []
            count = [0]
            def cancel():
                count[0] += 1
                if count[0] == 2: raise exception
            def fetcher(url, **options):
                calls.append(url)
                options['cancel']()
                return b'[]'
            with self.assertRaises(type(exception)) as caught:
                fetch_catalog('cn', now=NOW, fetcher=fetcher, cancel=cancel)
            self.assertIs(caught.exception, exception)
            self.assertEqual(calls, [CATALOG_URLS[0]])
        with self.assertRaises(CatalogCancelled):
            fetch_catalog('cn', now=NOW, fetcher=lambda *a, **k: self.fail('cancelled before transport'), cancel=lambda: True)

    def test_a_transport_cannot_turn_a_swallowed_cancellation_into_success(self):
        cancellation = Stopped('stop during body read')
        calls = [0]
        def cancel():
            calls[0] += 1
            if calls[0] > 1: raise cancellation
        def fetcher(url, **options):
            try: options['cancel']()
            except Stopped: pass
            return b'[]'
        with self.assertRaises(Stopped) as caught:
            fetch_catalog('cn', now=NOW, fetcher=fetcher, cancel=cancel)
        self.assertIs(caught.exception, cancellation)

    def test_transport_rejects_redirects_compression_and_overlong_bodies(self):
        class Socket:
            def settimeout(self, value): pass
        class Response:
            status = 302
            def getheader(self, key, default=None): return default
            def close(self): pass
            def read1(self, size): return b''
        class Connection:
            sock = Socket()
            def __init__(self, *a, **k): pass
            def connect(self): pass
            def request(self, *a, **k): pass
            def getresponse(self): return response
            def close(self): pass
        response = Response()
        with patch('autohsr.redemption_codes.http.client.HTTPSConnection', Connection):
            with self.assertRaises(OSError): _request(CATALOG_URLS[0], timeout=1, max_bytes=32, cancel=None)
            response.status = 200
            response.getheader = lambda key, default=None: 'gzip' if key == 'Content-Encoding' else default
            with self.assertRaises(OSError): _request(CATALOG_URLS[0], timeout=1, max_bytes=32, cancel=None)
            response.getheader = lambda key, default=None: '100' if key == 'Content-Length' else default
            with self.assertRaises(OSError): _request(CATALOG_URLS[0], timeout=1, max_bytes=32, cancel=None)
            response.getheader = lambda key, default=None: default
            response.read1 = lambda size: b'x'*size
            with self.assertRaises(OSError): _request(CATALOG_URLS[0], timeout=1, max_bytes=32, cancel=None)
            response.read1 = lambda size: b'[]'
            with patch('autohsr.redemption_codes.time.monotonic', side_effect=[0., .1, .2, .3, 2.]):
                with self.assertRaises(OSError): _request(CATALOG_URLS[0], timeout=1, max_bytes=32, cancel=None)
        with self.assertRaises(CodesError): _request('https://example.invalid/catalog', timeout=1, max_bytes=32, cancel=None)


if __name__ == '__main__':
    unittest.main()
