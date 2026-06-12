import json
from typing import Any

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
    "\n"
    "Active memories rule: If there are active memories (e.g. sickness, injury), weave them into "
    "the relevant beat where appropriate, and at the end of the debrief explicitly ask the user "
    "for an update on their condition — one concise sentence, naturally appended after the four "
    "beats.\n"
)

_AGENT_PERSONA = (
    "You are FitSync, a personal strength-and-conditioning assistant. "
    "Answer the user's specific question using their real data. "
    "Be direct and numbers-forward. Target ~150 words. "
    "Format: Slack mrkdwn (*bold*, _italics_). No preamble, no sign-off.\n"
    "\n"
    "You have access to two tools: save_memory and delete_memory.\n"
    "- Call save_memory when the user mentions something worth remembering across sessions "
    "(sickness, injury, travel, life events affecting training).\n"
    "- Call delete_memory when the user confirms a previously remembered condition is resolved "
    "(e.g. 'I'm better now', 'injury cleared up'). Match against the active memories provided "
    "in the system context and delete the most relevant one.\n"
    "Always answer the user's question in your final response, even if you called a tool."
)

_MEMORY_TOOLS = [
    {
        "name": "save_memory",
        "description": (
            "Persist a fact about the user's current condition (e.g. illness, injury, life event) "
            "so it can be recalled in future sessions and weekly debriefs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": (
                        "A concise, self-contained statement of the fact to remember. "
                        "Include the date if relevant, e.g. 'User reported a sore throat on 2026-06-12.'"
                    ),
                }
            },
            "required": ["fact"],
        },
    },
    {
        "name": "delete_memory",
        "description": (
            "Mark an existing memory as inactive when the user confirms the condition has resolved."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "The 'id' field of the memory to delete, as provided in the active memories context.",
                }
            },
            "required": ["memory_id"],
        },
    },
]


def _format_memories_block(memories: list[dict]) -> str:
    if not memories:
        return "Active memories: none."
    lines = ["Active memories (use these to personalise your response):"]
    for m in memories:
        lines.append(f"  - id={m['id']} | {m['fact']} (since {m.get('created_at', 'unknown')})")
    return "\n".join(lines)


def _build_user_payload(workouts: list[dict], biometrics: dict) -> str:
    return (
        "Here is this week's data.\n\n"
        f"Workouts (most recent first, up to 10):\n{json.dumps(workouts, default=str)}\n\n"
        f"Biometrics from the last 7 days (weight, resting_heart_rate, hrv, sleep):\n"
        "Sleep entries are individual sleep sessions with start/end times; use them to assess duration and consistency.\n"
        f"{json.dumps(biometrics, default=str)}\n\n"
        "Write the weekly debrief."
    )


def weekly_debrief(
    goal: str,
    workouts: list[dict],
    biometrics: dict,
    memories: list[dict] | None = None,
) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_blocks = [
        {
            "type": "text",
            "text": _SYSTEM_PERSONA,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"User's current fitness goal:\n{goal}",
        },
    ]
    if memories:
        system_blocks.append(
            {"type": "text", "text": _format_memories_block(memories)}
        )

    response = client.messages.create(
        model=MODEL_DEBRIEF,
        max_tokens=600,
        system=system_blocks,
        messages=[{"role": "user", "content": _build_user_payload(workouts, biometrics)}],
    )

    return "".join(block.text for block in response.content if block.type == "text")


def fitness_agent(
    question: str,
    goal: str,
    workouts: list[dict],
    biometrics: dict,
    memories: list[dict] | None = None,
) -> str:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

    # Import here to avoid circular imports at module load time
    import memory as mem_store

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system_blocks = [
        {
            "type": "text",
            "text": _AGENT_PERSONA,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": f"User's current fitness goal:\n{goal}",
        },
        {
            "type": "text",
            "text": _format_memories_block(memories or []),
        },
    ]

    user_content = (
        f"Question: {question}\n\n"
        f"Recent workouts (most recent first, up to 10):\n"
        f"{json.dumps(workouts, default=str)}\n\n"
        f"Biometrics from the last 7 days (weight, resting_heart_rate, hrv, sleep):\n"
        f"{json.dumps(biometrics, default=str)}"
    )

    messages: list[Any] = [{"role": "user", "content": user_content}]

    # Tool-calling loop: keep going until Claude stops requesting tools
    while True:
        response = client.messages.create(
            model=MODEL_AGENT,
            max_tokens=1024,
            system=system_blocks,
            tools=_MEMORY_TOOLS,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )

        # Collect any text blocks from this turn
        text_blocks = [block.text for block in response.content if block.type == "text"]
        tool_use_blocks = [block for block in response.content if block.type == "tool_use"]

        if not tool_use_blocks or response.stop_reason == "end_turn":
            # No more tool calls — return the final text response
            text = "".join(text_blocks)
            if response.stop_reason == "max_tokens":
                text += "…"
            return text

        # Append Claude's response (including tool_use blocks) to the conversation
        messages.append({"role": "assistant", "content": response.content})

        # Execute each tool and collect results
        tool_results: list[dict[str, Any]] = []
        for tool_block in tool_use_blocks:
            tool_name = tool_block.name
            tool_input = tool_block.input

            try:
                if tool_name == "save_memory":
                    saved = mem_store.save_memory(str(tool_input["fact"]))
                    result_content = json.dumps({"status": "saved", "id": saved["id"]})
                elif tool_name == "delete_memory":
                    mem_store.delete_memory(str(tool_input["memory_id"]))
                    result_content = json.dumps({"status": "deleted"})
                else:
                    result_content = json.dumps({"error": f"Unknown tool: {tool_name}"})
            except Exception as exc:  # noqa: BLE001
                result_content = json.dumps({"error": str(exc)})

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_block.id,
                    "content": result_content,
                }
            )

        messages.append({"role": "user", "content": tool_results})
