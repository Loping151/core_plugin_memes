"""NSFW 双门控（基于 nsfwpy；未安装则全部放行）。

阈值含义：drawing+neutral 的总占比。低于阈值视为不合适。
- 输入门：每张待上传图片单独检测；任一不通过则丢弃
- 输出门：成品图检测；不通过则不发送
"""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Optional, Tuple

from gsuid_core.logger import logger

from ..memes_config.config import memes_config


_detector_lock = asyncio.Lock()
_detector = None  # type: ignore[assignment]
_detector_init = False


async def _get_detector():
    global _detector, _detector_init
    if _detector_init:
        return _detector
    async with _detector_lock:
        if _detector_init:
            return _detector
        _detector_init = True
        try:
            from nsfwpy import NSFW  # type: ignore
        except ImportError:
            logger.info("[core_plugin_memes] 未安装 nsfwpy，跳过 NSFW 检测")
            _detector = None
            return None
        model = (memes_config.get_config("MemeNsfwModel").data or "").strip() or None
        try:
            _detector = NSFW(model_name=model) if model else NSFW()
        except TypeError:
            try:
                _detector = NSFW(model) if model else NSFW()
            except Exception as e:
                logger.warning(f"[core_plugin_memes] NSFW 初始化失败：{e}")
                _detector = None
        except Exception as e:
            logger.warning(f"[core_plugin_memes] NSFW 初始化失败：{e}")
            _detector = None
        return _detector


def _enabled() -> bool:
    return bool(memes_config.get_config("MemeNsfwEnabled").data)


def _input_threshold() -> float:
    v = memes_config.get_config("MemeNsfwInputThreshold").data
    try:
        return float(v) / 100.0
    except Exception:
        return 0.4


def _output_threshold() -> float:
    v = memes_config.get_config("MemeNsfwOutputThreshold").data
    try:
        return float(v) / 100.0
    except Exception:
        return 0.5


async def _score(data: bytes) -> Optional[float]:
    detector = await _get_detector()
    if detector is None:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None

    def _run() -> Optional[float]:
        try:
            img = Image.open(BytesIO(data))
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            for fn in ("predict_pil_image", "predict_image", "predict_pil"):
                if hasattr(detector, fn):
                    result = getattr(detector, fn)(img)
                    break
            else:
                if hasattr(detector, "predict"):
                    result = detector.predict(img)
                else:
                    return None
            drawing = float(result.get("drawing", 0.0) or 0.0)
            neutral = float(result.get("neutral", 0.0) or 0.0)
            return drawing + neutral
        except Exception as e:
            logger.warning(f"[core_plugin_memes] NSFW 推理失败：{e}")
            return None

    return await asyncio.to_thread(_run)


async def check_input(data: bytes) -> Tuple[bool, Optional[float]]:
    """检查上传图。返回 (是否放行, 分数)；未启用或检测失败时放行。"""
    if not _enabled():
        return True, None
    score = await _score(data)
    if score is None:
        return True, None
    return score >= _input_threshold(), score


async def check_output(data: bytes) -> Tuple[bool, Optional[float]]:
    if not _enabled():
        return True, None
    score = await _score(data)
    if score is None:
        return True, None
    return score >= _output_threshold(), score
