"""User command handlers for BabililoBot."""

import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from src.config import get_settings, FREE_MODELS
from src.database.repository import Repository
from src.services.conversation import ConversationManager

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles user commands like /start, /help, /model, /clear."""

    def __init__(self, repository: Repository, conversation_manager: ConversationManager):
        self.repository = repository
        self.conversation_manager = conversation_manager
        self.settings = get_settings()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.effective_user or not update.message:
            return

        user = update.effective_user

        # Register/update user in database
        await self.repository.get_or_create_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )

        welcome_message = (
            f"👋 Hello, {user.first_name or 'there'}!\n\n"
            "I'm **BabililoBot**, your AI assistant powered by cutting-edge language models.\n\n"
            "Just send me a message and I'll respond! Here are some commands:\n\n"
            "• /help - Show all commands\n"
            "• /model - Change AI model\n"
            "• /clear - Start fresh conversation\n"
            "• /usage - View your usage stats\n\n"
            "Let's chat! 💬"
        )

        await update.message.reply_text(welcome_message, parse_mode="Markdown")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not update.message:
            return

        help_text = (
            "📚 **Available Commands**\n\n"
            "**General:**\n"
            "• /start - Start the bot\n"
            "• /help - Show this help message\n"
            "• /model - View or change AI model\n"
            "• /clear - Clear conversation history\n"
            "• /usage - View your usage statistics\n\n"
            "**Tips:**\n"
            "• Just send any message to chat with me\n"
            "• Use /clear to start a fresh conversation\n"
            "• Try different models for different tasks\n\n"
            "Powered by OpenRouter 🚀"
        )

        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def model_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /model command - show model selection."""
        if not update.effective_user or not update.message:
            return

        # Get current model
        user = await self.repository.get_user_by_telegram_id(update.effective_user.id)
        current_model = user.selected_model if user else self.settings.openrouter_default_model

        # Create inline keyboard with model options
        keyboard = []
        for model_id, model_name in FREE_MODELS:
            is_selected = "✓ " if model_id == current_model else ""
            keyboard.append([
                InlineKeyboardButton(
                    f"{is_selected}{model_name}",
                    callback_data=f"model:{model_id}"
                )
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "🤖 **Select AI Model**\n\n"
            f"Current model: `{current_model}`\n\n"
            "Choose a model below:",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def model_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle model selection callback."""
        if not update.callback_query or not update.effective_user:
            return

        query = update.callback_query
        await query.answer()

        # Extract model from callback data
        if not query.data or not query.data.startswith("model:"):
            return

        model_id = query.data[6:]  # Remove "model:" prefix

        # Update user's model
        await self.repository.update_user_model(update.effective_user.id, model_id)

        # Find model name
        model_name = model_id
        for mid, mname in FREE_MODELS:
            if mid == model_id:
                model_name = mname
                break

        await query.edit_message_text(
            f"✅ Model changed to **{model_name}**\n\n"
            f"`{model_id}`\n\n"
            "Your next messages will use this model.",
            parse_mode="Markdown",
        )

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /clear command - clear conversation history."""
        if not update.effective_user or not update.message:
            return

        await self.conversation_manager.clear_conversation(update.effective_user.id)

        await update.message.reply_text(
            "🗑️ Conversation cleared!\n\n"
            "Send me a message to start a new conversation.",
        )

    async def usage_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /usage command - show user statistics."""
        if not update.effective_user or not update.message:
            return

        stats = await self.repository.get_user_usage_stats(update.effective_user.id)

        usage_text = (
            "📊 **Your Usage Statistics**\n\n"
            f"• Total messages: {stats.get('total_messages', 0)}\n"
            f"• Conversations: {stats.get('conversations', 0)}\n"
            f"• Current model: `{stats.get('selected_model', 'N/A')}`\n"
        )

        if stats.get('member_since'):
            usage_text += f"• Member since: {stats['member_since'][:10]}\n"

        await update.message.reply_text(usage_text, parse_mode="Markdown")

