"""Database repository for CRUD operations."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, List, Optional

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.database.models import Base, Conversation, Message, User

logger = logging.getLogger(__name__)


class Repository:
    """Database repository for all database operations."""

    def __init__(self, database_url: str):
        # SQLite doesn't support pool_size/max_overflow
        engine_kwargs = {"echo": False}
        if "sqlite" not in database_url:
            engine_kwargs["pool_size"] = 10
            engine_kwargs["max_overflow"] = 20

        self.engine = create_async_engine(database_url, **engine_kwargs)
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_db(self) -> None:
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables initialized")

    async def close(self) -> None:
        """Close database connections."""
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session context manager."""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # User operations
    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
    ) -> User:
        """Get existing user or create new one."""
        async with self.session() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                )
                session.add(user)
                await session.flush()
                logger.info(f"Created new user: {telegram_id}")
            else:
                # Update user info if changed
                user.username = username
                user.first_name = first_name
                user.last_name = last_name

            return user

    async def get_user_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID."""
        async with self.session() as session:
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            return result.scalar_one_or_none()

    async def update_user_model(self, telegram_id: int, model: str) -> None:
        """Update user's selected model."""
        async with self.session() as session:
            await session.execute(
                update(User).where(User.telegram_id == telegram_id).values(selected_model=model)
            )

    async def ban_user(self, telegram_id: int) -> bool:
        """Ban a user."""
        async with self.session() as session:
            result = await session.execute(
                update(User).where(User.telegram_id == telegram_id).values(is_banned=True)
            )
            return result.rowcount > 0

    async def unban_user(self, telegram_id: int) -> bool:
        """Unban a user."""
        async with self.session() as session:
            result = await session.execute(
                update(User).where(User.telegram_id == telegram_id).values(is_banned=False)
            )
            return result.rowcount > 0

    async def increment_user_messages(self, telegram_id: int) -> None:
        """Increment user's total message count."""
        async with self.session() as session:
            await session.execute(
                update(User)
                .where(User.telegram_id == telegram_id)
                .values(total_messages=User.total_messages + 1)
            )

    async def get_all_users(self) -> List[User]:
        """Get all users."""
        async with self.session() as session:
            result = await session.execute(select(User))
            return list(result.scalars().all())

    async def get_user_stats(self) -> dict:
        """Get user statistics."""
        async with self.session() as session:
            total_users = await session.execute(select(func.count(User.id)))
            active_users = await session.execute(
                select(func.count(User.id)).where(User.is_banned == False)
            )
            total_messages = await session.execute(select(func.sum(User.total_messages)))

            return {
                "total_users": total_users.scalar() or 0,
                "active_users": active_users.scalar() or 0,
                "total_messages": total_messages.scalar() or 0,
            }

    # Conversation operations
    async def get_or_create_active_conversation(self, telegram_id: int) -> Conversation:
        """Get active conversation or create new one."""
        async with self.session() as session:
            # Get user
            user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_result.scalar_one_or_none()

            if user is None:
                raise ValueError(f"User with telegram_id {telegram_id} not found")

            # Get active conversation
            conv_result = await session.execute(
                select(Conversation)
                .where(Conversation.user_id == user.id, Conversation.is_active == True)
                .options(selectinload(Conversation.messages))
            )
            conversation = conv_result.scalar_one_or_none()

            if conversation is None:
                conversation = Conversation(user_id=user.id, is_active=True)
                session.add(conversation)
                await session.flush()
                logger.info(f"Created new conversation for user {telegram_id}")

            return conversation

    async def end_conversation(self, telegram_id: int) -> None:
        """End active conversation for user."""
        async with self.session() as session:
            user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_result.scalar_one_or_none()

            if user:
                await session.execute(
                    update(Conversation)
                    .where(Conversation.user_id == user.id, Conversation.is_active == True)
                    .values(is_active=False, ended_at=datetime.utcnow())
                )

    # Message operations
    async def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        tokens_used: Optional[int] = None,
        model_used: Optional[str] = None,
    ) -> Message:
        """Add message to conversation."""
        async with self.session() as session:
            message = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                tokens_used=tokens_used,
                model_used=model_used,
            )
            session.add(message)
            await session.flush()
            return message

    async def get_conversation_messages(
        self, conversation_id: int, limit: Optional[int] = None
    ) -> List[Message]:
        """Get messages for conversation."""
        async with self.session() as session:
            query = (
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
            )

            if limit:
                query = query.limit(limit)

            result = await session.execute(query)
            messages = list(result.scalars().all())
            return list(reversed(messages))  # Return in chronological order

    async def get_user_usage_stats(self, telegram_id: int) -> dict:
        """Get usage statistics for a user."""
        async with self.session() as session:
            user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_result.scalar_one_or_none()

            if not user:
                return {"total_messages": 0, "conversations": 0}

            conv_count = await session.execute(
                select(func.count(Conversation.id)).where(Conversation.user_id == user.id)
            )

            return {
                "total_messages": user.total_messages,
                "conversations": conv_count.scalar() or 0,
                "selected_model": user.selected_model,
                "member_since": user.created_at.isoformat() if user.created_at else None,
            }


# Global repository instance
_repository: Optional[Repository] = None


async def get_repository() -> Repository:
    """Get or create repository instance."""
    global _repository
    if _repository is None:
        settings = get_settings()
        _repository = Repository(settings.database_url)
        await _repository.init_db()
    return _repository


async def close_repository() -> None:
    """Close repository connections."""
    global _repository
    if _repository is not None:
        await _repository.close()
        _repository = None

