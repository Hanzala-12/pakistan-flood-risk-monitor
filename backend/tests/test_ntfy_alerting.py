"""app/alerting/ntfy.py — no live network calls, requests.post is
monkeypatched, same pattern as the other ingestion provider tests."""
from dataclasses import dataclass
from unittest.mock import patch

from app.alerting.ntfy import maybe_send_severe_alert


@dataclass
class FakeSettings:
    ntfy_enabled: bool = True
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str | None = "test-topic"


@dataclass
class FakeDistrict:
    id: str = "sukkur"
    name: str = "Sukkur"
    province: str = "Sindh"


def test_no_call_when_disabled():
    with patch("app.alerting.ntfy.get_settings", return_value=FakeSettings(ntfy_enabled=False)):
        with patch("app.alerting.ntfy.requests.post") as mock_post:
            maybe_send_severe_alert(FakeDistrict(), "High", "Severe", 0.8)
    mock_post.assert_not_called()


def test_no_call_when_no_topic_configured():
    with patch("app.alerting.ntfy.get_settings", return_value=FakeSettings(ntfy_topic=None)):
        with patch("app.alerting.ntfy.requests.post") as mock_post:
            maybe_send_severe_alert(FakeDistrict(), "High", "Severe", 0.8)
    mock_post.assert_not_called()


def test_no_call_when_new_level_is_not_severe():
    with patch("app.alerting.ntfy.get_settings", return_value=FakeSettings()):
        with patch("app.alerting.ntfy.requests.post") as mock_post:
            maybe_send_severe_alert(FakeDistrict(), "Moderate", "High", 0.6)
    mock_post.assert_not_called()


def test_no_call_when_already_severe_last_time():
    # The whole point: don't re-notify every single refresh it stays Severe.
    with patch("app.alerting.ntfy.get_settings", return_value=FakeSettings()):
        with patch("app.alerting.ntfy.requests.post") as mock_post:
            maybe_send_severe_alert(FakeDistrict(), "Severe", "Severe", 0.9)
    mock_post.assert_not_called()


def test_posts_when_newly_severe():
    with patch("app.alerting.ntfy.get_settings", return_value=FakeSettings()):
        with patch("app.alerting.ntfy.requests.post") as mock_post:
            maybe_send_severe_alert(FakeDistrict(), "High", "Severe", 0.81)

    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://ntfy.sh/test-topic"
    assert b"Sukkur" in kwargs["data"]
    assert kwargs["headers"]["Priority"] == "urgent"


def test_posts_when_no_prior_data_and_first_snapshot_is_severe():
    with patch("app.alerting.ntfy.get_settings", return_value=FakeSettings()):
        with patch("app.alerting.ntfy.requests.post") as mock_post:
            maybe_send_severe_alert(FakeDistrict(), None, "Severe", 0.95)
    mock_post.assert_called_once()


def test_network_failure_does_not_raise():
    import requests
    with patch("app.alerting.ntfy.get_settings", return_value=FakeSettings()):
        with patch("app.alerting.ntfy.requests.post", side_effect=requests.RequestException("boom")):
            maybe_send_severe_alert(FakeDistrict(), "High", "Severe", 0.8)  # should not raise
