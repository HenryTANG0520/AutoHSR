"""Explicit entry for weekly relic cleanup. It never starts a daily or plan run."""
from datetime import datetime
import json
from pathlib import Path

from .config import ROOT, Settings, SettingsError
from .models import AutomationError
from .weekly_plan import CHINA
from .weekly_relic_cleanup import LEDGER_NAME, TimestampStore, open_live_port, perform


def _failed(error):
    print(json.dumps({'status': 'failed', 'operation': 'weekly_relic_cleanup',
                      'timestamp_written': False, 'error': str(error)}, ensure_ascii=False))
    return 1


def run(args, raw_args, parser, *, port_factory=None, now=None, store_path=None):
    flags = [argument.partition('=')[0] for argument in raw_args if argument.startswith('--')]
    allowed = {'--weekly-relic-cleanup', '--config', '--game-path'}
    if flags.count('--weekly-relic-cleanup') != 1 or set(flags) - allowed:
        parser.error('周遗器清理为独立入口，仅可附带 --config 和 --game-path，不会随日常执行。')
    try:
        settings = Settings.load(args.config)
        if args.game_path is not None:
            settings.game_path = args.game_path
        clock = now or datetime.now(CHINA)
        store = Path(store_path) if store_path is not None else ROOT / 'runs' / LEDGER_NAME
        result = perform(settings, TimestampStore(store), clock, invoked=True,
                         port_factory=port_factory or open_live_port)
    except (OSError, ValueError, TypeError, SettingsError, AutomationError) as error:
        return _failed(error)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in {'success', 'skipped'} else 1
