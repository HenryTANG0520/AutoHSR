"""Shared mode routing for the desktop and CLI daily page checks."""

MESSAGE_OPERATION = 'daily_message_observe'
EVENT_OPERATION = 'daily_event_observe'
EVENT_CLAIM_OPERATION = 'daily_event_claim'
ACHIEVEMENT_CLAIM_OPERATION = 'achievement_bulk_claim'
REWARD_OPERATION = 'daily_reward_observe'
SCREEN_OPERATION = 'screen_test'
READ_ONLY_OPERATIONS = frozenset((MESSAGE_OPERATION, EVENT_OPERATION, SCREEN_OPERATION))
OPERATIONS = READ_ONLY_OPERATIONS | {REWARD_OPERATION}
MODES = ('achievements', 'support', 'messages', 'odyssey')


def operation_for(mode):
    if mode == 'screen':
        return SCREEN_OPERATION
    if mode not in MODES:
        raise ValueError('请选择受支持的日常页面。')
    if mode in ('achievements', 'support'):
        return REWARD_OPERATION
    return MESSAGE_OPERATION if mode == 'messages' else EVENT_OPERATION


def runner_for(settings, emit, mode, *, wait_for_foreground=False):
    from .app import Runner

    operation = operation_for(mode)
    return Runner(settings, emit, operation=operation, daily_reward_mode=mode if operation == REWARD_OPERATION else None,
                  observation_wait_for_foreground=wait_for_foreground)
