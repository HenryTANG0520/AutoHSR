"""Exercise the formal CLI without opening a game, GUI, or image source."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from autohsr.__main__ import main
from autohsr.config import Settings
from autohsr.task_workflow import read


_OPT_IN = '--workflow-yaml-native-vision'
_NOTIFY_PROFILE = '--workflow-yaml-notify-profile'
_IMPORT = '--task-workflow-convert-yaml'
_DESTINATION = '--workflow-json-destination'


class WorkflowYamlCliTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.source = self.root / 'workflow.yml'
        self.destination = self.root / 'converted.json'
        self.image = self.root / 'templates' / '提示.PNG'
        self.raw = (
            'name: 命令行转换\nsteps:\n'
            '- type: find_image\n'
            '  template_path: templates/提示.PNG\n'
            '- type: if\n'
            '  condition_type: text_not_exists\n'
            '  text: 继续\n'
            '  children: [{type: wait, seconds: 0}]\n'
        ).encode('utf-8')
        self.source.write_bytes(self.raw)

    def invoke(self, *arguments):
        out, error = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(error):
            try:
                code = main(list(arguments))
            except SystemExit as result:
                code = result.code
        return code, out.getvalue(), error.getvalue()

    def forbid_io(self, stack, watched):
        def guarded(operation):
            def checked(path, *args, **kwargs):
                self.assertNotIn(path, watched, f'unexpected path access: {path}')
                return operation(path, *args, **kwargs)
            return checked

        for name in ('open', 'stat', 'lstat', 'resolve'):
            stack.enter_context(patch.object(Path, name, guarded(getattr(Path, name))))
        stack.enter_context(patch.object(Settings, 'load', side_effect=AssertionError('unexpected config load')))
        stack.enter_context(patch('autohsr.app.find_game', side_effect=AssertionError('unexpected game lookup')))
        stack.enter_context(patch('autohsr.gui.main', side_effect=AssertionError('unexpected GUI launch')))

    def test_help_names_the_conversion_only_opt_in(self):
        code, help_text, error = self.invoke('--help')
        self.assertEqual((code, error), (0, ''))
        self.assertIn(_OPT_IN, help_text)
        self.assertIn('仅用于 ' + _IMPORT, help_text)
        self.assertIn('双帧图文规则，默认关闭', help_text)
        self.assertIn(_NOTIFY_PROFILE, help_text)
        self.assertIn('不授权发送', help_text)

    def test_default_rejects_and_opt_in_exclusively_publishes_a_native_definition(self):
        with ExitStack() as stack:
            self.forbid_io(stack, {self.image})
            code, out, error = self.invoke(_IMPORT, str(self.source), _DESTINATION, str(self.destination))
            self.assertEqual((code, out), (2, ''))
            self.assertIn('模板匹配', json.loads(error)['error'])
            self.assertFalse(self.destination.exists())

            args = (_OPT_IN, f'{_IMPORT}={self.source}', f'{_DESTINATION}={self.destination}')
            code, out, error = self.invoke(*args)
            self.assertEqual((code, error), (0, ''))
            result = json.loads(out)
            self.assertEqual((result['status'], result['mode'], Path(result['path'])),
                             ('success', 'convert_yaml', self.destination))
            original_output = self.destination.read_bytes()
            self.assertEqual(result['sha256'], hashlib.sha256(original_output).hexdigest())
            image, branch = read(self.destination)['steps']
            self.assertEqual(image['task'], 'workflow_game_image')
            self.assertEqual(Path(image['params']['template']), self.image)
            self.assertEqual(branch['screen_condition']['task'], 'workflow_game_text')
            self.assertIs(branch['screen_condition']['value'], False)

            code, out, error = self.invoke(*args)
            self.assertEqual((code, out), (2, ''))
            self.assertEqual(json.loads(error)['status'], 'failed')
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertEqual(self.destination.read_bytes(), original_output)
        self.assertFalse(self.image.exists())

    def test_flag_with_other_modes_is_rejected_before_dispatch_and_target_access(self):
        other = self.root / 'other.json'
        bundle = self.root / 'other.zip'
        modes = (
            (),
            (_DESTINATION, str(self.destination)),
            ('--task-workflow', str(other)),
            ('--task-workflow-check', str(other)),
            ('--task-workflow-import', str(bundle), '--workflow-bundle-destination', str(self.root / 'extracted')),
            ('--task-workflow-export', str(other), '--workflow-bundle-destination', str(bundle)),
            ('--challenge-check', str(other)),
            ('--schedule-check', str(other)),
            ('--notify-profile-check', str(other)),
            ('--redemption-check', str(other), '--redemption-server', 'cn'),
            ('--warp-analysis', '--warp-import', str(other)),
            ('--launch', '--config', str(other)),
        )
        with ExitStack() as stack:
            self.forbid_io(stack, {self.source, self.destination, other, bundle, self.root / 'extracted'})
            for module in ('challenge_cli', 'schedule_cli', 'notify_cli', 'redemption_cli', 'warp_cli'):
                stack.enter_context(patch(f'autohsr.{module}.dispatch',
                                          side_effect=AssertionError(f'unexpected dispatch: {module}')))
            for args in modes:
                for flag in ((_OPT_IN,), (_NOTIFY_PROFILE, 'manual-test')):
                    with self.subTest(args=args, flag=flag[0]):
                        code, out, error = self.invoke(*args, *flag)
                        self.assertEqual((code, out), (2, ''))
                        self.assertIn(f'{flag[0]} 仅用于 {_IMPORT}', error.splitlines()[-1])

    def test_invalid_yaml_combinations_do_not_reach_either_file(self):
        other = self.root / 'settings.json'
        base = (_IMPORT, str(self.source), _DESTINATION, str(self.destination))
        cases = (
            ((_IMPORT, str(self.source), _OPT_IN), '指定新的 JSON'),
            ((*base, _OPT_IN, '--config', str(other)), '不能与其他运行参数混用'),
            ((*base, _OPT_IN, '--workflow-step-path', '0'), '不能与其他运行参数混用'),
            ((*base, _OPT_IN, '--workflow-allow-notify'), '不能与其他运行参数混用'),
            ((*base, _OPT_IN, '--workflow-bundle-destination', str(other)), '不能与其他运行参数混用'),
            ((*base, f'{_OPT_IN}=true'), _OPT_IN),
            ((*base, _NOTIFY_PROFILE, 'one', f'{_NOTIFY_PROFILE}=two'), '只能绑定一个通知方案'),
            ((*base, _NOTIFY_PROFILE, 'manual-test', '--workflow-allow-notify'), '不能与其他运行参数混用'),
            ((*base, _NOTIFY_PROFILE, 'manual-test', '--notify-profile', 'other'), '不能与其他运行参数混用'),
        )
        with ExitStack() as stack:
            self.forbid_io(stack, {self.source, self.destination, other})
            for args, message in cases:
                with self.subTest(args=args):
                    code, out, error = self.invoke(*args)
                    self.assertEqual((code, out), (2, ''))
                    self.assertIn(message, error.splitlines()[-1])
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertFalse(self.destination.exists())

    def test_notification_conversion_and_check_are_offline_and_binding_cannot_authorize_run(self):
        message = 'ONLY_IN_DRAFT\n下一行  正文'
        raw = ('name: 通知流程\nsteps: [{type: send_message, text: '
               + json.dumps(message, ensure_ascii=False) + '}]\n').encode('utf-8')
        self.source.write_bytes(raw)
        args = (_IMPORT, str(self.source), _DESTINATION, str(self.destination))
        with ExitStack() as stack:
            self.forbid_io(stack, set())
            for target in ('autohsr.notify_profiles.ProfileStore.load_version', 'autohsr.notify_http.request',
                           'autohsr.workflow_notify.send_step', 'autohsr.task_workflow_run.freeze_step_notifications'):
                stack.enter_context(patch(target, side_effect=AssertionError(f'unexpected notification access: {target}')))
            code, out, error = self.invoke(*args)
            self.assertEqual((code, out), (2, ''))
            self.assertIn('步骤 0（send_message）', json.loads(error)['error'])
            self.assertNotIn('ONLY_IN_DRAFT', error)
            self.assertFalse(self.destination.exists())

            code, out, error = self.invoke(*args, _OPT_IN, f'{_NOTIFY_PROFILE}=manual-test')
            self.assertEqual((code, error), (0, ''))
            self.assertEqual(json.loads(out)['mode'], 'convert_yaml')
            self.assertNotIn('ONLY_IN_DRAFT', out)
            self.assertEqual(read(self.destination)['steps'][0]['params'], dict(profile='manual-test', message=message))

            code, out, error = self.invoke('--task-workflow-check', str(self.destination))
            self.assertEqual((code, error), (0, ''))
            self.assertEqual(json.loads(out)['reservations']['notification_calls'], 1)
            self.assertIs(json.loads(out)['configuration_loaded'], False)
            self.assertNotIn('ONLY_IN_DRAFT', out)

            code, out, error = self.invoke('--task-workflow', str(self.destination))
            self.assertEqual((code, out), (2, ''))
            self.assertIn('--workflow-allow-notify', error.splitlines()[-1])
        self.assertEqual(self.source.read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
