from datetime import datetime, timezone

import requests

from config import SLACK_BOT_TOKEN, SLACK_CHANNEL

SLACK_API_URL = "https://slack.com/api/chat.postMessage"


def _format_duration(seconds: int) -> str:
    if not seconds:
        return "n/a"
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _compute_duration_seconds(workout: dict) -> int:
    if workout.get("duration_seconds"):
        return int(workout["duration_seconds"])
    start = workout.get("start_time")
    end = workout.get("end_time")
    if start and end:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        return int((e - s).total_seconds())
    return 0


def _format_set(s: dict) -> str:
    parts = []
    weight = s.get("weight_kg")
    reps = s.get("reps")
    distance = s.get("distance_meters")
    duration = s.get("duration_seconds")

    if weight is not None and reps is not None:
        parts.append(f"{weight}kg × {reps}")
    elif reps is not None:
        parts.append(f"{reps} reps")
    if distance is not None:
        parts.append(f"{distance}m")
    if duration is not None:
        parts.append(_format_duration(duration))
    if s.get("rpe") is not None:
        parts.append(f"RPE {s['rpe']}")
    return ", ".join(parts) if parts else "—"


def build_workout_summary(workout: dict) -> dict:
    """Build a Slack Block Kit message summarising a Hevy workout."""
    title = workout.get("title") or "Hevy Workout"
    description = workout.get("description") or ""
    exercises = workout.get("exercises") or []

    duration_seconds = _compute_duration_seconds(workout)
    total_sets = sum(len(ex.get("sets") or []) for ex in exercises)
    total_volume = 0.0
    for ex in exercises:
        for s in ex.get("sets") or []:
            w = s.get("weight_kg") or 0
            r = s.get("reps") or 0
            total_volume += float(w) * float(r)

    start_time_str = workout.get("start_time")
    when = ""
    if start_time_str:
        try:
            dt = datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
            when = dt.astimezone(timezone.utc).strftime("%a %b %d, %Y %H:%M UTC")
        except Exception:
            when = start_time_str

    header_text = f"💪 {title}"
    summary_lines = []
    if when:
        summary_lines.append(f"*When:* {when}")
    summary_lines.append(f"*Duration:* {_format_duration(duration_seconds)}")
    summary_lines.append(f"*Exercises:* {len(exercises)}  •  *Sets:* {total_sets}")
    if total_volume:
        summary_lines.append(f"*Total volume:* {total_volume:,.0f} kg")
    if description:
        summary_lines.append(f"\n_{description}_")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(summary_lines)}},
    ]

    if exercises:
        blocks.append({"type": "divider"})
        exercise_lines = []
        for ex in exercises:
            name = ex.get("title") or ex.get("exercise_template_id") or "Exercise"
            sets = ex.get("sets") or []
            set_strs = [f"  • {_format_set(s)}" for s in sets]
            exercise_lines.append(f"*{name}*\n" + ("\n".join(set_strs) if set_strs else "  • —"))
            if ex.get("notes"):
                exercise_lines.append(f"  _note: {ex['notes']}_")
        # Slack section text limit is 3000 chars — truncate defensively.
        body = "\n\n".join(exercise_lines)
        if len(body) > 2900:
            body = body[:2900] + "\n…(truncated)"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})

    fallback = f"{title} — {len(exercises)} exercises, {total_sets} sets, {_format_duration(duration_seconds)}"
    return {"text": fallback, "blocks": blocks}


def post_message_to_slack(text: str) -> dict:
    """Post a plain text message to the configured Slack channel."""
    if not SLACK_BOT_TOKEN:
        raise ValueError("SLACK_BOT_TOKEN environment variable is not set")
    if not SLACK_CHANNEL:
        raise ValueError("SLACK_CHANNEL environment variable is not set")

    payload = {"channel": SLACK_CHANNEL, "text": text}
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }

    response = requests.post(SLACK_API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise Exception(
            f"Slack API HTTP error: {response.status_code} - {response.text}"
        )
    data = response.json()
    if not data.get("ok"):
        raise Exception(f"Slack API error: {data.get('error')} - {data}")
    return data


def post_agent_reply(text: str, channel: str, thread_ts: str) -> dict:
    """Post an agent reply into a specific Slack thread."""
    if not SLACK_BOT_TOKEN:
        raise ValueError("SLACK_BOT_TOKEN environment variable is not set")

    payload = {"channel": channel, "text": text, "thread_ts": thread_ts}
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }

    response = requests.post(SLACK_API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise Exception(
            f"Slack API HTTP error: {response.status_code} - {response.text}"
        )
    data = response.json()
    if not data.get("ok"):
        raise Exception(f"Slack API error: {data.get('error')} - {data}")
    return data


def post_debrief_to_slack(debrief_text: str, goal: str) -> dict:
    """Post a weekly Claude-generated debrief to the configured Slack channel."""
    if not SLACK_BOT_TOKEN:
        raise ValueError("SLACK_BOT_TOKEN environment variable is not set")
    if not SLACK_CHANNEL:
        raise ValueError("SLACK_CHANNEL environment variable is not set")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "📊 Weekly debrief", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"*Goal:* {goal}"}]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": debrief_text[:2900]}},
    ]
    fallback = "Weekly debrief"

    payload = {"channel": SLACK_CHANNEL, "text": fallback, "blocks": blocks}
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }

    response = requests.post(SLACK_API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise Exception(
            f"Slack API HTTP error: {response.status_code} - {response.text}"
        )
    data = response.json()
    if not data.get("ok"):
        raise Exception(f"Slack API error: {data.get('error')} - {data}")
    return data


def post_workout_to_slack(workout: dict) -> dict:
    """Post a formatted workout summary to a Slack channel via chat.postMessage."""
    if not SLACK_BOT_TOKEN:
        raise ValueError("SLACK_BOT_TOKEN environment variable is not set")
    if not SLACK_CHANNEL:
        raise ValueError("SLACK_CHANNEL environment variable is not set")

    message = build_workout_summary(workout)
    payload = {"channel": SLACK_CHANNEL, **message}
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json; charset=utf-8",
    }

    response = requests.post(SLACK_API_URL, headers=headers, json=payload)
    if response.status_code != 200:
        raise Exception(
            f"Slack API HTTP error: {response.status_code} - {response.text}"
        )
    data = response.json()
    if not data.get("ok"):
        raise Exception(f"Slack API error: {data.get('error')} - {data}")
    return data
