import json
import time
import boto3

from clients.hevy import list_recent_workouts
from clients.google_health import fetch_biometrics
from clients.claude import weekly_debrief
from clients.slack import post_debrief_to_slack
from config import GOAL_SSM_PARAMETER_NAME


def _get_goal_from_ssm() -> str:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=GOAL_SSM_PARAMETER_NAME, WithDecryption=True)
    return response["Parameter"]["Value"]


def handler(event, context):
    start = time.monotonic()
    print(json.dumps({"event": "debrief.started"}))

    goal = _get_goal_from_ssm()

    try:
        workouts = list_recent_workouts(limit=10)
        print(json.dumps({"event": "debrief.hevy_fetched", "count": len(workouts)}))
    except Exception as e:
        print(json.dumps({"event": "debrief.hevy_error", "error": str(e)}))
        workouts = []

    try:
        biometrics = fetch_biometrics(days=7)
        print(json.dumps({
            "event": "debrief.biometrics_fetched",
            "counts": {k: len(v) for k, v in biometrics.items()},
        }))
    except Exception as e:
        print(json.dumps({"event": "debrief.biometrics_error", "error": str(e)}))
        biometrics = {"weight": [], "resting_heart_rate": [], "hrv": [], "sleep": []}

    try:
        text = weekly_debrief(goal, workouts, biometrics)
        print(json.dumps({"event": "debrief.claude_success", "chars": len(text)}))
    except Exception as e:
        print(json.dumps({"event": "debrief.claude_error", "error": str(e)}))
        raise

    slack_response = post_debrief_to_slack(text, goal)
    duration_ms = round((time.monotonic() - start) * 1000)
    print(json.dumps({
        "event": "debrief.slack_posted",
        "slack_ts": slack_response.get("ts"),
        "duration_ms": duration_ms,
    }))

    return {"status": "success", "slack_ts": slack_response.get("ts")}
