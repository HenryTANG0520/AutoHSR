"""Transport-neutral discovery and invocation for AutoHSR task capabilities."""

from collections.abc import Collection
from typing import Literal, TypedDict

from .task_workflow import WORKFLOW_PAGES, WorkflowError


SCREEN_CHECK_PLAN = 'autohsr.screen_check_plan'
SCREEN_CHECK_PLAN_VERSION = 1
_RESERVATION_FIELDS = ('daily_calls', 'du_calls', 'currency_calls', 'du_runs', 'currency_games', 'executions')


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


class CapabilityError(WorkflowError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _object_schema(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def _pages_schema():
    return dict(type='array', items=dict(type='string', enum=list(WORKFLOW_PAGES)),
                minItems=1, maxItems=len(WORKFLOW_PAGES), uniqueItems=True,
                description='按核对顺序填写。短信通知须单独选择，活动页须依次放在末尾。')


class TaskCapabilities:
    """Use the host's explicit allowlist for both discovery and dispatch."""

    def __init__(self, *, enabled: Collection[str]):
        self._enabled = frozenset(enabled)

    def discover(self) -> tuple[CapabilityInfo, ...]:
        output_schema = _object_schema(dict(
            status=dict(type='string', const='success'), mode=dict(type='string', const='preview'),
            pages=_pages_schema(),
            reservations=_object_schema({name: dict(type='integer', minimum=0) for name in _RESERVATION_FIELDS}),
            game_accessed=dict(type='boolean', const=False),
        ))
        return (CapabilityInfo(
            id=SCREEN_CHECK_PLAN, version=SCREEN_CHECK_PLAN_VERSION,
            title='预览所选页面核对', description='离线预览所选页面的核对顺序和预算。',
            enabled=SCREEN_CHECK_PLAN in self._enabled, read_only=True,
            input_schema=_object_schema(dict(pages=_pages_schema())), output_schema=output_schema,
        ),)

    def dispatch(self, capability_id: str, version: int, arguments: object) -> ScreenCheckPlanResult:
        if capability_id != SCREEN_CHECK_PLAN:
            raise CapabilityError('unknown_capability', '未知任务能力。')
        if type(version) is not int or version != SCREEN_CHECK_PLAN_VERSION:
            raise CapabilityError('unsupported_version', '任务能力版本不受支持。')
        if capability_id not in self._enabled:
            raise CapabilityError('disabled', '所选页面核对预览已禁用。')
        if not isinstance(arguments, dict) or arguments.keys() != {'pages'} or not isinstance(arguments['pages'], list):
            raise CapabilityError('invalid_arguments', '预览参数须为仅包含 pages 列表的对象。')

        from .selected_page_check import build_recipe

        try:
            recipe = build_recipe(arguments['pages'])
        except WorkflowError as error:
            raise CapabilityError('invalid_arguments', str(error)) from error
        return ScreenCheckPlanResult(
            status='success', mode='preview', pages=[step['params']['target'] for step in recipe.steps],
            reservations={name: recipe.profile[name] for name in _RESERVATION_FIELDS}, game_accessed=False,
        )
