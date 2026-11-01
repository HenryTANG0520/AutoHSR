"""Offline card browsing checks: mapped transparent windows, no desktop input."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from unittest.mock import patch

from ux_smoke import ROOT, Settings, Window, module

OUT = ROOT / 'runs/task-board-navigation'


def main():
    checks, errors = [], []
    def check(name, value):
        assert value, (name, errors)
        checks.append(name)
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder)
        config = local / 'config.json'
        Settings(overlay_logs=False).save(config)
        saved = config.read_bytes()
        with patch.object(module, 'ROOT', local), patch.object(Window, '_start', side_effect=AssertionError('No backend allowed')):
            for scale in (1., 1.25, 1.5, 2.):
                root = tk.Tk()
                root.withdraw()
                root.attributes('-alpha', 0)
                root.attributes('-disabled', True)
                root.tk.call('tk', 'scaling', scale * 96 / 72)
                root.report_callback_exception = lambda kind, value, trace: errors.append(str(value))
                ui = Window(root, config)
                try:
                    for size, dimensions in (('default', (1536, 864)), ('minimum', (1100, 800))):
                        root.geometry(f'{round(dimensions[0]*scale)}x{round(dimensions[1]*scale)}')
                        root.deiconify()
                        ui._show_page('home')
                        root.update()
                        board = ui.table
                        board.offset = 0
                        board.selection_remove()
                        root.update()
                        before = {key: value.get() for key, value in ui.tasks.items()}
                        signature = ui._form_signature()
                        prefix = f'{scale}_{size}_'
                        keys = list(board.names)
                        visible = board.visible_count
                        board._set_hover(keys[2])
                        board.event_generate('<MouseWheel>', delta=-120)
                        root.update()
                        check(prefix+'one_wheel_reveals_next_card', board.offset == 1 and keys[visible] in board.hitboxes and board.hitboxes[keys[visible]][2]-board.hitboxes[keys[visible]][0] >= board.card_width-1)
                        check(prefix+'scroll_removes_old_card_hover', board.hover is None)
                        board.event_generate('<MouseWheel>', delta=120)
                        root.update()
                        check(prefix+'reverse_wheel_returns_first_page', board.offset == 0)
                        board.event_generate('<MouseWheel>', delta=0)
                        root.update()
                        check(prefix+'zero_wheel_does_not_move', board.offset == 0)
                        partial = keys[visible]
                        x1, y1, x2, y2 = board.hitboxes[partial]
                        board.event_generate('<Button-1>', x=round((x1+x2)/2*scale), y=round((y1+y2)/2*scale))
                        root.update()
                        check(prefix+'partial_card_reveals_without_editing', board.offset == 1 and board.selected == partial and ui.active_page == 'home' and before == {key: value.get() for key, value in ui.tasks.items()})
                        board.event_generate('<MouseWheel>', delta=120)
                        root.update()
                        board.selected = keys[1]
                        board.event_generate('<MouseWheel>', delta=-120)
                        root.update()
                        check(prefix+'visible_selection_survives_browsing', board.selected == keys[1])
                        board.event_generate('<MouseWheel>', delta=120)
                        root.update()
                        board.selected = keys[0]
                        board.event_generate('<MouseWheel>', delta=-120)
                        root.update()
                        check(prefix+'hidden_selection_cannot_own_enter', board.selected is None)
                        calls = []
                        with patch.object(ui, '_show_task_setup', side_effect=calls.append):
                            board.event_generate('<Return>')
                            # Disabled windows do not receive native keyboard focus;
                            # invoke the bound action locally to check its target.
                            if not calls:
                                board.activate()
                            root.update()
                        check(prefix+'enter_acts_on_visible_head', calls == [keys[1]] and board.selected == keys[1])
                        for _ in range(len(keys)+2):
                            board.event_generate('<MouseWheel>', delta=-120)
                        root.update()
                        check(prefix+'wheel_stops_at_last_full_page', board.offset == len(keys)-visible)
                        board.move(-len(keys))
                        root.update()
                        check(prefix+'keyboard_reveals_first_selected_card', board.offset == 0 and board.selected == keys[0])
                        x1, y1, x2, y2 = board.hitboxes['next']
                        board.event_generate('<Button-1>', x=round((x1+x2)/2*scale), y=round((y1+y2)/2*scale))
                        root.update()
                        check(prefix+'arrow_browses_and_clears_hidden_selection', board.offset == 1 and board.selected is None)
                        board.move(len(keys))
                        root.update()
                        check(prefix+'keyboard_reveals_last_selected_card', board.selected == keys[-1] and board.offset == len(keys)-visible)
                        # A resized page can leave an old selection outside the
                        # fully visible range. First activation must reveal it.
                        board.offset = 0
                        board.selected = keys[-1]
                        board.redraw()
                        root.update()
                        calls = []
                        with patch.object(ui, '_show_task_setup', side_effect=calls.append):
                            board.activate()
                            root.update()
                        check(prefix+'offscreen_activation_reveals_without_action', not calls and board.offset == len(keys)-visible and board.selected == keys[-1])
                        check(prefix+'browsing_never_changes_plan', signature == ui._form_signature() and before == {key: value.get() for key, value in ui.tasks.items()} and not ui.dirty)
                        check(prefix+'browsing_never_saves', config.read_bytes() == saved)
                    check(f'{scale}_no_callback_errors', not errors)
                finally:
                    ui.closing = True
                    for token in root.tk.splitlist(root.tk.call('after', 'info')):
                        if str(root.tk.call('after', 'info', token)[0]).endswith('_drain'):
                            root.after_cancel(token)
                    root.destroy()
    result = dict(checks=checks, count=len(checks), os_input=False, desktop_capture=False, game_started=False, native_pixels_verified=False)
    (OUT / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
