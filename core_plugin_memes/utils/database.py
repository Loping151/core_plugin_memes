from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Type, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import func
from sqlmodel import Field, select

from gsuid_core.utils.database.base_models import BaseIDModel, with_session
from gsuid_core.webconsole.mount_app import GsAdminModel, PageSchema, site


T_MemeRecord = TypeVar("T_MemeRecord", bound="MemeRecord")


class MemeRecord(BaseIDModel, table=True):
    """表情调用记录"""

    __tablename__ = "CorePluginMemes_Record"
    __table_args__: Dict[str, Any] = {"extend_existing": True}

    bot_id: str = Field(default="", title="平台/适配器")
    bot_self_id: str = Field(default="", title="Bot 自身 ID")
    user_id: str = Field(default="", title="触发用户")
    user_name: str = Field(default="", title="用户昵称")
    group_id: Optional[str] = Field(default=None, title="群聊 ID")
    user_type: str = Field(default="group", title="会话类型")
    meme_key: str = Field(default="", title="表情 key", index=True)
    meme_keyword: str = Field(default="", title="主关键词")
    time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        title="UTC 时间",
        index=True,
    )

    @classmethod
    @with_session
    async def add_record(
        cls: Type[T_MemeRecord],
        session: AsyncSession,
        *,
        bot_id: str,
        bot_self_id: str,
        user_id: str,
        user_name: str,
        group_id: Optional[str],
        user_type: str,
        meme_key: str,
        meme_keyword: str,
    ) -> None:
        record = cls(
            bot_id=bot_id,
            bot_self_id=bot_self_id,
            user_id=user_id,
            user_name=user_name,
            group_id=group_id,
            user_type=user_type,
            meme_key=meme_key,
            meme_keyword=meme_keyword,
        )
        session.add(record)

    @classmethod
    @with_session
    async def query_records(
        cls: Type[T_MemeRecord],
        session: AsyncSession,
        *,
        bot_id: Optional[str] = None,
        bot_self_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        meme_key: Optional[str] = None,
        time_start: Optional[datetime] = None,
        time_stop: Optional[datetime] = None,
    ) -> List["MemeRecord"]:
        stmt = select(cls)
        if bot_id is not None:
            stmt = stmt.where(cls.bot_id == bot_id)
        if bot_self_id is not None:
            stmt = stmt.where(cls.bot_self_id == bot_self_id)
        if user_id is not None:
            stmt = stmt.where(cls.user_id == user_id)
        if group_id is not None:
            stmt = stmt.where(cls.group_id == group_id)
        if meme_key is not None:
            stmt = stmt.where(cls.meme_key == meme_key)
        if time_start is not None:
            stmt = stmt.where(cls.time >= _to_naive_utc(time_start))
        if time_stop is not None:
            stmt = stmt.where(cls.time <= _to_naive_utc(time_stop))
        result = await session.execute(stmt.order_by(cls.time.asc()))
        return list(result.scalars().all())

    @classmethod
    @with_session
    async def count_by_meme(
        cls: Type[T_MemeRecord],
        session: AsyncSession,
        *,
        bot_id: Optional[str] = None,
        bot_self_id: Optional[str] = None,
        user_id: Optional[str] = None,
        group_id: Optional[str] = None,
        time_start: Optional[datetime] = None,
        time_stop: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Tuple[str, int]]:
        stmt = select(cls.meme_key, func.count(cls.id)).group_by(cls.meme_key)
        if bot_id is not None:
            stmt = stmt.where(cls.bot_id == bot_id)
        if bot_self_id is not None:
            stmt = stmt.where(cls.bot_self_id == bot_self_id)
        if user_id is not None:
            stmt = stmt.where(cls.user_id == user_id)
        if group_id is not None:
            stmt = stmt.where(cls.group_id == group_id)
        if time_start is not None:
            stmt = stmt.where(cls.time >= _to_naive_utc(time_start))
        if time_stop is not None:
            stmt = stmt.where(cls.time <= _to_naive_utc(time_stop))
        stmt = stmt.order_by(func.count(cls.id).desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]

    @classmethod
    @with_session
    async def count_by_user(
        cls: Type[T_MemeRecord],
        session: AsyncSession,
        *,
        bot_id: Optional[str] = None,
        bot_self_id: Optional[str] = None,
        group_id: Optional[str] = None,
        meme_key: Optional[str] = None,
        time_start: Optional[datetime] = None,
        time_stop: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Tuple[str, str, int]]:
        stmt = select(cls.user_id, cls.user_name, func.count(cls.id)).group_by(
            cls.user_id, cls.user_name
        )
        if bot_id is not None:
            stmt = stmt.where(cls.bot_id == bot_id)
        if bot_self_id is not None:
            stmt = stmt.where(cls.bot_self_id == bot_self_id)
        if group_id is not None:
            stmt = stmt.where(cls.group_id == group_id)
        if meme_key is not None:
            stmt = stmt.where(cls.meme_key == meme_key)
        if time_start is not None:
            stmt = stmt.where(cls.time >= _to_naive_utc(time_start))
        if time_stop is not None:
            stmt = stmt.where(cls.time <= _to_naive_utc(time_stop))
        stmt = stmt.order_by(func.count(cls.id).desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()
        return [(r[0], r[1], r[2]) for r in rows]

    @classmethod
    @with_session
    async def count_by_group(
        cls: Type[T_MemeRecord],
        session: AsyncSession,
        *,
        bot_id: Optional[str] = None,
        bot_self_id: Optional[str] = None,
        meme_key: Optional[str] = None,
        time_start: Optional[datetime] = None,
        time_stop: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Tuple[Optional[str], int]]:
        stmt = select(cls.group_id, func.count(cls.id)).group_by(cls.group_id)
        if bot_id is not None:
            stmt = stmt.where(cls.bot_id == bot_id)
        if bot_self_id is not None:
            stmt = stmt.where(cls.bot_self_id == bot_self_id)
        if meme_key is not None:
            stmt = stmt.where(cls.meme_key == meme_key)
        if time_start is not None:
            stmt = stmt.where(cls.time >= _to_naive_utc(time_start))
        if time_stop is not None:
            stmt = stmt.where(cls.time <= _to_naive_utc(time_stop))
        stmt = stmt.order_by(func.count(cls.id).desc())
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).all()
        return [(r[0], r[1]) for r in rows]

    @classmethod
    @with_session
    async def total_count(
        cls: Type[T_MemeRecord],
        session: AsyncSession,
        **kwargs: Any,
    ) -> int:
        stmt = select(func.count(cls.id))
        bot_id = kwargs.get("bot_id")
        bot_self_id = kwargs.get("bot_self_id")
        user_id = kwargs.get("user_id")
        group_id = kwargs.get("group_id")
        meme_key = kwargs.get("meme_key")
        time_start = kwargs.get("time_start")
        time_stop = kwargs.get("time_stop")
        if bot_id is not None:
            stmt = stmt.where(cls.bot_id == bot_id)
        if bot_self_id is not None:
            stmt = stmt.where(cls.bot_self_id == bot_self_id)
        if user_id is not None:
            stmt = stmt.where(cls.user_id == user_id)
        if group_id is not None:
            stmt = stmt.where(cls.group_id == group_id)
        if meme_key is not None:
            stmt = stmt.where(cls.meme_key == meme_key)
        if time_start is not None:
            stmt = stmt.where(cls.time >= _to_naive_utc(time_start))
        if time_stop is not None:
            stmt = stmt.where(cls.time <= _to_naive_utc(time_stop))
        return int((await session.execute(stmt)).scalar_one() or 0)


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def parse_period(period: str) -> Tuple[datetime, datetime, str]:
    """解析时段关键词，返回 (start_aware, end_aware, humanized)。"""
    now = datetime.now().astimezone()
    p = period.strip()
    if p in ("日", "今日", "本日"):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now, "今日"
    if p in ("24小时", "1天"):
        return now - timedelta(days=1), now, "24小时"
    if p in ("周", "一周", "7天"):
        return now - timedelta(days=7), now, "7天"
    if p in ("本周",):
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=now.weekday()
        )
        return start, now, "本周"
    if p in ("月", "30天"):
        return now - timedelta(days=30), now, "30天"
    if p in ("本月", "月度"):
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now, "本月"
    if p in ("年", "一年", "365天"):
        return now - timedelta(days=365), now, "一年"
    if p in ("本年", "年度"):
        start = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return start, now, "本年"
    return now - timedelta(days=1), now, "24小时"


@site.register_admin
class CorePluginMemesRecordAdmin(GsAdminModel):
    pk_name = "id"
    page_schema = PageSchema(
        label="表情调用记录",
        icon="fa fa-smile",
    )  # type: ignore

    model = MemeRecord
