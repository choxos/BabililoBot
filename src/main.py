"""Main entry point for BabililoBot."""

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler as TelegramCommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ChosenInlineResultHandler,
    filters,
)

from src.config import get_settings
from src.database.repository import Repository
from src.services.openrouter import OpenRouterClient
from src.services.conversation import ConversationManager
from src.bot.handlers.chat import ChatHandler
from src.bot.handlers.commands import CommandHandler
from src.bot.handlers.admin import AdminHandler
from src.bot.handlers.inline import InlineHandler
from src.bot.handlers.export import ExportHandler
from src.bot.handlers.voice import VoiceHandler
from src.bot.handlers.documents import DocumentHandler
from src.bot.handlers.groups import GroupHandler
from src.bot.middleware.rate_limit import RateLimiter

# Global instances
repository = None
openrouter_client = None
rate_limiter = None
conversation_manager = None


def setup_logging() -> None:
    """Configure logging for the application."""
    settings = get_settings()

    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


async def post_init(application: Application) -> None:
    """Initialize resources after application starts."""
    global repository, openrouter_client, rate_limiter, conversation_manager

    logger = logging.getLogger(__name__)
    logger.info("Initializing BabililoBot...")

    settings = get_settings()

    # Initialize core services
    repository = Repository(settings.database_url)
    await repository.init_db()
    logger.info("Database initialized")

    openrouter_client = OpenRouterClient()
    rate_limiter = RateLimiter()
    conversation_manager = ConversationManager(repository)

    # Create handlers
    command_handler = CommandHandler(repository, conversation_manager, openrouter_client)
    chat_handler = ChatHandler(repository, conversation_manager, openrouter_client, rate_limiter)
    admin_handler = AdminHandler(repository, rate_limiter)
    inline_handler = InlineHandler(repository, openrouter_client)
    export_handler = ExportHandler(repository)
    voice_handler = VoiceHandler(repository, openrouter_client, conversation_manager)
    document_handler = DocumentHandler(repository, openrouter_client, conversation_manager)
    group_handler = GroupHandler(repository, openrouter_client, conversation_manager, rate_limiter)

    # Store handlers in bot_data for access in callbacks
    application.bot_data["chat_handler"] = chat_handler
    application.bot_data["document_handler"] = document_handler

    # ===== Command Handlers =====
    # Basic commands
    application.add_handler(TelegramCommandHandler("start", command_handler.start_command))
    application.add_handler(TelegramCommandHandler("help", command_handler.help_command))
    application.add_handler(TelegramCommandHandler("model", command_handler.model_command))
    application.add_handler(TelegramCommandHandler("clear", command_handler.clear_command))
    application.add_handler(TelegramCommandHandler("usage", command_handler.usage_command))

    # Feature commands
    application.add_handler(TelegramCommandHandler("persona", command_handler.persona_command))
    application.add_handler(TelegramCommandHandler("favorites", command_handler.favorites_command))
    application.add_handler(TelegramCommandHandler("search", command_handler.search_command))
    application.add_handler(TelegramCommandHandler("imagine", command_handler.imagine_command))
    application.add_handler(TelegramCommandHandler("voice", voice_handler.handle_voice_toggle))
    application.add_handler(TelegramCommandHandler("doc", document_handler.doc_command))
    application.add_handler(TelegramCommandHandler("export", export_handler.export_command))

    # Admin commands
    application.add_handler(TelegramCommandHandler("stats", admin_handler.stats_command))
    application.add_handler(TelegramCommandHandler("broadcast", admin_handler.broadcast_command))
    application.add_handler(TelegramCommandHandler("ban", admin_handler.ban_command))
    application.add_handler(TelegramCommandHandler("unban", admin_handler.unban_command))
    application.add_handler(TelegramCommandHandler("users", admin_handler.users_command))

    # Group commands
    application.add_handler(TelegramCommandHandler("groupsettings", group_handler.group_settings_command))

    # ===== Callback Query Handlers =====
    application.add_handler(CallbackQueryHandler(command_handler.model_callback, pattern="^model:"))
    application.add_handler(CallbackQueryHandler(command_handler.model_callback, pattern="^modelcat:"))
    application.add_handler(CallbackQueryHandler(command_handler.persona_callback, pattern="^persona:"))
    application.add_handler(CallbackQueryHandler(command_handler.favorites_callback, pattern="^fav:"))
    application.add_handler(CallbackQueryHandler(export_handler.handle_export_callback, pattern="^export:"))
    application.add_handler(CallbackQueryHandler(voice_handler.handle_voice_callback, pattern="^voice:"))
    application.add_handler(CallbackQueryHandler(
        lambda u, c: chat_handler.handle_regenerate(u, c), pattern="^regen:"
    ))

    # ===== Inline Query Handler =====
    application.add_handler(InlineQueryHandler(inline_handler.handle_inline_query))
    application.add_handler(ChosenInlineResultHandler(inline_handler.handle_chosen_inline_result))

    # ===== Message Handlers =====
    # Voice messages
    application.add_handler(MessageHandler(filters.VOICE, voice_handler.handle_voice_message))

    # Document uploads
    application.add_handler(MessageHandler(filters.Document.ALL, document_handler.handle_document))

    # Group messages (check if mentioned)
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS,
        group_handler.handle_group_message,
    ))

    # Regular text messages (DM) - must be last
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        chat_handler.handle_message,
    ))

    logger.info("All handlers registered")


async def post_shutdown(application: Application) -> None:
    """Cleanup resources on shutdown."""
    global repository, openrouter_client

    logger = logging.getLogger(__name__)
    logger.info("Shutting down BabililoBot...")

    if repository:
        await repository.close()
    if openrouter_client:
        await openrouter_client.close()

    logger.info("Cleanup complete")


def main() -> None:
    """Run the bot."""
    setup_logging()
    logger = logging.getLogger(__name__)

    settings = get_settings()

    logger.info("Starting BabililoBot...")
    logger.info(f"Default model: {settings.openrouter_default_model}")
    logger.info(f"Admin IDs: {settings.admin_ids}")

    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    logger.info("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
