import json
import os
import time
import boto3

from hevy_client import list_recent_workouts
from google_health_client import fetch_biometrics
from claude_client import weekly_debrief
from slack_client import post_debrief_to_slack

GOAL_SSM_PARAMETER_NAME = os.environ.get("GOAL_SSM_PARAMETER_NAME", "/fitsync/goal")


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
        biometrics = {"weight": [], "resting_heart_rate": [], "hrv": []}

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
