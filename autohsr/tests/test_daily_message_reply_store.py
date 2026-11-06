from copy import copy
import errno
import json
import multiprocessing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from autohsr.daily_message_reply_store import ReplyStore
from autohsr.models import AutomationError, FocusLost


ACCOUNT = 'a' * 64
OTHER_ACCOUNT = 'b' * 64
SECTION = 126801


def _reserve_in_process(directory, start):
    start.wait(timeout=10)
    try:
        ReplyStore(directory).reserve(ACCOUNT, SECTION)
    except AutomationError:
        raise SystemExit(2) from None


class ReplyStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'reply-ledger'
        self.store = ReplyStore(self.directory)

    def pending(self):
        reservation = self.store.reserve(ACCOUNT, SECTION)
        record, = self.directory.iterdir()
        return reservation, record

    def test_pending_and_confirmed_both_block_a_fresh_store(self):
        self.assertEqual(self.store.status(ACCOUNT, SECTION), 'none')
        reservation, record = self.pending()
        raw = record.read_bytes()
        data = json.loads(raw)
        self.assertEqual(set(data), {'schema', 'section', 'attempt', 'status'})
        self.assertEqual((data['schema'], data['section'], data['status']), (1, SECTION, 'pending'))
        self.assertEqual(self.store.status(ACCOUNT, SECTION), 'pending')
        self.assertNotIn(ACCOUNT, record.name)
        self.assertNotIn(ACCOUNT.encode('ascii'), raw)
        with self.assertRaises(AutomationError):
            ReplyStore(self.directory).reserve(ACCOUNT, SECTION)
        self.assertEqual(record.read_bytes(), raw)
        reservation.confirm()
        self.assertEqual(json.loads(record.read_bytes()), dict(data, status='confirmed'))
        self.assertEqual(self.store.status(ACCOUNT, SECTION), 'confirmed')
        with self.assertRaises(AutomationError):
            ReplyStore(self.directory).reserve(ACCOUNT, SECTION)
        self.store.reserve(ACCOUNT, SECTION + 1)
        self.store.reserve(OTHER_ACCOUNT, SECTION)
        self.assertEqual(len(list(self.directory.iterdir())), 3)

    def test_raw_uid_and_noncanonical_account_keys_are_rejected(self):
        for invalid in ('123456789', 123456789, ACCOUNT.upper(), ' ' + ACCOUNT):
            with self.subTest(account_key=invalid):
                with self.assertRaises(AutomationError):
                    self.store.reserve(invalid, SECTION)
        self.assertFalse(self.directory.exists())

    def test_only_the_original_reservation_can_confirm_once(self):
        reservation, record = self.pending()
        raw = record.read_bytes()
        with self.assertRaises(AutomationError):
            copy(reservation).confirm()
        self.assertEqual(record.read_bytes(), raw)
        reservation.confirm()
        with self.assertRaises(AutomationError):
            reservation.confirm()

    def test_partial_record_cannot_be_replaced_or_confirmed(self):
        reservation, record = self.pending()
        duplicate = record.read_bytes().replace(b'"status":"pending"', b'"status":"pending","status":"confirmed"')
        for malformed in (b'', b'{"status":"pending"', b'{"status":"confirmed"}', duplicate):
            with self.subTest(malformed=malformed):
                record.write_bytes(malformed)
                self.assertEqual(self.store.status(ACCOUNT, SECTION), 'pending')
                with self.assertRaises(AutomationError):
                    ReplyStore(self.directory).reserve(ACCOUNT, SECTION)
                with self.assertRaises(AutomationError):
                    reservation.confirm()
                self.assertEqual(record.read_bytes(), malformed)
                self.assertEqual(list(self.directory.iterdir()), [record])

    def test_an_identical_replacement_is_a_different_pending_file(self):
        reservation, record = self.pending()
        raw = record.read_bytes()
        replacement = record.with_suffix('.replacement')
        replacement.write_bytes(raw)
        replacement.replace(record)
        with self.assertRaises(AutomationError):
            reservation.confirm()
        self.assertEqual(record.read_bytes(), raw)

    def test_reserve_sync_failure_leaves_no_usable_intent(self):
        with patch('autohsr.daily_message_reply_store.os.fsync', side_effect=OSError(errno.ENOSPC, 'full')):
            with self.assertRaises(AutomationError):
                self.store.reserve(ACCOUNT, SECTION)
        self.assertEqual(list(self.directory.iterdir()), [])
        self.pending()

    def test_confirm_replace_failure_keeps_pending_and_blocks_reserve(self):
        reservation, record = self.pending()
        raw = record.read_bytes()
        with patch.object(Path, 'replace', side_effect=OSError(errno.ENOSPC, 'full')):
            with self.assertRaises(AutomationError):
                reservation.confirm()
        self.assertEqual(record.read_bytes(), raw)
        self.assertEqual(list(self.directory.iterdir()), [record])
        with self.assertRaises(AutomationError):
            self.store.reserve(ACCOUNT, SECTION)

    @unittest.skipUnless(os.name == 'nt', 'Windows file identity')
    def test_identical_stage_replacement_preserves_the_original_pending_record(self):
        reservation, record = self.pending()
        pending = record.read_bytes()
        existing = self.directory.parent / 'unrelated.json'

        def substitute():
            source, = self.directory.glob('.sms-reply-*.tmp')
            existing.write_bytes(source.read_bytes())
            source.unlink()
            os.link(existing, source)

        with self.assertRaises(AutomationError):
            reservation.confirm(before_replace=substitute)
        self.assertEqual(record.read_bytes(), pending)
        remaining, = self.directory.glob('.sms-reply-*.tmp')
        self.assertTrue(os.path.samefile(existing, remaining))

    def test_late_focus_veto_rechecks_after_a_sharing_retry(self):
        reservation, record = self.pending()
        raw = record.read_bytes()
        verifier = Mock(side_effect=(None, FocusLost('offline late focus loss')))
        with patch.object(Path, 'replace', side_effect=PermissionError('shared reader')) as replace, \
                patch('autohsr.storage.time.sleep'):
            with self.assertRaises(FocusLost):
                reservation.confirm(before_replace=verifier)
        self.assertEqual(verifier.call_count, 2)
        replace.assert_called_once()
        self.assertEqual(record.read_bytes(), raw)
        self.assertEqual(list(self.directory.iterdir()), [record])

    def test_two_processes_contending_for_one_section_publish_once(self):
        processes = multiprocessing.get_context('spawn')
        start = processes.Barrier(2)
        workers = []
        try:
            for _ in range(2):
                worker = processes.Process(target=_reserve_in_process, args=(self.directory, start))
                worker.start()
                workers.append(worker)
            for worker in workers:
                worker.join(timeout=15)
                self.assertIsNotNone(worker.exitcode)
            self.assertCountEqual([worker.exitcode for worker in workers], [0, 2])
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join()
                worker.close()
        record, = self.directory.iterdir()
        self.assertEqual(json.loads(record.read_bytes())['status'], 'pending')
