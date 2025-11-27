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
        """Parse markdown content into structured blocks."""
        blocks = []
        lines = text.split('\n')
        current_block = {'type': 'text', 'content': [], 'language': '', 'level': 0}
        in_code_block = False
        in_table = False
        table_rows = []

        for i, line in enumerate(lines):
            stripped = line.strip()
            
            # Check for code block start/end
            if stripped.startswith('```'):
                if in_table:
                    # End table before code block
                    if table_rows:
                        blocks.append({'type': 'table', 'content': table_rows, 'language': '', 'level': 0})
                        table_rows = []
                    in_table = False
                
                if not in_code_block:
                    if current_block['content']:
                        current_block['content'] = '\n'.join(current_block['content'])
                        blocks.append(current_block)
                    
                    in_code_block = True
                    code_language = stripped[3:].strip()
                    current_block = {'type': 'code', 'content': [], 'language': code_language, 'level': 0}
                else:
                    in_code_block = False
                    current_block['content'] = '\n'.join(current_block['content'])
                    blocks.append(current_block)
                    current_block = {'type': 'text', 'content': [], 'language': '', 'level': 0}
                continue
                    
            if in_code_block:
                current_block['content'].append(line)
                continue
            
            # Check for markdown table row
            if '|' in stripped and stripped.startswith('|') and stripped.endswith('|'):
                # Check if it's a separator row (|---|---|)
                if re.match(r'^\|[\s\-:]+\|$', stripped.replace('|', '|').replace('-', '-')):
                    # This is a separator row, skip it but mark we're in a table
                    in_table = True
                    continue
                
                # Parse table row
                cells = [cell.strip() for cell in stripped.split('|')[1:-1]]
                if cells:
                    if not in_table:
                        # Save current block before starting table
                        if current_block['content']:
                            current_block['content'] = '\n'.join(current_block['content'])
                            blocks.append(current_block)
                            current_block = {'type': 'text', 'content': [], 'language': '', 'level': 0}
                        in_table = True
                    table_rows.append(cells)
                continue
            
            # If we were in a table and hit a non-table line, save the table
            if in_table:
                if table_rows:
                    blocks.append({'type': 'table', 'content': table_rows, 'language': '', 'level': 0})
                    table_rows = []
                in_table = False
            
            # Check for markdown headers (# ## ### etc.)
            header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
            if header_match:
                if current_block['content']:
                    current_block['content'] = '\n'.join(current_block['content'])
                    blocks.append(current_block)
                    current_block = {'type': 'text', 'content': [], 'language': '', 'level': 0}
                
                level = len(header_match.group(1))
                header_text = header_match.group(2).strip()
                blocks.append({'type': 'heading', 'content': header_text, 'language': '', 'level': level})
                continue
            
            # Check for bold headers like **Header**
            if stripped.startswith('**') and stripped.endswith('**') and len(stripped) > 4:
                inner = stripped[2:-2]
                if inner and '**' not in inner:
                    if current_block['content']:
                        current_block['content'] = '\n'.join(current_block['content'])
                        blocks.append(current_block)
                        current_block = {'type': 'text', 'content': [], 'language': '', 'level': 0}
                    blocks.append({'type': 'heading', 'content': inner, 'language': '', 'level': 2})
                    continue

            # Regular text
            current_block['content'].append(line)

        # Don't forget remaining content
        if in_table and table_rows:
            blocks.append({'type': 'table', 'content': table_rows, 'language': '', 'level': 0})
        
        if current_block['content']:
            if isinstance(current_block['content'], list):
                current_block['content'] = '\n'.join(current_block['content'])
            blocks.append(current_block)

        return blocks

    async def _export_pdf(
        self, query, user_prompt: Optional[str], response: str, timestamp: str
    ) -> None:
        """Generate and send PDF file with proper formatting."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.colors import HexColor
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

            # Heading styles for different levels
            h1_style = ParagraphStyle(
                'H1',
                parent=styles['Heading1'],
                fontSize=16,
                leading=20,
                spaceAfter=10,
                spaceBefore=16,
                fontName='Helvetica-Bold',
                textColor=HexColor('#1a1a2e'),
            )

            h2_style = ParagraphStyle(
                'H2',
                parent=styles['Heading2'],
                fontSize=14,
                leading=18,
                spaceAfter=8,
                spaceBefore=14,
                fontName='Helvetica-Bold',
                textColor=HexColor('#2d3436'),
            )

            h3_style = ParagraphStyle(
                'H3',
                parent=styles['Heading3'],
                fontSize=12,
                leading=16,
                spaceAfter=6,
                spaceBefore=12,
                fontName='Helvetica-Bold',
                textColor=HexColor('#444444'),
            )

            code_style = ParagraphStyle(
                'Code',
                parent=styles['Code'],
                fontSize=9,
                leading=12,
                fontName='Courier',
            )

            meta_style = ParagraphStyle(
                'Meta',
                parent=styles['Normal'],
                fontSize=9,
                textColor=HexColor('#888888'),
            )

            def get_heading_style(level: int):
                if level == 1:
                    return h1_style
                elif level == 2:
                    return h2_style
                else:
                    return h3_style

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

            # Parse and format response
            blocks = self._parse_markdown_content(response)

            # Table cell style
            table_cell_style = ParagraphStyle(
                'TableCell',
                parent=styles['Normal'],
                fontSize=9,
                leading=12,
                fontName='Helvetica',
            )

            for block in blocks:
                if block['type'] == 'code':
                    story.append(Spacer(1, 0.1 * inch))
                    
                    if block['language']:
                        lang_style = ParagraphStyle(
                            'LangLabel',
                            fontSize=8,
                            textColor=HexColor('#666666'),
                            fontName='Helvetica-Oblique',
                        )
                        story.append(Paragraph(f"{block['language']}", lang_style))
                    
                    code_text = block['content']
                    code_text = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    
                    code_para = Preformatted(code_text, code_style)
                    t = Table([[code_para]], colWidths=[6.8 * inch])
                    t.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f5f5f5')),
                        ('BOX', (0, 0), (-1, -1), 1, HexColor('#ddd')),
                        ('LEFTPADDING', (0, 0), (-1, -1), 10),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                        ('TOPPADDING', (0, 0), (-1, -1), 8),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ]))
                    story.append(t)
                    story.append(Spacer(1, 0.1 * inch))

                elif block['type'] == 'table':
                    story.append(Spacer(1, 0.1 * inch))
                    
                    # Build table data with Paragraphs for text wrapping
                    table_data = []
                    for row_idx, row in enumerate(block['content']):
                        table_row = []
                        for cell in row:
                            cell_text = cell.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                            # Handle bold in cells
                            cell_text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', cell_text)
                            cell_text = re.sub(r'`([^`]+)`', r'<font face="Courier" size="8">\1</font>', cell_text)
                            table_row.append(Paragraph(cell_text, table_cell_style))
                        table_data.append(table_row)
                    
                    if table_data:
                        # Calculate column widths
                        num_cols = len(table_data[0]) if table_data else 1
                        col_width = 6.8 * inch / num_cols
                        
                        t = Table(table_data, colWidths=[col_width] * num_cols)
                        t.setStyle(TableStyle([
                            # Header row styling
                            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#4a90a4')),
                            ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#ffffff')),
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            # All cells
                            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cccccc')),
                            ('LEFTPADDING', (0, 0), (-1, -1), 8),
                            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                            ('TOPPADDING', (0, 0), (-1, -1), 6),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                            # Alternating row colors
                            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f9f9f9')]),
                        ]))
                        story.append(t)
                    story.append(Spacer(1, 0.1 * inch))

                elif block['type'] == 'heading':
                    level = block.get('level', 2)
                    style = get_heading_style(level)
                    heading_text = block['content']
                    heading_text = heading_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    story.append(Paragraph(heading_text, style))

                else:
                    # Regular text
                    text = block['content']
                    if text.strip():
                        text_escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        
                        # Handle inline code
                        text_escaped = re.sub(
                            r'`([^`]+)`',
                            r'<font face="Courier" size="9" color="#c7254e" backColor="#f9f2f4">\1</font>',
                            text_escaped
                        )
                        # Handle bold
                        text_escaped = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text_escaped)
                        # Handle italic
                        text_escaped = re.sub(r'\*([^*]+)\*', r'<i>\1</i>', text_escaped)
                        # Handle line breaks
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
                caption="📄 PDF exported!",
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
        """Generate and send Markdown file."""
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
        """Handle /export command."""
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
