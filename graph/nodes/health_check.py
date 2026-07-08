import os
import logging
from datetime import datetime
from playwright.sync_api import sync_playwright, Page
from config import Config
from graph.state import GraphState
from telegram_bot.bot import send_photo_sync, send_message_sync

logger = logging.getLogger(__name__)

_LOGIN_BUTTON_SELECTORS = [
    "a:has-text('Log-in')",
    "a:has-text('Anmeldung')",
    "#btn-header-main-login",
    ".login-btn a",
]


def _click_first_visible_login_button(page: Page) -> bool:
    """Click whichever login-button selector is visible first. Returns True on success."""
    for sel in _LOGIN_BUTTON_SELECTORS:
        try:
            el = page.locator(sel).first
            if el.is_visible():
                el.click()
                logger.info(f"Clicked login button using selector: {sel}")
                return True
        except Exception:
            continue
    return False


def _login_and_navigate_to_jobs(page: Page) -> None:
    """Perform credential login and return to the jobs listing page."""
    logger.info(f"Navigating to login page: {Config.URL_LOGIN}")
    page.goto(Config.URL_LOGIN)

    if not _click_first_visible_login_button(page):
        logger.warning("Could not find or click a visible login button. Trying to proceed anyway...")

    page.fill('input[name="user_login"]', Config.USER_LOGIN)
    page.fill('input[name="user_pass"]', Config.USER_PASS)
    page.click('input[name="user-submit"]')
    page.wait_for_timeout(5000)

    logger.info(f"Navigating back to jobs page: {Config.URL_LOGIN}")
    page.goto(Config.URL_LOGIN)


def _verify_job_page_selectors(page: Page) -> tuple[bool, str]:
    """Check job-listing and job-detail selectors. Returns (passed, error_message)."""
    job_links = page.query_selector_all('h3 a')
    if not job_links:
        return False, "Selector 'h3 a' (job listings) returned 0 results."

    first_job_url = job_links[0].get_attribute('href')
    if not first_job_url:
        return False, "Could not retrieve href from first job link."

    logger.info(f"Visiting test job URL: {first_job_url}")
    page.goto(first_job_url)

    if not page.query_selector("div.job-description"):
        return False, "Selector 'div.job-description' (job description) returned 0 results."

    if not page.query_selector_all("div.job-detail strong"):
        logger.warning(
            "Selector 'div.job-detail strong' (salary info) returned 0 results, "
            "but continuing as salary might be optional."
        )

    return True, ""


def _take_failure_screenshot(page: Page) -> str | None:
    """Capture a timestamped screenshot and return the path, or None on failure."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"screenshots/health_check_fail_{timestamp}.png"
    try:
        page.screenshot(path=path)
        logger.info(f"Screenshot saved to {path}")
        return path
    except Exception as se:
        logger.error(f"Failed to capture screenshot: {se}")
        return None


def _notify_health_check_failure(error_msg: str, run_id: str, screenshot_path: str | None) -> None:
    """Send Telegram alert when health-check fails."""
    alert_text = (
        f"⚠️ Bot Alert\n\n"
        f"Node: health_check\n"
        f"Error: {error_msg}\n"
        f"Run ID: {run_id}\n\n"
        f"Bot stopped. Manual check needed."
    )
    if screenshot_path and os.path.exists(screenshot_path):
        send_photo_sync(screenshot_path, caption=alert_text)
    else:
        send_message_sync(alert_text)


def health_check_node(state: GraphState) -> GraphState:
    logger.info("Starting health check...")
    Config.validate()
    os.makedirs("screenshots", exist_ok=True)

    success = True
    error_msg = ""
    screenshot_path = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context().new_page()

        try:
            _login_and_navigate_to_jobs(page)
            success, error_msg = _verify_job_page_selectors(page)
        except Exception as e:
            success = False
            error_msg = f"Exception during health check: {str(e)}"

        if not success:
            screenshot_path = _take_failure_screenshot(page)

        browser.close()

    if not success:
        logger.error(f"Health check failed: {error_msg}")
        _notify_health_check_failure(error_msg, state.get('run_id', ''), screenshot_path)
        state["errors"].append(error_msg)
    else:
        logger.info("Health check passed successfully.")

    return state
