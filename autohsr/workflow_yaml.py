"""Convert the supported subset of pinned March7thAssistant YAML to a draft.

Schema reference: March7thAssistant 7cf6c6b, module/workflow/__init__.py.
Only the explicitly selected definition is read. A draft uses the same compiler
and exclusive JSON publication as a native AutoHSR workflow.
"""
from __future__ import annotations

from decimal import Decimal, DecimalException
import os
from pathlib import Path, PureWindowsPath
import re
import stat
from types import MappingProxyType

import yaml
from yaml.events import AliasEvent
from yaml.nodes import ScalarNode

from .models import normalize
from .task_workflow import MAX_BYTES, MAX_DEPTH, MAX_NODES, PAGE_TASK, WorkflowError, compile_recipe
from .task_workflow_draft import SavedWorkflow, WorkflowDraft, _snapshot
from .workflow_yaml_crop import parse_march7th_crop


_YAML_DEPTH = 2 * MAX_DEPTH + 3
_YAML_NODES = 64 * MAX_NODES + 32
_META = {'author', 'version', 'description'}
_YAML_SUFFIXES = {'.yaml', '.yml'}
_TEMPLATE_SUFFIXES = {'.png', '.jpg', '.jpeg'}
_VISION_STEPS = {'find_image', 'find_text', 'if', 'while'}
_VISION_CONDITIONS = {'image_exists', 'image_not_exists', 'text_exists', 'text_not_exists'}
_STEP_FIELDS = {
    'type', 'text', 'audio_path', 'target_screen', 'template_path', 'threshold',
    'crop', 'include', 'max_retries', 'seconds', 'count', 'condition_type',
    'max_iterations', 'children', 'with_screenshot', 'key', 'key_duration',
    'key_action', 'click_action', 'press_duration', 'start', 'end', 'drag_duration',
}
_INTEGER = re.compile(r'^[+-]?[0-9]+$')
_NUMBER = re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')
_PAGE_TARGETS = {
    'menu': 'phone', 'guide2': 'daily_training', 'guide3': 'survival_index',
    'dispatch': 'assignments', 'mail': 'mail', 'reward_guide': 'reward_guide',
    'pass1': 'battlepass_rewards', 'pass2': 'battlepass_tasks',
}
_UNSUPPORTED = {
    'click_image': '模板点击没有等价的 AutoHSR 步骤',
    'click_text': '文字点击没有等价的 AutoHSR 步骤',
    'click_crop': '坐标点击没有等价的 AutoHSR 步骤',
    'drag_mouse': '鼠标滑动没有等价的 AutoHSR 步骤',
    'press_key': '按键没有等价的 AutoHSR 步骤',
    'find_image': '上游模板匹配和重试语义尚无等价的 AutoHSR 步骤',
    'find_text': '上游画面取样和文字匹配语义尚无等价的 AutoHSR 步骤',
    'if': '上游即时画面或上一动作的布尔条件尚无等价的 AutoHSR 步骤',
    'while': '上游循环条件和达到上限的行为尚无等价的 AutoHSR 步骤',
    'send_message': '上游通知缺少 AutoHSR 所需的显式方案绑定',
}


