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

from typing import Optional

async def process_user_feedback(update, job, text: str):
    fb = text.lower().strip().strip("!.,?-")
    action = None
    instructions = ""
    
    # Exact keywords list for direct approval/rejection
    approve_keywords = {"send", "senden", "go", "yes", "ja", "ok", "okay", "gut", "schicken", "passt", "yep", "perfekt"}
    reject_keywords = {"skip", "nein", "no", "nope", "lassen", "überspringen", "nächste", "next", "ne"}
    
    if fb in approve_keywords:
        action = "approve"
    elif fb in reject_keywords:
        action = "reject"
                
    if action:
        logger.info(f"Direct match found: action classified as '{action}' without calling LLM.")
    else:
        logger.info("Feedback is not a simple command, passing to LLM for analysis...")
        from prompts.template_manager import manager
        from graph.nodes.pitch_writer import call_llm
        prompt = manager.render("reply_handler.jinja", user_feedback=text)
        action = "modify"
        instructions = text

        try:
            response_text = await asyncio.to_thread(call_llm, prompt, json_mode=True)
            if response_text:
                import json
                data = json.loads(response_text)
                raw_action = data.get("action", "modify").lower().strip()
                if raw_action in ("send", "apply", "approve", "yes", "go"):
                    action = "approve"
                elif raw_action in ("reject", "skip", "no"):
                    action = "reject"
                else:
                    action = "modify"
                instructions = data.get("modification_instructions", text)
        except Exception as e:
            logger.error(f"Failed to classify reply via LLM: {e}")
            if any(w in fb for w in approve_keywords):
                action = "approve"
            elif any(w in fb for w in reject_keywords):
                action = "reject"
            else:
                action = "modify"

    from db.jobs_db import add_or_update_job
    
    if action == "modify":
        rounds = job.get("modification_rounds", 0)
        if rounds >= Config.MAX_MODIFICATION_ROUNDS:
            await update.message.reply_text(f"⚠️ Max rounds reached for '{job['title']}'. Forcing approval/application...")
            action = "approve"
        else:
            job["modification_rounds"] = rounds + 1
            job["status"] = "pending"
            job["user_feedback"] = instructions
            await update.message.reply_text(f"🔄 Ändere Pitch für '{job['title']}'...")
            
            from graph.nodes.pitch_writer import write_pitch_email
            try:
                new_pitch = await asyncio.to_thread(write_pitch_email, job, job["pain_points"], instructions)
                job["pitch"] = new_pitch
                
                msg_text = (
                    f"🔄 Pitch updated (Round {job['modification_rounds']})\n\n"
                    f"📌 {job['title']}\n"
                    f"🏢 {job.get('company_name', 'Unknown Company')}\n\n"
                    f"✉️ Generierter Pitch:\n"
                    f"─────────────────────\n"
                    f"{new_pitch}\n"
                    f"─────────────────────\n\n"
                    f"Antwort: gut so / überspringen / kürzer machen / ..."
                )
                new_msg = await update.message.reply_text(msg_text)
                job["telegram_message_id"] = new_msg.message_id
                add_or_update_job(job)
            except Exception as e:
                logger.error(f"Failed to regenerate pitch: {e}")
                await update.message.reply_text(f"❌ Fehler bei der Pitch-Generierung: {e}")
                
    if action == "approve":
        job["status"] = "approved"
        add_or_update_job(job)
        await update.message.reply_text(f"🚀 Bewerbung für '{job['title']}' wird abgeschickt...")
        
        from graph.nodes.apply import apply_job
        success = await asyncio.to_thread(apply_job, job)
        if success:
            job["status"] = "applied"
            await update.message.reply_text(f"✅ Bewerbung für '{job['title']}' erfolgreich versendet!")
        else:
            job["status"] = "error"
            await update.message.reply_text(f"❌ Bewerbung für '{job['title']}' fehlgeschlagen (siehe Logs).")
        add_or_update_job(job)
        
        # Send next card in queue
        check_and_send_next_card()

    elif action == "reject":
        job["status"] = "rejected"
        add_or_update_job(job)
        await update.message.reply_text(f"⏭️ Job '{job['title']}' übersprungen.")
        
        # Send next card in queue
        check_and_send_next_card()


