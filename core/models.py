from typing import Any, Optional

from pydantic import BaseModel, Field


class SlackEvent(BaseModel):
    """Slack Events API payload. Fields are optional because the shape varies by event type."""
    type: str = Field(..., description="Event type, e.g. 'url_verification' or 'event_callback'")
    token: Optional[str] = Field(None, description="(deprecated) verification token")
    challenge: Optional[str] = Field(None, description="Challenge string sent during url_verification")
    team_id: Optional[str] = None
    api_app_id: Optional[str] = None
    event: Optional[dict[str, Any]] = Field(None, description="Inner event object for event_callback")
    event_id: Optional[str] = None
    event_time: Optional[int] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "type": "url_verification",
                    "token": "Jhj5dZrVaK7ZwHHjRyZWjbDl",
                    "challenge": "3eZbrw1aBm2rZgRNFdxV2595E9CY3gmdALWMmHkvFXO7tYXAYM8P",
                },
                {
                    "type": "event_callback",
                    "team_id": "T0123456789",
                    "api_app_id": "A0123456789",
                    "event": {"type": "message", "text": "hello", "user": "U123", "channel": "C123"},
                    "event_id": "Ev0123456789",
                    "event_time": 1700000000,
                },
            ]
        }
    }
