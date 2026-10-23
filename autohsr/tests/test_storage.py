"""File-sharing regressions; no game inputs."""
import errno
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from autohsr.storage import replace_file,REPLACE_RETRY_DELAYS


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.source=self.root/'pending.tmp';self.source.write_text('new')
        self.destination=self.root/'ledger.json';self.destination.write_text('old')

    def test_transient_lock_retries_rename_and_publishes_prepared_bytes_once(self):
        original=Path.replace;attempts=[]
        def locked(source,destination):
            attempts.append(source.read_text())
            if len(attempts)<3:
                self.assertEqual(Path(destination).read_text(),'old')
                raise PermissionError('shared read handle')
            return original(source,destination)
        with patch.object(Path,'replace',locked),patch('autohsr.storage.time.sleep') as sleep:
            replace_file(self.source,self.destination)
        self.assertEqual(attempts,['new']*3)
        self.assertEqual(sleep.call_count,2)
        self.assertEqual(self.destination.read_text(),'new')
        self.assertFalse(self.source.exists())

    def test_permanent_lock_keeps_old_ledger_and_pending_evidence(self):
        with patch.object(Path,'replace',side_effect=PermissionError('locked')) as rename, \
             patch('autohsr.storage.time.sleep') as sleep:
            with self.assertRaises(PermissionError):
                replace_file(self.source,self.destination)
        self.assertEqual(rename.call_count,len(REPLACE_RETRY_DELAYS)+1)
        self.assertEqual(sleep.call_count,len(REPLACE_RETRY_DELAYS))
        self.assertEqual(self.destination.read_text(),'old')
        self.assertEqual(self.source.read_text(),'new')

    def test_disk_full_is_not_treated_as_a_temporary_sharing_lock(self):
        with patch.object(Path,'replace',side_effect=OSError(errno.ENOSPC,'full')) as rename, \
             patch('autohsr.storage.time.sleep') as sleep:
            with self.assertRaises(OSError):
                replace_file(self.source,self.destination)
        rename.assert_called_once();sleep.assert_not_called()
        self.assertEqual(self.destination.read_text(),'old')

    @unittest.skipUnless(os.name=='nt','Windows sharing semantics')
    def test_real_windows_reader_can_close_during_atomic_publish(self):
        entered=threading.Event()
        def reader():
            with self.destination.open('rb') as handle:
                self.assertEqual(handle.read(),b'old')
                entered.set()
                threading.Event().wait(.12)
        worker=threading.Thread(target=reader)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            replace_file(self.source,self.destination)
        finally:
            worker.join()
        self.assertEqual(self.destination.read_text(),'new')

    def test_both_du_ledger_writers_survive_one_lock_without_game_input(self):
        from autohsr.app import Context
        from autohsr.config import Settings
        from autohsr.differential_universe import DifferentialUniverseWorkflow
        from autohsr.models import RunReport
        context=Mock(settings=Settings(),report=RunReport(operation='differential_universe',run_dir=str(self.root)))
        flow=DifferentialUniverseWorkflow(context,1)
        original=Path.replace
        for publish in (flow._persist_ledger,lambda:Context._persist_du_ledger(context)):
            calls=[]
            def locked(source,destination):
                calls.append(str(source))
                if len(calls)==1:raise PermissionError('reader')
                return original(source,destination)
            with patch.object(Path,'replace',locked),patch('autohsr.storage.time.sleep'):
                publish()
            self.assertEqual(len(calls),2)
            self.assertEqual(json.loads((self.root/'differential-universe-ledger.json').read_text('utf8'))['session_id'],flow.session_id)
        context.click.assert_not_called();context.key.assert_not_called()
