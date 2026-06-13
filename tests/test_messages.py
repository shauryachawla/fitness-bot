"""Tests for the /messages endpoint agent flow."""
import json
import os
import sys
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch external deps before importing main so module-level clients don't fail
with patch("anthropic.Anthropic"), patch("boto3.client"):
    from main import app

client = TestClient(app, raise_server_exceptions=False)


# --- url_verification ---

def test_url_verification():
    resp = client.post("/messages", json={
        "type": "url_verification",
        "challenge": "test_challenge_abc",
    })
    assert resp.status_code == 200
    assert resp.text == "test_challenge_abc"
    print("PASS  url_verification")


# --- retry short-circuit ---

def test_retry_ignored():
    resp = client.post(
        "/messages",
        json={"type": "event_callback", "event": {"type": "app_mention", "text": "<@UBOT> hi"}},
        headers={"X-Slack-Retry-Num": "1"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    print("PASS  retry_ignored")


# --- app_mention happy path ---

def test_app_mention_replies_in_thread():
    ssm_mock = MagicMock()
    ssm_mock.get_parameter.return_value = {"Parameter": {"Value": "get jacked"}}

    with patch("main.boto3.client", return_value=ssm_mock), \
         patch("main.list_recent_workouts", return_value=[{"title": "Chest Day"}]), \
         patch("main.fetch_biometrics", return_value={"weight": [], "resting_heart_rate": [], "hrv": [], "sleep": []}), \
         patch("main.fitness_agent", return_value="You had a solid chest day.") as mock_agent, \
         patch("main.get_thread_messages", return_value=[]), \
         patch("main.post_agent_reply") as mock_reply:

        resp = client.post("/messages", json={
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@UBOT123> how was my last workout?",
                "channel": "C123",
                "ts": "1234567890.000001",
            },
        })

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Claude was called with the stripped question
    args = mock_agent.call_args
    assert args[0][0] == "how was my last workout?"
    assert args[0][1] == "get jacked"

    # Reply posted to correct channel + thread
    mock_reply.assert_called_once_with("You had a solid chest day.", "C123", "1234567890.000001")
    print("PASS  app_mention_replies_in_thread")


# --- mention text stripping ---

def test_mention_text_stripped():
    ssm_mock = MagicMock()
    ssm_mock.get_parameter.return_value = {"Parameter": {"Value": "goal"}}

    with patch("main.boto3.client", return_value=ssm_mock), \
         patch("main.list_recent_workouts", return_value=[]), \
         patch("main.fetch_biometrics", return_value={}), \
         patch("main.fitness_agent", return_value="ok") as mock_agent, \
         patch("main.get_thread_messages", return_value=[]), \
         patch("main.post_agent_reply"):

        client.post("/messages", json={
            "type": "event_callback",
            "event": {
                "type": "app_mention",
                "text": "<@UABC> <@UDEF>   should I rest today?",
                "channel": "C1",
                "ts": "1.0",
            },
        })

    question = mock_agent.call_args[0][0]
    assert question == "should I rest today?", f"got: {repr(question)}"
    print("PASS  mention_text_stripped")


# --- Claude error falls back gracefully ---

def test_claude_error_posts_fallback():
    ssm_mock = MagicMock()
    ssm_mock.get_parameter.return_value = {"Parameter": {"Value": "goal"}}

    with patch("main.boto3.client", return_value=ssm_mock), \
         patch("main.list_recent_workouts", return_value=[]), \
         patch("main.fetch_biometrics", return_value={}), \
         patch("main.fitness_agent", side_effect=Exception("claude down")), \
         patch("main.get_thread_messages", return_value=[]), \
         patch("main.post_agent_reply") as mock_reply:

        resp = client.post("/messages", json={
            "type": "event_callback",
            "event": {"type": "app_mention", "text": "<@UBOT> hi", "channel": "C1", "ts": "1.0"},
        })

    assert resp.status_code == 200
    reply_text = mock_reply.call_args[0][0]
    assert "error" in reply_text.lower()
    print("PASS  claude_error_fallback")


# --- non-mention event is a no-op ---

def test_non_mention_event_ignored():
    with patch("main.get_thread_messages", return_value=[]), \
         patch("main.post_agent_reply") as mock_reply:
        resp = client.post("/messages", json={
            "type": "event_callback",
            "event": {"type": "message", "text": "hello", "channel": "C1", "ts": "1.0"},
        })

    assert resp.status_code == 200
    mock_reply.assert_not_called()
    print("PASS  non_mention_ignored")


if __name__ == "__main__":
    test_url_verification()
    test_retry_ignored()
    test_app_mention_replies_in_thread()
    test_mention_text_stripped()
    test_claude_error_posts_fallback()
    test_non_mention_event_ignored()
    print("\nAll tests passed.")
