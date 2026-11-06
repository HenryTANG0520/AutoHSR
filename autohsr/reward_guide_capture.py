"""One explicit, foreground-only capture of a verified Reward Guide viewport."""

from .daily_observe import SCREEN_OPERATION
from .models import AutomationError, Stopped
from .reward_guide_export import _Rejected, _publish, _target


def _receipt(status, *, width=None, height=None):
    return dict(status=status, input_sent=False, visible_section='ongoing' if status == 'ok' else None,
                width=width, height=height)


class RewardGuideCapture:
    def __init__(self, destination):
        self._target = _target(destination)
        self.receipt = None

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


def capture_reward_guide(settings, capture):
    from .app import Runner

    runner = Runner(settings, operation=SCREEN_OPERATION, reward_guide_capture=capture)
    report = runner.run()
    if capture.receipt is not None:
        return capture.receipt
    if report.status == 'stopped':
        return _receipt('stopped')
    return _receipt('report_unverified' if report.report_saved is not True else 'unverified')
