"""Workflow editor receipts, source preservation, and exclusive publication."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from textwrap import dedent
import unittest
from unittest.mock import patch

from autohsr import warp_service
from autohsr.config import Settings
from autohsr.task_workflow import MAX_BYTES, WorkflowError, read, task_spec
from autohsr.task_workflow_draft import WorkflowDraft, WorkflowSaveConflict


def document(name='日常草稿'):
    return dict(version=1, name=name, steps=[
        dict(id='wait', type='wait', seconds=0),
    ])


class WorkflowDraftTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.source = self.root / '原流程.json'
        self.original = ('\ufeff' + json.dumps(document(), ensure_ascii=False, indent=4)).encode('utf8')
        self.source.write_bytes(self.original)
        self.target = self.root / '另存.json'

    def assert_conflict(self, reason, draft, target):
        with self.assertRaises(WorkflowSaveConflict) as error:
            draft.save_as(target)
        self.assertEqual(error.exception.reason, reason)

    def test_load_edits_detached_tree_and_saves_a_verified_cli_document(self):
        from autohsr.__main__ import main

        draft = WorkflowDraft.load(self.source)
        self.assertFalse(draft.dirty)
        self.assertTrue(draft.source_is_current())
        self.assertEqual(draft.source, self.source)
        draft.document['name'] = '编辑后的流程'
        draft.document['steps'][0]['seconds'] = 2
        preview = draft.validate()
        preview.document['steps'][0]['seconds'] = 99
        self.assertEqual(draft.document['steps'][0]['seconds'], 2)
        self.assertFalse(self.target.exists())

        saved = draft.save_as(self.target)
        self.assertEqual(saved.path, self.target)
        self.assertEqual(saved.recipe.document, read(self.target))
        self.assertEqual(saved.sha256, hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(draft.source, self.source)
        self.assertTrue(draft.dirty)
        self.assertFalse(WorkflowDraft.load(saved.path).dirty)
        with (patch('autohsr.config.Settings.load') as config, redirect_stdout(io.StringIO()) as output,
              redirect_stderr(io.StringIO())):
            self.assertEqual(main(['--task-workflow-check', str(saved.path)]), 0)
        config.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['reservations'], saved.recipe.profile)

    def test_relative_references_follow_the_explicit_destination(self):
        value = dict(version=1, name='记录分析', steps=[
            dict(id='records', type='task', task='warp_export',
                 params=dict(imports=['inputs/原件.json'], output='exports/结果.json')),
        ])
        self.source.write_text(json.dumps(value, ensure_ascii=False), encoding='utf8')
        sibling = self.root / '目标目录'
        sibling.mkdir()
        target = sibling / 'copy.json'
        draft = WorkflowDraft.load(self.source)

        self.assertEqual(draft.validate().base_dir, self.root)
        self.assertEqual(draft.validate(destination=target).base_dir, sibling)
        saved = draft.save_as(target)
        self.assertEqual(read(target), value)
        _, options = task_spec(Settings(), saved.recipe.steps[0], saved.recipe.base_dir)
        self.assertEqual(options['imports'], [str(sibling / 'inputs' / '原件.json')])
        self.assertEqual(options['output'], str(sibling / 'exports' / '结果.json'))
        self.assertFalse((sibling / 'inputs').exists())
        self.assertFalse((sibling / 'exports').exists())

    def test_rejects_a_new_budget_even_after_valid_selected_step_preview(self):
        draft = WorkflowDraft.load(self.source)
        draft.document['steps'] = [
            dict(id='dayOne', type='task', task='daily'),
            dict(id='dayTwo', type='task', task='daily'),
        ]
        self.assertEqual(draft.validate(selected_path='0').profile['daily_calls'], 1)
        with self.assertRaisesRegex(WorkflowError, '一份日常预算'):
            draft.save_as(self.target)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(self.target.exists())

    def test_loaded_path_and_existing_target_preserve_every_byte(self):
        draft = WorkflowDraft.load(self.source)
        self.assert_conflict('source_path', draft, self.source)
        for data in (self.original, b'{invalid!'):
            with self.subTest(valid=data == self.original):
                self.target.write_bytes(data)
                self.assert_conflict('target_exists', draft, self.target)
                self.assertEqual(self.target.read_bytes(), data)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_changed_or_missing_source_is_never_recreated_by_save(self):
        draft = WorkflowDraft.load(self.source)
        before = self.source.stat()
        foreign = b'!' * len(self.original)
        self.source.write_bytes(foreign)
        os.utime(self.source, ns=(before.st_atime_ns, before.st_mtime_ns))
        self.assertFalse(draft.source_is_current())
        self.assert_conflict('source_changed', draft, self.source)
        self.assertEqual(self.source.read_bytes(), foreign)

        draft.document['name'] = '保留旧草稿'
        self.assertEqual(draft.save_as(self.target).recipe.document['name'], '保留旧草稿')
        self.assertEqual(self.source.read_bytes(), foreign)
        self.source.unlink()
        self.assert_conflict('source_changed', draft, self.source)
        self.assertFalse(self.source.exists())

    def test_invalid_import_and_missing_destination_directory_do_not_create_files(self):
        for invalid in (b'{"version":1,"version":1}', b'\xff', b'NaN', b'x' * (MAX_BYTES + 1)):
            with self.subTest(size=len(invalid), prefix=invalid[:16]):
                self.source.write_bytes(invalid)
                with self.assertRaises(WorkflowError):
                    WorkflowDraft.load(self.source)
                self.assertEqual(self.source.read_bytes(), invalid)
        self.source.write_bytes(self.original)
        missing = self.root / 'missing'
        with self.assertRaises(FileNotFoundError):
            WorkflowDraft.load(self.source).save_as(missing / 'copy.json')
        self.assertFalse(missing.exists())

    def test_valid_large_input_round_trips_within_the_existing_limit(self):
        value = dict(version=1, name='接近文件限制', steps=[
            dict(id='records' + str(index), type='task', task='warp_analysis',
                 params=dict(imports=['x' * 4083] * 32))
            for index in range(8)
        ])
        raw = json.dumps(value, ensure_ascii=False).encode('utf8')
        pretty = json.dumps(value, ensure_ascii=False, indent=2).encode('utf8')
        self.assertLessEqual(len(raw), MAX_BYTES)
        self.assertGreater(len(pretty), MAX_BYTES)
        self.source.write_bytes(raw)
        saved = WorkflowDraft.load(self.source).save_as(self.target)
        self.assertLessEqual(self.target.stat().st_size, MAX_BYTES)
        self.assertEqual(saved.recipe.document, value)

    def test_external_file_created_at_the_real_publish_boundary_is_preserved(self):
        draft = WorkflowDraft.load(self.source)
        operation = 'rename' if os.name == 'nt' else 'link'
        publish = getattr(os, operation)
        foreign = b'foreign source bytes'

        def claim_destination(staging, target):
            Path(target).write_bytes(foreign)
            return publish(staging, target)

        with patch.object(warp_service.os, operation, side_effect=claim_destination) as native:
            self.assert_conflict('target_exists', draft, self.target)
        native.assert_called_once()
        self.assertEqual(self.target.read_bytes(), foreign)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob('.autohsr-warp-*')), [])

    def test_fsync_and_unverified_readback_preserve_the_draft(self):
        draft = WorkflowDraft.load(self.source)
        draft.document['name'] = '待保存'
        with (patch.object(warp_service.os, 'fsync', side_effect=OSError('disk write failed')),
              self.assertRaisesRegex(OSError, 'disk write failed')):
            draft.save_as(self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob('.autohsr-warp-*')), [])

        foreign = b'changed after publish'

        def publish_then_change(path, writer, **kwargs):
            digest = warp_service.publish_new(path, writer, **kwargs)
            Path(path).write_bytes(foreign)
            return digest

        with patch('autohsr.task_workflow_draft.publish_new', side_effect=publish_then_change):
            self.assert_conflict('readback_changed', draft, self.target)
        self.assertEqual(self.target.read_bytes(), foreign)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(draft.document['name'], '待保存')
        self.assertTrue(draft.dirty)

    def test_two_processes_at_the_native_publish_boundary_have_one_winner(self):
        script = dedent('''
            import os
            from pathlib import Path
            import sys
            import time
            from unittest.mock import patch
            from autohsr import warp_service
            from autohsr.task_workflow_draft import WorkflowDraft, WorkflowSaveConflict

            source, target, label = sys.argv[1:]
            root = Path(target).parent
            draft = WorkflowDraft.load(source)
            draft.document['name'] = label
            operation = 'rename' if os.name == 'nt' else 'link'
            native = getattr(os, operation)

            def wait_for_peer(staging, destination):
                (root / ('ready-' + label)).touch()
                deadline = time.monotonic() + 5
                while len(list(root.glob('ready-*'))) < 2:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('peer did not reach native publication')
                    time.sleep(.01)
                return native(staging, destination)

            with patch.object(warp_service.os, operation, side_effect=wait_for_peer):
                try:
                    draft.save_as(target)
                except WorkflowSaveConflict as conflict:
                    print(conflict.reason)
                else:
                    print(label)
        ''')
        children = []
        try:
            for name in ('first', 'second'):
                children.append(subprocess.Popen(
                    [sys.executable, '-B', '-c', script, str(self.source), str(self.target), name],
                    cwd=Path(__file__).resolve().parents[2],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            results = []
            for child in children:
                output, error = child.communicate(timeout=12)
                self.assertEqual(child.returncode, 0, error)
                results.append(output.strip())
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                    child.communicate()
        winner = read(self.target)['name']
        self.assertIn(winner, ('first', 'second'))
        self.assertCountEqual(results, ['target_exists', winner])
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob('.autohsr-warp-*')), [])
