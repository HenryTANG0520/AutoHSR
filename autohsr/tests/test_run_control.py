"""Typed stop intent through fake children; never execute a native Runner."""
from copy import deepcopy
from threading import Event, RLock
from types import SimpleNamespace
import unittest

from autohsr.app import Runner
from autohsr.currency_wars_loop import CurrencyLoopRunner
from autohsr.plan_runner import PlanRunner
from autohsr.run_control import stop_requested


class FakeChild:
    def __init__(self, result=None, on_run=None):
        self.result = result
        self.on_run = on_run
        self._stop = Event()
        self.run_calls = 0
        self.stop_calls = 0

    @property
    def stop_requested(self):
        return self._stop.is_set()

    def stop(self):
        self.stop_calls += 1
        self._stop.set()

    def run(self):
        self.run_calls += 1
        if self.on_run is not None:
            self.on_run()
        return self.result


def wrapper(kind):
    parent = kind.__new__(kind)
    parent._stop = Event()
    parent._lock = RLock()
    parent._paused = False
    parent.child = None
    parent._control_hwnd = None
    parent.emit = lambda event: None
    return parent


def run_child(parent, child):
    if isinstance(parent, PlanRunner):
        return parent._run(object(), phase='fake', factory=lambda *args, **kwargs: child)
    return parent._run_bound_child(child)


