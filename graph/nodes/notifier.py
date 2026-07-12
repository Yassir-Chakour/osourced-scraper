import logging
from graph.state import GraphState
from telegram_bot.bot import send_message_sync
from data.jobs_db import add_or_update_job


logger = logging.getLogger(__name__)

def notifier_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping notifier node due to existing errors.")
        return state
        
    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    if idx >= len(jobs):
        logger.warning("No job to notify.")
        return state
        
    job = jobs[idx]
    
    # If the job status is already applied, skipped, or error, skip notifying
    if job.get("status") in ("applied", "rejected", "error"):
        logger.info(f"Job status is {job['status']}, skipping notifier node.")
        return state
        
    # Format message
    pain_points_text = ""
    if job.get("pain_points"):
        pain_points_text = "🎯 Pain Points erkannt:\n" + "\n".join(f"• {pt}" for pt in job["pain_points"]) + "\n\n"
        
    salary_line = f"💰 {job.get('salary_range')}\n" if job.get("salary_range") != "null" else ""
    
    msg_text = (
        f"🆕 New Job Found\n\n"
        f"📌 {job['title']}\n"
        f"{salary_line}"
        f"🏢 {job.get('company_name', 'Unknown Company')}\n"
        f"🔗 {job['link']}\n\n"
        f"{pain_points_text}"
        f"✉️ Generierter Pitch:\n"
        f"─────────────────────\n"
        f"{job.get('pitch', '')}\n"
        f"─────────────────────\n\n"
        f"Antwort: gut so / überspringen / kürzer machen / ..."
    )
    
    # Check if max rounds reached and we need to warn user
    rounds = job.get("modification_rounds", 0)
    if rounds >= 3:
        msg_text += "\n\n⚠️ 3 Runden erreicht. Soll ich trotzdem abschicken oder überspringen?"
        
    job["status"] = "pending"
    job["telegram_message_id"] = None

    # Persist in the database
    add_or_update_job(job)
    logger.info(f"Saved job '{job['title']}' to database with status 'pending' (unsent).")

    return state


