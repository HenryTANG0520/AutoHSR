"""Opt-in YAML vision projection without a template or game read."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from autohsr.task_workflow import WorkflowError, compile_recipe, read
from autohsr.workflow_yaml import convert_march7th_yaml, load_march7th_yaml


class WorkflowYamlNativeVisionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.source = self.root / 'upstream' / 'workflow.yaml'
        self.source.parent.mkdir()
        self.target = self.root / 'saved' / 'draft.json'
        self.target.parent.mkdir()

    def write(self, body):
        original = ('name: 迁移图文\nsteps:\n' + body).encode('utf-8')
        self.source.write_bytes(original)
        return original

    def test_public_apis_require_an_explicit_boolean_opt_in(self):
        original = self.write('- type: find_text\n  text: 提示\n')
        for options in ({}, {'use_native_vision': False}):
            with self.subTest(options=options):
                with self.assertRaisesRegex(WorkflowError, '步骤 0.*按字面匹配'):
                    load_march7th_yaml(self.source, **options)
                with self.assertRaisesRegex(WorkflowError, '步骤 0.*按字面匹配'):
                    convert_march7th_yaml(self.source, self.target, **options)
                self.assertFalse(self.target.exists())
        with patch.object(Path, 'open', side_effect=AssertionError('invalid option reached file read')):
            for value in (1, 'true', None):
                with self.subTest(value=value), self.assertRaisesRegex(WorkflowError, '布尔值'):
                    load_march7th_yaml(self.source, use_native_vision=value)
        draft = load_march7th_yaml(self.source, use_native_vision=True)
        self.assertIsNone(draft.source)
        self.assertEqual(draft.document['steps'][0]['task'], 'workflow_game_text')
        self.assertFalse(self.target.exists())
        self.assertEqual(self.source.read_bytes(), original)
        self.source.write_bytes(original + b'use_native_vision: true\n')
        with self.assertRaisesRegex(WorkflowError, 'name／steps'):
            load_march7th_yaml(self.source)

    def test_find_and_nested_conditions_preserve_native_query_and_source_after_save(self):
        template = self.source.parent / 'templates' / '提示 图.PNG'
        shadow = self.target.parent / 'templates' / template.name
        for path, raw in ((template, b'original template'), (shadow, b'shadow template')):
            path.parent.mkdir()
            path.write_bytes(raw)
        absolute_template = self.root / 'external.JPG'
        original = self.write(
            '- type: find_image\n'
            "  template_path: 'templates\\提示 图.PNG'\n"
            '  threshold: "0.82"\n'
            '  crop: (1 / 8, 2 / 8, 3 / 8, 4 / 8)\n'
            '- type: find_text\n'
            '  text: " ; 看见提示 ; "\n'
            '  include: true\n'
            '  threshold: 0.99\n'
            '- type: if\n'
            '  condition_type: image_not_exists\n'
            '  template_path: ' + json.dumps(str(absolute_template)) + '\n'
            '  children:\n'
            '  - type: wait\n    seconds: 0\n'
            '  - type: while\n'
            '    condition_type: text_exists\n'
            '    text: 继续\n'
            '    include: false\n'
            '    crop: [0.125, 0, 0.5, 0.5]\n'
            '    max_retries: 1\n'
            '    max_iterations: "3"\n'
            '    children:\n'
            '    - type: continue\n'
            '    - type: break\n'
        )

        def guard(operation):
            def checked(path, *args, **kwargs):
                self.assertNotIn(path.suffix.casefold(), ('.png', '.jpg', '.jpeg'))
                return operation(path, *args, **kwargs)
            return checked

        with ExitStack() as stack:
            for name in ('open', 'stat', 'lstat', 'resolve'):
                stack.enter_context(patch.object(Path, name, guard(getattr(Path, name))))
            stack.enter_context(patch('autohsr.app.find_game', side_effect=AssertionError('accessed game')))
            result = convert_march7th_yaml(self.source, self.target, use_native_vision=True)
        native = read(result.path)
        image, text, branch = native['steps']
        self.assertEqual(image, dict(id='m7-0', type='task', task='workflow_game_image',
                                     params=dict(template=str(template), threshold=.82, region=[.125, .25, .5, .75])))
        self.assertEqual(text, dict(id='m7-1', type='task', task='workflow_game_text',
                                    params=dict(text='看见提示', contains=True, region=[0, 0, 1, 1])))
        self.assertEqual(branch['screen_condition'], dict(task='workflow_game_image', value=False,
                         params=dict(template=str(absolute_template), threshold=.9, region=[0, 0, 1, 1])))
        self.assertEqual([row['id'] for row in branch['steps']], ['m7-2-0', 'm7-2-1'])
        loop = branch['steps'][1]
        self.assertEqual(loop['max_iterations'], 3)
        self.assertEqual(loop['screen_condition'], dict(task='workflow_game_text', value=True,
                         params=dict(text='继续', contains=False, region=[.125, 0, .625, .5])))
        self.assertEqual([(node['id'], node['type']) for node in loop['steps']],
                         [('m7-2-1-0', 'continue'), ('m7-2-1-1', 'break')])
        selected = compile_recipe(native, base_dir=self.target.parent, selected_path='2/1')
        self.assertEqual(selected.profile['executions'], 11)
        self.assertEqual(selected.steps, [loop])
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(template.read_bytes(), b'original template')
        self.assertEqual(shadow.read_bytes(), b'shadow template')
        self.assertFalse(absolute_template.exists())

    def test_known_default_and_other_polarity_combinations_are_preserved(self):
        self.write(
            '- type: if\n  text: 已到达\n  children: [{type: wait}]\n'
            '- type: if\n  condition_type: image_exists\n  template_path: t.jpeg\n'
            '  threshold: 0.5\n  children: [{type: wait}]\n'
            '- type: while\n  condition_type: text_not_exists\n  text: 结束\n'
            '  children: [{type: wait}]\n'
        )
        one, two, three = load_march7th_yaml(self.source, use_native_vision=True).validate().steps
        self.assertEqual([(node['screen_condition']['task'], node['screen_condition']['value'])
                          for node in (one, two, three)],
                         [('workflow_game_text', True), ('workflow_game_image', True), ('workflow_game_text', False)])
        self.assertEqual(two['screen_condition']['params']['threshold'], .5)
        self.assertEqual(three['max_iterations'], 20)

    def test_unsupported_semantics_reject_entire_file_after_supported_steps(self):
        cases = (
            ('{type: find_text, text: "甲; 乙"}', '多个候选'),
            ('{type: find_text, text: "；！！", include: "false"}', '布尔值'),
            ('{type: find_text, text: "！！"}', '目标文字为空'),
            ('{type: find_image, template_path: ok.png, max_retries: 2}', '任一次'),
            ('{type: find_image, template_path: ok.png, max_retries: 0}', '须为正数'),
            ('{type: find_image, template_path: ok.png, threshold: 2000000}', '原生算法'),
            ('{type: find_image, template_path: ok.png, threshold: 0.49}', '原生算法'),
            ('{type: find_image, template_path: ok.png, threshold: .nan}', '原生算法'),
            ('{type: find_image, template_path: ok.png, threshold: false}', '原生算法'),
            ('{type: find_image, template_path: ok.png, crop: "(0,0,1/0,1)"}', '分母'),
            ('{type: if, condition_type: last_result, children: [{type: wait}]}', '上一动作'),
            ('{type: if, condition_type: last_result_failed, children: [{type: wait}]}', '上一动作'),
            ('{type: if, condition_type: text_found, text: 提示, children: [{type: wait}]}', '条件类型无效'),
            ('{type: if, text: 提示, children: [{type: break}]}', '步骤 1/0.*循环控制'),
            ('{type: if, text: 提示, children: [{type: click_text, text: 提示}]}', '步骤 1/0.*文字点击'),
            ('{type: if, text: 提示, children: []}', '非空的子步骤'),
            ('{type: while, text: 提示, max_iterations: 0, children: [{type: wait}]}', '无限运行'),
            ('{type: while, text: 提示, max_iterations: 1001, children: [{type: wait}]}', '循环上限'),
            ('{type: while, text: 提示, max_iterations: 1.5, children: [{type: wait}]}', '循环上限'),
            ('{type: while, text: 提示, max_iterations: 1, children: [{type: run_script}]}', '步骤 1/0.*未获支持'),
        )
        for step, message in cases:
            with self.subTest(step=step):
                original = self.write('- {type: find_text, text: 可以迁移}\n- ' + step + '\n')
                pattern = message if message.startswith('步骤') else '步骤 1.*' + message
                with self.assertRaisesRegex(WorkflowError, pattern):
                    convert_march7th_yaml(self.source, self.target, use_native_vision=True)
                self.assertFalse(self.target.exists())
                self.assertEqual(self.source.read_bytes(), original)

    def test_template_rejects_cwd_network_and_unsupported_paths(self):
        cases = (
            ('./templates/t.png', '工作目录'), (r'..\templates\t.png', '工作目录'),
            (r'\\server\share\t.png', '模板路径无效'), ('https://example.test/t.jpg', '模板路径无效'),
            (r'\\?\C:\templates\t.png', '模板路径无效'), ('C:t.png', '模板路径无效'),
            ('templates/../t.png', '模板路径无效'), ('templates/t.png/', '模板路径无效'),
            ('templates/CON.png', '模板路径无效'), ('t.webp', 'PNG 或 JPEG'), ('t.png ', '首尾含空白'),
        )
        if os.name == 'nt':
            cases += ((r'\templates\t.png', '模板路径无效'),)
        for path, message in cases:
            with self.subTest(path=path):
                self.write('- type: find_image\n  template_path: ' + json.dumps(path) + '\n')
                with self.assertRaisesRegex(WorkflowError, '步骤 0.*' + message):
                    convert_march7th_yaml(self.source, self.target, use_native_vision=True)
                self.assertFalse(self.target.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows volume classification')
    def test_template_on_mapped_network_drive_is_rejected(self):
        remote = 'Z:' if self.root.drive.upper() != 'Z:' else 'Y:'
        self.write('- type: find_image\n  template_path: ' + remote + '/t.png\n')
        with patch('autohsr.workflow_audio._local_drive', side_effect=lambda drive: drive == self.root.anchor):
            with self.assertRaisesRegex(WorkflowError, '步骤 0.*本地磁盘'):
                load_march7th_yaml(self.source, use_native_vision=True)


if __name__ == '__main__':
    unittest.main()
