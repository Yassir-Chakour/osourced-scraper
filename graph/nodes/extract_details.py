import logging
from playwright.sync_api import sync_playwright, Page
from graph.state import GraphState

logger = logging.getLogger(__name__)


def _extract_company_name(page: Page) -> str:
    """Return company name from the first matching selector, or 'Unknown Company'."""
    for selector in (
        "div.company-name",
        "span.company",
        ".job-detail h4",
        "div.job-detail h4",
        "h4",
    ):
        el = page.query_selector(selector)
        if el:
            return el.inner_text().strip()
    return "Unknown Company"


def _extract_salary_range(page: Page) -> str:
    """Return formatted salary range from job-detail strong elements."""
    salary_els = page.query_selector_all("div.job-detail strong")
    if len(salary_els) >= 2:
        return f"{salary_els[0].inner_text().strip()} - {salary_els[1].inner_text().strip()}"
    if len(salary_els) == 1:
        return salary_els[0].inner_text().strip()
    return "null"


def extract_details_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping extract_details node due to existing errors.")
        return state

    idx = state.get("current_job_index", 0)
    jobs = state.get("jobs", [])
    if idx >= len(jobs):
        logger.warning("No job to process at index.")
        return state

    job = jobs[idx]
    logger.info(f"Extracting details for job: {job['title']} ({job['link']})")
    auth_state_path = "data/auth.json"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=auth_state_path)
        page = context.new_page()

        try:
            page.goto(job["link"])

            apply_btn = page.query_selector('div.cs-text button')
            if not apply_btn:
                # No apply button means we already applied or listing closed.
                logger.info(f"No apply button found for job: {job['title']}. Marking as applied/skipped.")
                job["status"] = "applied"
                browser.close()
                return state

            desc_el = page.query_selector("div.job-description")
            job["description"] = desc_el.inner_text().strip() if desc_el else "No description available"
            job["salary_range"] = _extract_salary_range(page)
            job["company_name"] = _extract_company_name(page)

            logger.info(
                f"Extracted: Salary: {job['salary_range']}, "
                f"Company: {job['company_name']}, Desc length: {len(job['description'])}"
            )

        except Exception as e:
            logger.error(f"Error extracting details for {job['link']}: {e}")
            job["status"] = "error"
            job["error_message"] = str(e)

        browser.close()

    return state
