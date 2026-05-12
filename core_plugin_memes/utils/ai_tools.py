"""memes 插件直通 AI 工具（category="self"，主 agent 每次必定加载）。

by_trigger 类工具走相似度阈值动态加载，当用户 query 不太"像 meme"时 memes 的
工具不会进入主 agent 的 tool list，导致 AI 直接放弃调用。这里提供 3 个 self
类直通 wrapper：

- `search_meme_kb(query)` — 题材/关键字 RAG 检索 meme KB
- `meme_make(keyword, text)` — 精确关键词生成 meme（复用 memes_make 内部逻辑）
- `meme_random(text)` — 随机 meme（复用 memes_make 内部逻辑）

这些工具与 by_trigger 版本并存，AI 优先用 self 版本不受查询相似度影响。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Optional

from pydantic_ai import RunContext

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.ai_core.models import ToolContext
from gsuid_core.ai_core.register import ai_tools


@ai_tools(category="self")
async def search_meme_kb(
    ctx: RunContext[ToolContext],
    query: str,
    limit: int = 8,
    score_threshold: float = 0.3,
) -> str:
    """按题材 / 关键字 / 标签 RAG 搜索 meme 知识库，拿候选关键词。

    用户讲题材（"明朝 / 老板 / 加油 / 拍 / 猫"）想要 meme 但说不出确切
    keyword 时，**必须先用本工具**拿候选。返回里每条带 meme 的 title（含
    主 keyword）+ tags。选定后再调 `meme_make(keyword=..., text=...)` 实际生成。

    Args:
        query: 题材关键字，必填。例 "明朝"、"加油"、"老板生气"、"开心"。
        limit: 最多返回多少候选，默认 8。
        score_threshold: 相似度阈值，0.3 比常规 0.45 宽松，便于发现弱相关项。

    Returns:
        命中候选列表的 str（含 title / tags / content_preview / _score）；
        无结果时返回提示文本。
    """
    logger.info(
        f"🛠️ [search_meme_kb] query={query!r} limit={limit} threshold={score_threshold}"
    )
    try:
        from gsuid_core.ai_core.rag import query_knowledge
    except ImportError:
        return "AI 知识库模块不可用"

    try:
        points = await query_knowledge(
            query=query,
            limit=limit,
            plugin_filter=["core_plugin_memes"],
        )
    except Exception as e:
        logger.exception("[search_meme_kb] query_knowledge 失败")
        return f"meme KB 检索失败: {e}"

    items = []
    for p in points:
        if p.payload is None:
            continue
        if p.score < score_threshold:
            continue
        items.append({
            "title": p.payload.get("title", ""),
            "tags": p.payload.get("tags", []),
            "content_preview": (p.payload.get("content") or "")[:240],
            "_score": round(p.score, 4),
        })

    logger.info(
        f"🛠️ [search_meme_kb] 命中 {len(items)} 条（raw {len(points)} 条）"
    )
    if not items:
        return (
            f"meme KB 里没有匹配 {query!r} 的表情。可换更口语化的题材词再试，"
            "或告知用户暂无相关表情。"
        )
    return str(items)


@ai_tools(category="self")
async def meme_make(
    ctx: RunContext[ToolContext],
    keyword: str,
    text: str = "",
) -> str:
    """用**精确 meme 关键词**生成表情图并发给当前对话用户。

    若只有题材而没有具体关键词，先调 `search_meme_kb(query=...)` 拿候选。
    使用本工具时 keyword 必须是 meme 的 name（如 "拍 / 摸 / 点赞 / 举牌"）。

    Args:
        keyword: 表情关键词，必填。例 "拍"、"摸"、"点赞"。
        text: 附加 token，按空格拼接到 keyword 后面。例 "你好 自己" / "@123456" /
            "牛逼"。可空。

    Returns:
        生成状态文本。meme 图片由本工具直接发送给当前对话用户。
    """
    logger.info(f"🛠️ [meme_make] keyword={keyword!r} text={text!r}")
    if not keyword:
        return "请提供 keyword（meme 关键词）"

    tool_ctx = ctx.deps
    bot: Optional[Bot] = tool_ctx.bot
    base_ev = tool_ctx.ev
    if bot is None or base_ev is None:
        return "无法获取 bot / event 上下文"

    from ..memes_make import _make_meme as _handler

    payload = (keyword + " " + (text or "")).strip()
    ev = deepcopy(base_ev)
    ev.text = payload
    ev.raw_text = payload
    try:
        await _handler(bot, ev)
    except Exception as e:
        logger.exception("[meme_make] _make_meme 失败")
        return f"meme 生成失败: {e}"
    return f"已尝试生成 meme: keyword={keyword!r}，图片已直接发给用户。"


@ai_tools(category="self")
async def meme_random(
    ctx: RunContext[ToolContext],
    text: str = "",
) -> str:
    """随机抽一张当前可用 meme 发给用户。

    Args:
        text: 可选 token（用法同 meme_make 的 text 参数），帮助系统按图片/文字
            参数数量筛掉不匹配的候选。

    Returns:
        生成状态文本。图片由本工具直接发给用户。
    """
    logger.info(f"🛠️ [meme_random] text={text!r}")
    tool_ctx = ctx.deps
    bot: Optional[Bot] = tool_ctx.bot
    base_ev = tool_ctx.ev
    if bot is None or base_ev is None:
        return "无法获取 bot / event 上下文"

    from ..memes_make import _random_meme as _handler

    payload = (text or "").strip()
    ev = deepcopy(base_ev)
    ev.text = payload
    ev.raw_text = payload
    try:
        await _handler(bot, ev)
    except Exception as e:
        logger.exception("[meme_random] _random_meme 失败")
        return f"随机 meme 失败: {e}"
    return "已抽取一张随机 meme，图片已发给用户。"
