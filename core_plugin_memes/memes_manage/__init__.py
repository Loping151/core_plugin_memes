from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..utils.client import MemeClientError
from ..utils.manager import MemeMode, meme_manager
from ..utils.prefix import primary_prefix


# 用户级别：每个 user_id 自己管理自己的可用表情，不限权限
sv_manage_user = SV("表情禁启用", priority=4)
# 全局：仅 master/superuser
sv_manage_global = SV("表情全局管理", priority=4, pm=1)


async def _resolve_one(bot: Bot, name: str):
    try:
        await meme_manager.init()
    except MemeClientError as e:
        await bot.send(f"无法连接表情包后端：{e.message}")
        return None
    found = await meme_manager.find(name)
    if not found:
        searched = await meme_manager.search(name, include_tags=False, limit=5)
        if searched:
            tip = "\n".join(
                f"* {m.key}（{'/'.join(m.keywords) if m.keywords else m.key}）"
                for m in searched
            )
            await bot.send(f"未找到表情 “{name}”，相近表情：\n{tip}")
        else:
            await bot.send(f"未找到表情 “{name}”")
        return None
    return found[0]


@sv_manage_user.on_prefix(("禁用表情",), block=True)
async def _disable(bot: Bot, ev: Event):
    name = ev.text.strip()
    if not name:
        return await bot.send(
            f"请提供要禁用的表情名，例如：{primary_prefix()}禁用表情 摸"
        )
    info = await _resolve_one(bot, name)
    if not info:
        return
    if meme_manager.is_disabled_globally(info.key):
        return await bot.send(f"表情 {info.key} 已被全局禁用")
    ok = meme_manager.block_for_user(ev.user_id, info.key)
    if ok:
        await bot.send(f"表情 {info.key} 已对你禁用")
    else:
        await bot.send(f"表情 {info.key} 之前已禁用过了")


@sv_manage_user.on_prefix(("启用表情",), block=True)
async def _enable(bot: Bot, ev: Event):
    name = ev.text.strip()
    if not name:
        return await bot.send(
            f"请提供要启用的表情名，例如：{primary_prefix()}启用表情 摸"
        )
    info = await _resolve_one(bot, name)
    if not info:
        return
    if meme_manager.is_disabled_globally(info.key):
        return await bot.send(
            f"表情 {info.key} 处于全局禁用，需要 master/SU 切换为黑名单模式"
        )
    meme_manager.unblock_for_user(ev.user_id, info.key)
    await bot.send(f"表情 {info.key} 已启用")


@sv_manage_global.on_prefix(("全局禁用表情",), block=True)
async def _global_disable(bot: Bot, ev: Event):
    if ev.user_pm > 1:
        return await bot.send("仅 master/superuser 可设置全局禁用")
    name = ev.text.strip()
    if not name:
        return await bot.send("请提供要全局禁用的表情名")
    info = await _resolve_one(bot, name)
    if not info:
        return
    meme_manager.set_global_mode(info.key, MemeMode.WHITE)
    await bot.send(f"表情 {info.key} 已设为全局禁用（白名单模式）")


@sv_manage_global.on_prefix(("全局启用表情",), block=True)
async def _global_enable(bot: Bot, ev: Event):
    if ev.user_pm > 1:
        return await bot.send("仅 master/superuser 可设置全局启用")
    name = ev.text.strip()
    if not name:
        return await bot.send("请提供要全局启用的表情名")
    info = await _resolve_one(bot, name)
    if not info:
        return
    meme_manager.set_global_mode(info.key, MemeMode.BLACK)
    await bot.send(f"表情 {info.key} 已恢复全局启用（黑名单模式）")


@sv_manage_global.on_fullmatch(("黑名单", "禁用列表", "黑名单列表"), block=True)
async def _list_global_disabled(bot: Bot, ev: Event):
    if ev.user_pm > 1:
        return await bot.send("仅 master/superuser 可查看全局禁用列表")
    try:
        await meme_manager.init()
    except MemeClientError as e:
        return await bot.send(f"无法连接表情包后端：{e.message}")
    keys = meme_manager.list_globally_disabled()
    if not keys:
        return await bot.send("当前没有全局禁用的表情")
    await bot.send("当前全局禁用的表情：\n" + "\n".join(keys))
