import json
import logging
from scrapling.fetchers import StealthyFetcher
from graph.state import GraphState

logger = logging.getLogger(__name__)


def _extract_company_name(response) -> str:
    """Return company name from the first matching selector, or 'Unknown Company'."""
    for selector in (
        "div.company-name",
        "span.company",
        ".job-detail h4",
        "div.job-detail h4",
        "h4",
    ):
        el = response.css(selector, adaptive=True)
        if el:
            txt = el[0].css('::text').get()
            if txt:
                return txt.strip()
    return "Unknown Company"


def _extract_salary_range(response) -> str:
    """Return formatted salary range from job-detail strong elements."""
    salary_els = response.css("div.job-detail strong", adaptive=True)
    if len(salary_els) >= 2:
        return f"{salary_els[0].css('::text').get().strip()} - {salary_els[1].css('::text').get().strip()}"
    if len(salary_els) == 1:
        return salary_els[0].css('::text').get().strip()
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
    
    # Fast path: skip if details are already extracted (e.g. pending job loaded from DB)
    if job.get("description") and job.get("company_name"):
        logger.info(f"Details already extracted for: {job['title']}")
        return state

    logger.info(f"Extracting details for job: {job['title']} ({job['link']})")
    auth_state_path = "data/auth.json"

    try:
        with open(auth_state_path, "r", encoding="utf-8") as f:
            auth_data = json.load(f)
        cookies = auth_data.get("cookies", [])

        StealthyFetcher.adaptive = True
        response = StealthyFetcher.fetch(job["link"], cookies=cookies, headless=True)

        # Check if we already applied (website shows "Beworben" text)
        all_text = response.get_all_text() or ""
        already_applied = "Beworben" in all_text or "Sie haben sich bereits beworben" in all_text
        apply_btn = response.css('div.cs-text button', adaptive=True)
        
        if already_applied or not apply_btn:
            reason = "already applied ('Beworben' text found)" if already_applied else "no apply button found (closed/ended)"
            logger.info(f"Skipping job: {job['title']} - {reason}. Marking as applied.")
            job["status"] = "applied"
            return state

        desc_el = response.css("div.job-description", adaptive=True)
        job["description"] = desc_el[0].get_all_text().strip() if desc_el else "No description available"
        job["salary_range"] = _extract_salary_range(response)
        job["company_name"] = _extract_company_name(response)

        logger.info(
            f"Extracted: Salary: {job['salary_range']}, "
            f"Company: {job['company_name']}, Desc length: {len(job['description'])}"
        )

    except Exception as e:
        logger.error(f"Error extracting details for {job['link']}: {e}")
        job["status"] = "error"
        job["error_message"] = str(e)

    return state
