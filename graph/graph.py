import json
import logging
import time
from langgraph.graph import StateGraph, END
from config import Config
from graph.state import GraphState
from graph.nodes.health_check import health_check_node
from graph.nodes.login import login_node
from graph.nodes.scraper import scraper_node
from graph.nodes.filter import filter_node
from graph.nodes.extract_details import extract_details_node
from graph.nodes.pitch_writer import pitch_writer_node
from graph.nodes.notifier import notifier_node
from graph.nodes.reply_handler import reply_handler_node
from graph.nodes.apply import apply_node
from graph.nodes.reporter import reporter_node

logger = logging.getLogger(__name__)

def save_run_state(state: GraphState):
    """Write current state to data/run_state.json for visibility/inspection."""
    try:
        with open("data/run_state.json", "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save run_state.json: {e}")

def wrap_node_with_save(node_func):
    """Wrapper to automatically save state to disk after each node execution."""
    def wrapped(state: GraphState) -> GraphState:
        new_state = node_func(state)
        save_run_state(new_state)
        return new_state
    return wrapped

def next_job_node(state: GraphState) -> GraphState:
    """Helper node to increment the current job index with rate limit sleep."""
    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    
    # If there are more jobs to process, sleep to avoid hitting rate limits
    if idx + 1 < len(jobs):
        delay = getattr(Config, 'RATE_LIMIT_DELAY', 30)
        logger.info(f"Rate limiting: sleeping for {delay} seconds before processing the next job...")
        time.sleep(delay)
        
    state["current_job_index"] = idx + 1
    return state

# Build the StateGraph
workflow = StateGraph(GraphState)

# Add all nodes wrapped with save function
workflow.add_node("health_check", wrap_node_with_save(health_check_node))
workflow.add_node("login", wrap_node_with_save(login_node))
workflow.add_node("scraper", wrap_node_with_save(scraper_node))
workflow.add_node("filter", wrap_node_with_save(filter_node))
workflow.add_node("extract_details", wrap_node_with_save(extract_details_node))
workflow.add_node("pitch_writer", wrap_node_with_save(pitch_writer_node))
workflow.add_node("notifier", wrap_node_with_save(notifier_node))
workflow.add_node("reply_handler", wrap_node_with_save(reply_handler_node))
workflow.add_node("apply", wrap_node_with_save(apply_node))
workflow.add_node("next_job", wrap_node_with_save(next_job_node))
workflow.add_node("reporter", wrap_node_with_save(reporter_node))

# Entry Point
workflow.set_entry_point("health_check")

# Define conditional edges from health check
workflow.add_conditional_edges(
    "health_check",
    lambda state: "reporter" if state.get("errors") else "login",
    {"reporter": "reporter", "login": "login"}
)

# Define conditional edges from login
workflow.add_conditional_edges(
    "login",
    lambda state: "reporter" if state.get("errors") else "scraper",
    {"reporter": "reporter", "scraper": "scraper"}
)

# Define conditional edges from scraper
workflow.add_conditional_edges(
    "scraper",
    lambda state: "reporter" if state.get("errors") else "filter",
    {"reporter": "reporter", "filter": "filter"}
)

# Define conditional edges from filter
def route_after_filter(state: GraphState):
    if state.get("errors"):
        return "reporter"
    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    return "extract_details" if idx < len(jobs) else "reporter"

workflow.add_conditional_edges(
    "filter",
    route_after_filter,
    {"reporter": "reporter", "extract_details": "extract_details"}
)

# Define conditional edges from extract_details
def route_after_extract_details(state: GraphState):
    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    if idx < len(jobs):
        if jobs[idx].get("status") in ("applied", "rejected", "error"):
            return "next_job"
    return "pitch_writer"

workflow.add_conditional_edges(
    "extract_details",
    route_after_extract_details,
    {"next_job": "next_job", "pitch_writer": "pitch_writer"}
)

# Linear flow for pitch writing and feedback
workflow.add_edge("pitch_writer", "notifier")
workflow.add_edge("notifier", "reply_handler")

# Define conditional edges from reply_handler
def route_after_reply_handler(state: GraphState):
    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    if idx < len(jobs):
        status = jobs[idx].get("status")
        if status == "pending":
            return "pitch_writer"
        elif status == "approved":
            return "apply"
    return "next_job"

workflow.add_conditional_edges(
    "reply_handler",
    route_after_reply_handler,
    {
        "pitch_writer": "pitch_writer",
        "apply": "apply",
        "next_job": "next_job"
    }
)

# Edge from apply to next_job
workflow.add_edge("apply", "next_job")

# Define conditional edges from next_job
def route_after_next_job(state: GraphState):
    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    return "extract_details" if idx < len(jobs) else "reporter"

workflow.add_conditional_edges(
    "next_job",
    route_after_next_job,
    {"extract_details": "extract_details", "reporter": "reporter"}
)

# Reporter is the final node
workflow.add_edge("reporter", END)

# Compile the graph
app = workflow.compile()
