import os
import json
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, Page
from config import Config
from graph.state import GraphState, Job
from telegram_bot.bot import send_message_sync, send_photo_sync

logger = logging.getLogger(__name__)


def record_applied_job(job: Job, status: str = "applied"):
    """Record job in the permanent applied_jobs.json file."""
    applied_jobs_path = "data/applied_jobs.json"
    os.makedirs("data", exist_ok=True)

    data = {"applied": []}
    if os.path.exists(applied_jobs_path):
        try:
            with open(applied_jobs_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read applied_jobs.json: {e}")

    # Check for duplicates to avoid writing the same job twice
    if not any(item.get("url") == job["link"] for item in data.get("applied", [])):
        data["applied"].append({
            "url": job["link"],
            "applied_at": datetime.now().isoformat(),
            "title": job["title"],
            "status": status
        })

        try:
            with open(applied_jobs_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Recorded job ({status}) in applied_jobs.json: {job['title']}")
        except Exception as e:
            logger.error(f"Failed to write to applied_jobs.json: {e}")


def _fill_and_submit_application(page: Page, job: Job) -> None:
    """Click apply, fill the pitch textarea, and submit (or skip submit in dry-run)."""
    apply_btn = page.query_selector('div.cs-text button')
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

    record_applied_job(job)


def _take_apply_failure_screenshot(page: Page) -> str | None:
    """Capture a timestamped screenshot on apply failure and return its path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("screenshots", exist_ok=True)
    path = f"screenshots/apply_fail_{timestamp}.png"
    try:
        page.screenshot(path=path)
        return path
    except Exception as se:
        logger.error(f"Failed to capture screenshot: {se}")
        return None


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

    logger.info(f"Applying to job: {job['title']} (DRY_RUN={Config.DRY_RUN})")
    auth_state_path = "data/auth.json"
    success = True
    error_msg = ""
    screenshot_path = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=auth_state_path)
        page = context.new_page()

        try:
            page.goto(job["link"])
            _fill_and_submit_application(page, job)
        except Exception as e:
            success = False
            error_msg = f"Exception during application submission: {str(e)}"
            logger.error(error_msg)
            job["status"] = "error"
            job["error_message"] = error_msg

        if not success:
            screenshot_path = _take_apply_failure_screenshot(page)

        browser.close()

    if not success:
        alert_text = (
            f"\u26a0\ufe0f Application Failed\n\n"
            f"Job: {job['title']}\n"
            f"Error: {error_msg}\n"
            f"Run ID: {state.get('run_id')}"
        )
        if screenshot_path and os.path.exists(screenshot_path):
            send_photo_sync(screenshot_path, caption=alert_text)
        else:
            send_message_sync(alert_text)

    return state
