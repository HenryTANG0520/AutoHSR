"""Window-boundary geometry tests: no Tk, native windows, or screenshots."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest

from tools.gui_layout import check_layout


class Widget:
    """Only the geometry protocol read by the checker and place_dialog."""
    def __init__(self, name, master=None, *, x=0, y=0, width=100, height=30,
                 kind='TFrame', window=False, mapped=True, requested_height=None,
                 side=0, top=0):
        self.name, self.master, self.kind = name, master, kind
        self.x, self.y, self.width, self.height = x, y, width, height
        self.window, self.mapped = window, mapped
        self.side, self.top = side, top
        self.requested_height = height if requested_height is None else requested_height
        self.children = {}
        self.minimum = None
        if master is not None:
            master.children[self.name] = self

    def __str__(self):
        return self.name

    def winfo_children(self):
        return tuple(self.children.values())

    def winfo_ismapped(self):
        return self.mapped

    def winfo_toplevel(self):
        return self if self.window else self.master.winfo_toplevel()

    def winfo_rootx(self):
        return self.x + (self.side if self.window else 0)

    def winfo_rooty(self):
        return self.y + (self.top if self.window else 0)

    def winfo_x(self):
        return self.x

    def winfo_y(self):
        return self.y

    def winfo_width(self):
        return self.width

    def winfo_height(self):
        return self.height

    def winfo_class(self):
        return self.kind

    def winfo_reqheight(self):
        return self.requested_height

    def geometry(self, value):
        matched = re.fullmatch(r'(\d+)x(\d+)(?:\+(-?\d+)\+(-?\d+))?', value)
        if matched is None:
            raise AssertionError('unexpected geometry syntax in model')
        self.width, self.height = map(int, matched.group(1, 2))
        if matched.group(3) is not None:
            self.x, self.y = map(int, matched.group(3, 4))

    def update_idletasks(self):
        pass

    def minsize(self, width, height):
        self.minimum = width, height

    def title(self, *args):
        raise AssertionError('checker must not read a private title')

    def cget(self, *args):
        raise AssertionError('checker must not read private widget text')


class UnresolvableTclChildren(Widget):
    def winfo_children(self):
        # A deliberately failing resolver models an unwrapped Tcl-only popdown.
        # The checker must use children, not rely on Tcl-name resolution at all.
        raise KeyError('unwrapped Tcl-only popdown')


def root_window(**kwargs):
    return Widget('.', kind='Tk', window=True, width=1100, height=800, **kwargs)


def legacy_layout(root):
    # Exact pre-fix checker, retained only to demonstrate its wrong boundary.
    def walk(widget):
        for child in widget.winfo_children():
            if not child.winfo_ismapped():
                continue
            x = child.winfo_rootx() - root.winfo_rootx()
            y = child.winfo_rooty() - root.winfo_rooty()
            assert x >= 0 and y >= 0, (str(child), x, y)
            assert x + child.winfo_width() <= root.winfo_width() + 2, (str(child), 'width')
            assert y + child.winfo_height() <= root.winfo_height() + 2, (str(child), 'height')
            if child.winfo_class() in ('TLabel', 'TButton', 'TCheckbutton', 'TEntry', 'TCombobox'):
                assert child.winfo_height() >= child.winfo_reqheight(), (str(child), 'clipped')
            walk(child)
    walk(root)


def actual_place_dialog(work_area):
    # Compile only the existing pure placement function, without importing the
    # desktop module (and therefore without importing Tk or calling monitor APIs).
    path = Path(__file__).resolve().parents[1] / 'desktop_dialogs.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'place_dialog')
    scope = {'_work_area': work_area}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), scope)
    return scope['place_dialog']


class GuiLayoutTests(unittest.TestCase):
    def setUp(self):
        self.area = (0, 0, 1920, 1080)
        self.owners = []

    def work_area(self, owner):
        self.owners.append(owner)
        return self.area

    def test_actual_placement_exposes_old_checker_boundary_and_new_checker_passes(self):
        root = root_window()
        popup = Widget('.!toplevel', root, kind='Toplevel', window=True, side=8, top=31)
        actual_place_dialog(self.work_area)(popup, root, (1200, 500), (400, 220))
        Widget('.!toplevel.!button', popup, kind='TButton',
               x=popup.winfo_rootx()+20, y=popup.winfo_rooty()+20)
        self.assertGreater(popup.winfo_rootx()+popup.width, root.width+2)
        with self.assertRaises(AssertionError) as rejected:
            legacy_layout(root)
        self.assertEqual(rejected.exception.args, (('.!toplevel', 'width'),))
        self.owners.clear()
        check_layout(root, work_area=self.work_area)
        self.assertEqual(self.owners, [root])

    def test_root_content_still_must_fit_root_client(self):
        root = root_window(x=200, y=100)
        Widget('.!frame', root, x=1290, y=120, width=30, height=30)
        with self.assertRaises(AssertionError) as rejected:
            check_layout(root, work_area=self.work_area)
        self.assertEqual(rejected.exception.args[0]['check'], 'content_outside_client')
        self.assertEqual(rejected.exception.args[0]['window'], '.')
        self.assertEqual(self.owners, [])

    def test_popup_content_uses_own_client_even_when_it_fits_root(self):
        for x, y, width, height in ((490, 120, 30, 30), (120, 290, 30, 30), (99, 120, 30, 30)):
            with self.subTest(rect=(x, y, width, height)):
                root = root_window()
                popup = Widget('.!toplevel', root, kind='Toplevel', window=True,
                               x=100, y=100, width=400, height=200)
                Widget('.!toplevel.!frame', popup, x=x, y=y, width=width, height=height)
                with self.assertRaises(AssertionError) as rejected:
                    check_layout(root, work_area=self.work_area)
                self.assertEqual(rejected.exception.args[0]['check'], 'content_outside_client')
                self.assertEqual(rejected.exception.args[0]['window'], '.!toplevel')

    def test_independent_window_must_fit_monitor(self):
        for x, y in ((-1, 20), (20, -1), (1830, 20), (20, 1000)):
            with self.subTest(position=(x, y)):
                root = root_window()
                Widget('.!toplevel', root, kind='Toplevel', window=True,
                       x=x, y=y, width=100, height=100)
                with self.assertRaises(AssertionError) as rejected:
                    check_layout(root, work_area=self.work_area)
                self.assertEqual(rejected.exception.args[0]['check'], 'window_outside_work_area')
                self.assertEqual(rejected.exception.args[0]['work_area'], self.area)

    def test_native_frame_is_included_in_monitor_bounds(self):
        root = root_window()
        # Client right=1916 is on-screen; its eight-pixel frame is not.
        Widget('.!toplevel', root, kind='Toplevel', window=True,
               x=1808, y=100, width=100, height=100, side=8, top=31)
        with self.assertRaises(AssertionError) as rejected:
            check_layout(root, work_area=self.work_area)
        self.assertEqual(rejected.exception.args[0]['outer'], (1808, 100, 1924, 239))

    def test_popup_controls_are_checked_for_clipped_height(self):
        for kind in ('TLabel', 'TButton', 'TCheckbutton', 'TEntry', 'TCombobox', 'Label'):
            with self.subTest(kind=kind):
                root = root_window()
                popup = Widget('.!toplevel', root, kind='Toplevel', window=True,
                               x=100, y=100, width=400, height=200)
                Widget('.!toplevel.!control', popup, kind=kind, x=120, y=120,
                       height=18, requested_height=20)
                with self.assertRaises(AssertionError) as rejected:
                    check_layout(root, work_area=self.work_area)
                self.assertEqual(rejected.exception.args[0]['check'], 'clipped_control_height')

    def test_popup_under_hidden_master_is_not_skipped(self):
        root = root_window()
        hidden = Widget('.!frame', root, mapped=False)
        popup = Widget('.!frame.!toplevel', hidden, kind='Toplevel', window=True,
                       x=1200, y=100, width=400, height=200)
        Widget('.!frame.!toplevel.!button', popup, kind='TButton', x=1220, y=120)
        check_layout(root, work_area=self.work_area)
        self.assertEqual(self.owners, [root])
        popup.x = 1900
        with self.assertRaises(AssertionError):
            check_layout(root, work_area=self.work_area)

    def test_python_owned_tree_checks_controls_and_popups_without_tcl_resolution(self):
        for overflow, expected in ((None, None), ('root', 'content_outside_client'),
                                   ('popup', 'window_outside_work_area'),
                                   ('popup_content', 'content_outside_client')):
            with self.subTest(overflow=overflow):
                root = UnresolvableTclChildren('.', kind='Tk', window=True, width=1100, height=800)
                Widget('.!button', root, kind='TButton', x=1090 if overflow == 'root' else 20, y=20)
                hidden = UnresolvableTclChildren('.!combobox', root, kind='TCombobox', mapped=False)
                popup = UnresolvableTclChildren('.!combobox.!toplevel', hidden, kind='Toplevel',
                    window=True, x=1900 if overflow == 'popup' else 1200, y=100, width=400, height=200)
                Widget('.!combobox.!toplevel.!button', popup, kind='TButton',
                       x=1585 if overflow == 'popup_content' else 1220, y=120, width=30)
                if expected is None:
                    check_layout(root, work_area=self.work_area)
                else:
                    with self.assertRaises(AssertionError) as rejected:
                        check_layout(root, work_area=self.work_area)
                    self.assertEqual(rejected.exception.args[0]['check'], expected)

    def test_nested_window_uses_its_owner_monitor_contract(self):
        root = root_window()
        popup = Widget('.!toplevel', root, kind='Toplevel', window=True,
                       x=1200, y=100, width=400, height=200)
        inner = Widget('.!toplevel.!frame', popup, x=1220, y=120)
        Widget('.!toplevel.!frame.!toplevel', inner, kind='Toplevel', window=True,
               x=1600, y=100, width=300, height=200)
        check_layout(root, work_area=self.work_area)
        self.assertEqual(self.owners, [root, popup])

    def test_negative_monitor_origin_and_original_content_rounding_margin(self):
        self.area = (-1920, -100, 0, 980)
        root = root_window(x=-1600, y=0)
        Widget('.!frame', root, x=-1600, y=0, width=1102, height=802)
        popup = Widget('.!toplevel', root, kind='Toplevel', window=True,
                       x=-1900, y=-80, width=1800, height=900)
        Widget('.!toplevel.!label', popup, kind='TLabel', x=-1880, y=-60)
        check_layout(root, work_area=self.work_area)

    def test_failure_records_geometry_without_reading_private_content(self):
        root = root_window()
        Widget('.!toplevel', root, kind='Toplevel', window=True,
               x=1900, y=100, width=100, height=100)
        with self.assertRaises(AssertionError) as rejected:
            check_layout(root, work_area=self.work_area)
        details = rejected.exception.args[0]
        self.assertEqual(details['type'], 'Toplevel')
        self.assertEqual(details['master'], '.')
        self.assertEqual(details['rect'], (1900, 100, 2000, 200))
        self.assertNotIn('title', details)
        self.assertNotIn('text', details)


if __name__ == '__main__':
    unittest.main()
