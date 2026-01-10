import uuid
from datetime import datetime, timezone
from typing import Optional, TypeVar, Type, Sequence
from sqlalchemy import DateTime, select
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase
from sqlalchemy.ext.asyncio import AsyncSession


class Base(DeclarativeBase):
    """Base class for all models"""
    pass


T = TypeVar("T", bound="BaseModel")


class BaseModel(Base):
    """Abstract base model with common fields and async CRUD methods"""
    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), 
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    def add(self, db: AsyncSession) -> "BaseModel":
        """Add new object to db session without committing"""
        db.add(self)
        return self
    
    def remove(self, db: AsyncSession) -> "BaseModel":
        """Mark object for deletion without committing"""
        db.delete(self)
        return self

    async def insert(self, db: AsyncSession, commit: bool = True) -> "BaseModel":
        """Insert new object to db"""
        db.add(self)
        if commit:
            await db.commit()
            await db.refresh(self)
        return self

    async def update(self, db: AsyncSession, commit: bool = True) -> "BaseModel":
        """Save updates to the object"""
        self.updated_at = datetime.now(timezone.utc)
        if commit:
            await db.commit()
            await db.refresh(self)
        return self

    async def delete(self, db: AsyncSession, commit: bool = True) -> "BaseModel":
        """Delete object from db"""
        await db.delete(self)
        if commit:
            await db.commit()
        return self

    @classmethod
    async def fetch_one(cls: Type[T], db: AsyncSession, **kwargs) -> Optional[T]:
        """Get first matching object"""
        result = await db.execute(
            select(cls).filter_by(**kwargs)
        )
        return result.scalars().first()

    @classmethod
    async def fetch_unique(cls: Type[T], db: AsyncSession, **kwargs) -> Optional[T]:
        """Get unique object or None"""
        result = await db.execute(
            select(cls).filter_by(**kwargs)
        )
        return result.scalars().one_or_none()

    @classmethod
    async def fetch_all(cls: Type[T], db: AsyncSession, **kwargs) -> Sequence[T]:
        """Get all matching objects"""
        result = await db.execute(
            select(cls).filter_by(**kwargs)
        )
        return result.scalars().all()

    @classmethod
    async def fetch_by_id(cls: Type[T], db: AsyncSession, id: uuid.UUID) -> Optional[T]:
        """Get object by ID"""
        result = await db.execute(
            select(cls).filter_by(id=id)
        )
        return result.scalars().first()