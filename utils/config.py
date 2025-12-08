import os
from dotenv import load_dotenv
from typing import Optional

# Load environment variables from .env directory
# Try multiple locations for flexibility
env_paths = [
    'config.env',
    '.env.local',
    '.env',
]

for env_path in env_paths:
    if os.path.exists(env_path) and os.path.isfile(env_path):
        load_dotenv(dotenv_path=env_path)
        break
else:
    # Fallback to .env.example or load from environment variables
    if os.path.exists('.env.example') and os.path.isfile('.env.example'):
        load_dotenv(dotenv_path='.env.example')


class Config:
    """Application configuration"""

    # Google Sheets
    GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
    GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "credentials.json")

    # Trello
    TRELLO_API_KEY = os.getenv("TRELLO_API_KEY", "")
    TRELLO_API_TOKEN = os.getenv("TRELLO_API_TOKEN", "")
    TRELLO_BOARD_ID = os.getenv("TRELLO_BOARD_ID", "")
    TRELLO_NEW_LIST_ID = os.getenv("TRELLO_NEW_LIST_ID", "")
    TRELLO_CONTACTED_LIST_ID = os.getenv("TRELLO_CONTACTED_LIST_ID", "")
    TRELLO_QUALIFIED_LIST_ID = os.getenv("TRELLO_QUALIFIED_LIST_ID", "")
    TRELLO_CLOSED_LIST_ID = os.getenv("TRELLO_CLOSED_LIST_ID", "")
    TRELLO_WEBHOOK_URL = os.getenv("TRELLO_WEBHOOK_URL", "")

    # Application
    APP_ENV = os.getenv("APP_ENV", "development")
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "30"))

    # FastAPI
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))

    # Trello List mapping (actual status names from your system)
    # Dynamically build mapping, skip empty IDs
    _raw_mapping = {
        "New": TRELLO_NEW_LIST_ID,
        "Contacted": TRELLO_CONTACTED_LIST_ID,
        "Qualified": TRELLO_QUALIFIED_LIST_ID,
        "Closed": TRELLO_CLOSED_LIST_ID,
    }
    # Filter out empty values to handle missing list IDs gracefully
    TRELLO_LIST_MAPPING = {k: v for k, v in _raw_mapping.items() if v}


def validate_config() -> bool:
    """Validate critical configuration is set"""
    required = [
        "GOOGLE_SHEETS_ID",
        "TRELLO_API_KEY",
        "TRELLO_API_TOKEN",
        "TRELLO_BOARD_ID",
    ]
    for key in required:
        if not getattr(Config, key, None):
            print(f"ERROR: Missing configuration {key}")
            return False
    return True
