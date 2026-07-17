import os
import sys
import logging
import zoneinfo
from logging.handlers import RotatingFileHandler
from datetime import datetime, time as dt_time, timedelta
from config import Config
from telegram_bot.bot import start_bot, stop_bot
from graph.graph import app
from graph.state import GraphState

# Configure logging
os.makedirs("logs", exist_ok=True)
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Rotating File Handler
file_handler = RotatingFileHandler(
    "logs/bot.log",
    maxBytes=1_000_000,  # 1 MB
    backupCount=3
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.INFO)

# Console Handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# Setup root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# Suppress noisy library logs (e.g., Telegram API HTTP request logs)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("main")

def get_seconds_until_next_run(run_time_str: str, timezone_str: str) -> float:
    try:
        hour, minute = map(int, run_time_str.split(":"))
    except Exception:
        hour, minute = 9, 0
        logger.warning(f"Invalid DAILY_RUN_TIME format '{run_time_str}'. Defaulting to 09:00.")

    tz = None
    if timezone_str:
        try:
            tz = zoneinfo.ZoneInfo(timezone_str)
        except Exception as e:
            logger.warning(f"Could not load timezone '{timezone_str}', falling back to local time. Error: {e}")
            
    now = datetime.now(tz)
    
    # Target time on the same date as now
    target_time = datetime.combine(
        now.date(),
        dt_time(hour=hour, minute=minute),
        tzinfo=now.tzinfo
    )
    
    if now >= target_time:
        target_time += timedelta(days=1)
        
    delta = target_time - now
    return delta.total_seconds()

if __name__ == "__main__":
    logger.info("Starting Osourced Scraper application...")
    
    try:
        Config.validate()
        logger.info("Configuration validated successfully.")
    except Exception as e:
        logger.critical(f"Configuration validation failed: {e}")
        sys.exit(1)
        
    logger.info("Starting Telegram Bot...")
    try:
        start_bot()
    except Exception as e:
        logger.exception(f"Failed to start Telegram Bot: {e}")
        sys.exit(1)
        
    import time
    if Config.RUN_MODE == "daily":
        logger.info(f"Daemon mode started in DAILY mode. Target run time: {Config.DAILY_RUN_TIME} (Timezone: {Config.TIMEZONE or 'Local'}).")
    else:
        logger.info(f"Daemon mode started in INTERVAL mode. Check interval: {Config.CHECK_INTERVAL} seconds.")
    
    first_run = True
    try:
        while True:
            # If we don't run on startup, sleep first on the very first iteration
            if first_run and not Config.RUN_ON_STARTUP and Config.RUN_MODE == "daily":
                sleep_seconds = get_seconds_until_next_run(Config.DAILY_RUN_TIME, Config.TIMEZONE)
                logger.info(f"Startup run bypassed. Sleeping for {sleep_seconds:.1f} seconds until next scheduled run at {Config.DAILY_RUN_TIME}...")
                time.sleep(sleep_seconds)
                first_run = False
                
            # Wipe old run_state.json for a clean new scrape run
            run_state_path = "data/run_state.json"
            if os.path.exists(run_state_path):
                try:
                    os.remove(run_state_path)
                    logger.info("Wiped old run_state.json.")
                except Exception as e:
                    logger.warning(f"Could not remove old run_state.json: {e}")
            
            from db.jobs_db import load_jobs
            pending_jobs = [j for j in load_jobs() if j.get("status") == "pending"]
            logger.info(f"Loaded {len(pending_jobs)} pending jobs from database on startup.")

            initial_state: GraphState = {
                "jobs": pending_jobs,
                "current_job_index": 0,
                "run_id": datetime.now().isoformat(),
                "errors": [],
                "telegram_chat_id": Config.TELEGRAM_CHAT_ID
            }
            
            logger.info(f"Invoking StateGraph with run_id: {initial_state['run_id']}")
            try:
                app.invoke(initial_state)
                logger.info("StateGraph execution completed.")
                
                # If there is no active job card, send the next one in the queue
                from telegram_bot.bot import check_and_send_next_card
                check_and_send_next_card()
            except Exception as e:
                logger.exception(f"Unhandled error during LangGraph execution: {e}")

            # Calculate next sleep duration
            if Config.RUN_MODE == "daily":
                sleep_seconds = get_seconds_until_next_run(Config.DAILY_RUN_TIME, Config.TIMEZONE)
                logger.info(f"Run completed. Sleeping for {sleep_seconds:.1f} seconds until next scheduled run at {Config.DAILY_RUN_TIME}...")
            else:
                sleep_seconds = float(Config.CHECK_INTERVAL)
                logger.info(f"Run completed. Sleeping for {sleep_seconds:.1f} seconds before next check...")
                
            first_run = False
            time.sleep(sleep_seconds)
            
    except KeyboardInterrupt:
        logger.info("Daemon interrupted by user. Shutting down...")
    finally:
        logger.info("Shutting down Telegram Bot...")
        try:
            stop_bot()
        except Exception as e:
            logger.error(f"Error during Telegram Bot shutdown: {e}")
            
    logger.info("Osourced Scraper finished.")