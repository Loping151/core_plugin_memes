from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..utils.client import meme_client, MemeClientError
from ..utils.gate import passes_gate
from ..utils.manager import meme_manager
from ..utils.prefix import join_prefixes
from ..utils.render import render_meme_list


sv_help = SV("表情包列表", priority=4)


_HELP_KEYS = ("表情包制作", "列表", "表情列表", "表情帮助")


@sv_help.on_fullmatch(_HELP_KEYS, block=True)
async def _show_help(bot: Bot, ev: Event):
    if not passes_gate(ev):
        return
    try:
        await meme_manager.init()
    except MemeClientError as e:
        return await bot.send(f"无法连接表情包后端：{e.message}")
    except Exception as e:
        logger.exception("[core_plugin_memes] 初始化失败")
        return await bot.send(f"加载表情列表失败：{e}")

    memes = await meme_manager.get_all()
    items = []
    for info in memes:
        keywords = "、".join(info.keywords) if info.keywords else info.key
        ud = not meme_manager.can_use(ev.user_id, info.key)
        gd = meme_manager.is_disabled_globally(info.key)
        # 用户级 ud 的判定：仅在非全局禁用时记禁用标记，否则只显示全局
        if gd:
            ud = False
        items.append((info.key, keywords, ud, gd))

    backend = "?"
    try:
        backend = await meme_client.get_backend()
    except Exception:
        pass

    title = "表情包列表"
    prefix_str = join_prefixes("/")
    subtitle = (
        f"共 {len(items)} 个表情 ｜ 后端：{backend.upper()} ｜ "
        f"用法：{prefix_str}关键词 + 图片/文字/@QQ号/自己"
    )
    img = render_meme_list(items, title=title, subtitle=subtitle)
    await bot.send(img)
