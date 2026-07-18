import asyncio
import threading
import logging
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackQueryHandler
from config import Config

logger = logging.getLogger(__name__)

# Shared variables for thread communication
_reply_event = threading.Event()
_latest_reply = None
_loop = None
_thread = None
_application = None
_session_job_links = set()

from typing import Optional

async def process_user_feedback(update, job, text: str):
    fb = text.lower().strip().strip("!.,?-")
    action = None
    instructions = ""
    
    # Identify message object to reply to
    msg = None
    if hasattr(update, "message") and update.message:
        msg = update.message
    elif hasattr(update, "callback_query") and update.callback_query:
        msg = update.callback_query.message
    else:
        msg = getattr(update, "message", None)
        
    if not msg:
        logger.error("Could not find message object to reply to.")
        return
    
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
            await msg.reply_text(f"⚠️ Max rounds reached for '{job['title']}'. Forcing approval/application...")
            action = "approve"
        else:
            job["modification_rounds"] = rounds + 1
            job["status"] = "pending"
            job["user_feedback"] = instructions
            await msg.reply_text(f"🔄 Ändere Pitch für '{job['title']}'...")
            
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
                new_msg = await msg.reply_text(msg_text, reply_markup=_get_job_card_keyboard())
                job["telegram_message_id"] = new_msg.message_id
                add_or_update_job(job)
            except Exception as e:
                logger.error(f"Failed to regenerate pitch: {e}")
                await msg.reply_text(f"❌ Fehler bei der Pitch-Generierung: {e}")
                
    if action in ("approve", "reject"):
        # Remove buttons from original job card
        if job.get("telegram_message_id"):
            try:
                await _application.bot.edit_message_reply_markup(
                    chat_id=Config.TELEGRAM_CHAT_ID,
                    message_id=job["telegram_message_id"],
                    reply_markup=None
                )
            except Exception as e:
                logger.warning(f"Could not remove keyboard markup: {e}")

    if action == "approve":
        job["status"] = "approved"
        add_or_update_job(job)
        await msg.reply_text(f"🚀 Bewerbung für '{job['title']}' wird abgeschickt...")
        
        from graph.nodes.apply import apply_job
        success = await asyncio.to_thread(apply_job, job)
        if success:
            job["status"] = "applied"
            await msg.reply_text(f"✅ Bewerbung für '{job['title']}' erfolgreich versendet!")
        else:
            job["status"] = "error"
            await msg.reply_text(f"❌ Bewerbung für '{job['title']}' fehlgeschlagen (siehe Logs).")
        add_or_update_job(job)
        
        # Send next card in queue
        await check_and_send_next_card_async()

    elif action == "reject":
        job["status"] = "rejected"
        add_or_update_job(job)
        await msg.reply_text(f"⏭️ Job '{job['title']}' übersprungen.")
        
        # Send next card in queue
        await check_and_send_next_card_async()


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
    
    # Check for send all command
    if text.lower().strip() in ("send all", "alles senden"):
        asyncio.create_task(send_all_jobs(update))
        return
    
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


