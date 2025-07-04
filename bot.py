import logging
import subprocess
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)
import yt_dlp
import os
import re
import shutil

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Dictionary to temporarily store user data
user_data = {}

# Check if FFmpeg is installed
def check_ffmpeg_installed():
    """Check if FFmpeg is available in the system PATH"""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    
    logger.error("FFmpeg is not installed!")
    
# Check FFmpeg at startup
FFMPEG_INSTALLED = check_ffmpeg_installed()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hello! Send me a video link from Instagram, YouTube, or TikTok and I'll download it for you.\n\n"
        f"FFmpeg Status: {'✅ Installed' if FFMPEG_INSTALLED else '❌ Not installed - Audio conversion disabled'}"
    )

def is_valid_url(url: str) -> bool:
    """Check if the URL is supported."""
    patterns = [
        r'https?://(www\.)?(youtube\.com|youtu\.be)/.+',
        r'https?://(www\.)?instagram\.com/(p|reel)/.+',
        r'https?://(vm\.tiktok\.com|www\.tiktok\.com)/.+',
        r'https?://(www\.)?facebook\.com/.+',
        r'https?://(www\.)?twitter\.com/.+'
    ]
    return any(re.match(pattern, url) for pattern in patterns)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    if not is_valid_url(url):
        await update.message.reply_text("⚠️ Unsupported URL. Please send a link from YouTube, Instagram, or TikTok.")
        return
    
    # Temporarily store the URL
    user_id = update.message.from_user.id
    user_data[user_id] = {
        'url': url,
        'chat_id': update.message.chat_id
    }
    
    # Create choice buttons
    keyboard = [
        [
            InlineKeyboardButton("Download Video 🎬", callback_data='video'),
            InlineKeyboardButton("Download Audio Only 🎵", callback_data='audio')
        ],
        [
            InlineKeyboardButton("High Quality Video (if available) 📺", callback_data='high_quality')
        ]
    ]
    
    # Disable audio button if FFmpeg not installed
    if not FFMPEG_INSTALLED:
        keyboard[0][1] = InlineKeyboardButton(
            "Audio Disabled (FFmpeg missing)", 
            callback_data='ffmpeg_error'
        )
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📥 Choose download type:",
        reply_markup=reply_markup
    )

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE, media_type: str):
    """Process the download based on user choice."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = user_data.get(user_id)
    
    if not data:
        await query.edit_message_text("❌ Link expired. Please send the link again.")
        return
    
    url = data['url']
    chat_id = data['chat_id']
    
    await query.edit_message_text("⏳ Downloading... Please wait")
    
    try:
        if media_type == 'video':
            # Video download options
            ydl_opts = {
                'outtmpl': 'downloaded.%(ext)s',
                'format': 'best[filesize<50M]',
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,  # 50MB
            }
        elif media_type == 'high_quality':
            # High quality video options
            ydl_opts = {
                'outtmpl': 'downloaded.%(ext)s',
                'format': 'best',
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,  # 50MB
            }
        else:  # audio
            # Audio download options
            ydl_opts = {
                'outtmpl': 'downloaded.%(ext)s',
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 20 * 1024 * 1024,  # 20MB
            }

        if 'instagram' in url:
            ydl_opts.update({
                'format': 'best',
                # 'cookiefile': 'cookies.txt'  # Uncomment if you have cookies file
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            
            # Adjust filename for audio files
            if media_type == 'audio':
                file_path = os.path.splitext(file_path)[0] + '.mp3'

        # Check file size
        file_size = os.path.getsize(file_path)
        
        if media_type in ['video', 'high_quality'] and file_size > 50 * 1024 * 1024:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Video size exceeds 50MB Telegram limit."
            )
            os.remove(file_path)
            return
        
        if media_type == 'audio' and file_size > 20 * 1024 * 1024:
            await context.bot.send_message(
                chat_id=chat_id,
                text="⚠️ Audio file size exceeds 20MB limit."
            )
            os.remove(file_path)
            return

        # Send the file
        if media_type in ['video', 'high_quality']:
            await context.bot.send_video(
                chat_id=chat_id,
                video=open(file_path, 'rb'),
                supports_streaming=True,
                caption="Video downloaded successfully! ✅"
            )
        else:  # audio
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=open(file_path, 'rb'),
                caption="Audio downloaded successfully! ✅"
            )
            
        os.remove(file_path)

    except yt_dlp.utils.DownloadError as e:
        error_msg = f"❌ Download error: {str(e)}"
        # Special handling for FFmpeg errors
        if "ffmpeg" in str(e).lower() or "ffprobe" in str(e).lower():
            error_msg += "\n\nFFmpeg is not installed or not in your system PATH!\nPlease install FFmpeg to enable audio conversion."
        await context.bot.send_message(
            chat_id=chat_id,
            text=error_msg
        )
    except Exception as e:
        logger.exception("Unexpected error")
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ An error occurred while processing your request"
        )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button selection."""
    query = update.callback_query
    choice = query.data
    
    if choice == 'ffmpeg_error':
        await query.answer("FFmpeg is not installed! Audio conversion disabled.", show_alert=True)
        return
    
    if choice == 'video':
        await handle_download(update, context, 'video')
    elif choice == 'audio':
        if not FFMPEG_INSTALLED:
            await query.answer("FFmpeg is not installed! Audio conversion disabled.", show_alert=True)
            return
        await handle_download(update, context, 'audio')
    elif choice == 'high_quality':
        await handle_download(update, context, 'high_quality')

if __name__ == '__main__':
    try:
        # Replace with your actual bot token
        TOKEN = "7599353405:AAG8u8fcytR9LL7VPAtOz7yfjGzwp-_EbsI"
        
        
        application = ApplicationBuilder().token(TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        logger.info("✅ Bot is running...")
        print("="*50)
        print("Bot started successfully!")
        print("You can now go to Telegram and use the bot")
        print("="*50)
        
        application.run_polling()
        
    except Exception as e:
        logger.exception("Fatal error starting bot")