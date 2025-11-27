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
        """Handle incoming voice messages - transcribe, respond, and reply with voice."""
        if not update.effective_user or not update.message or not update.message.voice:
            return

        user = update.effective_user
        voice = update.message.voice

        # Check voice duration (limit to 60 seconds)
        if voice.duration > 60:
            await update.message.reply_text(
                "⚠️ Voice messages must be under 60 seconds."
            )
            return

        status_msg = await update.message.reply_text("🎤 Processing voice message...")

        try:
            # Download voice file
            voice_file = await context.bot.get_file(voice.file_id)

            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                await voice_file.download_to_drive(tmp.name)
                tmp_path = Path(tmp.name)

            # Transcribe audio
            transcribed_text = await self._transcribe_audio(tmp_path)
            tmp_path.unlink(missing_ok=True)

            if not transcribed_text:
                await status_msg.edit_text(
                    "🎤 Couldn't transcribe your voice message.\n\n"
                    "**Tip:** Make sure to speak clearly. You can also type your message."
                ,parse_mode="Markdown")
                return

            await status_msg.edit_text(
                f"📝 *Heard:* {transcribed_text}\n\n💭 Thinking...",
                parse_mode="Markdown"
            )

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
                f"🎤 *You said:* {transcribed_text}\n\n🤖 {response.content}",
                parse_mode="Markdown",
            )

            # ALWAYS send voice reply for voice messages (voice-to-voice)
            await self._send_voice_reply(update, response.content)

        except Exception as e:
            logger.error(f"Voice message error: {e}")
            await status_msg.edit_text(
                "❌ Error processing voice message. Please try again or type your message."
            )

    async def _transcribe_audio(self, audio_path: Path) -> Optional[str]:
        """Transcribe audio file to text."""
        
        # Method 1: Try speech_recognition with pydub for conversion
        try:
            import speech_recognition as sr
            from pydub import AudioSegment
            
            # Convert OGG to WAV
            audio = AudioSegment.from_ogg(str(audio_path))
            wav_path = audio_path.with_suffix(".wav")
            audio.export(str(wav_path), format="wav")
            
            recognizer = sr.Recognizer()
            with sr.AudioFile(str(wav_path)) as source:
                audio_data = recognizer.record(source)
            
            wav_path.unlink(missing_ok=True)
            
            # Try Google Speech Recognition (free)
            try:
                text = recognizer.recognize_google(audio_data)
                return text
            except sr.UnknownValueError:
                logger.warning("Could not understand audio")
                return None
            except sr.RequestError as e:
                logger.error(f"Google Speech API error: {e}")
                return None
                    
        except ImportError as e:
            logger.warning(f"Speech recognition imports failed: {e}")
        except Exception as e:
            logger.error(f"Transcription error: {e}")

        return None

    async def _send_voice_reply(self, update: Update, text: str) -> None:
        """Convert text to speech and send as voice message."""
        try:
            from gtts import gTTS

            # Limit text length for TTS (gTTS has limits)
            tts_text = text[:2000] if len(text) > 2000 else text
            
            # Clean text for TTS (remove markdown)
            tts_text = tts_text.replace("**", "").replace("*", "").replace("`", "")
            tts_text = tts_text.replace("#", "").replace("_", " ")

            # Generate speech
            tts = gTTS(text=tts_text, lang='en', slow=False)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tts.save(tmp.name)
                tmp_path = Path(tmp.name)

            # Send voice message
            with open(tmp_path, 'rb') as audio_file:
                await update.message.reply_voice(
                    voice=audio_file,
                    caption="🔊 Voice response"
                )

            tmp_path.unlink(missing_ok=True)
            logger.info("Voice reply sent successfully")

        except ImportError:
            logger.warning("gTTS not available for voice replies")
            await update.message.reply_text("(Voice reply unavailable - gTTS not installed)")
        except Exception as e:
            logger.error(f"TTS error: {e}")

    async def handle_voice_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /voice command to toggle voice responses for TEXT messages."""
        if not update.effective_user or not update.message:
            return

        user_id = update.effective_user.id
        args = context.args

        db_user = await self.repository.get_user_by_telegram_id(user_id)
        if not db_user:
            await update.message.reply_text("Please /start first.")
            return

        if not args:
            status = "enabled ✅" if db_user.voice_enabled else "disabled ❌"
            await update.message.reply_text(
                f"🔊 **Voice Settings**\n\n"
                f"Voice replies for text messages: {status}\n\n"
                f"**Note:** Voice messages always get voice replies!\n\n"
                f"Commands:\n"
                f"• `/voice on` - Also get voice for text messages\n"
                f"• `/voice off` - Text replies only for text messages",
                parse_mode="Markdown",
            )
            return

        action = args[0].lower()
        if action == "on":
            await self.repository.update_user_voice(user_id, True)
            await update.message.reply_text("✅ Voice responses enabled for text messages too!")
        elif action == "off":
            await self.repository.update_user_voice(user_id, False)
            await update.message.reply_text("🔇 Voice responses disabled for text messages.\n\nVoice messages still get voice replies!")
        else:
            await update.message.reply_text("Usage: `/voice on` or `/voice off`", parse_mode="Markdown")

    async def handle_voice_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle voice button callback to generate audio for a message."""
        if not update.callback_query:
            return

        query = update.callback_query
        await query.answer("🔊 Generating audio...")

        # Get the message content
        original_message = query.message
        if not original_message or not original_message.text:
            await query.answer("No message to convert", show_alert=True)
            return

        try:
            from gtts import gTTS

            text = original_message.text[:2000]
            # Clean markdown
            text = text.replace("**", "").replace("*", "").replace("`", "")
            text = text.replace("#", "").replace("_", " ")
            
            tts = gTTS(text=text, lang='en', slow=False)

            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tts.save(tmp.name)
                tmp_path = Path(tmp.name)

            with open(tmp_path, 'rb') as audio_file:
                await query.message.reply_voice(
                    voice=audio_file,
                    caption="🔊 Audio version"
                )

            tmp_path.unlink(missing_ok=True)

        except ImportError:
            await query.answer("Voice generation not available", show_alert=True)
        except Exception as e:
            logger.error(f"TTS callback error: {e}")
            await query.answer("Failed to generate audio", show_alert=True)
