"""Export handler for PDF/Markdown generation."""

import io
import logging
import re
from datetime import datetime
from typing import Optional, Tuple, List

from telegram import Update, InputFile
from telegram.ext import ContextTypes

from src.database.repository import Repository

logger = logging.getLogger(__name__)


class ExportHandler:
    """Handles exporting messages to PDF and Markdown formats."""

    def __init__(self, repository: Repository):
        self.repository = repository

    async def _get_prompt_and_response(self, message_id: int) -> Tuple[Optional[str], Optional[str]]:
        """Get the user prompt and assistant response for a message."""
        try:
            message = await self.repository.get_message_by_id(message_id)
            if not message:
                return None, None

            messages = await self.repository.get_conversation_messages(
                message.conversation_id, limit=50
            )

            user_prompt = None
            assistant_response = message.content

            for i, msg in enumerate(messages):
                if msg.id == message_id and i > 0:
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

        data = query.data.split(":")
        if len(data) != 3:
            return

        _, format_type, message_id = data

        try:
            message_id = int(message_id)
        except ValueError:
            await query.answer("Invalid message ID", show_alert=True)
            return

        user_prompt, assistant_response = await self._get_prompt_and_response(message_id)

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
            elif format_type in ["txt", "md"]:
                await self._export_markdown(query, user_prompt, assistant_response, timestamp)
            else:
                await query.answer("Unknown format", show_alert=True)

        except Exception as e:
            logger.error(f"Export error: {e}")
            await query.answer("Failed to generate file", show_alert=True)

    def _parse_markdown_content(self, text: str) -> List[dict]:
        """Parse markdown content into structured blocks.
        
        Returns list of dicts with 'type' (text/code/heading) and 'content'.
        """
        blocks = []
        lines = text.split('\n')
        current_block = {'type': 'text', 'content': [], 'language': ''}
        in_code_block = False
        code_language = ''

        for line in lines:
            # Check for code block start/end
            if line.strip().startswith('```'):
                if not in_code_block:
                    # Save current text block
                    if current_block['content']:
                        current_block['content'] = '\n'.join(current_block['content'])
                        blocks.append(current_block)
                    
                    # Start code block
                    in_code_block = True
                    code_language = line.strip()[3:].strip()
                    current_block = {'type': 'code', 'content': [], 'language': code_language}
                else:
                    # End code block
                    in_code_block = False
                    current_block['content'] = '\n'.join(current_block['content'])
                    blocks.append(current_block)
                    current_block = {'type': 'text', 'content': [], 'language': ''}
            elif in_code_block:
                current_block['content'].append(line)
            else:
                # Check for headings
                if line.startswith('**') and line.endswith('**') and len(line) > 4:
                    if current_block['content']:
                        current_block['content'] = '\n'.join(current_block['content'])
                        blocks.append(current_block)
                        current_block = {'type': 'text', 'content': [], 'language': ''}
                    blocks.append({'type': 'heading', 'content': line.strip('*'), 'language': ''})
                else:
                    current_block['content'].append(line)

        # Don't forget the last block
        if current_block['content']:
            if isinstance(current_block['content'], list):
                current_block['content'] = '\n'.join(current_block['content'])
            blocks.append(current_block)

        return blocks

    async def _export_pdf(
        self, query, user_prompt: Optional[str], response: str, timestamp: str
    ) -> None:
        """Generate and send PDF file with proper code block formatting."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.colors import HexColor, Color
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, HRFlowable,
                Preformatted, Table, TableStyle
            )
            from reportlab.lib.units import inch
            from reportlab.lib.enums import TA_LEFT

            buffer = io.BytesIO()
            doc = SimpleDocTemplate(
                buffer,
                pagesize=letter,
                leftMargin=0.6 * inch,
                rightMargin=0.6 * inch,
                topMargin=0.6 * inch,
                bottomMargin=0.6 * inch,
            )
            styles = getSampleStyleSheet()

            # Custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=20,
                spaceAfter=8,
                textColor=HexColor('#1a1a2e'),
                fontName='Helvetica-Bold',
            )

            prompt_label_style = ParagraphStyle(
                'PromptLabel',
                parent=styles['Heading2'],
                fontSize=13,
                textColor=HexColor('#e94560'),
                spaceAfter=8,
                spaceBefore=16,
                fontName='Helvetica-Bold',
            )

            response_label_style = ParagraphStyle(
                'ResponseLabel',
                parent=styles['Heading2'],
                fontSize=13,
                textColor=HexColor('#0f3460'),
                spaceAfter=8,
                spaceBefore=16,
                fontName='Helvetica-Bold',
            )

            content_style = ParagraphStyle(
                'Content',
                parent=styles['Normal'],
                fontSize=10,
                leading=14,
                spaceAfter=6,
                fontName='Helvetica',
            )

            heading_style = ParagraphStyle(
                'ContentHeading',
                parent=styles['Normal'],
                fontSize=11,
                leading=16,
                spaceAfter=6,
                spaceBefore=12,
                fontName='Helvetica-Bold',
                textColor=HexColor('#16213e'),
            )

            code_style = ParagraphStyle(
                'Code',
                parent=styles['Code'],
                fontSize=9,
                leading=12,
                fontName='Courier',
                backColor=HexColor('#f4f4f4'),
                borderColor=HexColor('#e0e0e0'),
                borderWidth=1,
                borderPadding=8,
                leftIndent=0,
                rightIndent=0,
            )

            meta_style = ParagraphStyle(
                'Meta',
                parent=styles['Normal'],
                fontSize=9,
                textColor=HexColor('#888888'),
            )

            # Build document
            story = []

            # Header
            story.append(Paragraph("🤖 BabililoBot", title_style))
            story.append(Paragraph(f"Generated: {timestamp.replace('_', ' ')}", meta_style))
            story.append(Spacer(1, 0.2 * inch))
            story.append(HRFlowable(width="100%", thickness=1, color=HexColor('#e0e0e0')))
            story.append(Spacer(1, 0.15 * inch))

            # User Prompt
            if user_prompt:
                story.append(Paragraph("💬 Your Question", prompt_label_style))
                prompt_escaped = user_prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                prompt_escaped = prompt_escaped.replace("\n", "<br/>")
                story.append(Paragraph(prompt_escaped, content_style))
                story.append(Spacer(1, 0.15 * inch))

            # AI Response
            story.append(Paragraph("🤖 AI Response", response_label_style))

            # Parse and format response with code blocks
            blocks = self._parse_markdown_content(response)

            for block in blocks:
                if block['type'] == 'code':
                    # Code block with background
                    story.append(Spacer(1, 0.1 * inch))
                    
                    # Language label if present
                    if block['language']:
                        lang_style = ParagraphStyle(
                            'LangLabel',
                            fontSize=8,
                            textColor=HexColor('#666666'),
                            fontName='Helvetica',
                        )
                        story.append(Paragraph(f"<i>{block['language']}</i>", lang_style))
                    
                    # Code content in a table for background
                    code_text = block['content']
                    code_text = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    
                    # Create a table with background color for code
                    code_para = Preformatted(code_text, code_style)
                    t = Table([[code_para]], colWidths=[6.8 * inch])
                    t.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f8f8f8')),
                        ('BOX', (0, 0), (-1, -1), 1, HexColor('#e0e0e0')),
                        ('LEFTPADDING', (0, 0), (-1, -1), 10),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                        ('TOPPADDING', (0, 0), (-1, -1), 8),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ]))
                    story.append(t)
                    story.append(Spacer(1, 0.1 * inch))

                elif block['type'] == 'heading':
                    story.append(Paragraph(block['content'], heading_style))

                else:
                    # Regular text
                    text = block['content']
                    if text.strip():
                        text_escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        # Handle inline code
                        text_escaped = re.sub(
                            r'`([^`]+)`',
                            r'<font face="Courier" size="9" color="#c7254e">\1</font>',
                            text_escaped
                        )
                        # Handle bold
                        text_escaped = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text_escaped)
                        text_escaped = text_escaped.replace("\n", "<br/>")
                        story.append(Paragraph(text_escaped, content_style))

            # Footer
            story.append(Spacer(1, 0.3 * inch))
            story.append(HRFlowable(width="100%", thickness=0.5, color=HexColor('#e0e0e0')))
            story.append(Spacer(1, 0.1 * inch))
            story.append(Paragraph("Powered by BabililoBot • t.me/babililobot", meta_style))

            doc.build(story)
            buffer.seek(0)

            await query.message.reply_document(
                document=InputFile(buffer, filename=f"babililo_{timestamp}.pdf"),
                caption="📄 PDF exported with formatted code blocks!",
            )

        except ImportError as e:
            logger.error(f"PDF import error: {e}")
            await query.answer("PDF export not available", show_alert=True)
        except Exception as e:
            logger.error(f"PDF generation error: {e}")
            await query.answer("PDF generation failed", show_alert=True)

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
            caption="📝 Markdown exported!",
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
