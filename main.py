import json
import re
import time

import boto3
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from mangum import Mangum

from clients.claude import fitness_agent
from clients.google_health import fetch_biometrics, log_workout_to_google_health
from clients.hevy import fetch_workout, list_recent_workouts
from clients.slack import post_agent_reply, post_workout_to_slack
from config import DEDUP_TABLE_NAME, GOAL_SSM_PARAMETER_NAME
from models import SlackEvent

app = FastAPI(title="Hevy to Google Health Sync Webhook")


@app.post("/messages")
async def receive_message(request: Request, payload: SlackEvent):
    """
    Slack Events API endpoint.
    Handles url_verification handshake and app_mention events.
    """
    print(json.dumps({
        "event": "slack.event_received",
        "type": payload.type,
        "payload": payload.model_dump(exclude_none=True),
    }))

    if payload.type == "url_verification":
        return PlainTextResponse(content=payload.challenge or "")

    # Slack retries if no 200 within 3 seconds — ignore retries to avoid double replies.
    if request.headers.get("X-Slack-Retry-Num"):
        return {"ok": True}

    inner = payload.event or {}
    if inner.get("type") == "app_mention":
        raw_text = inner.get("text", "")
        question = re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()
        channel = inner.get("channel", "")
        thread_ts = inner.get("ts", "")

        print(json.dumps({
            "event": "agent.mention_received",
            "channel": channel,
            "question": question,
        }))

        try:
            ssm = boto3.client("ssm")
            goal = ssm.get_parameter(
                Name=GOAL_SSM_PARAMETER_NAME, WithDecryption=True
            )["Parameter"]["Value"]
        except Exception as e:
            print(json.dumps({"event": "agent.ssm_error", "error": str(e)}))
            goal = ""

        try:
            workouts = list_recent_workouts(limit=5)
        except Exception as e:
            print(json.dumps({"event": "agent.hevy_error", "error": str(e)}))
            workouts = []

        try:
            biometrics = fetch_biometrics(days=7)
        except Exception as e:
            print(json.dumps({"event": "agent.biometrics_error", "error": str(e)}))
            biometrics = {"weight": [], "resting_heart_rate": [], "hrv": [], "sleep": []}

        try:
            reply = fitness_agent(question, goal, workouts, biometrics)
            print(json.dumps({"event": "agent.claude_success", "chars": len(reply)}))
        except Exception as e:
            print(json.dumps({"event": "agent.claude_error", "error": str(e)}))
            reply = "Sorry, I ran into an error fetching your data. Try again in a moment."

        try:
            post_agent_reply(reply, channel, thread_ts)
            print(json.dumps({"event": "agent.reply_posted", "channel": channel}))
        except Exception as e:
            print(json.dumps({"event": "agent.reply_error", "error": str(e)}))

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

    if DEDUP_TABLE_NAME:
        dynamodb = boto3.resource("dynamodb")
        table = dynamodb.Table(DEDUP_TABLE_NAME)
        try:
            table.put_item(
                Item={"workoutId": workout_id, "ttl": int(time.time()) + 86400},
                ConditionExpression="attribute_not_exists(workoutId)",
            )
        except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
            print(json.dumps({"event": "webhook.duplicate", "workout_id": workout_id}))
            return {"status": "duplicate", "workout_id": workout_id}

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