class _Loader(yaml.SafeLoader):
    # The upstream codec uses YAML 1.2. Keep words like "on" and dates
    # as text, and avoid PyYAML's YAML 1.1 octal and sexagesimal rules.
    yaml_implicit_resolvers = {}

    def __init__(self, stream):
        super().__init__(stream)
        self.depth = 0
        self.nodes_seen = 0

    def compose_document(self):
        event = self.peek_event()
        if event.version not in (None, (1, 2)) or event.tags:
            raise WorkflowError('三月七 YAML 仅支持默认或 1.2 版本，且不允许标签指令。')
        return super().compose_document()

    def compose_node(self, parent, index):
        event = self.peek_event()
        if isinstance(event, AliasEvent) or event.anchor is not None:
            raise WorkflowError('三月七 YAML 不允许锚点或别名。')
        if event.tag is not None:
            raise WorkflowError('三月七 YAML 不允许显式标签。')
        if self.depth >= _YAML_DEPTH or self.nodes_seen >= _YAML_NODES:
            raise WorkflowError('三月七 YAML 的解析层级或节点数超出上限。')
        self.depth += 1
        self.nodes_seen += 1
        try:
            return super().compose_node(parent, index)
        finally:
            self.depth -= 1

    def construct_mapping(self, node, deep=False):
        keys = set()
        for key, _ in node.value:
            if (not isinstance(key, ScalarNode) or key.tag != 'tag:yaml.org,2002:str'
                    or key.value == '<<' or key.value in keys):
                raise WorkflowError('三月七 YAML 不允许非文字键、合并键或重复字段。')
            keys.add(key.value)
        return super().construct_mapping(node, deep=deep)


def _numeric(value, grammar):
    if len(value) > 64 or not grammar.fullmatch(value):
        raise ValueError('unsupported numeric scalar')
    return Decimal(value)


def _yaml_number(loader, node):
    return _numeric(loader.construct_scalar(node), _NUMBER)


_Loader.add_implicit_resolver(
    'tag:yaml.org,2002:null', re.compile(r'^(?:~|null|Null|NULL)?$'), ['~', 'n', 'N', ''],
)
_Loader.add_implicit_resolver(
    'tag:yaml.org,2002:bool', re.compile(r'^(?:true|True|TRUE|false|False|FALSE)$'), 'tTfF',
)
_Loader.add_implicit_resolver('tag:autohsr,2026:number', _NUMBER, '+-.0123456789')
_Loader.add_constructor('tag:autohsr,2026:number', _yaml_number)


def _local_path(value, suffixes, *, source):
    path = Path(value)
    if (path.suffix.casefold() not in suffixes or '..' in path.parts
            or (path.anchor and not path.is_absolute())):
        message = '请选择本地的三月七 .yaml／.yml 文件。' if source else '请选择新的本地 .json 文件。'
        raise WorkflowError(message)
    path = path.absolute()
    if not _is_local_disk(path):
        raise WorkflowError('请选择本地磁盘中的普通文件。')
    current = Path(path.anchor)
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        if not _valid_part(part):
            raise WorkflowError('文件名或目录名无效。')
        current /= part
        last = index == len(parts) - 1
        if last and not source:
            break  # The native publisher independently enforces exclusive creation.
        info = current.lstat()
        expected = stat.S_ISREG if last else stat.S_ISDIR
        if not expected(info.st_mode) or getattr(info, 'st_file_attributes', 0) & (
                stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_OFFLINE):
            raise WorkflowError('三月七 YAML 仅支持普通本地文件和目录。')
    return current


def _is_local_disk(path):
    if os.name != 'nt':
        return True
    from .workflow_audio import _local_drive

    return len(path.drive) == 2 and _local_drive(path.anchor)


def _valid_part(part):
    return (not any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF or char in ':\\<>"|?*' for char in part)
            and not part.endswith(('.', ' ')) and not PureWindowsPath(part).is_reserved())


def _media_reference(value, source_dir, where, *, label, suffixes, suffix_error):
    """Bind a lexical media reference without accessing the media."""
    text = value.replace('\\', '/')
    if len(text) > 4096:
        raise WorkflowError(f'{where}的{label}路径过长。')
    path = Path(text)
    if path.suffix.casefold() not in suffixes:
        raise WorkflowError(f'{where}{suffix_error}')
    # pathlib normalizes away a leading "./". March7th resolves this form
    # against its process cwd, so check the spelling before using the path.
    if text.startswith(('./', '../')):
        raise WorkflowError(f'{where}的 ./ 或 ../ {label}路径依赖三月七进程的工作目录，无法确定来源。')
    parts = path.parts[1:] if path.anchor else path.parts
    if (text.startswith('//') or text.endswith('/')
            or (path.anchor and not path.is_absolute()) or '..' in path.parts
            or not all(_valid_part(part) for part in parts)):
        raise WorkflowError(f'{where}的{label}路径无效，须为普通相对路径或本地绝对路径。')
    absolute = source_dir / path
    if not _is_local_disk(absolute):
        raise WorkflowError(f'{where}的{label}路径须位于本地磁盘。')
    # Keep an absolute reference so the draft and any Save As use the same
    # upstream location. File checks belong to the native task.
    reference = str(absolute)
    if len(reference) > 4096:
        raise WorkflowError(f'{where}的{label}路径过长。')
    return reference


