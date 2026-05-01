"""核心：表情生成与随机表情。

挂载在 SV 上的 catch-all `on_prefix("")` 在 force_prefix 满足时触发：
- 输入：`mm<keyword> [图片|文字|@QQ|自己|--option val ...]`
- 行为：找到表情 → 拉取参数 → 校验数量 → 调用后端 → NSFW 双门控 → 缩放 → 发送
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import Any, Dict, List, Optional, Tuple

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.segment import MessageSegment
from gsuid_core.sv import SV

from ..memes_config.config import memes_config
from ..utils.client import MemeClientError, NormalizedMemeInfo, meme_client
from ..utils.database import MemeRecord
from ..utils.event_helpers import (
    fetch_image_bytes,
    fetch_qq_avatar_bytes,
    get_sender_avatar_bytes,
    get_sender_name,
    parse_meme_invocation,
    resize_to_webp,
    split_text_tokens,
)
from ..utils.gate import passes_gate
from ..utils.manager import meme_manager
from ..utils.nsfw import check_input, check_output
from ..utils.prefix import primary_prefix


# 显式命令的较高优先级；catch-all 设为较低（数字大）
sv_random = SV("随机表情", priority=4)
sv_make = SV("表情包制作核心", priority=20)


_INIT_LOCK = asyncio.Lock()


async def _ensure_init() -> bool:
    """命令路径用：若 manager 还没 ready，启动后台拉取（不阻塞当前命令），返回 False。

    返回值不再 await 阻塞 30 秒——避免一条命令把整条对话卡住。
    """
    if meme_manager.is_ready:
        return True
    if meme_manager.is_loading:
        return False
    # 没人在拉，自己启动一次（不 await，让命令尽快回应）
    if _INIT_LOCK.locked():
        return False
    asyncio.create_task(_kickoff_init(), name="core_plugin_memes:lazy-init")
    return False


async def _kickoff_init() -> None:
    async with _INIT_LOCK:
        if meme_manager.is_ready:
            return
        try:
            await meme_manager.init()
        except MemeClientError as e:
            logger.warning(f"[core_plugin_memes] 初始化失败：{e.message}")
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[core_plugin_memes] 初始化失败：{e}")


# ---- 关键词匹配 ----


# 控制台/常见命令前缀（不应被识别为表情关键词）。
_RESERVED_PREFIXES: Tuple[str, ...] = (
    "表情包制作", "表情列表", "表情详情", "表情示例", "表情搜索", "表情查找",
    "表情查询", "表情统计", "表情调用统计", "表情使用统计",
    "禁用表情", "启用表情", "全局禁用表情", "全局启用表情",
    "黑名单", "禁用列表", "黑名单列表",
    "更新表情", "刷新表情", "重载表情",
    "随机表情",
    "帮助", "插件帮助", "列表", "查看表情", "表情帮助",
    "开启表情包", "关闭表情包", "启用表情包功能", "禁用表情包功能",
    "本群开启表情包", "本群关闭表情包", "表情包开关", "表情包状态",
)


async def _match_keyword(raw_text: str) -> Tuple[Optional[NormalizedMemeInfo], str, str]:
    """从 ev.text 切出 (meme_info, actual_keyword, rest_text)。"""
    text = raw_text.lstrip()
    if not text:
        return None, "", ""

    for reserved in _RESERVED_PREFIXES:
        if text.startswith(reserved):
            return None, "", ""

    # 长前缀匹配：tonoke 名称索引（按首字符桶 + 长度倒序）。
    # 不要求关键词与文字之间有空格——`mm菲比说你好` 也可以命中 `菲比说`。
    key, name, rest = meme_manager.find_by_prefix_key(text)
    if key is None:
        return None, "", ""
    info = await meme_client.get_info(key)
    return info, name, rest


# ---- 头像/图片解析 ----


_AT_INLINE = re.compile(r"@(\d{3,})")


async def _resolve_images(
    ev: Event,
    info: NormalizedMemeInfo,
    rest_text: str,
) -> Tuple[
    List[Tuple[str, bytes]],
    List[str],
    List[Dict[str, Any]],
    List[str],
    Dict[str, Any],
    List[str],
]:
    """拼装 (images_with_name, texts, user_infos, debug_notes, options, at_display_names)。

    at_display_names 用于"meme 需要文字而用户只 at 了人"时作为兜底文字。
    自己 → ev.sender 的 card/nickname；其它 @ → user_id 字串。
    """
    image_bytes: List[Tuple[str, bytes]] = []
    user_infos: List[Dict[str, Any]] = []
    notes: List[str] = []
    at_display_names: List[str] = []

    # 1) 消息内附带的真图片
    for url in ev.image_list or []:
        if not url:
            continue
        data = await fetch_image_bytes(url)
        if data:
            image_bytes.append(("image", data))

    # 2) 解析文字 token，提取 --option / @123 / 自己 / 普通文字
    tokens = split_text_tokens(rest_text)
    texts, at_user_ids, options = parse_meme_invocation(info, tokens)

    # 3) 把 ev.at_list 中的用户也算上
    extra_at = list(ev.at_list or [])
    # 合并到 at_user_ids，但保持出现顺序（at_list 一般在 token 之前出现，置前）
    merged_ats = list(extra_at) + at_user_ids

    # 4) 转换 at→avatar bytes，同时收集 display_name
    for token in merged_ats:
        if token == "__self__" or str(token) == str(ev.user_id):
            data = await get_sender_avatar_bytes(ev)
            name = get_sender_name(ev)
            if data:
                image_bytes.append((name, data))
                user_infos.append({"name": name, "gender": "unknown"})
                at_display_names.append(name)
            else:
                notes.append("无法获取你的头像")
                at_display_names.append(name)
        else:
            # 跨平台获取任意 @用户的 card 需要 IM API；这里用 user_id 兜底
            data = await fetch_qq_avatar_bytes(str(token))
            display = str(token)
            if data:
                image_bytes.append((display, data))
                user_infos.append({"name": display, "gender": "unknown"})
                at_display_names.append(display)
            else:
                notes.append(f"无法获取 @{token} 的头像")
                at_display_names.append(display)

    return image_bytes, texts, user_infos, notes, options, at_display_names


def _format_count(min_n: int, max_n: int) -> str:
    return str(min_n) if min_n == max_n else f"{min_n} ~ {max_n}"


async def _do_make(
    bot: Bot,
    ev: Event,
    info: NormalizedMemeInfo,
    keyword: str,
    rest_text: str,
    *,
    show_info: bool,
):
    image_bytes, texts, user_infos, notes, options, at_display_names = (
        await _resolve_images(ev, info, rest_text)
    )

    # 自动补图：min_images=1 且没图，使用发送者头像
    if (
        info.min_images == 1
        and not image_bytes
        and bool(memes_config.get_config("MemeUseSenderWhenNoImage").data)
    ):
        data = await get_sender_avatar_bytes(ev)
        if data:
            image_bytes.append((get_sender_name(ev), data))
            user_infos.append({"name": get_sender_name(ev), "gender": "unknown"})

    # min_images=2 已指定 1 张，第一张当作发送者头像
    if info.min_images == 2 and len(image_bytes) == 1:
        data = await get_sender_avatar_bytes(ev)
        if data:
            image_bytes.insert(0, (get_sender_name(ev), data))
            user_infos.insert(0, {"name": get_sender_name(ev), "gender": "unknown"})

    # 文字兜底：先用 @ 的人的昵称（自己=card/nickname；其它=user_id），再用默认文字
    if info.min_texts > 0 and len(texts) < info.min_texts and at_display_names:
        for display in at_display_names:
            if len(texts) >= info.min_texts:
                break
            texts.append(display)

    if (
        info.min_texts > 0
        and len(texts) == 0
        and info.default_texts
        and bool(memes_config.get_config("MemeUseDefaultWhenNoText").data)
    ):
        texts = list(info.default_texts)

    # 数量策略
    missing_text = (memes_config.get_config("MemeMissingTextPolicy").data or "ignore").lower()
    missing_image = (memes_config.get_config("MemeMissingImagePolicy").data or "ignore").lower()
    extra_text = (memes_config.get_config("MemeExtraTextPolicy").data or "drop").lower()
    extra_image = (memes_config.get_config("MemeExtraImagePolicy").data or "drop").lower()

    if len(image_bytes) < info.min_images:
        if missing_image == "prompt":
            return await bot.send(
                f"表情 “{info.key}” 需要图片 {_format_count(info.min_images, info.max_images)} 张，"
                f"实际收到 {len(image_bytes)} 张"
            )
        return  # ignore
    if len(image_bytes) > info.max_images:
        if extra_image == "prompt":
            return await bot.send(
                f"表情 “{info.key}” 图片过多（最多 {info.max_images} 张），"
                f"实际收到 {len(image_bytes)} 张"
            )
        image_bytes = image_bytes[: info.max_images]
        user_infos = user_infos[: info.max_images]

    if len(texts) < info.min_texts:
        if missing_text == "prompt":
            return await bot.send(
                f"表情 “{info.key}” 需要文字 {_format_count(info.min_texts, info.max_texts)} 段，"
                f"实际收到 {len(texts)} 段"
            )
        return  # ignore
    if len(texts) > info.max_texts:
        if extra_text == "prompt":
            return await bot.send(
                f"表情 “{info.key}” 文字过多（最多 {info.max_texts} 段），"
                f"实际收到 {len(texts)} 段"
            )
        texts = texts[: info.max_texts]

    # 输入门 NSFW
    is_su = ev.user_pm <= 1
    filtered_images: List[Tuple[str, bytes]] = []
    for name, data in image_bytes:
        ok, score = await check_input(data)
        if not ok and not is_su:
            return await bot.send(
                f"上传图片未通过审核 (drawing+neutral={score:.2%})"
                if score is not None else "上传图片未通过审核"
            )
        filtered_images.append((name, data))

    # 调用后端
    try:
        result = await meme_client.generate(
            info.key,
            filtered_images,
            texts,
            options,
            user_infos=user_infos,
        )
    except MemeClientError as e:
        return await bot.send(f"生成失败：{e.message}")
    except Exception as e:
        logger.exception("[core_plugin_memes] 调用后端失败")
        return await bot.send(f"生成失败：{e}")

    # 输出门 NSFW
    ok, score = await check_output(result)
    if not ok and not is_su:
        return await bot.send(
            f"成品图未通过审核 (drawing+neutral={score:.2%})"
            if score is not None else "成品图未通过审核"
        )

    # 缩放 + 发送
    if bool(memes_config.get_config("MemeResizeImage").data):
        max_size = int(memes_config.get_config("MemeResizeImageSize").data or 800)
        result = resize_to_webp(result, max_size)

    # 记录
    try:
        await MemeRecord.add_record(  # type: ignore[call-arg]
            bot_id=ev.bot_id,
            bot_self_id=ev.bot_self_id,
            user_id=ev.user_id,
            user_name=get_sender_name(ev),
            group_id=ev.group_id,
            user_type=ev.user_type,
            meme_key=info.key,
            meme_keyword=keyword or info.key,
        )
    except Exception as e:
        logger.warning(f"[core_plugin_memes] 写入调用记录失败：{e}")

    # 把 "指令: <prefix><keyword>" + 提示 + 图片合到一条多模态消息里发出
    parts: List[Any] = []
    if show_info:
        primary = primary_prefix()
        keyword_for_show = info.keywords[0] if info.keywords else info.key
        parts.append(f"指令：{primary}{keyword_for_show}\n")
    if notes:
        parts.append("\n".join(notes) + "\n")
    parts.append(MessageSegment.image(result))

    if len(parts) == 1 and isinstance(parts[0], (bytes, bytearray)):
        await bot.send(parts[0])
    else:
        await bot.send(parts)


# ---- catch-all 表情生成 ----


@sv_make.on_prefix("", block=True)
async def _make_meme(bot: Bot, ev: Event):
    raw = (ev.text or "").lstrip()
    if not raw:
        return
    if not passes_gate(ev):
        return
    if not await _ensure_init():
        # 仅当本条消息可能是表情关键词时才提示，避免群里随便说话被骚扰
        if not _looks_like_meme_attempt(raw):
            return
        if meme_manager.is_loading:
            return await bot.send("表情包元数据拉取中，请稍后再试…")
        return await bot.send("表情包后端不可用，请检查 MemeApiUrl 配置")
    info, keyword, rest = await _match_keyword(raw)
    if info is None:
        return  # 静默忽略未识别的关键词
    await _do_make(bot, ev, info, keyword, rest, show_info=False)


def _looks_like_meme_attempt(text: str) -> bool:
    """启发式：表情触发的关键词通常 1~6 个 CJK 字符 + 可选空格/文字。
    避免把 'mm 你好啊朋友们今天天气不错' 这类正常聊天误识为待补提示。"""
    head = text.split(maxsplit=1)[0]
    return 1 <= len(head) <= 8 and head not in _RESERVED_PREFIXES


# ---- 随机表情 ----


@sv_random.on_fullmatch(("随机表情",), block=True)
@sv_random.on_prefix(("随机表情",), block=True)
async def _random_meme(bot: Bot, ev: Event):
    if not passes_gate(ev):
        return
    if not await _ensure_init():
        return await bot.send("表情包后端不可用，请检查 MemeApiUrl 配置")
    rest = ev.text.strip()
    tokens = split_text_tokens(rest)
    # 临时算一下你提供的 image/text 数量，从而筛掉不合适的表情
    explicit_images_n = len(ev.image_list or []) + len(ev.at_list or [])
    has_self = "自己" in tokens
    n_images_hint = explicit_images_n + (1 if has_self else 0)
    n_texts_hint = sum(
        1
        for t in tokens
        if not t.startswith("--") and t != "自己" and not _AT_INLINE.fullmatch(t)
    )

    candidates: List[NormalizedMemeInfo] = []
    for info in await meme_manager.get_all():
        if meme_manager.is_disabled_globally(info.key):
            continue
        if not meme_manager.can_use(ev.user_id, info.key):
            continue
        if info.min_images > n_images_hint + 1:  # 允许补一张头像
            continue
        if info.min_texts > n_texts_hint and not info.default_texts:
            continue
        if info.max_images < max(0, n_images_hint - 0):
            continue
        if info.max_texts < n_texts_hint:
            continue
        candidates.append(info)

    if not candidates:
        return await bot.send("没有符合当前图片/文字数量的可用表情")

    info = random.choice(candidates)
    show_info = bool(memes_config.get_config("MemeRandomShowInfo").data)
    # 用 rest 当作 meme 的 rest，把 keyword 设为 info 的主关键词
    keyword = info.keywords[0] if info.keywords else info.key
    await _do_make(bot, ev, info, keyword, rest, show_info=show_info)
