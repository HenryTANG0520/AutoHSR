"""The daily-training search adapter for the authorized single-item craft."""

from .daily_synthesis import task_target


def synthesis_target(pair, view):
    first, second = (task_target(frame.scene) for frame in pair)
    if (first is not None and second is not None
            and all(abs(a - b) <= .006 for a, b in zip(first.box, second.box))
            and any(card['task'] == 'synthesis' and card['state'] == 'pending'
                    and abs(center - second.center[0]) <= .035
                    for card, center in zip(view.cards, view.centers))):
        return 'synthesis'
    return None
