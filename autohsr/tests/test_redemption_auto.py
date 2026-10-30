"""Automatic server binding through real flow; only fake files/registry/IO."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.config import Settings, SettingsError
from autohsr.models import AutomationError
from autohsr.redemption_codes import CatalogFetchError, from_values
from autohsr.redemption_run import RedemptionWorkflow, run_redemption
from autohsr.redemption_server import HYP_KEYS, UnknownServerError, resolve
from autohsr.redemption_settings import resolve_batch
from autohsr.redemption_store import RedemptionStore
from autohsr.windows import GameWindow
from autohsr.tests import test_redemption_run as flows


class AutoServerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cn = self.root / 'cn-client' / 'StarRail.exe'
        self.global_ = self.root / 'global-client' / 'StarRail.exe'
        for path in (self.cn, self.global_):
            path.parent.mkdir()
            path.write_bytes(b'fake game file, never executed')
        values = {HYP_KEYS[0][1]: str(self.cn.parent), HYP_KEYS[1][1]: str(self.global_.parent)}
        self.reader = Mock(side_effect=lambda key, name: values[key])
        self.store = RedemptionStore(self.root / 'ledger.json')

    def context(self, scenes, *, server='auto', executable=None):
        c = flows.context(self.root, scenes)
        c.settings.redemption_server = server
        # Deliberately stale cached path: resolution must use the live getter.
        c.window.path = str(self.cn)
        c.window.current_executable.return_value = str(executable or self.global_)
        return c

    def execute(self, c, *, server='global'):
        clock = SimpleNamespace(monotonic=lambda: c.clock.value)
        with patch('autohsr.redemption_run.time', clock), patch('autohsr.redemption_pages.time', clock), \
             patch('autohsr.redemption_server.resolve', side_effect=lambda path: resolve(path, reader=self.reader)):
            return run_redemption(c, batch=from_values([flows.CODE], server), store=self.store)

    def test_live_window_executable_selects_global_and_freezes_only_anonymous_proof(self):
        c = self.context(flows.sequence())
        self.assertEqual(self.execute(c).status, 'ok')
        data = c.report.redemption
        self.assertEqual((data['server_selection'], data['server']), ('auto', 'global'))
        self.assertEqual(data['server_resolution']['server'], 'global')
        self.assertEqual(data['source']['server_resolution'], data['server_resolution'])
        self.assertEqual(self.reader.call_count, 2)  # Binding checks do not re-read registry.
        self.assertGreater(c.window.current_executable.call_count, 2)
        self.assertNotIn(str(self.cn), json.dumps(data))
        self.assertNotIn(str(self.global_), json.dumps(data))
        self.assertEqual(self.store.lookup(data['account_key'], 'global', flows.CODE)['status'], 'redeemed')
        self.assertIsNone(self.store.lookup(data['account_key'], 'cn', flows.CODE))

    def test_injected_wrong_server_is_rejected_before_capture_or_input(self):
        c = self.context([])
        c.snapshot = Mock(side_effect=AssertionError('no capture before rejecting stale batch'))
        with self.assertRaises(AutomationError):
            self.execute(c, server='cn')
        c.snapshot.assert_not_called()
        c.window.click.assert_not_called()
        c.window.type_redemption_code.assert_not_called()

    def test_wrong_explicit_batch_also_cannot_silently_override_selection(self):
        c = self.context([], server='cn')
        c.snapshot = Mock(side_effect=AssertionError('no capture'))
        with patch('autohsr.redemption_server.resolve', side_effect=AssertionError('explicit server must not probe')):
            with self.assertRaises(AutomationError):
                run_redemption(c, batch=from_values([flows.CODE], 'global'), store=self.store)
        c.snapshot.assert_not_called()

    def test_explicit_selection_preserves_flow_without_new_metadata_probe(self):
        c = self.context(flows.sequence(), server='cn')
        c.window.current_executable.side_effect = AssertionError('explicit mode must not use new live getter')
        clock = SimpleNamespace(monotonic=lambda: c.clock.value)
        with patch('autohsr.redemption_run.time', clock), patch('autohsr.redemption_pages.time', clock), \
             patch('autohsr.redemption_server.resolve', side_effect=AssertionError('no registry probe')):
            self.assertEqual(run_redemption(c, batch=from_values([flows.CODE], 'cn'), store=self.store).status, 'ok')
        c.window.current_executable.assert_not_called()
        self.assertIsNone(c.report.redemption['server_resolution'])

    def test_changed_live_executable_during_typing_discards_remaining_characters(self):
        c = self.context(flows.sequence())
        typed = []
        def partial(code, geometry, *, checkpoint):
            checkpoint()
            typed.append(code[0])
            c.window.current_executable.return_value = str(self.cn)
            checkpoint()
            typed.append(code[1:])
        c.window.type_redemption_code.side_effect = partial
        with self.assertRaises(UnknownServerError):
            self.execute(c)
        self.assertEqual(typed, [flows.CODE[0]])
        self.assertEqual(c.window.click.call_count, 3)
        self.assertNotIn('submit_code', [action['intent'] for action in c.report.redemption['actions']])

    def test_unknown_resolution_does_not_default_to_cn_or_fetch_or_capture(self):
        c = self.context([])
        with patch('autohsr.redemption_server.resolve', side_effect=UnknownServerError('ambiguous')), \
             patch('autohsr.redemption_codes.fetch_catalog', side_effect=AssertionError('no fetch')):
            with self.assertRaises(UnknownServerError):
                run_redemption(c, store=self.store)
        self.assertEqual(c.report.redemption, {})
        c.window.click.assert_not_called()

    def test_existing_session_blocks_before_registry_or_fetch(self):
        c = self.context([])
        c.report.redemption = {'status': 'partial', 'original': 'retained'}
        with patch('autohsr.redemption_server.resolve', side_effect=AssertionError('no probing old batch')), \
             patch('autohsr.redemption_codes.fetch_catalog', side_effect=AssertionError('no fetch')):
            with self.assertRaises(AutomationError):
                run_redemption(c)
        self.assertEqual(c.report.redemption['original'], 'retained')

    def test_wrong_scope_or_missing_run_directory_never_probes_installation(self):
        for mode in ('reward_only', 'check', 'daily_disabled', 'missing_run'):
            with self.subTest(mode=mode):
                c = self.context([])
                if mode == 'daily_disabled':
                    c.report.operation = 'daily'
                    c.settings.redemption_enabled = False
                elif mode == 'missing_run':
                    c.report.run_dir = ''
                else:
                    c.report.operation = mode
                with patch('autohsr.redemption_server.resolve', side_effect=AssertionError('no registry probe')):
                    with self.assertRaises(AutomationError):
                        run_redemption(c, store=self.store)
                c.window.current_executable.assert_not_called()
                c.window.click.assert_not_called()

    def test_frozen_proof_corruption_blocks_before_input(self):
        c = self.context([])
        with patch('autohsr.redemption_server.resolve', side_effect=lambda path: resolve(path, reader=self.reader)):
            workflow = RedemptionWorkflow(c, batch=from_values([flows.CODE], 'global'), store=self.store)
        workflow.data['server_resolution']['source_digest'] = '0' * 64
        with self.assertRaises(AutomationError):
            workflow.require_server_binding()
        c.window.click.assert_not_called()

    def test_save_task_tree_and_schedule_do_not_resolve_auto(self):
        from autohsr.task_workflow import compile_recipe, task_spec
        from autohsr.schedule_dispatch import NativeScheduleExecutor
        from autohsr.schedule_plan import validate
        settings = Settings(redemption_enabled=True, redemption_source='manual', redemption_server='auto', redemption_codes=['Case7'])
        node = dict(id='codes', type='task', task='daily', params=dict(tasks=['redemption']))
        with patch('autohsr.redemption_server.resolve', side_effect=AssertionError('not a runtime probe')):
            settings.save(self.root / 'config.json')
            recipe = compile_recipe(dict(version=1, name='fixture', steps=[node]))
            copied, _ = task_spec(settings, recipe.steps[0], recipe.base_dir)
            self.assertEqual(copied.redemption_server, 'auto')
            executor = NativeScheduleExecutor(settings, base_dir=self.root, run_root=self.root / 'runs', busy_probe=lambda: False)
            plan = validate(dict(version=1, id='fixture', name='fixture', time='08:30', weekdays=[1],
                target=dict(type='task', task='daily', params=node['params'])))
            manifest = executor.freeze(plan)
            self.assertEqual(manifest['settings']['redemption_server'], 'auto')
            self.assertTrue(executor.revalidate(manifest))

    def test_batch_requires_typed_proof_and_filters_fallback_with_resolved_server(self):
        settings = Settings(redemption_server='auto', redemption_source='online')
        with patch('autohsr.redemption_codes.fetch_catalog', side_effect=AssertionError('no unresolved request')):
            with self.assertRaises(SettingsError):
                resolve_batch(settings)
        resolution = resolve(str(self.global_), reader=self.reader)
        with patch('autohsr.redemption_codes.fetch_catalog', side_effect=CatalogFetchError([])) as fetch:
            batch = resolve_batch(settings, server_resolution=resolution)
        self.assertEqual(fetch.call_args.args[0], 'global')
        self.assertEqual(batch.server, 'global')
        self.assertTrue(batch.source['fallback'])
        self.assertEqual(batch.source['server_resolution'], resolution.to_dict())
        self.assertEqual(settings.redemption_server, 'auto')

    def test_preview_rejects_auto_before_config_registry_network_or_file_read(self):
        from autohsr.__main__ import main
        for args in (['--redemption-check', 'missing'], ['--redemption-fetch']):
            with self.subTest(args=args), patch.object(Settings, 'load', side_effect=AssertionError('no config')), \
                patch('autohsr.redemption_server.resolve', side_effect=AssertionError('no registry')), \
                patch('autohsr.redemption_codes.fetch_catalog', side_effect=AssertionError('no network')), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main([*args, '--redemption-server', 'auto'])

    def test_native_cli_keeps_auto_as_runtime_choice_without_saving(self):
        from autohsr.__main__ import main
        path = self.root / 'config.json'
        Settings().save(path)
        original = path.read_bytes()
        fake = Mock()
        fake.run.return_value = {'status': 'success', 'operation': 'redemption'}
        with patch('autohsr.app.Runner', return_value=fake) as factory, \
            patch('autohsr.redemption_server.resolve', side_effect=AssertionError('CLI construction is not a probe')), \
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--redeem-codes', '--config', str(path), '--redemption-code', 'Code7', '--redemption-server', 'auto']), 0)
        self.assertEqual(factory.call_args.args[0].redemption_server, 'auto')
        self.assertEqual(path.read_bytes(), original)

    def test_window_getter_uses_live_process_metadata_and_rejects_unreadable_source(self):
        window = GameWindow.__new__(GameWindow)
        window.hwnd, window.path, window.guard = 123, 'stale-cache-value', Mock()
        with patch('autohsr.windows.process_path', return_value=str(self.global_)) as query:
            self.assertEqual(window.current_executable(), str(self.global_))
        query.assert_called_once_with(123)
        window.guard.assert_called_once()
        with patch('autohsr.windows.process_path', return_value=''), self.assertRaises(AutomationError):
            window.current_executable()