def _audio_path(value, source_dir, where):
    text = value.strip() if isinstance(value, str) else ''
    return _media_reference(text, source_dir, where, label='音频', suffixes={'.wav'},
                            suffix_error='须明确指定 WAV 文件，默认 MP3 和其他格式无法迁移。')


def _whole(value, default, limit, *, quoted_grammar, where):
    try:
        if isinstance(value, str):
            value = _numeric(value.strip(), quoted_grammar)
        if value is None:
            value = Decimal(default)
        if isinstance(value, Decimal) and 0 <= value <= limit and value == value.to_integral_value():
            return int(value)
    except (ValueError, DecimalException):
        pass
    raise WorkflowError(f'{where}必须是 0～{limit} 的整数。')


def _template_threshold(value, where):
    try:
        if value is None:
            return .9
        if isinstance(value, str):
            value = _numeric(value.strip(), _NUMBER)
        if isinstance(value, Decimal) and Decimal('.5') <= value <= 1:
            return float(value)
    except (ValueError, DecimalException):
        pass
    raise WorkflowError(f'{where}的图片阈值须在原生算法的 0.50～1 范围内。')


def _vision_node(step, source_dir, where, *, use_native_vision):
    kind = step['type']

    def reject(detail):
        prefix = '' if use_native_vision else _UNSUPPORTED[kind] + '。'
        raise WorkflowError(f'{where}无法迁移。{prefix}{detail}。')

    limit = None
    if kind == 'while':
        limit = _whole(step.get('max_iterations'), 20, 1000, quoted_grammar=_INTEGER, where=where + '的循环上限')
        if not limit:
            reject('上游条件循环的上限为 0 时会无限运行')
    condition = None
    if kind in ('if', 'while'):
        condition = step.get('condition_type')
        if condition is None or condition == '':
            condition = 'text_exists'
        if condition in ('last_result', 'last_result_failed'):
            reject('上一动作的布尔值会被等待、控制节点和异常改写，无法绑定为原生的已核实事实')
        if not isinstance(condition, str) or condition not in _VISION_CONDITIONS:
            reject('条件类型无效')
        image = condition.startswith('image_')
    else:
        image = kind == 'find_image'
    try:
        region = parse_march7th_crop(step.get('crop'))
    except WorkflowError as error:
        raise WorkflowError(f'{where}无法迁移。{error}') from None
    attempts = _whole(step.get('max_retries'), 1, 10000, quoted_grammar=_INTEGER, where=where + '的检测尝试次数')
    if not attempts:
        reject('检测尝试次数须为正数')
    if attempts > 1:
        reject('原版尝试多次时任一次匹配即可通过，原生需要同次观察的两帧结果一致')
    target = step.get('template_path' if image else 'text')
    if not isinstance(target, str) or not target.strip():
        reject('缺少明确的检测模板或目标文字')
    if not image and len(target) > 120:
        reject('目标文字超过原生的 120 字限制')
    targets = [part.strip() for part in target.split(';') if part.strip()] if not image else []
    if len(targets) > 1:
        reject('原版按分号列出多个候选，原生文字判断只接收一个目标')
    if not use_native_vision:
        if kind == 'while':
            reject('每轮需要重新取帧，已保存的步骤事实不能代替下一轮检测')
        if kind == 'if':
            reject('上游即时检测的失败值不能作为原生条件的已核实未匹配')
        if image:
            reject('模板可能使用透明掩码和不同方向的阈值，未读取素材确认匹配契约')
        reject('上游文字按字面匹配，原生使用文字规范化和置信度要求')

    if image:
        if target != target.strip():
            reject('模板路径首尾含空白，来源无法无损绑定')
        task = 'workflow_game_image'
        params = dict(template=_media_reference(
            target, source_dir, where, label='模板', suffixes=_TEMPLATE_SUFFIXES,
            suffix_error='须明确指定本地 PNG 或 JPEG 模板。',
        ), threshold=_template_threshold(step.get('threshold'), where), region=region)
    else:
        contains = step.get('include', False)
        if type(contains) is not bool:
            reject('文字包含匹配须明确为布尔值')
        if not targets or not normalize(targets[0]) or any(
                ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in targets[0]):
            reject('目标文字为空或含有原生无法表达的字符')
        task = 'workflow_game_text'
        params = dict(text=targets[0], contains=contains, region=region)
    if condition is None:
        return dict(type='task', task=task, params=params)
    native = dict(screen_condition=dict(task=task, params=params, value=condition in ('image_exists', 'text_exists')))
    if limit is not None:
        native['max_iterations'] = limit
    return native


