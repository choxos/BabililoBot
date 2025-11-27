"""Group chat handler for BabililoBot."""

import logging
from typing import Optional

from telegram import Update, ChatMember
from telegram.ext import ContextTypes
from telegram.constants import ChatAction, ChatType

from src.config import get_settings
from src.database.repository import Repository
from src.services.openrouter import OpenRouterClient
from src.services.conversation import ConversationManager
from src.bot.middleware.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


class GroupHandler:
    """Handles group chat interactions."""

    def __init__(
        self,
        repository: Repository,
        openrouter_client: OpenRouterClient,
        conversation_manager: ConversationManager,
        rate_limiter: RateLimiter,
    ):
        self.repository = repository
        self.openrouter = openrouter_client
        self.conversation_manager = conversation_manager
        self.rate_limiter = rate_limiter
        self.settings = get_settings()

    def _is_group_chat(self, update: Update) -> bool:
        """Check if message is from a group chat."""
        if not update.effective_chat:
            return False
        return update.effective_chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]

    def _is_mentioned(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
        """Check if bot was mentioned or replied to."""
        if not update.message:
            return False

        # Check for direct reply to bot
        if update.message.reply_to_message:
            reply_from = update.message.reply_to_message.from_user
            if reply_from and reply_from.id == context.bot.id:
                return True

        # Check for @mention
        if update.message.entities:
            for entity in update.message.entities:
                if entity.type == "mention":
                    mention_text = update.message.text[entity.offset:entity.offset + entity.length]
                    bot_username = f"@{context.bot.username}"
                    if mention_text.lower() == bot_username.lower():
                        return True

        return False

    async def handle_group_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[bool]:
        """Handle messages in group chats. Returns True if handled."""
        if not self._is_group_chat(update):
            return None

        if not update.effective_user or not update.message or not update.message.text:
            return None

        # Only respond if mentioned or replied to
        if not self._is_mentioned(update, context):
            return False

        user = update.effective_user
        group = update.effective_chat
        message_text = update.message.text.strip()

        # Remove bot mention from message
        bot_mention = f"@{context.bot.username}"
        message_text = message_text.replace(bot_mention, "").strip()

        if not message_text:
            await update.message.reply_text("Yes? How can I help?")
            return True

        # Get or create group settings
        group_settings = await self.repository.get_or_create_group_settings(group.id, group.title)

        if not group_settings.is_enabled:
            return True  # Silently ignore if disabled

        # Check group rate limit (stricter than DM)
        allowed, wait_time = await self.rate_limiter.check_rate_limit(
            group.id,  # Use group ID for rate limiting
            is_admin=False,
        )

        if not allowed:
            await update.message.reply_text(
                f"⏳ Slow down! Wait {wait_time:.0f}s before asking again."
            )
            return True

        # Show typing
        await context.bot.send_chat_action(
            chat_id=group.id,
            action=ChatAction.TYPING,
        )

        try:
            # Get user's model preference
            db_user = await self.repository.get_or_create_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )

            # Build context (use group-specific conversation)
            messages = await self.conversation_manager.build_api_messages(
                telegram_id=user.id,
                new_message=message_text,
                group_id=group.id,
            )

            # Get response
            response = await self.openrouter.chat_completion(
                messages=messages,
                model=db_user.selected_model,
                max_tokens=1024,  # Shorter responses in groups
            )

            # Store in conversation
            await self.conversation_manager.add_user_message(
                user.id, message_text, group_id=group.id
            )
            await self.conversation_manager.add_assistant_message(
                telegram_id=user.id,
                content=response.content,
                model_used=db_user.selected_model,
                group_id=group.id,
            )

            # Reply
            await update.message.reply_text(response.content, parse_mode="Markdown")
            return True

        except Exception as e:
            logger.error(f"Group message error: {e}")
            await update.message.reply_text("❌ Sorry, I couldn't process that.")
            return True

    async def group_settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /groupsettings command (admin only)."""
        if not update.effective_user or not update.message or not update.effective_chat:
            return

        if not self._is_group_chat(update):
            await update.message.reply_text("This command is for group chats only.")
            return

        # Check if user is group admin
        user_id = update.effective_user.id
        chat_member = await context.bot.get_chat_member(update.effective_chat.id, user_id)

        if chat_member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
            await update.message.reply_text("⛔ This command is for group admins only.")
            return

        group = update.effective_chat
        settings = await self.repository.get_or_create_group_settings(group.id, group.title)

        args = context.args

        if not args:
            status = "✅ Enabled" if settings.is_enabled else "❌ Disabled"
            await update.message.reply_text(
                f"⚙️ **Group Settings**\n\n"
                f"Status: {status}\n"
                f"Rate limit: {settings.rate_limit_messages} msgs/min\n\n"
                f"Commands:\n"
                f"• `/groupsettings on` - Enable bot\n"
                f"• `/groupsettings off` - Disable bot\n"
                f"• `/groupsettings limit <n>` - Set rate limit",
                parse_mode="Markdown",
            )
            return

        action = args[0].lower()

        if action == "on":
            await self.repository.update_group_settings(group.id, is_enabled=True)
            await update.message.reply_text("✅ Bot enabled in this group!")

        elif action == "off":
            await self.repository.update_group_settings(group.id, is_enabled=False)
            await update.message.reply_text("❌ Bot disabled in this group.")

        elif action == "limit" and len(args) > 1:
            try:
                limit = int(args[1])
                if 1 <= limit <= 30:
                    await self.repository.update_group_settings(group.id, rate_limit=limit)
                    await update.message.reply_text(f"✅ Rate limit set to {limit} messages per minute.")
                else:
                    await update.message.reply_text("Rate limit must be between 1 and 30.")
            except ValueError:
                await update.message.reply_text("Please provide a valid number.")

        else:
            await update.message.reply_text("Unknown option. Use `/groupsettings` for help.", parse_mode="Markdown")

