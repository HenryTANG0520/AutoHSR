"""Schedule core only: synthetic definitions, temp storage and fake Runners.

No project CLI, native game Runner, Windows execution marker or real timer is
used. Worker threads only call the controlled fake executor in this module.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from autohsr.schedule_plan import (CHINA, ScheduleError, due_slot, loads, next_due,
                                  preview, read, revision, validate)
from autohsr.schedule_store import ScheduleStore, SlotClaim
from autohsr.schedule_runtime import Scheduler


def definition(plan_id='synthetic', **extra):
    value = dict(version=1, id=plan_id, name='离线计划', time='04:00',
                 target=dict(type='task', task='synthetic_local', params={}))
    value.update(extra)
    return value


class Clock:
    def __init__(self):
        self.now = datetime(2026, 10, 30, 3, 59, 0, tzinfo=CHINA)
        self.seconds = 0

    def __call__(self):
        return self.now

    def set(self, hour=4, minute=0, second=0, *, days=0):
        self.now = self.now.replace(hour=hour, minute=minute, second=second) + timedelta(days=days)


class FakeRunner:
    def __init__(self, *, status='success', saved=True, block=False, auto_release=True):
        self.status, self.saved, self.block, self.auto_release = status, saved, block, auto_release
        self.started, self.release, self.stopped = threading.Event(), threading.Event(), threading.Event()
        self.pause_changes = []
        self.paused = False
        self.emit = lambda event: None
        self.calls = 0

    def run(self):
        self.calls += 1
        self.started.set()
        if self.block:
            if not self.release.wait(3):
                raise AssertionError('fake worker was not released')
        self.emit(dict(type='log', message='synthetic-private-UID100000001', account='synthetic-private'))
        self.emit(dict(type='finished', report=dict(uid='synthetic-private-UID100000001')))
        return dict(status='stopped' if self.stopped.is_set() else self.status, report_saved=self.saved,
                    operation='synthetic_local', run_dir='synthetic-private-directory')

    def stop(self):
        self.stopped.set()
        if self.auto_release:
            self.release.set()

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_changes.append(self.paused)
        self.emit(dict(type='paused', paused=self.paused))
        return self.paused


class FakeExecutor:
    def __init__(self, *runners):
        self.available = list(runners)
        self.created = []
        self.frozen = []
        self.verified = []
        self.external_busy = False
        self.changed = False

    def freeze(self, plan):
        self.frozen.append(deepcopy(plan))
        return dict(source='synthetic-private-source', target=deepcopy(plan['target']))

    def revalidate(self, manifest):
        self.verified.append(deepcopy(manifest))
        if self.changed:
            raise ScheduleError('synthetic changed source')

    def busy(self):
        return self.external_busy

    def create(self, target, manifest, emit):
        runner = self.available.pop(0) if self.available else FakeRunner()
        runner.emit = emit
        self.created.append(runner)
        return runner


class HeldNotificationRunner(FakeRunner):
    """A completed original game report held by a cancellable fake notification."""
    def __init__(self):
        super().__init__(block=True, auto_release=False)
        self.stop_requested = False
        self.original_report = dict(status='success', report_saved=True, operation='synthetic_local',
                                    run_dir='synthetic-private-directory')

    def run(self):
        self.calls += 1
        self.started.set()
        if not self.release.wait(3):
            raise AssertionError('fake notification was not released')
        return deepcopy(self.original_report)

    def stop(self):
        self.stop_requested = True
        self.stopped.set()


class DefinitionTests(unittest.TestCase):
    def test_defaults_are_inert_and_do_not_mutate_the_input(self):
        value = definition()
        original = deepcopy(value)
        plan = validate(value)
        self.assertEqual(value, original)
        self.assertEqual(plan['weekdays'], list(range(1, 8)))
        self.assertEqual(plan['repeat'], dict(count=1, interval_seconds=0))
        self.assertEqual(plan['conflict'], 'skip')
        self.assertEqual(plan['timeout_seconds'], 0)
        self.assertNotIn('enabled', plan)

    def test_strict_fields_reject_implicit_enable_scripts_bad_times_and_limits(self):
        invalid = [dict(definition(), enabled=True), dict(definition(), time='4:00'),
                   dict(definition(), time='04:0０'), dict(definition(), weekdays=[True]),
                   dict(definition(), weekdays=[1, 1]), dict(definition(), weekdays=[]),
                   dict(definition(), repeat=dict(count=0)), dict(definition(), repeat=dict(count=True)),
                   dict(definition(), repeat=dict(count=1001)), dict(definition(), repeat=dict(infinite=True)),
                   dict(definition(), conflict='kill'), dict(definition(), timeout_seconds=-1),
                   dict(definition(), target=dict(type='script', command='fake')),
                   dict(definition(), target=dict(type='task', task='synthetic_local', params=[])),
                   dict(definition(), target=dict(type='workflow', path='fake.json', step_path='0/-1'))]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ScheduleError):
                validate(value)

    def test_json_rejects_duplicates_nan_oversize_and_non_json_values(self):
        for raw in ('{"id":"a","id":"b"}', '{"value":NaN}', b'x' * 65537):
            with self.subTest(raw=str(raw)[:40]), self.assertRaises(ScheduleError):
                loads(raw)
        for value in (dict(definition(), target={1: 'bad'}), dict(definition(), name='\ud800')):
            with self.assertRaises(ScheduleError):
                validate(value)

    def test_minute_slots_convert_to_beijing_and_never_backfill(self):
        plan = definition(weekdays=[5])
        slot = datetime(2026, 10, 30, 4, tzinfo=CHINA)
        self.assertEqual(due_slot(plan, slot + timedelta(seconds=59)), slot)
        self.assertEqual(due_slot(plan, slot.astimezone(timezone.utc)), slot)
        self.assertIsNone(due_slot(plan, slot + timedelta(minutes=1)))
        self.assertIsNone(due_slot(plan, slot + timedelta(days=1)))
        with self.assertRaises(ScheduleError):
            due_slot(plan, slot.replace(tzinfo=None))

    def test_preview_next_week_and_canonical_revision(self):
        plan = definition(weekdays=[5])
        at_due = datetime(2026, 10, 30, 4, tzinfo=CHINA)
        self.assertEqual(next_due(plan, at_due), at_due + timedelta(days=7))
        data = preview(plan, at_due, count=2)
        self.assertEqual(data['next_times'], [(at_due + timedelta(days=n)).isoformat() for n in (7, 14)])
        self.assertTrue(data['saved_does_not_enable'])
        self.assertEqual(revision(plan), revision(validate(plan)))

    def test_explicit_file_read_is_bounded_and_has_no_other_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'schedule.json'
            path.write_text(json.dumps(definition()), encoding='utf8')
            self.assertEqual(read(path), validate(definition()))
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ScheduleStore(self.root)
        self.plan = validate(definition())
        self.digest = self.store.save(self.plan)['revision']
        self.slot = datetime(2026, 10, 30, 4, tzinfo=CHINA)

    def test_save_never_enables_and_old_versions_survive_explicit_replace(self):
        before = self.store._definition(self.plan['id'], self.digest).read_bytes()
        self.assertFalse(self.store.list_public()[0]['enabled'])
        with self.assertRaises(ScheduleError):
            self.store.save(definition(name='changed'))
        result = self.store.save(definition(name='changed'), replace=True, expected_revision=self.digest)
        self.assertFalse(result['enabled'])
        self.assertNotEqual(result['revision'], self.digest)
        self.assertEqual(self.store._definition(self.plan['id'], self.digest).read_bytes(), before)
        with self.assertRaises(ScheduleError):
            self.store.save(self.plan, replace=True, expected_revision=self.digest)

    def test_claim_survives_new_store_and_never_replays_pending(self):
        claim, first = self.store.claim(self.plan, self.digest, self.slot, {})
        self.store.begin_attempt(claim, 0)
        restarted = ScheduleStore(self.root)
        repeated, old = restarted.claim(self.plan, self.digest, self.slot, {})
        self.assertIsNone(repeated)
        self.assertEqual(old['status'], 'running')
        self.assertEqual(old['attempts'][0]['status'], 'pending')

    def test_acknowledged_and_unknown_terminal_receipts_are_immutable(self):
        for day, status in enumerate(('success', 'unknown')):
            slot = self.slot + timedelta(days=day)
            claim, _ = self.store.claim(self.plan, self.digest, slot, {})
            self.store.begin_attempt(claim, 0)
            self.store.record_result(claim, 0, dict(status=status))
            self.store.finish(claim, status)
            before = self.store._receipt_path(claim.key).read_bytes()
            self.assertIsNone(self.store.claim(self.plan, self.digest, slot, {})[0])
            with self.assertRaises(ScheduleError):
                self.store.finish(claim, 'failed')
            self.assertEqual(self.store._receipt_path(claim.key).read_bytes(), before)

    def test_corrupt_receipt_is_preserved_and_bad_owner_cannot_write(self):
        claim, _ = self.store.claim(self.plan, self.digest, self.slot, {})
        with self.assertRaises(ScheduleError):
            self.store.begin_attempt(SlotClaim(claim.key, '0' * 32), 0)
        path = self.store._receipt_path(claim.key)
        data = json.loads(path.read_text('utf8')); data['attempts'] = [None]
        before = json.dumps(data).encode('utf8'); path.write_bytes(before)
        with self.assertRaises(ScheduleError):
            self.store.claim(self.plan, self.digest, self.slot, {})
        self.assertEqual(path.read_bytes(), before)

    def test_two_controllers_cannot_both_claim_a_slot(self):
        barrier = threading.Barrier(2)
        claims, failures = [], []
        def submit():
            barrier.wait()
            try:
                claims.append(ScheduleStore(self.root).claim(self.plan, self.digest, self.slot, {})[0])
            except ScheduleError as error:
                failures.append(error)
        workers = [threading.Thread(target=submit) for _ in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(2)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        self.assertEqual(len(claims) + len(failures), 2)
        self.assertEqual(len(self.store.receipts()), 1)

    def test_pending_or_failed_attempt_blocks_repeat_success(self):
        plan = validate(definition('has-repeat', repeat=dict(count=2)))
        digest = self.store.save(plan)['revision']
        claim, _ = self.store.claim(plan, digest, self.slot, {})
        self.store.begin_attempt(claim, 0)
        with self.assertRaises(ScheduleError):
            self.store.begin_attempt(claim, 1)
        with self.assertRaises(ScheduleError):
            self.store.finish(claim, 'success')
        self.store.record_result(claim, 0, dict(status='failed'))
        with self.assertRaises(ScheduleError):
            self.store.begin_attempt(claim, 1)

    def test_receipt_never_exceeds_saved_repeat_or_claims_an_incomplete_success(self):
        plan = validate(definition('twice', repeat=dict(count=2)))
        digest = self.store.save(plan)['revision']
        claim, _ = self.store.claim(plan, digest, self.slot, {})
        self.store.begin_attempt(claim, 0)
        self.store.record_result(claim, 0, dict(status='success'))
        with self.assertRaises(ScheduleError):
            self.store.finish(claim, 'success')
        self.store.begin_attempt(claim, 1)
        self.store.record_result(claim, 1, dict(status='success'))
        with self.assertRaises(ScheduleError):
            self.store.begin_attempt(claim, 2)
        self.store.finish(claim, 'success')

    def test_conflicting_success_cache_is_preserved_without_replay(self):
        claim, _ = self.store.claim(self.plan, self.digest, self.slot, {})
        self.store.begin_attempt(claim, 0)
        self.store.record_result(claim, 0, dict(status='success'))
        self.store.finish(claim, 'success')
        path = self.store._receipt_path(claim.key)
        data = json.loads(path.read_text('utf8'))
        data['attempts'][0]['result']['status'] = 'failed'
        before = json.dumps(data).encode('utf8'); path.write_bytes(before)
        with self.assertRaises(ScheduleError):
            self.store.claim(self.plan, self.digest, self.slot, {})
        self.assertEqual(path.read_bytes(), before)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = ScheduleStore(self.root)
        self.clock = Clock()
        self.events = []
        self.schedulers, self.runners = [], []
        self.addCleanup(self.cleanup_workers)

    def cleanup_workers(self):
        for runner in self.runners:
            runner.release.set()
        for scheduler in self.schedulers:
            scheduler.stop(wait=True, timeout=2)

    def build(self, *runners, plan=None, start=True):
        self.runners.extend(runners)
        plan = plan or definition()
        self.store.save(plan)
        executor = FakeExecutor(*runners)
        scheduler = Scheduler(self.store, executor, clock=self.clock, emit=self.events.append,
                              monotonic=lambda: self.clock.seconds)
        self.schedulers.append(scheduler)
        scheduler.enable(plan['id'])
        if start:
            scheduler.start()
        return scheduler, executor

    def fire(self, scheduler):
        self.clock.set()
        scheduler.tick()

    def test_save_enable_construction_and_start_minute_do_not_execute(self):
        self.clock.set()
        scheduler, executor = self.build(start=False)
        scheduler.tick()
        self.assertFalse(scheduler.snapshot()['started'])
        scheduler.start(); scheduler.tick()
        self.assertEqual(executor.created, [])
        self.assertEqual(self.store.receipts(), [])
        self.clock.set(minute=1); scheduler.tick()
        self.assertEqual(executor.created, [])

    def test_current_slot_runs_once_and_public_state_excludes_private_content(self):
        scheduler, executor = self.build()
        self.fire(scheduler)
        self.assertTrue(scheduler.wait_idle(2))
        scheduler.tick(); scheduler.tick()
        self.assertEqual(len(executor.created), 1)
        self.assertEqual(executor.created[0].calls, 1)
        self.assertEqual(scheduler.snapshot()['last']['status'], 'success')
        public = json.dumps([scheduler.snapshot(), self.events])
        self.assertNotIn('synthetic-private', public)
        self.assertNotIn('manifest', public)
        self.assertNotIn('target', public)
        self.assertEqual(executor.frozen[0]['repeat']['count'], 1)

    def test_notification_child_types_status_and_counts_remain_distinct_from_game(self):
        class NotificationRunner(FakeRunner):
            def run(self):
                for status in ('accepted', 'unknown', 'rejected'):
                    self.emit(dict(type='notification_result', status=status, profile='synthetic-private-profile',
                                   provider='synthetic-private-provider', error='synthetic-private-UID100000001'))
                self.emit(dict(type='notification_phase', status='running', game_status='success',
                               requested_profiles=3, profile='synthetic-private-profile'))
                self.emit(dict(type='notification_summary', status='partial', profiles=3,
                               requested_profiles=3, accepted=1, report={'uid': 'synthetic-private-UID100000001'}))
                return super().run()
        scheduler, executor = self.build(NotificationRunner())
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        children = [event for event in self.events if event['type'] == 'schedule_child']
        results = [event for event in children if event['child_type'] == 'notification_result']
        self.assertEqual([event['status'] for event in results], ['accepted', 'unknown', 'rejected'])
        phase = next(event for event in children if event['child_type'] == 'notification_phase')
        self.assertEqual(phase['game_status'], 'success')
        summary = next(event for event in children if event['child_type'] == 'notification_summary')
        self.assertEqual((summary['status'], summary['profiles'], summary['requested_profiles'], summary['accepted']),
                         ('partial', 3, 3, 1))
        self.assertEqual(scheduler.snapshot()['last']['status'], 'success')
        self.assertNotIn('synthetic-private', json.dumps([scheduler.snapshot(), self.events]))

    def test_unknown_child_types_and_invalid_notification_values_do_not_leak(self):
        class InvalidEventsRunner(FakeRunner):
            def run(self):
                self.emit(dict(type='synthetic-private-UID100000001', status='accepted', profiles=1))
                self.emit(dict(type='log', message='synthetic-private-UID100000001'))
                self.emit(dict(type='notification_summary', status='synthetic-private-status',
                               game_status='accepted', profiles=True, requested_profiles=-1, accepted='2',
                               manifest={'uid': 'synthetic-private-UID100000001'}, path='synthetic-private-path'))
                self.emit(dict(type='notification_summary', status='filtered', profiles=0,
                               requested_profiles=0, accepted=0, game_status='stopped'))
                return super().run()
        scheduler, executor = self.build(InvalidEventsRunner())
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        children = [event for event in self.events if event['type'] == 'schedule_child']
        self.assertEqual(len(children), 2)
        first, second = children
        self.assertEqual(first['child_type'], 'notification_summary')
        self.assertFalse(set(first) & {'status', 'game_status', 'profiles', 'requested_profiles', 'accepted'})
        self.assertEqual((second['status'], second['game_status'], second['profiles'],
                          second['requested_profiles'], second['accepted']), ('filtered', 'stopped', 0, 0, 0))
        self.assertNotIn('synthetic-private', json.dumps([scheduler.snapshot(), self.events]))

    def test_sleep_missed_minutes_and_backward_clock_never_backfill(self):
        scheduler, executor = self.build()
        self.clock.set(minute=5); scheduler.tick()
        self.assertEqual(executor.created, [])
        self.clock.set(); scheduler.tick()
        self.assertTrue(scheduler.wait_idle(2))
        self.clock.set(hour=3, minute=58); scheduler.tick()
        self.clock.set(); scheduler.tick()
        self.assertEqual(len(executor.created), 1)

    def test_restarting_controller_does_not_restore_enable_or_replay_slot(self):
        scheduler, executor = self.build()
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2)); scheduler.stop()
        fresh = Scheduler(self.store, executor, clock=self.clock)
        self.schedulers.append(fresh)
        self.assertEqual(fresh.snapshot()['enabled_ids'], [])
        self.clock.set(hour=3, minute=59)
        fresh.enable('synthetic'); fresh.start()
        self.fire(fresh); self.assertTrue(fresh.wait_idle(2))
        self.assertEqual(len(executor.created), 1)

    def test_bounded_repeat_shares_frozen_manifest_and_stops_after_failure(self):
        first, second = FakeRunner(), FakeRunner(status='failed')
        scheduler, executor = self.build(first, second, plan=definition(repeat=dict(count=3)))
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(len(executor.created), 2)
        self.assertEqual(executor.verified[0], executor.verified[1])
        receipt = self.store.receipts()[0]
        self.assertEqual([row['status'] for row in receipt['attempts']], ['success', 'failed'])
        self.assertEqual(scheduler.snapshot()['last']['completed'], 1)

    def test_successful_finite_repeat_creates_exact_count(self):
        scheduler, executor = self.build(plan=definition(repeat=dict(count=3)))
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(len(executor.created), 3)
        self.assertEqual(scheduler.snapshot()['last']['status'], 'success')
        self.assertEqual(scheduler.snapshot()['last']['completed'], 3)

    def test_changed_manifest_and_changed_plan_never_construct_runner(self):
        scheduler, executor = self.build()
        executor.changed = True
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(executor.created, [])
        self.assertEqual(scheduler.snapshot()['last']['reason'], 'target_unverified')
        self.store.save(dict(definition(), name='saved-new-version'), replace=True)
        self.clock.set(days=1); scheduler.tick()
        self.assertEqual(scheduler.snapshot()['enabled_ids'], [])
        self.assertEqual(executor.created, [])

    def test_unsaved_report_remains_unknown_and_blocks_repeats(self):
        scheduler, executor = self.build(FakeRunner(saved=False), plan=definition(repeat=dict(count=2)))
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(len(executor.created), 1)
        receipt = self.store.receipts()[0]
        self.assertEqual(receipt['status'], 'unknown')
        self.assertEqual(receipt['attempts'][0]['result']['game_status'], 'success')

    def test_dispatcher_report_reference_is_kept_privately_and_never_emitted(self):
        runner = FakeRunner()
        runner.schedule_source = dict(report_path='synthetic-private-path/report.json',
                                      sha256='a' * 64, size=123, operation='synthetic_local')
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        receipt = self.store.receipts()[0]
        self.assertEqual(receipt['attempts'][0]['result']['source'], runner.schedule_source)
        self.assertNotIn('synthetic-private', json.dumps([scheduler.snapshot(), self.events]))
        self.assertNotIn('a' * 64, json.dumps([scheduler.snapshot(), self.events]))

    def test_existing_but_invalid_report_reference_prevents_verified_success(self):
        invalid = [None, dict(report_path='fake/report.json', sha256='bad', size=1, operation='synthetic_local'),
                   dict(report_path='fake/report.json', sha256='a' * 64, size=True, operation='synthetic_local'),
                   dict(report_path='fake/report.json', sha256='a' * 64, size=1, operation='another_task')]
        for index, source in enumerate(invalid):
            runner = FakeRunner(); runner.schedule_source = source
            self.clock.set(hour=3, minute=59)
            scheduler, executor = self.build(runner, plan=definition('source-' + str(index)))
            self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
            self.assertEqual(scheduler.snapshot()['last']['status'], 'unknown')
            self.assertEqual(len(executor.created), 1)

    def test_write_failure_before_attempt_constructs_nothing_and_never_retries_slot(self):
        scheduler, executor = self.build()
        with patch.object(self.store, 'begin_attempt', side_effect=OSError('synthetic disk error')):
            self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        scheduler.tick()
        self.assertEqual(executor.created, [])
        self.assertEqual(self.store.receipts()[0]['status'], 'unknown')

    def test_intention_and_attempt_are_durable_before_executor_constructs_runner(self):
        scheduler, executor = self.build()
        create = executor.create
        def inspect_before_create(*args):
            receipt = self.store.receipts()[0]
            self.assertEqual(receipt['status'], 'running')
            self.assertEqual(receipt['attempts'], [dict(index=0, status='pending', result={})])
            return create(*args)
        executor.create = inspect_before_create
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(len(executor.created), 1)

    def test_existing_unfinished_slot_is_public_unknown_and_not_replayed(self):
        scheduler, executor = self.build()
        plan, digest = self.store.load('synthetic')
        self.store.claim(plan, digest, datetime(2026, 10, 30, 4, tzinfo=CHINA), {})
        self.fire(scheduler)
        self.assertEqual(executor.created, [])
        self.assertTrue(any(event.get('type') == 'schedule_reused' and event.get('status') == 'unknown'
                            for event in self.events))

    def test_external_conflict_always_skips_without_stop_even_when_stop_owned(self):
        scheduler, executor = self.build(plan=definition(conflict='stop_owned'))
        executor.external_busy = True
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(executor.created, [])
        self.assertEqual(scheduler.snapshot()['last']['reason'], 'external_runner_busy')

    def test_active_conflict_skip_consumes_only_new_slot(self):
        runner = FakeRunner(block=True)
        scheduler, executor = self.build(runner)
        self.store.save(definition('second', time='04:01'))
        scheduler.enable('second')
        self.fire(scheduler)
        self.assertTrue(runner.started.wait(2))
        self.clock.set(minute=1); scheduler.tick()
        self.assertEqual(len(executor.created), 1)
        receipts = {row['plan_id']: row for row in self.store.receipts()}
        self.assertEqual(receipts['synthetic']['status'], 'running')
        self.assertEqual(receipts['second']['status'], 'skipped')
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))

    def test_stop_owned_waits_for_actual_exit_before_creating_next(self):
        runner = FakeRunner(block=True, auto_release=False)
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        self.store.save(definition('second', time='04:01', conflict='stop_owned'))
        scheduler.enable('second')
        self.clock.set(minute=1); scheduler.tick()
        self.assertTrue(runner.stopped.wait(2))
        self.assertEqual(len(executor.created), 1)
        self.assertIsNotNone(scheduler.snapshot()['pending'])
        self.assertFalse(scheduler.wait_idle(0))
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(len(executor.created), 2)
        self.assertEqual(scheduler.snapshot()['last']['id'], 'second')
        self.assertTrue(scheduler.snapshot()['running'])

    def test_child_stop_without_owned_reason_stops_future_scheduling(self):
        for saved in (True, False):
            with self.subTest(saved=saved):
                directory = self.root / ('saved' if saved else 'unsaved')
                store = ScheduleStore(directory)
                store.save(definition())
                executor = FakeExecutor(FakeRunner(status='stopped', saved=saved))
                self.clock.set(hour=3, minute=59)
                scheduler = Scheduler(store, executor, clock=self.clock)
                self.schedulers.append(scheduler)
                scheduler.enable('synthetic'); scheduler.start()
                self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
                self.assertFalse(scheduler.snapshot()['running'])
                self.assertEqual(store.receipts()[0]['status'], 'stopped' if saved else 'unknown')
                self.assertEqual(scheduler.snapshot()['enabled_ids'], ['synthetic'])
                self.clock.set(days=1); scheduler.tick()
                self.assertEqual(len(executor.created), 1)
                scheduler.start(); scheduler.tick()
                self.assertEqual(len(executor.created), 1)  # Restart minute is still skipped.

    def test_adapter_stop_hint_stops_future_work_even_if_report_validation_raises(self):
        class InvalidStoppedReport(FakeRunner):
            schedule_stopped = True
            def run(self):
                self.calls += 1
                self.started.set()
                raise ScheduleError('synthetic stopped report is missing')
        scheduler, executor = self.build(InvalidStoppedReport(), plan=definition(repeat=dict(count=2)))
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        snapshot = scheduler.snapshot()
        self.assertFalse(snapshot['running'])
        self.assertIsNone(snapshot['pending'])
        self.assertEqual(snapshot['enabled_ids'], ['synthetic'])
        self.assertEqual(snapshot['last']['status'], 'unknown')
        self.assertEqual(self.store.receipts()[0]['status'], 'unknown')
        self.clock.set(days=1); scheduler.tick()
        self.assertEqual(len(executor.created), 1)

    def test_internal_replacement_with_stop_hint_and_bad_report_keeps_controller_running(self):
        class InvalidStoppedReport(FakeRunner):
            schedule_stopped = True
            def run(self):
                self.started.set()
                if not self.release.wait(3):
                    raise AssertionError('fake worker was not released')
                raise ScheduleError('synthetic stopped report is missing')
        runner = InvalidStoppedReport(block=True, auto_release=False)
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        self.store.save(definition('second', time='04:01', conflict='stop_owned'))
        scheduler.enable('second')
        self.clock.set(minute=1); scheduler.tick()
        self.assertTrue(runner.stopped.wait(2))
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))
        self.assertTrue(scheduler.snapshot()['running'])
        self.assertEqual(len(executor.created), 2)
        receipts = {row['plan_id']: row for row in self.store.receipts()}
        self.assertEqual(receipts['synthetic']['status'], 'unknown')
        self.assertEqual(receipts['second']['status'], 'success')

    def test_child_stop_is_latched_before_receipt_write_failure(self):
        runner = FakeRunner(status='stopped')
        runner.schedule_stopped = True
        scheduler, executor = self.build(runner)
        with patch.object(self.store, 'record_result', side_effect=OSError('synthetic receipt failure')):
            self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        snapshot = scheduler.snapshot()
        self.assertFalse(snapshot['running'])
        self.assertEqual(snapshot['enabled_ids'], ['synthetic'])
        self.assertEqual(snapshot['last']['status'], 'unknown')
        receipt = self.store.receipts()[0]
        self.assertEqual(receipt['status'], 'unknown')
        self.assertEqual(receipt['attempts'][0]['status'], 'pending')
        self.assertEqual(runner.status, 'stopped')
        self.clock.set(days=1); scheduler.tick()
        self.assertEqual(len(executor.created), 1)

    def test_internal_replacement_receipt_failure_does_not_latch_global_stop(self):
        runner = FakeRunner(block=True, auto_release=False)
        runner.schedule_stopped = True
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        self.store.save(definition('second', time='04:01', conflict='stop_owned'))
        scheduler.enable('second')
        record_result = self.store.record_result
        failures = []
        def fail_only_first(claim, index, summary):
            if not failures:
                failures.append(claim.key)
                raise OSError('synthetic first receipt failure')
            return record_result(claim, index, summary)
        with patch.object(self.store, 'record_result', side_effect=fail_only_first):
            self.clock.set(minute=1); scheduler.tick()
            self.assertTrue(runner.stopped.wait(2))
            self.assertEqual(len(executor.created), 1)
            runner.release.set(); self.assertTrue(scheduler.wait_idle(2))
        self.assertTrue(scheduler.snapshot()['running'])
        self.assertEqual(len(executor.created), 2)
        receipts = {row['plan_id']: row for row in self.store.receipts()}
        self.assertEqual(receipts['synthetic']['status'], 'unknown')
        self.assertEqual(receipts['synthetic']['attempts'][0]['status'], 'pending')
        self.assertEqual(receipts['second']['status'], 'success')

    def test_notification_control_stop_prevents_next_due_claim_and_preserves_game_success(self):
        runner = HeldNotificationRunner()
        before = deepcopy(runner.original_report)
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        self.store.save(definition('second', time='04:01'))
        scheduler.enable('second')
        runner.stop_requested = True  # F10 consumed inside the notification wrapper.
        self.clock.set(minute=1); scheduler.tick()
        self.assertFalse(scheduler.snapshot()['running'])
        self.assertIsNotNone(scheduler.snapshot()['active'])
        self.assertEqual(len(self.store.receipts()), 1)  # No claim for the newly due second job.
        self.assertEqual(len(executor.created), 1)
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))
        receipt = self.store.receipts()[0]
        self.assertEqual(receipt['status'], 'success')
        self.assertEqual(receipt['attempts'][0]['status'], 'success')
        self.assertEqual(receipt['reason'], 'controller_stopped')
        self.assertEqual(runner.original_report, before)
        self.clock.set(days=1); scheduler.tick()
        self.assertEqual(len(executor.created), 1)

    def test_owned_notification_replacement_does_not_global_stop_or_rewrite_success(self):
        runner = HeldNotificationRunner()
        before = deepcopy(runner.original_report)
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        self.store.save(definition('second', time='04:01', conflict='stop_owned'))
        scheduler.enable('second')
        self.clock.set(minute=1); scheduler.tick()
        self.assertTrue(runner.stop_requested)
        self.assertTrue(scheduler.snapshot()['running'])
        self.assertIsNotNone(scheduler.snapshot()['pending'])
        self.clock.set(minute=2); scheduler.tick()
        self.assertTrue(scheduler.snapshot()['running'])
        self.assertEqual(len(executor.created), 1)
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(len(executor.created), 2)
        receipts = {row['plan_id']: row for row in self.store.receipts()}
        self.assertEqual(receipts['synthetic']['status'], 'success')
        self.assertEqual(receipts['synthetic']['reason'], 'replaced_by_schedule')
        self.assertEqual(receipts['second']['status'], 'success')
        self.assertEqual(runner.original_report, before)

    def test_returned_and_exception_stop_requested_are_seen_without_later_tick(self):
        class CompletedNotification(HeldNotificationRunner):
            def __init__(self, invalid):
                super().__init__()
                self.invalid = invalid
            def run(self):
                self.stop_requested = True
                if self.invalid:
                    raise ScheduleError('synthetic notification control stop with invalid receipt')
                return deepcopy(self.original_report)
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                self.clock.set(hour=3, minute=59)
                scheduler, executor = self.build(CompletedNotification(invalid),
                    plan=definition('control-invalid' if invalid else 'control-success'))
                self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
                self.assertFalse(scheduler.snapshot()['running'])
                self.assertEqual(scheduler.snapshot()['last']['status'], 'unknown' if invalid else 'success')
                self.assertEqual(len(executor.created), 1)

    def test_control_stop_after_one_success_leaves_finite_repeat_partial(self):
        class CompletedNotification(HeldNotificationRunner):
            def run(self):
                self.stop_requested = True
                return deepcopy(self.original_report)
        scheduler, executor = self.build(CompletedNotification(), plan=definition(repeat=dict(count=2)))
        self.fire(scheduler); self.assertTrue(scheduler.wait_idle(2))
        self.assertFalse(scheduler.snapshot()['running'])
        self.assertEqual(len(executor.created), 1)
        receipt = self.store.receipts()[0]
        self.assertEqual(receipt['status'], 'partial')
        self.assertEqual([row['status'] for row in receipt['attempts']], ['success'])
        self.assertEqual(scheduler.snapshot()['last']['completed'], 1)

    def test_pause_resume_tracks_actual_runner_state_and_blocks_new_triggers(self):
        runner = FakeRunner(block=True)
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        scheduler.pause(); scheduler.pause()
        self.assertEqual(runner.pause_changes, [True])
        self.assertTrue(scheduler.snapshot()['paused'])
        scheduler.resume(); scheduler.resume()
        self.assertEqual(runner.pause_changes, [True, False])
        runner.paused = True; runner.emit(dict(type='paused', paused=True))
        scheduler.resume()
        self.assertEqual(runner.pause_changes, [True, False, False])
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))

    def test_pause_before_due_does_not_trigger_or_catch_up_after_minute(self):
        scheduler, executor = self.build()
        scheduler.pause(); self.fire(scheduler)
        self.clock.set(minute=1); scheduler.resume(); scheduler.tick()
        self.assertEqual(executor.created, [])
        self.assertEqual(self.store.receipts(), [])

    def test_stop_preserves_reference_until_runner_exits_and_cancels_pending(self):
        runner = FakeRunner(block=True, auto_release=False)
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        self.store.save(definition('second', time='04:01', conflict='stop_owned'))
        scheduler.enable('second'); self.clock.set(minute=1); scheduler.tick()
        scheduler.stop()
        self.assertTrue(scheduler.snapshot()['stopping'])
        self.assertIsNotNone(scheduler.snapshot()['active'])
        self.assertIsNone(scheduler.snapshot()['pending'])
        self.assertFalse(scheduler.wait_idle(0))
        with self.assertRaises(ScheduleError):
            scheduler.start()
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(len(executor.created), 1)

    def test_disable_leaves_active_alone_but_prevents_next_slot(self):
        runner = FakeRunner(block=True)
        scheduler, executor = self.build(runner)
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        scheduler.disable('synthetic')
        self.assertFalse(runner.stopped.is_set())
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))
        self.clock.set(days=1); scheduler.tick()
        self.assertEqual(len(executor.created), 1)

    def test_wall_timeout_is_checked_while_paused_and_waits_for_exit(self):
        runner = FakeRunner(block=True, auto_release=False)
        scheduler, executor = self.build(runner, plan=definition(timeout_seconds=10))
        self.fire(scheduler); self.assertTrue(runner.started.wait(2))
        scheduler.pause(); self.clock.seconds = 11; scheduler.tick()
        self.assertTrue(runner.stopped.is_set())
        self.assertFalse(scheduler.wait_idle(0))
        runner.release.set(); self.assertTrue(scheduler.wait_idle(2))
        self.assertEqual(scheduler.snapshot()['last']['reason'], 'timeout')
        self.assertEqual(len(executor.created), 1)


if __name__ == '__main__':
    unittest.main()
