from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from topology_syslog.api.main import create_app
from topology_syslog.models import Incident


def _incident() -> Incident:
    return Incident(
        incident_id="INC-AUTH-001",
        created_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
        root_cause_node="Core-Router1",
        primary_event="%LINK-3-UPDOWN: Interface GE0/0 down",
        status="OPEN",
    )


@pytest.fixture
def authenticated_app():
    return create_app(
        database_url="sqlite:///:memory:",
        syslog_port=0,
        auth_enabled=True,
        auth_reader_token="reader-token",
        auth_operator_token="operator-token",
        auth_admin_token="admin-token",
        cors_origins=["http://localhost:3000"],
    )


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_auth_rejects_unauthenticated_http_requests(authenticated_app):
    with TestClient(authenticated_app) as client:
        response = client.get("/incidents")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_reader_can_read_but_cannot_operate(authenticated_app):
    with TestClient(authenticated_app) as client:
        authenticated_app.state.store.save(_incident())

        assert client.get("/incidents", headers=_bearer("reader-token")).status_code == 200
        response = client.put(
            "/incidents/INC-AUTH-001/resolve", headers=_bearer("reader-token")
        )

    assert response.status_code == 401


def test_operator_can_operate_but_cannot_delete(authenticated_app):
    with TestClient(authenticated_app) as client:
        authenticated_app.state.store.save(_incident())

        resolved = client.put(
            "/incidents/INC-AUTH-001/resolve", headers=_bearer("operator-token")
        )
        deleted = client.delete(
            "/incidents?before=2026-09-04T00:00:00Z&confirm=true",
            headers=_bearer("operator-token"),
        )

    assert resolved.status_code == 200
    assert deleted.status_code == 401


def test_admin_can_delete(authenticated_app):
    with TestClient(authenticated_app) as client:
        incident = _incident()
        incident.status = "CLOSED"
        authenticated_app.state.store.save(incident)
        response = client.delete(
            "/incidents?before=2026-09-04T00:00:00Z&confirm=true",
            headers=_bearer("admin-token"),
        )

    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_websocket_requires_a_valid_reader_token(authenticated_app):
    with TestClient(authenticated_app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/ws/incidents"):
                pass

        with client.websocket_connect("/ws/incidents?access_token=reader-token") as ws:
            assert ws is not None


def test_auth_enabled_requires_token_and_explicit_cors_origin():
    with pytest.raises(ValueError, match="requires at least one"):
        create_app(database_url="sqlite:///:memory:", auth_enabled=True)

    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        create_app(
            database_url="sqlite:///:memory:",
            auth_enabled=True,
            auth_admin_token="admin-token",
        )