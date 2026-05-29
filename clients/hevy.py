import requests

from config import HEVY_API_KEY

HEVY_API_BASE_URL = "https://api.hevyapp.com/v1"


def fetch_workout(workout_id: str) -> dict:
    """Fetch full workout details from the Hevy API by workout ID."""
    if not HEVY_API_KEY:
        raise ValueError("HEVY_API_KEY environment variable is not set")

    url = f"{HEVY_API_BASE_URL}/workouts/{workout_id}"
    headers = {
        "api-key": HEVY_API_KEY,
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 404:
        raise ValueError(f"Workout not found: {workout_id}")
    if response.status_code != 200:
        raise Exception(
            f"Hevy API error fetching workout {workout_id}: "
            f"{response.status_code} - {response.text}"
        )

    return response.json()


def list_recent_workouts(limit: int = 10) -> list[dict]:
    """Fetch the user's most recent workouts. Requires Hevy Pro."""
    if not HEVY_API_KEY:
        raise ValueError("HEVY_API_KEY environment variable is not set")

    url = f"{HEVY_API_BASE_URL}/workouts"
    headers = {
        "api-key": HEVY_API_KEY,
        "Accept": "application/json",
    }
    params = {"page": 1, "pageSize": limit}

    response = requests.get(url, headers=headers, params=params)

    if response.status_code != 200:
        raise Exception(
            f"Hevy API error listing workouts: "
            f"{response.status_code} - {response.text}"
        )

    body = response.json()
    workouts = body.get("workouts") if isinstance(body, dict) else body
    if not isinstance(workouts, list):
        return []
    return workouts[:limit]
