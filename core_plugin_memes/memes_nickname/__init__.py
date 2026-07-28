"""监听全部消息，把发送者昵称写进缓存，供 @ 他人时取名用。

每条消息只做内存 dict 比对，名字没变直接返回；变更走 30 秒 debounce 批量落库。
"""

from gsuid_core.bot import Bot
from gsuid_core.logger import logger
from gsuid_core.models import Event
from gsuid_core.server import on_core_shutdown, on_core_start
from gsuid_core.sv import SV

from ..utils.nickname import nickname_cache


sv_nickname = SV("表情包昵称记录", priority=99, area="ALL")


@sv_nickname.on_message("昵称记录", block=False, prefix=False)
async def _record_nickname(bot: Bot, ev: Event):
    try:
        nickname_cache.remember(ev)
    except Exception as e:
        logger.warning(f"[memes·昵称] 记录昵称失败：{e}")


@on_core_start
async def _preload_nickname_cache() -> None:
    await nickname_cache.preload()


@on_core_shutdown
async def _flush_nickname_cache() -> None:
    await nickname_cache.flush()
