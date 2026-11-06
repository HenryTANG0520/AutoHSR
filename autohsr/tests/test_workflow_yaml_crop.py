from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from autohsr.task_workflow import WorkflowError, compile_recipe
from autohsr.workflow_yaml import convert_march7th_yaml
from autohsr.workflow_yaml_crop import parse_march7th_crop


class March7thCropTests(unittest.TestCase):
    def test_defaults_and_decimal_variants(self):
        for value in (None, '', [], ()):
            with self.subTest(value=value):
                self.assertEqual(parse_march7th_crop(value), [0., 0., 1., 1.])
        for value in ('0.125, .25, 5e-1, +.75', (0.125, Decimal('.25'), '.5', '.75')):
            with self.subTest(value=value):
                self.assertEqual(parse_march7th_crop(value), [.125, .25, .625, 1.])

    def test_upstream_capture_expression_converts_width_and_height_to_endpoints(self):
        region = parse_march7th_crop('(1342 / 1920, 416 / 1080, 216 / 1920, 411 / 1080)')
        self.assertEqual(region, [1342 / 1920, 416 / 1080, 1558 / 1920, 827 / 1080])
        native = dict(version=1, name='选区格式', steps=[
            dict(id='image', type='task', task='workflow_image',
                 params=dict(image='selected.png', template='receive.png', region=region)),
        ])
        self.assertEqual(compile_recipe(native).steps[0]['params']['region'], region)

    def test_bounds_use_exact_ratios_before_converting_to_floats(self):
        self.assertEqual(parse_march7th_crop('1/3, 2/3, 2/3, 1/3'), [1/3, 2/3, 1., 1.])
        for value in ('0.999999999999999999, 0, 0.000000000000000002, 1',
                      '1e-20, 0, 1, 1',
                      '-0.1, 0, 1, 1',
                      '0, 0, 1, -0.1',
                      '0, 1, 1, 0',
                      '0.99999999999999999, 0, .00000000000000001, 1'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(WorkflowError, '边界'):
                    parse_march7th_crop(value)

    def test_small_grammar_rejects_coercion_and_executable_or_unbounded_expressions(self):
        cases = (
            (True, '四个'), ([True, 0, 1, 1], '四个'), ({'x': 0}, '四个'),
            (' ', '四个'), ('(0, 0,, 1, 1)', '四个'),
            ('((0, 0, 1, 1))', '十进制'),
            ('0, 0, 1/2/3, 1', '至多一次'),
            (['1/2', 0, 1, 1], '十进制'),
            ('0, 0, 1/0, 1', '分母'),
            ('0, 0, 1/0.0000, 1', '分母'),
            ('0, 0, 0.25 + 0.25, 1', '十进制'),
            ("0, 0, __import__('os').system('echo unsafe'), 1", '十进制'),
            ('0, 0, 1e10000000, 1', '指数'),
            ('0, 0, 1e-10000000, 1', '指数'),
            ('0, 0, Inf, 1', '十进制'),
            ([0, 0, Decimal('NaN'), 1], '十进制'),
            ([0, 0, float('inf'), 1], '十进制'),
            ([0, 0, 10 ** 1000, 1], '四个'),
            ('0, 0, ' + '1' * 600 + ', 1', '算式过长'),
            ([0, 0, '1' * 65, 1], '长度'),
        )
        for value, message in cases:
            with self.subTest(value=str(value)[:100]):
                with self.assertRaisesRegex(WorkflowError, message):
                    parse_march7th_crop(value)


class March7thObservationDiagnosticTests(unittest.TestCase):
    def test_reports_concrete_blocker_and_keeps_whole_tree_unpublished(self):
        cases = (
            ('type: find_image, template_path: templates/icon.png, crop: [0, 0, .5, .5]', '透明掩码'),
            ('type: find_image, template_path: templates/icon.png, crop: "(0,0,1/0,1)"', '选区算式的分母'),
            ('type: find_image, template_path: templates/icon.png, crop: [0, 0, 0.5, 0.5], max_retries: 2', '任一次'),
            ('type: find_text, text: "开门; 继续", crop: [0, 0, .5, 1]', '多个候选'),
            ('type: find_text, text: "开门", crop: [0, 0, .5, 1], include: false', '按字面匹配'),
            ('type: find_text, text: "开门", crop: [0, 0, false, 1]', '四个归一化'),
            ('type: if, condition_type: image_not_exists, template_path: templates/icon.png, children: [{type: wait}]',
             '失败值不能作为'),
            ('type: if, condition_type: last_result_failed, crop: "ignored", children: [{type: wait}]',
             '上一动作的布尔值'),
            ('type: while, condition_type: text_exists, text: "开门", max_iterations: 20, children: [{type: wait}]',
             '不能代替下一轮检测'),
            ('type: while, condition_type: text_exists, text: "开门", max_iterations: 0, children: [{type: wait}]',
             '无限运行'),
            ('type: while, condition_type: text_not_exists, text: "开门", max_iterations: 1001, children: [{type: wait}]',
             '循环上限'),
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'workflow.yaml', root / 'draft.json'
            template = root / 'templates' / 'icon.png'
            template.parent.mkdir()
            template.write_bytes(b'opaque fixture, conversion must never inspect')
            original_open, original_stat, original_lstat = Path.open, Path.stat, Path.lstat

            def guard(operation):
                def checked(path, *args, **kwargs):
                    self.assertNotEqual(path.suffix, '.png')
                    return operation(path, *args, **kwargs)
                return checked

            for step, message in cases:
                with self.subTest(step=step):
                    original = (
                        'name: 选区诊断\nsteps:\n'
                        '- type: wait\n'
                        '- type: for\n  count: 2\n  children:\n'
                        '  - {' + step + '}\n'
                    ).encode('utf-8')
                    source.write_bytes(original)
                    with (patch.object(Path, 'open', guard(original_open)),
                          patch.object(Path, 'stat', guard(original_stat)),
                          patch.object(Path, 'lstat', guard(original_lstat))):
                        with self.assertRaisesRegex(WorkflowError, '步骤 1/0.*' + message):
                            convert_march7th_yaml(source, target)
                    self.assertFalse(target.exists())
                    self.assertEqual(source.read_bytes(), original)
                    self.assertEqual(template.read_bytes(), b'opaque fixture, conversion must never inspect')


if __name__ == '__main__':
    unittest.main()
