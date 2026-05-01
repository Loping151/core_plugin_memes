import asyncio

from gsuid_core.logger import logger
from gsuid_core.server import on_core_start
from gsuid_core.sv import Plugins

Plugins(
    name="core_plugin_memes",
    force_prefix=["mm", "bq"],
    allow_empty_prefix=False,
    priority=4,
)

from . import memes_config  # noqa: F401, E402
from . import memes_group_switch  # noqa: F401, E402
from . import memes_help  # noqa: F401, E402
from . import memes_info  # noqa: F401, E402
from . import memes_make  # noqa: F401, E402
from . import memes_manage  # noqa: F401, E402
from . import memes_plugin_help  # noqa: F401, E402
from . import memes_refresh  # noqa: F401, E402
from . import memes_search  # noqa: F401, E402
from . import memes_stats  # noqa: F401, E402


@on_core_start
async def _bootstrap_memes() -> None:
    """core 启动后异步触发一次元数据拉取；不阻塞 core 启动；失败仅 warning，后续命令会重试。

    manager.init() 内部会打印开始/完成日志（"开始拉取后端表情元数据，请稍候…"
    与 "拉取完成 ✅  共 N 个表情可用"），所以这里不再重复记录。
    """
    from .memes_config.config import memes_config
    from .utils.client import MemeClientError
    from .utils.manager import meme_manager

    base = (memes_config.get_config("MemeApiUrl").data or "").strip()
    if not base:
        logger.info("[core_plugin_memes] MemeApiUrl 未配置，跳过启动预热")
        return

    async def _go() -> None:
        try:
            await meme_manager.init()
        except MemeClientError as e:
            logger.warning(
                f"[core_plugin_memes] 启动预热失败：{e.message}（后续命令会重试）"
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[core_plugin_memes] 启动预热异常：{e}")

    asyncio.create_task(_go(), name="core_plugin_memes:bootstrap")
