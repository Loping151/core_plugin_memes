from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..memes_config.config import memes_config
from ..utils.client import MemeClientError
from ..utils.gate import passes_gate
from ..utils.manager import meme_manager
from ..utils.prefix import primary_prefix


sv_search = SV("表情搜索", priority=4)


_SEARCH_KEYS = ("表情搜索", "表情查找", "表情查询")


@sv_search.on_fullmatch(_SEARCH_KEYS, block=True)
@sv_search.on_prefix(
    _SEARCH_KEYS,
    block=True,
    to_ai="""根据关键词 / 标签 / 题材搜索 meme 列表（**给一张总览图**，不是直接生成
表情图）。

**这是你「按话题找表情」的入口**。下面这些场景**必须先调本工具拿候选清单**，
不要凭印象推关键词、也不要直接吐"我不知道有没有"：

- 「找个/有没有 XX 的表情 / XX 的 meme / 关于 XX 的表情」（XX 可以是题材 /
  动作 / 人物 / 情绪，如「明朝 / 猫 / 拍 / 老板 / 加油 / 生气」）
- 「我想要个 XX 题材的表情包 / 帮我找 XX 类的 meme」
- 用户描述要做的表情但说不出具体 keyword 时

调完之后看返回的关键词，再决定下一步：

- 命中了想要的：用对应关键词调 `表情包制作` 生成实际表情图。
- 没命中：告诉用户"暂时没有 XX 主题的表情，可以试试 X / Y（这俩是结果里
  最接近的）"。
- 想找已知/猜出的精确关键词的用法/示例，**用 `表情详情` 工具**而不是本工具。

Args:
    text: 搜索词，必填。可以是名字、标签、人物、题材关键字（如 "猫 / 老板 /
        加油 / 拍 / 明朝"）。空字符串会返回错误提示，所以一定要带 text。
""",
)
async def _search(bot: Bot, ev: Event):
    if not passes_gate(ev):
        return
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
