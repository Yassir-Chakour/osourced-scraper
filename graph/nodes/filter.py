import logging
from graph.state import GraphState
from db.jobs_db import load_jobs

logger = logging.getLogger(__name__)

def filter_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping filter node due to existing errors.")
        return state

    logger.info("Starting filter node (database in-memory deduplication)...")
    scraped_jobs = state.get("jobs", [])
    if not scraped_jobs:
        logger.info("No scraped jobs to filter.")
        return state

    # Load all recorded jobs from database
    existing_jobs = load_jobs()
    
    # Build set of normalized links that are already processed or applied
    # Statuses that we consider already handled: applied, rejected, approved, or error
    processed_links = {
        j["link"].rstrip("/")
        for j in existing_jobs
        if j.get("link") and j.get("status") in ("applied", "rejected")
    }

    new_jobs = []
    skipped_count = 0
    for job in scraped_jobs:
        link = job.get("link", "").rstrip("/")
        if link in processed_links:
            skipped_count += 1
        else:
            new_jobs.append(job)

    logger.info(
        f"Filter results: {len(scraped_jobs)} scraped on site, "
        f"{skipped_count} already applied/handled in database. "
        f"{len(new_jobs)} genuinely new jobs to process."
    )

    state["jobs"] = new_jobs
    state["current_job_index"] = 0
    return state

