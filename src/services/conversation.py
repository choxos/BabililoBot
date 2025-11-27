"""Conversation memory manager for maintaining chat context."""

import logging
from typing import List, Optional

from src.config import get_settings
from src.database.repository import Repository
from src.database.models import Message
from src.services.openrouter import ChatMessage

logger = logging.getLogger(__name__)

# Default system prompt
DEFAULT_SYSTEM_PROMPT = """You are BabililoBot, a helpful, friendly, and intelligent AI assistant. You engage in natural conversations, answer questions accurately, and help users with various tasks. Be concise but thorough in your responses. If you don't know something, say so honestly."""


class ConversationManager:
    """Manages conversation context and memory for chat sessions."""

    def __init__(self, repository: Repository):
        self.repository = repository
        self.settings = get_settings()
        self.context_size = self.settings.conversation_context_size
        self._document_context: dict[int, str] = {}  # user_id -> document content

    def set_document_context(self, user_id: int, content: str) -> None:
        """Set document context for a user."""
        self._document_context[user_id] = content

    def clear_document_context(self, user_id: int) -> None:
        """Clear document context for a user."""
        self._document_context.pop(user_id, None)

    def get_document_context(self, user_id: int) -> Optional[str]:
        """Get document context for a user."""
        return self._document_context.get(user_id)

    async def _get_system_prompt(self, telegram_id: int) -> str:
        """Get system prompt for user (considering active persona)."""
        try:
            persona = await self.repository.get_active_persona(telegram_id)
            if persona:
                return persona.system_prompt
        except Exception as e:
            logger.error(f"Error getting persona: {e}")

        return DEFAULT_SYSTEM_PROMPT

    async def get_context_messages(
        self,
        telegram_id: int,
        include_system: bool = True,
        group_id: Optional[int] = None,
    ) -> List[ChatMessage]:
        """Get conversation context messages for a user."""
        messages: List[ChatMessage] = []

        # Add system prompt
        if include_system:
            system_prompt = await self._get_system_prompt(telegram_id)

            # Add document context if available
            doc_context = self.get_document_context(telegram_id)
            if doc_context:
                system_prompt += f"\n\n[Document Context]\nThe user has uploaded a document. Use this content to answer their questions:\n\n{doc_context[:10000]}"

            messages.append(ChatMessage(role="system", content=system_prompt))

        try:
            conversation = await self.repository.get_or_create_active_conversation(
                telegram_id, group_id=group_id
            )

            db_messages = await self.repository.get_conversation_messages(
                conversation.id, limit=self.context_size
            )

            for msg in db_messages:
                messages.append(ChatMessage(role=msg.role, content=msg.content))

        except Exception as e:
            logger.error(f"Error fetching context for user {telegram_id}: {e}")

        return messages

    async def add_user_message(
        self,
        telegram_id: int,
        content: str,
        group_id: Optional[int] = None,
    ) -> int:
        """Add user message to conversation."""
        conversation = await self.repository.get_or_create_active_conversation(
            telegram_id, group_id=group_id
        )
        await self.repository.add_message(
            conversation_id=conversation.id,
            role="user",
            content=content,
        )
        await self.repository.increment_user_messages(telegram_id)
        return conversation.id

    async def add_assistant_message(
        self,
        telegram_id: int,
        content: str,
        tokens_used: Optional[int] = None,
        model_used: Optional[str] = None,
        group_id: Optional[int] = None,
    ) -> Optional[Message]:
        """Add assistant response to conversation."""
        conversation = await self.repository.get_or_create_active_conversation(
            telegram_id, group_id=group_id
        )
        message = await self.repository.add_message(
            conversation_id=conversation.id,
            role="assistant",
            content=content,
            tokens_used=tokens_used,
            model_used=model_used,
        )
        return message

    async def clear_conversation(
        self, telegram_id: int, group_id: Optional[int] = None
    ) -> None:
        """Clear user's conversation and start fresh."""
        await self.repository.end_conversation(telegram_id, group_id=group_id)
        logger.info(f"Cleared conversation for user {telegram_id}")

    async def build_api_messages(
        self,
        telegram_id: int,
        new_message: str,
        group_id: Optional[int] = None,
    ) -> List[ChatMessage]:
        """Build complete message list for API call."""
        messages = await self.get_context_messages(
            telegram_id, include_system=True, group_id=group_id
        )
        messages.append(ChatMessage(role="user", content=new_message))
        return messages

    def estimate_tokens(self, messages: List[ChatMessage]) -> int:
        """Estimate token count for messages."""
        total_chars = sum(len(m.content) for m in messages)
        return total_chars // 4

    async def trim_context_if_needed(
        self,
        messages: List[ChatMessage],
        max_tokens: int = 4000,
    ) -> List[ChatMessage]:
        """Trim context if it exceeds token limit."""
        estimated = self.estimate_tokens(messages)

        if estimated <= max_tokens:
            return messages

        if len(messages) <= 2:
            return messages

        system_msg = messages[0] if messages[0].role == "system" else None
        other_msgs = messages[1:] if system_msg else messages

        while self.estimate_tokens(messages) > max_tokens and len(other_msgs) > 2:
            other_msgs = other_msgs[1:]
            messages = [system_msg] + other_msgs if system_msg else other_msgs

        return messages
