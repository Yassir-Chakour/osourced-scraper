import asyncio
import threading
import logging
import re
from typing import Optional, List
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from config import Config
from prompts import guardrail_manager
from db.jobs_db import load_jobs
from db.ignored_companies import get_ignored_companies, add_ignored_company, remove_ignored_company

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
        "🤖 **Osourced Scraper & Auto-Apply Bot**\n\n"
        "⚙️ **So funktioniert das System:**\n"
        "• Jeden Morgen um **09:00 Uhr** scanne ich neue Stellenangebote.\n"
        "• Neue Stellen werden **vollautomatisch** beworben.\n"
        "• Bereits beworbene Stellen werden sofort im Speicher übersprungen.\n"
        "• Stellen von blockierten Firmen werden automatisch ignoriert.\n"
        "• Nach dem Durchlauf sende ich dir **1 zufälliges Bewerbungsbeispiel** zur Überprüfung.\n"
        "• Wenn es keine neuen Stellen gab, erhältst du eine kurze Info.\n\n"
        "🧠 **Prompt-Tuning per Chat:**\n"
        "Du kannst mir jederzeit eine Nachricht schreiben (z. B. *'Verwende ab jetzt immer Du statt Sie'* oder *'Erwähne kein n8n mehr'*). "
        "Ich aktualisiere meine Prompt-Guardrails sofort für alle zukünftigen Bewerbungen!\n\n"
        "📋 **Befehle:**\n"
        "/guardrails - Zeigt alle aktuell aktiven Prompt-Regeln\n"
        "/add_rule <Regel> - Fügt eine neue Prompt-Regel hinzu\n"
        "/reset_guardrails - Setzt alle gelernten Regeln zurück\n"
        "/ignored - Zeigt blockierte Firmen\n"
        "/ignore <Firma> - Blockiert eine Firma\n"
        "/unignore <Firma> - Entfernt eine Firma von der Blockierliste\n"
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
            "Schreibe mir einfach deine Wünsche im Chat (z. B. *\"Fasse dich kürzer\"* oder *\"add to prompt\"*), um Regeln hinzuzufügen.",
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


async def _add_rule_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /add_rule <rule text> or /prompt <rule text>."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    if not context.args:
        context.user_data["awaiting_prompt_rule"] = True
        await update.message.reply_text(
            "📝 Bitte gib die Regel an, die zum Prompt hinzugefügt werden soll:\n\n"
            "Beispiel: `/add_rule Verwende immer Du statt Sie`\n"
            "Oder antworte einfach direkt auf diese Nachricht.",
            parse_mode="Markdown"
        )
        return

    rule_text = " ".join(context.args).strip()
    status_msg = await update.message.reply_text("⏳ Aktualisiere Prompt-Regeln...")
    try:
        reply = await asyncio.to_thread(guardrail_manager.process_user_feedback, rule_text)
        await status_msg.edit_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error processing prompt rule: {e}")
        await status_msg.edit_text(f"❌ Fehler bei der Verarbeitung: {e}")


async def _reset_guardrails_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /reset_guardrails command."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    result = guardrail_manager.reset_guardrails()
    await update.message.reply_text(result)


async def _ignored_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ignored command to list all blocked companies."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    companies = get_ignored_companies()
    if not companies:
        await update.message.reply_text("📋 Keine blockierten Firmen hinterlegt.")
        return

    list_text = "\n".join(f"• `{c}`" for c in companies)
    await update.message.reply_text(
        f"🚫 **Blockierte Firmen ({len(companies)}):**\n\n{list_text}\n\n"
        f"Firma hinzufügen: `/ignore <Name>`\n"
        f"Firma entfernen: `/unignore <Name>`",
        parse_mode="Markdown"
    )


async def _ignore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ignore <company> command."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    if not context.args:
        await update.message.reply_text("Bitte gib einen Firmennamen an:\n`/ignore Firmenname`", parse_mode="Markdown")
        return

    company_name = " ".join(context.args).strip()
    if add_ignored_company(company_name):
        await update.message.reply_text(f"🚫 **Firma blockiert:** `{company_name}` wurde zur Ausschlussliste hinzugefügt. Bewerbungen für diese Firma werden ab jetzt übersprungen.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Fehler beim Hinzufügen von `{company_name}`.")


