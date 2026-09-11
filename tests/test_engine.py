import datetime as dt
from app.engine import evaluate
NOW = dt.datetime(2026, 9, 11, 14, 0)

def snap(**over):
    r = {'meter_id': 'M-101', 'name': 'Test', 'feeder': 'FEEDER-A', 'transformer': 'TX-A1', 'kind': 'shop', 'voltage': 230.0, 'current': 1.0, 'kw': 0.8, 'baseline_kw': 0.8, 'reverse_events': 0, 'phase_current': [0.33, 0.33, 0.34], 'phases': [230, 230, 230], 'flags': {}}
    r.update(over)
    return [r]

def test_healthy_snapshot_raises_nothing():
    out = evaluate(snap(), ['M-101'], NOW)
    assert out == []

def test_bypass_detected():
    out = evaluate(snap(kw=0.06, flags={'cover_open': True}), ['M-101'], NOW)
    kinds = [a['kind'] for a in out]
    assert 'bypass' in kinds
    ev = next((a for a in out if a['kind'] == 'bypass'))['evidence']
    assert ev['drop_pct'] > 90 and ev['cover_open'] is True

def test_undervoltage_severities():
    warn = evaluate(snap(voltage=192.0), ['M-101'], NOW)
    crit = evaluate(snap(voltage=178.0), ['M-101'], NOW)
    assert [a['severity'] for a in warn] == ['warning']
    assert [a['severity'] for a in crit] == ['critical']

def test_overvoltage():
    out = evaluate(snap(voltage=258.0), ['M-101'], NOW)
    assert out[0]['kind'] == 'overvoltage'

def test_phase_imbalance():
    out = evaluate(snap(phase_current=[0.8, 0.1, 0.05], current=0.95), ['M-101'], NOW)
    assert any((a['kind'] == 'imbalance' for a in out))

def test_tamper_reverse_flow():
    out = evaluate(snap(reverse_events=9), ['M-101'], NOW)
    assert any((a['kind'] == 'tamper' and a['severity'] == 'critical' for a in out))

def test_offline_meter():
    out = evaluate([], ['M-101'], NOW)
    assert [a['kind'] for a in out] == ['offline']

def test_transformer_group_loss():
    s = snap(kw=0.3, baseline_kw=0.8)
    s.append(dict(s[0], meter_id='M-102', transformer='TX-A1', kw=0.4, baseline_kw=1.5))
    out = evaluate(s, ['M-101', 'M-102'], NOW)
    assert any((a['kind'] == 'tx_loss' and a['scope'] == 'TX-A1' for a in out))

def test_neutral_tamper_phase_split():
    out = evaluate(snap(phases=[262.0, 214.0, 206.0], voltage=227.3), ['M-101'], NOW)
    kinds = [a['kind'] for a in out]
    assert 'neutral_tamper' in kinds
    ev = next((a for a in out if a['kind'] == 'neutral_tamper'))['evidence']
    assert ev['voltage_split_v'] > 40

def test_neutral_healthy_phases_quiet():
    out = evaluate(snap(phases=[230.5, 229.8, 230.1]), ['M-101'], NOW)
    assert 'neutral_tamper' not in [a['kind'] for a in out]

def test_frequency_warning_and_critical():
    warn = evaluate(snap(freq_hz=50.35), ['M-101'], NOW)
    crit = evaluate(snap(freq_hz=48.9), ['M-101'], NOW)
    assert any((a['kind'] == 'frequency' and a['severity'] == 'warning' for a in warn))
    assert any((a['kind'] == 'frequency' and a['severity'] == 'critical' for a in crit))

def test_low_power_factor():
    out = evaluate(snap(pf=0.52, kw=0.7), ['M-101'], NOW)
    assert any((a['kind'] == 'low_pf' for a in out))

def test_transformer_overload():
    s = snap(kw=4.5, baseline_kw=1.9)
    s.append(dict(s[0], meter_id='M-102', name='Mill 2', kw=2.0, baseline_kw=1.5))
    out = evaluate(s, ['M-101', 'M-102'], NOW)
    ol = [a for a in out if a['kind'] == 'overload' and a['scope'] == 'TX-A1']
    assert ol and ol[0]['evidence']['loading_pct'] >= 100

def test_feeder_outage_needs_most_meters_silent():
    meta = {f'M-{i}': {'feeder': 'FEEDER-B', 'transformer': 'TX-B1'} for i in range(1, 11)}
    present = [dict(snap()[0], meter_id=f'M-{i}') for i in range(1, 4)]
    out = evaluate(present, list(meta), NOW, spec_meta=meta)
    assert any((a['kind'] == 'feeder_outage' and 'FEEDER-B' in a['title'] for a in out))

def test_no_feeder_outage_when_almost_all_reporting():
    meta = {f'M-{i}': {'feeder': 'FEEDER-B', 'transformer': 'TX-B1'} for i in range(1, 11)}
    present = [dict(snap()[0], meter_id=f'M-{i}') for i in range(1, 10)]
    out = evaluate(present, list(meta), NOW, spec_meta=meta)
    assert not any((a['kind'] == 'feeder_outage' for a in out))

def test_meter_and_fleet_risk_scoring():
    from app.engine import meter_risk, fleet_health
    alerts = evaluate(snap(kw=0.06, voltage=180.0, flags={'cover_open': True}), ['M-101'], NOW)
    r = meter_risk(alerts, 'M-101')
    assert r['score'] >= 50 and 'bypass' in r['reasons']
    assert fleet_health({'M-101': r}, 10) < 100
