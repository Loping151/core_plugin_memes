"""把 meme 元信息注册到 AI Core 知识库。

每次 `meme_manager.init` 完成（启动加载 / `更新表情` 触发的强制刷新）后调
`sync_memes_kb_async()`，会用当前 `meme_client._info_cache` 里全部 meme 的元
信息生成 `KnowledgePoint`，覆盖式注册到 `_ENTITIES`，并把变化推到 Qdrant。

同步遵循 `meme_manager.is_disabled_globally` —— 被全局禁用的 meme 不写进 KB，
AI 也就不会建议用户用它们。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from gsuid_core.logger import logger

if TYPE_CHECKING:
    from .client import NormalizedMemeInfo


_PLUGIN_NAME = "core_plugin_memes"


def _format_int_range(lo: int, hi: int, unit: str) -> str:
    if lo == hi:
        return f"{lo}{unit}" if lo > 0 else f"无{unit}"
    return f"{lo}~{hi}{unit}"


def _build_meme_kp(info: "NormalizedMemeInfo") -> dict:
    from gsuid_core.ai_core.models import KnowledgePoint

    keywords = [k for k in info.keywords if k]
    shortcuts = [sc.keyword for sc in info.shortcuts if sc.keyword]
    tags = [t for t in info.tags if t]

    images_desc = _format_int_range(info.min_images, info.max_images, " 张图")
    texts_desc = _format_int_range(info.min_texts, info.max_texts, " 段文字")

    parts: List[str] = [f"# 表情 {info.key}"]
    if keywords:
        parts.append("关键词：" + " / ".join(keywords))
    if shortcuts:
        parts.append("快捷指令：" + " / ".join(shortcuts))
    if tags:
        parts.append("标签：" + " / ".join(tags))
    parts.append(f"图片需求：{images_desc}")
    parts.append(f"文字需求：{texts_desc}")
    if info.default_texts:
        parts.append("默认文字：" + " / ".join(info.default_texts))
    if info.options:
        opt_lines: List[str] = []
        for opt in info.options:
            seg = f"--{opt.name}"
            if opt.long_aliases:
                seg += " (" + ", ".join(f"--{a}" for a in opt.long_aliases) + ")"
            if opt.choices:
                seg += " 取值: " + " / ".join(opt.choices)
            if opt.description:
                seg += f" — {opt.description}"
            opt_lines.append(seg)
        parts.append("可选参数：\n  " + "\n  ".join(opt_lines))

    parts.append(
        "用法：通过表情包指令前缀（默认 `mm` 或 `bq`）加上关键词触发，例如"
        f" `mm{keywords[0]}` 之后按需附带图片 / 文字 / `@用户` / `自己`。"
    )

    content = "\n".join(parts)
    title = f"表情：{keywords[0] if keywords else info.key}"

    # tag 去重，把所有关键词 / 快捷指令 / 标签都丢进去方便 RAG 检索
    kp_tags = list(dict.fromkeys([info.key] + keywords + shortcuts + tags + ["表情包", "meme"]))

    return KnowledgePoint(
        id=f"meme_{info.key}",
        plugin=_PLUGIN_NAME,
        type="表情",
        category="表情包",
        title=title,
        content=content,
        tags=kp_tags,
    )


def register_memes_to_kb() -> int:
    """把当前 `meme_client._info_cache` 里启用中的 meme 同步进 _ENTITIES。

    Returns:
        实际注册条数（跳过的全局禁用项不计）。
    """
    try:
        from gsuid_core.ai_core.register import _ENTITIES, ai_entity
    except Exception:
        logger.debug("[core_plugin_memes][AI-KB] AI Core register 不可用，跳过")
        return 0

    from .client import meme_client
    from .manager import meme_manager

    # 1) 清掉本插件之前注册的所有条目，避免重复或残留过期项
    _ENTITIES[:] = [e for e in _ENTITIES if e.get("plugin") != _PLUGIN_NAME]

    # 2) 用当前 info_cache 重建
    cache = getattr(meme_client, "_info_cache", {})
    count = 0
    for key, info in cache.items():
        if meme_manager.is_disabled_globally(key):
            continue
        try:
            kp = _build_meme_kp(info)
        except Exception:
            logger.exception(f"[core_plugin_memes][AI-KB] 构造 KP 失败: {key}")
            continue
        ai_entity(kp)
        count += 1

    logger.info(f"🧠 [core_plugin_memes][AI-KB] 已注册 {count} 个表情到知识库")
    return count


async def sync_memes_kb_async() -> None:
    """注册 + 推向量库。AI 未启用时为 no-op。"""
    try:
        from gsuid_core.ai_core.configs.ai_config import ai_config

        if not ai_config.get_config("enable").data:
            return
    except Exception:
        return

    register_memes_to_kb()

    try:
        from gsuid_core.ai_core.rag.knowledge import sync_knowledge

        await sync_knowledge()
    except Exception:
        logger.exception("[core_plugin_memes][AI-KB] sync_knowledge 失败")
