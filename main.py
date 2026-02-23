import logging
import io
import os
import asyncio
from telegram import Update, BotCommand
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from config import BOT_TOKEN, DRIVE_FOLDER_ID
from drive_service import get_drive_service, find_duplicates, delete_file, GoogleAuthError, get_auth_flow, save_token
from queue_manager import QueueManager
from admin_utils import is_admin, add_admin, remove_admin

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

queue_mgr = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message and resumes bot if admin."""
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)
    
    if is_admin(username) and queue_mgr.paused:
        await queue_mgr.resume_bot()
        await update.message.reply_text("▶️ **Bot Resumed!** I am now accepting new tasks.", parse_mode='Markdown')
        return

    await update.message.reply_text(
        "Hi! I'm your Google Drive Uploader Bot. "
        "Send me any file, photo, or video, and I'll upload it to your Drive folder one by one."
    )

async def pause_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pauses the bot and clears all tasks (Admin only)."""
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)

    if not is_admin(username):
        await update.message.reply_text("❌ This command is restricted to admins.")
        return

    await update.message.reply_text("⏳ Pausing bot and clearing all tasks... Please wait.")
    cancelled_count = await queue_mgr.pause_bot()
    
    await update.message.reply_text(
        f"⏸️ **Bot Paused!**\n\n"
        f"• Running task stopped.\n"
        f"• {cancelled_count} queued tasks cleared.\n"
        f"• New tasks will be rejected.\n\n"
        f"Send /start to resume.",
        parse_mode='Markdown'
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles file uploads by adding them to the queue."""
    message = update.message
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)

    if not is_admin(username):
        await message.reply_text("❌ Only admins can upload files to Google Drive.")
        return

    file = None
    file_name = None
    mime_type = None

    if message.document:
        file = await message.document.get_file()
        file_name = message.document.file_name
        mime_type = message.document.mime_type
    elif message.photo:
        file = await message.photo[-1].get_file()
        file_name = f"photo_{message.photo[-1].file_unique_id}.jpg"
        mime_type = 'image/jpeg'
    elif message.video:
        file = await message.video.get_file()
        file_name = message.video.file_name or f"video_{message.video.file_unique_id}.mp4"
        mime_type = message.video.mime_type

    if not file:
        await message.reply_text("Unsupported file type.")
        return

    file_info = {
        'file': file,
        'name': file_name,
        'mime_type': mime_type
    }
    
    await queue_mgr.add_job(update, context, file_info)

async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adds a new admin (Admin only)."""
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)

    if not is_admin(username):
        await update.message.reply_text("❌ This command is restricted to admins.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /addadmin <username>")
        return

    target_user = context.args[0]
    success, msg = add_admin(target_user)
    await update.message.reply_text(f"{'✅' if success else '❌'} {msg}")

async def remove_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes an admin (Admin only)."""
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)

    if not is_admin(username):
        await update.message.reply_text("❌ This command is restricted to admins.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <username>")
        return

    target_user = context.args[0]
    success, msg = remove_admin(target_user)
    await update.message.reply_text(f"{'✅' if success else '❌'} {msg}")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Scans for duplicate files in the Drive folder."""
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)

    if not is_admin(username):
        await update.message.reply_text("❌ This command is restricted to admins.")
        return

    await update.message.reply_text("🔍 Scanning for duplicates... This may take a while.")
    
    loop = asyncio.get_running_loop()
    try:
        service = await loop.run_in_executor(None, get_drive_service)
        duplicates = await loop.run_in_executor(None, find_duplicates, service, DRIVE_FOLDER_ID)
        
        if not duplicates:
            await update.message.reply_text("✅ No duplicate files found.")
            return

        msg = f"Found {len(duplicates)} sets of duplicates (Name-Based):\n\n"
        for norm_name, files in duplicates.items():
            # Use the name from the first file as the display name
            display_name = files[0]['name']
            msg += f"• `{display_name}`: {len(files)} copies\n"
            
        if len(msg) > 4000:
            msg = msg[:4000] + "\n...(truncated)"
            
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        if isinstance(e, GoogleAuthError):
            await update.message.reply_text(f"❌ **Drive Auth Error:**\n`{str(e)}`\n\nUse /reauth to fix this.", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Error during scan: `{str(e)}`", parse_mode='Markdown')

async def reauth_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates a re-authorization URL (Admin only)."""
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)

    if not is_admin(username):
        await update.message.reply_text("❌ This command is restricted to admins.")
        return

    try:
        flow = get_auth_flow()
        auth_url, _ = flow.authorization_url(prompt='consent')
        
        msg = (
            "🔑 **Google Drive Authorization**\n\n"
            "1. Click the link below and log in.\n"
            "2. Copy the authorization code.\n"
            "3. **Reply to this message** with the code.\n\n"
            f"[Authorize Here]({auth_url})"
        )
        await update.message.reply_text(msg, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to generate auth URL: {str(e)}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text messages, potentially authorization codes."""
    text = update.message.text.strip()
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)

    # Simple check if it might be an auth code (usually long, no spaces)
    if is_admin(username) and len(text) > 30 and ' ' not in text:
        status_msg = await update.message.reply_text("⏳ Verifying authorization code...")
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, save_token, text)
            await status_msg.edit_text("✅ **Authorization Successful!**\nYou can now resume uploads or use /scan.")
        except Exception as e:
            await status_msg.edit_text(f"❌ **Authorization Failed:**\n{str(e)}\n\nMake sure you copied the full code and try again.")
        return

    # If not an auth code, just ignore or add more text handling here

