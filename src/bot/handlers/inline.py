"""Inline query handler for BabililoBot."""

import hashlib
import logging
from typing import Optional
from uuid import uuid4

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from src.config import get_settings
from src.database.repository import Repository
from src.services.openrouter import OpenRouterClient, ChatMessage

logger = logging.getLogger(__name__)


class InlineHandler:
    """Handles inline queries for @babililobot usage in any chat."""

    def __init__(self, repository: Repository, openrouter_client: OpenRouterClient):
        self.repository = repository
        self.openrouter = openrouter_client
        self.settings = get_settings()
        self._cache: dict = {}  # Simple query cache

    def _get_cache_key(self, query: str, model: str) -> str:
        """Generate cache key for query."""
        return hashlib.md5(f"{query}:{model}".encode()).hexdigest()

    async def handle_inline_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle inline queries."""
        if not update.inline_query:
            return

        query = update.inline_query.query.strip()
        user = update.inline_query.from_user

        # Require at least 3 characters
        if len(query) < 3:
            await update.inline_query.answer(
                results=[],
                cache_time=0,
                switch_pm_text="Type at least 3 characters...",
                switch_pm_parameter="start",
            )
            return

        try:
            # Get user's selected model
            db_user = await self.repository.get_user_by_telegram_id(user.id)
            model = db_user.selected_model if db_user else self.settings.openrouter_default_model

            # Check cache
            cache_key = self._get_cache_key(query, model)
            if cache_key in self._cache:
                response = self._cache[cache_key]
            else:
                # Generate response
                messages = [
                    ChatMessage(role="system", content="You are a helpful assistant. Provide concise, direct answers. Keep responses under 200 words."),
                    ChatMessage(role="user", content=query),
                ]

                result = await self.openrouter.chat_completion(
                    messages=messages,
                    model=model,
                    max_tokens=500,
                )
                response = result.content

                # Cache result (limit cache size)
                if len(self._cache) > 100:
                    self._cache.clear()
                self._cache[cache_key] = response

            # Create result
            results = [
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="🤖 AI Response",
                    description=response[:100] + "..." if len(response) > 100 else response,
                    input_message_content=InputTextMessageContent(
                        message_text=f"**Q:** {query}\n\n**A:** {response}",
                        parse_mode="Markdown",
                    ),
                ),
                InlineQueryResultArticle(
                    id=str(uuid4()),
                    title="📝 Response Only",
                    description="Send just the answer without the question",
                    input_message_content=InputTextMessageContent(
                        message_text=response,
                        parse_mode="Markdown",
                    ),
                ),
            ]

            await update.inline_query.answer(
                results=results,
                cache_time=300,  # Cache for 5 minutes
                is_personal=True,
            )

        except Exception as e:
            logger.error(f"Inline query error: {e}")
            await update.inline_query.answer(
                results=[
                    InlineQueryResultArticle(
                        id=str(uuid4()),
                        title="❌ Error",
                        description="Failed to generate response. Try again.",
                        input_message_content=InputTextMessageContent(
                            message_text="Sorry, I couldn't process your request. Please try again.",
                        ),
                    ),
                ],
                cache_time=0,
            )

    async def handle_chosen_inline_result(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Track when inline results are chosen (optional analytics)."""
        if update.chosen_inline_result:
            logger.info(f"Inline result chosen: {update.chosen_inline_result.result_id}")

