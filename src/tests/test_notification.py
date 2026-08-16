from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from topology_syslog.models import Incident
from topology_syslog.notification.slack import SlackNotifier, _build_payload
from topology_syslog.notification.webhook import WebhookNotifier


def _inc() -> Incident:
    return Incident(
        incident_id="INC-20260816-001",
        created_at=datetime(2026, 8, 16, 10, 0, 0, tzinfo=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="%LINK-3-UPDOWN: Interface GE0/0 down",
        secondary_nodes=["Dist-Switch1", "Access-SW1"],
        raw_log_count=3,
    )


def _mock_ok_response() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    return resp


# ---- WebhookNotifier ---------------------------------------------

def test_webhook_sends_correct_payload():
    with patch("httpx.post", return_value=_mock_ok_response()) as mock_post:
        WebhookNotifier("http://example.com/notify").send(_inc())

    payload = mock_post.call_args.kwargs["json"]
    assert payload["incident_id"] == "INC-20260816-001"
    assert payload["root_cause"] == "Core-Router1"
    assert payload["secondary_affected_count"] == 2
    assert payload["secondary_nodes"] == ["Dist-Switch1", "Access-SW1"]
    assert payload["raw_log_count"] == 3
    assert payload["created_at"].startswith("2026-08-16T10:00:00")


def test_webhook_posts_to_correct_url():
    with patch("httpx.post", return_value=_mock_ok_response()) as mock_post:
        WebhookNotifier("http://webhook.test/hook").send(_inc())

    assert mock_post.call_args.args[0] == "http://webhook.test/hook"


def test_webhook_sends_custom_headers():
    with patch("httpx.post", return_value=_mock_ok_response()) as mock_post:
        WebhookNotifier(
            "http://example.com/notify",
            headers={"X-Token": "secret"},
        ).send(_inc())

    assert mock_post.call_args.kwargs["headers"]["X-Token"] == "secret"


def test_webhook_propagates_http_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("HTTP 500")
    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(Exception, match="HTTP 500"):
            WebhookNotifier("http://example.com/notify").send(_inc())


# ---- SlackNotifier -----------------------------------------------

def test_slack_sends_block_kit_payload():
    with patch("httpx.post", return_value=_mock_ok_response()) as mock_post:
        SlackNotifier("https://hooks.slack.com/T000/B000/xxx").send(_inc())

    payload = mock_post.call_args.kwargs["json"]
    assert "blocks" in payload
    assert len(payload["blocks"]) >= 2


def test_slack_header_block_contains_incident_id():
    payload = _build_payload(_inc())
    header_text = payload["blocks"][0]["text"]["text"]
    assert "INC-20260816-001" in header_text


def test_slack_section_contains_root_cause():
    payload = _build_payload(_inc())
    fields_text = str(payload["blocks"][1]["fields"])
    assert "Core-Router1" in fields_text


def test_slack_propagates_http_error():
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = Exception("HTTP 403")
    with patch("httpx.post", return_value=mock_resp):
        with pytest.raises(Exception, match="HTTP 403"):
            SlackNotifier("https://hooks.slack.com/bad").send(_inc())
