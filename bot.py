import os
import logging
from datetime import datetime, timedelta
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters
)
from collections import defaultdict

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment variable
BOT_TOKEN = os.environ.get('BOT_TOKEN')

# Storage
user_warnings = defaultdict(int)  # user_id: warning_count
user_invites = defaultdict(int)   # user_id: invite_count
restricted_users = set()          # user_ids with hi-only restriction

# Blacklist words
BLACKLIST_WORDS = ['පොඩි', 'කාමුක', 'ලිංගික', 'අසභ්‍ය', 'sex', 'porn', 'xxx', 'adult', 'nude']

# Allowed first message for new users
ALLOWED_FIRST_MESSAGES = ['hi', 'hello', 'හායි', 'හලෝ', 'hey']


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    await update.message.reply_text(
        "🤖 Bot Active!\n\n"
        "Features:\n"
        "✅ Auto welcome (20s delete)\n"
        "✅ Blacklist words (3 warns = 2h mute)\n"
        "✅ Block forwards & links\n"
        "✅ New member restrictions\n"
        "✅ Anti-spam\n\n"
        "Admin Commands:\n"
        "/stats - Bot statistics"
    )


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome new members with auto-delete"""
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        
        # Add to restricted users (hi-only mode)
        restricted_users.add(member.id)
        
        # Send welcome message
        welcome_msg = await update.message.reply_text(
            f"👋 Welcome {member.mention_html()}!\n\n"
            f"🔒 You can only say 'Hi' for now.\n\n"
            f"📌 To unlock full access:\n"
            f"• Add 5 members to this group, OR\n"
            f"• Wait 1 hour\n\n"
            f"This message will self-destruct in 20 seconds.",
            parse_mode='HTML'
        )
        
        # Schedule message deletion after 20 seconds
        context.job_queue.run_once(
            delete_message,
            20,
            data={'chat_id': update.effective_chat.id, 'message_id': welcome_msg.message_id}
        )
        
        # Schedule auto-unlock after 1 hour
        context.job_queue.run_once(
            auto_unlock_user,
            3600,
            data={'chat_id': update.effective_chat.id, 'user_id': member.id}
        )


async def delete_message(context: ContextTypes.DEFAULT_TYPE):
    """Delete a message"""
    job_data = context.job.data
    try:
        await context.bot.delete_message(
            chat_id=job_data['chat_id'],
            message_id=job_data['message_id']
        )
    except Exception as e:
        logger.error(f"Error deleting message: {e}")


async def auto_unlock_user(context: ContextTypes.DEFAULT_TYPE):
    """Auto-unlock user after 1 hour"""
    job_data = context.job.data
    user_id = job_data['user_id']
    
    if user_id in restricted_users:
        restricted_users.remove(user_id)
        try:
            await context.bot.send_message(
                chat_id=job_data['chat_id'],
                text=f"🔓 User unlocked! You can now send any message."
            )
        except Exception as e:
            logger.error(f"Error sending unlock message: {e}")


async def track_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track when users add new members"""
    if update.message.new_chat_members:
        inviter_id = update.message.from_user.id
        
        # Count invites
        new_members_count = len([m for m in update.message.new_chat_members if not m.is_bot])
        user_invites[inviter_id] += new_members_count
        
        # Check if user should be unlocked (5+ invites)
        if user_invites[inviter_id] >= 5 and inviter_id in restricted_users:
            restricted_users.remove(inviter_id)
            await update.message.reply_text(
                f"🎉 Congratulations! You've added 5 members.\n"
                f"🔓 Full access unlocked!"
            )


async def check_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check all messages for violations"""
    if not update.message or not update.message.text:
        return
    
    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id
    message_text = update.message.text.lower()
    
    # Check if user is restricted (hi-only mode)
    if user_id in restricted_users:
        if message_text.strip() not in ALLOWED_FIRST_MESSAGES:
            await update.message.delete()
            await update.message.reply_text(
                f"⚠️ {update.message.from_user.mention_html()}\n"
                f"You can only say 'Hi' for now.\n\n"
                f"To unlock: Add 5 members or wait 1 hour.",
                parse_mode='HTML'
            )
            return
    
    # Check for blacklist words
    for word in BLACKLIST_WORDS:
        if word in message_text:
            await update.message.delete()
            user_warnings[user_id] += 1
            
            if user_warnings[user_id] >= 3:
                # Mute for 2 hours
                await context.bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=datetime.now() + timedelta(hours=2)
                )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🚫 {update.message.from_user.mention_html()}\n"
                         f"3 warnings received!\n"
                         f"Muted for 2 hours.",
                    parse_mode='HTML'
                )
                user_warnings[user_id] = 0  # Reset warnings
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Warning {user_warnings[user_id]}/3\n"
                         f"{update.message.from_user.mention_html()}\n"
                         f"Don't use inappropriate words!",
                    parse_mode='HTML'
                )
            return
    
    # Check for links
    if 'http://' in message_text or 'https://' in message_text or 't.me/' in message_text:
        await update.message.delete()
        await update.message.reply_text(
            f"🚫 {update.message.from_user.mention_html()}\n"
            f"Links are not allowed!",
            parse_mode='HTML'
        )
        return


async def check_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block forwarded messages"""
    if update.message.forward_date or update.message.forward_from:
        await update.message.delete()
        await update.message.reply_text(
            f"🚫 {update.message.from_user.mention_html()}\n"
            f"Forwarded messages are not allowed!",
            parse_mode='HTML'
        )


async def spam_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Basic anti-spam (delete if too many messages quickly)"""
    # Simple implementation - can be enhanced
    user_id = update.message.from_user.id
    current_time = datetime.now()
    
    if not hasattr(context.bot_data, 'user_message_times'):
        context.bot_data['user_message_times'] = defaultdict(list)
    
    # Track message times
    context.bot_data['user_message_times'][user_id].append(current_time)
    
    # Keep only last 10 seconds of messages
    context.bot_data['user_message_times'][user_id] = [
        t for t in context.bot_data['user_message_times'][user_id]
        if (current_time - t).seconds < 10
    ]
    
    # If more than 5 messages in 10 seconds = spam
    if len(context.bot_data['user_message_times'][user_id]) > 5:
        await update.message.delete()
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.now() + timedelta(minutes=5)
        )
        await update.message.reply_text(
            f"🚫 {update.message.from_user.mention_html()}\n"
            f"Spam detected! Muted for 5 minutes.",
            parse_mode='HTML'
        )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    stats_text = (
        f"📊 Bot Statistics\n\n"
        f"👥 Restricted users: {len(restricted_users)}\n"
        f"⚠️ Users with warnings: {len(user_warnings)}\n"
        f"🎯 Total invites tracked: {sum(user_invites.values())}\n"
    )
    await update.message.reply_text(stats_text)


def main():
    """Start the bot"""
    if not BOT_TOKEN:
        print("Error: BOT_TOKEN not found in environment variables!")
        return
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    
    # Message handlers
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        welcome_new_member
    ))
    application.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_MEMBERS,
        track_new_members
    ))
    application.add_handler(MessageHandler(
        filters.FORWARDED,
        check_forward
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        check_message
    ))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        spam_check
    ))
    
    # Start bot
    print("🤖 Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
