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

# One-time Google OAuth bootstrap (writes refresh token to SSM)
python auth_setup.py

# Invoke the Lambda handler locally with the canned API Gateway event
sam build && sam local invoke FitSyncFunction -e events/webhook_workout_created.json

# Deploy (params come from samconfig.toml or --guided)
sam build && sam deploy
```

A push to `main` triggers [.github/workflows/deploy.yml](.github/workflows/deploy.yml), which runs `sam build && sam deploy` against region `ap-south-2`.

There is no test suite.

## Architecture

Single-Lambda FastAPI app wrapped with Mangum. API Gateway is configured with a `/{proxy+}` catch-all, so all routing happens inside FastAPI ([main.py](main.py)). The Lambda entrypoint is `main.handler`.

Three routes:
- `GET /` — health check ([main.py:174](main.py#L174)).
- `POST /webhook` — Hevy webhook. Drives the Hevy → Google Health → Slack flow ([main.py:88](main.py#L88)).
- `POST /messages` — Slack Events API endpoint. Handles `url_verification` handshake and `app_mention` events with a fitness agent ([main.py:20](main.py#L20)).

### Hevy → Google Health → Slack pipeline

The webhook flow ([main.py:88](main.py#L88)) receives a thin `{"workoutId": "..."}` payload from Hevy and **fetches the full workout** from Hevy's API.

1. `POST /webhook` reads `workoutId` from the body (400 if missing).
2. [clients/hevy.py: fetch_workout](clients/hevy.py) calls `GET https://api.hevyapp.com/v1/workouts/{id}` with the `api-key` header.
3. [clients/google_health.py: log_workout_to_google_health](clients/google_health.py) refreshes the Google OAuth token via SSM, then POSTs a `WORKOUT` exercise data point to `https://health.googleapis.com/v4/users/me/dataTypes/exercise/dataPoints`.
4. On success, [clients/slack.py: post_workout_to_slack](clients/slack.py) posts a Block Kit summary. Slack failures are logged but **do not fail the webhook** — the Google Health write is the contract.

All logs are single-line JSON keyed by an `event` field (e.g. `webhook.received`, `hevy.fetch_started`, `sync.success`, `slack.post_error`). Preserve this format when adding logging — CloudWatch queries depend on it.

### Token storage

The Google OAuth refresh token lives in AWS SSM Parameter Store as a `SecureString` under `SSM_PARAMETER_NAME` (default `/fitsync/google_health_refresh_token`). [clients/google_health.py: refresh_google_token](clients/google_health.py) reads it on every invocation and, **if Google rotates the refresh token, writes the new one back to SSM** ([clients/google_health.py:58](clients/google_health.py#L58)). The Lambda's IAM policy in [template.yaml](template.yaml) grants `ssm:GetParameter` *and* `ssm:PutParameter` scoped to that single parameter — both are required.

The scopes requested in [auth_setup.py](auth_setup.py) are the granular Google Health scopes (`.writeonly` + `.readonly`). If you change scopes, the existing refresh token in SSM becomes invalid and `python auth_setup.py` must be re-run.

### Configuration surface

Runtime config is environment variables, injected by the SAM template from stack parameters: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SSM_PARAMETER_NAME`, `HEVY_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_CHANNEL`, `ANTHROPIC_API_KEY`, `GOAL_SSM_PARAMETER_NAME`. Locally, [clients/slack.py](clients/slack.py) and [auth_setup.py](auth_setup.py) load `.env` via `python-dotenv`; the other modules read `os.environ` directly. When adding a new env var, wire it through **both** [template.yaml](template.yaml) `Environment.Variables` and the `parameter-overrides` block in [.github/workflows/deploy.yml](.github/workflows/deploy.yml).

### Python version note

[pyproject.toml](pyproject.toml) and [template.yaml](template.yaml) target Python **3.14**.

## Gotchas

- [samconfig.toml](samconfig.toml) currently contains real secrets in `parameter_overrides`. Do not commit edits that leak more, and prefer the GitHub Actions workflow secrets path for new credentials.
- API Gateway uses `/{proxy+}` with `Method: ANY`, so any new FastAPI route is exposed automatically — no template change needed for new endpoints.
- The `/messages` endpoint handles `url_verification` handshakes and `app_mention` events, calling the fitness agent to answer training questions. It ignores Slack retries (identified by `X-Slack-Retry-Num` header) to avoid duplicate replies.
