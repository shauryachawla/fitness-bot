import json
import time
from typing import Any, Optional
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from mangum import Mangum
from google_health_client import log_workout_to_google_health
from hevy_client import fetch_workout
from slack_client import post_workout_to_slack, post_message_to_slack

app = FastAPI(title="Hevy to Google Health Sync Webhook")

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


@app.post("/messages")
async def receive_message(payload: SlackEvent):
    """
    Slack Events API endpoint.
    Handles the one-time url_verification handshake and any future event callbacks.
    """
    print(json.dumps({
        "event": "slack.event_received",
        "type": payload.type,
        "payload": payload.model_dump(exclude_none=True),
    }))

    # Slack url_verification handshake — echo the challenge back as plain text.
    if payload.type == "url_verification":
        return PlainTextResponse(content=payload.challenge or "")

    # event_callback or anything else — acknowledge with 200 so Slack doesn't retry.
    post_message_to_slack("message aya hai")
    return {"ok": True}

@app.post("/webhook")
async def hevy_webhook(request: Request):
    """
    Receives webhook events from Hevy and triggers Google Health sync.
    """
    start = time.monotonic()

    try:
        payload = await request.json()
    except Exception:
        print(f"[WARNING] webhook.invalid_json path={request.url}")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    print(json.dumps({
        "event": "webhook.received",
        "payload": payload,
    }))

    workout_id = payload.get("workoutId")
    if not workout_id:
        print(json.dumps({"event": "webhook.missing_workout_id"}))
        raise HTTPException(status_code=400, detail="Missing workoutId in payload")

    print(json.dumps({"event": "hevy.fetch_started", "workout_id": workout_id}))
    try:
        workout = fetch_workout(workout_id)
    except ValueError as e:
        print(json.dumps({"event": "hevy.fetch_error", "workout_id": workout_id, "error": str(e)}))
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(json.dumps({"event": "hevy.fetch_error", "workout_id": workout_id, "error": str(e)}))
        raise HTTPException(status_code=502, detail=f"Failed to fetch workout from Hevy: {e}")

    workout_title = workout.get("title", "<untitled>")
    workout_start = workout.get("start_time")
    print(json.dumps({
        "event": "sync.started",
        "workout_id": workout_id,
        "workout_title": workout_title,
        "workout_start": workout_start,
    }))

    try:
        result = log_workout_to_google_health(workout)
        duration_ms = round((time.monotonic() - start) * 1000)
        print(json.dumps({
            "event": "sync.success",
            "workout_id": workout_id,
            "workout_title": workout_title,
            "duration_ms": duration_ms,
        }))

        slack_response = None
        try:
            slack_response = post_workout_to_slack(workout)
            print(json.dumps({
                "event": "slack.post_success",
                "workout_id": workout_id,
                "slack_ts": slack_response.get("ts"),
                "slack_channel": slack_response.get("channel"),
            }))
        except Exception as slack_err:
            print(json.dumps({
                "event": "slack.post_error",
                "workout_id": workout_id,
                "error": str(slack_err),
            }))

        return {
            "status": "success",
            "google_health_response": result,
            "slack_posted": bool(slack_response and slack_response.get("ok")),
        }
    except Exception as e:
        duration_ms = round((time.monotonic() - start) * 1000)
        print(json.dumps({
            "event": "sync.error",
            "workout_id": workout_id,
            "workout_title": workout_title,
            "error": str(e),
            "duration_ms": duration_ms,
        }))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def health_check():
    return {"status": "ok", "message": "fitsync is running"}

# Wrap the FastAPI app with Mangum to create the Lambda handler
handler = Mangum(app)
