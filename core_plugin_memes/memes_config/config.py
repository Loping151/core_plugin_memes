import os

from gsuid_core.data_store import get_res_path
from gsuid_core.utils.plugins_config.gs_config import StringConfig
from gsuid_core.utils.plugins_config.models import (
    GsBoolConfig,
    GsIntConfig,
    GsStrConfig,
)

CONFIG_DEFAULT = {
    "MemeApiUrl": GsStrConfig(
        "表情包后端地址",
        "meme-generator HTTP 服务地址，必填，例如 http://127.0.0.1:2235",
        "",
    ),
    "MemeApiType": GsStrConfig(
        "后端类型",
        "auto/py/rs，auto 时自动探测；py 对接 meme-generator (Python 版)，rs 对接 meme-generator-rs",
        "auto",
        ["auto", "py", "rs"],
    ),
    "MemeRequestTimeout": GsIntConfig(
        "HTTP 请求超时（秒）",
        "调用后端的最大等待秒数",
        60,
    ),
    "MemeNsfwEnabled": GsBoolConfig(
        "启用 NSFW 检测",
        "对上传图片和成品图执行 nsfwpy 检测；未安装 nsfwpy 时自动失效",
        False,
    ),
    "MemeNsfwModel": GsStrConfig(
        "NSFW 模型",
        "nsfwpy 模型名/路径；留空则用默认模型",
        "",
    ),
    "MemeNsfwInputThreshold": GsIntConfig(
        "上传图片阈值（百分比）",
        "drawing+neutral 占比的最小百分比，低于此值判定为不合适并丢弃；默认 40",
        40,
        100,
    ),
    "MemeNsfwOutputThreshold": GsIntConfig(
        "成品图阈值（百分比）",
        "成品图 drawing+neutral 占比最小百分比，低于此值不发送；默认 50",
        50,
        100,
    ),
    "MemeResizeImage": GsBoolConfig(
        "缩放成品图",
        "是否将成品图缩放到指定最大边并转 WEBP",
        True,
    ),
    "MemeResizeImageSize": GsIntConfig(
        "成品图最大边",
        "缩放成品图的最大边像素数",
        800,
    ),
    "MemeAllowDirect": GsBoolConfig(
        "允许私聊触发",
        "关闭后，私聊（direct）发送的所有指令一律忽略；群聊不受影响",
        True,
    ),
    "MemeMissingTextPolicy": GsStrConfig(
        "缺少文字时的处理",
        "ignore=静默不响应；prompt=回复一条提示；不支持交互式补充",
        "prompt",
        ["ignore", "prompt"],
    ),
    "MemeMissingImagePolicy": GsStrConfig(
        "缺少图片时的处理",
        "ignore=静默不响应；prompt=回复一条提示；不支持交互式补充",
        "prompt",
        ["ignore", "prompt"],
    ),
    "MemeExtraTextPolicy": GsStrConfig(
        "文字过多时的处理",
        "drop=只保留前 max_texts 段；prompt=回复提示数量不符",
        "drop",
        ["drop", "prompt"],
    ),
    "MemeExtraImagePolicy": GsStrConfig(
        "图片过多时的处理",
        "drop=只保留前 max_images 张；prompt=回复提示数量不符",
        "drop",
        ["drop", "prompt"],
    ),
    "MemeUseSenderWhenNoImage": GsBoolConfig(
        "无图自动用发送者头像",
        "min_images=1 且未提供图片时，自动使用发送者头像",
        True,
    ),
    "MemeUseDefaultWhenNoText": GsBoolConfig(
        "无文字自动用默认文字",
        "min_texts>0 且未提供文字时，自动使用 default_texts",
        True,
    ),
    "MemeRandomShowInfo": GsBoolConfig(
        "随机表情显示关键词",
        "随机表情触发时附带提示关键词",
        True,
    ),
    "MemeListPageSize": GsIntConfig(
        "搜索分页大小",
        "表情搜索结果每页条数",
        5,
    ),
}


CONFIG_PATH = get_res_path() / "core_plugin_memes" / "config.json"
os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)


memes_config = StringConfig("core_plugin_memes", CONFIG_PATH, CONFIG_DEFAULT)
