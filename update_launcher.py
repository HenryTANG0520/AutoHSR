"""Entry point for the independent Windows updater."""

from pathlib import Path
import sys

from autohsr.app_update import UpdateError
from autohsr.app_update_handoff import worker


if __name__ == '__main__':
    if sys.argv[1:] == ['--protocol-check']:
        from autohsr.app_update_handoff import PROTOCOL

        raise SystemExit(0 if PROTOCOL == 1 else 1)
    if len(sys.argv) != 2:
        raise SystemExit(2)
    try:
        raise SystemExit(worker(Path(sys.argv[1])))
    except (OSError, UpdateError):
        raise SystemExit(1)
