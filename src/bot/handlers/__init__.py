"""Handler module for BabililoBot."""

from src.bot.handlers.chat import ChatHandler
from src.bot.handlers.commands import CommandHandler
from src.bot.handlers.admin import AdminHandler

__all__ = ["ChatHandler", "CommandHandler", "AdminHandler"]

