"""meme-generator HTTP 客户端 —— 自适应 Python / Rust 后端。

两版后端的差异：
- Python 版（meme-generator）：路径 `/memes/keys`（复数）；图片直传 multipart 直接拿字节；
  错误用 5xx 状态码；info 返 `params_type.args_type.{args_model, parser_options}`。
- Rust 版（meme-generator-rs）：keys/infos/search/version 路径为 `/meme/`（单数）；
  图片走 `/image/upload` + `image_id` 中转；错误一律 HTTP 500 + body.code；
  info 返 `params.options[]`，shortcut 字段也不同。

本模块统一对外暴露 `MemeClient`，根据后端类型自动选择实现并把不同 schema 归一到
统一的 `NormalizedMemeInfo`，让上层逻辑无需关心背后是哪一版。
"""

from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import httpx

from gsuid_core.logger import logger

from ..memes_config.config import memes_config


class MemeClientError(Exception):
    """统一抛出的异常类型。"""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.code = code


# -------- 归一后的 schema --------


@dataclass
class NormalizedOption:
    name: str
    type: str  # boolean / string / integer / float
    description: Optional[str] = None
    default: Any = None
    short_aliases: List[str] = field(default_factory=list)
    long_aliases: List[str] = field(default_factory=list)
    choices: Optional[List[str]] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None


@dataclass
class NormalizedShortcut:
    keyword: str  # 用户常用的人话
    args: List[str] = field(default_factory=list)


@dataclass
class NormalizedMemeInfo:
    key: str
    keywords: List[str]
    shortcuts: List[NormalizedShortcut]
    tags: List[str]
    min_images: int
    max_images: int
    min_texts: int
    max_texts: int
    default_texts: List[str]
    options: List[NormalizedOption]
    date_created: Optional[datetime] = None
    date_modified: Optional[datetime] = None


# -------- Client --------


BackendType = Literal["py", "rs"]


