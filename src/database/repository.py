"""Database repository for CRUD operations."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, List, Optional

from sqlalchemy import select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.database.models import Base, Conversation, Message, User, Persona, Favorite, GroupSettings, Document

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
        # Initialize preset personas
        await self._init_preset_personas()

    async def _init_preset_personas(self) -> None:
        """Initialize preset personas."""
        presets = [
            ("Default", "You are BabililoBot, a helpful, friendly AI assistant."),
            ("Coder", "You are an expert programmer. Provide clean, well-documented code with explanations. Focus on best practices and efficiency."),
            ("Writer", "You are a creative writer. Help with storytelling, editing, and crafting compelling narratives."),
            ("Tutor", "You are a patient teacher. Explain concepts clearly with examples, adapting to the student's level."),
            ("Analyst", "You are a data analyst. Provide structured, logical analysis with clear insights and recommendations."),
            ("Translator", "You are a multilingual translator. Provide accurate translations while preserving meaning and context."),
        ]
        async with self.session() as session:
            for name, prompt in presets:
                existing = await session.execute(
                    select(Persona).where(Persona.name == name, Persona.is_preset == True)
                )
                if not existing.scalar_one_or_none():
                    persona = Persona(name=name, system_prompt=prompt, is_preset=True)
                    session.add(persona)

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

    async def update_user_voice(self, telegram_id: int, enabled: bool) -> None:
        """Update user's voice setting."""
        async with self.session() as session:
            await session.execute(
                update(User).where(User.telegram_id == telegram_id).values(voice_enabled=enabled)
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
    async def get_or_create_active_conversation(
        self, telegram_id: int, group_id: Optional[int] = None
    ) -> Conversation:
        """Get active conversation or create new one."""
        async with self.session() as session:
            user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_result.scalar_one_or_none()

            if user is None:
                raise ValueError(f"User with telegram_id {telegram_id} not found")

            # Get active conversation (for group or DM)
            query = select(Conversation).where(
                Conversation.user_id == user.id,
                Conversation.is_active == True
            )
            if group_id:
                query = query.where(Conversation.group_id == group_id)
            else:
                query = query.where(Conversation.group_id.is_(None))

            conv_result = await session.execute(query.options(selectinload(Conversation.messages)))
            conversation = conv_result.scalar_one_or_none()

            if conversation is None:
                conversation = Conversation(user_id=user.id, is_active=True, group_id=group_id)
                session.add(conversation)
                await session.flush()
                logger.info(f"Created new conversation for user {telegram_id}")

            return conversation

    async def end_conversation(self, telegram_id: int, group_id: Optional[int] = None) -> None:
        """End active conversation for user."""
        async with self.session() as session:
            user_result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user_result.scalar_one_or_none()

            if user:
                query = update(Conversation).where(
                    Conversation.user_id == user.id,
                    Conversation.is_active == True
                )
                if group_id:
                    query = query.where(Conversation.group_id == group_id)
                else:
                    query = query.where(Conversation.group_id.is_(None))

                await session.execute(query.values(is_active=False, ended_at=datetime.utcnow()))

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

    async def get_message_by_id(self, message_id: int) -> Optional[Message]:
        """Get message by ID."""
        async with self.session() as session:
            result = await session.execute(select(Message).where(Message.id == message_id))
            return result.scalar_one_or_none()

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
            return list(reversed(messages))

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

    # Persona operations
    async def get_preset_personas(self) -> List[Persona]:
        """Get all preset personas."""
        async with self.session() as session:
            result = await session.execute(select(Persona).where(Persona.is_preset == True))
            return list(result.scalars().all())

    async def get_user_personas(self, telegram_id: int) -> List[Persona]:
        """Get user's custom personas."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return []
            result = await session.execute(
                select(Persona).where(Persona.user_id == user.id)
            )
            return list(result.scalars().all())

    async def get_active_persona(self, telegram_id: int) -> Optional[Persona]:
        """Get user's active persona."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return None
            result = await session.execute(
                select(Persona).where(
                    ((Persona.user_id == user.id) | (Persona.is_preset == True)),
                    Persona.is_active == True
                )
            )
            return result.scalar_one_or_none()

    async def set_active_persona(self, telegram_id: int, persona_id: int) -> bool:
        """Set user's active persona."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return False

            # Deactivate all personas for user
            await session.execute(
                update(Persona).where(Persona.user_id == user.id).values(is_active=False)
            )

            # Activate selected persona
            await session.execute(
                update(Persona).where(Persona.id == persona_id).values(is_active=True)
            )
            return True

    async def create_persona(
        self, telegram_id: int, name: str, system_prompt: str
    ) -> Optional[Persona]:
        """Create custom persona for user."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return None

            persona = Persona(user_id=user.id, name=name, system_prompt=system_prompt)
            session.add(persona)
            await session.flush()
            return persona

    async def delete_persona(self, telegram_id: int, persona_id: int) -> bool:
        """Delete user's custom persona."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return False

            result = await session.execute(
                delete(Persona).where(
                    Persona.id == persona_id,
                    Persona.user_id == user.id,
                    Persona.is_preset == False
                )
            )
            return result.rowcount > 0

    # Favorites operations
    async def add_favorite(
        self, telegram_id: int, message_id: int, tags: Optional[str] = None
    ) -> Optional[Favorite]:
        """Add message to favorites."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return None

            favorite = Favorite(user_id=user.id, message_id=message_id, tags=tags)
            session.add(favorite)
            await session.flush()
            return favorite

    async def get_favorites(self, telegram_id: int, limit: int = 20) -> List[Favorite]:
        """Get user's favorites."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return []

            result = await session.execute(
                select(Favorite)
                .where(Favorite.user_id == user.id)
                .options(selectinload(Favorite.message))
                .order_by(Favorite.created_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def remove_favorite(self, telegram_id: int, favorite_id: int) -> bool:
        """Remove from favorites."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return False

            result = await session.execute(
                delete(Favorite).where(
                    Favorite.id == favorite_id,
                    Favorite.user_id == user.id
                )
            )
            return result.rowcount > 0

    # Group settings operations
    async def get_or_create_group_settings(
        self, group_id: int, group_name: Optional[str] = None
    ) -> GroupSettings:
        """Get or create group settings."""
        async with self.session() as session:
            result = await session.execute(
                select(GroupSettings).where(GroupSettings.telegram_group_id == group_id)
            )
            settings = result.scalar_one_or_none()

            if settings is None:
                settings = GroupSettings(telegram_group_id=group_id, group_name=group_name)
                session.add(settings)
                await session.flush()

            return settings

    async def update_group_settings(
        self,
        group_id: int,
        is_enabled: Optional[bool] = None,
        rate_limit: Optional[int] = None,
        persona_id: Optional[int] = None,
    ) -> None:
        """Update group settings."""
        async with self.session() as session:
            values = {}
            if is_enabled is not None:
                values["is_enabled"] = is_enabled
            if rate_limit is not None:
                values["rate_limit_messages"] = rate_limit
            if persona_id is not None:
                values["persona_id"] = persona_id

            if values:
                await session.execute(
                    update(GroupSettings)
                    .where(GroupSettings.telegram_group_id == group_id)
                    .values(**values)
                )

    # Document operations
    async def save_document(
        self, user_id: int, filename: str, content: str, file_type: str
    ) -> Document:
        """Save uploaded document."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == user_id))
            user = user.scalar_one_or_none()
            if not user:
                raise ValueError("User not found")

            # Deactivate previous documents
            await session.execute(
                update(Document)
                .where(Document.user_id == user.id)
                .values(is_active=False)
            )

            doc = Document(
                user_id=user.id,
                filename=filename,
                content=content,
                file_type=file_type,
                is_active=True,
            )
            session.add(doc)
            await session.flush()
            return doc

    async def get_active_document(self, telegram_id: int) -> Optional[Document]:
        """Get user's active document."""
        async with self.session() as session:
            user = await session.execute(select(User).where(User.telegram_id == telegram_id))
            user = user.scalar_one_or_none()
            if not user:
                return None

            result = await session.execute(
                select(Document).where(
                    Document.user_id == user.id,
                    Document.is_active == True
                )
            )
            return result.scalar_one_or_none()


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
