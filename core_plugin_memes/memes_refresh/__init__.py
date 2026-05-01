from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..utils.client import meme_client, MemeClientError
from ..utils.manager import meme_manager


sv_refresh = SV("更新表情", priority=4, pm=1)


_REFRESH_KEYS = ("更新表情", "刷新表情", "重载表情")


@sv_refresh.on_fullmatch(_REFRESH_KEYS, block=True)
async def _refresh(bot: Bot, ev: Event):
    if ev.user_pm > 1:
        return await bot.send("仅 master/superuser 可触发更新表情")
    try:
        await meme_client.get_backend(force=True)
        ok, fail = await meme_manager.init(force=True)
    except MemeClientError as e:
        return await bot.send(f"更新失败：{e.message}")
    except Exception as e:
        return await bot.send(f"更新失败：{e}")

    backend = await meme_client.get_backend()
    await bot.send(
        f"已重新拉取后端（{backend.upper()}），"
        f"成功 {ok} 个，失败 {fail} 个"
    )
