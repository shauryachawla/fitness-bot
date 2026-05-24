import json
import time
from fastapi import FastAPI, Request, HTTPException
from mangum import Mangum
from google_health_client import log_workout_to_google_health
from hevy_client import fetch_workout

app = FastAPI(title="Hevy to Google Health Sync Webhook")

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
        return {"status": "success", "google_health_response": result}
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
