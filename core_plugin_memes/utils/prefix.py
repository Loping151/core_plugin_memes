"""读取本插件当前生效的前缀。

走 gsuid 的 `get_plugin_force_prefixs` / `get_plugin_prefixs`，因此用户在
`config_plugins.json` 里改了前缀也能立即拿到，不写死 mm/bq。
"""

from __future__ import annotations

from typing import List

from gsuid_core.sv import get_plugin_force_prefixs, get_plugin_prefixs


PLUGIN_NAME = "core_plugin_memes"


def all_prefixes() -> List[str]:
    """force_prefix 优先 + 用户配置的 prefix；保留出现顺序、去重；都拿不到时退回默认。"""
    seen: List[str] = []
    try:
        for p in get_plugin_force_prefixs(PLUGIN_NAME):
            if p and p not in seen:
                seen.append(p)
    except Exception:
        pass
    try:
        for p in get_plugin_prefixs(PLUGIN_NAME):
            if p and p not in seen:
                seen.append(p)
    except Exception:
        pass
    if not seen:
        seen = ["mm", "bq"]  # 仅作为框架尚未注册时的兜底
    return seen


def primary_prefix() -> str:
    return all_prefixes()[0]


def join_prefixes(sep: str = "/") -> str:
    """例如 "mm/bq" 或 "mm · bq"。"""
    return sep.join(all_prefixes())