async def remove_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Removes all duplicate files based on name, keeping the oldest one."""
    user = update.effective_user
    username = f"@{user.username}" if user.username else str(user.id)

    if not is_admin(username):
        await update.message.reply_text("❌ This command is restricted to admins.")
        return

    await update.message.reply_text("🗑️ Duplicate removal (Name-Based) started... This may take a while.")
    
    loop = asyncio.get_running_loop()
    try:
        service = await loop.run_in_executor(None, get_drive_service)
        duplicates = await loop.run_in_executor(None, find_duplicates, service, DRIVE_FOLDER_ID)
        
        if not duplicates:
            await update.message.reply_text("✅ No duplicate files found to remove.")
            return
            
        total_deleted = 0
        
        for norm_name, files in duplicates.items():
            # Sort by createdTime (oldest first)
            files.sort(key=lambda x: x['createdTime'])
            
            # Keep the first one (index 0), delete the rest
            to_delete = files[1:]
            
            for file in to_delete:
                success = await loop.run_in_executor(None, delete_file, service, file['id'])
                if success:
                    total_deleted += 1
                    
        await update.message.reply_text(f"✅ Removal complete.\nDeleted {total_deleted} duplicate files. Originals kept.")
    except Exception as e:
        if isinstance(e, GoogleAuthError):
            await update.message.reply_text(f"❌ **Drive Auth Error:**\n`{str(e)}`\n\nUse /reauth to fix this.", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Error during removal: `{str(e)}`", parse_mode='Markdown')

async def post_init(application):
    """Executes after application is initialized."""
    global queue_mgr
    queue_mgr = QueueManager(application)
    
    # Set Bot Menu Commands
    commands = [
        BotCommand("start", "Start or resume the bot"),
        BotCommand("scan", "Check for duplicate files"),
        BotCommand("removeall", "Delete duplicates (Keep originals)"),
        BotCommand("pause", "Stop and clear queue"),
        BotCommand("reauth", "Fix expired Drive token")
    ]
    await application.bot.set_my_commands(commands)
    
    # Trigger Google Drive authorization
    try:
        print("Checking Google Drive authorization...")
        get_drive_service()
        print("Google Drive authorization successful!")
    except Exception as e:
        print(f"Google Drive authorization failed or pending: {e}")

def main():
    """Starts the bot."""
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("Please set your BOT_TOKEN in config.py")
        return

    application = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)
    
    pause_handler = CommandHandler('pause', pause_command)
    application.add_handler(pause_handler)

    add_admin_handler = CommandHandler('addadmin', add_admin_command)
    application.add_handler(add_admin_handler)

    remove_admin_handler = CommandHandler('removeadmin', remove_admin_command)
    application.add_handler(remove_admin_handler)

    scan_handler = CommandHandler('scan', scan_command)
    application.add_handler(scan_handler)

    remove_all_handler = CommandHandler('removeall', remove_all_command)
    application.add_handler(remove_all_handler)

    reauth_handler = CommandHandler('reauth', reauth_command)
    application.add_handler(reauth_handler)
    
    # Handle documents, photos, and videos
    message_handler = MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_document)
    application.add_handler(message_handler)

    # Handle text (for auth codes)
    text_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_text)
    application.add_handler(text_handler)
    
    print("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
