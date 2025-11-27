"""Conversation memory manager for maintaining chat context."""

import logging
from typing import List, Optional

from src.config import get_settings
from src.database.repository import Repository
from src.services.openrouter import ChatMessage

logger = logging.getLogger(__name__)

# System prompt for the assistant
SYSTEM_PROMPT = """You are BabililoBot, a helpful, friendly, and intelligent AI assistant. You engage in natural conversations, answer questions accurately, and help users with various tasks. Be concise but thorough in your responses. If you don't know something, say so honestly."""


class ConversationManager:
    """Manages conversation context and memory for chat sessions."""

    def __init__(self, repository: Repository):
        self.repository = repository
        self.settings = get_settings()
        self.context_size = self.settings.conversation_context_size

    async def get_context_messages(
        self,
        telegram_id: int,
        include_system: bool = True,
    ) -> List[ChatMessage]:
        """Get conversation context messages for a user.

        Args:
            telegram_id: User's Telegram ID
            include_system: Whether to include system prompt

        Returns:
            List of ChatMessage objects for API context
        """
        messages: List[ChatMessage] = []

        # Add system prompt
        if include_system:
            messages.append(ChatMessage(role="system", content=SYSTEM_PROMPT))

        try:
            # Get active conversation
            conversation = await self.repository.get_or_create_active_conversation(telegram_id)

            # Get recent messages
            db_messages = await self.repository.get_conversation_messages(
                conversation.id, limit=self.context_size
            )

            # Convert to ChatMessage objects
            for msg in db_messages:
                messages.append(ChatMessage(role=msg.role, content=msg.content))

        except Exception as e:
            logger.error(f"Error fetching context for user {telegram_id}: {e}")

        return messages

    async def add_user_message(
        self,
        telegram_id: int,
        content: str,
    ) -> int:
        """Add user message to conversation.

        Args:
            telegram_id: User's Telegram ID
            content: Message content

        Returns:
            Conversation ID
        """
        conversation = await self.repository.get_or_create_active_conversation(telegram_id)
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
    ) -> None:
        """Add assistant response to conversation.

        Args:
            telegram_id: User's Telegram ID
            content: Response content
            tokens_used: Tokens used for this response
            model_used: Model that generated the response
        """
        conversation = await self.repository.get_or_create_active_conversation(telegram_id)
        await self.repository.add_message(
            conversation_id=conversation.id,
            role="assistant",
            content=content,
            tokens_used=tokens_used,
            model_used=model_used,
        )

    async def clear_conversation(self, telegram_id: int) -> None:
        """Clear user's conversation and start fresh.

        Args:
            telegram_id: User's Telegram ID
        """
        await self.repository.end_conversation(telegram_id)
        logger.info(f"Cleared conversation for user {telegram_id}")

    async def build_api_messages(
        self,
        telegram_id: int,
        new_message: str,
    ) -> List[ChatMessage]:
        """Build complete message list for API call.

        This gets the context and appends the new user message.

        Args:
            telegram_id: User's Telegram ID
            new_message: New message from user

        Returns:
            Complete list of messages for API
        """
        # Get existing context
        messages = await self.get_context_messages(telegram_id, include_system=True)

        # Add new user message
        messages.append(ChatMessage(role="user", content=new_message))

        return messages

    def estimate_tokens(self, messages: List[ChatMessage]) -> int:
        """Estimate token count for messages.

        Uses rough estimate of 4 characters per token.

        Args:
            messages: List of messages

        Returns:
            Estimated token count
        """
        total_chars = sum(len(m.content) for m in messages)
        return total_chars // 4

    async def trim_context_if_needed(
        self,
        messages: List[ChatMessage],
        max_tokens: int = 4000,
    ) -> List[ChatMessage]:
        """Trim context if it exceeds token limit.

        Keeps system prompt and most recent messages.

        Args:
            messages: List of messages
            max_tokens: Maximum tokens allowed

        Returns:
            Trimmed message list
        """
        estimated = self.estimate_tokens(messages)

        if estimated <= max_tokens:
            return messages

        # Keep system prompt (first message) and trim from the middle
        if len(messages) <= 2:
            return messages

        system_msg = messages[0] if messages[0].role == "system" else None
        other_msgs = messages[1:] if system_msg else messages

        # Remove oldest messages until under limit
        while self.estimate_tokens(messages) > max_tokens and len(other_msgs) > 2:
            other_msgs = other_msgs[1:]
            messages = [system_msg] + other_msgs if system_msg else other_msgs

        return messages