def _steps(values, source_dir, *, use_native_vision, prefix=(), total=None, in_loop=False):
    if total is None:
        total = [0]
    if not isinstance(values, list) or not values or len(prefix) >= MAX_DEPTH:
        raise WorkflowError('三月七 YAML 的步骤列表为空、无效或嵌套过深。')
    result = []
    for index, value in enumerate(values):
        path = (*prefix, index)
        where = '三月七步骤 ' + '/'.join(map(str, path))
        total[0] += 1
        if total[0] > MAX_NODES:
            raise WorkflowError(f'三月七 YAML 最多 {MAX_NODES} 个步骤。')
        if not isinstance(value, dict) or value.keys() - _STEP_FIELDS:
            raise WorkflowError(f'{where}包含未知字段或不是步骤对象。')
        kind = value.get('type')
        if not isinstance(kind, str) or not kind:
            raise WorkflowError(f'{where}缺少明确的步骤类型。')
        node = dict(id='m7-' + '-'.join(map(str, path)), type=kind)
        if kind in _VISION_STEPS:
            node.update(_vision_node(value, source_dir, f'{where}（{kind}）', use_native_vision=use_native_vision))
        elif kind in _UNSUPPORTED:
            raise WorkflowError(f'{where}（{kind}）无法迁移。{_UNSUPPORTED[kind]}。')
        children = value.get('children', [])
        control = kind in ('for', 'if', 'while')
        if control:
            if not isinstance(children, list) or not children:
                raise WorkflowError(f'{where}须有非空的子步骤列表。')
        elif children != []:
            raise WorkflowError(f'{where}包含无法保留的子步骤。')
        if kind == 'wait':
            node['seconds'] = _whole(
                value.get('seconds'), 1, 3600, quoted_grammar=_NUMBER, where=where + '的等待秒数',
            )
        elif kind == 'for':
            count = _whole(
                value.get('count'), 1, 1000, quoted_grammar=_INTEGER, where=where + '的循环次数',
            )
            if not count:
                raise WorkflowError(f'{where}是无限循环，无法迁移。')
            node['count'] = count
        elif kind == 'play_audio':
            node.update(type='task', task='workflow_audio',
                        params={'path': _audio_path(value.get('audio_path'), source_dir, where)},
                        on_failure='continue')
        elif kind == 'switch_screen':
            screen = value.get('target_screen')
            target = _PAGE_TARGETS.get(screen.strip()) if isinstance(screen, str) else None
            if target is None:
                raise WorkflowError(f'{where}（switch_screen）缺少已适配的对应页面。')
            node.update(type='task', task=PAGE_TASK, params={'target': target}, on_failure='continue')
        elif kind == 'stop_workflow':
            node['type'] = 'stop'
        elif kind in ('break', 'continue'):
            if not in_loop:
                raise WorkflowError(f'{where}的循环控制只能位于循环中。')
        elif kind not in _VISION_STEPS:
            raise WorkflowError(f'{where}的步骤类型未获支持。')
        if control:
            node['steps'] = _steps(children, source_dir, use_native_vision=use_native_vision, prefix=path, total=total,
                                   in_loop=in_loop or kind in ('for', 'while'))
        result.append(node)
    return result


