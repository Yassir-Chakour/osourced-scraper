import os
import logging
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright
from config import Config
from graph.state import GraphState, Job
from telegram_bot.bot import send_message_sync

logger = logging.getLogger(__name__)

def scraper_node(state: GraphState) -> GraphState:
    if state.get("errors"):
        logger.warning("Skipping scraper node due to existing errors.")
        return state
        
    logger.info("Starting scraper node...")
    auth_state_path = "data/auth.json"
    
    if not os.path.exists(auth_state_path):
        err = "Auth state file data/auth.json not found. Run login node first."
        logger.error(err)
        state["errors"].append(err)
        return state
        
    jobs_found = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Load the saved session context
        context = browser.new_context(storage_state=auth_state_path)
        page = context.new_page()
        
        try:
            logger.info(f"Navigating to jobs page: {Config.URL_LOGIN}")
            page.goto(Config.URL_LOGIN)
            
            logger.info("Extracting job elements...")
            elements = page.query_selector_all('h3 a')
            
            for job_element in elements:
                title = job_element.inner_text().strip()
                link = job_element.get_attribute('href')
                if link and title:
                    if not link.startswith("http"):
                        link = urljoin(Config.URL_LOGIN, link)
                    
                    job: Job = {
                        "title": title,
                        "link": link,
                        "salary_range": "null",
                        "description": "",
                        "company_name": "",
                        "pain_points": [],
                        "pitch": "",
                        "user_feedback": "",
                        "modification_rounds": 0,
                        "status": "pending",
                        "error_message": None
                    }
                    jobs_found.append(job)
            
            logger.info(f"Found {len(jobs_found)} job listings.")
            
        except Exception as e:
            err = f"Exception during job scraping: {str(e)}"
            logger.error(err)
            state["errors"].append(err)
            
        browser.close()
        
    if not state.get("errors"):
        if not jobs_found:
            msg = "No jobs found on osourced.is."
            logger.warning(msg)
            send_message_sync(msg)
            # Add a specific error so we terminate gracefully
            state["errors"].append("no_jobs_found")
        else:
            state["jobs"] = jobs_found
            state["current_job_index"] = 0
            
    return state
