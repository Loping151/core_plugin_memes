"""插件级"帮助"指令——只列命令，按 user_pm 决定显示哪些条目。"""

from typing import List, Tuple

from gsuid_core.bot import Bot
from gsuid_core.models import Event
from gsuid_core.sv import SV

from ..utils.gate import passes_gate
from ..utils.prefix import all_prefixes
from ..utils.render import render_command_help
from ..version import CorePluginMemesVersion


sv_plugin_help = SV("表情包帮助", priority=4)


# (command_template, eg_template, desc, min_pm)
# command_template / eg_template 中的 `<P>` 在渲染前会被替换为真实前缀
_HELP_SECTIONS: List[Tuple[str, List[Tuple[str, str, str, int]]]] = [
    (
        "查看 / 浏览",
        [
            (
                "<P>表情列表",
                "<P0>表情列表",
                "渲染所有表情，分段显示：可用 / 用户禁用 / 全局禁用。"
                "别名：表情包制作 / 表情帮助 / 列表",
                6,
            ),
            (
                "<P>表情详情 <名称>",
                "<P0>表情详情 摸",
                "查看某个表情的关键词、参数、预览图。别名：表情示例 / 查看表情",
                6,
            ),
            (
                "<P>表情搜索 <关键词>",
                "<P0>表情搜索 卡提",
                "在 keyword 与 tag 中模糊搜索。别名：表情查找 / 表情查询",
                6,
            ),
        ],
    ),
    (
        "制作表情",
        [
            (
                "<P><表情关键词> [图/文字/@QQ/自己] [--option val]",
                "<P0>摸 自己",
                "核心命令。`自己`=发送者头像，`@123456`=指定 QQ 头像；"
                "`--option val` / `--option=val` 透传到后端。",
                6,
            ),
            (
                "<P>随机表情 [文字/图/@]",
                "<P0>随机表情 摸",
                "在符合数量约束、未被禁用的表情里随机一个。",
                6,
            ),
        ],
    ),
    (
        "调用统计",
        [
            (
                "<P>表情统计 [时段] [范围] [表情名]",
                "<P0>表情统计 本月 全局",
                "时段：日/24小时/本日/周/7天/本周/月/30天/本月/年/本年；"
                "范围：全局/我的/按群/按用户（默认本群）；"
                "可附表情名只看单条。别名：表情调用统计 / 表情使用统计",
                6,
            ),
        ],
    ),
    (
        "用户级管理",
        [
            (
                "<P>禁用表情 <名称>",
                "<P0>禁用表情 摸",
                "屏蔽该表情对当前 user_id 触发。",
                6,
            ),
            (
                "<P>启用表情 <名称>",
                "<P0>启用表情 摸",
                "撤销用户级屏蔽。",
                6,
            ),
        ],
    ),
    (
        "本群开关",
        [
            (
                "<P>开启表情包",
                "<P0>开启表情包",
                "在本群恢复整个插件的所有指令；任何群成员都可触发。"
                "别名：启用表情包功能 / 本群开启表情包",
                6,
            ),
            (
                "<P>关闭表情包",
                "<P0>关闭表情包",
                "在本群关闭整个插件——除"
                "“开启表情包 / 表情包开关”外的所有命令都被忽略。",
                6,
            ),
            (
                "<P>表情包开关",
                "<P0>表情包开关",
                "查询本群当前是开启还是关闭。",
                6,
            ),
        ],
    ),
    (
        "全局管理（仅 master / superuser）",
        [
            (
                "<P>全局禁用表情 <名称>",
                "<P0>全局禁用表情 摸",
                "切到白名单模式（默认全员禁用）。",
                1,
            ),
            (
                "<P>全局启用表情 <名称>",
                "<P0>全局启用表情 摸",
                "切回黑名单模式（默认全员启用）。",
                1,
            ),
            (
                "<P>黑名单",
                "<P0>黑名单",
                "查看处于全局禁用模式的所有表情。别名：禁用列表 / 黑名单列表",
                1,
            ),
            (
                "<P>更新表情",
                "<P0>更新表情",
                "重新探测后端、拉取所有表情元数据。别名：刷新表情 / 重载表情",
                1,
            ),
        ],
    ),
]


_HELP_KEYS = ("帮助", "插件帮助")


def _expand(template: str, prefixes: List[str], primary: str) -> str:
    return (
        template.replace("<P>", "/".join(prefixes))
        .replace("<P0>", primary)
    )


@sv_plugin_help.on_fullmatch(_HELP_KEYS, block=True)
async def _show_plugin_help(bot: Bot, ev: Event):
    if not passes_gate(ev):
        return
    user_pm = ev.user_pm if isinstance(ev.user_pm, int) else 6
    prefixes = all_prefixes()
    primary = prefixes[0]

    sections: List[Tuple[str, List[Tuple[str, str, str]]]] = []
    for name, items in _HELP_SECTIONS:
        visible = [
            (
                _expand(cmd, prefixes, primary),
                _expand(eg, prefixes, primary),
                desc,
            )
            for cmd, eg, desc, min_pm in items
            if user_pm <= min_pm
        ]
        if visible:
            sections.append((name, visible))

    prefix_label = " · ".join(prefixes)
    img = render_command_help(
        sections,
        title="插件帮助",
        subtitle=f"前缀  {prefix_label}    ·    v{CorePluginMemesVersion}",
        footer=f"发  {primary}表情列表  看所有表情  ／  发  {primary}表情详情 <名>  看单个示例。",
    )
    await bot.send(img)
