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
        logger.info(f"Container/button text indicates already applied. Marking as applied.")
        job["status"] = "applied"
        send_message_sync(f"✅ Already applied on website for: {job['title']}")
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
        logger.info("[DRY_RUN] Skipping final submit click.")
        job["status"] = "applied"
        send_message_sync(f"\U0001f4dd [DRY RUN] Pitch filled for {job['title']}. Skipping submission.")
    else:
        logger.info("Submitting application...")
        page.click("div.modal-body >> text=Jetzt Bewerben")
        page.wait_for_timeout(5000)
        job["status"] = "applied"
        send_message_sync(f"\U0001f680 Application Sent for: {job['title']}")


def apply_job(job: Job) -> bool:
    """Synchronously apply to a single job using Playwright cookies. Returns True if successful."""
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

        StealthyFetcher.adaptive = True
        StealthyFetcher.fetch(job["link"], cookies=cookies, page_action=apply_action, headless=True)
    except Exception as e:
        success = False
        error_msg = f"Exception during fetch/apply: {str(e)}"
        job["status"] = "error"
        job["error_message"] = error_msg

    if not success:
        alert_text = (
            f"⚠️ Application Failed\n\n"
            f"Job: {job['title']}\n"
            f"Error: {error_msg}"
        )
        send_message_sync(alert_text)

    return success


def apply_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping apply node due to existing errors.")
        return state

    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    if idx >= len(jobs):
        logger.warning("No job to apply to.")
        return state

    job = jobs[idx]
    if job.get("status") != "approved":
        logger.warning(f"Job status is {job.get('status')}, not approved. Skipping application.")
        return state

    apply_job(job)
    return state