def _get_job_card_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("🚀 Abschicken (Send)", callback_data="approve"),
            InlineKeyboardButton("⏭️ Überspringen (Skip)", callback_data="reject")
        ],
        [
            InlineKeyboardButton("⚡ Alle Abschicken (Send All)", callback_data="send_all")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_final_session_report() -> None:
    global _session_job_links
    if not _session_job_links:
        return
        
    from db.jobs_db import load_jobs
    all_jobs = load_jobs()
    
    session_jobs = [j for j in all_jobs if j.get("link") in _session_job_links]
    if not session_jobs:
        return
        
    applied = 0
    rejected = 0
    error_count = 0
    
    job_details_lines = []
    for job in session_jobs:
        status = job.get("status", "pending")
        title = job.get("title", "Unknown Title")
        if status == "applied":
            applied += 1
            job_details_lines.append(f"✅ Applied: {title}")
        elif status == "rejected":
            rejected += 1
            job_details_lines.append(f"⏭️ Skipped: {title}")
        elif status == "error":
            error_count += 1
            job_details_lines.append(f"❌ Error: {title} ({job.get('error_message', 'Unknown error')})")
            
    report_lines = [
        "📊 Osourced Scraper Session Report",
        f"Total Jobs Processed: {len(session_jobs)}",
        f"• Applied: {applied}",
        f"• Skipped/Rejected: {rejected}",
        f"• Errors: {error_count}",
    ]
    
    if job_details_lines:
        report_lines.append("\n📋 Job Breakdown:")
        report_lines.extend(job_details_lines)
        
    report_text = "\n".join(report_lines)
    
    logger.info("Sending final session report to Telegram...")
    await send_message_async(report_text)
    _session_job_links.clear()


async def send_all_jobs(update_or_query) -> None:
    from db.jobs_db import load_jobs, add_or_update_job
    from graph.nodes.apply import apply_job
    
    jobs = load_jobs()
    pending_jobs = [j for j in jobs if j.get("status") == "pending"]
    
    is_query = hasattr(update_or_query, "answer")
    msg_target = update_or_query.message if is_query else update_or_query.message
    
    if not pending_jobs:
        await msg_target.reply_text("Keine ausstehenden Bewerbungen zum Abschicken gefunden.")
        return
        
    if is_query:
        try:
            await update_or_query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
            
    status_msg = await msg_target.reply_text(f"⚡ Sende {len(pending_jobs)} ausstehende Bewerbungen ab...")
    
    for job in pending_jobs:
        _session_job_links.add(job["link"])
        
        # Ensure pitch is generated
        if not job.get("pitch"):
            from graph.nodes.pitch_writer import pitch_writer_node
            from graph.state import GraphState
            dummy_state: GraphState = {"jobs": [job], "current_job_index": 0, "errors": []}
            try:
                pitch_writer_node(dummy_state)
                job = dummy_state["jobs"][0]
            except Exception as e:
                logger.error(f"Failed to generate pitch for send_all: {e}")
                
        await status_msg.reply_text(f"⏳ Bewerbe für: {job['title']}...")
        success = await asyncio.to_thread(apply_job, job)
        if success:
            job["status"] = "applied"
        else:
            job["status"] = "error"
        add_or_update_job(job)
        
    await status_msg.reply_text("✅ Alle ausstehenden Bewerbungen verarbeitet!")
    await send_final_session_report()


async def _callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    chat_id = update.effective_chat.id
    if str(chat_id) != str(Config.TELEGRAM_CHAT_ID):
        logger.warning(f"Received callback from unauthorized chat ID: {chat_id}")
        return
        
    data = query.data
    logger.info(f"Received CallbackQuery: {data}")
    
    if data == "send_all":
        asyncio.create_task(send_all_jobs(query))
        return
        
    message_id = query.message.message_id
    from db.jobs_db import get_job_by_message_id
    job = get_job_by_message_id(message_id)
    
    if not job:
        await query.message.reply_text("Kein ausstehender Job zu dieser Nachricht gefunden.")
        return
        
    if job.get("status") in ("applied", "rejected", "error"):
        await query.message.reply_text(f"Dieser Job ('{job['title']}') wurde bereits verarbeitet (Status: {job['status']}).")
        return
        
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
        
    if data == "approve":
        asyncio.create_task(process_user_feedback(query, job, "ja"))
    elif data == "reject":
        asyncio.create_task(process_user_feedback(query, job, "skip"))


def start_bot():
    global _loop, _thread, _application
    if _thread and _thread.is_alive():
        logger.warning("Telegram Bot is already running.")
        return

    _loop = asyncio.new_event_loop()
    _application = ApplicationBuilder().token(Config.TELEGRAM_BOT_TOKEN).build()
    _application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _message_handler))
    _application.add_handler(CallbackQueryHandler(_callback_handler))
    
    def run_app():
        asyncio.set_event_loop(_loop)
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


async def send_message_async(text: str, reply_markup=None) -> Optional[int]:
    """Send text message asynchronously (must be called from the event loop thread)."""
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID is missing in Config.")
        return None
    bot_instance = _application.bot if (_application and _application.bot) else Bot(token=Config.TELEGRAM_BOT_TOKEN)
    msg = await bot_instance.send_message(chat_id=Config.TELEGRAM_CHAT_ID, text=text, reply_markup=reply_markup)
    return msg.message_id


def send_message_sync(text: str, reply_markup=None) -> Optional[int]:
    """Send text message synchronously from any thread and return its message ID."""
    if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
        logger.error("Telegram bot token or chat ID is missing in Config.")
        return None

    try:
        if _loop and _loop.is_running():
            future = asyncio.run_coroutine_threadsafe(send_message_async(text, reply_markup), _loop)
            return future.result(timeout=15)
        else:
            import concurrent.futures
            def run_in_new_loop():
                return asyncio.run(send_message_async(text, reply_markup))
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(run_in_new_loop)
                return future.result(timeout=15)
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


async def check_and_send_next_card_async() -> None:
    """Finds the next pending unsent job in the database and sends its card to Telegram if no other job is active (async version)."""
    from db.jobs_db import load_jobs, add_or_update_job
    jobs = load_jobs()
    
    # Check if there are no more pending jobs at all
    pending_unsent = [j for j in jobs if j.get("status") == "pending" and j.get("telegram_message_id") is None]
    pending_sent = [j for j in jobs if j.get("status") == "pending" and j.get("telegram_message_id") is not None]
    
    if not pending_unsent and not pending_sent:
        logger.info("No more pending jobs in database queue.")
        await send_final_session_report()
        return

    # 1. Check if there is an active pending job already sent
    if pending_sent:
        logger.info("An active pending job card already exists in Telegram. Skipping sending next card.")
        return
        
    # 2. Find the next job in the queue that has not been sent yet
    next_job = pending_unsent[0]
        
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
        
    logger.info(f"Sending next job card to Telegram (async): '{next_job['title']}'...")
    
    # Track link in session
    _session_job_links.add(next_job["link"])
    
    msg_id = await send_message_async(msg_text, reply_markup=_get_job_card_keyboard())
    
    if msg_id:
        next_job["telegram_message_id"] = msg_id
        add_or_update_job(next_job)
        logger.info(f"Next job card sent successfully. Msg ID: {msg_id}")
    else:
        logger.error(f"Failed to send next job card for '{next_job['title']}'.")


def check_and_send_next_card() -> None:
    """Finds the next pending unsent job in the database and sends its card to Telegram if no other job is active (sync wrapper)."""
    if _loop and _loop.is_running():
        future = asyncio.run_coroutine_threadsafe(check_and_send_next_card_async(), _loop)
        future.result(timeout=15)
    else:
        asyncio.run(check_and_send_next_card_async())

