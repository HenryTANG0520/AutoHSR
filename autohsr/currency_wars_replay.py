"""Versioned local evidence, immutable replay, and no game imports or actions."""
from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .models import AutomationError, Scene
from .ocr_isolation import IsolatedVision, _tokens

STAGES = ("unclassified", "entry", "guide_before", "guide_after", "tutorial", "economy", "feedback", "recovery", "ending")
FIELDS = {"schema_version", "origin", "image", "sha256", "recorded_at", "dimensions", "game_version", "language", "stage", "tokens", "expected_mode_text_visible"}


def save_sample(scene: Scene, screenshot: Path, *, origin="unverified_capture", stage="unclassified") -> Path:
    screenshot = Path(screenshot)
    height, width = scene.image.shape[:2]
    payload = dict(schema_version=1, origin=origin, image=screenshot.name,
                   sha256=hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                   recorded_at=datetime.now(timezone.utc).isoformat(), dimensions=[width, height],
                   game_version="unverified", language="unverified", stage=stage,
                   tokens=[asdict(token) for token in scene.tokens])
    destination = screenshot.with_suffix(".sample.json")
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(destination)
    return destination


def load_sample(path: Path) -> tuple[dict, Scene]:
    from PIL import Image
    import numpy as np
    path = Path(path).resolve()
    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("样本清单超过 2 MiB")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) - FIELDS or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("样本版本或字段不支持")
        if data.get("origin") not in ("synthetic", "unverified_capture") or data.get("stage") not in STAGES:
            raise ValueError("样本来源或阶段无效")
        for field in ("recorded_at", "game_version", "language"):
            if not isinstance(data.get(field), str) or not data[field] or len(data[field]) > 200:
                raise ValueError(f"{field} 未记录")
        stamp = datetime.fromisoformat(data["recorded_at"])
        if stamp.tzinfo is None:
            raise ValueError("记录时间缺少时区")
        if "expected_mode_text_visible" in data and type(data["expected_mode_text_visible"]) is not bool:
            raise ValueError("期望值必须为布尔值")
        if not isinstance(data.get("image"), str):
            raise ValueError("缺少图像文件")
        relative = Path(data["image"])
        image_path = (path.parent / relative).resolve()
        if relative.is_absolute() or not image_path.is_relative_to(path.parent):
            raise ValueError("图像路径必须位于样本目录内")
        if image_path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("图像文件超过 32 MiB")
        digest = data.get("sha256")
        image_bytes = image_path.read_bytes()
        if len(image_bytes) > 32 * 1024 * 1024:
            raise ValueError("图像文件超过 32 MiB")
        if not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest) or hashlib.sha256(image_bytes).hexdigest() != digest:
            raise ValueError("图像 SHA256 不匹配")
        dimensions = data.get("dimensions")
        if not isinstance(dimensions, list) or len(dimensions) != 2 or any(type(x) is not int or x <= 0 for x in dimensions):
            raise ValueError("尺寸记录无效")
        with Image.open(io.BytesIO(image_bytes)) as bitmap:
            if bitmap.format != "PNG" or list(bitmap.size) != dimensions or bitmap.width * bitmap.height > 16_777_216:
                raise ValueError("PNG 格式、像素尺寸或尺寸记录无效")
            image = np.asarray(bitmap.convert("RGB"))[:, :, ::-1].copy()
        tokens = _tokens(dict(status="ok", tokens=data.get("tokens")))
        # Recorded monotonic timestamps are never accepted as current live frames.
        return data, Scene(tokens, image=image, captured_at=0)
    except (ValueError, OSError) as error:
        raise AutomationError(f"货币战争样本无效：{error}") from error


def replay_sample(path: Path, *, reocr=False) -> dict:
    from .currency_wars import decide, observe
    data, scene = load_sample(path)
    recorded = observe(scene, .65)
    ocr_scene = IsolatedVision().read(scene.image) if reocr else scene
    observation = observe(ocr_scene, .65) if reocr else recorded
    decision = decide(observation)
    from .currency_wars_match import read_match
    match = read_match(ocr_scene, .65)
    expected = data.get("expected_mode_text_visible")
    return dict(operation="currency_wars_replay", status="replayed", origin=data["origin"], stage=data["stage"],
                sample=str(Path(path).resolve()), reocr=bool(reocr), game_accessed=False,
                recorded_mode_text_visible=recorded.mode_text_visible,
                observation=asdict(observation), decision=asdict(decision),
                match=asdict(match) if match else None,
                expectation_passed=None if expected is None else expected == observation.mode_text_visible)
