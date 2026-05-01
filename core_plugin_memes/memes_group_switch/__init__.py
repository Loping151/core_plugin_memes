"""按群开/关整个表情包功能（SV pm=3，所有群成员可设置）。

不走 utils.gate 闸门：关闭后这条命令仍要能开回来。
"""

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..utils.manager import meme_manager
from ..utils.prefix import primary_prefix


sv_group_switch = SV("表情包按群开关", priority=4, pm=3)


_ENABLE_KEYS = ("开启表情包", "启用表情包功能", "本群开启表情包")
_DISABLE_KEYS = ("关闭表情包", "禁用表情包功能", "本群关闭表情包")
_STATUS_KEYS = ("表情包开关", "表情包状态")


@sv_group_switch.on_fullmatch(_ENABLE_KEYS, block=True)
async def _enable(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("仅限群聊使用")
    changed = meme_manager.enable_group(ev.group_id)
    if changed:
        await bot.send("已为本群开启表情包功能 ✅")
    else:
        await bot.send("本群本来就是开启状态")


@sv_group_switch.on_fullmatch(_DISABLE_KEYS, block=True)
async def _disable(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("仅限群聊使用")
    changed = meme_manager.disable_group(ev.group_id)
    p = primary_prefix()
    if changed:
        await bot.send(
            f"已为本群关闭表情包功能 ⛔  发送 `{p}开启表情包` 可恢复"
        )
    else:
        await bot.send("本群本来就是关闭状态")


@sv_group_switch.on_fullmatch(_STATUS_KEYS, block=True)
async def _status(bot: Bot, ev: Event):
    if not ev.group_id:
        return await bot.send("仅限群聊使用")
    enabled = meme_manager.is_group_enabled(ev.group_id)
    await bot.send(
        f"本群表情包功能：{'开启 ✅' if enabled else '关闭 ⛔'}"
    )
