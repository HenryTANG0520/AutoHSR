"""Transport-neutral discovery and invocation for AutoHSR task capabilities."""

from collections.abc import Collection
from typing import Literal, TypedDict

from .task_workflow import MAX_DEPTH, MAX_NODES, WORKFLOW_PAGES, WorkflowError, compile_recipe


SCREEN_CHECK_PLAN = 'autohsr.screen_check_plan'
SCREEN_CHECK_PLAN_VERSION = 1
WORKFLOW_CHECK = 'autohsr.task_workflow_check'
WORKFLOW_CHECK_VERSION = 1
_VERSIONS = {SCREEN_CHECK_PLAN: SCREEN_CHECK_PLAN_VERSION, WORKFLOW_CHECK: WORKFLOW_CHECK_VERSION}
_RESERVATION_FIELDS = ('daily_calls', 'du_calls', 'currency_calls', 'du_runs', 'currency_games', 'executions')
_OPTIONAL_RESERVATIONS = ('du_rewards_calls', 'notification_calls')


class CapabilityInfo(TypedDict):
    id: str
    version: int
    title: str
    description: str
    enabled: bool
    read_only: bool
    input_schema: dict
    output_schema: dict


class ScreenCheckPlanResult(TypedDict):
    status: Literal['success']
    mode: Literal['preview']
    pages: list[str]
    reservations: dict[str, int]
    game_accessed: Literal[False]


class WorkflowCheckResult(TypedDict):
    status: Literal['success']
    mode: Literal['validation']
    name: str
    selected_path: list[int]
    reservations: dict[str, int]
    game_accessed: Literal[False]
    configuration_loaded: Literal[False]
    source_files_read: Literal[False]


class CapabilityError(WorkflowError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _object_schema(properties, *, optional=()):
    return dict(type='object', properties=properties,
                required=[field for field in properties if field not in optional], additionalProperties=False)


def _pages_schema():
    return dict(type='array', items=dict(type='string', enum=list(WORKFLOW_PAGES)),
                minItems=1, maxItems=len(WORKFLOW_PAGES), uniqueItems=True,
                description='按核对顺序填写。短信通知须单独选择，活动页须依次放在末尾。')


def _reservations_schema(*, optional=()):
    return _object_schema({name: dict(type='integer', minimum=0) for name in (*_RESERVATION_FIELDS, *optional)},
                          optional=optional)


def _screen_check(arguments):
    if not isinstance(arguments, dict) or arguments.keys() != {'pages'} or not isinstance(arguments['pages'], list):
        raise WorkflowError('预览参数须为仅包含 pages 列表的对象。')

    from .selected_page_check import build_recipe

    recipe = build_recipe(arguments['pages'])
    return ScreenCheckPlanResult(
        status='success', mode='preview', pages=[step['params']['target'] for step in recipe.steps],
        reservations={name: recipe.profile[name] for name in _RESERVATION_FIELDS}, game_accessed=False,
    )


def _workflow_check(arguments):
    if (not isinstance(arguments, dict) or 'document' not in arguments
            or arguments.keys() - {'document', 'step_path'}
            or ('step_path' in arguments and not isinstance(arguments['step_path'], str))):
        raise WorkflowError('校验参数须包含流程 document，可另传步骤路径 step_path。')
    recipe = compile_recipe(arguments['document'], selected_path=arguments.get('step_path'))
    return WorkflowCheckResult(
        status='success', mode='validation', name=recipe.document['name'], selected_path=list(recipe.path),
        reservations=recipe.profile, game_accessed=False, configuration_loaded=False, source_files_read=False,
    )


class TaskCapabilities:
    """Use the host's explicit allowlist for both discovery and dispatch."""

    def __init__(self, *, enabled: Collection[str]):
        self._enabled = frozenset(enabled)

    def discover(self) -> tuple[CapabilityInfo, ...]:
        screen = CapabilityInfo(
            id=SCREEN_CHECK_PLAN, version=SCREEN_CHECK_PLAN_VERSION,
            title='预览所选页面核对', description='离线预览所选页面的核对顺序和预算。',
            enabled=SCREEN_CHECK_PLAN in self._enabled, read_only=True,
            input_schema=_object_schema(dict(pages=_pages_schema())),
            output_schema=_object_schema(dict(
                status=dict(type='string', const='success'), mode=dict(type='string', const='preview'),
                pages=_pages_schema(), reservations=_reservations_schema(), game_accessed=dict(type='boolean', const=False),
            )),
        )
        workflow = CapabilityInfo(
            id=WORKFLOW_CHECK, version=WORKFLOW_CHECK_VERSION,
            title='校验任务流与静态预算', description='离线校验任务流或所选步骤，并计算其最大静态预留。',
            enabled=WORKFLOW_CHECK in self._enabled, read_only=True,
            input_schema=_object_schema(dict(
                document=_object_schema(dict(
                    version=dict(type='integer', const=1), name=dict(type='string', minLength=1, maxLength=80),
                    steps=dict(type='array', minItems=1, maxItems=MAX_NODES, items=dict(type='object')),
                )),
                step_path=dict(type='string', description='从零开始的步骤序号，例如 1/0。省略时校验整棵流程。'),
            ), optional=('step_path',)),
            output_schema=_object_schema(dict(
                status=dict(type='string', const='success'), mode=dict(type='string', const='validation'),
                name=dict(type='string'), selected_path=dict(type='array', maxItems=MAX_DEPTH,
                                                           items=dict(type='integer', minimum=0)),
                reservations=_reservations_schema(optional=_OPTIONAL_RESERVATIONS),
                game_accessed=dict(type='boolean', const=False), configuration_loaded=dict(type='boolean', const=False),
                source_files_read=dict(type='boolean', const=False),
            )),
        )
        return screen, workflow

    def dispatch(self, capability_id: str, version: int, arguments: object) -> ScreenCheckPlanResult | WorkflowCheckResult:
        if not isinstance(capability_id, str) or capability_id not in _VERSIONS:
            raise CapabilityError('unknown_capability', '未知任务能力。')
        if type(version) is not int or version != _VERSIONS[capability_id]:
            raise CapabilityError('unsupported_version', '任务能力版本不受支持。')
        if capability_id not in self._enabled:
            message = '所选页面核对预览已禁用。' if capability_id == SCREEN_CHECK_PLAN else '任务流校验已禁用。'
            raise CapabilityError('disabled', message)

        check = _screen_check if capability_id == SCREEN_CHECK_PLAN else _workflow_check
        try:
            return check(arguments)
        except ValueError as error:
            raise CapabilityError('invalid_arguments', str(error)) from error
