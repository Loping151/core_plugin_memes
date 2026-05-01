from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..memes_config.config import memes_config
from ..utils.client import MemeClientError
from ..utils.manager import meme_manager
from ..utils.prefix import primary_prefix


sv_search = SV("表情搜索", priority=4)


_SEARCH_KEYS = ("表情搜索", "表情查找", "表情查询")


@sv_search.on_fullmatch(_SEARCH_KEYS, block=True)
@sv_search.on_prefix(_SEARCH_KEYS, block=True)
async def _search(bot: Bot, ev: Event):
    name = ev.text.strip()
    if not name:
        return await bot.send(
            f"请提供要搜索的关键词，例如：{primary_prefix()}表情搜索 摸"
        )

    try:
        await meme_manager.init()
    except MemeClientError as e:
        return await bot.send(f"无法连接表情包后端：{e.message}")

    found = await meme_manager.search(name, include_tags=True)
    if not found:
        return await bot.send(f"未找到与 “{name}” 相关的表情")

    page_size = int(memes_config.get_config("MemeListPageSize").data or 5)
    total_pages = max(1, (len(found) + page_size - 1) // page_size)
    lines = [f"共找到 {len(found)} 个相关表情（共 {total_pages} 页，仅展示第 1 页）："]
    for i, info in enumerate(found[:page_size]):
        keywords = "/".join(info.keywords) if info.keywords else info.key
        tag_str = f"   tags: {'、'.join(info.tags)}" if info.tags else ""
        marker = ""
        if meme_manager.is_disabled_globally(info.key):
            marker = "  [全局禁用]"
        elif not meme_manager.can_use(ev.user_id, info.key):
            marker = "  [禁用]"
        lines.append(f"{i + 1}. {info.key}（{keywords}）{marker}{tag_str}")

    await bot.send("\n".join(lines))
