import uuid
from datetime import datetime, timezone
from typing import TypeVar, Type, Sequence, Any, Optional

from sqlalchemy import DateTime, select, Select, func as sa_func, desc as sa_desc, asc as sa_asc
from sqlalchemy.orm import Mapped, mapped_column, DeclarativeBase, InstrumentedAttribute
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


T = TypeVar("T", bound="BaseModel")


class QueryBuilder:
    """Fluent query builder for BaseModel with ACID-safe operations."""
    
    def __init__(self, model_class: Type[T], db: AsyncSession):
        self.model_class = model_class
        self.db = db
        self._query: Select = select(model_class)
        self._eager_load_options: list = []
    
    def filter(self, *conditions) -> "QueryBuilder":
        """Add WHERE conditions."""
        self._query = self._query.where(*conditions)
        return self
    
    def filter_by(self, **kwargs) -> "QueryBuilder":
        """Add WHERE conditions using keyword arguments."""
        self._query = self._query.filter_by(**kwargs)
        return self
    
    def with_relations(self, *relations) -> "QueryBuilder":
        """Eager load relationships."""
        from sqlalchemy.orm import selectinload
        for relation in relations:
            if isinstance(relation, str):
                # String relationship name
                self._query = self._query.options(selectinload(getattr(self.model_class, relation)))
            elif isinstance(relation, InstrumentedAttribute):
                # Direct relationship attribute
                self._query = self._query.options(selectinload(relation))
        return self
    
    def order_by(self, *columns, desc: bool = False) -> "QueryBuilder":
        """Add ORDER BY clause."""
        if desc:
            order_columns = [sa_desc(col) if not isinstance(col, type(sa_desc(self.model_class.id))) else col for col in columns]
        else:
            order_columns = [sa_asc(col) if not isinstance(col, type(sa_asc(self.model_class.id))) else col for col in columns]
        self._query = self._query.order_by(*order_columns)
        return self
    
    def limit(self, limit: int) -> "QueryBuilder":
        """Add LIMIT clause."""
        self._query = self._query.limit(limit)
        return self
    
    def offset(self, offset: int) -> "QueryBuilder":
        """Add OFFSET clause."""
        self._query = self._query.offset(offset)
        return self
    
    def paginate(self, page: int = 1, per_page: int = 20) -> "QueryBuilder":
        """Add pagination (LIMIT/OFFSET)."""
        offset = (page - 1) * per_page
        self._query = self._query.limit(per_page).offset(offset)
        return self
    
    async def all(self) -> Sequence[T]:
        """Execute query and return all results."""
        result = await self.db.execute(self._query)
        return result.scalars().all()
    
    async def first(self) -> Optional[T]:
        """Execute query and return first result or None."""
        result = await self.db.execute(self._query)
        return result.scalars().first()
    
    async def one(self) -> T:
        """Execute query and return exactly one result (raises if not found or multiple)."""
        result = await self.db.execute(self._query)
        return result.scalars().one()
    
    async def one_or_none(self) -> Optional[T]:
        """Execute query and return one result or None (raises if multiple)."""
        result = await self.db.execute(self._query)
        return result.scalars().one_or_none()
    
    async def count(self) -> int:
        """Return count of matching records."""
        count_query = select(sa_func.count()).select_from(self._query.subquery())
        result = await self.db.execute(count_query)
        return result.scalar() or 0


class BaseModel(Base):
    """Abstract base model with common fields and async CRUD methods."""
    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    
    def add(self, db: AsyncSession) -> "BaseModel":
        """Add object to session without committing."""
        db.add(self)
        return self
    
    def remove(self, db: AsyncSession) -> "BaseModel":
        """Mark object for deletion without committing."""
        db.delete(self)
        return self

    async def insert(self, db: AsyncSession, commit: bool = True, flush: bool = False) -> "BaseModel":
        """Insert new object to database.
        
        Args:
            db: Database session
            commit: If True, commits transaction immediately
            flush: If True, flushes to DB without committing (for batching)
        
        Returns:
            Self for method chaining
        """
        db.add(self)
        if commit:
            await db.commit()
            await db.refresh(self)
        elif flush:
            await db.flush()
        return self

    async def save(self, db: AsyncSession, commit: bool = True, flush: bool = False) -> "BaseModel":
        """Save updates to the object.
        
        Args:
            db: Database session
            commit: If True, commits transaction immediately
            flush: If True, flushes to DB without committing (for batching)
        
        Returns:
            Self for method chaining
        """
        self.updated_at = datetime.now(timezone.utc)
        if commit:
            await db.commit()
            await db.refresh(self)
        elif flush:
            await db.flush()
        return self

    async def delete(self, db: AsyncSession, commit: bool = True) -> "BaseModel":
        """Delete object from database.
        
        Args:
            db: Database session
            commit: If True, commits transaction immediately
        
        Returns:
            Self for method chaining
        """
        await db.delete(self)
        if commit:
            await db.commit()
        return self

    # ============== Query Methods ==============

    @classmethod
    def query(cls: Type[T], db: AsyncSession) -> QueryBuilder:
        """Create a fluent query builder for this model."""
        return QueryBuilder(cls, db)

    @classmethod
    async def fetch_one(cls: Type[T], db: AsyncSession, **kwargs) -> Optional[T]:
        """Get first matching object."""
        result = await db.execute(select(cls).filter_by(**kwargs))
        return result.scalars().first()

    @classmethod
    async def fetch_unique(cls: Type[T], db: AsyncSession, **kwargs) -> Optional[T]:
        """Get unique object or None."""
        result = await db.execute(select(cls).filter_by(**kwargs))
        return result.scalars().one_or_none()

    @classmethod
    async def fetch_all(cls: Type[T], db: AsyncSession, **kwargs) -> Sequence[T]:
        """Get all matching objects."""
        result = await db.execute(select(cls).filter_by(**kwargs))
        return result.scalars().all()

    @classmethod
    async def fetch_by_id(cls: Type[T], db: AsyncSession, id: uuid.UUID) -> Optional[T]:
        """Get object by ID."""
        return await db.get(cls, id)
    
    @classmethod
    async def fetch_with(
        cls: Type[T], 
        db: AsyncSession, 
        *relations,
        **filters
    ) -> Sequence[T]:
        """Fetch with eager loading of relationships.
        
        Args:
            db: Database session
            relations: Relationship names or attributes to eager load
            filters: Filter conditions (field=value)
        
        Example:
            users = await User.fetch_with(db, "organization", role=UserRole.DOCTOR)
        """
        return await cls.query(db).with_relations(*relations).filter_by(**filters).all()
    
    @classmethod
    async def fetch_one_with(
        cls: Type[T], 
        db: AsyncSession, 
        *relations,
        **filters
    ) -> Optional[T]:
        """Fetch one record with eager loading.
        
        Args:
            db: Database session
            relations: Relationship names or attributes to eager load
            filters: Filter conditions (field=value)
        
        Example:
            user = await User.fetch_one_with(db, "organization", email="test@example.com")
        """
        return await cls.query(db).with_relations(*relations).filter_by(**filters).one_or_none()