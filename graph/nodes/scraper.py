import os
import json
import logging
from urllib.parse import urljoin
from scrapling.fetchers import StealthyFetcher
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
    
    try:
        with open(auth_state_path, "r", encoding="utf-8") as f:
            auth_data = json.load(f)
        cookies = auth_data.get("cookies", [])
        
        logger.info(f"Navigating to jobs page: {Config.URL_LOGIN}")
        StealthyFetcher.adaptive = True
        response = StealthyFetcher.fetch(Config.URL_LOGIN, cookies=cookies, headless=True)
        
        logger.info("Extracting job elements...")
        elements = response.css('h3 a', adaptive=True)
        
        for job_element in elements:
            title_text = job_element.css('::text').get()
            title = title_text.strip() if title_text else ""
            link = job_element.attrib.get('href')
            if link and title:
                if not link.startswith("http"):
                    link = urljoin(Config.URL_LOGIN, link)
                
                from data.jobs_db import get_job_by_link
                existing_job = get_job_by_link(link)
                if existing_job:
                    logger.info(f"Skipping already scraped job: {title} ({link})")
                    continue
                
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
