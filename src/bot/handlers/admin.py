"""Admin command handlers for BabililoBot."""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from src.config import get_settings
from src.database.repository import Repository
from src.bot.middleware.rate_limit import RateLimiter

logger = logging.getLogger(__name__)


class AdminHandler:
    """Handles admin commands like /stats, /broadcast, /ban, /unban."""

    def __init__(self, repository: Repository, rate_limiter: RateLimiter):
        self.repository = repository
        self.rate_limiter = rate_limiter
        self.settings = get_settings()

    def _is_admin(self, user_id: int) -> bool:
        """Check if user is an admin."""
        return user_id in self.settings.admin_ids

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /stats command - show bot statistics (admin only)."""
        if not update.effective_user or not update.message:
            return

        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ This command is for admins only.")
            return

        try:
            stats = await self.repository.get_user_stats()
            rate_stats = self.rate_limiter.get_stats()

            stats_text = (
                "📈 **Bot Statistics**\n\n"
                f"**Users:**\n"
                f"• Total users: {stats.get('total_users', 0)}\n"
                f"• Active users: {stats.get('active_users', 0)}\n"
                f"• Total messages: {stats.get('total_messages', 0)}\n\n"
                f"**Rate Limiter:**\n"
                f"• Active buckets: {rate_stats.get('active_buckets', 0)}\n"
                f"• Capacity: {rate_stats.get('capacity', 0)} msgs\n"
            )

            await update.message.reply_text(stats_text, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await update.message.reply_text("❌ Error fetching statistics.")

    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /broadcast command - send message to all users (admin only)."""
        if not update.effective_user or not update.message:
            return

        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ This command is for admins only.")
            return

        # Get message to broadcast
        if not context.args:
            await update.message.reply_text(
                "Usage: /broadcast <message>\n\n"
                "Example: /broadcast Hello everyone! 👋"
            )
            return

        broadcast_message = " ".join(context.args)

        try:
            users = await self.repository.get_all_users()
            success_count = 0
            fail_count = 0

            await update.message.reply_text(
                f"📢 Broadcasting to {len(users)} users..."
            )

            for user in users:
                if user.is_banned:
                    continue

                try:
                    await context.bot.send_message(
                        chat_id=user.telegram_id,
                        text=f"📢 **Announcement**\n\n{broadcast_message}",
                        parse_mode="Markdown",
                    )
                    success_count += 1
                except Exception as e:
                    logger.warning(f"Failed to send broadcast to {user.telegram_id}: {e}")
                    fail_count += 1

            await update.message.reply_text(
                f"✅ Broadcast complete!\n\n"
                f"• Sent: {success_count}\n"
                f"• Failed: {fail_count}"
            )

        except Exception as e:
            logger.error(f"Error broadcasting: {e}")
            await update.message.reply_text("❌ Error during broadcast.")

    async def ban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /ban command - ban a user (admin only)."""
        if not update.effective_user or not update.message:
            return

        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ This command is for admins only.")
            return

        if not context.args or len(context.args) != 1:
            await update.message.reply_text(
                "Usage: /ban <telegram_user_id>\n\n"
                "Example: /ban 123456789"
            )
            return

        try:
            user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Please provide a numeric ID.")
            return

        # Don't allow banning admins
        if user_id in self.settings.admin_ids:
            await update.message.reply_text("❌ Cannot ban an admin.")
            return

        success = await self.repository.ban_user(user_id)

        if success:
            await update.message.reply_text(f"✅ User {user_id} has been banned.")
        else:
            await update.message.reply_text(f"❌ User {user_id} not found.")

    async def unban_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /unban command - unban a user (admin only)."""
        if not update.effective_user or not update.message:
            return

        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ This command is for admins only.")
            return

        if not context.args or len(context.args) != 1:
            await update.message.reply_text(
                "Usage: /unban <telegram_user_id>\n\n"
                "Example: /unban 123456789"
            )
            return

        try:
            user_id = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Please provide a numeric ID.")
            return

        success = await self.repository.unban_user(user_id)

        if success:
            await update.message.reply_text(f"✅ User {user_id} has been unbanned.")
        else:
            await update.message.reply_text(f"❌ User {user_id} not found.")

    async def users_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /users command - list recent users (admin only)."""
        if not update.effective_user or not update.message:
            return

        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("⛔ This command is for admins only.")
            return

        try:
            users = await self.repository.get_all_users()

            # Show last 20 users
            recent_users = sorted(users, key=lambda u: u.created_at, reverse=True)[:20]

            if not recent_users:
                await update.message.reply_text("No users found.")
                return

            users_text = "👥 **Recent Users**\n\n"
            for user in recent_users:
                status = "🚫" if user.is_banned else "✅"
                username = f"@{user.username}" if user.username else "N/A"
                users_text += f"{status} `{user.telegram_id}` - {username} ({user.total_messages} msgs)\n"

            await update.message.reply_text(users_text, parse_mode="Markdown")

        except Exception as e:
            logger.error(f"Error listing users: {e}")
            await update.message.reply_text("❌ Error fetching users.")

