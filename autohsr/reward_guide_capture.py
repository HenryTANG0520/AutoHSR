"""One explicit, foreground-only capture of a verified Reward Guide viewport."""

from .daily_observe import SCREEN_OPERATION
from .models import AutomationError, Stopped
from .reward_guide_export import _Rejected, _publish, _target


def _receipt(status, *, width=None, height=None):
    return dict(status=status, input_sent=False, visible_section='ongoing' if status == 'ok' else None,
                width=width, height=height)


class RewardGuideCapture:
    def __init__(self, destination, *, navigate_first=False):
        self._target = _target(destination)
        self.navigate_first = navigate_first
        self._navigation = None
        self.receipt = None

    def navigate(self, context):
        from .workflow_navigation import WorkflowNavigation

        if self._navigation is not None:
            raise AutomationError('本次奖励指南导航已经启动。')
        try:
            if _target(self._target[0]) != self._target:
                raise _Rejected('invalid_target')
        except _Rejected as error:
            self.receipt = _receipt(str(error))
            raise AutomationError('奖励指南导出位置已变化，未发送导航输入。') from None
        self._navigation = context.workflow_navigation = WorkflowNavigation(context, 'reward_guide')
        self._navigation.run()

    def require_handoff(self, reader, pair, installation):
        if self._navigation is not None:
            self._navigation.require_guide_handoff(reader, pair, installation)

    def with_navigation(self, receipt):
        if self._navigation is None:
            return receipt
        record = self._navigation.record
        actions = record['actions']
        sent = any(row['input_status'] == 'sent' for row in actions)
        return dict(receipt, input_sent=sent if sent or not actions else None,
                    navigation=dict(page_verified=record['page_verified'], actions=actions))

    def publish(self, observer):
        if self.receipt is not None:
            return
        try:
            with observer.reward_guide_crop() as (image, check):
                _publish(self._target, (), image, check)
                height, width = image.shape[:2]
                self.receipt = _receipt('ok', width=width, height=height)
        except Stopped:
            self.receipt = _receipt('stopped')
        except AutomationError:
            self.receipt = _receipt('unverified')
        except _Rejected as error:
            self.receipt = _receipt(str(error))
        except (OSError, RuntimeError, TypeError, ValueError):
            self.receipt = _receipt('publish_failed')
        except KeyboardInterrupt:
            self.receipt = _receipt('publish_unverified')
            raise

    def result(self, report):
        if self.receipt is not None:
            return self.with_navigation(self.receipt)
        if report.status == 'stopped':
            return self.with_navigation(_receipt('stopped'))
        return self.with_navigation(_receipt('report_unverified' if report.report_saved is not True else 'unverified'))


def capture_reward_guide(settings, capture):
    from .app import Runner

    runner = Runner(settings, operation=SCREEN_OPERATION, reward_guide_capture=capture,
                    observation_wait_for_foreground=capture.navigate_first is True)
    return capture.result(runner.run())
