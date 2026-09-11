import datetime as dt
from app.engine import evaluate

NOW = dt.datetime(2026, 9, 11, 14, 0)


def snap(**over):
    r = {"meter_id": "M-101", "name": "Test", "feeder": "FEEDER-A", "transformer": "TX-A1",
         "kind": "shop", "voltage": 230.0, "current": 1.0, "kw": 0.80, "baseline_kw": 0.80,
         "reverse_events": 0, "phase_current": [0.33, 0.33, 0.34], "phases": [230, 230, 230],
         "flags": {}}
    r.update(over)
    return [r]


def test_healthy_snapshot_raises_nothing():
    out = evaluate(snap(), ["M-101"], NOW)
    assert out == []


def test_bypass_detected():
    out = evaluate(snap(kw=0.06, flags={"cover_open": True}), ["M-101"], NOW)
    kinds = [a["kind"] for a in out]
    assert "bypass" in kinds
    ev = next(a for a in out if a["kind"] == "bypass")["evidence"]
    assert ev["drop_pct"] > 90 and ev["cover_open"] is True


def test_undervoltage_severities():
    warn = evaluate(snap(voltage=192.0), ["M-101"], NOW)
    crit = evaluate(snap(voltage=178.0), ["M-101"], NOW)
    assert [a["severity"] for a in warn] == ["warning"]
    assert [a["severity"] for a in crit] == ["critical"]


def test_overvoltage():
    out = evaluate(snap(voltage=258.0), ["M-101"], NOW)
    assert out[0]["kind"] == "overvoltage"


def test_phase_imbalance():
    out = evaluate(snap(phase_current=[0.8, 0.1, 0.05], current=0.95), ["M-101"], NOW)
    assert any(a["kind"] == "imbalance" for a in out)


def test_tamper_reverse_flow():
    out = evaluate(snap(reverse_events=9), ["M-101"], NOW)
    assert any(a["kind"] == "tamper" and a["severity"] == "critical" for a in out)


def test_offline_meter():
    out = evaluate([], ["M-101"], NOW)
    assert [a["kind"] for a in out] == ["offline"]


def test_transformer_group_loss():
    s = snap(kw=0.30, baseline_kw=0.80)
    s.append(dict(s[0], meter_id="M-102", transformer="TX-A1", kw=0.4, baseline_kw=1.5))
    out = evaluate(s, ["M-101", "M-102"], NOW)
    assert any(a["kind"] == "tx_loss" and a["scope"] == "TX-A1" for a in out)
