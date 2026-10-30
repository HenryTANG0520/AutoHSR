"""Temporary PNG/ledger contracts; no UI, input, real accounts or redemption."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from threading import Event, Thread
import unittest
from unittest.mock import patch

from PIL import Image

from autohsr.redemption_store import RedemptionStore, RedemptionStoreError, TERMINAL_STATUSES


ACCOUNT = 'a'*64
OTHER = 'b'*64


class RedemptionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = self.root/'run'; self.run.mkdir()
        self.before = self.png('before.png')
        self.one = self.png('result-one.png')
        self.two = self.png('result-two.png')
        self.store = RedemptionStore(self.root/'receipts.json')

    def png(self, name, *, root=None):
        path = (root or self.run)/name
        Image.new('RGB', (24, 20), 'gray').save(path)
        return path

    def claim(self, code='lowerCase7', account=ACCOUNT, server='cn'):
        return self.store.claim(account, server, code, run_dir=self.run, epoch=0,
            evidence=str(self.before), basis={'page': 'redemption_form', 'code_echo_verified': True})

    def finish(self, entry, status='redeemed'):
        return self.store.finish(entry['id'], status, evidence=[str(self.one), str(self.two)],
            basis={'page': 'redemption_result', 'state': status, 'two_captures_verified': True})

    def test_claim_is_durable_and_actual_disk_is_rechecked_before_confirmation(self):
        entry = self.claim('恭喜发财好运来')
        self.assertEqual(entry['code'], '恭喜发财好运来')
        loaded = RedemptionStore(self.store.path).require_pending(entry['id'], ACCOUNT, 'cn', entry['code'], 0)
        self.assertEqual(loaded, entry)
        self.assertEqual(loaded['status'], 'pending')
        disk = json.loads(self.store.path.read_text(encoding='utf-8'))
        disk['entries'][0]['epoch'] = 1
        self.store.path.write_text(json.dumps(disk), encoding='utf-8')
        frozen = self.store.path.read_bytes()
        with self.assertRaises(RedemptionStoreError):
            self.store.require_pending(entry['id'], ACCOUNT, 'cn', entry['code'], 0)
        self.assertEqual(self.store.path.read_bytes(), frozen)

    def test_account_server_and_original_case_are_separate_scopes(self):
        entries = [self.claim(), self.claim(account=OTHER), self.claim(server='global'), self.claim('LOWERCASE7')]
        self.assertEqual(len({e['id'] for e in entries}), 4)
        for entry in entries:
            self.assertEqual(self.store.lookup(entry['account_key'], entry['server'], entry['code']), entry)
        self.assertIsNone(self.store.lookup(ACCOUNT, 'cn', 'lowercase7'))

    def test_every_terminal_is_reused_across_instances_without_repeat_claim_or_overwrite(self):
        for status in sorted(TERMINAL_STATUSES):
            entry = self.claim('code'+status.replace('_', ''))
            final = self.finish(entry, status)
            self.assertEqual(RedemptionStore(self.store.path).lookup(ACCOUNT, 'cn', entry['code']), final)
            original = self.store.path.read_bytes()
            self.assertEqual(self.finish(entry, status), final)
            self.assertEqual(self.store.path.read_bytes(), original)
            with self.assertRaises(RedemptionStoreError): self.claim(entry['code'])
            with self.assertRaises(RedemptionStoreError):
                self.store.require_pending(entry['id'], ACCOUNT, 'cn', entry['code'], 0)
            with self.assertRaises(RedemptionStoreError): self.finish(entry, 'unknown')
            self.assertEqual(self.store.path.read_bytes(), original)

    def test_pending_and_unknown_cannot_be_claimed_or_reconciled_as_terminal(self):
        entry = self.claim()
        before = self.store.path.read_bytes()
        with self.assertRaises(RedemptionStoreError): self.claim()
        self.assertEqual(self.store.path.read_bytes(), before)
        unknown = self.store.finish(entry['id'], 'unknown', evidence=str(self.one), basis={'reason': 'unverified_feedback'})
        self.assertEqual(unknown['status'], 'unknown')
        original = self.store.path.read_bytes()
        with self.assertRaises(RedemptionStoreError): self.claim()
        with self.assertRaises(RedemptionStoreError): self.finish(entry)
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_terminal_requires_two_distinct_files_and_supported_status(self):
        entry = self.claim()
        original = self.store.path.read_bytes()
        for evidence in (str(self.one), [str(self.one), str(self.one)], [str(self.one)]*5):
            with self.assertRaises(RedemptionStoreError):
                self.store.finish(entry['id'], 'redeemed', evidence=evidence, basis={'page': 'result'})
        for status in ('success', 'pending', 'failed', True):
            with self.assertRaises(RedemptionStoreError):
                self.store.finish(entry['id'], status, evidence=[self.one, self.two], basis={'page': 'result'})
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_scope_and_epoch_must_match_and_evidence_is_immutable(self):
        entry = self.claim()
        for args in ((entry['id'], OTHER, 'cn', entry['code'], 0),
                     (entry['id'], ACCOUNT, 'global', entry['code'], 0),
                     (entry['id'], ACCOUNT, 'cn', 'LOWERCASE7', 0),
                     (entry['id'], ACCOUNT, 'cn', entry['code'], 1),
                     (entry['id'], ACCOUNT, 'cn', entry['code'], False),
                     ('c'*32, ACCOUNT, 'cn', entry['code'], 0)):
            with self.assertRaises(RedemptionStoreError): self.store.require_pending(*args)
        Image.new('RGB', (24, 20), 'red').save(self.before)
        original = self.store.path.read_bytes()
        with self.assertRaises(RedemptionStoreError): self.store.lookup(ACCOUNT, 'cn', entry['code'])
        with self.assertRaises(RedemptionStoreError): self.finish(entry)
        self.assertEqual(self.store.path.read_bytes(), original)

    def test_evidence_outside_run_and_invalid_basis_or_code_never_create_an_intent(self):
        outside = self.png('outside.png', root=self.root)
        for evidence, basis, epoch, code in ((outside, {'page': 'form'}, 0, 'code'),
                (self.before, {}, 0, 'code'), (self.before, {'bad': float('nan')}, 0, 'code'),
                (self.before, {'page': 'form'}, False, 'code'), (self.before, {'page': 'form'}, 0, 'bad code')):
            with self.assertRaises(RedemptionStoreError):
                self.store.claim(ACCOUNT, 'cn', code, run_dir=self.run, epoch=epoch, evidence=evidence, basis=basis)
            self.assertFalse(self.store.path.exists())
        entry = self.claim()
        with self.assertRaises(RedemptionStoreError):
            self.store.finish(entry['id'], 'redeemed', evidence=[outside, self.two], basis={'page': 'result'})

    def test_atomic_failure_before_publish_does_not_authorize_input_or_change_old_receipts(self):
        first = self.claim('first')
        original = self.store.path.read_bytes()
        with patch('autohsr.redemption_store.replace_file', side_effect=OSError('private failure path')):
            with self.assertRaises(RedemptionStoreError) as caught: self.claim('second')
        self.assertNotIn('private failure path', str(caught.exception))
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.store.lookup(ACCOUNT, 'cn', 'first'), first)
        self.assertIsNone(self.store.lookup(ACCOUNT, 'cn', 'second'))
        self.assertTrue(list(self.root.glob('*.pending')))

    def test_unknown_publication_outcome_leaves_pending_and_never_replays(self):
        def publish_then_fail(source, destination):
            Path(source).replace(destination)
            raise OSError('outcome uncertain')
        with patch('autohsr.redemption_store.replace_file', side_effect=publish_then_fail):
            with self.assertRaises(RedemptionStoreError): self.claim()
        observed = self.store.lookup(ACCOUNT, 'cn', 'lowerCase7')
        self.assertEqual(observed['status'], 'pending')
        with self.assertRaises(RedemptionStoreError): self.claim()

    def test_terminal_write_failure_preserves_the_original_pending_claim(self):
        entry = self.claim()
        original = self.store.path.read_bytes()
        with patch('autohsr.redemption_store.replace_file', side_effect=OSError('cannot publish result')):
            with self.assertRaises(RedemptionStoreError): self.finish(entry)
        self.assertEqual(self.store.path.read_bytes(), original)
        self.assertEqual(self.store.lookup(ACCOUNT, 'cn', entry['code']), entry)
        with self.assertRaises(RedemptionStoreError): self.claim()

    def test_concurrent_store_cannot_overwrite_an_inflight_intent(self):
        entered, release = Event(), Event()
        results = []
        def hold_publication(source, destination):
            entered.set()
            if not release.wait(3): raise RuntimeError('test release timeout')
            Path(source).replace(destination)
        def first():
            try: results.append(self.claim())
            except Exception as error: results.append(error)
        with patch('autohsr.redemption_store.replace_file', side_effect=hold_publication):
            thread = Thread(target=first)
            thread.start()
            try:
                self.assertTrue(entered.wait(3))
                with self.assertRaises(RedemptionStoreError):
                    RedemptionStore(self.store.path).claim(ACCOUNT, 'cn', 'lowerCase7', run_dir=self.run,
                        epoch=0, evidence=self.before, basis={'page': 'form'})
            finally:
                release.set(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], dict)
        self.assertEqual(self.store.lookup(ACCOUNT, 'cn', 'lowerCase7')['id'], results[0]['id'])

    def test_corrupt_json_duplicate_keys_and_duplicate_scope_are_preserved(self):
        for raw in (b'{bad', b'{"schema":1,"schema":1,"generation":0,"entries":[]}', b'{"schema":NaN}'):
            self.store.path.write_bytes(raw)
            with self.assertRaises(RedemptionStoreError): self.store.lookup(ACCOUNT, 'cn', 'code')
            with self.assertRaises(RedemptionStoreError): self.claim()
            self.assertEqual(self.store.path.read_bytes(), raw)
        self.store.path.unlink()
        self.claim()
        data = json.loads(self.store.path.read_text(encoding='utf-8'))
        data['entries'].append(deepcopy(data['entries'][0]))
        raw = json.dumps(data).encode(); self.store.path.write_bytes(raw)
        with self.assertRaises(RedemptionStoreError): self.store.lookup(ACCOUNT, 'cn', 'lowerCase7')
        self.assertEqual(self.store.path.read_bytes(), raw)

    def test_public_summary_has_only_server_and_status_counts(self):
        entry = self.claim('PrivateCode7')
        self.finish(entry)
        self.claim('另一个码', account=OTHER)
        summary = self.store.public_summary(ACCOUNT, 'cn')
        self.assertEqual(summary['total'], 1)
        self.assertEqual(summary['statuses']['redeemed'], 1)
        serialized = json.dumps(summary, ensure_ascii=False)
        for forbidden in (ACCOUNT, OTHER, str(self.root), 'PrivateCode7', '另一个码', 'account', 'path', 'code'):
            self.assertNotIn(forbidden, serialized)


if __name__ == '__main__':
    unittest.main()
