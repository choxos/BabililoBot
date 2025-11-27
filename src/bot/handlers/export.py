"""Export handler for PDF/TXT/Markdown generation."""

import io
import logging
from datetime import datetime
from typing import Optional

from telegram import Update, InputFile
from telegram.ext import ContextTypes

from src.database.repository import Repository

logger = logging.getLogger(__name__)


class ExportHandler:
    """Handles exporting messages to PDF, TXT, and Markdown formats."""

    def __init__(self, repository: Repository):
        self.repository = repository

    async def handle_export_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle export button callbacks."""
        if not update.callback_query:
            return

        query = update.callback_query
        await query.answer("Generating file...")

        # Parse callback data: export:format:message_id
        data = query.data.split(":")
        if len(data) != 3:
            return

        _, format_type, message_id = data

        try:
            message_id = int(message_id)
        except ValueError:
            await query.answer("Invalid message ID", show_alert=True)
            return

        # Get the message content from the replied message
        original_message = query.message
        if not original_message or not original_message.text:
            await query.answer("No message to export", show_alert=True)
            return

        content = original_message.text
        user = update.effective_user
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        try:
            if format_type == "pdf":
                await self._export_pdf(query, content, timestamp)
            elif format_type == "txt":
                await self._export_txt(query, content, timestamp)
            elif format_type == "md":
                await self._export_markdown(query, content, timestamp)
            else:
                await query.answer("Unknown format", show_alert=True)

        except Exception as e:
            logger.error(f"Export error: {e}")
            await query.answer("Failed to generate file", show_alert=True)

    async def _export_pdf(self, query, content: str, timestamp: str) -> None:
        """Generate and send PDF file."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.lib.units import inch

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()

            # Create custom style for content
            content_style = ParagraphStyle(
                'Content',
                parent=styles['Normal'],
                fontSize=11,
                leading=14,
                spaceAfter=12,
            )

            # Build document
            story = []

            # Title
            story.append(Paragraph("BabililoBot Response", styles['Heading1']))
            story.append(Spacer(1, 0.25 * inch))
            story.append(Paragraph(f"Generated: {timestamp}", styles['Normal']))
            story.append(Spacer(1, 0.5 * inch))

            # Content - escape special characters and handle newlines
            content_escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            paragraphs = content_escaped.split("\n\n")
            for para in paragraphs:
                if para.strip():
                    # Replace single newlines with <br/>
                    para = para.replace("\n", "<br/>")
                    story.append(Paragraph(para, content_style))
                    story.append(Spacer(1, 0.1 * inch))

            doc.build(story)
            buffer.seek(0)

            await query.message.reply_document(
                document=InputFile(buffer, filename=f"babililo_response_{timestamp}.pdf"),
                caption="📄 Here's your PDF export!",
            )

        except ImportError:
            # Fallback if reportlab not available
            await query.answer("PDF export not available", show_alert=True)

    async def _export_txt(self, query, content: str, timestamp: str) -> None:
        """Generate and send TXT file."""
        header = f"BabililoBot Response\nGenerated: {timestamp}\n{'='*50}\n\n"
        full_content = header + content

        buffer = io.BytesIO(full_content.encode('utf-8'))
        buffer.seek(0)

        await query.message.reply_document(
            document=InputFile(buffer, filename=f"babililo_response_{timestamp}.txt"),
            caption="📝 Here's your TXT export!",
        )

    async def _export_markdown(self, query, content: str, timestamp: str) -> None:
        """Generate and send Markdown file."""
        header = f"# BabililoBot Response\n\n*Generated: {timestamp}*\n\n---\n\n"
        full_content = header + content

        buffer = io.BytesIO(full_content.encode('utf-8'))
        buffer.seek(0)

        await query.message.reply_document(
            document=InputFile(buffer, filename=f"babililo_response_{timestamp}.md"),
            caption="📋 Here's your Markdown export!",
        )

    async def export_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /export command to export conversation history."""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        try:
            # Get user's conversation history
            conversation = await self.repository.get_or_create_active_conversation(user_id)
            messages = await self.repository.get_conversation_messages(conversation.id)

            if not messages:
                await update.message.reply_text("No conversation history to export.")
                return

            # Build conversation text
            content_lines = ["# Conversation History\n"]
            for msg in messages:
                role = "👤 You" if msg.role == "user" else "🤖 BabililoBot"
                timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M") if msg.created_at else ""
                content_lines.append(f"\n## {role} ({timestamp})\n")
                content_lines.append(msg.content + "\n")

            content = "\n".join(content_lines)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

            # Send as markdown file
            buffer = io.BytesIO(content.encode('utf-8'))
            buffer.seek(0)

            await update.message.reply_document(
                document=InputFile(buffer, filename=f"babililo_conversation_{timestamp}.md"),
                caption="📚 Here's your full conversation history!",
            )

        except Exception as e:
            logger.error(f"Export command error: {e}")
            await update.message.reply_text("Failed to export conversation.")

