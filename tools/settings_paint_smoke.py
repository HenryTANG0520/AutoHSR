"""Compare the bounded settings artwork with the original full-canvas render."""
from pathlib import Path
import json
import sys
import tempfile
import tkinter as tk
import types
from unittest.mock import patch

from PIL import Image, ImageChops, ImageGrab, ImageTk
from ux_smoke import ROOT, Settings, Window, module
from autohsr import theme
from autohsr.desktop_settings import SECTIONS


def main():
    out = ROOT/"runs/settings-paint-ui"
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append(name)
    def reject(*args, **kwargs):
        raise AssertionError("Painting checks cannot start a game backend")
    fake = types.ModuleType("autohsr.app")
    fake.Runner = reject
    with tempfile.TemporaryDirectory() as folder, patch.object(module, "ROOT", Path(folder)), \
            patch.dict(sys.modules, {"autohsr.app": fake}):
        config = Path(folder)/"config.json"
        Settings().save(config)
        original = config.read_bytes()
        for dpi in (1., 1.5, 2.):
            root = tk.Tk()
            root.tk.call("tk", "scaling", dpi*96/72)
            root.report_callback_exception = lambda kind, value, tb: (_ for _ in ()).throw(value.with_traceback(tb))
            ui = Window(root, config)
            try:
                root.update()
                ui._show_daily_tasks("mail")
                for sample, (size, label) in enumerate((("normal", "normal"), ("zoomed", "zoomed"), ("normal", "restored"))):
                    ui.stamina.set(str(120+sample*10))
                    ui.elapsed_seconds = 65+sample
                    ui._clock()
                    root.state(size)
                    root.update()
                    ui.responsive_layout.fit()
                    root.update()
                    for section, *_ in SECTIONS:
                        ui.settings_buttons[section].invoke()
                        # Include the changing run metrics in the comparison.
                        root.update()
                        shell = ui.settings_shell
                        width, height = shell.winfo_width(), shell.winfo_height()
                        pixels = ImageTk.getimage(shell._photo).convert("RGB")
                        actual = Image.new("RGB", (width, height), shell.cget("bg"))
                        actual.paste(pixels)
                        painter = theme.Painter(width, height, ui.ui_scale, shell.cget("bg"))
                        shell.paint(painter)
                        expected = painter.finish().convert("RGB")
                        difference = ImageChops.difference(actual, expected)
                        prefix = f"{dpi}_{label}_{section}"
                        if difference.getbbox():
                            actual.save(out/(prefix+"-actual.png"))
                            expected.save(out/(prefix+"-expected.png"))
                            difference.save(out/(prefix+"-difference.png"))
                        check(prefix+"_pixels_match_full_render", difference.getbbox() is None)
                        check(prefix+"_solid_background_is_not_rasterized", pixels.height < height/2)
                    check(f"{dpi}_{label}_covered_scene_is_not_mapped", not ui.backdrop.winfo_ismapped())
                    if dpi == 1.5:
                        ImageGrab.grab(window=root.winfo_id()).save(out/(label+".png"))
                ui._leave_settings()
                root.update()
                check(f"{dpi}_return_restores_scene", ui.backdrop.winfo_ismapped() and ui.backdrop._photo is not None)
                check(f"{dpi}_config_unchanged", config.read_bytes() == original)
            finally:
                ui.closing = True
                for token in root.tk.splitlist(root.tk.call("after", "info")):
                    root.after_cancel(token)
                root.destroy()
    result = dict(count=len(checks), checks=checks, game_started=False)
    (out/"result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
