import asyncio
import threading
import logging
from telegram import Bot
from telegram.ext import ApplicationBuilder, MessageHandler, filters
from config import Config

logger = logging.getLogger(__name__)

# Shared variables for thread communication
_reply_event = threading.Event()
_latest_reply = None
_loop = None
_thread = None
_application = None

async def _message_handler(update, context):
    global _latest_reply
    # Only listen to the configured chat ID
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        logger.warning(f"Received message from unauthorized chat ID: {chat_id}")
        return
    
    text = update.message.text
    logger.info(f"Received Telegram reply: {text}")
    _latest_reply = text
    _reply_event.set()

def start_bot():
    global _loop, _thread, _application
    if _thread and _thread.is_alive():
        logger.warning("Telegram Bot is already running.")
        return

    _loop = asyncio.new_event_loop()
    _application = ApplicationBuilder().token(Config.TELEGRAM_BOT_TOKEN).build()
    _application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _message_handler))
    
    def run_app():
        asyncio.set_event_loop(_loop)
        # Initialize and start application
        _loop.run_until_complete(_application.initialize())
        _loop.run_until_complete(_application.updater.start_polling())
        _loop.run_until_complete(_application.start())
        logger.info("Telegram Bot started polling.")
        _loop.run_forever()

    _thread = threading.Thread(target=run_app, daemon=True)
    _thread.start()

def stop_bot():
    global _loop, _application, _thread
    if _loop and _application:
        try:
            future = asyncio.run_coroutine_threadsafe(_application.updater.stop(), _loop)
            future.result(timeout=5)
            future2 = asyncio.run_coroutine_threadsafe(_application.stop(), _loop)
            future2.result(timeout=5)
        except Exception as e:
            logger.error(f"Error stopping Telegram application: {e}")
        finally:
            _loop.call_soon_threadsafe(_loop.stop)
            _thread = None
            logger.info("Telegram Bot stopped.")

def send_message_sync(text: str) -> None:
    """Send text message synchronously from any thread."""
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID is missing in Config.")
        return

    async def _send():
        bot_instance = _application.bot if (_application and _application.bot) else Bot(token=Config.TELEGRAM_BOT_TOKEN)
        await bot_instance.send_message(chat_id=Config.TELEGRAM_CHAT_ID, text=text)

    try:
        if _loop and _loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_send(), _loop)
            future.result(timeout=15)
        else:
            asyncio.run(_send())
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")

def send_photo_sync(photo_path: str, caption: str = None) -> None:
    """Send photo message synchronously from any thread."""
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID is missing in Config.")
        return

    async def _send_photo():
        bot_instance = _application.bot if (_application and _application.bot) else Bot(token=Config.TELEGRAM_BOT_TOKEN)
        with open(photo_path, 'rb') as photo_file:
            await bot_instance.send_photo(chat_id=Config.TELEGRAM_CHAT_ID, photo=photo_file, caption=caption)

    try:
        if _loop and _loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_send_photo(), _loop)
            future.result(timeout=25)
        else:
            asyncio.run(_send_photo())
    except Exception as e:
        logger.error(f"Failed to send Telegram photo: {e}")

def clear_reply() -> None:
    """Clear any previous reply state."""
    global _latest_reply
    _reply_event.clear()
    _latest_reply = None
    logger.info("Cleared previous Telegram reply state.")

def wait_for_reply(timeout_seconds: float = None) -> str:
    """Block the thread until a message is received from the user, or timeout."""
    global _latest_reply
    
    timeout_str = f"{timeout_seconds}s" if timeout_seconds is not None else "indefinite"
    logger.info(f"Waiting for Telegram reply (timeout: {timeout_str})...")
    is_set = _reply_event.wait(timeout=timeout_seconds)
    if is_set:
        return _latest_reply
    else:
        logger.warning("Timeout waiting for user reply.")
        return "timeout"
