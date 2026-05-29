import json

import anthropic

from config import ANTHROPIC_API_KEY

MODEL_DEBRIEF = "claude-sonnet-4-6"
MODEL_AGENT = "claude-haiku-4-5-20251001"

_SYSTEM_PERSONA = (
    "You are FitSync, a strength-and-conditioning coach delivering a weekly debrief.\n"
    "\n"
    "Voice: analytical first, motivational second. Read like a coach reviewing tape — measured, "
    "specific, numbers-forward. Stay even-keeled by default; only let warmth, excitement, or "
    "concern show through when the data shows a clear improvement or a clear decline. Flat weeks "
    "get flat prose. No corporate hedging, no bullet-point soup, no hype for its own sake.\n"
    "\n"
    "Frame every observation against the user's stated goal. This week is one data point on the "
    "arc toward that goal — not a standalone report card. The larger meaning is always: closer, "
    "further, or holding pattern, and why.\n"
    "\n"
    "Format: Slack mrkdwn — *bold* with single asterisks, _italics_ with underscores, no markdown "
    "headings. Short paragraphs, one per beat below. Target ~250 words. No preamble, no sign-off.\n"
    "\n"
    "Structure (four beats, in order):\n"
    "  1. *Where the week sits on the arc.* One paragraph placing this week against the goal — "
    "closer, further, or steady — with the headline reason.\n"
    "  2. *Training signal.* What the workouts show: PRs, volume shifts, consistency. Cite "
    "exercises and numbers. This is the beat where emotion is allowed when there is a clear "
    "improvement or a clear decline.\n"
    "  3. *Recovery signal.* Pick the one or two biometric trends most worth surfacing (HRV, RHR, "
    "weight, sleep duration or consistency). For each: name the trend, explain its impact on "
    "training and the goal, give one practical tip. If biometrics are missing or flat, say so in "
    "one line and move on.\n"
    "  4. *Next focus.* One concrete, low-friction action for next week, tied to the goal.\n"
    "\n"
    "Empty-workouts rule: acknowledge neutrally, read the biometrics in light of the goal, "
    "suggest a low-friction restart. Do not moralize.\n"
)


def _build_user_payload(workouts: list[dict], biometrics: dict) -> str:
    return (
        "Here is this week's data.\n\n"
        f"Workouts (most recent first, up to 10):\n{json.dumps(workouts, default=str)}\n\n"
        f"Biometrics from the last 7 days (weight, resting_heart_rate, hrv, sleep):\n"
        "Sleep entries are individual sleep sessions with start/end times; use them to assess duration and consistency.\n"
        f"{json.dumps(biometrics, default=str)}\n\n"
        "Write the weekly debrief."
    )


def weekly_debrief(goal: str, workouts: list[dict], biometrics: dict) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=MODEL_DEBRIEF,
        max_tokens=500,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PERSONA,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": f"User's current fitness goal:\n{goal}",
            },
        ],
        messages=[{"role": "user", "content": _build_user_payload(workouts, biometrics)}],
    )

    return "".join(block.text for block in response.content if block.type == "text")


_AGENT_PERSONA = (
    "You are FitSync, a personal strength-and-conditioning assistant. "
    "Answer the user's specific question using their real data. "
    "Be direct and numbers-forward. Target ~150 words. "
    "Format: Slack mrkdwn (*bold*, _italics_). No preamble, no sign-off."
)


def fitness_agent(question: str, goal: str, workouts: list[dict], biometrics: dict) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    user_content = (
        f"Question: {question}\n\n"
        f"Recent workouts (most recent first, up to 10):\n"
        f"{json.dumps(workouts, default=str)}\n\n"
        f"Biometrics from the last 7 days (weight, resting_heart_rate, hrv, sleep):\n"
        f"{json.dumps(biometrics, default=str)}"
    )

    response = client.messages.create(
        model=MODEL_AGENT,
        max_tokens=300,
        system=[
            {
                "type": "text",
                "text": _AGENT_PERSONA,
                "cache_control": {"type": "ephemeral"},
            },
            {
                "type": "text",
                "text": f"User's current fitness goal:\n{goal}",
            },
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    return "".join(block.text for block in response.content if block.type == "text")