class MemeClient:
    def __init__(self) -> None:
        self._backend: Optional[BackendType] = None
        self._info_cache: Dict[str, NormalizedMemeInfo] = {}
        self._keys_cache: List[str] = []
        self._lock = asyncio.Lock()

    # ---- 配置访问 ----

    @staticmethod
    def base_url() -> str:
        url = (memes_config.get_config("MemeApiUrl").data or "").strip()
        return url.rstrip("/")

    @staticmethod
    def configured_type() -> str:
        return (memes_config.get_config("MemeApiType").data or "auto").strip().lower()

    @staticmethod
    def timeout() -> float:
        return float(memes_config.get_config("MemeRequestTimeout").data or 60)

    # ---- 后端探测 ----

    async def get_backend(self, force: bool = False) -> BackendType:
        if self._backend is not None and not force:
            return self._backend

        async with self._lock:
            if self._backend is not None and not force:
                return self._backend

            configured = self.configured_type()
            if configured in ("py", "rs"):
                self._backend = configured  # type: ignore[assignment]
                logger.info(f"[core_plugin_memes] 后端类型：{configured}（手动配置）")
                return self._backend  # type: ignore[return-value]

            base = self.base_url()
            if not base:
                raise MemeClientError("未配置 meme-generator 后端地址（MemeApiUrl）")

            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    resp = await client.get(f"{base}/memes/keys")
                    if resp.status_code == 200 and isinstance(resp.json(), list):
                        self._backend = "py"
                        logger.info("[core_plugin_memes] 后端探测：Python 版")
                        return self._backend
                except Exception as e:
                    logger.debug(f"[core_plugin_memes] /memes/keys 探测失败：{e}")

                try:
                    resp = await client.get(f"{base}/meme/keys")
                    if resp.status_code == 200 and isinstance(resp.json(), list):
                        self._backend = "rs"
                        logger.info("[core_plugin_memes] 后端探测：Rust 版")
                        return self._backend
                except Exception as e:
                    logger.debug(f"[core_plugin_memes] /meme/keys 探测失败：{e}")

            raise MemeClientError("无法连接到 meme-generator 后端，请检查 MemeApiUrl 配置")

    # ---- 通用 ----

    async def get_keys(self, force: bool = False) -> List[str]:
        if self._keys_cache and not force:
            return self._keys_cache
        backend = await self.get_backend()
        path = "/memes/keys" if backend == "py" else "/meme/keys"
        async with httpx.AsyncClient(timeout=self.timeout()) as client:
            resp = await client.get(self.base_url() + path)
        self._raise_for_error(resp, backend)
        keys = resp.json()
        if not isinstance(keys, list):
            raise MemeClientError("后端返回 keys 列表格式异常")
        self._keys_cache = sorted(keys)
        return self._keys_cache

    async def get_info(self, key: str, force: bool = False) -> NormalizedMemeInfo:
        if not force and key in self._info_cache:
            return self._info_cache[key]
        backend = await self.get_backend()
        path = f"/memes/{key}/info"
        async with httpx.AsyncClient(timeout=self.timeout()) as client:
            resp = await client.get(self.base_url() + path)
        self._raise_for_error(resp, backend)
        data = resp.json()
        info = (
            self._normalize_py_info(data)
            if backend == "py"
            else self._normalize_rs_info(data)
        )
        self._info_cache[key] = info
        return info

    async def refresh_all(self) -> Tuple[int, int]:
        """重新拉取 keys 和所有 info。返回 (成功条数, 失败条数)。

        Rust：`/meme/infos` 一次拿全。
        Python：并行 per-key，单 httpx.AsyncClient 复用 keep-alive，
                Semaphore=32；760 个 keys 在本地通常 < 2s 完成。
        """
        async with self._lock:
            self._info_cache.clear()
            self._keys_cache.clear()
        keys = await self.get_keys(force=True)
        backend = await self.get_backend()

        if backend == "rs":
            try:
                async with httpx.AsyncClient(timeout=self.timeout()) as client:
                    resp = await client.get(self.base_url() + "/meme/infos")
                self._raise_for_error(resp, backend)
                infos = resp.json()
                if isinstance(infos, list):
                    ok = 0
                    fail = 0
                    for raw in infos:
                        try:
                            info = self._normalize_rs_info(raw)
                            self._info_cache[info.key] = info
                            ok += 1
                        except Exception as e:
                            fail += 1
                            logger.warning(
                                f"[core_plugin_memes] 解析 info 失败：{e}"
                            )
                    return ok, fail
            except Exception as e:
                logger.warning(
                    f"[core_plugin_memes] /meme/infos 失败，回退到并行 per-key 拉取：{e}"
                )

        # Python 后端 / Rust 兜底：并行 per-key
        sem = asyncio.Semaphore(32)

        async def _fetch_one(client: httpx.AsyncClient, key: str) -> bool:
            async with sem:
                try:
                    resp = await client.get(f"{self.base_url()}/memes/{key}/info")
                    self._raise_for_error(resp, "py")
                    info = self._normalize_py_info(resp.json())
                    self._info_cache[info.key] = info
                    return True
                except Exception as e:
                    logger.warning(f"[core_plugin_memes] 获取 {key} info 失败：{e}")
                    return False

        async with httpx.AsyncClient(
            timeout=self.timeout(),
            limits=httpx.Limits(max_keepalive_connections=32, max_connections=64),
        ) as client:
            results = await asyncio.gather(
                *[_fetch_one(client, k) for k in keys], return_exceptions=False
            )
        ok = sum(1 for r in results if r)
        fail = len(results) - ok
        return ok, fail

    async def generate_preview(self, key: str) -> bytes:
        backend = await self.get_backend()
        async with httpx.AsyncClient(timeout=self.timeout()) as client:
            if backend == "py":
                resp = await client.get(
                    f"{self.base_url()}/memes/{key}/preview"
                )
                self._raise_for_error(resp, backend)
                return resp.content
            else:
                resp = await client.get(
                    f"{self.base_url()}/memes/{key}/preview"
                )
                self._raise_for_error(resp, backend)
                image_id = resp.json().get("image_id")
                return await self._rs_get_image(client, image_id)

    async def generate(
        self,
        key: str,
        images: List[Tuple[str, bytes]],
        texts: List[str],
        options: Dict[str, Any],
        user_infos: Optional[List[Dict[str, Any]]] = None,
    ) -> bytes:
        """生成表情。images: [(name, bytes)]"""
        backend = await self.get_backend()
        async with httpx.AsyncClient(timeout=self.timeout()) as client:
            if backend == "py":
                # 把 user_infos 注入 args
                args: Dict[str, Any] = dict(options)
                if user_infos is not None:
                    args["user_infos"] = user_infos
                files = [("images", (name, data)) for name, data in images]
                form: Dict[str, Any] = {
                    "texts": texts,
                    "args": json.dumps(args, ensure_ascii=False),
                }
                resp = await client.post(
                    f"{self.base_url()}/memes/{key}/",
                    files=files if files else None,
                    data=form,
                )
                self._raise_for_error(resp, backend)
                return resp.content
            else:
                image_ids: List[Dict[str, str]] = []
                for name, data in images:
                    image_id = await self._rs_upload_bytes(client, data)
                    image_ids.append({"name": name, "id": image_id})
                payload = {
                    "images": image_ids,
                    "texts": texts,
                    "options": options,
                }
                resp = await client.post(
                    f"{self.base_url()}/memes/{key}", json=payload
                )
                self._raise_for_error(resp, backend)
                image_id = resp.json().get("image_id")
                return await self._rs_get_image(client, image_id)

    async def search(self, query: str, include_tags: bool = True) -> List[str]:
        """关键词搜索。Rust 版有原生 search；Python 版用本地缓存兜底。"""
        backend = await self.get_backend()
        if backend == "rs":
            async with httpx.AsyncClient(timeout=self.timeout()) as client:
                resp = await client.get(
                    f"{self.base_url()}/meme/search",
                    params={"query": query, "include_tags": include_tags},
                )
                self._raise_for_error(resp, backend)
                result = resp.json()
                return result if isinstance(result, list) else []
        # Python 版兜底：在本地 keywords 里模糊匹配
        await self.get_keys()
        hits: List[str] = []
        q = query.lower()
        for key in self._keys_cache:
            try:
                info = await self.get_info(key)
            except Exception:
                continue
            haystack = [info.key.lower()] + [k.lower() for k in info.keywords]
            if include_tags:
                haystack += [t.lower() for t in info.tags]
            for s in haystack:
                if q in s:
                    hits.append(info.key)
                    break
        return hits

    # ---- Rust 专用辅助 ----

    async def _rs_upload_bytes(self, client: httpx.AsyncClient, data: bytes) -> str:
        payload = {"type": "data", "data": base64.b64encode(data).decode()}
        resp = await client.post(
            f"{self.base_url()}/image/upload", json=payload
        )
        self._raise_for_error(resp, "rs")
        image_id = resp.json().get("image_id")
        if not image_id:
            raise MemeClientError("Rust 后端未返回 image_id")
        return image_id

    async def _rs_get_image(
        self, client: httpx.AsyncClient, image_id: Optional[str]
    ) -> bytes:
        if not image_id:
            raise MemeClientError("Rust 后端未返回 image_id")
        resp = await client.get(f"{self.base_url()}/image/{image_id}")
        self._raise_for_error(resp, "rs")
        return resp.content

    # ---- 错误归一 ----

    @staticmethod
    def _raise_for_error(resp: httpx.Response, backend: BackendType) -> None:
        if resp.status_code == 200:
            return
        if backend == "py":
            try:
                detail = resp.json().get("detail")
            except Exception:
                detail = resp.text
            raise MemeClientError(
                f"Python 后端返回 {resp.status_code}：{detail}",
                code=resp.status_code,
            )
        # rs：500 + body.code
        try:
            payload = resp.json()
            code = payload.get("code")
            message = payload.get("message")
            raise MemeClientError(
                f"Rust 后端 code={code}：{message}",
                code=code,
            )
        except MemeClientError:
            raise
        except Exception:
            raise MemeClientError(
                f"Rust 后端返回 {resp.status_code}：{resp.text}",
                code=resp.status_code,
            )

    # ---- schema 归一 ----

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                return None
        return None

    @classmethod
    def _normalize_py_info(cls, data: Dict[str, Any]) -> NormalizedMemeInfo:
        params = data.get("params_type", {})
        args_type = params.get("args_type") or {}
        options: List[NormalizedOption] = []
        for opt in args_type.get("parser_options", []):
            names = opt.get("names", [])
            short_aliases = [n for n in names if n and not n.startswith("--")]
            long_aliases = [n[2:] for n in names if isinstance(n, str) and n.startswith("--")]
            primary_long = long_aliases[0] if long_aliases else (
                short_aliases[0] if short_aliases else ""
            )
            help_text = opt.get("help_text") or ""
            default = opt.get("default")
            # 类型兜底，从 args_model 里推断
            args_model = args_type.get("args_model", {})
            props = args_model.get("properties", {}) if isinstance(args_model, dict) else {}
            field_meta = props.get(primary_long, {}) if isinstance(props, dict) else {}
            field_type = field_meta.get("type", "string") or "string"
            if field_type == "boolean":
                opt_type = "boolean"
            elif field_type == "integer":
                opt_type = "integer"
            elif field_type == "number":
                opt_type = "float"
            else:
                opt_type = "string"
            options.append(
                NormalizedOption(
                    name=opt.get("dest")
                    or primary_long
                    or (short_aliases[0] if short_aliases else ""),
                    type=opt_type,
                    description=help_text or field_meta.get("description"),
                    default=default,
                    short_aliases=short_aliases,
                    long_aliases=long_aliases,
                    choices=field_meta.get("enum"),
                    minimum=field_meta.get("minimum"),
                    maximum=field_meta.get("maximum"),
                )
            )

        shortcuts: List[NormalizedShortcut] = []
        for sc in data.get("shortcuts", []):
            keyword = sc.get("humanized") or sc.get("key") or ""
            args = sc.get("args") or []
            shortcuts.append(NormalizedShortcut(keyword=str(keyword), args=list(args)))

        tags = list(data.get("tags") or [])
        return NormalizedMemeInfo(
            key=data.get("key", ""),
            keywords=list(data.get("keywords") or []),
            shortcuts=shortcuts,
            tags=sorted(tags),
            min_images=int(params.get("min_images", 0)),
            max_images=int(params.get("max_images", 0)),
            min_texts=int(params.get("min_texts", 0)),
            max_texts=int(params.get("max_texts", 0)),
            default_texts=list(params.get("default_texts") or []),
            options=options,
            date_created=cls._parse_dt(data.get("date_created")),
            date_modified=cls._parse_dt(data.get("date_modified")),
        )

    @classmethod
    def _normalize_rs_info(cls, data: Dict[str, Any]) -> NormalizedMemeInfo:
        params = data.get("params", {})
        options: List[NormalizedOption] = []
        for opt in params.get("options", []):
            opt_type = opt.get("type", "string")
            flags = opt.get("parser_flags") or {}
            short_aliases = list(flags.get("short_aliases") or [])
            if flags.get("short"):
                short_aliases.append(opt.get("name"))
            long_aliases = list(flags.get("long_aliases") or [])
            if flags.get("long"):
                long_aliases.append(opt.get("name"))
            options.append(
                NormalizedOption(
                    name=opt.get("name", ""),
                    type=opt_type,
                    description=opt.get("description"),
                    default=opt.get("default"),
                    short_aliases=[a for a in short_aliases if a],
                    long_aliases=[a for a in long_aliases if a],
                    choices=opt.get("choices"),
                    minimum=opt.get("minimum"),
                    maximum=opt.get("maximum"),
                )
            )

        shortcuts: List[NormalizedShortcut] = []
        for sc in data.get("shortcuts", []):
            keyword = sc.get("humanized") or ""
            if not keyword:
                names = sc.get("names") or []
                if names:
                    keyword = str(names[0])
            args: List[str] = list(sc.get("texts") or [])
            sc_options = sc.get("options") or {}
            for k, v in sc_options.items():
                args.extend([f"--{k}", str(v)])
            if keyword:
                shortcuts.append(NormalizedShortcut(keyword=keyword, args=args))

        tags = list(data.get("tags") or [])
        return NormalizedMemeInfo(
            key=data.get("key", ""),
            keywords=list(data.get("keywords") or []),
            shortcuts=shortcuts,
            tags=sorted(tags),
            min_images=int(params.get("min_images", 0)),
            max_images=int(params.get("max_images", 0)),
            min_texts=int(params.get("min_texts", 0)),
            max_texts=int(params.get("max_texts", 0)),
            default_texts=list(params.get("default_texts") or []),
            options=options,
            date_created=cls._parse_dt(data.get("date_created")),
            date_modified=cls._parse_dt(data.get("date_modified")),
        )


meme_client = MemeClient()
