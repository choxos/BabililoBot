"""Chat message handler for BabililoBot."""

import asyncio
import logging
from typing import Optional, Callable, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
from telegram.error import BadRequest

from src.config import get_settings
from src.database.repository import Repository
from src.services.conversation import ConversationManager
from src.services.openrouter import OpenRouterClient, OpenRouterError
from src.bot.middleware.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


class ChatHandler:
    """Handles incoming chat messages with streaming support."""

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

    def _get_response_keyboard(self, message_id: int) -> InlineKeyboardMarkup:
        """Create inline keyboard for response actions."""
        keyboard = [
            [
                InlineKeyboardButton("📄 PDF", callback_data=f"export:pdf:{message_id}"),
                InlineKeyboardButton("📝 TXT", callback_data=f"export:txt:{message_id}"),
                InlineKeyboardButton("⭐ Save", callback_data=f"fav:add:{message_id}"),
            ],
            [
                InlineKeyboardButton("🔊 Voice", callback_data=f"voice:{message_id}"),
                InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen:{message_id}"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    async def handle_message(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        override_text: Optional[str] = None,
    ) -> Optional[Message]:
        """Handle incoming text messages with streaming responses."""
        if not update.effective_user or not update.message:
            return None

        user = update.effective_user
        message_text = override_text or (update.message.text or "").strip()

        # Skip empty messages
        if not message_text:
            return None

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
            return None

        # Check rate limit
        is_admin = user.id in self.settings.admin_ids
        allowed, wait_time = await self.rate_limiter.check_rate_limit(user.id, is_admin)

        if not allowed:
            await update.message.reply_text(
                f"⏳ Rate limit reached. Please wait {wait_time:.0f} seconds."
            )
            return None

        # Send initial "thinking" message
        thinking_msg = await update.message.reply_text("💭 Thinking...")

        try:
            # Build conversation context
            messages = await self.conversation_manager.build_api_messages(
                telegram_id=user.id,
                new_message=message_text,
            )
            messages = await self.conversation_manager.trim_context_if_needed(messages)

            # Stream response with progressive updates
            full_response = await self._stream_response(
                thinking_msg,
                messages,
                db_user.selected_model,
            )

            if full_response:
                # Store messages in database
                await self.conversation_manager.add_user_message(user.id, message_text)
                msg_record = await self.conversation_manager.add_assistant_message(
                    telegram_id=user.id,
                    content=full_response,
                    model_used=db_user.selected_model,
                )

                # Add action buttons
                try:
                    keyboard = self._get_response_keyboard(msg_record.id if msg_record else 0)
                    await thinking_msg.edit_text(
                        full_response,
                        reply_markup=keyboard,
                        parse_mode="Markdown",
                    )
                except BadRequest:
                    # If markdown fails, send without formatting
                    await thinking_msg.edit_text(
                        full_response,
                        reply_markup=keyboard,
                    )

                return thinking_msg

        except OpenRouterError as e:
            logger.error(f"OpenRouter error for user {user.id}: {e.message}")
            error_msg = "❌ Sorry, I encountered an error."
            if e.status_code == 429:
                error_msg = "⏳ AI service rate limited. Try again soon."
            await thinking_msg.edit_text(error_msg)

        except Exception as e:
            logger.exception(f"Unexpected error from user {user.id}")
            await thinking_msg.edit_text("❌ An unexpected error occurred.")

        return None

    async def _stream_response(
        self,
        message: Message,
        messages: list,
        model: str,
    ) -> str:
        """Stream response with progressive message editing."""
        full_content = ""
        last_update = ""
        update_interval = 0.5  # Update every 500ms
        last_update_time = asyncio.get_event_loop().time()

        try:
            async for chunk in self.openrouter.stream_chat_completion(
                messages=messages,
                model=model,
            ):
                full_content += chunk
                current_time = asyncio.get_event_loop().time()

                # Update message at intervals to avoid rate limiting
                if current_time - last_update_time >= update_interval:
                    display_text = full_content + " ▌"  # Cursor indicator

                    # Only update if content changed significantly
                    if len(display_text) - len(last_update) >= 20:
                        try:
                            await message.edit_text(display_text)
                            last_update = display_text
                            last_update_time = current_time
                        except BadRequest as e:
                            if "not modified" not in str(e).lower():
                                logger.warning(f"Edit failed: {e}")

            return full_content

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            # Fallback to non-streaming
            if not full_content:
                response = await self.openrouter.chat_completion(
                    messages=messages,
                    model=model,
                )
                return response.content
            return full_content

    async def handle_regenerate(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """Handle regenerate callback."""
        if not update.callback_query:
            return

        query = update.callback_query
        await query.answer("Regenerating response...")

        # Get the last user message from context
        user_id = update.effective_user.id
        messages = await self.conversation_manager.get_context_messages(user_id)

        if messages and len(messages) >= 2:
            # Find last user message
            last_user_msg = None
            for msg in reversed(messages):
                if msg.role == "user":
                    last_user_msg = msg.content
                    break

            if last_user_msg:
                # Clear last exchange and regenerate
                await self.conversation_manager.clear_conversation(user_id)

                # Create a fake update for regeneration
                class FakeMessage:
                    text = last_user_msg
                    async def reply_text(self, *args, **kwargs):
                        return await query.message.reply_text(*args, **kwargs)

                class FakeUpdate:
                    effective_user = update.effective_user
                    effective_chat = update.effective_chat
                    message = FakeMessage()

                await self.handle_message(FakeUpdate(), context, override_text=last_user_msg)