async def _message_handler(update, context):
    global _latest_reply
    # Only listen to the configured chat ID
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        logger.warning(f"Received message from unauthorized chat ID: {chat_id}")
        return
    
    text = update.message.text
    if not text:
        return
        
    logger.info(f"Received Telegram message: {text}")
    
    # 1. Identify which job this feedback relates to
    reply_to = update.message.reply_to_message
    job = None
    
    from db.jobs_db import get_job_by_message_id, get_latest_pending_job
    
    if reply_to:
        job = get_job_by_message_id(reply_to.message_id)
        if not job:
            logger.info(f"User replied to message {reply_to.message_id}, but no job found in database.")
            
    # Fallback to the latest pending job
    if not job:
        job = get_latest_pending_job()
        
    if not job:
        await update.message.reply_text("Kein ausstehender Job gefunden, auf den sich diese Nachricht bezieht.")
        return
        
    # Check if job is already decided
    if job.get("status") in ("applied", "rejected", "error"):
        await update.message.reply_text(f"Dieser Job ('{job['title']}') wurde bereits verarbeitet (Status: {job['status']}).")
        return

    # Process feedback in the background
    asyncio.create_task(process_user_feedback(update, job, text))
    
    # Legacy state update for backward compatibility
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
        _loop.run_until_complete(_application.updater.start_polling(drop_pending_updates=True))
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

def send_message_sync(text: str) -> Optional[int]:
    """Send text message synchronously from any thread and return its message ID."""
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID is missing in Config.")
        return None

    async def _send():
        bot_instance = _application.bot if (_application and _application.bot) else Bot(token=Config.TELEGRAM_BOT_TOKEN)
        msg = await bot_instance.send_message(chat_id=Config.TELEGRAM_CHAT_ID, text=text)
        return msg.message_id

    try:
        if _loop and _loop.is_running():
            future = asyncio.run_coroutine_threadsafe(_send(), _loop)
            return future.result(timeout=15)
        else:
            return asyncio.run(_send())
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


def check_and_send_next_card() -> None:
    """Finds the next pending unsent job in the database and sends its card to Telegram if no other job is active."""
    from db.jobs_db import load_jobs, add_or_update_job
    jobs = load_jobs()
    
    # 1. Check if there is an active pending job already sent
    active_pending = [j for j in jobs if j.get("status") == "pending" and j.get("telegram_message_id") is not None]
    if active_pending:
        logger.info("An active pending job card already exists in Telegram. Skipping sending next card.")
        return
        
    # 2. Find the next job in the queue that has not been sent yet
    next_job = None
    for j in jobs:
        if j.get("status") == "pending" and j.get("telegram_message_id") is None:
            next_job = j
            break
            
    if not next_job:
        logger.info("No more unsent pending jobs in database queue.")
        return
        
    # 3. Format message
    pain_points_text = ""
    if next_job.get("pain_points"):
        pain_points_text = "🎯 Pain Points erkannt:\n" + "\n".join(f"• {pt}" for pt in next_job["pain_points"]) + "\n\n"
        
    salary_line = f"💰 {next_job.get('salary_range')}\n" if next_job.get("salary_range") != "null" else ""
    
    msg_text = (
        f"🆕 New Job Found\n\n"
        f"📌 {next_job['title']}\n"
        f"{salary_line}"
        f"🏢 {next_job.get('company_name', 'Unknown Company')}\n"
        f"🔗 {next_job['link']}\n\n"
        f"{pain_points_text}"
        f"✉️ Generierter Pitch:\n"
        f"─────────────────────\n"
        f"{next_job.get('pitch', '')}\n"
        f"─────────────────────\n\n"
        f"Antwort: gut so / überspringen / kürzer machen / ..."
    )
    
    rounds = next_job.get("modification_rounds", 0)
    if rounds >= 3:
        msg_text += "\n\n⚠️ 3 Runden erreicht. Soll ich trotzdem abschicken oder überspringen?"
        
    logger.info(f"Sending next job card to Telegram: '{next_job['title']}'...")
    msg_id = send_message_sync(msg_text)
    
    if msg_id:
        next_job["telegram_message_id"] = msg_id
        add_or_update_job(next_job)
        logger.info(f"Next job card sent successfully. Msg ID: {msg_id}")
    else:
        logger.error(f"Failed to send next job card for '{next_job['title']}'.")

