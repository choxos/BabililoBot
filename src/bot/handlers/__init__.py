"""Handler module for BabililoBot."""

from src.bot.handlers.chat import ChatHandler
from src.bot.handlers.commands import CommandHandler
from src.bot.handlers.admin import AdminHandler
from src.bot.handlers.inline import InlineHandler
from src.bot.handlers.export import ExportHandler
from src.bot.handlers.voice import VoiceHandler
from src.bot.handlers.documents import DocumentHandler
from src.bot.handlers.groups import GroupHandler

__all__ = [
    "ChatHandler",
    "CommandHandler",
    "AdminHandler",
    "InlineHandler",
    "ExportHandler",
    "VoiceHandler",
    "DocumentHandler",
    "GroupHandler",
]
