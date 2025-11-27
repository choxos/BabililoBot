"""Voice message handler for BabililoBot."""

import io
import logging
import tempfile
from pathlib import Path
from typing import Optional

from telegram import Update, InputFile
from telegram.ext import ContextTypes

from src.config import get_settings
from src.database.repository import Repository
from src.services.openrouter import OpenRouterClient, ChatMessage
from src.services.conversation import ConversationManager

logger = logging.getLogger(__name__)


class VoiceHandler:
    """Handles voice messages - speech-to-text and text-to-speech."""

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

    async def handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming voice messages."""
        if not update.effective_user or not update.message or not update.message.voice:
            return

        user = update.effective_user
        voice = update.message.voice

        # Check voice duration (limit to 60 seconds)
        if voice.duration > 60:
            await update.message.reply_text(
                "⚠️ Voice messages must be under 60 seconds. Please send a shorter message."
            )
            return

        status_msg = await update.message.reply_text("🎤 Processing voice message...")

        try:
            # Download voice file
            voice_file = await context.bot.get_file(voice.file_id)

            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await voice_file.download_to_drive(tmp.name)
                tmp_path = Path(tmp.name)

            # Transcribe using Whisper via OpenRouter (if available) or fallback
            transcribed_text = await self._transcribe_audio(tmp_path)

            if not transcribed_text:
                await status_msg.edit_text("❌ Couldn't transcribe audio. Please try again.")
                tmp_path.unlink(missing_ok=True)
                return

            await status_msg.edit_text(f"📝 *Transcribed:* {transcribed_text}\n\n💭 Generating response...", parse_mode="Markdown")

            # Get user settings
            db_user = await self.repository.get_or_create_user(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
            )

            # Build conversation context
            messages = await self.conversation_manager.build_api_messages(
                telegram_id=user.id,
                new_message=transcribed_text,
            )

            # Get AI response
            response = await self.openrouter.chat_completion(
                messages=messages,
                model=db_user.selected_model,
            )

            # Store in conversation
            await self.conversation_manager.add_user_message(user.id, transcribed_text)
            await self.conversation_manager.add_assistant_message(
                telegram_id=user.id,
                content=response.content,
                model_used=db_user.selected_model,
            )

            # Send text response
            await status_msg.edit_text(
                f"📝 *You said:* {transcribed_text}\n\n🤖 *Response:*\n{response.content}",
                parse_mode="Markdown",
            )

            # If voice replies enabled, also send audio
            if db_user.voice_enabled:
                await self._send_voice_reply(update, response.content)

            # Cleanup
            tmp_path.unlink(missing_ok=True)

        except Exception as e:
            logger.error(f"Voice message error: {e}")
            await status_msg.edit_text("❌ Failed to process voice message.")

    async def _transcribe_audio(self, audio_path: Path) -> Optional[str]:
        """Transcribe audio file to text."""
        try:
            # Try using OpenRouter's Whisper model if available
            # For now, use a simple approach with speech_recognition if available
            import speech_recognition as sr

            # Convert ogg to wav for speech_recognition
            import subprocess
            wav_path = audio_path.with_suffix(".wav")

            subprocess.run(
                ["ffmpeg", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav_path), "-y"],
                capture_output=True,
                timeout=30,
            )

            recognizer = sr.Recognizer()
            with sr.AudioFile(str(wav_path)) as source:
                audio = recognizer.record(source)

            text = recognizer.recognize_google(audio)
            wav_path.unlink(missing_ok=True)
            return text

        except ImportError:
            logger.warning("speech_recognition not available, using fallback")
            return await self._transcribe_fallback(audio_path)
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return await self._transcribe_fallback(audio_path)

    async def _transcribe_fallback(self, audio_path: Path) -> Optional[str]:
        """Fallback transcription - ask user to type."""
        return None  # Will prompt user to type instead

    async def _send_voice_reply(self, update: Update, text: str) -> None:
        """Convert text to speech and send as voice message."""
        try:
            from gtts import gTTS

            # Limit text length for TTS
            tts_text = text[:1000] if len(text) > 1000 else text

            # Generate speech
            tts = gTTS(text=tts_text, lang='en', slow=False)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tts.save(tmp.name)
                tmp_path = Path(tmp.name)

            # Send voice message
            with open(tmp_path, 'rb') as audio_file:
                await update.message.reply_voice(voice=audio_file, caption="🔊 Voice response")

            tmp_path.unlink(missing_ok=True)

        except ImportError:
            logger.warning("gTTS not available for voice replies")
        except Exception as e:
            logger.error(f"TTS error: {e}")

    async def handle_voice_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /voice command to toggle voice responses."""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        args = context.args

        db_user = await self.repository.get_user_by_telegram_id(user_id)
        if not db_user:
            await update.message.reply_text("Please /start first.")
            return

        if not args:
            status = "enabled" if db_user.voice_enabled else "disabled"
            await update.message.reply_text(
                f"🔊 Voice responses are currently **{status}**.\n\n"
                "Use `/voice on` or `/voice off` to change.",
                parse_mode="Markdown",
            )
            return

        action = args[0].lower()
        if action == "on":
            await self.repository.update_user_voice(user_id, True)
            await update.message.reply_text("✅ Voice responses enabled! I'll reply with audio when you send voice messages.")
        elif action == "off":
            await self.repository.update_user_voice(user_id, False)
            await update.message.reply_text("🔇 Voice responses disabled.")
        else:
            await update.message.reply_text("Usage: `/voice on` or `/voice off`", parse_mode="Markdown")

    async def handle_voice_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice button callback to generate audio for a message."""
        if not update.callback_query:
            return

        query = update.callback_query
        await query.answer("Generating audio...")

        # Get the message content
        original_message = query.message
        if not original_message or not original_message.text:
            await query.answer("No message to convert", show_alert=True)
            return

        await self._send_voice_reply_query(query, original_message.text)

    async def _send_voice_reply_query(self, query, text: str) -> None:
        """Convert text to speech from callback query."""
        try:
            from gtts import gTTS

            tts_text = text[:1000] if len(text) > 1000 else text
            tts = gTTS(text=tts_text, lang='en', slow=False)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tts.save(tmp.name)
                tmp_path = Path(tmp.name)

            with open(tmp_path, 'rb') as audio_file:
                await query.message.reply_voice(voice=audio_file, caption="🔊 Voice version")

            tmp_path.unlink(missing_ok=True)

        except Exception as e:
            logger.error(f"TTS callback error: {e}")
            await query.answer("Failed to generate audio", show_alert=True)

