# core_plugin_memes

<h1 align = "center">core_plugin_memes</h1>

## 说明

本插件为 [早柚核心 (gsuid_core)](https://github.com/Genshin-bots/gsuid_core)
的扩展，提供基于 [meme-generator](https://github.com/MemeCrafters/meme-generator)
（Python 版）和 [meme-generator-rs](https://github.com/MemeCrafters/meme-generator-rs)
（Rust 版）的表情包制作能力。两种后端任选其一，自动适配。

## 安装

> 该插件为 [早柚核心 (gsuid_core)](https://github.com/Genshin-bots/gsuid_core)
> 的扩展，可参考 [GenshinUID](https://github.com/KimigaiiWuyi/GenshinUID) 的安装方式。

**安装步骤（按顺序做）**

1. clone 到 core 的 plugins 目录：

   ```bash
   cd path/to/gsuid_core/gsuid_core/plugins
   git clone <THIS_REPO_URL> core_plugin_memes
   ```

2. **重启 core**——必须重启一次，让 plugin 注册前缀 `mm` / `bq` 与启动钩子。
3. 在 **webconsole → 插件管理 → `core_plugin_memes`** 中**填写 `MemeApiUrl`**
   （**必填**，例如 `http://127.0.0.1:2234`），其它配置按需调整。
4. master / superuser 在群里发 `mm更新表情`，让插件按新配置重新探测后端、
   并行拉取所有 `info`、重建索引。完成后日志：

   ```
   [core_plugin_memes] 开始拉取后端表情元数据，请稍候…
   [core_plugin_memes] 拉取完成 ✅  共 760 个表情可用
   ```

5. 发 `mm帮助` 看命令清单；发 `mm表情列表` 看所有可用表情。

## 丨拓展

- meme 后端 (Python 版) ：[meme-generator](https://github.com/MemeCrafters/meme-generator)
- meme 后端 (Rust 版)   ：[meme-generator-rs](https://github.com/MemeCrafters/meme-generator-rs)
- 第三方表情仓库          ：[meme-generator-contrib](https://github.com/MemeCrafters/meme-generator-contrib)、
  [meme-generator-contrib-rs](https://github.com/MemeCrafters/meme-generator-contrib-rs)、
  [meme_emoji](https://github.com/anyliew/meme_emoji)、
  [tudou-meme](https://github.com/LRZ9712/tudou-meme)

## 丨安装提醒

> **注意：该插件为 [早柚核心 (gsuid_core)](https://github.com/Genshin-bots/gsuid_core)
> 的扩展，具体安装方式可参考 [GenshinUID](https://github.com/KimigaiiWuyi/GenshinUID)。**
>
> **必须依赖**：core 自带的依赖（FastAPI / SQLModel / msgspec / Pillow / httpx）已能满足本插件
> 全部核心功能。**只要 core 能跑，插件就能跑。**
>
> **建议安装以下额外依赖：**
> - `rapidfuzz`：用于"表情搜索 / 表情详情"的拼写容错匹配；未安装时降级为 `substring` 匹配。
> - `nsfwpy`：当 `MemeNsfwEnabled = true` 时启用 NSFW 双门控；未安装时所有图片直接放行。
>
> ```bash
> # Linux/Mac（在 core 的虚拟环境中执行）
> source .venv/bin/activate && uv pip install rapidfuzz nsfwpy
> # Windows
> .venv\Scripts\activate; uv pip install rapidfuzz nsfwpy
> ```
>
> **如有条件，建议为系统补充以下字体，避免表情列表/帮助图渲染异常：**
> - 汉字字体（必须有其一，否则中文显示为方框）：
>   `Noto Sans CJK SC/TC/JP/KR`、`Source Han Sans`、`WenQuanYi Micro Hei`、`WenQuanYi Zen Hei`、
>   `PingFang`（macOS）、`Microsoft YaHei`（Windows）、`SimHei`（Windows）
> - 拉丁回退字体：`DejaVu Sans`（绝大多数 Linux 默认已有）
>
> Debian/Ubuntu 一行装齐：
> ```bash
> sudo apt install fonts-noto-cjk fonts-wqy-microhei fonts-dejavu
> ```
>
> **后端要求：** 必须有一个 meme-generator (py 或 rs) 可访问，且与 core 同处可达网络。
> 后端的部署方式见上方"丨拓展"。本插件**不会**自动启动后端进程。

## 配置

进入 webconsole → 插件管理 → `core_plugin_memes`：

| key | 类型 | 默认 | 生效时机 | 说明 |
|---|---|---|---|---|
| `MemeApiUrl`（**必填**） | str | `""` | ⚠️ 改后跑 `mm更新表情` | meme 后端 HTTP 地址 |
| `MemeApiType` | str | `auto` | ⚠️ 改后跑 `mm更新表情` | `auto` / `py` / `rs`；auto 时自动识别 |
| `MemeRequestTimeout` | int | 60 | 实时 | HTTP 请求超时秒 |
| `MemeNsfwEnabled` | bool | false | 实时 | 启用 NSFW 检测（需先装 `nsfwpy`） |
| `MemeNsfwModel` | str | `""` | 🔁 改后重启 core | nsfwpy 模型名/路径，留空走默认 |
| `MemeNsfwInputThreshold` | int | 40 | 实时 | 上传图阈值（drawing+neutral 占比百分比） |
| `MemeNsfwOutputThreshold` | int | 50 | 实时 | 成品图阈值（百分比） |
| `MemeResizeImage` | bool | true | 实时 | 缩放成品图并转 WEBP |
| `MemeResizeImageSize` | int | 800 | 实时 | 成品图最大边像素 |
| `MemeAllowDirect` | bool | true | 实时 | 是否允许私聊触发；关闭后 direct 一律忽略 |
| `MemeMissingTextPolicy` | str | `ignore` | 实时 | 缺文字时：`ignore` / `prompt`（不支持交互式补充） |
| `MemeMissingImagePolicy` | str | `ignore` | 实时 | 缺图时：`ignore` / `prompt` |
| `MemeExtraTextPolicy` | str | `drop` | 实时 | 文字过多：`drop`（截断） / `prompt` |
| `MemeExtraImagePolicy` | str | `drop` | 实时 | 图过多：`drop`（截断） / `prompt` |
| `MemeUseSenderWhenNoImage` | bool | true | 实时 | min_images=1 且没图时使用发送者头像 |
| `MemeUseDefaultWhenNoText` | bool | true | 实时 | min_texts>0 且没文字时使用 default_texts |
| `MemeRandomShowInfo` | bool | true | 实时 | 随机表情触发时附带 `指令：<前缀><关键词>` |
| `MemeListPageSize` | int | 5 | 实时 | 表情搜索每页条数 |

**生效时机说明**

- **实时** —— 写入 `data/core_plugin_memes/config.json` 后下一条命令立即生效，无需任何刷新动作。
- ⚠️ **改后跑 `mm更新表情`** —— `MemeApiUrl` / `MemeApiType` 改后，新请求会用新 URL，
  但本地索引（后端类型缓存、keys、info、关键词桶）还是旧后端的快照。需 master/SU
  发 `mm更新表情`，或重启 core 让启动钩子重新拉取。
- 🔁 **改后重启 core** —— `MemeNsfwModel` 在第一次启用 NSFW 检测时被加载到内存中
  并复用；改 model 路径后必须重启 core 才会用新模型。
- **前缀（`mm` / `bq`）改动** —— 改 `core_config.json` 的 `core_plugin_memes.force_prefix`
  / `prefix` 后**必须重启 core**，因为触发器在 core 启动时基于前缀注册一次后就固定了。

## 持久化文件

- `data/core_plugin_memes/config.json` —— 上述所有配置项。
- `data/core_plugin_memes/manager.json` —— 用户级 `禁用表情` 黑名单 + 全局 `白名单模式`
  的状态。**移除某个表情后，该表情的禁用记录会被保留**（不会自动清理），
  但 `mm黑名单` 等命令只显示**当前后端仍存在**的项；如果该表情后续重新出现，
  之前的禁用偏好会自动恢复。
- `data/core_plugin_memes/group_switch.json` —— 按群关闭整个插件的群 id 集合
  （由 `mm关闭表情包` / `mm开启表情包` 维护）。
- gsuid 自带 ORM 表 `CorePluginMemes_Record` —— 所有调用记录（user/group/bot/time/key）；
  webconsole 自动注册"表情调用记录"管理页。

## 命令一览

默认前缀：`mm` 或 `bq`，与命令拼接使用。

| 命令 | 别名 | 权限 | 说明 |
|---|---|---|---|
| `mm/bq帮助` | `插件帮助` | 所有人 | **插件命令帮助**（命令列表，按权限筛选） |
| `mm/bq表情列表` | `表情包制作`、`表情帮助`、`列表` | 所有人 | **表情清单**，按 可用 / 用户禁用 / 全局禁用 分段 |
| `mm/bq表情详情 <name>` | `表情示例`、`查看表情` | 所有人 | 关键词、参数、预览图 |
| `mm/bq表情搜索 <name>` | `表情查找`、`表情查询` | 所有人 | 模糊搜索（含 tag） |
| `mm/bq开启表情包` | `启用表情包功能`、`本群开启表情包` | 群内任何人 | 在本群恢复全部命令 |
| `mm/bq关闭表情包` | `禁用表情包功能`、`本群关闭表情包` | 群内任何人 | 在本群关闭整个插件（开关命令除外） |
| `mm/bq表情包开关` | `表情包状态` | 群内任何人 | 查询本群当前开/关状态 |
| `mm/bq禁用表情 <name>` | – | 所有人 | 当前 user_id 自管 |
| `mm/bq启用表情 <name>` | – | 所有人 | 取消用户级禁用 |
| `mm/bq全局禁用表情 <name>` | – | master/SU | 切到白名单模式 |
| `mm/bq全局启用表情 <name>` | – | master/SU | 切回黑名单模式 |
| `mm/bq黑名单` | `禁用列表`、`黑名单列表` | master/SU | 列出全局禁用的表情 |
| `mm/bq更新表情` | `刷新表情`、`重载表情` | master/SU | 重新拉取后端 |
| `mm/bq表情统计 [时段] [范围] [name]` | `表情调用统计`、`表情使用统计` | 所有人 | 详见下文 |
| `mm/bq随机表情 [文字/图/@]` | – | 所有人 | 在数量约束内随机一个可用表情 |
| `mm/bq<keyword> [图/文字/@QQ/自己 --opt val]` | – | 所有人 | **核心**：制作表情 |

### 表情统计参数

`mm表情统计 [时段] [范围] [表情名?]`

- 时段：`日`/`今日`/`本日`、`24小时`/`1天`、`周`/`一周`/`7天`、`本周`、`月`/`30天`、`本月`、`年`/`一年`、`本年`（默认 24 小时）
- 范围：`全局`、`我的`、`按群`、`按用户`（默认本群）
- 表情名：可选；提供后只统计该表情

例：

- `mm表情统计 月 全局` —— 全局月度排行
- `mm表情统计 本周 我的` —— 你本周用得最多的表情
- `mm表情统计 本日 按用户 摸` —— 本群本日"摸"被谁用了
- `mm表情统计 本月 按群` —— 本月最活跃的群

## NSFW

仅在 `MemeNsfwEnabled = true` 且系统已 `pip install nsfwpy` 时生效；阈值含义为
`drawing + neutral` 总占比百分比。master/superuser 跳过门控。
NSFW 检测耗时较长，且不能保证刁钻 NSFW 过滤，酌情启用。

## 致谢

- [meme-generator](https://github.com/MemeCrafters/meme-generator) / [meme-generator-rs](https://github.com/MemeCrafters/meme-generator-rs)
  —— 后端能力来源
- [nonebot-plugin-memes-api](https://github.com/MemeCrafters/nonebot-plugin-memes-api) —— 部分参考
- [gsuid_core](https://github.com/Genshin-bots/gsuid_core) —— 插件运行时
- [nsfwpy](https://pypi.org/project/nsfwpy/) —— 可选 NSFW 检测后端