class StopIntentTests(unittest.TestCase):
    def test_only_literal_runner_true_and_exact_original_stopped_status_count(self):
        self.assertFalse(stop_requested())
        for value in (None, False, 0, 1, 'true', 'stopped', [], [True], lambda: True, Event()):
            with self.subTest(value_type=type(value).__name__):
                self.assertFalse(stop_requested(SimpleNamespace(stop_requested=value)))
        self.assertTrue(stop_requested(SimpleNamespace(stop_requested=True)))
        for status in (None, True, 1, 'partial', 'failed', 'unknown', 'success', 'Stopped', ' stopped '):
            self.assertFalse(stop_requested(report={'status': status}))
            self.assertFalse(stop_requested(report=SimpleNamespace(status=status)))
        self.assertTrue(stop_requested(report={'status': 'stopped'}))
        self.assertTrue(stop_requested(report=SimpleNamespace(status='stopped')))
        self.assertFalse(stop_requested({'stop_requested': True}))
        self.assertFalse(stop_requested(SimpleNamespace(schedule_stopped=True)))

    def test_broken_optional_observers_do_not_mask_an_independent_report(self):
        class Broken:
            @property
            def stop_requested(self):
                raise ValueError('observer failed')

            @property
            def status(self):
                raise ValueError('status failed')

        self.assertFalse(stop_requested(Broken()))
        self.assertFalse(stop_requested(report=Broken()))
        self.assertTrue(stop_requested(Broken(), {'status': 'stopped'}))
        self.assertTrue(stop_requested(SimpleNamespace(stop_requested=True), Broken()))

    def test_status_like_objects_and_private_flags_are_not_stop_evidence(self):
        class LooksStopped:
            def __eq__(self, other):
                return True

        self.assertFalse(stop_requested(report={'status': LooksStopped()}))
        private = Event()
        private.set()
        self.assertFalse(stop_requested(SimpleNamespace(_stop=private, status='stopped')))

    def test_original_report_data_is_not_modified(self):
        report = {'status': 'partial', 'report_saved': False, 'daily_verified': True,
                  'currency_wars': {'victories': 2, 'defeats': 1}, 'stamina_spent': 120}
        original = deepcopy(report)
        self.assertTrue(stop_requested(SimpleNamespace(stop_requested=True), report))
        self.assertEqual(report, original)

    def test_native_runner_property_reads_only_its_event_without_starting_it(self):
        native = Runner.__new__(Runner)
        native._stop = Event()
        self.assertFalse(native.stop_requested)
        native._stop.set()
        self.assertTrue(native.stop_requested)
        with self.assertRaises(AttributeError):
            native.stop_requested = False

    def test_composed_properties_are_read_only_and_reject_untyped_children(self):
        for kind in (PlanRunner, CurrencyLoopRunner):
            parent = wrapper(kind)
            self.assertFalse(parent.stop_requested)
            for value in (1, 'true', lambda: True):
                parent.child = SimpleNamespace(stop_requested=value)
                self.assertFalse(parent.stop_requested)
            child = FakeChild()
            child._stop.set()
            parent.child = child
            self.assertTrue(parent.stop_requested)
            self.assertFalse(parent._stop.is_set())
            self.assertEqual(child.stop_calls, 0)
            self.assertEqual(child.run_calls, 0)
            parent.child = None
            self.assertFalse(parent.stop_requested)
            parent._stop.set()
            self.assertTrue(parent.stop_requested)

    def test_nested_and_cyclic_property_reads_are_bounded_without_stop_calls(self):
        outer = wrapper(PlanRunner)
        inner = wrapper(CurrencyLoopRunner)
        leaf = FakeChild()
        outer.child, inner.child = inner, leaf
        self.assertFalse(stop_requested(outer))
        leaf._stop.set()
        self.assertTrue(stop_requested(outer))
        self.assertFalse(outer._stop.is_set())
        self.assertFalse(inner._stop.is_set())
        self.assertEqual(leaf.stop_calls, 0)
        inner.child = outer
        self.assertFalse(stop_requested(outer))
        self.assertFalse(outer.stop_requested)
        outer.child = outer
        self.assertFalse(outer.stop_requested)

    def test_partial_report_after_child_stop_propagates_before_child_release(self):
        for kind in (PlanRunner, CurrencyLoopRunner):
            with self.subTest(wrapper=kind.__name__):
                parent = wrapper(kind)
                report = {'status': 'partial', 'report_saved': False, 'daily_verified': True,
                          'stamina_spent': 120, 'currency_wars': {'victories': 1, 'defeats': 0}}
                original = deepcopy(report)
                child = FakeChild(report)
                child.on_run = child._stop.set
                self.assertIs(run_child(parent, child), report)
                self.assertTrue(parent.stop_requested)
                self.assertTrue(parent._stop.is_set())
                self.assertIsNone(parent.child)
                self.assertEqual(child.stop_calls, 1)
                self.assertEqual(report, original)

    def test_original_stopped_object_is_read_before_conversion_changes_projection(self):
        for kind in (PlanRunner, CurrencyLoopRunner):
            with self.subTest(wrapper=kind.__name__):
                parent = wrapper(kind)

                class Result:
                    status = 'stopped'

                    def to_dict(result_self):
                        self.assertTrue(parent._stop.is_set())
                        return {'status': 'partial', 'report_saved': False}

                child = FakeChild(Result())
                result = run_child(parent, child)
                self.assertEqual(result['status'], 'partial')
                self.assertTrue(parent.stop_requested)
                self.assertEqual(child.stop_calls, 1)

    def test_original_raw_stopped_dict_propagates_without_a_child_property_stop(self):
        for kind in (PlanRunner, CurrencyLoopRunner):
            parent = wrapper(kind)
            report = {'status': 'stopped', 'report_saved': False}
            child = FakeChild(report)
            self.assertIs(run_child(parent, child), report)
            self.assertTrue(parent._stop.is_set())
            self.assertEqual(report, {'status': 'stopped', 'report_saved': False})

    def test_child_run_exception_still_propagates_a_typed_stop_in_finally(self):
        for kind in (PlanRunner, CurrencyLoopRunner):
            parent = wrapper(kind)
            child = FakeChild()

            def fail():
                child._stop.set()
                raise RuntimeError('child failed after stop')

            child.on_run = fail
            with self.assertRaisesRegex(RuntimeError, 'child failed after stop'):
                run_child(parent, child)
            self.assertTrue(parent._stop.is_set())
            self.assertIsNone(parent.child)
            self.assertEqual(child.stop_calls, 1)

    def test_conversion_exception_after_late_stop_is_propagated_in_finally(self):
        for kind in (PlanRunner, CurrencyLoopRunner):
            parent = wrapper(kind)
            child = FakeChild()

            class Result:
                status = 'partial'

                def to_dict(self):
                    child._stop.set()
                    raise RuntimeError('report conversion failed')

            child.result = Result()
            with self.assertRaisesRegex(RuntimeError, 'report conversion failed'):
                run_child(parent, child)
            self.assertTrue(parent._stop.is_set())
            self.assertIsNone(parent.child)

    def test_partial_unknown_and_ordinary_exceptions_do_not_invent_stop(self):
        for kind in (PlanRunner, CurrencyLoopRunner):
            for status in ('partial', 'failed', 'unknown', 'success'):
                parent = wrapper(kind)
                report = {'status': status, 'report_saved': False}
                child = FakeChild(report)
                self.assertIs(run_child(parent, child), report)
                self.assertFalse(parent.stop_requested)
                self.assertEqual(child.stop_calls, 0)
            parent = wrapper(kind)
            child = FakeChild(on_run=lambda: (_ for _ in ()).throw(RuntimeError('ordinary failure')))
            with self.assertRaisesRegex(RuntimeError, 'ordinary failure'):
                run_child(parent, child)
            self.assertFalse(parent.stop_requested)
            self.assertIsNone(parent.child)

    def test_finally_does_not_clear_or_stop_a_replacement_child(self):
        for kind in (PlanRunner, CurrencyLoopRunner):
            parent = wrapper(kind)
            replacement = FakeChild()
            child = FakeChild({'status': 'partial'})

            def replace_owned_child():
                child._stop.set()
                parent.child = replacement

            child.on_run = replace_owned_child
            run_child(parent, child)
            self.assertIs(parent.child, replacement)
            self.assertFalse(parent._stop.is_set())
            self.assertEqual(child.stop_calls, 0)
            self.assertEqual(replacement.stop_calls, 0)


if __name__ == '__main__':
    unittest.main()
