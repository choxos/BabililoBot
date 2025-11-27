"""Chat message handler for BabililoBot."""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

from src.config import get_settings
from src.database.repository import Repository
from src.services.conversation import ConversationManager
from src.services.openrouter import OpenRouterClient, OpenRouterError
from src.bot.middleware.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


class ChatHandler:
    """Handles incoming chat messages."""

    def __init__(
        self,
        repository: Repository,
        conversation_manager: ConversationManager,
        openrouter_client: OpenRouterClient,
        rate_limiter: RateLimiter,
    ):
        self.repository = repository
        self.conversation_manager = conversation_manager
        self.openrouter = openrouter_client
        self.rate_limiter = rate_limiter
        self.settings = get_settings()

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        user = update.effective_user
        message_text = update.message.text.strip()

        # Skip empty messages
        if not message_text:
            return

        # Get or create user
        db_user = await self.repository.get_or_create_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )

        # Check if user is banned
        if db_user.is_banned:
            await update.message.reply_text(
                "⛔ You have been banned from using this bot."
            )
            return

        # Check rate limit
        is_admin = user.id in self.settings.admin_ids
        allowed, wait_time = await self.rate_limiter.check_rate_limit(user.id, is_admin)

        if not allowed:
            await update.message.reply_text(
                f"⏳ Rate limit reached. Please wait {wait_time:.0f} seconds before sending another message."
            )
            return

        # Show typing indicator
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        try:
            # Build conversation context with new message
            messages = await self.conversation_manager.build_api_messages(
                telegram_id=user.id,
                new_message=message_text,
            )

            # Trim context if needed
            messages = await self.conversation_manager.trim_context_if_needed(messages)

            # Get response from OpenRouter
            response = await self.openrouter.chat_completion(
                messages=messages,
                model=db_user.selected_model,
            )

            # Store messages in database
            await self.conversation_manager.add_user_message(user.id, message_text)
            await self.conversation_manager.add_assistant_message(
                telegram_id=user.id,
                content=response.content,
                tokens_used=response.tokens_prompt + response.tokens_completion,
                model_used=response.model,
            )

            # Send response
            await self._send_response(update, response.content)

        except OpenRouterError as e:
            logger.error(f"OpenRouter error for user {user.id}: {e.message}")
            error_msg = "❌ Sorry, I encountered an error processing your request."
            if e.status_code == 429:
                error_msg = "⏳ The AI service is rate limited. Please try again in a moment."
            await update.message.reply_text(error_msg)

        except Exception as e:
            logger.exception(f"Unexpected error handling message from {user.id}")
            await update.message.reply_text(
                "❌ An unexpected error occurred. Please try again later."
            )

    async def _send_response(self, update: Update, content: str) -> None:
        """Send response, handling message length limits.

        Telegram has a 4096 character limit per message.
        """
        if not update.message:
            return

        max_length = 4000  # Leave some buffer

        if len(content) <= max_length:
            await update.message.reply_text(content, parse_mode="Markdown")
            return

        # Split into chunks
        chunks = []
        while content:
            if len(content) <= max_length:
                chunks.append(content)
                break

            # Find a good split point
            split_point = content.rfind("\n\n", 0, max_length)
            if split_point == -1:
                split_point = content.rfind("\n", 0, max_length)
            if split_point == -1:
                split_point = content.rfind(" ", 0, max_length)
            if split_point == -1:
                split_point = max_length

            chunks.append(content[:split_point])
            content = content[split_point:].lstrip()

        # Send chunks
        for i, chunk in enumerate(chunks):
            try:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                # Fallback without markdown if parsing fails
                await update.message.reply_text(chunk)

