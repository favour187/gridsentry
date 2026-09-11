import os
os.environ["DATABASE_URL"] = "sqlite:///./data/test_gs.db"
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Alert
@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
def test_live_shape(client):
    r = client.get("/api/live")
    d = r.json()
    assert r.status_code == 200
    assert d["kpis"]["total"] == 18
    assert len(d["meters"]) >= 15
    for m in d["meters"]:
        assert {"meter_id", "voltage", "kw", "status", "x", "y"} <= set(m)
def test_scenario_bypass_raises_alert(client):
    r = client.post("/api/scenarios", json={"kind": "bypass", "meter_id": "M-105"})
    assert r.status_code == 200
    client.post("/api/scenarios", json={"kind": "bypass", "meter_id": "M-105"})
    seen = False
    for _ in range(6):
        d = client.get("/api/live").json()
        if any(a["kind"] == "bypass" and a["meter_id"] == "M-105" for a in d["alerts"]):
            seen = True
            break
    assert seen
def test_ingest_auth(client):
    assert client.post("/api/ingest/M-101", json={"voltage": 230, "current": 1, "kw": 0.8}).status_code == 401
    assert client.post("/api/ingest/NOPE", json={"voltage": 230, "current": 1, "kw": 0.8}, headers={"Authorization": "Bearer x"}).status_code == 404
def test_ingest_bypass(client):
    from app.sim import token_for
    tok = token_for("M-108")
    r = client.post("/api/ingest/M-108", headers={"Authorization": f"Bearer {tok}"},
                    json={"voltage": 228.0, "current": 0.02, "kw": 0.008, "cover_open": True})
    assert r.status_code == 200
    d = client.get("/api/live").json()
    assert any(a["kind"] == "bypass" and a["meter_id"] == "M-108" for a in d["alerts"])
def test_ack_resolve_cycle(client):
    d = client.get("/api/live").json()
    aid = d["alerts"][0]["id"]
    assert client.post(f"/api/alerts/{aid}/ack").json()["status"] == "ack"
    assert client.post(f"/api/alerts/{aid}/resolve").json()["status"] == "resolved"
def test_investigate_offline_provider(client):
    from app.sim import token_for
    client.post("/api/ingest/M-103", headers={"Authorization": f"Bearer {token_for('M-103')}"},
                json={"voltage": 229.0, "current": 0.02, "kw": 0.01, "cover_open": True})
    d = client.get("/api/live").json()
    assert d["alerts"], "expected at least one alert"
    aid = d["alerts"][0]["id"]
    r = client.post(f"/api/investigate/{aid}").json()
    assert r["provider"] == "offline"
    assert "Recommended action" in r["report"] or "action" in r
