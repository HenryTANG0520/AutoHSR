"""Geometry checks shared by the offline desktop acceptance scripts.

The caller supplies desktop_dialogs._work_area; importing this module neither
imports Tk nor consults a native window or monitor.
"""
from __future__ import annotations


_HEIGHT_CHECKED = frozenset((
    'TLabel', 'TButton', 'TCheckbutton', 'TEntry', 'TCombobox',
    'Label', 'Button', 'Checkbutton', 'Entry',
))


def _client_rect(widget):
    x, y = widget.winfo_rootx(), widget.winfo_rooty()
    return x, y, x + widget.winfo_width(), y + widget.winfo_height()


def _outer_rect(window):
    # Match the frame measurement used by desktop_dialogs.place_dialog.
    left, top, right, bottom = _client_rect(window)
    side = max(0, left - window.winfo_x())
    title = max(0, top - window.winfo_y())
    return left - side, top - title, right + side, bottom + side


def _fail(check, widget, window, **details):
    # Widget paths and geometry help identify a failure without reading titles,
    # label text, report contents, or other application data.
    raise AssertionError(dict(
        check=check, widget=str(widget), type=widget.winfo_class(),
        master=str(widget.master) if widget.master is not None else None,
        rect=_client_rect(widget), window=str(window), client=_client_rect(window),
        **details,
    ))


def check_layout(root, *, work_area):
    """Check every mapped descendant against its own window's client area.

    An owned Toplevel is an independent window: its outer frame must fit the
    owner's monitor work area, and its controls must fit its own client area.
    ``work_area(owner)`` follows desktop_dialogs._work_area's LTRB contract.
    The checker only reads geometry; it does not update or create windows.
    """
    def walk(widget, window):
        # Tcl-only combobox popdowns need not have Python wrappers. Snapshot the
        # Python-owned tree without querying or resolving those Tcl window names.
        # Keep owned Toplevels in this tree: their separate bounds still matter.
        for child in tuple(widget.children.values()):
            independent = child.winfo_toplevel() is child
            if independent:
                if child.winfo_ismapped():
                    outer = _outer_rect(child)
                    monitor = tuple(work_area(window))
                    if not (monitor[0] <= outer[0] and monitor[1] <= outer[1]
                            and outer[2] <= monitor[2] and outer[3] <= monitor[3]):
                        _fail('window_outside_work_area', child, child,
                              owner=str(window), outer=outer, work_area=monitor)
                walk(child, child)
                continue

            if child.winfo_ismapped():
                left, top, right, bottom = _client_rect(child)
                bounds = _client_rect(window)
                # Preserve the original two-pixel right/bottom rounding margin.
                if not (bounds[0] <= left and bounds[1] <= top
                        and right <= bounds[2] + 2 and bottom <= bounds[3] + 2):
                    _fail('content_outside_client', child, window)
                if (child.winfo_class() in _HEIGHT_CHECKED
                        and child.winfo_height() < child.winfo_reqheight()):
                    _fail('clipped_control_height', child, window,
                          requested_height=child.winfo_reqheight())
            # A Toplevel can remain mapped even when its logical master is not.
            # Continue through hidden containers so that window is still checked.
            walk(child, window)

    walk(root, root)
