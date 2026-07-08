import json
import logging
import requests
from config import Config
from graph.state import GraphState, Job
from graph.nodes.pitch_writer import call_llm
from prompts.template_manager import manager

logger = logging.getLogger(__name__)

def reply_handler_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping reply_handler node due to existing errors.")
        return state
        
    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    if idx >= len(jobs):
        logger.warning("No job to handle reply for.")
        return state
        
    job = jobs[idx]
    
    # If the job status is already decided, skip
    if job.get("status") in ("applied", "rejected", "error"):
        logger.info(f"Job status is {job['status']}, skipping reply handler.")
        return state
        
    user_feedback = job.get("user_feedback", "").strip()
    logger.info(f"Analyzing user feedback: '{user_feedback}'")
    
    prompt = manager.render("reply_handler.jinja", user_feedback=user_feedback)

    action = "modify"
    instructions = user_feedback

    try:
        response_text = call_llm(prompt, json_mode=True)
        if response_text:
            data = json.loads(response_text)
            action = data.get("action", "modify").lower()
            instructions = data.get("modification_instructions", user_feedback)
    except (requests.RequestException, json.JSONDecodeError) as e:
        logger.error(f"Failed to classify reply via LLM: {e}")
        fb = user_feedback.lower()
        if any(w in fb for w in ("gut", "schicken", "ok", "yes", "passt", "senden", "go", "perfekt", "ja", "yep")):
            action = "approve"
        elif any(w in fb for w in ("\u00fcberspringen", "nein", "skip", "nope", "n\u00e4chste", "ne", "lassen")):
            action = "reject"
        else:
            action = "modify"

    # Check max modification rounds constraint
    rounds = job.get("modification_rounds", 0)
    if action == "modify":
        if rounds >= Config.MAX_MODIFICATION_ROUNDS:
            logger.warning(f"Max modification rounds ({Config.MAX_MODIFICATION_ROUNDS}) reached. Treating modify action as skip/reject.")
            action = "reject"
        else:
            job["modification_rounds"] = rounds + 1
            job["status"] = "pending"
            job["user_feedback"] = instructions
            logger.info(f"Job marked for modification round {job['modification_rounds']}. Instructions: {instructions}")
            
    if action == "approve":
        job["status"] = "approved"
        logger.info("Job action approved.")
        
    elif action == "reject":
        job["status"] = "rejected"
        logger.info("Job action rejected/skipped.")
        from graph.nodes.apply import record_applied_job
        record_applied_job(job, status="rejected")
        
    return state
