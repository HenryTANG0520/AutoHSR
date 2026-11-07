"""The daily-training search adapter for the authorized single-item craft."""

from .daily_synthesis import task_target
from .daily_training_search import search_task


def _synthesis_target(pair, view, _confidence):
    first, second = (task_target(frame.scene) for frame in pair)
    if (first is not None and second is not None
            and all(abs(a - b) <= .006 for a, b in zip(first.box, second.box))
            and any(card['task'] == 'synthesis' and card['state'] == 'pending'
                    and abs(center - second.center[0]) <= .035
                    for card, center in zip(view.cards, view.centers))):
        return True
    return None


def find_hidden_card(workflow, scene, activity):
    """Return the current frame and whether a freshly settled synthesis card is actionable."""
    if not (workflow.settings.daily and workflow.settings.daily_synthesis):
        return scene, False
    receipt = {}
    try:
        current, found = search_task(workflow, scene, activity, _synthesis_target, receipt)
        return current, found is True
    finally:
        if receipt:
            workflow.ctx.report.training_synthesis_search = receipt
