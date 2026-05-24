import os
import json
from datetime import datetime, timezone, timedelta
import boto3
import requests

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
SSM_PARAMETER_NAME = os.environ.get("SSM_PARAMETER_NAME", "/fitsync/google_health_refresh_token")

def get_refresh_token_from_ssm():
    """Retrieve the secure refresh token from AWS SSM Parameter Store."""
    print(f"Retrieving refresh token from SSM parameter: {SSM_PARAMETER_NAME}")
    ssm = boto3.client('ssm')
    response = ssm.get_parameter(
        Name=SSM_PARAMETER_NAME,
        WithDecryption=True
    )
    return response['Parameter']['Value']

def save_refresh_token_to_ssm(new_refresh_token):
    """Save the newly generated refresh token back to SSM."""
    print(f"Saving new refresh token to SSM parameter: {SSM_PARAMETER_NAME}")
    ssm = boto3.client('ssm')
    ssm.put_parameter(
        Name=SSM_PARAMETER_NAME,
        Description='Google Health API Refresh Token for fitsync',
        Value=new_refresh_token,
        Type='SecureString',
        Overwrite=True
    )

def refresh_google_token():
    """Exchange the current refresh token for a new access token (and optionally a new refresh token)."""
    refresh_token = get_refresh_token_from_ssm()
    
    token_url = "https://oauth2.googleapis.com/token"
    
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    
    print("Refreshing Google token...")
    response = requests.post(token_url, data=data)
    
    if response.status_code != 200:
        raise Exception(f"Failed to refresh token: {response.text}")
        
    token_data = response.json()
    access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token")
    
    # Google doesn't always return a new refresh token on refresh.
    # If they do, we update our stored token.
    if new_refresh_token:
        save_refresh_token_to_ssm(new_refresh_token)
    
    return access_token

def log_workout_to_google_health(hevy_workout):
    """Parses the Hevy workout data and posts it to the Google Health API."""
    try:
        access_token = refresh_google_token()
    except Exception as e:
        print(f"Auth Error: {e}")
        raise
    
    # Parse Hevy times
    start_time_str = hevy_workout.get("start_time")
    end_time_str = hevy_workout.get("end_time")
    duration_seconds = hevy_workout.get("duration_seconds", 0)
    title = hevy_workout.get("title", "Hevy Workout")
    
    # If end_time is not provided, calculate it from start_time and duration
    if not start_time_str:
        raise ValueError("Missing start_time in Hevy payload")
        
    try:
        start_time_str = start_time_str.replace("Z", "+00:00")
        start_dt = datetime.fromisoformat(start_time_str)
        
        if end_time_str:
            end_time_str = end_time_str.replace("Z", "+00:00")
            end_dt = datetime.fromisoformat(end_time_str)
        else:
            end_dt = start_dt + timedelta(seconds=duration_seconds)
            
        start_iso = start_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
    except Exception as e:
        print(f"Error parsing dates: {e}")
        raise ValueError("Invalid date format in Hevy payload")
    
    activity_url = "https://health.googleapis.com/v4/users/me/dataTypes/exercise/dataPoints"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Weightlifting maps best to "WORKOUT" or similar in Google Health API v4
    # The string literals are standard, "WORKOUT" is a safe fallback for general lifting/gym.
    data = {
        "exercise": {
            "interval": {
                "startTime": start_iso,
                "endTime": end_iso
            },
            "exerciseType": "WORKOUT",
            "displayName": title,
            "activeDuration": f"{duration_seconds}s"
        }
    }
    
    print(f"Logging activity to Google Health: {json.dumps(data)}")
    response = requests.post(activity_url, headers=headers, json=data)
    
    if response.status_code not in (200, 201):
        raise Exception(f"Failed to log activity: {response.status_code} - {response.text}")
        
    print("Successfully logged workout to Google Health.")
    return response.json()
