import os
import json
import logging
from graph.state import GraphState
from telegram_bot.bot import send_message_sync

logger = logging.getLogger(__name__)

def filter_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping filter node due to existing errors.")
        return state
        
    logger.info("Starting filter node...")
    applied_jobs_path = "data/applied_jobs.json"
    
    applied_urls = set()
    if os.path.exists(applied_jobs_path):
        try:
            with open(applied_jobs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                applied_list = data.get("applied", [])
                for item in applied_list:
                    if "url" in item:
                        applied_urls.add(item["url"])
        except Exception as e:
            logger.error(f"Failed to read applied_jobs.json: {e}")
            
    filtered_jobs = []
    for job in state.get("jobs", []):
        if job["link"] in applied_urls:
            logger.info(f"Filtering out already applied job: {job['title']} ({job['link']})")
        else:
            filtered_jobs.append(job)
            
    logger.info(f"Jobs before filtering: {len(state.get('jobs', []))}, after filtering: {len(filtered_jobs)}")
    
    state["jobs"] = filtered_jobs
    state["current_job_index"] = 0
    
    if not filtered_jobs:
        msg = "All found jobs have already been applied to."
        logger.info(msg)
        send_message_sync(msg)
        # Add a specific error/flag so we terminate gracefully
        state["errors"].append("all_jobs_filtered")
        
    return state
