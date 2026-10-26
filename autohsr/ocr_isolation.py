"""One OCR job in a disposable process; no window or gameplay APIs in child.

Large images and results use private temporary files, avoiding a blocking IPC
send while the OCR runtime is stuck. The coordinator polls a process handle.
"""
from __future__ import annotations

import json
import math
import multiprocessing
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .models import AutomationError, Scene, Token


def _ocr_job(input_path: str, output_path: str, confidence: float):
    try:
        import numpy as np
        from .vision import Vision
        image = np.load(input_path, allow_pickle=False)
        reader = Vision(confidence)
        scene = reader.read(image)
        from .currency_wars_match import supplement_numbers
        scene = supplement_numbers(scene, reader)
        from .currency_wars_standard import supplement_rank
        scene = supplement_rank(scene, reader)
        from .currency_wars_collector import supplement_character_tier
        scene = supplement_character_tier(scene, reader)
        from .currency_wars_match import supplement_shop_fields
        scene = supplement_shop_fields(scene, reader)
        result = dict(status="ok", tokens=[asdict(token) for token in scene.tokens])
    except Exception as error:
        result = dict(status="error", error=f"{type(error).__name__}: {error}"[:2000])
    destination = Path(output_path)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(destination)


def _tokens(result: dict) -> list[Token]:
    if not isinstance(result, dict) or result.get("status") != "ok":
        error = result.get("error", "结果无效") if isinstance(result, dict) else "结果无效"
        raise AutomationError(f"独立 OCR 失败：{error}")
    entries = result.get("tokens")
    if not isinstance(entries, list) or len(entries) > 4096:
        raise AutomationError("独立 OCR 返回的文字列表无效。")
    tokens = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise AutomationError("独立 OCR 返回了无效文字。")
        text, score, box = entry.get("text"), entry.get("score"), entry.get("box")
        if (not isinstance(text, str) or len(text) > 4096 or type(score) not in (int, float)
                or not math.isfinite(score) or not 0 <= score <= 1
                or not isinstance(box, list) or len(box) != 4
                or any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1 for x in box)
                or box[0] >= box[2] or box[1] >= box[3]):
            raise AutomationError("独立 OCR 返回了无效置信度或坐标。")
        tokens.append(Token(text, score, tuple(box)))
    return tokens


class IsolatedVision:
    def __init__(self, confidence=.65, *, checkpoint=lambda: None, inactive=lambda: 0., timeout=30.):
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("OCR 超时必须为正数。")
        self.confidence, self.checkpoint, self.inactive, self.timeout = confidence, checkpoint, inactive, timeout

    def template(self, scene, path, roi=(0, 0, 1, 1), threshold=.88):
        """Pure image matching shares Vision's implementation, never its OCR engine."""
        from .vision import Vision
        self.checkpoint()
        result = Vision.template(self, scene, path, roi, threshold)
        self.checkpoint()
        return result

    def read(self, image, geometry=None) -> Scene:
        import numpy as np
        self.checkpoint()
        captured_at = time.monotonic()
        inactive_before = self.inactive()
        process = None
        started = False
        with tempfile.TemporaryDirectory(prefix="autohsr-ocr-") as folder:
            source, destination = Path(folder) / "frame.npy", Path(folder) / "result.json"
            np.save(source, image, allow_pickle=False)
            try:
                process = multiprocessing.get_context("spawn").Process(
                    target=_ocr_job, args=(str(source), str(destination), self.confidence), name="AutoHSR-OCR", daemon=True)
                process.start()
                started = True
                while True:
                    self.checkpoint()
                    elapsed = time.monotonic() - captured_at - (self.inactive() - inactive_before)
                    if elapsed >= self.timeout:
                        raise AutomationError(f"独立 OCR 超时（{self.timeout:g} 秒），已停止本次识别。")
                    if not process.is_alive():
                        process.join()
                        if process.exitcode != 0 or not destination.is_file():
                            raise AutomationError(f"独立 OCR 进程异常退出（{process.exitcode}），未接受任何识别结果。")
                        if destination.stat().st_size > 2 * 1024 * 1024:
                            raise AutomationError("独立 OCR 结果超过大小限制。")
                        try:
                            tokens = _tokens(json.loads(destination.read_text(encoding="utf-8")))
                        except (ValueError, OSError) as error:
                            raise AutomationError(f"独立 OCR 结果无法读取：{error}") from error
                        self.checkpoint()
                        return Scene(tokens, image, geometry, captured_at)
                    process.join(.05)
            finally:
                if process is not None:
                    if started:
                        if process.is_alive():
                            process.terminate()
                        process.join(1)
                        if process.is_alive():
                            process.kill()
                            process.join(1)
                        if process.is_alive():
                            raise AutomationError("OCR 子进程未能退出；停止本次任务，请核对进程状态。")
                    process.close()
