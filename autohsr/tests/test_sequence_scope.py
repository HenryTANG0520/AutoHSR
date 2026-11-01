"""Composition boundaries, with an in-memory execution marker only."""
from contextvars import copy_context
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from autohsr.models import AutomationError
from autohsr import workflow_identity as identity
from autohsr import workflow_lease as lease
from autohsr.tests import test_plan_sequence_scope as fixtures


class SequenceScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.kernel = fixtures.MemoryKernel()
        for name, value in (('_kernel', lambda: self.kernel),
                            ('C.set_last_error', self.kernel.set_error), ('C.get_last_error', self.kernel.get_error)):
            p = patch('autohsr.workflow_lease.' + name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_composed_sequences_do_not_create_or_release_an_outer_handle(self):
        with lease.workflow_lease():
            with lease.sequence_lease(), lease.sequence_lease():
                lease.require_workflow_access()
                self.assertEqual(self.kernel.created, 1)
            self.assertEqual(len(self.kernel.handles), 1)
            with self.assertRaises(AutomationError):
                with lease.workflow_lease():
                    pass
        self.assertFalse(self.kernel.handles)
        lease.require_workflow_access()

    def test_copied_context_cannot_transfer_the_owner_thread(self):
        failures = []
        with lease.sequence_lease(), identity.sequence_identity(self.root):
            context = copy_context()
            def worker():
                for enter in (lease.sequence_lease, lambda: identity.sequence_identity(self.root)):
                    try:
                        with enter():
                            failures.append('unexpected_permission')
                    except AutomationError:
                        failures.append('blocked')
            thread = threading.Thread(target=lambda: context.run(worker))
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, ['blocked', 'blocked'])
            lease.require_workflow_access()
        self.assertFalse(identity.active())
        self.assertFalse(self.kernel.handles)

    def test_child_preserves_parent_identity_and_publisher(self):
        outer_events, inner_events = [], []
        with identity.sequence_identity(self.root, publish=outer_events.append) as parent:
            with identity.sequence_identity(self.root / 'child', required=False, publish=inner_events.append) as child:
                self.assertIs(parent, child)
                child.publish(child.public())
                self.assertTrue(child.required)
            self.assertTrue(identity.active())
        self.assertEqual(len(outer_events), 1)
        self.assertEqual(inner_events, [])
        self.assertFalse(identity.active())
        self.assertFalse((self.root / 'identity').exists())  # Merely entering proves no account.

    def test_undeclared_game_scope_cannot_silently_upgrade_a_local_parent(self):
        with identity.sequence_identity(self.root, required=False) as parent:
            with self.assertRaises(AutomationError):
                with identity.sequence_identity(self.root / 'child', required=True):
                    pass
            self.assertFalse(parent.required)
        self.assertFalse(identity.active())

    def test_exception_releases_both_scopes_and_next_sequence_can_start(self):
        with self.assertRaises(RuntimeError):
            with lease.sequence_lease(), identity.sequence_identity(self.root):
                raise RuntimeError('synthetic failure')
        self.assertFalse(identity.active())
        self.assertFalse(self.kernel.handles)
        with lease.sequence_lease(), identity.sequence_identity(self.root) as current:
            self.assertFalse(current.public()['bound'])
            self.assertFalse(current.public()['verified'])

    def test_invalid_identity_options_cannot_enter_a_scope(self):
        for options in (dict(required=1), dict(required=None), dict(publish=True)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                with identity.sequence_identity(self.root, **options):
                    pass
        self.assertFalse(identity.active())
