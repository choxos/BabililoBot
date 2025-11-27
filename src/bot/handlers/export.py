"""Export handler for PDF/Markdown generation."""

import io
import logging
from datetime import datetime
from typing import Optional, Tuple

from telegram import Update, InputFile
from telegram.ext import ContextTypes

from src.database.repository import Repository

logger = logging.getLogger(__name__)


class ExportHandler:
    """Handles exporting messages to PDF and Markdown formats."""

    def __init__(self, repository: Repository):
        self.repository = repository

    async def _get_prompt_and_response(self, message_id: int) -> Tuple[Optional[str], Optional[str]]:
        """Get the user prompt and assistant response for a message.
        
        Returns:
            Tuple of (user_prompt, assistant_response)
        """
        try:
            # Get the assistant message
            message = await self.repository.get_message_by_id(message_id)
            if not message:
                return None, None

            # Get conversation messages to find the preceding user message
            messages = await self.repository.get_conversation_messages(
                message.conversation_id, limit=50
            )

            # Find the user message before this assistant message
            user_prompt = None
            assistant_response = message.content

            for i, msg in enumerate(messages):
                if msg.id == message_id and i > 0:
                    # Look for the user message before this one
                    for j in range(i - 1, -1, -1):
                        if messages[j].role == "user":
                            user_prompt = messages[j].content
                            break
                    break

            return user_prompt, assistant_response
        except Exception as e:
            logger.error(f"Error getting prompt and response: {e}")
            return None, None

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

        # Get prompt and response from database
        user_prompt, assistant_response = await self._get_prompt_and_response(message_id)

        # Fallback to message text if database lookup fails
        if not assistant_response:
            original_message = query.message
            if not original_message or not original_message.text:
                await query.answer("No message to export", show_alert=True)
                return
            assistant_response = original_message.text
            user_prompt = None

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        try:
            if format_type == "pdf":
                await self._export_pdf(query, user_prompt, assistant_response, timestamp)
            elif format_type == "txt":
                # Changed to markdown
                await self._export_markdown(query, user_prompt, assistant_response, timestamp)
            elif format_type == "md":
                await self._export_markdown(query, user_prompt, assistant_response, timestamp)
            else:
                await query.answer("Unknown format", show_alert=True)

        except Exception as e:
            logger.error(f"Export error: {e}")
            await query.answer("Failed to generate file", show_alert=True)

    async def _export_pdf(
        self, query, user_prompt: Optional[str], response: str, timestamp: str
    ) -> None:
        """Generate and send PDF file with prompt and response."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.colors import HexColor
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
            from reportlab.lib.units import inch

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                leftMargin=0.75 * inch,
                rightMargin=0.75 * inch,
                topMargin=0.75 * inch,
                bottomMargin=0.75 * inch,
            )
            styles = getSampleStyleSheet()

            # Custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                spaceAfter=6,
                textColor=HexColor('#2E86AB'),
            )

            prompt_label_style = ParagraphStyle(
                'PromptLabel',
                parent=styles['Heading2'],
                fontSize=12,
                textColor=HexColor('#A23B72'),
                spaceAfter=6,
                spaceBefore=12,
            )

            response_label_style = ParagraphStyle(
                'ResponseLabel',
                parent=styles['Heading2'],
                fontSize=12,
                textColor=HexColor('#2E86AB'),
                spaceAfter=6,
                spaceBefore=12,
            )

            content_style = ParagraphStyle(
                'Content',
                parent=styles['Normal'],
                fontSize=11,
                leading=16,
                spaceAfter=8,
            )

            meta_style = ParagraphStyle(
                'Meta',
                parent=styles['Normal'],
                fontSize=9,
                textColor=HexColor('#666666'),
            )

            # Build document
            story = []

            # Header
            story.append(Paragraph("BabililoBot", title_style))
            story.append(Paragraph(f"Generated: {timestamp.replace('_', ' ')}", meta_style))
            story.append(Spacer(1, 0.3 * inch))
            story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#CCCCCC')))
            story.append(Spacer(1, 0.2 * inch))

            # User Prompt
            if user_prompt:
                story.append(Paragraph("💬 Your Question", prompt_label_style))
                prompt_escaped = user_prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                prompt_escaped = prompt_escaped.replace("\n", "<br/>")
                story.append(Paragraph(prompt_escaped, content_style))
                story.append(Spacer(1, 0.2 * inch))

            # AI Response
            story.append(Paragraph("🤖 AI Response", response_label_style))

            response_escaped = response.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            paragraphs = response_escaped.split("\n\n")
            for para in paragraphs:
                if para.strip():
                    para = para.replace("\n", "<br/>")
                    story.append(Paragraph(para, content_style))

            doc.build(story)
            buffer.seek(0)

            await query.message.reply_document(
                document=InputFile(buffer, filename=f"babililo_{timestamp}.pdf"),
                caption="📄 PDF exported with your prompt and response!",
            )

        except ImportError:
            await query.answer("PDF export not available", show_alert=True)

    async def _export_markdown(
        self, query, user_prompt: Optional[str], response: str, timestamp: str
    ) -> None:
        """Generate and send Markdown file with prompt and response."""
        lines = [
            "# BabililoBot Export",
            "",
            f"*Generated: {timestamp.replace('_', ' ')}*",
            "",
            "---",
            "",
        ]

        if user_prompt:
            lines.extend([
                "## 💬 Your Question",
                "",
                user_prompt,
                "",
            ])

        lines.extend([
            "## 🤖 AI Response",
            "",
            response,
            "",
            "---",
            "",
            "*Powered by BabililoBot - https://t.me/babililobot*",
        ])

        content = "\n".join(lines)
        buffer = io.BytesIO(content.encode('utf-8'))
        buffer.seek(0)

        await query.message.reply_document(
            document=InputFile(buffer, filename=f"babililo_{timestamp}.md"),
            caption="📝 Markdown exported with your prompt and response!",
        )

    async def export_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /export command to export full conversation history."""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id

        try:
            conversation = await self.repository.get_or_create_active_conversation(user_id)
            messages = await self.repository.get_conversation_messages(conversation.id)

            if not messages:
                await update.message.reply_text("No conversation history to export.")
                return

            # Build conversation markdown
            lines = [
                "# Conversation History",
                "",
                f"*Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
                "",
                "---",
                "",
            ]

            for msg in messages:
                if msg.role == "user":
                    lines.append("## 💬 You")
                else:
                    lines.append("## 🤖 BabililoBot")

                if msg.created_at:
                    lines.append(f"*{msg.created_at.strftime('%Y-%m-%d %H:%M')}*")
                lines.append("")
                lines.append(msg.content)
                lines.append("")
                lines.append("---")
                lines.append("")

            lines.append("*Powered by BabililoBot*")

            content = "\n".join(lines)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

            buffer = io.BytesIO(content.encode('utf-8'))
            buffer.seek(0)

            await update.message.reply_document(
                document=InputFile(buffer, filename=f"babililo_conversation_{timestamp}.md"),
                caption="📚 Full conversation exported!",
            )

        except Exception as e:
            logger.error(f"Export command error: {e}")
            await update.message.reply_text("Failed to export conversation.")
