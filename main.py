import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
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

logger = logging.getLogger("main")

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
    logger.info(f"Daemon mode started. Check interval: {Config.CHECK_INTERVAL} seconds.")
    
    try:
        while True:
            # Wipe old run_state.json for a clean new scrape run
            run_state_path = "data/run_state.json"
            if os.path.exists(run_state_path):
                try:
                    os.remove(run_state_path)
                    logger.info("Wiped old run_state.json.")
                except Exception as e:
                    logger.warning(f"Could not remove old run_state.json: {e}")
            
            initial_state: GraphState = {
                "jobs": [],
                "current_job_index": 0,
                "run_id": datetime.now().isoformat(),
                "errors": [],
                "telegram_chat_id": Config.TELEGRAM_CHAT_ID
            }
            
            logger.info(f"Invoking StateGraph with run_id: {initial_state['run_id']}")
            try:
                app.invoke(initial_state)
                logger.info("StateGraph execution completed.")
            except Exception as e:
                logger.exception(f"Unhandled error during LangGraph execution: {e}")
                
            logger.info(f"Sleeping for {Config.CHECK_INTERVAL} seconds before next run...")
            time.sleep(Config.CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        logger.info("Daemon interrupted by user. Shutting down...")
    finally:
        logger.info("Shutting down Telegram Bot...")
        try:
            stop_bot()
        except Exception as e:
            logger.error(f"Error during Telegram Bot shutdown: {e}")
            
    logger.info("Osourced Scraper finished.")