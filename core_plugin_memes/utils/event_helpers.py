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

from ..memes_config.config import memes_config
from .client import NormalizedMemeInfo, NormalizedOption


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
            logger.warning(f"[memes·事件] 下载图片失败 {url_or_b64}: {e}")
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
            logger.warning(f"[memes·事件] 读取本地图片失败 {path}: {e}")
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


_ESCAPE_MAP = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
_ESCAPE_PATTERN = re.compile(r"\\(.)")


def unescape(text: str) -> str:
    r"""\n \t \r \\ 转真实字符，其余 \x 原样保留。"""
    return _ESCAPE_PATTERN.sub(
        lambda m: _ESCAPE_MAP.get(m.group(1), m.group(0)), text
    )


def unescape_enabled() -> bool:
    try:
        return bool(memes_config.get_config("MemeUnescapeText").data)
    except Exception:
        return True


def split_text_tokens(text: str) -> List[str]:
    """命令风格分词：空格分词，引号内保留空格，反斜杠不参与分词。"""
    text = text.strip()
    if not text:
        return []
    try:
        lex = shlex.shlex(text, posix=True)
        lex.whitespace_split = True
        lex.commenters = ""
        lex.escape = ""  # 反斜杠交给 unescape 处理，分词阶段原样保留
        tokens = list(lex)
    except ValueError:
        tokens = text.split()
    return [t for t in tokens if t]


def single_text_enabled() -> bool:
    try:
        return bool(memes_config.get_config("MemeSingleTextWhole").data)
    except Exception:
        return True


def _build_options_index(info: NormalizedMemeInfo) -> Dict[str, NormalizedOption]:
    options_index: Dict[str, NormalizedOption] = {}
    for opt in info.options:
        for alias in [opt.name] + opt.short_aliases + opt.long_aliases:
            if not alias:
                continue
            stripped = alias.lstrip("-")
            if not stripped:
                continue
            cands = {alias, stripped, f"--{stripped}"}
            if len(stripped) == 1:
                cands.add(f"-{stripped}")
            for cand in cands:
                options_index.setdefault(cand, opt)
                options_index.setdefault(cand.lower(), opt)
    return options_index


def parse_meme_invocation(
    info: NormalizedMemeInfo, tokens: List[str]
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """从 token 列表里抽取 (texts, at_user_ids, options)。

    - 形如 `-x` / `--xxx` / `--xxx=v` 的 token 被解析为 option
    - 形如 `@123` 的 token 被记为 at_user_id（用对应 QQ 头像）
    - `自己` 被记为占位 `__self__`
    - 其他文字进入 texts
    """
    options_index = _build_options_index(info)

    texts: List[str] = []
    at_user_ids: List[str] = []
    options: Dict[str, Any] = {}

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # --opt=value
        if tok.startswith("--") and "=" in tok:
            head, _, val = tok.partition("=")
            opt = options_index.get(head)
            if opt is not None:
                options[opt.name] = (
                    _coerce(val, opt.type) if opt.takes_value else opt.const_value
                )
                i += 1
                continue

        # --opt [value?]
        opt = options_index.get(tok)
        if opt is not None:
            if not opt.takes_value or opt.type == "boolean":
                options[opt.name] = (
                    opt.const_value if opt.const_value is not None else True
                )
                i += 1
                continue
            if i + 1 < len(tokens):
                options[opt.name] = _coerce(tokens[i + 1], opt.type)
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

    if unescape_enabled():
        texts = [unescape(t) for t in texts]

    return texts, at_user_ids, options


# 引号段整体算一个词，其余按空白切
_WORD_PATTERN = re.compile(r"\"[^\"]*\"|'[^']*'|\S+")


def _strip_wrapping_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        inner = text[1:-1]
        if text[0] not in inner:
            return inner
    return text


def parse_single_text_invocation(
    info: NormalizedMemeInfo, raw_text: str
) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """只要 1 段文字的表情：剥掉 option/@ 后，剩下的原文整段作为一段文字。"""
    options_index = _build_options_index(info)
    at_user_ids: List[str] = []
    options: Dict[str, Any] = {}
    kept: List[Tuple[int, int]] = []
    consumed: List[Tuple[int, int]] = []

    words = [
        (m.start(), m.end(), m.group()) for m in _WORD_PATTERN.finditer(raw_text)
    ]
    i = 0
    while i < len(words):
        start, end, word = words[i]

        if word.startswith("--") and "=" in word:
            head, _, val = word.partition("=")
            opt = options_index.get(head)
            if opt is not None:
                options[opt.name] = (
                    _coerce(_strip_wrapping_quotes(val), opt.type)
                    if opt.takes_value
                    else opt.const_value
                )
                consumed.append((start, end))
                i += 1
                continue

        opt = options_index.get(word) or options_index.get(word.lower())
        if opt is not None:
            if not opt.takes_value or opt.type == "boolean":
                options[opt.name] = (
                    opt.const_value if opt.const_value is not None else True
                )
                consumed.append((start, end))
                i += 1
                continue
            if i + 1 < len(words):
                options[opt.name] = _coerce(
                    _strip_wrapping_quotes(words[i + 1][2]), opt.type
                )
                consumed.append((start, words[i + 1][1]))
                i += 2
                continue
            consumed.append((start, end))
            i += 1
            continue

        if _AT_PATTERN.fullmatch(word):
            at_user_ids.append(word[1:])
            consumed.append((start, end))
            i += 1
            continue

        if word == "自己":
            at_user_ids.append("__self__")
            consumed.append((start, end))
            i += 1
            continue

        kept.append((start, end))
        i += 1

    texts: List[str] = []
    if kept:
        first, last = kept[0][0], kept[-1][1]
        # option/@ 夹在文字中间时不能直接切原文，退化成空格拼接
        if any(first <= c[0] and c[1] <= last for c in consumed):
            text = " ".join(raw_text[s:e] for s, e in kept)
        else:
            text = raw_text[first:last]
        text = _strip_wrapping_quotes(text.strip())
        if unescape_enabled():
            text = unescape(text)
        if text:
            texts.append(text)

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
    return unescape(val) if unescape_enabled() else val


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
        logger.warning(f"[memes·事件] 缩放图片失败：{e}")
        return data
