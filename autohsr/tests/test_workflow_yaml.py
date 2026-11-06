import hashlib
import json
import os
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from autohsr.config import Settings
from autohsr.task_workflow import MAX_BYTES, WorkflowError, compile_recipe, read, task_spec
from autohsr.task_workflow_draft import WorkflowDraft, WorkflowSaveConflict
from autohsr.warp_service import publish_new
from autohsr.workflow_yaml import convert_march7th_yaml, load_march7th_yaml


class WorkflowYamlTests(unittest.TestCase):
    def setUp(self):
        root = self.enterContext(TemporaryDirectory())
        self.root = Path(root)
        self.source = self.root / 'workflow.yaml'
        self.target = self.root / 'draft.json'

    def write(self, content):
        raw = content.encode('utf-8') if isinstance(content, str) else content
        self.source.write_bytes(raw)
        return raw

    def test_export_shape_builds_an_unsaved_native_draft_with_stable_paths(self):
        original = self.write(
            '\ufeffname: on\n'
            'author: 三月七\n'
            'version: "1.2"\n'
            'description: |\n  第一行\n  第二行\n'
            'steps:\n'
            '- type: wait\n'
            "  text: ''\n  audio_path: ./assets/audio/pa.mp3\n  target_screen: ''\n"
            "  template_path: ''\n  threshold: 0.9\n  crop: ''\n  include: false\n"
            '  max_retries: 1\n  seconds: 1.0\n  count: 1\n  condition_type: text_exists\n'
            "  max_iterations: 20\n  children: []\n  with_screenshot: false\n  key: ''\n"
            '  key_duration: 0.1\n  key_action: press_and_release\n'
            '  click_action: press_and_release\n  press_duration: 0.1\n'
            "  start: ''\n  end: ''\n  drag_duration: 0.5\n"
            '- type: for\n  count: 03\n  children:\n'
            '  - type: wait\n    seconds: 0\n'
            '  - type: for\n    count: "2"\n    children:\n'
            '    - {type: wait, seconds: "2.0"}\n'
            '    - {type: continue}\n'
            '  - type: break\n'
            '- type: stop_workflow\n'
            '- type: wait\n'
        )
        draft = load_march7th_yaml(self.source)
        self.assertIsInstance(draft, WorkflowDraft)
        self.assertEqual(draft.original_source, self.source)
        self.assertIsNone(draft.source)
        self.assertFalse(draft.source_is_current())
        self.assertEqual(dict(draft.metadata), dict(author='三月七', version='1.2', description='第一行\n第二行\n'))
        self.assertEqual(draft.document, {
            'version': 1, 'name': 'on', 'steps': [
                {'id': 'm7-0', 'type': 'wait', 'seconds': 1},
                {'id': 'm7-1', 'type': 'for', 'count': 3, 'steps': [
                    {'id': 'm7-1-0', 'type': 'wait', 'seconds': 0},
                    {'id': 'm7-1-1', 'type': 'for', 'count': 2, 'steps': [
                        {'id': 'm7-1-1-0', 'type': 'wait', 'seconds': 2},
                        {'id': 'm7-1-1-1', 'type': 'continue'},
                    ]},
                    {'id': 'm7-1-2', 'type': 'break'},
                ]},
                {'id': 'm7-2', 'type': 'stop'},
                {'id': 'm7-3', 'type': 'wait', 'seconds': 1},
            ],
        })
        self.assertEqual(list(self.root.iterdir()), [self.source])
        self.assertEqual(draft.validate(selected_path='1/1/0').steps[0]['seconds'], 2)
        draft.document['name'] = '编辑后的流程'
        saved = draft.save_as(self.target)
        self.assertEqual(read(saved.path), draft.document)
        self.assertEqual(WorkflowDraft.load(saved.path).validate().profile, saved.recipe.profile)
        self.assertEqual(saved.sha256, hashlib.sha256(self.target.read_bytes()).hexdigest())
        self.assertEqual(self.source.read_bytes(), original)

    def test_yml_variant_and_yaml_12_directive(self):
        self.source = self.root / 'workflow.YML'
        self.write('%YAML 1.2\n---\nname: yes\nsteps: [{type: wait, seconds: 1e0}]\n')
        saved = convert_march7th_yaml(self.source, self.target)
        self.assertEqual((saved.recipe.document['name'], saved.recipe.steps[0]['seconds']), ('yes', 1))

    def test_no_overwrite_including_original_and_publish_race(self):
        original = self.write('name: 等待\nsteps: [{type: wait}]\n')
        draft = load_march7th_yaml(self.source)
        self.target.write_bytes(b'occupied')
        with self.assertRaises(WorkflowSaveConflict):
            draft.save_as(self.target)
        self.assertEqual(self.target.read_bytes(), b'occupied')
        with self.assertRaisesRegex(WorkflowError, r'\.json'):
            draft.save_as(self.source)
        self.assertEqual(self.source.read_bytes(), original)
        raced = self.root / 'raced.json'

        def interleave(path, writer, *, limit):
            path.write_bytes(b'first writer')
            return publish_new(path, writer, limit=limit)

        with patch('autohsr.task_workflow_draft.publish_new', side_effect=interleave):
            with self.assertRaises(WorkflowSaveConflict):
                draft.save_as(raced)
        self.assertEqual(raced.read_bytes(), b'first writer')

    def test_template_action_rejects_entire_tree_without_reading_assets(self):
        original = self.write(
            'name: 模板例子\nsteps:\n'
            '- type: wait\n'
            '- type: for\n  count: 2\n  children:\n'
            '  - type: find_image\n'
            '    template_path: templates/receive.png\n'
            '    threshold: 0.9\n    max_retries: 2\n'
            '    crop: (1342 / 1920, 416 / 1080, 216 / 1920, 411 / 1080)\n'
        )
        template = self.root / 'templates' / 'receive.png'
        template.parent.mkdir()
        template.write_bytes(b'not opened')
        real_open = Path.open

        def open_selected(path, *args, **kwargs):
            self.assertEqual(path, self.source)
            return real_open(path, *args, **kwargs)

        with patch.object(Path, 'open', open_selected):
            with self.assertRaisesRegex(WorkflowError, r'步骤 1/0.*模板匹配'):
                convert_march7th_yaml(self.source, self.target)
        self.assertFalse(self.target.exists())
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(template.read_bytes(), b'not opened')

    def test_native_steps_and_upstream_actions_do_not_bypass_mapping(self):
        for kind in ('click_image', 'click_text', 'click_crop', 'drag_mouse', 'press_key', 'switch_screen',
                     'find_text', 'if', 'while', 'send_message', 'task', 'run_script', 'stop'):
            with self.subTest(kind=kind):
                self.write(f'name: 中途有不支持动作\nsteps: [{{type: wait}}, {{type: {kind}}}]\n')
                with self.assertRaisesRegex(WorkflowError, r'步骤 1'):
                    convert_march7th_yaml(self.source, self.target)
                self.assertFalse(self.target.exists())

    def test_known_switch_screen_targets_preserve_daily_page_identity(self):
        names = ('menu', 'guide2', 'guide3', 'dispatch', 'mail', 'reward_guide', 'pass1', 'pass2')
        steps = ''.join(f'  - type: switch_screen\n    target_screen: {name}\n' for name in names)
        original = self.write('name: 日常页面\nsteps:\n' + steps)
        saved = convert_march7th_yaml(self.source, self.target)
        self.assertEqual([node['task'] for node in saved.recipe.steps], ['workflow_open_page'] * len(names))
        self.assertEqual([node['params']['target'] for node in saved.recipe.steps],
                         ['phone', 'daily_training', 'survival_index', 'assignments', 'mail', 'reward_guide',
                          'battlepass_rewards', 'battlepass_tasks'])
        self.assertEqual(self.source.read_bytes(), original)
        for name in ('battlepass', 'pass3', 'start_srpass', 'guide4', 'main', 'unknown'):
            with self.subTest(name=name):
                self.write(f'name: 精确页面\nsteps: [{{type: switch_screen, target_screen: {name}}}]\n')
                with self.assertRaisesRegex(WorkflowError, r'步骤 0.*switch_screen'):
                    load_march7th_yaml(self.source)

    def test_wav_references_stay_bound_to_original_locations_after_save_as(self):
        self.source = self.root / 'upstream' / 'workflow.yaml'
        source_audio = self.source.parent / 'clips' / '提示 音.WAV'
        source_audio.parent.mkdir(parents=True)
        with wave.open(str(source_audio), 'wb') as clip:
            clip.setparams((1, 2, 8000, 16, 'NONE', 'not compressed'))
            clip.writeframes(bytes(32))
        original_audio = source_audio.read_bytes()
        external_audio = self.root / 'independent.wav'  # The draft may reference a file not yet installed.
        destination = self.root / 'other' / 'draft.json'
        shadow_audio = destination.parent / 'clips' / source_audio.name
        shadow_audio.parent.mkdir(parents=True)
        shadow_audio.write_bytes(b'same relative name but wrong source')
        original = self.write(
            'name: 本地音频\nsteps:\n'
            '- type: for\n  count: 2\n  children:\n'
            '  - type: play_audio\n    audio_path: ' + json.dumps('clips\\提示 音.WAV') + '\n'
            '- type: play_audio\n  audio_path: ' + json.dumps(str(external_audio)) + '\n'
        )

        def guard_media(operation):
            def guarded(path, *args, **kwargs):
                self.assertNotEqual(path.suffix.casefold(), '.wav')
                return operation(path, *args, **kwargs)
            return guarded

        with (patch.object(Path, 'open', guard_media(Path.open)),
              patch.object(Path, 'stat', guard_media(Path.stat)),
              patch.object(Path, 'lstat', guard_media(Path.lstat)),
              patch('autohsr.workflow_audio.play') as play):
            draft = load_march7th_yaml(self.source)
            preview = draft.validate(destination=destination)
            saved = draft.save_as(destination)
        play.assert_not_called()
        self.assertEqual(saved.recipe.document, preview.document)
        reloaded = WorkflowDraft.load(saved.path).validate()
        self.assertEqual(reloaded.document, preview.document)
        audio_steps = (reloaded.steps[0]['steps'][0], reloaded.steps[1])
        for step, expected in zip(audio_steps, (source_audio, external_audio), strict=True):
            self.assertEqual((step['type'], step['task'], step['on_failure']), ('task', 'workflow_audio', 'continue'))
            self.assertEqual(Path(step['params']['path']), expected)
            _, options = task_spec(Settings(), step, reloaded.base_dir)
            self.assertEqual(Path(options['path']), expected)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(source_audio.read_bytes(), original_audio)
        self.assertEqual(shadow_audio.read_bytes(), b'same relative name but wrong source')
        self.assertFalse(external_audio.exists())
        self.assertEqual(set(destination.parent.iterdir()), {destination, shadow_audio.parent})

    def test_audio_rejects_default_formats_cwd_and_unsafe_paths(self):
        cases = (
            (None, '默认 MP3'), ('', '默认 MP3'), ('./assets/audio/pa.mp3', '默认 MP3'),
            ('clips/beep.ogg', '默认 MP3'),
            ('./clips/beep.wav', '工作目录'), (r'.\clips\beep.wav', '工作目录'),
            ('../clips/beep.wav', '工作目录'), (r'..\clips\beep.wav', '工作目录'),
            (r'\\server\share\beep.wav', '音频路径无效'), ('//server/share/beep.wav', '音频路径无效'),
            (r'\\?\C:\clips\beep.wav', '音频路径无效'), ('file://C:/clips/beep.wav', '音频路径无效'),
            ('https://example.test/clip.wav', '音频路径无效'), ('C:clip.wav', '音频路径无效'),
            ('clips/../beep.wav', '音频路径无效'), ('clips/beep.wav/', '音频路径无效'),
            ('clips/clip:alternate.wav', '音频路径无效'), ('clips/CON.wav', '音频路径无效'),
            ('clips / NUL/clip.wav', '音频路径无效'), ('a' * 4096 + '.wav', '路径过长'),
        )
        if os.name == 'nt':
            cases += (('/clips/beep.wav', '音频路径无效'), (r'\clips\beep.wav', '音频路径无效'))
        for audio_path, message in cases:
            with self.subTest(audio_path=str(audio_path)[:90]):
                field = '' if audio_path is None else '\n  audio_path: ' + json.dumps(audio_path)
                original = self.write('name: 拒绝音频\nsteps:\n- type: wait\n- type: play_audio' + field + '\n')
                with self.assertRaisesRegex(WorkflowError, '步骤 1.*' + message):
                    convert_march7th_yaml(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.assertEqual(self.source.read_bytes(), original)

    @unittest.skipUnless(os.name == 'nt', 'Windows drive classification')
    def test_drive_letter_mapped_to_network_is_rejected(self):
        remote = 'Z:' if self.root.drive.upper() != 'Z:' else 'Y:'
        self.write('name: 映射驱动器\nsteps:\n- type: play_audio\n  audio_path: ' + remote + '/clip.wav\n')
        with patch('autohsr.workflow_audio._local_drive', side_effect=lambda drive: drive == self.root.anchor):
            with self.assertRaisesRegex(WorkflowError, '步骤 0.*本地磁盘'):
                convert_march7th_yaml(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_unsupported_parameters_and_children_are_not_silently_removed(self):
        for node in (
            '{type: wait, seconds: 0.5}', '{type: wait, seconds: true}',
            '{type: wait, seconds: .inf}', '{type: wait, seconds: -1}',
            '{type: wait, seconds: 3601}', '{type: for, count: 0, children: [{type: break}]}',
            '{type: for, count: 1.5, children: [{type: wait}]}', '{type: for, count: 1001}',
            '{type: wait, enabled: false}', '{type: wait, script: run_me}', '{type: wait, children: [{type: wait}]}',
            '{type: break}', '{type: continue}', '{type: for, children: []}',
        ):
            with self.subTest(node=node):
                self.write(f'name: 非等价\nsteps: [{node}]\n')
                with self.assertRaises(WorkflowError):
                    convert_march7th_yaml(self.source, self.target)
                self.assertFalse(self.target.exists())

    def test_official_index_and_non_workflow_documents(self):
        for content, message in (
            ('allowed_workflows: [sample_auto_upgrade]\ndefault_workflow: sample_auto_upgrade\n', '官方示例索引'),
            ('name: 脚本\nsteps: [{type: wait}]\n_workflow_base_dir: C:/other', 'name／steps'),
            ('name: 原生\nversion: 1\nsteps: [{id: w, type: wait, seconds: 1}]\n', '未知字段'),
            ('name: 无步骤\nsteps: []\n', '步骤列表'),
            ('name: true\nsteps: [{type: wait}]\n', '流程文字'),
        ):
            with self.subTest(content=content):
                self.write(content)
                with self.assertRaisesRegex(WorkflowError, message):
                    load_march7th_yaml(self.source)

    def test_yaml_unsafe_shapes_and_encodings_rejected_before_publication(self):
        cases = (
            ('name: &name demo\nsteps: [{type: wait}]\n', '锚点或别名'),
            ('name: *missing\nsteps: [{type: wait}]\n', '锚点或别名'),
            ('name: ! name\nsteps: [{type: wait}]\n', '显式标签'),
            ('name: !!python/object/apply:os.system [bad]\nsteps: [{type: wait}]\n', '显式标签'),
            ('name: demo\nsteps: [{type: wait, <<: {seconds: 1}}]\n', '合并键'),
            ('name: demo\nsteps: [{type: wait, "type": stop_workflow}]\n', '重复字段'),
            ('name: demo\nsteps: [{type: wait, 1: a}]\n', '非文字键'),
            ('name: demo\nsteps: [{type: wait, [a, b]: c}]\n', '非文字键'),
            ('name: demo\nsteps: [{type: wait}]\n---\nname: next\nsteps: [{type: wait}]\n', '单份 UTF-8'),
            ('%YAML 1.1\n---\nname: demo\nsteps: [{type: wait}]\n', '1.2'),
            (b'name: \xff\nsteps: []', 'UTF-8'),
        )
        for content, message in cases:
            with self.subTest(content=content):
                original = self.write(content)
                with self.assertRaisesRegex(WorkflowError, message):
                    convert_march7th_yaml(self.source, self.target)
                self.assertFalse(self.target.exists())
                self.assertEqual(self.source.read_bytes(), original)

    def test_file_parse_and_compiler_limits_are_independent(self):
        cases = (
            (b'#' + b'a' * MAX_BYTES, '1 MiB'),
            ('name: x\nsteps: [{type: wait, crop: ' + '[' * 100 + '0' + ']' * 100 + '}]', '解析层级'),
            ('name: x\nsteps: [{type: wait, crop: [' + '0,' * 17000 + '0]}]', '节点数'),
            ('name: x\nsteps:\n' + '- {type: wait}\n' * 257, '256 个步骤'),
            ('name: x\nsteps: [{type: for, count: 101, children: '
             '[{type: for, count: 100, children: [{type: wait}]}]}]', '10000'),
        )
        for content, message in cases:
            with self.subTest(message=message):
                self.write(content)
                with self.assertRaisesRegex(WorkflowError, message):
                    convert_march7th_yaml(self.source, self.target)
                self.assertFalse(self.target.exists())
        self.write('name: x\nsteps:\n' + '- {type: wait}\n' * 256)
        self.assertEqual(len(compile_recipe(load_march7th_yaml(self.source).document).steps), 256)

    def test_requires_an_explicit_ordinary_source_and_existing_local_output_parent(self):
        self.source.mkdir()
        with self.assertRaisesRegex(WorkflowError, '普通本地'):
            load_march7th_yaml(self.source)
        self.source.rmdir()
        self.write('name: x\nsteps: [{type: wait}]\n')
        with self.assertRaisesRegex(WorkflowError, '无法读取'):
            load_march7th_yaml(self.root / 'missing.yml')
        with self.assertRaisesRegex(WorkflowError, r'\.yaml'):
            load_march7th_yaml(self.target)
        with self.assertRaisesRegex(WorkflowError, '已存在'):
            convert_march7th_yaml(self.source, self.root / 'missing' / 'draft.json')
        self.assertFalse((self.root / 'missing').exists())

    def test_rejects_source_and_destination_through_reparse_directory(self):
        folder = self.root / 'mount'
        folder.mkdir()
        self.write('name: x\nsteps: [{type: wait}]\n')
        real_lstat = Path.lstat

        def reparse(path):
            if path == folder:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
            return real_lstat(path)

        with patch.object(Path, 'lstat', reparse):
            with self.assertRaisesRegex(WorkflowError, '普通本地'):
                load_march7th_yaml(folder / 'workflow.yaml')
            with self.assertRaisesRegex(WorkflowError, '普通本地'):
                load_march7th_yaml(self.source).validate(destination=folder / 'draft.json')
            with self.assertRaisesRegex(WorkflowError, '普通本地'):
                convert_march7th_yaml(self.source, folder / 'draft.json')
        self.assertEqual(list(folder.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
