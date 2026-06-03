import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
SSM_PARAMETER_NAME = os.environ.get("SSM_PARAMETER_NAME", "/fitsync/google_health_refresh_token")
HEVY_API_KEY = os.environ.get("HEVY_API_KEY")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
GOAL_SSM_PARAMETER_NAME = os.environ.get("GOAL_SSM_PARAMETER_NAME", "/fitsync/goal")
DEDUP_TABLE_NAME = os.environ.get("DEDUP_TABLE_NAME")
