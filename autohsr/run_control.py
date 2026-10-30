"""Read explicit stop intent independently of mutable report-save outcomes.

No runner internals, native APIs, report mutation, or truthy approximations are
used. The thread-local guard bounds malformed recursive wrapper relationships.
"""
from threading import local


_reads = local()


def stop_requested(runner=None, report=None) -> bool:
    """Accept only a literal runner True or an original stopped report."""
    active = getattr(_reads, 'active', None)
    if active is None:
        active = set()
        _reads.active = active
    if runner is not None:
        key = ('runner', id(runner))
        if key not in active:
            active.add(key)
            try:
                if getattr(runner, 'stop_requested', None) is True:
                    return True
            except Exception:
                # A broken optional observer is not evidence of a stop. The
                # independent original report may still provide that evidence.
                pass
            finally:
                active.remove(key)
    if report is not None:
        key = ('report', id(report))
        if key not in active:
            active.add(key)
            try:
                status = report.get('status') if isinstance(report, dict) else getattr(report, 'status', None)
                return type(status) is str and status == 'stopped'
            except Exception:
                pass
            finally:
                active.remove(key)
    return False
