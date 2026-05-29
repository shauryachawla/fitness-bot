# FitSync

Syncs workouts from [Hevy](https://www.hevyapp.com/) to Google Health via webhook. When Hevy fires a `workout_created` event, FitSync logs the workout as an exercise data point in the Google Health API.

## How it works

```
Hevy → POST /webhook → FastAPI → Google Health API v4
```

1. Hevy sends a `workout_created` webhook to the `/webhook` endpoint.
2. The app extracts the workout's `start_time`, `end_time`/`duration_seconds`, and `title`.
3. It fetches a Google OAuth refresh token from AWS SSM Parameter Store, exchanges it for an access token, and posts the workout as a `WORKOUT` exercise data point to Google Health.
4. If Google returns a rotated refresh token, it is saved back to SSM automatically.

## Project structure

| File | Description |
|---|---|
| [main.py](main.py) | FastAPI app — `POST /webhook` handler, `POST /messages` (Slack), + `GET /` health check. Wrapped with Mangum for Lambda. |
| [clients/google_health.py](clients/google_health.py) | Token refresh from SSM, Google Health API v4 calls, biometrics fetching. |
| [clients/hevy.py](clients/hevy.py) | Hevy API client for fetching workouts and listing recent workouts. |
| [clients/slack.py](clients/slack.py) | Slack API client for posting messages and formatted workout summaries. |
| [clients/claude.py](clients/claude.py) | Anthropic client for fitness agent and weekly debrief. |
| [models.py](models.py) | Pydantic models (e.g., `SlackEvent`). |
| [config.py](config.py) | Environment variable configuration. |
| [auth_setup.py](auth_setup.py) | One-time local OAuth flow to obtain and store the refresh token in SSM. |
| [template.yaml](template.yaml) | AWS SAM template — deploys a Python 3.14 Lambda behind API Gateway. |

## Prerequisites

- Python >= 3.14
- AWS credentials configured locally (`~/.aws/credentials` or environment variables)
- A Google Cloud project with the **Google Health API** enabled and an OAuth 2.0 **Web application** client created

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GOOGLE_CLIENT_ID` | Yes | — | OAuth 2.0 client ID from Google Cloud |
| `GOOGLE_CLIENT_SECRET` | Yes | — | OAuth 2.0 client secret |
| `SSM_PARAMETER_NAME` | No | `/fitsync/google_health_refresh_token` | SSM parameter name for the Google Health refresh token |
| `HEVY_API_KEY` | Yes | — | Hevy API key for fetching workout data |
| `SLACK_BOT_TOKEN` | Yes | — | Slack bot token for posting messages |
| `SLACK_CHANNEL` | Yes | — | Slack channel ID for posting workouts and debrief |
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic API key for Claude |
| `GOAL_SSM_PARAMETER_NAME` | No | `/fitsync/goal` | SSM parameter name for the fitness goal |

Create a `.env` file in the project root:

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

The required OAuth scope is `https://www.googleapis.com/auth/googlehealth.activity_and_fitness`.

### 2. Obtain and store the refresh token

```bash
pip install -r requirements.txt
python auth_setup.py
```

Open the printed URL in a browser, complete the Google consent screen, and the script will store the refresh token as a `SecureString` in AWS SSM. Your AWS user needs `ssm:PutParameter` permission.

## Running locally

```bash
uvicorn main:app --reload --port 8000
```

Test with a sample webhook (note: Hevy sends just the `workoutId`, and the app fetches the full workout):

```bash
curl -X POST http://127.0.0.1:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"workoutId":"your-hevy-workout-id"}'
```

Or use the canned event with SAM:

```bash
sam build && sam local invoke FitSyncFunction -e events/webhook_workout_created.json
```

The app also exposes `GET /` as a health check that returns `{"status": "ok"}`.

## Deployment (AWS Lambda)

The app uses [Mangum](https://mangum.io/) to wrap FastAPI for Lambda and includes an AWS SAM template.

```bash
sam build
sam deploy --guided
```

SAM will prompt for `GoogleClientId`, `GoogleClientSecret`, and `SsmParameterName`. The Lambda function is granted `ssm:GetParameter` and `ssm:PutParameter` on the configured SSM parameter. The deployed API Gateway URL is printed in the stack outputs.

**Lambda configuration (template.yaml):**
- Runtime: Python 3.14
- Timeout: 30 seconds
- Architecture: x86_64
- Handler: `main.handler`

## Webhook payload reference

FitSync ignores all event types except `workout_created`. The minimal expected shape:

```json
{
  "event_type": "workout_created",
  "workout": {
    "start_time": "2026-05-21T12:00:00Z",
    "duration_seconds": 3600,
    "title": "Gym Session"
  }
}
```

`end_time` is optional — if omitted, it is calculated from `start_time + duration_seconds`.

