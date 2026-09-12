import logging
import json
from playwright.sync_api import Page
from scrapling.fetchers import StealthyFetcher
from config import Config
from graph.state import GraphState, Job
from telegram_bot.bot import send_message_sync

logger = logging.getLogger(__name__)


def _fill_and_submit_application(page: Page, job: Job) -> None:
    """Click apply, fill the pitch textarea, and submit (or skip submit in dry-run)."""
    # Check if we already applied (check container/button instead of whole page to avoid chat history false positives)
    cs_text_el = page.query_selector('div.cs-text')
    cs_text_content = cs_text_el.text_content() if cs_text_el else ""
    apply_btn = page.query_selector('div.cs-text button')
    
    already_applied = False
    if apply_btn:
        btn_text = apply_btn.text_content() or ""
        if "beworben" in btn_text.lower():
            already_applied = True
            
    if not already_applied and cs_text_content:
        if "beworben" in cs_text_content.lower():
            already_applied = True

    if already_applied:
        logger.info(f"Container/button text indicates already applied for '{job['title']}'. Marking as applied.")
        job["status"] = "applied"
        return

    if not apply_btn:
        raise ValueError("Apply button not found on job page.")

    apply_btn.click()
    page.wait_for_timeout(2000)

    textarea = page.query_selector('textarea')
    if not textarea:
        raise ValueError("Modal textarea not found.")

    textarea.fill(job["pitch"])
    page.wait_for_timeout(1000)

    if Config.DRY_RUN:
        logger.info(f"[DRY_RUN] Pitch filled for {job['title']}. Skipping submission.")
        job["status"] = "applied"
    else:
        logger.info(f"Submitting application for {job['title']}...")
        page.click("div.modal-body >> text=Jetzt Bewerben")
        page.wait_for_timeout(5000)
        job["status"] = "applied"


def apply_job(job: Job) -> bool:
    """Synchronously apply to a single job using Playwright cookies. Returns True if successful."""
    import concurrent.futures
    from db.jobs_db import add_or_update_job

    logger.info(f"Applying to job: {job['title']} (DRY_RUN={Config.DRY_RUN})")
    auth_state_path = "data/auth.json"
    success = True
    error_msg = ""

    try:
        with open(auth_state_path, "r", encoding="utf-8") as f:
            auth_data = json.load(f)
        cookies = auth_data.get("cookies", [])

        def apply_action(page: Page):
            nonlocal success, error_msg
            try:
                _fill_and_submit_application(page, job)
            except Exception as e:
                success = False
                error_msg = f"Exception during application submission: {str(e)}"
                logger.error(error_msg)
                job["status"] = "error"
                job["error_message"] = error_msg

        def _do_fetch_and_apply():
            StealthyFetcher.adaptive = True
            StealthyFetcher.fetch(job["link"], cookies=cookies, page_action=apply_action, headless=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_fetch_and_apply)
            future.result(timeout=60)

    except concurrent.futures.TimeoutError:
        success = False
        error_msg = f"Apply timed out after 60s for {job['link']}"
        logger.error(error_msg)
        job["status"] = "error"
        job["error_message"] = error_msg
    except Exception as e:
        success = False
        error_msg = f"Exception during fetch/apply: {str(e)}"
        logger.error(error_msg)
        job["status"] = "error"
        job["error_message"] = error_msg

    # Persist the final status to DB
    add_or_update_job(job)

    if not success:
        logger.warning(f"Application failed for '{job['title']}': {error_msg}")

    return success


def apply_node(state: GraphState) -> GraphState:
    """Directly applies to the job currently being processed."""
    if state.get("errors"):
        logger.warning("Skipping apply node due to existing errors.")
        return state

    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    if idx >= len(jobs):
        logger.warning("No job to apply to.")
        return state

    job = jobs[idx]
    if job.get("status") in ("applied", "rejected", "error"):
        logger.info(f"Job status is {job.get('status')}. Skipping application.")
        return state

    apply_job(job)
    return state