async def _unignore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /unignore <company> command."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    if not context.args:
        await update.message.reply_text("Bitte gib einen Firmennamen an:\n`/unignore Firmenname`", parse_mode="Markdown")
        return

    company_name = " ".join(context.args).strip()
    if remove_ignored_company(company_name):
        await update.message.reply_text(f"✅ **Firma freigegeben:** `{company_name}` wurde von der Ausschlussliste entfernt.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Fehler beim Entfernen von `{company_name}`.")


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
    ignored_companies_count = len(get_ignored_companies())

    msg = (
        f"📊 **System-Status:**\n\n"
        f"• Erfasste Stellen in DB: {len(jobs)}\n"
        f"• Erfolgreich beworben: {applied}\n"
        f"• Übersprungen / Ignoriert: {rejected}\n"
        f"• Fehlerhafte Bewerbungen: {errors}\n"
        f"• Blockierte Firmen: {ignored_companies_count}\n"
        f"• Aktive Prompt-Guardrails: {guardrails_count}\n"
        f"• Modus: Täglich um {Config.DAILY_RUN_TIME} Uhr ({Config.TIMEZONE or 'Europe/Berlin'})"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


TRIGGER_AWAITING_REGEX = re.compile(
    r"^(add\s+this(\s+company)?|add\s+company|add\s+to\s+blacklist|blacklist(\s+company)?|block\s+company|firma\s+sperren|firma\s+blockieren|sperre\s+firma|firma\s+hinzufügen|auf\s+blacklist(\s+setzen)?)$",
    re.IGNORECASE
)

TRIGGER_AWAITING_PROMPT_REGEX = re.compile(
    r"^(add\s+to\s+prompt|update\s+prompt|change\s+prompt|add\s+rule|prompt\s+rule|neue\s+regel|regel\s+hinzufügen|prompt\s+anpassen)$",
    re.IGNORECASE
)

DIRECT_ADD_PATTERNS = [
    re.compile(r"^add\s+this(?:\s+company)?[:\s]+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:add|füge)\s+(?:this\s+company\s+|the\s+company\s+|die\s+firma\s+|firma\s+)?(.+?)\s+(?:to\s+(?:the\s+)?blacklist|zur\s+blacklist|auf\s+die\s+blacklist)$", re.IGNORECASE),
    re.compile(r"^(?:blacklist|block|sperre|ignoriere)\s+(?:die\s+firma\s+|firma\s+|company\s+)?(.+)$", re.IGNORECASE),
    re.compile(r"^setze\s+(.+?)\s+auf\s+die\s+blacklist$", re.IGNORECASE),
]


async def _message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process natural language user feedback, commands, and blacklist additions."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        logger.warning(f"Received message from unauthorized chat ID: {chat_id}")
        return

    text = update.message.text or update.message.caption
    if not text:
        return

    text_clean = text.strip()

    # 1. State machine: Was the bot waiting for a company name to blacklist?
    if context.user_data.get("awaiting_company_blacklist"):
        if text_clean.lower() in ("cancel", "abbrechen", "/cancel"):
            context.user_data["awaiting_company_blacklist"] = False
            await update.message.reply_text("❌ Vorgang abgebrochen.")
            return

        add_ignored_company(text_clean)
        context.user_data["awaiting_company_blacklist"] = False
        await update.message.reply_text(
            f"🚫 **Firma blockiert:** `{text_clean}` wurde zur Blacklist hinzugefügt.\n\n"
            f"Stellenangebote dieser Firma werden ab jetzt vollautomatisch übersprungen.",
            parse_mode="Markdown"
        )
        return

    # 2. State machine: Was the bot waiting for a prompt rule / guardrail?
    if context.user_data.get("awaiting_prompt_rule"):
        if text_clean.lower() in ("cancel", "abbrechen", "/cancel"):
            context.user_data["awaiting_prompt_rule"] = False
            await update.message.reply_text("❌ Vorgang abgebrochen.")
            return

        context.user_data["awaiting_prompt_rule"] = False
        status_msg = await update.message.reply_text("⏳ Aktualisiere Prompt-Regeln...")
        try:
            reply = await asyncio.to_thread(guardrail_manager.process_user_feedback, text_clean)
            await status_msg.edit_text(reply, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error processing prompt rule: {e}")
            await status_msg.edit_text(f"❌ Fehler bei der Verarbeitung: {e}")
        return

    # 3. Trigger two-step blacklist conversation: "add this", "add company", "add to blacklist", etc.
    if TRIGGER_AWAITING_REGEX.match(text_clean):
        context.user_data["awaiting_company_blacklist"] = True
        await update.message.reply_text(
            "👍 **Verstanden!** Sende mir bitte als Nächstes den Namen der Firma, die ich auf die Blacklist setzen soll.\n\n"
            "_(Tippe `abbrechen`, um abzubrechen)_",
            parse_mode="Markdown"
        )
        return

    # 4. Trigger two-step prompt rule conversation: "add to prompt", "add rule", "prompt anpassen"
    if TRIGGER_AWAITING_PROMPT_REGEX.match(text_clean):
        context.user_data["awaiting_prompt_rule"] = True
        await update.message.reply_text(
            "📝 **Prompt anpassen:**\n\n"
            "Was genau soll ich in zukünftigen Bewerbungen beachten oder ändern?\n\n"
            "_(z. B. 'Verwende immer Du statt Sie' oder 'Erwähne kein n8n mehr')_\n"
            "_(Tippe `abbrechen`, um abzubrechen)_",
            parse_mode="Markdown"
        )
        return

    # 5. Direct fast-path regex: "add World Bite to blacklist", "block World Bite", "sperre World Bite"
    for pattern in DIRECT_ADD_PATTERNS:
        match = pattern.match(text_clean)
        if match:
            comp = match.group(1).strip().strip('"\'')
            if comp and comp.lower() not in ("company", "firma", "this"):
                add_ignored_company(comp)
                await update.message.reply_text(
                    f"🚫 **Firma blockiert:** `{comp}` wurde zur Blacklist hinzugefügt.\n\n"
                    f"Stellenangebote dieser Firma werden ab jetzt vollautomatisch übersprungen.",
                    parse_mode="Markdown"
                )
                return

    # 6. Fallback to LLM for complex instructions, mixed feedback, or prompt tuning
    logger.info(f"Received natural language instruction on Telegram: '{text_clean}'")
    status_msg = await update.message.reply_text("⏳ Verarbeite Anweisung...")

    try:
        reply = await asyncio.to_thread(guardrail_manager.process_user_feedback, text_clean)
        await status_msg.edit_text(reply, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error processing feedback: {e}")
        await status_msg.edit_text(f"❌ Fehler bei der Verarbeitung: {e}")


async def _photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos without captions by asking for the company name."""
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        return

    if not update.message.caption:
        context.user_data["awaiting_company_blacklist"] = True
        await update.message.reply_text(
            "📸 **Screenshot erhalten!**\n\n"
            "Sende mir bitte den Namen der Firma als Textnachricht, damit ich sie auf die Blacklist setzen kann.\n\n"
            "_(Tippe `abbrechen`, um abzubrechen)_",
            parse_mode="Markdown"
        )


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
    _application.add_handler(CommandHandler(["add_rule", "prompt"], _add_rule_command))
    _application.add_handler(CommandHandler("reset_guardrails", _reset_guardrails_command))
    _application.add_handler(CommandHandler("ignored", _ignored_command))
    _application.add_handler(CommandHandler("ignore", _ignore_command))
    _application.add_handler(CommandHandler("unignore", _unignore_command))
    _application.add_handler(CommandHandler("status", _status_command))

    # Photo handler (screenshots)
    _application.add_handler(MessageHandler(filters.PHOTO, _photo_handler))

    # Text & captioned messages
    _application.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, _message_handler))

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


