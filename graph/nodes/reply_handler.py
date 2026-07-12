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
    
    fb = user_feedback.lower().strip().strip("!.,?-")
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
        prompt = manager.render("reply_handler.jinja", user_feedback=user_feedback)
        action = "modify"
        instructions = user_feedback

        try:
            response_text = call_llm(prompt, json_mode=True)
            if response_text:
                data = json.loads(response_text)
                raw_action = data.get("action", "modify").lower().strip()
                # Normalize action output from LLM
                if raw_action in ("send", "apply", "approve", "yes", "go"):
                    action = "approve"
                elif raw_action in ("reject", "skip", "no"):
                    action = "reject"
                else:
                    action = "modify"
                instructions = data.get("modification_instructions", user_feedback)
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.error(f"Failed to classify reply via LLM: {e}")
            # Fallback simple keyword search in case LLM is completely down
            if any(w in fb for w in approve_keywords):
                action = "approve"
            elif any(w in fb for w in reject_keywords):
                action = "reject"
            else:
                action = "modify"

    # Check max modification rounds constraint
    rounds = job.get("modification_rounds", 0)
    if action == "modify":
        if rounds >= Config.MAX_MODIFICATION_ROUNDS:
            logger.warning(f"Max modification rounds ({Config.MAX_MODIFICATION_ROUNDS}) reached. Forcing approval to apply since user always applies.")
            action = "approve"
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
        
    return state
