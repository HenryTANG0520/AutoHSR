"""Offline contract checks for the selected page preview pilot."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from unittest import TestCase
from unittest.mock import patch

from autohsr.__main__ import main
from autohsr.task_capabilities import CapabilityError, SCREEN_CHECK_PLAN, SCREEN_CHECK_PLAN_VERSION, TaskCapabilities
from autohsr.task_workflow import WORKFLOW_PAGES


class TaskCapabilityTests(TestCase):
    def setUp(self):
        self.service = TaskCapabilities(enabled={SCREEN_CHECK_PLAN})

    def test_discovery_describes_the_version_and_strict_json_objects(self):
        descriptor, = json.loads(json.dumps(self.service.discover()))
        self.assertEqual((descriptor['id'], descriptor['version']), ('autohsr.screen_check_plan', 1))
        self.assertIs(descriptor['read_only'], True)
        self.assertIs(descriptor['enabled'], True)
        for schema in (descriptor['input_schema'], descriptor['output_schema']):
            self.assertEqual(schema['type'], 'object')
            self.assertIs(schema['additionalProperties'], False)
            self.assertEqual(set(schema['required']), set(schema['properties']))
        pages = descriptor['input_schema']['properties']['pages']
        self.assertEqual(pages['items']['enum'], list(WORKFLOW_PAGES))
        self.assertIs(pages['uniqueItems'], True)

    def test_disabled_unknown_and_unsupported_calls_never_compile(self):
        disabled = TaskCapabilities(enabled={'some_other_capability'})
        self.assertIs(disabled.discover()[0]['enabled'], False)
        with patch('autohsr.selected_page_check.build_recipe') as build:
            for service, name, version, code in (
                (disabled, SCREEN_CHECK_PLAN, 1, 'disabled'),
                (self.service, 'unknown', 1, 'unknown_capability'),
                (self.service, SCREEN_CHECK_PLAN, 2, 'unsupported_version'),
                (self.service, SCREEN_CHECK_PLAN, True, 'unsupported_version'),
            ):
                with self.subTest(name=name, version=version, code=code), self.assertRaises(CapabilityError) as failure:
                    service.dispatch(name, version, {'pages': ['mail']})
                self.assertEqual(failure.exception.code, code)
            build.assert_not_called()

    def test_validation_rejects_extra_fields_and_keeps_existing_page_rules(self):
        for arguments in (None, {}, {'pages': 'mail'}, {'pages': ('mail',)}, {'pages': ['mail'], 'config': 'extra'},
                          {'pages': []}, {'pages': ['mail', 'mail']}, {'pages': ['unknown']}, {'pages': [{}]},
                          {'pages': ['odyssey', 'mail']}, {'pages': ['reward_guide', 'odyssey']},
                          {'pages': ['messages', 'mail']}):
            with self.subTest(arguments=arguments), self.assertRaises(CapabilityError) as failure:
                self.service.dispatch(SCREEN_CHECK_PLAN, SCREEN_CHECK_PLAN_VERSION, arguments)
            self.assertEqual(failure.exception.code, 'invalid_arguments')

    def test_cli_and_capability_return_the_same_existing_preview(self):
        pages = ['mail', 'phone', 'odyssey', 'reward_guide']
        expected = dict(status='success', mode='preview', pages=pages,
                        reservations=dict(daily_calls=0, du_calls=0, currency_calls=0, du_runs=0,
                                          currency_games=0, executions=4), game_accessed=False)
        with patch('autohsr.config.Settings.load') as load, patch('autohsr.task_workflow_run.TaskWorkflowRunner') as run, \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(self.service.dispatch(SCREEN_CHECK_PLAN, SCREEN_CHECK_PLAN_VERSION, {'pages': pages}),
                             expected)
            self.assertEqual(main(['--screen-check-plan', *pages]), 0)
        self.assertEqual(json.loads(output.getvalue()), expected)
        self.assertEqual(errors.getvalue(), '')
        load.assert_not_called()
        run.assert_not_called()

    def test_cli_maps_dispatch_errors_to_existing_failure_output(self):
        for service, pages, message in (
            (self.service, ['odyssey', 'mail'], '活动页面须放在末尾，并按巡星之礼、奖励指南的顺序排列。'),
            (TaskCapabilities(enabled=set()), ['mail'], '所选页面核对预览已禁用。'),
        ):
            with self.subTest(pages=pages), patch('autohsr.task_workflow_cli._TASK_CAPABILITIES', service), \
                    redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(main(['--screen-check-plan', *pages]), 2)
            self.assertEqual(output.getvalue(), '')
            self.assertEqual(json.loads(errors.getvalue()), dict(status='failed', error=message))
