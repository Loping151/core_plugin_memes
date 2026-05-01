"""通用闸门：在每条命令进入业务前判断是否放行。

- 私聊开关：MemeAllowDirect 关闭时直接拦截 direct 消息
- 按群开关：群 id 在 manager._group_disabled 集合中时拦截

闸门只用于"业务命令"。"群级开/关 表情包"那条命令本身**不走**这个闸门，
否则关闭后就再也开不回来。
"""

from __future__ import annotations

from gsuid_core.models import Event

from ..memes_config.config import memes_config
from .manager import meme_manager


def passes_gate(ev: Event) -> bool:
    if ev.user_type == "direct":
        if not bool(memes_config.get_config("MemeAllowDirect").data):
            return False
    if ev.user_type == "group" and ev.group_id is not None:
        if not meme_manager.is_group_enabled(ev.group_id):
            return False
    return True
