"""从 gsuid Event 抽取消息段、获取头像、解析参数。"""

from __future__ import annotations

import re
import shlex
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PIL import Image

from gsuid_core.logger import logger
from gsuid_core.models import Event

from .client import NormalizedMemeInfo


# ---- 图像 ----


async def fetch_image_bytes(url_or_b64: str) -> Optional[bytes]:
    if not url_or_b64:
        return None
    if url_or_b64.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url_or_b64)
                resp.raise_for_status()
                return resp.content
        except Exception as e:
            logger.warning(f"[core_plugin_memes] 下载图片失败 {url_or_b64}: {e}")
            return None
    if url_or_b64.startswith("base64://"):
        import base64

        return base64.b64decode(url_or_b64[len("base64://") :])
    if url_or_b64.startswith("file://"):
        path = url_or_b64[len("file://") :]
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"[core_plugin_memes] 读取本地图片失败 {path}: {e}")
            return None
    return None


async def fetch_qq_avatar_bytes(qid: str, size: int = 640) -> Optional[bytes]:
    url = f"http://q1.qlogo.cn/g?b=qq&nk={qid}&s={size}"
    return await fetch_image_bytes(url)


async def get_sender_avatar_bytes(ev: Event) -> Optional[bytes]:
    """尽量获取发送者头像字节。"""
    if ev.sender and isinstance(ev.sender, dict):
        avatar_url = ev.sender.get("avatar")
        if isinstance(avatar_url, str) and avatar_url.startswith(("http", "https")):
            data = await fetch_image_bytes(avatar_url)
            if data:
                return data
    if ev.bot_id == "onebot" and ev.user_id:
        return await fetch_qq_avatar_bytes(ev.user_id)
    return None


def get_sender_name(ev: Event) -> str:
    if ev.sender and isinstance(ev.sender, dict):
        for key in ("card", "nickname", "name"):
            v = ev.sender.get(key)
            if v:
                return str(v)
    return ev.user_id or "未知"


# ---- 文本/参数解析 ----


# 用一个非歧义的占位符替换数字风格的 @123，避免在带空格的命令里被识别成 token
_AT_PATTERN = re.compile(r"@(\d{3,})")


def split_text_tokens(text: str) -> List[str]:
    """命令风格分词，保留 quoted segment。"""
    text = text.strip()
    if not text:
        return []
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = text.split()
    return [t for t in tokens if t]


def parse_meme_invocation(
    info: NormalizedMemeInfo, tokens: List[str]
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """从 token 列表里抽取 (texts, at_user_ids, options)。

    - 形如 `--xxx` / `--xxx=v` 的 token 被解析为 option
    - 形如 `@123` 的 token 被记为 at_user_id（用对应 QQ 头像）
    - `自己` 被记为占位 `__self__`
    - 其他文字进入 texts
    """
    options_index: Dict[str, Tuple[str, str]] = {}
    # name → (canonical_name, type)
    for opt in info.options:
        canonical = opt.name
        opt_type = opt.type
        for alias in [opt.name] + opt.short_aliases + opt.long_aliases:
            if not alias:
                continue
            for cand in {alias, alias.lstrip("-"), f"--{alias.lstrip('-')}"}:
                options_index[cand] = (canonical, opt_type)
                options_index[cand.lower()] = (canonical, opt_type)

    texts: List[str] = []
    at_user_ids: List[str] = []
    options: Dict[str, Any] = {}

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # --opt=value
        if tok.startswith("--") and "=" in tok:
            head, _, val = tok.partition("=")
            if head in options_index:
                name, opt_type = options_index[head]
                options[name] = _coerce(val, opt_type)
                i += 1
                continue

        # --opt [value?]
        if tok in options_index:
            name, opt_type = options_index[tok]
            if opt_type == "boolean":
                options[name] = True
                i += 1
                continue
            if i + 1 < len(tokens):
                options[name] = _coerce(tokens[i + 1], opt_type)
                i += 2
                continue
            i += 1
            continue

        # @123 → at
        m = _AT_PATTERN.fullmatch(tok)
        if m:
            at_user_ids.append(m.group(1))
            i += 1
            continue

        if tok == "自己":
            at_user_ids.append("__self__")
            i += 1
            continue

        texts.append(tok)
        i += 1

    return texts, at_user_ids, options


def _coerce(val: str, opt_type: str) -> Any:
    if opt_type == "boolean":
        return val.lower() not in ("false", "0", "no", "off", "")
    if opt_type == "integer":
        try:
            return int(val)
        except ValueError:
            return val
    if opt_type == "float":
        try:
            return float(val)
        except ValueError:
            return val
    return val


# ---- 缩放 / 转 webp ----


def resize_to_webp(data: bytes, max_size: int) -> bytes:
    try:
        img = Image.open(BytesIO(data))
        img.load()
        if img.format == "GIF":
            return data
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
            img = img.resize(new_size, Image.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        buf = BytesIO()
        img.save(buf, format="WEBP", quality=92)
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"[core_plugin_memes] 缩放图片失败：{e}")
        return data
