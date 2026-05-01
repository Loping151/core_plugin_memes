"""表情元数据管理 + 黑/白名单。

- 元数据从后端拉取后缓存在内存（同时由 client._info_cache 持有）
- 黑白名单持久化在 `data/core_plugin_memes/manager.json`
  - 每个 meme_key 有一个 mode（black / white）
    - black：默认放行；user_id 进入 black_list 后对该用户禁用
    - white：默认全员禁用；user_id 进入 white_list 才允许
- 通过模糊匹配（rapidfuzz 可选，否则降级到 difflib）支持 find / search
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from gsuid_core.data_store import get_res_path
from gsuid_core.logger import logger

from .client import NormalizedMemeInfo, meme_client


class MemeMode(IntEnum):
    BLACK = 0  # 默认放行，黑名单内的 user 不允许
    WHITE = 1  # 默认禁用，白名单内的 user 允许


@dataclass
class MemeStateConfig:
    mode: MemeMode = MemeMode.BLACK
    black_list: List[str] = field(default_factory=list)
    white_list: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "mode": int(self.mode),
            "black_list": list(self.black_list),
            "white_list": list(self.white_list),
        }

    @classmethod
    def from_dict(cls, raw: Dict) -> "MemeStateConfig":
        return cls(
            mode=MemeMode(int(raw.get("mode", 0))),
            black_list=list(raw.get("black_list") or []),
            white_list=list(raw.get("white_list") or []),
        )


class MemeManager:
    def __init__(self) -> None:
        base = Path(get_res_path()) / "core_plugin_memes"
        os.makedirs(base, exist_ok=True)
        self._path = base / "manager.json"
        self._group_switch_path = base / "group_switch.json"
        self._lock = asyncio.Lock()
        self._loaded = False
        self._ready = False
        self._loading = False
        # meme_key → MemeStateConfig
        self._state: Dict[str, MemeStateConfig] = {}
        # name → [meme_key]，name 包括 key、所有 keyword、shortcut humanized
        self._name_index: Dict[str, List[str]] = {}
        # tag → [meme_key]
        self._tag_index: Dict[str, List[str]] = {}
        # 首字符桶：first_char → 按 len desc 排序的 name 列表，用于长前缀匹配
        self._first_char_index: Dict[str, List[str]] = {}
        self._duplicate_names: Dict[str, List[str]] = {}
        # 按群关闭整个表情包功能的群 id 集合
        self._group_disabled: set = set()
        self._group_switch_loaded = False

    # ---- persistence ----

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text("utf-8"))
                self._state = {
                    k: MemeStateConfig.from_dict(v) for k, v in raw.items()
                }
            except Exception as e:
                logger.warning(f"[core_plugin_memes] manager.json 解析失败：{e}")
                self._state = {}

    def _dump(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {k: v.to_dict() for k, v in self._state.items()},
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )

    def _load_group_switch(self) -> None:
        if self._group_switch_loaded:
            return
        self._group_switch_loaded = True
        if self._group_switch_path.exists():
            try:
                raw = json.loads(self._group_switch_path.read_text("utf-8"))
                self._group_disabled = set(str(g) for g in (raw.get("disabled_groups") or []))
            except Exception as e:
                logger.warning(f"[core_plugin_memes] group_switch.json 解析失败：{e}")
                self._group_disabled = set()

    def _dump_group_switch(self) -> None:
        self._group_switch_path.parent.mkdir(parents=True, exist_ok=True)
        self._group_switch_path.write_text(
            json.dumps(
                {"disabled_groups": sorted(self._group_disabled)},
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )

    # ---- 按群开关 ----

    def is_group_enabled(self, group_id) -> bool:
        if group_id is None:
            return True
        self._load_group_switch()
        return str(group_id) not in self._group_disabled

    def disable_group(self, group_id) -> bool:
        """关闭后返回是否产生变化。"""
        self._load_group_switch()
        gid = str(group_id)
        if gid in self._group_disabled:
            return False
        self._group_disabled.add(gid)
        self._dump_group_switch()
        return True

    def enable_group(self, group_id) -> bool:
        self._load_group_switch()
        gid = str(group_id)
        if gid not in self._group_disabled:
            return False
        self._group_disabled.discard(gid)
        self._dump_group_switch()
        return True

    # ---- init ----

    async def init(self, force: bool = False) -> Tuple[int, int]:
        """从后端拉取元数据并刷新本地索引。"""
        async with self._lock:
            self._loading = True
            try:
                logger.info("[core_plugin_memes] 开始拉取后端表情元数据，请稍候…")
                ok, fail = await meme_client.refresh_all()
                if not self._loaded:
                    self._load()
                    self._loaded = True

                keys = await meme_client.get_keys()
                for key in keys:
                    if key not in self._state:
                        self._state[key] = MemeStateConfig()
                self._dump()

                await self._rebuild_indexes(keys)
                self._ready = True
                logger.success(
                    f"[core_plugin_memes] 拉取完成 ✅  共 {len(keys)} 个表情可用"
                )
            finally:
                self._loading = False
        return ok, fail

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def is_loading(self) -> bool:
        return self._loading

    async def _rebuild_indexes(self, keys: List[str]) -> None:
        self._name_index.clear()
        self._tag_index.clear()
        self._first_char_index.clear()
        self._duplicate_names.clear()

        for key in keys:
            try:
                info = await meme_client.get_info(key)
            except Exception as e:
                logger.warning(f"[core_plugin_memes] 索引 {key} 失败：{e}")
                continue
            names = {key.lower()}
            for kw in info.keywords:
                if kw:
                    names.add(kw.lower())
            for sc in info.shortcuts:
                if sc.keyword:
                    names.add(sc.keyword.lower())
            for name in names:
                self._name_index.setdefault(name, []).append(key)
            for tag in info.tags:
                if tag:
                    self._tag_index.setdefault(tag.lower(), []).append(key)

        # 同名冲突：keyword 被多个 meme 共用，仅取第一个（按 keys 顺序）
        self._duplicate_names = {
            n: ks for n, ks in self._name_index.items() if len(ks) > 1
        }
        if self._duplicate_names:
            sample = list(self._duplicate_names.items())[:8]
            logger.warning(
                f"[core_plugin_memes] 检测到 {len(self._duplicate_names)} 个同名冲突，"
                "仅保留首个 meme（按后端 keys 顺序）。示例：\n  "
                + "\n  ".join(
                    f"'{n}' → {ks}" for n, ks in sample
                )
            )

        # 首字符桶 + 长度倒序：用于 O(bucket_size) 长前缀匹配
        for name in self._name_index.keys():
            if not name:
                continue
            self._first_char_index.setdefault(name[0], []).append(name)
        for bucket in self._first_char_index.values():
            bucket.sort(key=lambda n: (-len(n), n))

        logger.info(
            f"[core_plugin_memes] 索引完成：{len(self._name_index)} 个名称，"
            f"{len(self._tag_index)} 个 tag，分布到 {len(self._first_char_index)} 个首字符桶"
        )

    # ---- queries ----

    async def get_all(self) -> List[NormalizedMemeInfo]:
        keys = await meme_client.get_keys()
        result: List[NormalizedMemeInfo] = []
        for key in keys:
            try:
                result.append(await meme_client.get_info(key))
            except Exception:
                continue
        return result

    async def find(self, name: str) -> List[NormalizedMemeInfo]:
        if not name:
            return []
        name_l = name.lower()
        keys = self._name_index.get(name_l, [])
        return [await meme_client.get_info(k) for k in keys]

    def find_by_prefix_key(self, text: str) -> Tuple[Optional[str], str, str]:
        """长前缀匹配：扫描以 text 首字符开头的 name 桶（按长度倒序），找到首个
        被 text 命中前缀的 name。性能 O(bucket_size)；CJK 桶通常 1~5 项。

        - text 不要求与 name 之间有空格：`菲比说你好` 命中 `菲比说`
        - 也兼容有空格：`菲比说 你好` 同样命中 `菲比说`，多余空格被吃掉
        - 返回 (meme_key, matched_name, rest_text)；命中失败返回 (None, "", text)
        """
        if not text:
            return None, "", text
        text_l = text.lower()
        bucket = self._first_char_index.get(text_l[0])
        if not bucket:
            return None, "", text
        for name in bucket:
            if text_l.startswith(name):
                keys = self._name_index.get(name, [])
                if keys:
                    rest = text[len(name):]
                    if rest.startswith(" "):
                        rest = rest.lstrip()
                    return keys[0], name, rest
        return None, "", text

    async def search(
        self,
        name: str,
        include_tags: bool = True,
        score_cutoff: float = 70.0,
        limit: Optional[int] = None,
    ) -> List[NormalizedMemeInfo]:
        if not name:
            return []
        # 优先用后端搜索（Rust 版自带，Python 版由 client 兜底）
        result_keys: List[str] = []
        try:
            result_keys = await meme_client.search(name, include_tags=include_tags)
        except Exception as e:
            logger.debug(f"[core_plugin_memes] 后端 search 失败，本地兜底：{e}")

        if not result_keys:
            result_keys = self._fuzzy_local(name, include_tags, score_cutoff)

        memos: List[NormalizedMemeInfo] = []
        seen = set()
        for key in result_keys:
            if key in seen:
                continue
            seen.add(key)
            try:
                memos.append(await meme_client.get_info(key))
            except Exception:
                continue
            if limit is not None and len(memos) >= limit:
                break
        return memos

    def _fuzzy_local(
        self, name: str, include_tags: bool, score_cutoff: float
    ) -> List[str]:
        try:
            from rapidfuzz import process  # type: ignore

            names_pool = list(self._name_index.keys())
            tag_pool = list(self._tag_index.keys()) if include_tags else []
            name_l = name.lower()
            hits: List[str] = []
            for n, _, _ in process.extract(
                name_l, names_pool, score_cutoff=score_cutoff
            ):
                hits.extend(self._name_index.get(n, []))
            for t, _, _ in process.extract(
                name_l, tag_pool, score_cutoff=score_cutoff
            ):
                hits.extend(self._tag_index.get(t, []))
            return hits
        except ImportError:
            # 简化：直接 substring 匹配
            name_l = name.lower()
            hits: List[str] = []
            for n, keys in self._name_index.items():
                if name_l in n or n in name_l:
                    hits.extend(keys)
            if include_tags:
                for t, keys in self._tag_index.items():
                    if name_l in t or t in name_l:
                        hits.extend(keys)
            return hits

    # ---- 黑/白名单 ----

    def _ensure(self, key: str) -> MemeStateConfig:
        if key not in self._state:
            self._state[key] = MemeStateConfig()
        return self._state[key]

    def can_use(self, user_id: str, meme_key: str) -> bool:
        cfg = self._state.get(meme_key)
        if cfg is None:
            return True
        if cfg.mode == MemeMode.BLACK:
            return user_id not in cfg.black_list
        return user_id in cfg.white_list

    def is_disabled_globally(self, meme_key: str) -> bool:
        cfg = self._state.get(meme_key)
        return bool(cfg and cfg.mode == MemeMode.WHITE)

    def block_for_user(self, user_id: str, meme_key: str) -> bool:
        cfg = self._ensure(meme_key)
        if cfg.mode == MemeMode.WHITE:
            return False  # 全局禁用了，无法在用户级解决
        if user_id in cfg.black_list:
            return False
        cfg.black_list.append(user_id)
        self._dump()
        return True

    def unblock_for_user(self, user_id: str, meme_key: str) -> bool:
        cfg = self._ensure(meme_key)
        if cfg.mode == MemeMode.WHITE:
            return False  # 全局禁用了，得让 SU 改回来
        if user_id in cfg.black_list:
            cfg.black_list.remove(user_id)
            self._dump()
            return True
        return True

    def set_global_mode(self, meme_key: str, mode: MemeMode) -> None:
        cfg = self._ensure(meme_key)
        cfg.mode = mode
        self._dump()

    def list_globally_disabled(self) -> List[str]:
        """返回当前后端仍存在 + 被设为白名单（=全局禁用）的 meme key。

        某些表情可能从后端被移除，但本地 manager.json 仍持有它们的禁用状态——
        我们故意不删除，避免后续重新出现时丢失偏好；但展示 / 校验时只看现存的。
        """
        live_keys = set(meme_client._info_cache.keys())  # type: ignore[attr-defined]
        return [
            k for k, v in self._state.items()
            if v.mode == MemeMode.WHITE and k in live_keys
        ]


meme_manager = MemeManager()