def _decode(raw, source_dir, *, use_native_vision):
    if len(raw) > MAX_BYTES:
        raise WorkflowError('三月七 YAML 超过 1 MiB。')
    try:
        value = yaml.load(raw.decode('utf-8-sig'), Loader=_Loader)
    except (UnicodeError, yaml.YAMLError, DecimalException, ValueError, RecursionError) as error:
        if isinstance(error, WorkflowError):
            raise
        mark = getattr(error, 'problem_mark', None)
        location = f'第 {mark.line + 1} 行的' if mark is not None else ''
        raise WorkflowError(f'{location}三月七 YAML 无效，须为单份 UTF-8 定义。') from None
    if isinstance(value, dict) and 'allowed_workflows' in value:
        raise WorkflowError('所选文件是三月七官方示例索引，请选择具体示例目录中的 workflow.yaml。')
    if (not isinstance(value, dict) or not {'name', 'steps'} <= value.keys()
            or value.keys() - (_META | {'name', 'steps'})):
        raise WorkflowError('所选文件不符合三月七 YAML 的 name／steps 结构。')
    metadata = {}
    for key in _META & value.keys():
        item = value[key]
        if not isinstance(item, (str, Decimal)) or len(str(item)) > 4096:
            raise WorkflowError('三月七 YAML 的作者、版本或描述字段无效。')
        display = str(item)
        if any(char == '\0' or 0xD800 <= ord(char) <= 0xDFFF for char in display):
            raise WorkflowError('三月七 YAML 的作者、版本或描述字段无效。')
        metadata[key] = display
    steps = _steps(value['steps'], source_dir, use_native_vision=use_native_vision)
    return dict(version=1, name=value['name'], steps=steps), metadata


class March7thYamlDraft(WorkflowDraft):
    """A native draft with upstream display metadata kept separately."""

    def __init__(self, source, raw, revision, original, *, original_source=None, metadata=None):
        super().__init__(source, raw, revision, original)
        self.original_source = original_source
        self.metadata = MappingProxyType(metadata or {})

    def destination_path(self, path) -> Path:
        try:
            destination = _local_path(path, {'.json'}, source=False)
        except (TypeError, OSError) as error:
            raise WorkflowError('请选择已存在的本地父目录和新的 .json 文件名。') from error
        return super().destination_path(destination)


def load_march7th_yaml(path, *, use_native_vision: bool = False) -> March7thYamlDraft:
    """Read one YAML draft, with an explicit opt-in to native dual-frame vision."""
    if type(use_native_vision) is not bool:
        raise WorkflowError('实时图文适配开关必须为布尔值。')
    try:
        source = _local_path(path, _YAML_SUFFIXES, source=True)
        raw, _ = _snapshot(source)
    except (TypeError, OSError) as error:
        raise WorkflowError('无法读取所选三月七 YAML 文件。') from error
    document, metadata = _decode(raw, source.parent, use_native_vision=use_native_vision)
    recipe = compile_recipe(document, base_dir=source.parent)
    return March7thYamlDraft(None, None, None, recipe.document, original_source=source, metadata=metadata)


def convert_march7th_yaml(source, destination, *, use_native_vision: bool = False) -> SavedWorkflow:
    """Validate then exclusively publish a separate native JSON definition."""
    return load_march7th_yaml(source, use_native_vision=use_native_vision).save_as(destination)
