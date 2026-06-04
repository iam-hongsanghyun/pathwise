"""API skeleton: health + config handshake."""

from __future__ import annotations

from fastapi.testclient import TestClient

from pathwise.api.main import app

client = TestClient(app)


def test_health() -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_config_handshake() -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schemaVersion"] == "1.0"
    assert body["server"]["solver"] == "highs"
    assert body["domains"] == []  # populated in P3
