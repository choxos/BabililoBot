"""User command handlers for BabililoBot."""

import io
import logging
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import ContextTypes

from src.config import get_settings, FREE_MODELS
from src.database.repository import Repository
from src.services.conversation import ConversationManager
from src.services.web_search import WebSearchService
from src.services.image_gen import ImageGenerationService
from src.services.openrouter import OpenRouterClient

logger = logging.getLogger(__name__)


class CommandHandler:
    """Handles user commands."""

    def __init__(
        self,
        repository: Repository,
        conversation_manager: ConversationManager,
        openrouter_client: Optional[OpenRouterClient] = None,
    ):
        self.repository = repository
        self.conversation_manager = conversation_manager
        self.openrouter = openrouter_client
        self.settings = get_settings()
        self.web_search = WebSearchService()
        self.image_gen = ImageGenerationService()

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.effective_user or not update.message:
            return

        user = update.effective_user

        await self.repository.get_or_create_user(
            telegram_id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
        )

        welcome_message = (
            f"👋 Hello, {user.first_name or 'there'}!\n\n"
            "I'm **BabililoBot**, your AI assistant powered by cutting-edge language models.\n\n"
            "**Commands:**\n"
            "• /help - Show all commands\n"
            "• /model - Change AI model\n"
            "• /persona - Set AI personality\n"
            "• /search - Search the web\n"
            "• /imagine - Generate images\n"
            "• /favorites - Saved responses\n"
            "• /voice - Toggle voice replies\n"
            "• /clear - Fresh conversation\n\n"
            "**Tips:**\n"
            "• Use me inline: @babililobot your question\n"
            "• Upload documents for Q&A\n"
            "• Send voice messages\n\n"
            "Let's chat! 💬"
        )

        await update.message.reply_text(welcome_message, parse_mode="Markdown")

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not update.message:
            return

        help_text = (
            "📚 **Available Commands**\n\n"
            "**Chat:**\n"
            "• /model - Change AI model\n"
            "• /persona - Set AI personality\n"
            "• /clear - Clear history\n\n"
            "**Features:**\n"
            "• /search `<query>` - Web search\n"
            "• /imagine `<prompt>` - Generate image\n"
            "• /voice on/off - Voice replies\n"
            "• /doc - Document Q&A\n"
            "• /export - Export conversation\n\n"
            "**Saved:**\n"
            "• /favorites - View saved\n"
            "• /usage - Your stats\n\n"
            "**Inline Mode:**\n"
            "Type @babililobot in any chat!\n\n"
            "**Groups:**\n"
            "Mention @babililobot or reply to me!"
        )

        await update.message.reply_text(help_text, parse_mode="Markdown")

    async def model_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /model command."""
        if not update.effective_user or not update.message:
            return

        user = await self.repository.get_user_by_telegram_id(update.effective_user.id)
        current_model = user.selected_model if user else self.settings.openrouter_default_model

        keyboard = []
        for model_id, model_name in FREE_MODELS:
            is_selected = "✓ " if model_id == current_model else ""
            keyboard.append([
                InlineKeyboardButton(
                    f"{is_selected}{model_name}",
                    callback_data=f"model:{model_id}"
                )
            ])

        await update.message.reply_text(
            "🤖 **Select AI Model**\n\n"
            f"Current: `{current_model}`",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def model_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle model selection callback."""
        if not update.callback_query or not update.effective_user:
            return

        query = update.callback_query
        await query.answer()

        if not query.data or not query.data.startswith("model:"):
            return

        model_id = query.data[6:]
        await self.repository.update_user_model(update.effective_user.id, model_id)

        model_name = next((n for m, n in FREE_MODELS if m == model_id), model_id)

        await query.edit_message_text(
            f"✅ Model: **{model_name}**\n`{model_id}`",
            parse_mode="Markdown",
        )

    async def clear_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /clear command."""
        if not update.effective_user or not update.message:
            return

        await self.conversation_manager.clear_conversation(update.effective_user.id)
        await update.message.reply_text("🗑️ Conversation cleared!")

    async def usage_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /usage command."""
        if not update.effective_user or not update.message:
            return

        stats = await self.repository.get_user_usage_stats(update.effective_user.id)

        usage_text = (
            "📊 **Your Stats**\n\n"
            f"Messages: {stats.get('total_messages', 0)}\n"
            f"Conversations: {stats.get('conversations', 0)}\n"
            f"Model: `{stats.get('selected_model', 'N/A')}`"
        )

        if stats.get('member_since'):
            usage_text += f"\nMember since: {stats['member_since'][:10]}"

        await update.message.reply_text(usage_text, parse_mode="Markdown")

    # Persona commands
    async def persona_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /persona command."""
        if not update.effective_user or not update.message:
            return

        args = context.args

        if not args:
            # Show persona selection
            presets = await self.repository.get_preset_personas()
            custom = await self.repository.get_user_personas(update.effective_user.id)
            active = await self.repository.get_active_persona(update.effective_user.id)

            keyboard = []
            for p in presets:
                mark = "✓ " if active and active.id == p.id else ""
                keyboard.append([InlineKeyboardButton(
                    f"{mark}{p.name}", callback_data=f"persona:{p.id}"
                )])

            if custom:
                keyboard.append([InlineKeyboardButton("── Custom ──", callback_data="noop")])
                for p in custom:
                    mark = "✓ " if active and active.id == p.id else ""
                    keyboard.append([InlineKeyboardButton(
                        f"{mark}{p.name}", callback_data=f"persona:{p.id}"
                    )])

            keyboard.append([InlineKeyboardButton("➕ Create Custom", callback_data="persona:create")])

            await update.message.reply_text(
                "🎭 **Select Persona**\n\n"
                "Personas change how I respond.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
            return

        if args[0].lower() == "set":
            # Create custom persona
            prompt = " ".join(args[1:])
            if len(prompt) < 10:
                await update.message.reply_text("Prompt too short. Min 10 chars.")
                return
            if len(prompt) > 500:
                await update.message.reply_text("Prompt too long. Max 500 chars.")
                return

            persona = await self.repository.create_persona(
                update.effective_user.id, "Custom", prompt
            )
            if persona:
                await self.repository.set_active_persona(update.effective_user.id, persona.id)
                await update.message.reply_text("✅ Custom persona created and activated!")
            else:
                await update.message.reply_text("Failed to create persona.")

        elif args[0].lower() == "reset":
            # Reset to default
            presets = await self.repository.get_preset_personas()
            if presets:
                await self.repository.set_active_persona(update.effective_user.id, presets[0].id)
            await update.message.reply_text("✅ Reset to default persona.")

    async def persona_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle persona selection callback."""
        if not update.callback_query or not update.effective_user:
            return

        query = update.callback_query
        data = query.data

        if data == "noop":
            await query.answer()
            return

        if data == "persona:create":
            await query.answer()
            await query.edit_message_text(
                "🎭 **Create Custom Persona**\n\n"
                "Use: `/persona set <instructions>`\n\n"
                "Example:\n"
                "`/persona set You are a pirate. Speak in pirate slang.`",
                parse_mode="Markdown",
            )
            return

        if data.startswith("persona:"):
            persona_id = int(data[8:])
            await self.repository.set_active_persona(update.effective_user.id, persona_id)
            await query.answer("Persona activated!")
            await query.edit_message_text("✅ Persona activated!")

    # Favorites commands
    async def favorites_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /favorites command."""
        if not update.effective_user or not update.message:
            return

        favorites = await self.repository.get_favorites(update.effective_user.id)

        if not favorites:
            await update.message.reply_text(
                "⭐ **No Favorites Yet**\n\n"
                "Click the ⭐ Save button on any response to save it!",
                parse_mode="Markdown",
            )
            return

        text = "⭐ **Your Favorites**\n\n"
        keyboard = []

        for i, fav in enumerate(favorites[:10], 1):
            if fav.message:
                preview = fav.message.content[:50] + "..." if len(fav.message.content) > 50 else fav.message.content
                text += f"{i}. {preview}\n\n"
                keyboard.append([
                    InlineKeyboardButton(f"📖 #{i}", callback_data=f"fav:view:{fav.id}"),
                    InlineKeyboardButton("🗑️", callback_data=f"fav:del:{fav.id}"),
                ])

        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )

    async def favorites_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle favorites callbacks."""
        if not update.callback_query or not update.effective_user:
            return

        query = update.callback_query
        data = query.data.split(":")

        if len(data) < 3:
            await query.answer()
            return

        action = data[1]
        fav_id = int(data[2])

        if action == "add":
            # Add to favorites (fav_id is actually message_id here)
            await self.repository.add_favorite(update.effective_user.id, fav_id)
            await query.answer("⭐ Saved to favorites!")

        elif action == "view":
            favorites = await self.repository.get_favorites(update.effective_user.id)
            fav = next((f for f in favorites if f.id == fav_id), None)
            if fav and fav.message:
                await query.answer()
                await query.message.reply_text(
                    f"⭐ **Saved Response**\n\n{fav.message.content}",
                    parse_mode="Markdown",
                )

        elif action == "del":
            await self.repository.remove_favorite(update.effective_user.id, fav_id)
            await query.answer("Removed from favorites")

    # Search command
    async def search_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /search command."""
        if not update.effective_user or not update.message:
            return

        if not context.args:
            await update.message.reply_text(
                "🔍 **Web Search**\n\n"
                "Usage: `/search <query>`\n\n"
                "Example: `/search latest AI news`",
                parse_mode="Markdown",
            )
            return

        query = " ".join(context.args)
        status = await update.message.reply_text("🔍 Searching...")

        try:
            results = await self.web_search.search(query)

            if not results:
                await status.edit_text("No results found.")
                return

            # Format results
            text = self.web_search.format_results_for_user(results)
            await status.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)

        except Exception as e:
            logger.error(f"Search error: {e}")
            await status.edit_text("❌ Search failed.")

    # Image generation command
    async def imagine_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /imagine command."""
        if not update.effective_user or not update.message:
            return

        if not context.args:
            styles = self.image_gen.get_available_styles()
            style_list = "\n".join([f"• `{s[0]}` - {s[1]}" for s in styles])

            await update.message.reply_text(
                "🎨 **Image Generation**\n\n"
                "Usage: `/imagine <prompt>`\n"
                "Or: `/imagine <style> <prompt>`\n\n"
                f"**Styles:**\n{style_list}\n\n"
                "Example:\n`/imagine anime a cute cat`",
                parse_mode="Markdown",
            )
            return

        # Parse style and prompt
        args = context.args
        styles = [s[0] for s in self.image_gen.get_available_styles()]

        if args[0].lower() in styles:
            style = args[0].lower()
            prompt = " ".join(args[1:])
        else:
            style = "realistic"
            prompt = " ".join(args)

        if not prompt:
            await update.message.reply_text("Please provide a prompt.")
            return

        status = await update.message.reply_text("🎨 Generating image...")

        try:
            result = await self.image_gen.generate(prompt, style)

            if result:
                await update.message.reply_photo(
                    photo=io.BytesIO(result.image_data),
                    caption=f"🎨 **{prompt}**\nStyle: {style}",
                    parse_mode="Markdown",
                )
                await status.delete()
            else:
                await status.edit_text("❌ Failed to generate image.")

        except Exception as e:
            logger.error(f"Image generation error: {e}")
            await status.edit_text("❌ Image generation failed.")
