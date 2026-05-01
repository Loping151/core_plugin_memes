"""调用统计：

- `mm/bq表情统计`：默认本群本日 top10 表情
- `mm/bq表情统计 [日|24小时|本日|周|7天|本周|月|30天|本月|年|本年] [我的|全局|群|本群|按群|按用户] [表情名]`
- 例：`mm表情统计 月 全局`、`mm表情统计 本周 我的`、
       `mm表情统计 本月 按群`、`mm表情统计 本日 按用户 摸`
"""

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..utils.client import MemeClientError, meme_client
from ..utils.database import MemeRecord, parse_period
from ..utils.manager import meme_manager
from ..utils.render import render_top_chart


sv_stats = SV("表情调用统计", priority=4)


_STATS_KEYS = ("表情统计", "表情调用统计", "表情使用统计")


_PERIOD_TOKENS = {
    "日", "今日", "本日", "24小时", "1天",
    "周", "一周", "7天", "本周",
    "月", "30天", "本月", "月度",
    "年", "一年", "365天", "本年", "年度",
}

_SCOPE_GLOBAL = ("全局",)
_SCOPE_MY = ("我的",)
_SCOPE_GROUP_BY = ("按群", "群排行")
_SCOPE_USER_BY = ("按用户", "用户排行")


@sv_stats.on_fullmatch(_STATS_KEYS, block=True)
@sv_stats.on_prefix(_STATS_KEYS, block=True)
async def _stats(bot: Bot, ev: Event):
    raw = ev.text.strip()
    tokens = raw.split() if raw else []

    period = "24小时"
    scope = "group"  # group / global / my / by_group / by_user
    meme_name = None
    consumed: set = set()

    for i, tok in enumerate(tokens):
        if tok in _PERIOD_TOKENS:
            period = tok
            consumed.add(i)
        elif tok in _SCOPE_GLOBAL:
            scope = "global"
            consumed.add(i)
        elif tok in _SCOPE_MY:
            scope = "my"
            consumed.add(i)
        elif tok in _SCOPE_GROUP_BY:
            scope = "by_group"
            consumed.add(i)
        elif tok in _SCOPE_USER_BY:
            scope = "by_user"
            consumed.add(i)

    name_tokens = [t for i, t in enumerate(tokens) if i not in consumed]
    if name_tokens:
        meme_name = " ".join(name_tokens)

    start, end, humanized = parse_period(period)

    meme_key = None
    if meme_name:
        try:
            await meme_manager.init()
        except MemeClientError as e:
            return await bot.send(f"无法连接后端：{e.message}")
        found = await meme_manager.find(meme_name)
        if not found:
            return await bot.send(f"未找到表情 “{meme_name}”")
        meme_key = found[0].key

    if scope == "global":
        scope_text = "全局"
        rows = await MemeRecord.count_by_meme(  # type: ignore[call-arg]
            time_start=start,
            time_stop=end,
            meme_key=None,
            limit=20,
        ) if meme_key is None else []
        if meme_key is not None:
            total = await MemeRecord.total_count(  # type: ignore[call-arg]
                time_start=start, time_stop=end, meme_key=meme_key,
            )
            return await bot.send(
                f"{humanized}全局 “{meme_key}” 共调用 {total} 次"
            )
    elif scope == "my":
        scope_text = "我的"
        if meme_key is not None:
            total = await MemeRecord.total_count(  # type: ignore[call-arg]
                user_id=ev.user_id,
                time_start=start, time_stop=end, meme_key=meme_key,
            )
            return await bot.send(
                f"{humanized}你调用 “{meme_key}” 共 {total} 次"
            )
        rows = await MemeRecord.count_by_meme(  # type: ignore[call-arg]
            user_id=ev.user_id,
            time_start=start, time_stop=end, limit=20,
        )
    elif scope == "by_group":
        scope_text = "按群"
        rows_raw = await MemeRecord.count_by_group(  # type: ignore[call-arg]
            time_start=start, time_stop=end, meme_key=meme_key, limit=20,
        )
        rows = [(g or "（私聊）", c) for g, c in rows_raw]
    elif scope == "by_user":
        scope_text = "按用户"
        rows_raw = await MemeRecord.count_by_user(  # type: ignore[call-arg]
            group_id=ev.group_id, time_start=start, time_stop=end,
            meme_key=meme_key, limit=20,
        )
        rows = [(name or uid, c) for uid, name, c in rows_raw]
    else:
        scope_text = "本群"
        if not ev.group_id:
            scope_text = "私聊"
        if meme_key is not None:
            total = await MemeRecord.total_count(  # type: ignore[call-arg]
                group_id=ev.group_id,
                time_start=start, time_stop=end, meme_key=meme_key,
            )
            return await bot.send(
                f"{humanized}{scope_text} “{meme_key}” 共调用 {total} 次"
            )
        rows = await MemeRecord.count_by_meme(  # type: ignore[call-arg]
            group_id=ev.group_id,
            time_start=start, time_stop=end, limit=20,
        )

    if not rows:
        return await bot.send(f"{humanized}{scope_text}暂无表情调用记录")

    # 把 meme_key 替换成首选可读关键词（kurogames_phoebe_say → 菲比说）
    if scope in ("global", "my", "group", "by_group"):
        # by_group rows 是 (group_label, count)，跳过；其它三类首列才是 meme_key
        if scope != "by_group":
            rows = [
                (_human_label(label), n) for label, n in rows
            ]

    title = f"{humanized}{scope_text}表情调用排行"
    if meme_key is not None:
        title += f"（{_human_label(meme_key)}）"
    try:
        img = render_top_chart(title, rows)
        await bot.send(img)
    except Exception as e:
        logger.warning(f"[core_plugin_memes] 渲染统计图失败：{e}")
        text = "\n".join(f"{i + 1}. {label} - {n}" for i, (label, n) in enumerate(rows))
        await bot.send(f"{title}\n{text}")


def _human_label(meme_key: str) -> str:
    """meme_key → 第一个 keyword，找不到时回退到 key 本身。"""
    try:
        info = meme_client._info_cache.get(meme_key)  # type: ignore[attr-defined]
    except Exception:
        info = None
    if info and info.keywords:
        return info.keywords[0]
    return meme_key
