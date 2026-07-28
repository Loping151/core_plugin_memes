"""昵称缓存：收到消息时记下 sender 的 id → 昵称/群名片，被 @ 时反查。

core 下发的 at 段只带 user_id，没有昵称。数据存独立小库
`data/core_plugin_memes/nicknames.db`（不进主库 GsData.db）：
读全走内存，写按 30 秒 debounce 批量 UPSERT，group_id 为空串的行是全局昵称。
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from gsuid_core.data_store import get_res_path
from gsuid_core.logger import logger
from gsuid_core.models import Event


_FLUSH_DELAY = 30  # 秒，写盘 debounce
_MAX_ROWS = 50000
_GLOBAL = ""  # group_id 占位：全局昵称

Key = Tuple[str, str, str]  # (bot_id, user_id, group_id)


class NicknameCache:
    def __init__(self) -> None:
        base = Path(get_res_path()) / "core_plugin_memes"
        os.makedirs(base, exist_ok=True)
        self._path = base / "nicknames.db"
        # key → (name, updated)
        self._names: Dict[Key, Tuple[str, int]] = {}
        self._pending: Set[Key] = set()
        self._loaded = False
        self._flush_task: Optional[asyncio.Task] = None
        self._flush_lock = asyncio.Lock()

    # ---- sqlite ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS nickname ("
            "bot_id TEXT NOT NULL, user_id TEXT NOT NULL, group_id TEXT NOT NULL, "
            "name TEXT NOT NULL, updated INTEGER NOT NULL, "
            "PRIMARY KEY (bot_id, user_id, group_id))"
        )
        return conn

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT bot_id, user_id, group_id, name, updated FROM nickname"
                ).fetchall()
            finally:
                conn.close()
            self._names = {(r[0], r[1], r[2]): (r[3], int(r[4])) for r in rows}
            logger.debug(f"[memes·昵称] 载入 {len(self._names)} 条昵称")
        except Exception as e:
            logger.warning(f"[memes·昵称] 读取 nicknames.db 失败：{e}")

    def _write(self, rows: List[Tuple[str, str, str, str, int]]) -> List[Key]:
        """批量 UPSERT，超量时按 updated 淘汰，返回被淘汰的 key。"""
        victims: List[Key] = []
        try:
            conn = self._connect()
            try:
                conn.executemany(
                    "INSERT INTO nickname (bot_id, user_id, group_id, name, updated) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(bot_id, user_id, group_id) DO UPDATE SET "
                    "name = excluded.name, updated = excluded.updated",
                    rows,
                )
                conn.commit()
                total = conn.execute("SELECT COUNT(*) FROM nickname").fetchone()[0]
                if total > _MAX_ROWS:
                    victims = conn.execute(
                        "SELECT bot_id, user_id, group_id FROM nickname "
                        "ORDER BY updated ASC LIMIT ?",
                        (total - _MAX_ROWS,),
                    ).fetchall()
                    conn.executemany(
                        "DELETE FROM nickname WHERE bot_id = ? AND user_id = ? "
                        "AND group_id = ?",
                        victims,
                    )
                    conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"[memes·昵称] 写入 nicknames.db 失败：{e}")
        return victims

    async def preload(self) -> None:
        """core 启动时预热，避免首条消息在事件循环里同步读库。"""
        await asyncio.to_thread(self._load)

    # ---- flush ----

    def _schedule_flush(self) -> None:
        if self._flush_task and not self._flush_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._flush_task = loop.create_task(
            self._delayed_flush(), name="core_plugin_memes:nickname-flush"
        )

    async def _delayed_flush(self) -> None:
        try:
            await asyncio.sleep(_FLUSH_DELAY)
        except asyncio.CancelledError:
            return
        await self.flush()

    async def flush(self) -> None:
        async with self._flush_lock:
            if not self._pending:
                return
            pending = self._pending
            self._pending = set()
            rows = [
                (k[0], k[1], k[2], self._names[k][0], self._names[k][1])
                for k in pending
                if k in self._names
            ]
            if not rows:
                return
            for key in await asyncio.to_thread(self._write, rows):
                self._names.pop(tuple(key), None)  # type: ignore[arg-type]

    # ---- api ----

    def remember(self, ev: Event) -> None:
        """把本条消息发送者的昵称/群名片写进缓存。"""
        if not ev.user_id or not isinstance(ev.sender, dict):
            return
        nickname = ev.sender.get("nickname") or ev.sender.get("name")
        card = ev.sender.get("card")
        if not nickname and not card:
            return

        self._load()
        now = int(time.time())
        if nickname:
            self._put(ev.bot_id, str(ev.user_id), _GLOBAL, str(nickname).strip(), now)
        if card and ev.group_id:
            self._put(
                ev.bot_id, str(ev.user_id), str(ev.group_id), str(card).strip(), now
            )

    def _put(
        self, bot_id: str, user_id: str, group_id: str, name: str, now: int
    ) -> None:
        if not name:
            return
        key = (bot_id, user_id, group_id)
        old = self._names.get(key)
        if old and old[0] == name:
            return
        self._names[key] = (name, now)
        self._pending.add(key)
        self._schedule_flush()

    def get(
        self,
        bot_id: str,
        user_id: str,
        group_id: Optional[str] = None,
    ) -> Optional[str]:
        """本群群名片优先，其次全局昵称；查不到返回 None。"""
        self._load()
        if group_id:
            hit = self._names.get((bot_id, str(user_id), str(group_id)))
            if hit:
                return hit[0]
        hit = self._names.get((bot_id, str(user_id), _GLOBAL))
        return hit[0] if hit else None


nickname_cache = NicknameCache()
