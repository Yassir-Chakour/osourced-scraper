import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    USER_LOGIN = os.getenv('OSOURCED_EMAIL', 'yassir@shinobiautomation.com')
    USER_PASS = os.getenv('OSOURCED_PASSWORD')
    OPENROUTER_KEY = os.getenv('OPENROUTER_API_KEY')

    URL_LOGIN = "https://osourced.is/jobs/"

    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    MODEL = "openai/gpt-4o-mini"

    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
    MAX_MODIFICATION_ROUNDS = int(os.getenv('MAX_MODIFICATION_ROUNDS', '3'))
    DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'
    RATE_LIMIT_DELAY = int(os.getenv('RATE_LIMIT_DELAY', '30'))
    CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '900'))

    @staticmethod
    def validate():
        if not Config.USER_LOGIN or not Config.USER_PASS or not Config.OPENROUTER_KEY:
            raise ValueError("Missing OSOURCED_EMAIL, OSOURCED_PASSWORD or OPENROUTER_API_KEY environment variables.")
        if not Config.TELEGRAM_BOT_TOKEN or not Config.TELEGRAM_CHAT_ID:
            raise ValueError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variables.")