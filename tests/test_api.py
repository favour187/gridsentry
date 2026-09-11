import os
os.environ['DATABASE_URL'] = 'sqlite:///./data/test_gs.db'
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
    r = client.get('/api/health')
    assert r.status_code == 200 and r.json()['status'] == 'ok'

def test_live_shape(client):
    r = client.get('/api/live')
    d = r.json()
    assert r.status_code == 200
    assert d['kpis']['total'] == 18
    assert len(d['meters']) >= 15
    for m in d['meters']:
        assert {'meter_id', 'voltage', 'kw', 'status', 'x', 'y'} <= set(m)

def test_scenario_bypass_raises_alert(client):
    r = client.post('/api/scenarios', json={'kind': 'bypass', 'meter_id': 'M-105'})
    assert r.status_code == 200
    client.post('/api/scenarios', json={'kind': 'bypass', 'meter_id': 'M-105'})
    seen = False
    for _ in range(6):
        d = client.get('/api/live').json()
        if any((a['kind'] == 'bypass' and a['meter_id'] == 'M-105' for a in d['alerts'])):
            seen = True
            break
    assert seen

def test_ingest_auth(client):
    assert client.post('/api/ingest/M-101', json={'voltage': 230, 'current': 1, 'kw': 0.8}).status_code == 401
    assert client.post('/api/ingest/NOPE', json={'voltage': 230, 'current': 1, 'kw': 0.8}, headers={'Authorization': 'Bearer x'}).status_code == 404

def test_ingest_bypass(client):
    from app.sim import token_for
    tok = token_for('M-108')
    r = client.post('/api/ingest/M-108', headers={'Authorization': f'Bearer {tok}'}, json={'voltage': 228.0, 'current': 0.02, 'kw': 0.008, 'cover_open': True})
    assert r.status_code == 200
    d = client.get('/api/live').json()
    assert any((a['kind'] == 'bypass' and a['meter_id'] == 'M-108' for a in d['alerts']))

def test_ack_resolve_cycle(client):
    d = client.get('/api/live').json()
    aid = d['alerts'][0]['id']
    assert client.post(f'/api/alerts/{aid}/ack').json()['status'] == 'ack'
    assert client.post(f'/api/alerts/{aid}/resolve').json()['status'] == 'resolved'

def test_investigate_offline_provider(client):
    from app.sim import token_for
    client.post('/api/ingest/M-103', headers={'Authorization': f"Bearer {token_for('M-103')}"}, json={'voltage': 229.0, 'current': 0.02, 'kw': 0.01, 'cover_open': True})
    d = client.get('/api/live').json()
    assert d['alerts'], 'expected at least one alert'
    aid = d['alerts'][0]['id']
    r = client.post(f'/api/investigate/{aid}').json()
    assert r['provider'] == 'offline'
    assert 'Recommended action' in r['report'] or 'action' in r

def test_stats_endpoint_shape(client):
    client.get('/api/live')
    d = client.get('/api/stats').json()
    assert {'total', 'by_status', 'by_severity', 'by_kind', 'resolution_rate_pct', 'trend_24h'} <= set(d)
    assert len(d['trend_24h']) == 24

def test_csv_export(client):
    client.get('/api/live')
    r = client.get('/api/incidents.csv')
    assert r.status_code == 200
    assert 'text/csv' in r.headers['content-type']
    assert r.text.splitlines()[0].startswith('id,kind,severity')

def test_live_carries_frequency_pf_health(client):
    d = client.get('/api/live').json()
    m = d['meters'][0]
    assert 'freq_hz' in m and 'pf' in m and ('risk' in m)
    assert 'health' in d['kpis'] and d['kpis']['grid_freq_hz'] is not None
    assert 0 <= d['kpis']['health'] <= 100

def _wait_alert(client, kind, meter=None, tries=8):
    for _ in range(tries):
        d = client.get('/api/live').json()
        for a in d['alerts']:
            if a['kind'] == kind and (meter is None or a['meter_id'] == meter or a['scope'] == meter):
                return a
    return None

def test_neutral_scenario(client):
    client.post('/api/scenarios', json={'kind': 'neutral', 'meter_id': 'M-104'})
    assert _wait_alert(client, 'neutral_tamper', 'M-104')

def test_frequency_scenario(client):
    client.post('/api/scenarios', json={'kind': 'freq', 'feeder': 'FEEDER-B'})
    assert _wait_alert(client, 'frequency')

def test_feeder_outage_scenario(client):
    client.post('/api/scenarios', json={'kind': 'outage', 'feeder': 'FEEDER-B'})
    assert _wait_alert(client, 'feeder_outage', 'FEEDER-B')

def test_overload_scenario(client):
    client.post('/api/scenarios', json={'kind': 'overload', 'meter_id': 'M-106'})
    assert _wait_alert(client, 'overload', 'TX-A2')

def test_ingest_frequency_alert(client):
    from app.sim import token_for
    r = client.post('/api/ingest/M-101', headers={'Authorization': f"Bearer {token_for('M-101')}"}, json={'voltage': 229.0, 'current': 1.2, 'kw': 0.7, 'freq_hz': 48.7, 'pf': 0.9})
    assert r.status_code == 200
    assert 'frequency' in r.json()['alerts_raised']

def test_unknown_scenario_rejected(client):
    r = client.post('/api/scenarios', json={'kind': 'frobnicate'})
    assert r.status_code == 400
