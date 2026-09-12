import asyncio
import threading
import logging
from typing import Optional, List
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from config import Config
from prompts import guardrail_manager
from db.jobs_db import load_jobs

logger = logging.getLogger(__name__)

_loop = None
_thread = None
_application = None


def chunk_text(text: str, max_length: int = 4000) -> List[str]:
    """Splits a long text string into safe chunks <= max_length characters without splitting lines."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    current_chunk = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > max_length:
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_len = 0
            while len(line) > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
        current_chunk.append(line)
        current_len += len(line)
    if current_chunk:
        chunks.append("".join(current_chunk))
    return chunks


async def _start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start or /help."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    msg = (
        "👋 **Hallo Shinobi!**\n\n"
        "Ich bin dein autonomer Osourced-Bewerbungs-Bot.\n\n"
        "⚙️ **So funktioniert das System:**\n"
        "• Jeden Morgen um **09:00 Uhr** scanne ich neue Stellenangebote.\n"
        "• Neue Stellen werden **vollautomatisch** beworben.\n"
        "• Bereits beworbene Stellen werden sofort im Speicher übersprungen.\n"
        "• Nach dem Durchlauf sende ich dir **1 zufälliges Bewerbungsbeispiel** zur Überprüfung.\n"
        "• Wenn es keine neuen Stellen gab, erhältst du eine kurze Info.\n\n"
        "🧠 **Prompt-Tuning per Chat:**\n"
        "Du kannst mir jederzeit eine Nachricht schreiben (z. B. *'Verwende ab jetzt immer Du statt Sie'* oder *'Erwähne kein n8n mehr'*). "
        "Ich aktualisiere meine Prompt-Guardrails sofort für alle zukünftigen Bewerbungen!\n\n"
        "📋 **Befehle:**\n"
        "/guardrails - Zeigt alle aktuell aktiven Prompt-Regeln\n"
        "/reset_guardrails - Setzt alle gelernten Regeln zurück\n"
        "/status - Zeigt den aktuellen Datenbankstatus"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def _guardrails_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /guardrails command."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    rules = guardrail_manager.get_guardrails()
    if not rules:
        await update.message.reply_text(
            "📋 **Aktive Guardrails:** Keine benutzerdefinierten Regeln hinterlegt.\n\n"
            "Schreibe mir einfach deine Wünsche im Chat (z. B. *\"Fasse dich kürzer\"*), um Regeln hinzuzufügen.",
            parse_mode="Markdown"
        )
        return

    rules_text = "\n".join(f"• {r}" for r in rules)
    await update.message.reply_text(
        f"📋 **Aktive Prompt-Guardrails ({len(rules)}):**\n\n"
        f"{rules_text}\n\n"
        f"_Diese Regeln werden bei jeder Bewerbung automatisch vom System-Prompt beachtet._",
        parse_mode="Markdown"
    )


async def _reset_guardrails_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset_guardrails command."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    result = guardrail_manager.reset_guardrails()
    await update.message.reply_text(result)


async def _status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    jobs = load_jobs()
    applied = sum(1 for j in jobs if j.get("status") == "applied")
    rejected = sum(1 for j in jobs if j.get("status") == "rejected")
    errors = sum(1 for j in jobs if j.get("status") == "error")
    guardrails_count = len(guardrail_manager.get_guardrails())

    msg = (
        f"📊 **System-Status:**\n\n"
        f"• Erfasste Stellen in DB: {len(jobs)}\n"
        f"• Erfolgreich beworben: {applied}\n"
        f"• Übersprungen / Ignoriert: {rejected}\n"
        f"• Fehlerhafte Bewerbungen: {errors}\n"
        f"• Aktive Prompt-Guardrails: {guardrails_count}\n"
        f"• Modus: Täglich um {Config.DAILY_RUN_TIME} Uhr ({Config.TIMEZONE or 'Europe/Berlin'})"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def _message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process natural language user feedback to tune prompt guardrails."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        logger.warning(f"Received message from unauthorized chat ID: {chat_id}")
        return

    text = update.message.text
    if not text:
        return

    logger.info(f"Received user prompt feedback on Telegram: '{text}'")
    status_msg = await update.message.reply_text("⏳ Analysiere Feedback und aktualisiere Prompt-Regeln...")

    try:
        reply = await asyncio.to_thread(guardrail_manager.update_guardrails_from_feedback, text)
        await status_msg.edit_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error processing prompt feedback: {e}")
        await status_msg.edit_text(f"❌ Fehler bei der Aktualisierung: {e}")


def start_bot():
    """Start the Telegram bot in a dedicated daemon thread."""
    global _loop, _thread, _application
    if _thread and _thread.is_alive():
        logger.warning("Telegram Bot is already running.")
        return

    _loop = asyncio.new_event_loop()
    _application = ApplicationBuilder().token(Config.TELEGRAM_BOT_TOKEN).build()

    # Commands
    _application.add_handler(CommandHandler(["start", "help"], _start_command))
    _application.add_handler(CommandHandler("guardrails", _guardrails_command))
    _application.add_handler(CommandHandler("reset_guardrails", _reset_guardrails_command))
    _application.add_handler(CommandHandler("status", _status_command))

    # Text messages (prompt tuning feedback)
    _application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _message_handler))

    def run_app():
        asyncio.set_event_loop(_loop)
        _loop.run_until_complete(_application.initialize())
        _loop.run_until_complete(_application.updater.start_polling(drop_pending_updates=True))
        _loop.run_until_complete(_application.start())
        logger.info("Telegram Bot started polling (with prompt tuning listener).")
        _loop.run_forever()

    _thread = threading.Thread(target=run_app, daemon=True)
    _thread.start()


def stop_bot():
    """Stop the Telegram bot and its thread cleanly."""
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


async def send_message_async(text: str, reply_markup=None) -> Optional[int]:
    """Send text message asynchronously, safely chunking text to prevent 4096 char limits."""
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID is missing in Config.")
        return None

    bot_instance = _application.bot if (_application and _application.bot) else Bot(token=Config.TELEGRAM_BOT_TOKEN)
    chunks = chunk_text(text, max_length=3900)
    last_msg_id = None

    for idx, chunk in enumerate(chunks):
        markup = reply_markup if idx == len(chunks) - 1 else None
        try:
            msg = await bot_instance.send_message(
                chat_id=Config.TELEGRAM_CHAT_ID,
                text=chunk,
                reply_markup=markup,
                parse_mode="Markdown"
            )
            last_msg_id = msg.message_id
        except Exception:
            # Fallback without markdown if markdown parsing fails
            msg = await bot_instance.send_message(
                chat_id=Config.TELEGRAM_CHAT_ID,
                text=chunk,
                reply_markup=markup
            )
            last_msg_id = msg.message_id

    return last_msg_id


def send_message_sync(text: str, reply_markup=None) -> Optional[int]:
    """Send text message synchronously from any thread and return its message ID."""
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID is missing in Config.")
        return None

    try:
        if _loop and _loop.is_running():
            future = asyncio.run_coroutine_threadsafe(send_message_async(text, reply_markup), _loop)
            return future.result(timeout=20)
        else:
            import concurrent.futures
            def run_in_new_loop():
                return asyncio.run(send_message_async(text, reply_markup))
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                return future.result(timeout=20)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return None


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
            import concurrent.futures
            def run_in_new_loop():
                asyncio.run(_send_photo())
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                future.result(timeout=25)
    except Exception as e:
        logger.error(f"Failed to send Telegram photo: {e}")


def check_and_send_next_card() -> None:
    """Backward compatibility no-op. Applications are now submitted autonomously."""
    pass


