"""Chat message handler for BabililoBot."""

import asyncio
import logging
from typing import Optional, List

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

# Telegram message limit
MAX_MESSAGE_LENGTH = 4096


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
                InlineKeyboardButton("📝 MD", callback_data=f"export:md:{message_id}"),
                InlineKeyboardButton("⭐ Save", callback_data=f"fav:add:{message_id}"),
            ],
            [
                InlineKeyboardButton("🔊 Voice", callback_data=f"voice:{message_id}"),
                InlineKeyboardButton("🔄 Regenerate", callback_data=f"regen:{message_id}"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    def _split_message(self, text: str, max_length: int = 4000) -> List[str]:
        """Split a long message into chunks that fit Telegram's limit."""
        if len(text) <= max_length:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_length:
                chunks.append(text)
                break

            # Find a good split point
            split_point = text.rfind("\n\n", 0, max_length)
            if split_point == -1 or split_point < max_length // 2:
                split_point = text.rfind("\n", 0, max_length)
            if split_point == -1 or split_point < max_length // 2:
                split_point = text.rfind(". ", 0, max_length)
            if split_point == -1 or split_point < max_length // 2:
                split_point = text.rfind(" ", 0, max_length)
            if split_point == -1:
                split_point = max_length

            chunks.append(text[:split_point + 1].strip())
            text = text[split_point + 1:].strip()

        return chunks

    async def _send_long_response(
        self,
        update: Update,
        thinking_msg: Message,
        full_response: str,
        keyboard: InlineKeyboardMarkup,
    ) -> None:
        """Send a long response, splitting into multiple messages if needed."""
        chunks = self._split_message(full_response)

        if len(chunks) == 1:
            # Single message - try with markdown first
            try:
                await thinking_msg.edit_text(
                    chunks[0],
                    reply_markup=keyboard,
                    parse_mode="Markdown",
                )
            except BadRequest as e:
                if "too_long" in str(e).lower():
                    # Still too long, split further
                    chunks = self._split_message(full_response, max_length=3500)
                    await self._send_chunked_response(update, thinking_msg, chunks, keyboard)
                else:
                    # Markdown parsing error - try without markdown
                    try:
                        await thinking_msg.edit_text(
                            chunks[0],
                            reply_markup=keyboard,
                        )
                    except BadRequest:
                        # Last resort: split and send plain
                        chunks = self._split_message(full_response, max_length=3500)
                        await self._send_chunked_response(update, thinking_msg, chunks, keyboard)
        else:
            await self._send_chunked_response(update, thinking_msg, chunks, keyboard)

    async def _send_chunked_response(
        self,
        update: Update,
        thinking_msg: Message,
        chunks: List[str],
        keyboard: InlineKeyboardMarkup,
    ) -> None:
        """Send response as multiple messages."""
        for i, chunk in enumerate(chunks):
            is_last = i == len(chunks) - 1
            is_first = i == 0

            # Add part indicator for multi-part responses
            if len(chunks) > 1:
                part_indicator = f"📄 Part {i + 1}/{len(chunks)}\n\n"
                chunk = part_indicator + chunk

            try:
                if is_first:
                    # Edit the thinking message for the first chunk
                    try:
                        await thinking_msg.edit_text(chunk, parse_mode="Markdown")
                    except BadRequest:
                        await thinking_msg.edit_text(chunk)
                else:
                    # Send new messages for subsequent chunks
                    try:
                        if is_last:
                            await update.message.reply_text(
                                chunk,
                                reply_markup=keyboard,
                                parse_mode="Markdown",
                            )
                        else:
                            await update.message.reply_text(chunk, parse_mode="Markdown")
                    except BadRequest:
                        if is_last:
                            await update.message.reply_text(chunk, reply_markup=keyboard)
                        else:
                            await update.message.reply_text(chunk)
            except Exception as e:
                logger.error(f"Error sending chunk {i + 1}: {e}")

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

        if not message_text:
            return None

        db_user = await self.repository.get_or_create_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )

        if db_user.is_banned:
            await update.message.reply_text("⛔ You have been banned from using this bot.")
            return None

        is_admin = user.id in self.settings.admin_ids
        allowed, wait_time = await self.rate_limiter.check_rate_limit(user.id, is_admin)

        if not allowed:
            await update.message.reply_text(
                f"⏳ Rate limit reached. Please wait {wait_time:.0f} seconds."
            )
            return None

        thinking_msg = await update.message.reply_text("💭 Thinking...")

        try:
            messages = await self.conversation_manager.build_api_messages(
                telegram_id=user.id,
                new_message=message_text,
            )
            messages = await self.conversation_manager.trim_context_if_needed(messages)

            full_response = await self._stream_response(
                thinking_msg,
                messages,
                db_user.selected_model,
            )

            if full_response:
                await self.conversation_manager.add_user_message(user.id, message_text)
                msg_record = await self.conversation_manager.add_assistant_message(
                    telegram_id=user.id,
                    content=full_response,
                    model_used=db_user.selected_model,
                )

                keyboard = self._get_response_keyboard(msg_record.id if msg_record else 0)
                
                # Handle long responses
                await self._send_long_response(update, thinking_msg, full_response, keyboard)

                return thinking_msg

        except OpenRouterError as e:
            logger.error(f"OpenRouter error for user {user.id}: {e.message}")
            error_msg = "❌ Sorry, I encountered an error."
            if e.status_code == 429:
                error_msg = "⏳ AI service rate limited. Try again soon."
            await thinking_msg.edit_text(error_msg)

        except Exception as e:
            logger.exception(f"Unexpected error from user {user.id}")
            try:
                await thinking_msg.edit_text("❌ An unexpected error occurred.")
            except:
                pass

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
        update_interval = 0.5
        last_update_time = asyncio.get_event_loop().time()

        try:
            async for chunk in self.openrouter.stream_chat_completion(
                messages=messages,
                model=model,
            ):
                full_content += chunk
                current_time = asyncio.get_event_loop().time()

                # Update message at intervals (only for first 3500 chars to avoid issues)
                if current_time - last_update_time >= update_interval and len(full_content) < 3500:
                    display_text = full_content + " ▌"

                    if len(display_text) - len(last_update) >= 20:
                        try:
                            await message.edit_text(display_text)
                            last_update = display_text
                            last_update_time = current_time
                        except BadRequest as e:
                            if "not modified" not in str(e).lower():
                                pass  # Ignore edit errors during streaming

            return full_content

        except Exception as e:
            logger.error(f"Streaming error: {e}")
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

        user_id = update.effective_user.id
        messages = await self.conversation_manager.get_context_messages(user_id)

        if messages and len(messages) >= 2:
            last_user_msg = None
            for msg in reversed(messages):
                if msg.role == "user":
                    last_user_msg = msg.content
                    break

            if last_user_msg:
                await self.conversation_manager.clear_conversation(user_id)

                class FakeMessage:
                    text = last_user_msg
                    async def reply_text(self, *args, **kwargs):
                        return await query.message.reply_text(*args, **kwargs)

                class FakeUpdate:
                    effective_user = update.effective_user
                    effective_chat = update.effective_chat
                    message = FakeMessage()

                await self.handle_message(FakeUpdate(), context, override_text=last_user_msg)
