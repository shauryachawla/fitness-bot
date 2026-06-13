# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Dependency management uses `uv` (see [uv.lock](uv.lock)); `requirements.txt` is generated from it for SAM packaging.

```bash
# Install deps locally
uv sync                              # preferred (uses uv.lock)
pip install -r requirements.txt      # fallback / what Lambda build uses

# Run the app locally (FastAPI dev server)
uvicorn main:app --reload --port 8000

# Run tests
pytest tests/

# One-time Google OAuth bootstrap (writes refresh token to SSM)
python auth_setup.py

# Invoke the webhook Lambda locally with the canned API Gateway event
sam build && sam local invoke FitSyncFunction -e events/webhook_workout_created.json

# Invoke the debrief Lambda locally
sam build && sam local invoke DebriefFunction -e events/scheduled.json

# Deploy (params come from samconfig.toml or --guided)
sam build && sam deploy
```

A push to `main` triggers [.github/workflows/deploy.yml](.github/workflows/deploy.yml), which runs `sam build && sam deploy` against region `ap-south-2`.

## Architecture

Two Lambda functions, both backed by the same codebase:

- **`FitSyncFunction`** (`main.handler`) — FastAPI app wrapped with Mangum. API Gateway catch-all `/{proxy+}` routes all HTTP traffic here.
- **`DebriefFunction`** (`debrief.handler`) — Plain Lambda handler, invoked weekly by a CloudWatch scheduled rule (Friday 15:30 UTC).

### Routes (FitSyncFunction)

- `GET /` — health check ([main.py:196](main.py#L196))
- `POST /webhook` — Hevy webhook, drives the Hevy → Google Health → Slack flow ([main.py:158](main.py#L158))
- `POST /messages` — Slack Events API, handles `url_verification` handshake and `app_mention` events with a fitness agent ([main.py:21](main.py#L21))

### Hevy → Google Health → Slack pipeline

`POST /webhook` receives `{"workoutId": "..."}` from Hevy and returns 200 immediately; processing runs in a FastAPI background task.

1. [clients/hevy.py: fetch_workout](clients/hevy.py) calls `GET https://api.hevyapp.com/v1/workouts/{id}` with the `api-key` header.
2. [clients/google_health.py: log_workout_to_google_health](clients/google_health.py) refreshes the Google OAuth token via SSM, then POSTs a `WORKOUT` exercise data point to `https://health.googleapis.com/v4/users/me/dataTypes/exercise/dataPoints`.
3. [clients/slack.py: post_workout_to_slack](clients/slack.py) posts a Block Kit summary. Slack failures are logged but **do not fail the webhook** — the Google Health write is the contract.

Duplicate webhooks are suppressed by a DynamoDB conditional write (TTL 24 h). See `DEDUP_TABLE_NAME`.

### Slack fitness agent

`POST /messages` handles `app_mention` events. When the bot is @-mentioned:

1. Strips the mention text, fetches thread history via [clients/slack.py: get_thread_messages](clients/slack.py).
2. Reads the fitness goal from SSM (`GOAL_SSM_PARAMETER_NAME`), fetches up to 5 recent workouts from Hevy, 7-day biometrics from Google Health, and active memories from DynamoDB.
3. Calls [clients/claude.py: fitness_agent](clients/claude.py) with `claude-haiku-4-5-20251001`. The agent may call `save_memory` / `delete_memory` tools before replying.
4. Posts the reply back into the Slack thread.

Slack retries (identified by `X-Slack-Retry-Num` header) are ignored to avoid duplicate replies.

### Weekly debrief

`DebriefFunction` runs every Friday at 15:30 UTC. It:

1. Reads the fitness goal from SSM.
2. Fetches the 10 most recent workouts, 7-day biometrics, and active memories.
3. Calls [clients/claude.py: weekly_debrief](clients/claude.py) with `claude-sonnet-4-6`.
4. Posts the formatted debrief to Slack via [clients/slack.py: post_debrief_to_slack](clients/slack.py).

### Token storage

The Google OAuth refresh token lives in AWS SSM Parameter Store as a `SecureString` under `SSM_PARAMETER_NAME` (default `/fitsync/google_health_refresh_token`). [clients/google_health.py: refresh_google_token](clients/google_health.py) reads it on every invocation and, **if Google rotates the refresh token, writes the new one back to SSM**. The Lambda's IAM policy in [template.yaml](template.yaml) grants `ssm:GetParameter` *and* `ssm:PutParameter` on that parameter — both are required.

The scopes requested in [auth_setup.py](auth_setup.py) are the granular Google Health scopes (`.writeonly` + `.readonly`). If you change scopes, the existing refresh token in SSM becomes invalid and `python auth_setup.py` must be re-run.

### DynamoDB tables

Two tables, both provisioned by [template.yaml](template.yaml) in PAY_PER_REQUEST mode:

- **DeduplicationTable** (`DEDUP_TABLE_NAME`) — prevents reprocessing the same Hevy webhook. Items have a `ttl` field (24 h); DynamoDB TTL is enabled.
- **AgentMemoryTable** (`AGENT_MEMORY_TABLE_NAME`) — stores agent memories as `{id, fact, created_at, active}` items. Soft-deleted via `active=False`. Managed by [core/memory.py](core/memory.py).

### Configuration surface

Runtime config comes from environment variables injected by the SAM template: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SSM_PARAMETER_NAME`, `HEVY_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_CHANNEL`, `ANTHROPIC_API_KEY`, `GOAL_SSM_PARAMETER_NAME`, `DEDUP_TABLE_NAME`, `AGENT_MEMORY_TABLE_NAME`.

All env vars are loaded in [core/config.py](core/config.py) via `python-dotenv` (reads `.env` locally). When adding a new env var, wire it through **both** [template.yaml](template.yaml) `Environment.Variables` and the `parameter-overrides` block in [.github/workflows/deploy.yml](.github/workflows/deploy.yml).

### Python version note

[pyproject.toml](pyproject.toml) and [template.yaml](template.yaml) target Python **3.14**.

## Project layout

```
clients/          external API clients (Hevy, Google Health, Slack, Claude)
core/             app internals
  config.py       env var loading
  memory.py       DynamoDB agent-memory CRUD
  models.py       Pydantic models (SlackEvent)
events/           canned API Gateway events for sam local invoke
tests/            pytest test suite
main.py           FastAPI app + FitSyncFunction Lambda handler
debrief.py        DebriefFunction Lambda handler (weekly schedule)
auth_setup.py     one-time Google OAuth bootstrap
template.yaml     AWS SAM CloudFormation template
```

## Logging

All logs are single-line JSON keyed by an `event` field (e.g. `webhook.received`, `hevy.fetch_started`, `sync.success`, `slack.post_error`). Preserve this format when adding logging — CloudWatch queries depend on it.

## Gotchas

- [samconfig.toml](samconfig.toml) currently contains real secrets in `parameter_overrides`. Do not commit edits that leak more; prefer the GitHub Actions workflow secrets path for new credentials.
- API Gateway uses `/{proxy+}` with `Method: ANY`, so any new FastAPI route is exposed automatically — no template change needed for new endpoints.
- `clients/claude.py` imports `core.memory` inside the `fitness_agent` function body (not at module level) to avoid a circular import at load time.
