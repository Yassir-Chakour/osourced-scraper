import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    USER_LOGIN = 'yassir@shinobiautomation.com'
    USER_PASS = os.getenv('OSOURCED_PASSWORD')
    OPENROUTER_KEY = os.getenv('OPENROUTER_API_KEY')

    URL_LOGIN = "https://osourced.is/jobs/"

    API_URL = "https://openrouter.ai/api/v1/chat/completions"
    MODEL = "openai/gpt-4o-mini"

    @staticmethod
    def validate():
        if not Config.USER_PASS or not Config.OPENROUTER_KEY:
            raise ValueError("Missing environment variables. Please check your .env file.")