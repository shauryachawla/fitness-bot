# FitSync

A personal fitness assistant that connects [Hevy](https://www.hevyapp.com/), Google Health, Slack, and Claude AI.

## Features

- **Workout sync** — when Hevy fires a `workout_created` webhook, FitSync logs the workout to Google Health and posts a summary to Slack.
- **Slack agent** — @-mention the bot in Slack to ask training questions. The agent answers using your real workout and biometric data, and can remember ongoing conditions (injury, illness, travel).
- **Weekly debrief** — every Friday, Claude generates a structured coaching debrief from your workouts and biometrics and posts it to Slack.

## How it works

```
Hevy webhook  →  POST /webhook  →  Google Health + Slack summary
Slack mention →  POST /messages →  Claude agent  →  Slack reply
CloudWatch    →  DebriefFunction →  Claude debrief → Slack post
```

## Project structure

| Path | Description |
|---|---|
| [main.py](main.py) | FastAPI app — `POST /webhook`, `POST /messages`, `GET /` health check. Wrapped with Mangum for Lambda. |
| [debrief.py](debrief.py) | Weekly debrief Lambda handler, triggered by CloudWatch schedule (Friday 15:30 UTC). |
| [clients/google_health.py](clients/google_health.py) | Token refresh from SSM, Google Health API v4 calls, biometrics fetching. |
| [clients/hevy.py](clients/hevy.py) | Hevy API client — fetch workout by ID, list recent workouts. |
| [clients/slack.py](clients/slack.py) | Slack API client — post workout summaries, debrief, agent replies. |
| [clients/claude.py](clients/claude.py) | Anthropic client — `fitness_agent()` (Haiku) and `weekly_debrief()` (Sonnet). |
| [core/config.py](core/config.py) | Environment variable loading. |
| [core/memory.py](core/memory.py) | DynamoDB CRUD for agent memories. |
| [core/models.py](core/models.py) | Pydantic models (`SlackEvent`). |
| [auth_setup.py](auth_setup.py) | One-time local OAuth flow to obtain and store the Google refresh token in SSM. |
| [template.yaml](template.yaml) | AWS SAM template — two Lambda functions, two DynamoDB tables, API Gateway. |

## Prerequisites

- Python >= 3.14
- AWS credentials configured locally (`~/.aws/credentials` or environment variables)
- A Google Cloud project with the **Google Health API** enabled and an OAuth 2.0 **Web application** client created
- A Slack app with `chat:write` and `channels:history` bot scopes, subscribed to `app_mention` events

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | — | OAuth 2.0 client ID from Google Cloud |
| `GOOGLE_CLIENT_SECRET` | Yes | — | OAuth 2.0 client secret |
| `SSM_PARAMETER_NAME` | No | `/fitsync/google_health_refresh_token` | SSM parameter for the Google Health refresh token |
| `HEVY_API_KEY` | Yes | — | Hevy API key (requires Hevy Pro for list endpoint) |
| `SLACK_BOT_TOKEN` | Yes | — | Slack bot token (`xoxb-...`) |
| `SLACK_CHANNEL` | Yes | — | Slack channel ID for workout summaries and debrief |
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for Claude |
| `GOAL_SSM_PARAMETER_NAME` | No | `/fitsync/goal` | SSM parameter storing the current fitness goal |
| `DEDUP_TABLE_NAME` | No | — | DynamoDB table for webhook deduplication (set by SAM) |
| `AGENT_MEMORY_TABLE_NAME` | No | — | DynamoDB table for agent memories (set by SAM) |

Create a `.env` file in the project root for local development:

```env
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
SSM_PARAMETER_NAME=/fitsync/google_health_refresh_token
HEVY_API_KEY=your-hevy-api-key
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_CHANNEL=C123456789
ANTHROPIC_API_KEY=sk-ant-your-api-key
GOAL_SSM_PARAMETER_NAME=/fitsync/goal
```

## Setup (one-time)

### 1. Configure the Google OAuth client

In the Google Cloud Console, add the following to **Authorized redirect URIs** for your OAuth client:

```
http://127.0.0.1:8082/callback
```

### 2. Obtain and store the refresh token

```bash
pip install -r requirements.txt
python auth_setup.py
```

Open the printed URL in a browser, complete the Google consent screen, and the script stores the refresh token as a `SecureString` in AWS SSM. Your AWS user needs `ssm:PutParameter` permission.

## Running locally

```bash
uvicorn main:app --reload --port 8000
```

Trigger a webhook manually (Hevy sends just the workout ID; the app fetches the full workout):

```bash
curl -X POST http://127.0.0.1:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"workoutId":"your-hevy-workout-id"}'
```

Or use the canned API Gateway event with SAM:

```bash
sam build && sam local invoke FitSyncFunction -e events/webhook_workout_created.json
sam build && sam local invoke DebriefFunction -e events/scheduled.json
```

## Running tests

```bash
pytest tests/
```

## Deployment (AWS Lambda)

```bash
sam build
sam deploy --guided
```

SAM prompts for stack parameters on first deploy; subsequent deploys use `samconfig.toml`. The deployed API Gateway URL is printed in the stack outputs.

**Deployed resources:**
- `FitSyncFunction` — Python 3.14, 30 s timeout, API Gateway `/{proxy+}` catch-all
- `DebriefFunction` — Python 3.14, 60 s timeout, CloudWatch schedule (Friday 15:30 UTC)
- `DeduplicationTable` — DynamoDB, deduplicates Hevy webhooks (24 h TTL)
- `AgentMemoryTable` — DynamoDB, stores agent memories

## Webhook payload

Hevy sends a minimal payload containing only the workout ID:

```json
{"workoutId": "abc123"}
```

The app fetches the full workout from the Hevy API using this ID.
