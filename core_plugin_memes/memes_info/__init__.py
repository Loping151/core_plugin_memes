from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..utils.client import meme_client, MemeClientError
from ..utils.manager import meme_manager
from ..utils.prefix import primary_prefix


sv_info = SV("表情详情", priority=4)


_INFO_KEYS = ("表情详情", "表情示例", "查看表情")


@sv_info.on_fullmatch(_INFO_KEYS, block=True)
@sv_info.on_prefix(_INFO_KEYS, block=True)
async def _show_info(bot: Bot, ev: Event):
    name = ev.text.strip()
    if not name:
        return await bot.send(f"请提供要查看的表情名，例如：{primary_prefix()}表情详情 摸")

    try:
        await meme_manager.init()
    except MemeClientError as e:
        return await bot.send(f"无法连接表情包后端：{e.message}")

    found = await meme_manager.find(name)
    if not found:
        searched = await meme_manager.search(name, include_tags=True, limit=5)
        if searched:
            tip = "\n".join(
                f"* {m.key}（{'/'.join(m.keywords) if m.keywords else m.key}）"
                for m in searched
            )
            return await bot.send(f"没有找到表情 “{name}”，你是否想找：\n{tip}")
        return await bot.send(f"没有找到表情 “{name}”")

    if len(found) > 1:
        tip = "\n".join(
            f"{i + 1}. {m.key}（{'/'.join(m.keywords) if m.keywords else m.key}）"
            for i, m in enumerate(found)
        )
        await bot.send(f"找到 {len(found)} 个匹配，第一个用作详情：\n{tip}")
    info = found[0]

    keywords = "、".join(f"“{k}”" for k in info.keywords) or "—"
    shortcuts = "、".join(f"“{sc.keyword}”" for sc in info.shortcuts) or "—"
    tags = "、".join(f"“{t}”" for t in info.tags) or "—"
    image_num = (
        f"{info.min_images}"
        if info.max_images == info.min_images
        else f"{info.min_images} ~ {info.max_images}"
    )
    text_num = (
        f"{info.min_texts}"
        if info.max_texts == info.min_texts
        else f"{info.min_texts} ~ {info.max_texts}"
    )
    default_texts = (
        ", ".join(f"“{t}”" for t in info.default_texts)
        if info.default_texts else "—"
    )
    options_lines = []
    for opt in info.options:
        flags = ", ".join(
            ["--" + a for a in opt.long_aliases]
            + [a for a in opt.short_aliases]
        ) or opt.name
        desc = opt.description or ""
        default = "" if opt.default is None else f"（默认 {opt.default}）"
        options_lines.append(f"  * {flags}{default} {desc}".rstrip())

    info_msg = (
        f"表情名：{info.key}\n"
        f"关键词：{keywords}\n"
        f"快捷指令：{shortcuts}\n"
        f"标签：{tags}\n"
        f"需要图片数：{image_num}\n"
        f"需要文字数：{text_num}\n"
        f"默认文字：{default_texts}"
    )
    if options_lines:
        info_msg += "\n可选参数：\n" + "\n".join(options_lines)

    if meme_manager.is_disabled_globally(info.key):
        info_msg += "\n[全局禁用中]"
    elif not meme_manager.can_use(ev.user_id, info.key):
        info_msg += "\n[当前用户已禁用]"

    try:
        preview = await meme_client.generate_preview(info.key)
    except Exception as e:
        logger.warning(f"[core_plugin_memes] 预览失败：{e}")
        return await bot.send(info_msg + "\n（预览生成失败）")

    await bot.send(info_msg)
    await bot.send(preview)
