"""Document upload and Q&A handler for BabililoBot."""

import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from src.config import get_settings
from src.database.repository import Repository
from src.services.openrouter import OpenRouterClient, ChatMessage
from src.services.conversation import ConversationManager

logger = logging.getLogger(__name__)


class DocumentHandler:
    """Handles document uploads for Q&A."""

    def __init__(
        self,
        repository: Repository,
        openrouter_client: OpenRouterClient,
        conversation_manager: ConversationManager,
    ):
        self.repository = repository
        self.openrouter = openrouter_client
        self.conversation_manager = conversation_manager
        self.settings = get_settings()
        self._user_documents: dict[int, str] = {}  # user_id -> document content

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle document uploads (PDF, DOCX, TXT)."""
        if not update.effective_user or not update.message or not update.message.document:
            return

        user = update.effective_user
        document = update.message.document

        # Check file type
        filename = document.file_name or "document"
        file_ext = Path(filename).suffix.lower()

        if file_ext not in [".pdf", ".docx", ".txt", ".md"]:
            await update.message.reply_text(
                "📄 Supported formats: PDF, DOCX, TXT, MD\n"
                "Please upload a supported document."
            )
            return

        # Check file size (limit to 10MB)
        if document.file_size and document.file_size > 10 * 1024 * 1024:
            await update.message.reply_text(
                "⚠️ File too large. Maximum size is 10MB."
            )
            return

        status_msg = await update.message.reply_text(f"📥 Processing {filename}...")

        try:
            # Download file
            file = await context.bot.get_file(document.file_id)

            with tempfile.NamedTemporaryFile(suffix=file_ext, delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                tmp_path = Path(tmp.name)

            # Extract text based on file type
            text_content = await self._extract_text(tmp_path, file_ext)
            tmp_path.unlink(missing_ok=True)

            if not text_content:
                await status_msg.edit_text("❌ Could not extract text from document.")
                return

            # Store document for user
            self._user_documents[user.id] = text_content

            # Truncate preview
            preview = text_content[:500] + "..." if len(text_content) > 500 else text_content
            word_count = len(text_content.split())

            await status_msg.edit_text(
                f"✅ **Document loaded:** {filename}\n"
                f"📊 Words: {word_count}\n\n"
                f"**Preview:**\n{preview}\n\n"
                "You can now ask questions about this document!\n"
                "Use `/doc clear` to remove it from context.",
                parse_mode="Markdown",
            )

            # Also save to database for persistence
            await self.repository.save_document(
                user_id=user.id,
                filename=filename,
                content=text_content[:50000],  # Limit stored content
                file_type=file_ext,
            )

        except Exception as e:
            logger.error(f"Document processing error: {e}")
            await status_msg.edit_text("❌ Failed to process document.")

    async def _extract_text(self, file_path: Path, file_ext: str) -> Optional[str]:
        """Extract text from document."""
        try:
            if file_ext == ".txt" or file_ext == ".md":
                return file_path.read_text(encoding="utf-8")

            elif file_ext == ".pdf":
                try:
                    from pypdf import PdfReader
                    reader = PdfReader(file_path)
                    text = ""
                    for page in reader.pages:
                        text += page.extract_text() + "\n"
                    return text.strip()
                except ImportError:
                    logger.warning("pypdf not available")
                    return None

            elif file_ext == ".docx":
                try:
                    from docx import Document
                    doc = Document(file_path)
                    text = "\n".join([para.text for para in doc.paragraphs])
                    return text.strip()
                except ImportError:
                    logger.warning("python-docx not available")
                    return None

        except Exception as e:
            logger.error(f"Text extraction error: {e}")
            return None

    def get_document_context(self, user_id: int) -> Optional[str]:
        """Get document context for user."""
        return self._user_documents.get(user_id)

    async def clear_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /doc clear command."""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        if user_id in self._user_documents:
            del self._user_documents[user_id]
            await update.message.reply_text("📄 Document cleared from context.")
        else:
            await update.message.reply_text("No document in context.")

    async def doc_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /doc command."""
        if not update.effective_user or not update.message:
            return

        args = context.args
        user_id = update.effective_user.id

        if not args:
            # Show current document status
            if user_id in self._user_documents:
                doc = self._user_documents[user_id]
                word_count = len(doc.split())
                await update.message.reply_text(
                    f"📄 **Current Document**\n"
                    f"Words: {word_count}\n\n"
                    f"Commands:\n"
                    f"• `/doc clear` - Remove document\n"
                    f"• Upload a new file to replace",
                    parse_mode="Markdown",
                )
            else:
                await update.message.reply_text(
                    "📄 **Document Q&A**\n\n"
                    "Upload a PDF, DOCX, or TXT file and I'll answer questions about it!\n\n"
                    "Supported formats:\n"
                    "• PDF files\n"
                    "• Word documents (.docx)\n"
                    "• Text files (.txt, .md)",
                    parse_mode="Markdown",
                )
            return

        if args[0].lower() == "clear":
            await self.clear_document(update, context)

