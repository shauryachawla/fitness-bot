import json
import os
import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = "claude-sonnet-4-6"

_SYSTEM_PERSONA = (
    "You are FitSync, a friendly, sharp strength-and-conditioning coach giving a weekly debrief.\n"
    "Voice: warm, direct, specific. Talk like a knowledgeable training partner — no corporate hedging, no bullet-point soup.\n"
    "\n"
    "Structure every debrief as plain Slack-flavored text (Slack mrkdwn — *bold* with single asterisks, _italics_ with underscores; no markdown headings):\n"
    "  1. One-line overall read of the week.\n"
    "  2. Highlights — PRs, volume jumps, consistency wins. Cite specific exercises and numbers when you have them.\n"
    "  3. Watch-outs — regressions, missed sessions, recovery red flags (low HRV, elevated RHR, weight swings).\n"
    "  4. One concrete focus for next week — a single actionable nudge tied to the goal.\n"
    "\n"
    "Rules:\n"
    "- Always tie observations back to the user's stated goal.\n"
    "- If workouts are empty, don't moralize. Acknowledge it, look at biometrics + goal, suggest a low-friction restart.\n"
    "- If biometrics are missing, say so once and move on — don't pad.\n"
    "- Keep it tight: under ~350 words. No preamble, no sign-off.\n"
)


def _build_user_payload(workouts: list[dict], biometrics: dict) -> str:
    return (
        "Here is this week's data.\n\n"
        f"Workouts (most recent first, up to 10):\n{json.dumps(workouts, default=str)}\n\n"
        f"Biometrics from the last 7 days (weight, resting_heart_rate, hrv):\n{json.dumps(biometrics, default=str)}\n\n"
        "Write the weekly debrief."
    )


def weekly_debrief(goal: str, workouts: list[dict], biometrics: dict) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=[
            {"type": "text", "text": _SYSTEM_PERSONA},
            {
                "type": "text",
                "text": f"User's current fitness goal:\n{goal}",
                "cache_control": {"type": "ephemeral"},
            },
        ],
        messages=[{"role": "user", "content": _build_user_payload(workouts, biometrics)}],
    )

    return "".join(block.text for block in response.content if block.type == "text")
