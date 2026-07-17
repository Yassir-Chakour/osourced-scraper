import os
import json
import logging
import threading
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)
DB_PATH = "data/jobs_db.json"
_db_lock = threading.Lock()

def load_jobs() -> List[Dict[str, Any]]:
    """Load jobs from the JSON database in a thread-safe manner."""
    if not os.path.exists(DB_PATH):
        return []
    with _db_lock:
        try:
            with open(DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading jobs database: {e}")
            return []

def save_jobs(jobs: List[Dict[str, Any]]) -> None:
    """Save jobs to the JSON database in a thread-safe manner."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _db_lock:
        try:
            with open(DB_PATH, "w", encoding="utf-8") as f:
                json.dump(jobs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving jobs database: {e}")

def add_or_update_job(job: Dict[str, Any]) -> None:
    """Add a new job or update an existing one matched by link."""
    jobs = load_jobs()
    updated = False
    for i, j in enumerate(jobs):
        if j.get("link") == job.get("link"):
            jobs[i] = job
            updated = True
            break
    if not updated:
        jobs.append(job)
    save_jobs(jobs)

def get_job_by_message_id(message_id: int) -> Optional[Dict[str, Any]]:
    """Look up a job by its Telegram message ID."""
    jobs = load_jobs()
    for job in jobs:
        if job.get("telegram_message_id") == message_id:
            return job
    return None

def get_job_by_link(link: str) -> Optional[Dict[str, Any]]:
    """Look up a job by its link."""
    jobs = load_jobs()
    for job in jobs:
        if job.get("link") == link:
            return job
    return None

def get_latest_pending_job() -> Optional[Dict[str, Any]]:
    """Get the latest job with status 'pending' that has been sent to Telegram."""
    jobs = load_jobs()
    pending_jobs = [j for j in jobs if j.get("status") == "pending" and j.get("telegram_message_id") is not None]
    if pending_jobs:
        return pending_jobs[-1]
    return None
