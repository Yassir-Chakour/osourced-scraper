import logging
from graph.state import GraphState
from telegram_bot.bot import send_message_sync

logger = logging.getLogger(__name__)

def reporter_node(state: GraphState) -> GraphState:
    logger.info("Generating final run report...")
    
    run_id = state.get("run_id", "unknown")
    jobs = state.get("jobs", [])
    global_errors = state.get("errors", [])
    
    total = len(jobs)
    applied = 0
    rejected = 0
    error_count = 0
    pending = 0
    
    job_details_lines = []
    for job in jobs:
        status = job.get("status", "pending")
        title = job.get("title", "Unknown Title")
        if status == "applied":
            applied += 1
            job_details_lines.append(f"\u2705 Applied: {title}")
        elif status == "rejected":
            rejected += 1
            job_details_lines.append(f"\u23ed\ufe0f Skipped: {title}")
        elif status == "error":
            error_count += 1
            job_details_lines.append(f"\u274c Error: {title} ({job.get('error_message', 'Unknown error')})")
        else:
            pending += 1
            job_details_lines.append(f"\u23f3 Pending/Unresolved: {title}")
            
    # Compile summary report
    report_lines = [
        "📊 Osourced Scraper Run Report",
        f"Run ID: {run_id}",
        f"Total Jobs Found/Checked: {total}",
        f"• Applied: {applied}",
        f"• Skipped/Rejected: {rejected}",
        f"• Errors: {error_count}",
    ]
    
    if pending > 0:
        report_lines.append(f"• Pending/Unresolved: {pending}")
        
    if global_errors:
        report_lines.append(f"\n⚠️ Global Errors during run:")
        for err in global_errors:
            report_lines.append(f"- {err}")
            
    if job_details_lines:
        report_lines.append("\n📋 Job Breakdown:")
        report_lines.extend(job_details_lines)
        
    report_text = "\n".join(report_lines)
    
    logger.info("Sending final report to Telegram...")
    send_message_sync(report_text)
    
    return state
