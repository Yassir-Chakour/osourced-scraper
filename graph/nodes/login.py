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


def _fill_and_submit_credentials(page: Page) -> None:
    """Type credentials and submit the login form."""
    logger.info("Typing credentials...")
    page.fill('input[name="user_login"]', Config.USER_LOGIN)
    page.fill('input[name="user_pass"]', Config.USER_PASS)
    logger.info("Clicking Submit...")
    page.click('input[name="user-submit"]')
    logger.info("Waiting for login to finish...")
    page.wait_for_timeout(5000)


def _save_login_failure_screenshot(page: Page) -> str | None:
    """Capture a timestamped screenshot on login failure and return its path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"screenshots/login_fail_{timestamp}.png"
    try:
        page.screenshot(path=path)
        logger.info(f"Screenshot saved to {path}")
        return path
    except Exception as se:
        logger.error(f"Failed to capture screenshot: {se}")
        return None


def login_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping login node due to existing errors.")
        return state

    logger.info("Starting login node...")
    Config.validate()
    os.makedirs("data", exist_ok=True)
    os.makedirs("screenshots", exist_ok=True)
    auth_state_path = "data/auth.json"

    success = True
    error_msg = ""
    screenshot_path = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            logger.info(f"Navigating to login page: {Config.URL_LOGIN}")
            page.goto(Config.URL_LOGIN)

            logger.info("Looking for Login button...")
            if not _click_first_visible_login_button(page):
                logger.warning("Could not find or click a visible login button. Trying to proceed anyway...")

            _fill_and_submit_credentials(page)
            context.storage_state(path=auth_state_path)
            logger.info(f"Storage state saved successfully to {auth_state_path}")

        except Exception as e:
            success = False
            error_msg = f"Exception during login: {str(e)}"

        if not success:
            screenshot_path = _save_login_failure_screenshot(page)

        browser.close()

    if not success:
        logger.error(f"Login failed: {error_msg}")
        alert_text = (
            f"\u26a0\ufe0f Bot Alert\n\n"
            f"Node: login\n"
            f"Error: {error_msg}\n"
            f"Run ID: {state.get('run_id')}\n\n"
            f"Bot stopped. Manual check needed."
        )
        if screenshot_path and os.path.exists(screenshot_path):
            send_photo_sync(screenshot_path, caption=alert_text)
        else:
            send_message_sync(alert_text)

        state["errors"].append(error_msg)

    return state
