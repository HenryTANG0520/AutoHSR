"""Local fake-service coverage; no paid API and no game IO."""
import json
import threading
import time
import unittest
from dataclasses import asdict, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

from autohsr.currency_wars_llm import HybridProvider, LLMSettings, chat_request, request_payload
from autohsr.currency_wars_planner import candidates
from autohsr.currency_wars_state import FactEvidence
from autohsr.models import Stopped
from autohsr.tests.test_currency_wars_planner import snapshot


KEY = 'synthetic-key-for-local-tests'


def settings(**changes):
    return replace(LLMSettings(provider='hybrid', base_url='http://127.0.0.1:12345/v1', model='fake'), **changes)


def answer(state, candidate, **changes):
    value = dict(snapshot_id=state.snapshot_id, candidate_id=candidate.candidate_id, reason='保留当前金币')
    value.update(changes)
    return json.dumps(dict(choices=[dict(finish_reason='stop', message=dict(content=json.dumps(value)))],
                           usage=dict(prompt_tokens=120, completion_tokens=30))).encode()


class LLMTests(unittest.TestCase):
    def setUp(self):
        self.secret = patch.dict('os.environ', {'AUTOHSR_LLM_API_KEY': KEY})
        self.secret.start()
        self.addCleanup(self.secret.stop)
        self.state = snapshot()
        self.choices = candidates(self.state)
        self.hold = next(c for c in self.choices if c.kind == 'hold')

    def test_default_offline_never_opens_network_even_with_credentials(self):
        transport = Mock(side_effect=AssertionError('unexpected network'))
        provider = HybridProvider(replace(settings(), provider='offline'), transport=transport)
        self.assertEqual(provider.decide(self.state).provider, 'offline')
        self.assertEqual(provider.calls, 0)
        transport.assert_not_called()

    def test_api_selects_legal_candidate_and_reports_actual_usage(self):
        transport = Mock(return_value=('ok', answer(self.state, self.hold)))
        provider = HybridProvider(settings(), transport=transport)
        decision = provider.decide(self.state)
        self.assertEqual((decision.provider, decision.candidate_id), ('api', self.hold.candidate_id))
        self.assertEqual((decision.prompt_tokens, decision.completion_tokens), (120, 30))
        self.assertFalse(decision.executable)
        transport.assert_called_once()

    def test_invalid_truncated_duplicate_and_foreign_decisions_fall_back_without_retry(self):
        malformed = json.loads(answer(self.state, self.hold))
        malformed['choices'][0]['finish_reason'] = 'length'
        duplicate = json.loads(answer(self.state, self.hold))
        duplicate['choices'][0]['message']['content'] = '{"snapshot_id":"a","snapshot_id":"b"}'
        for raw in (b'not-json', json.dumps(malformed).encode(), json.dumps(duplicate).encode(),
                    answer(self.state, self.hold, candidate_id='invented'),
                    answer(self.state, self.hold, snapshot_id='stale')):
            transport = Mock(return_value=('ok', raw))
            result = HybridProvider(settings(), transport=transport).decide(self.state)
            self.assertEqual((result.provider, result.fallback_reason), ('offline', 'invalid_response'))
            transport.assert_called_once()

    def test_error_categories_call_limit_and_auth_circuit(self):
        for code in ('rate_limited', 'http_error', 'network_error'):
            transport = Mock(return_value=(code, None))
            provider = HybridProvider(settings(max_calls=1), transport=transport)
            self.assertEqual(provider.decide(self.state).fallback_reason, code)
            self.assertEqual(provider.decide(self.state).fallback_reason, 'call_limit')
            self.assertEqual(transport.call_count, 1)
        transport = Mock(return_value=('auth_failed', None))
        provider = HybridProvider(settings(), transport=transport)
        self.assertEqual(provider.decide(self.state).fallback_reason, 'auth_failed')
        self.assertEqual(provider.decide(self.state).fallback_reason, 'api_disabled')
        transport.assert_called_once()

    def test_missing_configuration_or_only_observations_make_no_request(self):
        transport = Mock()
        self.assertEqual(HybridProvider(settings(base_url=''), transport=transport).decide(self.state).fallback_reason,
                         'missing_configuration')
        self.assertEqual(HybridProvider(settings(), transport=transport).decide(snapshot(transaction_status='pending')).provider,
                         'offline')
        transport.assert_not_called()

    def test_changed_state_and_fallback_use_fresh_facts(self):
        changed = snapshot(gold=1)
        for response in (('ok', answer(self.state, self.hold)), ('network_error', None)):
            provider = HybridProvider(settings(), transport=Mock(return_value=response))
            result = provider.decide(self.state, refresh_state=lambda: changed)
            self.assertEqual(result.snapshot_id, changed.snapshot_id)
            self.assertEqual(result.provider, 'offline')
            selected = next(c for c in candidates(changed) if c.candidate_id == result.candidate_id)
            self.assertEqual(selected.kind, 'hold')

    def test_timeout_ignores_late_result_and_does_not_launch_parallel_request(self):
        release = threading.Event()
        def slow(*args):
            release.wait(2)
            return 'ok', answer(self.state, self.hold)
        transport = Mock(side_effect=slow)
        provider = HybridProvider(settings(timeout=.05), transport=transport)
        started = time.monotonic()
        try:
            self.assertEqual(provider.decide(self.state).fallback_reason, 'timeout')
            self.assertLess(time.monotonic() - started, .4)
            self.assertEqual(provider.decide(self.state).fallback_reason, 'request_inflight')
            self.assertEqual(transport.call_count, 1)
        finally:
            release.set()
        provider._inflight.wait(1)

    def test_stop_propagates_without_offline_action(self):
        release = threading.Event()
        started = threading.Event()
        def transport(*args):
            started.set()
            release.wait(2)
            return 'ok', answer(self.state, self.hold)
        def checkpoint():
            if started.is_set():
                raise Stopped('stop')
        provider = HybridProvider(settings(), transport=transport)
        try:
            with self.assertRaises(Stopped):
                provider.decide(self.state, checkpoint=checkpoint)
        finally:
            release.set()
        provider._inflight.wait(1)

    def test_payload_excludes_evidence_paths_and_personal_field_names(self):
        state = replace(self.state, evidence=tuple(replace(e, source_id='C:/private/uid-evidence.png')
                                                  for e in self.state.evidence))
        payload = request_payload(settings(), state, candidates(state), ())
        encoded = json.dumps(payload)
        for forbidden in ('C:/private', 'uid-evidence', KEY, 'image_url', 'window_title', 'api_key'):
            self.assertNotIn(forbidden, encoded)
        self.assertFalse(payload['stream'])
        alternate = request_payload(settings(token_limit_field='max_completion_tokens'), state, candidates(state), ())
        self.assertNotIn('max_tokens', alternate)
        self.assertEqual(alternate['max_completion_tokens'], 2048)

    def test_provider_error_text_and_echoed_key_never_reach_report(self):
        def failure(*args):
            raise RuntimeError(KEY)
        result = HybridProvider(settings(), transport=failure).decide(self.state)
        self.assertNotIn(KEY, json.dumps(asdict(result)))
        response = answer(self.state, self.hold, reason=KEY)
        result = HybridProvider(settings(), transport=Mock(return_value=('ok', response))).decide(self.state)
        self.assertNotIn(KEY, json.dumps(asdict(result)))

    def test_address_validation_blocks_embedded_credentials_and_remote_plaintext(self):
        for url in ('http://example.com/v1', 'https://key:secret@example.com/v1',
                    'https://example.com/v1?key=secret', 'file:///tmp/v1', 'https://example.com/\nv1'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                settings(base_url=url)

    def test_actual_http_protocol_and_redirect_does_not_forward_credentials(self):
        captured = []
        body = answer(self.state, self.hold)
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def do_POST(self):
                captured.append((self.path, self.headers.get('Authorization'),
                                 json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                if self.path.startswith('/redirect/'):
                    self.send_response(302)
                    self.send_header('Location', '/stolen')
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            result = HybridProvider(settings(base_url=base + '/v1')).decide(self.state)
            self.assertEqual(result.provider, 'api')
            self.assertEqual(captured[0][0], '/v1/chat/completions')
            self.assertEqual(captured[0][1], 'Bearer ' + KEY)
            result = HybridProvider(settings(base_url=base + '/redirect')).decide(self.state)
            self.assertEqual(result.fallback_reason, 'redirect_refused')
            self.assertEqual(len(captured), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(1)


if __name__ == '__main__':
    unittest.main()
