"""One explicitly scoped startup through the formal CLI, stopping before rewards.

Raw stdout/stderr stay local. This wrapper neither implements game input nor
loosens an existing Context guard; allowed actions delegate to original methods.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCOPES = ('phone', 'currency-home')
NAVIGATION = frozenset(('open_guide', 'open_universe_guide', 'select_currency_guide',
                        'participate', 'interact_currency'))
REWARDS = frozenset(('claim_supply', 'close_supply', 'close_login_reward'))


@contextmanager
def _storage_guard(result):
    try:
        yield
    except Exception:
        # Include stream open/close failures without losing earlier delegation
        # or letting a filesystem exception escape to the public console.
        result.update(code=2, status='probe_storage_failed')


@contextmanager
def _local_streams(stdout, stderr):
    # Python redirects capture CLI JSON/tracebacks. Descriptor redirects also
    # keep direct library writes to standard fd 1/2 out of the public result.
    sys.stdout.flush()
    sys.stderr.flush()
    with ExitStack() as stack:
        for descriptor, destination in ((1, stdout), (2, stderr)):
            saved = os.dup(descriptor)
            stack.callback(os.close, saved)
            stack.callback(os.dup2, saved, descriptor)
            os.dup2(destination.fileno(), descriptor)
        stack.enter_context(redirect_stdout(stdout))
        stack.enter_context(redirect_stderr(stderr))
        try:
            yield
        finally:
            stdout.flush()
            stderr.flush()


def _runtime():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from autohsr import __main__ as cli
    from autohsr.app import Context
    from autohsr.config import Settings
    from autohsr.models import Stopped
    from autohsr.workflows import DailyWorkflow
    return SimpleNamespace(cli_main=cli.main, Context=Context, Settings=Settings,
                           Stopped=Stopped, DailyWorkflow=DailyWorkflow)


def run_probe(scope, *, output_root=ROOT/'runs/interface-startup-probe', runtime=None):
    """Call the formal CLI once; ``input_actions`` report delegation, not proof.

    Injection is for pure tests. The command line cannot replace the runtime,
    pass gameplay flags, or run an implicit GUI when scope is absent.
    """
    if scope not in SCOPES:
        raise ValueError('An explicit supported scope is required.')
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ_')+uuid.uuid4().hex[:12]
    directory = Path(output_root).resolve()/name
    directory.mkdir(parents=True, exist_ok=False)
    result = dict(code=2, status='probe_failed', scope=scope, input_actions=[])
    boundary = None
    used = set()
    with _storage_guard(result), (directory/'stdout.log').open('x', encoding='utf-8') as stdout, \
            (directory/'stderr.log').open('x', encoding='utf-8') as stderr, \
            _local_streams(stdout, stderr):
        try:
            runtime = runtime or _runtime()
            original_load = runtime.Settings.load
            original_click = runtime.Context.currency_prepare_click
            original_back = runtime.Context.currency_prepare_back
            original_navigation = runtime.Context.currency_navigation_input

            def stop(context, scene, status):
                nonlocal boundary
                boundary = status
                try:
                    context.evidence(scene, 'interface_startup_scope_boundary')
                except BaseException:
                    boundary = 'scope_evidence_unverified'
                    raise
                raise runtime.Stopped('无消耗界面校准到达范围边界；未发送此动作。')

            def delegate(context, scene, intent, original, *args):
                if intent in used:
                    stop(context, scene, 'stopped_before_repeated_input')
                used.add(intent)
                row = dict(intent=intent, status='delegated')
                result['input_actions'].append(row)
                try:
                    value = original(context, scene, *args)
                except BaseException:
                    row['status'] = 'unverified'
                    raise
                row['status'] = 'method_returned'
                return value

            def load(cls, *args, **kwargs):
                settings = deepcopy(original_load(*args, **kwargs))
                settings.overlay_logs = False
                return settings

            def click(context, scene, intent, target):
                if intent != 'enter_game':
                    stop(context, scene, 'stopped_before_reward' if intent in REWARDS
                         else 'stopped_before_unapproved_input')
                return delegate(context, scene, 'enter_game', original_click, intent, target)

            def back(context, scene):
                if not runtime.DailyWorkflow(context)._world(scene):
                    stop(context, scene, 'stopped_before_menu_escape')
                return delegate(context, scene, 'open_phone', original_back)

            def navigation(context, scene, choice):
                intent = getattr(choice, 'intent', None)
                if scope != 'currency-home' or intent not in NAVIGATION:
                    stop(context, scene, 'stopped_before_open_mode' if intent == 'open_mode'
                         else 'stopped_before_unapproved_navigation')
                return delegate(context, scene, intent, original_navigation, choice)

            with ExitStack() as patches:
                patches.enter_context(patch.object(runtime.Settings, 'load', classmethod(load)))
                patches.enter_context(patch.object(runtime.Context, 'currency_prepare_click', click))
                patches.enter_context(patch.object(runtime.Context, 'currency_prepare_back', back))
                patches.enter_context(patch.object(runtime.Context, 'currency_navigation_input', navigation))
                flag = '--currency-wars-prepare' if scope == 'phone' else '--currency-wars-locate'
                code = runtime.cli_main([flag, '--no-notify'])
                result['code'] = code if type(code) is int and code in (0, 1, 2, 130) else 2
                result['status'] = boundary or 'cli_returned'
        except BaseException as error:
            # Raw errors can contain install paths or OCR. Keep them in this
            # invocation's local stderr, never interpolate them into the result.
            traceback.print_exc(file=stderr)
            stopped = runtime is not None and isinstance(error, runtime.Stopped)
            result['code'] = 130 if isinstance(error, KeyboardInterrupt) else 1 if stopped else 2
            result['status'] = boundary or ('stopped' if stopped else 'probe_failed')
    try:
        (directory/'summary.json').write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding='utf-8')
    except Exception:
        # A report write failure cannot erase delegation that already occurred.
        result.update(code=2, status='probe_summary_unverified')
    return result


def main(argv=None, *, runtime=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=SCOPES, required=True)
    parser.add_argument('--output-root', type=Path, default=ROOT/'runs/interface-startup-probe')
    args = parser.parse_args(argv)
    try:
        value = run_probe(args.scope, output_root=args.output_root, runtime=runtime)
    except Exception:
        value = dict(code=2, status='probe_storage_failed', scope=args.scope, input_actions=[])
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return value['code']


if __name__ == '__main__':
    raise SystemExit(main())
