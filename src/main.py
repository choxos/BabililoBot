"""Main entry point for BabililoBot."""

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler as TelegramCommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from src.config import get_settings
from src.database.repository import Repository, close_repository
from src.services.openrouter import OpenRouterClient, close_openrouter_client
from src.services.conversation import ConversationManager
from src.bot.handlers.chat import ChatHandler
from src.bot.handlers.commands import CommandHandler
from src.bot.handlers.admin import AdminHandler
from src.bot.middleware.rate_limit import RateLimiter

# Global instances
repository = None
openrouter_client = None
rate_limiter = None
conversation_manager = None
command_handler = None
chat_handler = None
admin_handler = None


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

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


async def post_init(application: Application) -> None:
    """Initialize resources after application starts."""
    global repository, openrouter_client, rate_limiter, conversation_manager
    global command_handler, chat_handler, admin_handler

    logger = logging.getLogger(__name__)
    logger.info("Initializing BabililoBot...")

    settings = get_settings()

    # Initialize database
    repository = Repository(settings.database_url)
    await repository.init_db()
    logger.info("Database initialized")

    # Initialize services
    openrouter_client = OpenRouterClient()
    rate_limiter = RateLimiter()
    conversation_manager = ConversationManager(repository)

    # Create handlers
    command_handler = CommandHandler(repository, conversation_manager)
    chat_handler = ChatHandler(
        repository, conversation_manager, openrouter_client, rate_limiter
    )
    admin_handler = AdminHandler(repository, rate_limiter)

    # Register handlers
    application.add_handler(
        TelegramCommandHandler("start", command_handler.start_command)
    )
    application.add_handler(
        TelegramCommandHandler("help", command_handler.help_command)
    )
    application.add_handler(
        TelegramCommandHandler("model", command_handler.model_command)
    )
    application.add_handler(
        TelegramCommandHandler("clear", command_handler.clear_command)
    )
    application.add_handler(
        TelegramCommandHandler("usage", command_handler.usage_command)
    )

    # Admin commands
    application.add_handler(
        TelegramCommandHandler("stats", admin_handler.stats_command)
    )
    application.add_handler(
        TelegramCommandHandler("broadcast", admin_handler.broadcast_command)
    )
    application.add_handler(
        TelegramCommandHandler("ban", admin_handler.ban_command)
    )
    application.add_handler(
        TelegramCommandHandler("unban", admin_handler.unban_command)
    )
    application.add_handler(
        TelegramCommandHandler("users", admin_handler.users_command)
    )

    # Callback query handler for model selection
    application.add_handler(
        CallbackQueryHandler(command_handler.model_callback, pattern="^model:")
    )

    # Message handler (must be last)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            chat_handler.handle_message,
        )
    )

    logger.info("Handlers registered")


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

    # Create application
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Start the bot
    logger.info("Bot is running. Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

